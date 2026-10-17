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
from typing import Final, Iterator
from xml.etree import ElementTree

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

_P = f"{W}p"
_R = f"{W}r"
_T = f"{W}t"
_TAB = f"{W}tab"
_BR = f"{W}br"
_NO_BREAK_HYPHEN = f"{W}noBreakHyphen"
_SYM = f"{W}sym"
_FONT = f"{W}font"
_CHAR = f"{W}char"
_U = f"{W}u"
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

#: What `<w:noBreakHyphen/>` contributes to the text. Word draws it as a hyphen
#: that will not break across a line, and the OPC template uses it for every
#: hyphenated word it does not want split: 'Comptroller-General', 'cooling-off',
#: 'non-use', and the '8-12' of an item range. Reading it as nothing — which is
#: what a reader that only knows `w:t` does — fused all of those into
#: 'ComptrollerGeneral'. It is written as the ASCII hyphen, the character the
#: Manual uses for the same words, for the same reason `Block.normalised`
#: collapses the non-breaking space: so the two corpora spell a word alike.
NO_BREAK_HYPHEN_TEXT: Final[str] = "-"

#: `<w:sym w:font=… w:char=…/>`: a glyph picked from a symbol font rather than
#: typed. Each pair the Register's documents are known to use, and the
#: character it stands for. A pair not listed raises — a symbol is a character
#: of the law's text, and guessing one, or dropping it as an unknown, is the
#: silently wrong record rule 3 exists to prevent.
#:
#: - Symbol F0BE is the long horizontal bar the template inserts where a
#:   heading wants its em dash: regulation 13.3 of the Regulations is
#:   'Notice of objection to importation—prescribed document', and every other
#:   heading in both instruments types that dash as U+2014.
SYMBOLS: Final[dict[tuple[str, str], str]] = {
    ("Symbol", "F0BE"): "\u2014",
}


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
    weight: str  # 'bold' | 'italic' | 'bold-italic' | 'underline'


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
    #: Underlined stretches of `text`, kept apart from `spans` because they
    #: mean something different and go somewhere different. Emphasis is the
    #: drafter's typography and rides on the units; underlining is the
    #: compilation's own annotation — Endnote 2's key reads 'underlining =
    #: whole or part not commenced or to be commenced' — and is read where the
    #: Register uses it, in the endnote tables.
    underlined: tuple[Span, ...] = ()
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


def normalised_offsets(
    text: str, spans: tuple[Span, ...]
) -> list[tuple[int, int]]:
    """Each span's (start, end) carried from `text` into `" ".join(text.split())`.

    The same collapse `Block.normalised` performs, walked character by
    character so an offset lands on the same word after it. A span's leading
    and trailing whitespace is not part of it once the whitespace is gone: the
    run ' (s 2(1) item 4)' is underlined from its bracket.
    """
    position: list[int | None] = []
    cursor = 0
    pending_space = False
    for character in text:
        if character.isspace():
            position.append(None)
            pending_space = cursor > 0
            continue
        if pending_space:
            cursor += 1
            pending_space = False
        position.append(cursor)
        cursor += 1

    offsets: list[tuple[int, int]] = []
    for span in spans:
        inside = [p for p in position[span.start : span.end] if p is not None]
        if inside:
            offsets.append((inside[0], inside[-1] + 1))
    return offsets


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
    underlined: list[tuple[int, int]] = []
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
                elif node.tag == _NO_BREAK_HYPHEN:
                    run_text.append(NO_BREAK_HYPHEN_TEXT)
                elif node.tag == _SYM:
                    run_text.append(_symbol(node))
            joined = "".join(run_text)
            if not joined:
                continue
            pieces.append(joined)
            cursor += len(joined)
            if weight is not None and joined.strip():
                spans.append(Span(text=joined, start=start, end=cursor, weight=weight))
            if _underlined(child):
                # Word splits a run wherever its editing history did, which
                # carries no meaning, so a stretch underlined across two runs
                # is one stretch: 'No 87, 2026' is not two annotations.
                if underlined and underlined[-1][1] == start:
                    underlined[-1] = (underlined[-1][0], cursor)
                else:
                    underlined.append((start, cursor))

    text = "".join(pieces)
    return Block(
        style=style,
        text=text,
        spans=tuple(spans),
        underlined=tuple(
            Span(text=text[start:end], start=start, end=end, weight="underline")
            for start, end in underlined
            if text[start:end].strip()
        ),
    )


def _symbol(node: ElementTree.Element) -> str:
    key = (node.get(_FONT) or "", (node.get(_CHAR) or "").upper())
    try:
        return SYMBOLS[key]
    except KeyError:
        raise DocumentShapeError(
            f"<w:sym w:font={key[0]!r} w:char={key[1]!r}/> is not a symbol this "
            "reader knows; it is a character of the law's text, so add it to "
            "docx.SYMBOLS with the character it stands for rather than drop it"
        ) from None


def _underlined(run: ElementTree.Element) -> bool:
    """`<w:u w:val="single"/>` and its kin; `w:val="none"` switches it off."""
    properties = run.find(_RPR)
    if properties is None:
        return False
    node = properties.find(_U)
    return node is not None and node.get(_VAL) != "none"


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
            marks: list[tuple[int, int]] = []
            offset = 0
            heading = False
            for paragraph in cell.iter(_P):
                block = _paragraph(paragraph)
                if block.style in _TABLE_HEADING_STYLES:
                    heading = True
                words = block.normalised()
                if words:
                    if texts:
                        offset += 1  # the space the join below puts between
                    marks.extend(
                        (offset + start, offset + end)
                        for start, end in normalised_offsets(block.text, block.underlined)
                    )
                    texts.append(words)
                    offset += len(words)
            text = " ".join(texts)
            cells.append(text)
            detailed.append(
                {
                    "text": text,
                    "colspan": _span(cell, _GRIDSPAN),
                    "heading": heading,
                    "continues": _continues(cell),
                    "underlined": tuple(marks),
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
