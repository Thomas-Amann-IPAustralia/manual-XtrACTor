"""Building `.docx` bytes from the committed XML fixtures.

The fixtures under `tests/fixtures/legislation/` are `word/document.xml`
slices taken verbatim out of the real compiled instruments — real Office of
Parliamentary Counsel markup, real styles, real numbering defects. They are
stored as XML rather than as `.docx` files on purpose: a `.docx` is a zip, so
a committed one is an opaque blob that cannot be reviewed and whose diff says
nothing. An XML slice is the evidence, readable in a pull request.

`docx.read_document` reads exactly one part of the package, so wrapping a slice
back into a minimal zip is enough to exercise the real reader.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "legislation"

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


def build_docx(document_xml: bytes) -> bytes:
    """A minimal, deterministic `.docx` around one `word/document.xml`.

    Every entry's timestamp is pinned, so the same slice always produces the
    same bytes — the fixtures have to be byte-stable for the idempotence test
    to be testing the pipeline rather than the zip writer. The Register pins
    its own documents the same way, to 1980-01-01.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in (
            ("[Content_Types].xml", _CONTENT_TYPES.encode("utf-8")),
            ("_rels/.rels", _RELS.encode("utf-8")),
            ("word/document.xml", document_xml),
        ):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return buffer.getvalue()


def fixture_docx(name: str) -> bytes:
    """'tma1995-slice' -> the .docx bytes of that committed slice."""
    return build_docx((FIXTURES / f"{name}.document.xml").read_bytes())


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def synthetic(*paragraphs: tuple[str | None, str]) -> bytes:
    """A document built from (style, text) pairs, for the edge cases.

    Tabs in the text are emitted as `<w:tab/>`, because the tab is the
    separator the OPC template puts between a provision's label and its words
    and several parsers here read it.
    """
    body: list[str] = []
    for style, text in paragraphs:
        properties = (
            f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        )
        runs = "".join(
            "<w:tab/>" if piece == "\t" else f'<w:t xml:space="preserve">{piece}</w:t>'
            for piece in _split_tabs(text)
        )
        body.append(f"<w:p>{properties}<w:r>{runs}</w:r></w:p>")
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>{"".join(body)}</w:body></w:document>'
    )
    return build_docx(xml.encode("utf-8"))


def _split_tabs(text: str) -> list[str]:
    pieces: list[str] = []
    for index, part in enumerate(text.split("\t")):
        if index:
            pieces.append("\t")
        if part:
            pieces.append(part)
    return pieces
