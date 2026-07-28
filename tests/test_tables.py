"""The grid, recovered from the markup.

`chunk.text` renders a table as a run of cell text. That is the correct
verbatim reading and it loses which cell sat under which column, which for the
45 pages of the Manual that carry tables — several of which are *only* a table
— is most of the content. These tests pin what `tables.py` recovers.
"""

from __future__ import annotations

import pytest

from tmm_snapshot.chunker import chunk_body
from tmm_snapshot.page import parse_page, resolve_nav
from tmm_snapshot.sitemap import NavPage

from conftest import fixture_html

TABLES_NAV = NavPage(
    url="https://manuals.ipaustralia.gov.au/trademark/7.-a-page-with-tables",
    page_ref="TMM/Part22/7",
    part_id="Part22",
    part_title="Part 22 Section 41 - Capable of Distinguishing",
    nav_title="7. A page with tables",
    nav_ordinal=7,
    kind="body",
)

#: A real page of the Manual whose whole content is one 7x4 table: the
#: applicant-identity grid from Part 10 Annex A2.
REAL_TABLE_SLUG = "annex-a2---identity-of-the-applicant"


@pytest.fixture(scope="module")
def synthetic_chunks():
    record, body = parse_page(
        fixture_html("synthetic", "page_tables.html"), TABLES_NAV
    )
    return chunk_body(body, record, TABLES_NAV)


@pytest.fixture(scope="module")
def by_heading(synthetic_chunks):
    """Chunks keyed by the number leading their leaf heading — '7.1', '7.2'."""
    return {chunk.heading_path[-1].split()[0]: chunk for chunk in synthetic_chunks}


def only_table(chunk):
    assert len(chunk.tables) == 1, f"{chunk.chunk_ref} has {len(chunk.tables)} tables"
    return chunk.tables[0]


def texts(table):
    """The grid as plain strings, for readable assertions."""
    return [[cell["text"] for cell in row] for row in table["cells"]]


# -- the ordinary case, on a real page ------------------------------------


def test_a_real_manual_table_keeps_its_rows_and_columns(sitemap):
    """Part 10 Annex A2 is a 7x4 grid, and every row keeps its own cells."""
    url = f"https://manuals.ipaustralia.gov.au/trademark/{REAL_TABLE_SLUG}"
    nav = resolve_nav(url, sitemap)
    record, body = parse_page(fixture_html("pages", f"{REAL_TABLE_SLUG}.html"), nav)
    chunks = chunk_body(body, record, nav, sitemap)

    table = only_table(chunks[0])
    assert (table["rows"], table["columns"]) == (7, 4)
    assert texts(table)[0] == ["Owner", "Name", "Address", "Description"]
    assert texts(table)[2][0] == "Corporate Body"
    assert texts(table)[2][3] == "ACN, ABN or ARBN"


def test_a_real_manual_table_declares_no_header(sitemap):
    """The Manual does not mark that grid's first row up as a header.

    It reads like one and this pipeline does not care: only <thead> and <th>
    say header, and inferring it from how the words look is the inference rule
    1 forbids. Recorded as null, first row left in `cells` as data.
    """
    url = f"https://manuals.ipaustralia.gov.au/trademark/{REAL_TABLE_SLUG}"
    nav = resolve_nav(url, sitemap)
    record, body = parse_page(fixture_html("pages", f"{REAL_TABLE_SLUG}.html"), nav)
    chunks = chunk_body(body, record, nav, sitemap)

    assert only_table(chunks[0])["header_row"] is None


def test_the_flattened_text_still_reads_verbatim(sitemap):
    """`text` is unchanged by any of this — it is what gets quoted."""
    url = f"https://manuals.ipaustralia.gov.au/trademark/{REAL_TABLE_SLUG}"
    nav = resolve_nav(url, sitemap)
    record, body = parse_page(fixture_html("pages", f"{REAL_TABLE_SLUG}.html"), nav)
    chunks = chunk_body(body, record, nav, sitemap)

    assert "Owner Name Address Description" in chunks[0].text
    assert "|" not in chunks[0].text


# -- headers ---------------------------------------------------------------


def test_a_thead_declares_the_header_row(by_heading):
    table = only_table(by_heading["7.1"])
    assert table["header_row"] == 0
    assert texts(table)[0] == ["Ground", "Section"]


