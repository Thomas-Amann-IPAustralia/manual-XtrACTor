"""Reading the compiled `.docx` as an ordered stream of styled blocks."""

from __future__ import annotations

import zipfile

import pytest
from legislation_fixtures import build_docx, fixture_docx, synthetic

from frl_snapshot.docx import DocumentShapeError, read_document


def test_paragraph_styles_survive_the_read():
    """The whole reason this module does not go through an HTML converter."""
    blocks = read_document(fixture_docx("tma1995-slice"))
    styles = {block.style for block in blocks}
    assert {"ActHead2", "ActHead5", "subsection", "paragraph", "notetext"} <= styles


def test_raw_text_keeps_the_tab_that_separates_a_label():
    blocks = read_document(fixture_docx("tma1995-slice"))
    subsection = next(
        block
        for block in blocks
        if block.style == "subsection" and "An application" in block.text
    )
    assert "\t" in subsection.text
    assert subsection.normalised().startswith("(1) An application")


def test_normalising_collapses_the_non_breaking_space():
    """'Part\\xa01—Preliminary' has to read 'Part 1—Preliminary' in both corpora."""
    document = synthetic(("ActHead2", "Part\xa01—Preliminary"))
    assert read_document(document)[0].normalised() == "Part 1—Preliminary"


def test_a_table_is_read_as_a_grid_and_as_words():
    blocks = read_document(fixture_docx("tmr1995-slice"))
    table = next(block for block in blocks if block.is_table)
    assert table.grid is not None
    assert table.table
    assert table.text  # contributes its words to the provision's prose


def test_a_header_row_is_read_from_the_style_not_the_position():
    """tables.py's rule for the Manual: the first row is never assumed."""
    blocks = read_document(fixture_docx("tmr1995-slice"))
    table = next(block for block in blocks if block.is_table)
    assert table.grid is not None
    assert any(cell["heading"] for row in table.grid for cell in row)


def test_a_cell_is_not_also_emitted_as_a_loose_paragraph():
    """`iter()` over the body would do exactly that, and the duplication is
    invisible until a word count comes out double."""
    blocks = read_document(fixture_docx("tmr1995-slice"))
    table = next(block for block in blocks if block.is_table)
    cell_text = next(
        cell for row in table.table or () for cell in row if cell
    )
    loose = [
        block
        for block in blocks
        if not block.is_table and block.normalised() == cell_text
    ]
    assert loose == []


def test_emphasis_spans_land_on_their_own_words():
    for name in ("tma1995-slice", "tmr1995-slice"):
        for block in read_document(fixture_docx(name)):
            for span in block.spans:
                assert block.text[span.start : span.end] == span.text


def test_bold_and_italic_combine():
    blocks = read_document(fixture_docx("tma1995-slice"))
    weights = {
        span.weight for block in blocks for span in block.spans
    }
    assert "bold-italic" in weights


def test_a_non_zip_raises():
    with pytest.raises(DocumentShapeError, match="not a readable"):
        read_document(b"this is not a zip file")


def test_a_zip_without_a_document_part_raises():
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "nothing useful")
    with pytest.raises(DocumentShapeError, match="no word/document.xml"):
        read_document(buffer.getvalue())


def test_an_empty_body_raises():
    xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
        '2006/main"><w:body/></w:document>'
    )
    with pytest.raises(DocumentShapeError, match="no paragraphs"):
        read_document(build_docx(xml.encode("utf-8")))


def _c48(style: str, needle: str) -> str:
    blocks = read_document(fixture_docx("tma1995-c48-slice"))
    return next(
        block.normalised()
        for block in blocks
        if block.style == style and needle in block.normalised()
    )


def test_a_non_breaking_hyphen_is_a_hyphen():
    """`<w:noBreakHyphen/>` carries no `w:t`, and a reader that only knew `w:t`
    wrote 'ComptrollerGeneral' 70 times into the Act — in section headings,
    where it reaches `title` and `heading_path`, as well as in the text."""
    assert _c48("ActHead5", "Customs may seize").startswith(
        "133 Comptroller-General of Customs"
    )
    assert _c48("ActHead3", "Division 2A").endswith("Computerised decision-making")
    assert "re-registration" in _c48("paragraphsub", "(iia)")


def test_the_hyphen_in_an_item_range_survives():
    """Endnote 3's commencement column: 'items 1, 2, 8-12', not '812'."""
    table = next(
        block for block in read_document(fixture_docx("tma1995-c48-slice")) if block.is_table
    )
    assert "sch 1 (items 1, 2, 8-12): 19 Sept 2026" in table.text
    assert "sch 1 (items 26-31): 18 Mar 2027" in table.text


def test_a_symbol_font_dash_is_read():
    """Regulation 13.3's heading takes its dash from the Symbol font."""
    heading = read_document(fixture_docx("tmr1995-symbol-slice"))[0]
    assert heading.normalised() == (
        "13.3 Notice of objection to importation—prescribed document"
    )


def test_an_unknown_symbol_raises():
    xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
        '2006/main"><w:body><w:p><w:r><w:t>a</w:t>'
        '<w:sym w:font="Wingdings" w:char="F0FC"/></w:r></w:p></w:body></w:document>'
    )
    with pytest.raises(DocumentShapeError, match="Wingdings"):
        read_document(build_docx(xml.encode("utf-8")))


def test_underlining_is_read_onto_the_cell_it_marks():
    """Offsets are into the cell's normalised text, and two runs underlined
    side by side are one stretch: '18 Mar 2027' and ' (s 2(1) item 4)' are
    separate runs in the markup."""
    blocks = read_document(fixture_docx("tma1995-c48-slice"))
    commencement = next(block for block in blocks if block.is_table).grid[1][3]
    (start, end), = commencement["underlined"]
    assert commencement["text"][start:end] == "18 Mar 2027 (s 2(1) item 4)"


def test_underlining_off_is_not_underlining():
    xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
        '2006/main"><w:body><w:p><w:r><w:rPr><w:u w:val="none"/></w:rPr>'
        "<w:t>plain</w:t></w:r></w:p></w:body></w:document>"
    )
    assert read_document(build_docx(xml.encode("utf-8")))[0].underlined == ()
