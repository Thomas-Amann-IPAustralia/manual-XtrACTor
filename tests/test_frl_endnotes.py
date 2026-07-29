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
