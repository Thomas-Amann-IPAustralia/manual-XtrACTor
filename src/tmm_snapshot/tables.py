"""Tables — the grid, recovered from the markup.

Called by the chunker, per chunk, like `citations.py` and for the same reason:
the logic is dense and wants a lot of test cases.

**Why this exists.** `flatten_text` renders a table as a run of cell text —
*"Owner Name Address Description Individual Surname + Given name/s ..."* — which
is the right answer for `chunk.text` (verbatim words, whitespace-normalised, and
the only string this system may quote) and useless for anything that needs to
know which cell sat under which column. 45 pages of the Manual carry tables and
several of them, like the Part 10 Annex A2 applicant-identity table, are *only*
a table. The grid is content, and it was being thrown away.

**What it deliberately does not do.** It does not decide that a table's first
row is a header because the cells look like labels, or because they are bold, or
because the row is short. Only `<thead>` and `<th>` say "header", and the Manual
uses them on two tables out of 121. Everywhere else `header_row` is null and the
first row is data as far as this pipeline is concerned — the ambiguity recorded
rather than resolved (CLAUDE.md rule 1). It also does not expand `colspan` into
the cells that span covers: which cells a merge occupies is a rendering
question, and answering it means inventing cells the Manual never wrote.
"""

from __future__ import annotations

from bs4 import Tag

from tmm_snapshot.page import flatten_text

#: Cells, in the two spellings HTML gives them.
_CELL_TAGS = ("td", "th")


def _span(cell: Tag, name: str) -> int:
    """A `colspan`/`rowspan` as an int, defaulting to 1.

    Anything unreadable — an empty string, `colspan="two"`, a negative — reads
    as 1 rather than raising. A span is a presentational hint about a cell whose
    text we already hold correctly, so a bad one costs a slightly wrong
    `columns` count; raising on it would drop a whole page's content over a
    typo in an attribute nobody reads.
    """
    try:
        value = int(str(cell.get(name, "1")).strip())
    except (TypeError, ValueError):
        return 1
    return value if value > 0 else 1


def _own_rows(table: Tag) -> list[Tag]:
    """The `<tr>`s belonging to this table, not to a table nested inside it."""
    return [row for row in table.find_all("tr") if row.find_parent("table") is table]


def _own_cells(row: Tag) -> list[Tag]:
    """The cells belonging to this row, not to a table nested inside it."""
    return [
        cell
        for cell in row.find_all(_CELL_TAGS)
        if cell.find_parent("tr") is row
    ]


def _cell_document(cell: Tag) -> dict[str, object]:
    """One cell. Spans are recorded only when they are not 1.

    Omitting the default keeps the page files small and, more importantly,
    keeps them still: a cell that never had a span must not start carrying
    `"colspan": 1` and rewrite every table in the corpus.
    """
    document: dict[str, object] = {"text": flatten_text(cell)}
    for name in ("colspan", "rowspan"):
        span = _span(cell, name)
        if span != 1:
            document[name] = span
    return document


def _header_row(table: Tag, rows: list[Tag]) -> int | None:
    """Index of the header row, or None when the markup does not say.

    Two spellings are accepted, both structural: a `<thead>` holding exactly
    one row, and a first row whose cells are all `<th>`. A `<thead>` with
    several rows is a stacked header this pipeline will not flatten into one —
    the rows are all in `cells` and the caller can see them, which is the
    honest answer. See the module docstring.
    """
    head = table.find("thead")
    if isinstance(head, Tag):
        indices = [
            index
            for index, row in enumerate(rows)
            if row.find_parent("thead") is head
        ]
        # By index, not `rows.index(row)`: BeautifulSoup compares tags by
        # content, so two identically-worded rows are `==` and `.index` would
        # answer with the first of them.
        return indices[0] if len(indices) == 1 else None

    if rows:
        cells = _own_cells(rows[0])
        if cells and all(cell.name == "th" for cell in cells):
            return 0
    return None


def _table_document(table: Tag, ordinal: int) -> dict[str, object]:
    """One table: the grid, its shape, and where its header is if it says.

    `columns` counts spanned columns rather than cells, so a two-cell row whose
    first cell is `colspan="2"` is three columns wide. That is the width the
    Manual renders, and the number a consumer needs to lay the grid back out.
    """
    rows = _own_rows(table)
    cells = [[_cell_document(cell) for cell in _own_cells(row)] for row in rows]
    widths = [
        sum(int(str(cell.get("colspan", 1))) for cell in row) for row in cells
    ]
    return {
        "ordinal": ordinal,
        "rows": len(rows),
        "columns": max(widths) if widths else 0,
        "header_row": _header_row(table, rows),
        "cells": cells,
    }


def extract_tables(body_fragment: Tag) -> list[dict]:
    """Every table in the fragment, in document order, as a grid.

    Nested tables are not given entries of their own: the outer table's cell
    already holds the inner one's text, and emitting both would store the same
    words twice and leave a consumer to work out which copy was authoritative.
    The Manual has no nested tables today — this is what happens if it grows
    one, and it loses the inner grid rather than the inner words.

    Order is document order, which is the source's own and therefore stable
    across crawls. `ordinal` is 1-based and scoped to the fragment, so a table
    is addressed as 'the second table in this chunk'.
    """
    tops = [
        table
        for table in body_fragment.find_all("table")
        if table.find_parent("table") is None
    ]
    return [_table_document(table, ordinal) for ordinal, table in enumerate(tops, 1)]
