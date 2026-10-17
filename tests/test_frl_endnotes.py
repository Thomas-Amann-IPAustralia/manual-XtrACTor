"""The compilation's endnotes — the instrument's own amendment history."""

from __future__ import annotations

from legislation_fixtures import fixture_docx

from frl_snapshot import config
from frl_snapshot.docx import read_document
from frl_snapshot.endnotes import split_endnotes
from frl_snapshot.structure import parse_document


def _sections():
    document = parse_document(
        read_document(fixture_docx("tma1995-slice")), config.INSTRUMENTS["TMA1995"]
    )
    return split_endnotes(document.endnote_blocks, "TMA1995")


def test_endnotes_are_numbered_and_addressable():
    sections = _sections()
    assert sections
    assert sections[0].ref == "TMA1995/endnote1"
    assert sections[0].number == 1
    assert "About the endnotes" in sections[0].title


def test_an_endnote_table_is_captured_verbatim():
    """Endnote 4 is 317 rows of 'Provision affected | How affected' in the full
    Act. The rows are the amendment history and are kept as written."""
    sections = _sections()
    with_tables = [section for section in sections if section.tables]
    assert with_tables
    rows = with_tables[0].tables[0]
    assert rows
    assert all(isinstance(cell, str) for row in rows for cell in row)


def test_the_provision_label_is_not_parsed_into_a_ref():
    """Deliberate. The column also holds 'Reader's Guide', 'Part 1',
    'Div 2 of Part 3' and 'ss 41-43'; a resolver that handles the easy rows and
    mangles the rest is the silently-wrong record rule 3 exists to prevent."""
    for section in _sections():
        for table in section.tables:
            for row in table:
                for cell in row:
                    assert not cell.startswith("TMA1995/")


def test_endnote_sections_have_distinct_refs():
    refs = [section.ref for section in _sections()]
    assert len(refs) == len(set(refs))


def _c48_amendment_history():
    sections = split_endnotes(read_document(fixture_docx("tma1995-c48-slice")), "TMA1995")
    return next(section for section in sections if section.number == 4)


def test_underlining_says_which_amendments_have_not_commenced():
    """Compilation 48: s 19 and s 221 both read 'am No 87, 2026'. Only the
    underline on s 19's says it is not yet law, so it is kept beside the words."""
    history = _c48_amendment_history()
    rows = history.tables[0]
    marked = {(mark.row, mark.cell): mark for mark in history.underlined[0]}

    s19 = next(index for index, row in enumerate(rows) if row[0] == "s 19")
    s221 = next(index for index, row in enumerate(rows) if row[0] == "s 221")
    assert rows[s19][1] == rows[s221][1] == "am No 87, 2026"
    assert marked[(s19, 1)].text == "No 87, 2026"
    assert (s221, 1) not in marked


def test_an_underlined_stretch_is_its_cells_own_words():
    for section in split_endnotes(
        read_document(fixture_docx("tma1995-c48-slice")), "TMA1995"
    ):
        for table, marks in zip(section.tables, section.underlined, strict=True):
            for mark in marks:
                assert table[mark.row][mark.cell][mark.start : mark.end] == mark.text