def test_an_all_th_first_row_declares_the_header_row(by_heading):
    table = only_table(by_heading["7.2"])
    assert table["header_row"] == 0
    assert texts(table)[0] == ["Class", "Description"]


def test_the_header_row_is_indexed_not_copied(by_heading):
    """`cells` holds every row. `header_row` points into it.

    Copying the header into its own field would store the same words twice and
    give them two chances to drift.
    """
    table = only_table(by_heading["7.1"])
    assert table["rows"] == len(table["cells"]) == 3
    assert texts(table)[1] == ["Not capable of distinguishing", "section 41"]


def test_a_stacked_header_is_recorded_as_no_header(by_heading):
    """Two <thead> rows are not flattened into one. The ambiguity is kept."""
    table = only_table(by_heading["7.6"])
    assert table["header_row"] is None
    assert table["rows"] == 3
    assert texts(table)[0] == ["Period", "Fee"]
    assert texts(table)[1] == ["From 2013", "AUD"]


# -- spans and ragged rows -------------------------------------------------


def test_spans_are_recorded_only_when_they_are_not_one(by_heading):
    table = only_table(by_heading["7.3"])
    assert table["cells"][0][0] == {"text": "Applicant details", "colspan": 2}
    assert table["cells"][1][0] == {"text": "Individual", "rowspan": 2}
    # No `"colspan": 1` anywhere: a default written out is a default that
    # rewrites every table in the corpus the day it is added.
    assert table["cells"][0][1] == {"text": "Notes"}


def test_columns_counts_spanned_width_not_cells(by_heading):
    """A two-cell row whose first cell is colspan=2 is three columns wide."""
    table = only_table(by_heading["7.3"])
    assert table["columns"] == 3


def test_a_ragged_row_is_recorded_as_it_is(by_heading):
    """The grid is not padded out to a rectangle with cells nobody wrote."""
    table = only_table(by_heading["7.3"])
    assert texts(table)[-1] == ["Sole cell"]


# -- cells that are not words ----------------------------------------------


def test_an_empty_cell_keeps_its_position(by_heading):
    """Dropping it would shift every cell after it into the wrong column."""
    table = only_table(by_heading["7.4"])
    assert texts(table)[1] == ["Blank", ""]


def test_an_image_only_cell_has_empty_text(by_heading):
    """The image itself is on the page record, not in the cell."""
    table = only_table(by_heading["7.4"])
    assert texts(table)[0] == ["Device", ""]


# -- nesting ---------------------------------------------------------------


def test_a_nested_table_gets_no_entry_of_its_own(by_heading):
    """One entry, for the outer table. The inner words live in its cell.

    Emitting both would store the same text twice and leave a consumer to work
    out which copy was authoritative.
    """
    chunk = by_heading["7.5"]
    assert len(chunk.tables) == 1
    assert chunk.tables[0]["rows"] == 1
    assert texts(chunk.tables[0])[0][0] == "Outer left"
    assert "Inner one" in texts(chunk.tables[0])[0][1]


# -- what must not be recorded --------------------------------------------


def test_a_chunk_with_no_table_records_an_empty_list(by_heading):
    assert by_heading["7.7"].tables == []


def test_the_amended_reasons_table_is_not_content(synthetic_chunks):
    """It is stripped before chunking, and its dates live on the page record.

    Recording it as a table would put the page's own amendment log into the
    corpus as if it were practice.
    """
    for chunk in synthetic_chunks:
        for table in chunk.tables:
            assert "Tables added." not in [
                cell["text"] for row in table["cells"] for cell in row
            ]


# -- determinism -----------------------------------------------------------


def test_extraction_is_repeatable(sitemap):
    """Rule 2: the same input yields the same grid, every time."""
    url = f"https://manuals.ipaustralia.gov.au/trademark/{REAL_TABLE_SLUG}"
    nav = resolve_nav(url, sitemap)
    html = fixture_html("pages", f"{REAL_TABLE_SLUG}.html")

    first_record, first_body = parse_page(html, nav)
    second_record, second_body = parse_page(html, nav)
    first = chunk_body(first_body, first_record, nav, sitemap)
    second = chunk_body(second_body, second_record, nav, sitemap)

    assert [chunk.tables for chunk in first] == [chunk.tables for chunk in second]
