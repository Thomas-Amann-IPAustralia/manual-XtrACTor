"""The compiled document, read once, as an ordered stream of styled blocks.

This is the module the whole pipeline's determinism rests on, so it is worth
being explicit about what it deliberately does *not* do.

The obvious way to get text out of a `.docx` is Mammoth to HTML and then a
readability extractor. That is what the reference implementation in the FRL
guide does, and for its purpose — a plain-text body to diff — it is the right
call. It is the wrong call here, because it throws away the one thing that
makes this corpus tractable: the Office of Parliamentary Counsel drafts to a
fixed stylesheet, and every structural fact about the law is carried in a
`w:pStyle` name. `ActHead2` is a Part. `ActHead5` is a section. `paragraph` is
a paragraph (a), `paragraphsub` a subparagraph (i). Flattening to HTML turns
all of that into indented `<p>` elements and leaves you inferring the hierarchy
back out of leading tabs and bracket shapes — which is guessing, and rule 1
forbids it.

So: `zipfile` and `ElementTree`, no dependency added, and the style name is
carried through to the output record verbatim. `SOURCE_NOTES.md` makes the
same argument about HTML-to-markdown libraries dropping the AustLII hrefs the
Manual's citation layer depends on. Same trap, different file format.

One reading, like `page.flatten_spans`: the text and the emphasis offsets come
out of a single walk, so a run's span cannot come to disagree with the text it
is a span of.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from typing import Iterator
from xml.etree import ElementTree

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

_P = f"{W}p"
_R = f"{W}r"
_T = f"{W}t"
_TAB = f"{W}tab"
_BR = f"{W}br"
_TBL = f"{W}tbl"
_TR = f"{W}tr"
_TC = f"{W}tc"
_PPR = f"{W}pPr"
_RPR = f"{W}rPr"
_PSTYLE = f"{W}pStyle"
_VAL = f"{W}val"
_GRIDSPAN = f"{W}gridSpan"
_VMERGE = f"{W}vMerge"
_TCPR = f"{W}tcPr"


class DocumentShapeError(Exception):
    """The `.docx` is not the shape this module knows how to read.

    Raised rather than worked around. A compiled instrument that has no
    document body, or a zip with no `word/document.xml`, is not a document with
    a quirk in it — it is evidence that either the download is broken or the
    Register has changed what it serves, and both need a person.
    """


@dataclass(frozen=True)
class Span:
    """A stretch of `Block.text` that the drafter set in bold, italic or both.

    Recorded rather than interpreted, for the same reason `links.py` records an
    anchor's offsets rather than deciding what the anchor meant. Two things
    ride on it, and neither is asserted here:

    - In a `Definition` block the leading bold-italic run is the term being
      defined. That is the OPC drafting convention, and it is how a defined-
      terms vocabulary gets built downstream without a model.
    - Legislation italicises the names of other instruments, so an italic span
      is where a citation layer should look for 'the *Customs Act 1901*'.

    `text[start:end] == span.text`, checked in `validate`, because an offset
    drifted by one underlines the wrong words while staying well-formed.
    """

    text: str
    start: int
    end: int
    weight: str  # 'bold' | 'italic' | 'bold-italic'


@dataclass(frozen=True)
class Block:
    """One paragraph, or one table, in document order.

    `text` keeps its tabs. The OPC stylesheet uses a tab to separate a
    provision's label from its words — `'\\t(3)\\tThis subsection applies…'` —
    so the tab is structural, and normalising it away here would mean parsing
    the label back out of a bracket shape later. `normalise()` is what the
    record gets; this is what the parser reads.
    """

    style: str | None
    text: str
    spans: tuple[Span, ...] = ()
    table: tuple[tuple[str, ...], ...] | None = None
    grid: tuple[tuple[dict, ...], ...] | None = None

    @property
    def is_table(self) -> bool:
        return self.table is not None

    def normalised(self) -> str:
        """The words, whitespace collapsed. What reaches the snapshot.

        `str.split()` treats the non-breaking space the OPC template puts in
        'Part\\xa01' as whitespace, so this collapses it too — the same
        treatment `tmm_snapshot.page.flatten_text` gives the Manual's markup,
        and the reason a heading reads 'Part 1' in both corpora.
        """
        return " ".join(self.text.split())


def read_document(data: bytes) -> tuple[Block, ...]:
    """Every paragraph and table of the document body, in order.

    Headers, footers and footnotes are separate parts of the package and are
    not read: they carry the compilation's page furniture, not its law.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise DocumentShapeError(f"not a readable .docx: {error}") from error

    try:
        xml = archive.read("word/document.xml")
    except KeyError as error:
        raise DocumentShapeError(
            "the .docx has no word/document.xml — it is not a Word document, "
            "or the download was truncated"
        ) from error

    root = ElementTree.fromstring(xml)
    body = root.find(f"{W}body")
    if body is None:
        raise DocumentShapeError("the .docx has no <w:body>")

    blocks = tuple(_blocks(body))
    if not blocks:
        raise DocumentShapeError("the .docx body holds no paragraphs")
    return blocks


def _blocks(body: ElementTree.Element) -> Iterator[Block]:
    """Top-level children only.

    A table's own paragraphs are reached through `_table`, not here, so a cell
    is never also emitted as a loose paragraph. `iter()` would do exactly that
    and the duplication would be invisible until a total came out double.
    """
    for element in body:
        if element.tag == _P:
            yield _paragraph(element)
        elif element.tag == _TBL:
            yield _table(element)


def _paragraph(element: ElementTree.Element) -> Block:
    style = None
    properties = element.find(_PPR)
    if properties is not None:
        node = properties.find(_PSTYLE)
        if node is not None:
            style = node.get(_VAL)

    pieces: list[str] = []
    spans: list[Span] = []
    cursor = 0

    for child in element.iter():
        if child.tag == _R:
            weight = _weight(child)
            start = cursor
            run_text: list[str] = []
            for node in child.iter():
                if node.tag == _T:
                    run_text.append(node.text or "")
                elif node.tag == _TAB:
                    run_text.append("\t")
                elif node.tag == _BR:
                    run_text.append(" ")
            joined = "".join(run_text)
            if not joined:
                continue
            pieces.append(joined)
            cursor += len(joined)
            if weight is not None and joined.strip():
                spans.append(Span(text=joined, start=start, end=cursor, weight=weight))

    return Block(style=style, text="".join(pieces), spans=tuple(spans))


def _weight(run: ElementTree.Element) -> str | None:
    """'bold', 'italic', 'bold-italic', or None.

    `<w:b/>` with no `w:val` means on; `w:val="0"` or `"false"` means the run
    turns an inherited bold *off*, which the definitions blocks do use.
    """
    properties = run.find(_RPR)
    if properties is None:
        return None
    bold = _toggle(properties.find(f"{W}b"))
    italic = _toggle(properties.find(f"{W}i"))
    if bold and italic:
        return "bold-italic"
    if bold:
        return "bold"
    if italic:
        return "italic"
    return None


def _toggle(node: ElementTree.Element | None) -> bool:
    if node is None:
        return False
    value = node.get(_VAL)
    return value not in {"0", "false", "off"}


def _table(element: ElementTree.Element) -> Block:
    """A table as its grid, and as the words it contributes to the prose.

    Follows `tmm_snapshot.tables`: rows, cells and spans as the markup declares
    them, and **no assumption that the first row is a header**. The Register's
    documents carry `TableHeading`-styled cells where a heading is meant, so
    the header is read from the style rather than from the position — and a
    table whose first row is data stays data.
    """
    rows: list[tuple[str, ...]] = []
    grid: list[tuple[dict, ...]] = []

    for row in element.findall(_TR):
        cells: list[str] = []
        detailed: list[dict] = []
        for cell in row.findall(_TC):
            texts: list[str] = []
            heading = False
            for paragraph in cell.iter(_P):
                block = _paragraph(paragraph)
                if block.style in _TABLE_HEADING_STYLES:
                    heading = True
                words = block.normalised()
                if words:
                    texts.append(words)
            text = " ".join(texts)
            cells.append(text)
            detailed.append(
                {
                    "text": text,
                    "colspan": _span(cell, _GRIDSPAN),
                    "heading": heading,
                    "continues": _continues(cell),
                }
            )
        rows.append(tuple(cells))
        grid.append(tuple(detailed))

    return Block(
        style="<table>",
        text=" ".join(cell for row in rows for cell in row if cell),
        table=tuple(rows),
        grid=tuple(grid),
    )


#: Cell styles the OPC template uses for a table's own heading row.
_TABLE_HEADING_STYLES = frozenset({"TableHeading", "ENoteTableHeading"})


def _span(cell: ElementTree.Element, tag: str) -> int:
    properties = cell.find(_TCPR)
    if properties is None:
        return 1
    node = properties.find(tag)
    if node is None:
        return 1
    try:
        return max(1, int(node.get(_VAL) or 1))
    except ValueError:
        return 1


def _continues(cell: ElementTree.Element) -> bool:
    """True when this cell is the continuation of a vertical merge above it.

    `<w:vMerge/>` with no `w:val` continues; `w:val="restart"` begins. Recorded
    so a reader can rebuild the merge rather than seeing a run of empty cells
    and guessing which one owns the text.
    """
    properties = cell.find(_TCPR)
    if properties is None:
        return False
    node = properties.find(_VMERGE)
    if node is None:
        return False
    return (node.get(_VAL) or "continue") != "restart"
