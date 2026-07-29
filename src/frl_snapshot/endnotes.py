"""The compilation's endnotes: the instrument's own amendment history.

Every compiled instrument ends with four endnotes, and two of them are the
reason this module exists:

- **Endnote 3, legislation history** — every Act or instrument that has amended
  this one, with its number, year, assent date and commencement.
- **Endnote 4, amendment history** — 317 rows for the Act alone, one per
  provision touched, in the form `s 41 | am No 45, 2006`.

This is the same thing the Manual carries in its per-page "Amended Reasons"
table and that `page.last_amended` / `page.amendment_note` capture — the
document telling you its own history — and it is captured for the same reason.
Unlike the Manual's, it reaches back to 1995 and is per provision.

**What this module does not do.** It does not resolve `s 41` to `TMA1995/s41`.
That parse looks trivial on the rows that are section numbers and is not
trivial at all on the rest: the column also holds `Reader's Guide`, `List of
terms`, `Part 1`, `Div 2 of Part 3`, `ss 41–43`, `s 41(3)(a)` and `Sch 1`, and
a resolver that handles the easy 60% and quietly mangles the rest produces
exactly the silently-wrong record rule 3 exists to prevent. The rows are
captured verbatim, both columns, and turning them into amendment edges is a
piece of ontology work with its own error model — the layer above this one.
Deferred, not forgotten: LEGISLATION_NOTES.md §7.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Iterable

from frl_snapshot.docx import Block

#: 'Endnote 3—Legislation history'. The em dash again, and the number is worth
#: having because the endnotes are numbered consistently across every compiled
#: instrument the Register publishes.
_ENDNOTE_HEADING = re.compile(r"^Endnote\s+(?P<number>\d+)\s*—\s*(?P<title>.+)$")

#: The heading style that opens each endnote.
_SECTION_STYLE: Final[str] = "ENotesHeading2"

#: The heading style that opens the endnotes as a whole; skipped, since it is
#: the word 'Endnotes' and nothing else.
_ROOT_STYLE: Final[str] = "ENotesHeading1"


@dataclass(frozen=True)
class Endnote:
    """One numbered endnote, with its prose and its tables."""

    ref: str
    number: int | None
    title: str
    paragraphs: tuple[str, ...]
    tables: tuple[tuple[tuple[str, ...], ...], ...]


def split_endnotes(blocks: Iterable[Block], instrument_code: str) -> list[Endnote]:
    """Cut the endnote block stream into its numbered sections.

    Material before the first `Endnote N—…` heading is kept under a section
    with `number: null` rather than dropped, so that a compilation which grows
    a preamble does not lose it silently.
    """
    sections: list[Endnote] = []
    number: int | None = None
    title = ""
    paragraphs: list[str] = []
    tables: list[tuple[tuple[str, ...], ...]] = []
    seen: set[str] = set()

    def close() -> None:
        nonlocal paragraphs, tables
        if number is None and not paragraphs and not tables:
            paragraphs, tables = [], []
            return
        ref = _ref(instrument_code, number, title, seen)
        sections.append(
            Endnote(
                ref=ref,
                number=number,
                title=title,
                paragraphs=tuple(paragraphs),
                tables=tuple(tables),
            )
        )
        paragraphs, tables = [], []

    for block in blocks:
        if block.style == _ROOT_STYLE:
            continue

        if block.style == _SECTION_STYLE:
            close()
            text = block.normalised()
            match = _ENDNOTE_HEADING.match(text)
            if match is None:
                # Not fatal: an unheaded endnote section still gets captured,
                # under its own words. The endnotes are the record of the
                # amendment history and losing one to a heading that did not
                # parse would be the worse failure.
                number, title = None, text
            else:
                number, title = int(match.group("number")), match.group("title")
            continue

        if block.is_table and block.table:
            tables.append(block.table)
            continue

        text = block.normalised()
        if text:
            paragraphs.append(text)

    close()
    return sections


def _ref(
    instrument_code: str, number: int | None, title: str, seen: set[str]
) -> str:
    """'TMA1995/endnote3', or a slug when the section carries no number."""
    if number is not None:
        candidate = f"{instrument_code}/endnote{number}"
    else:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "unnumbered"
        candidate = f"{instrument_code}/endnote-{slug}"

    ref, seat = candidate, 1
    while ref in seen:
        seat += 1
        ref = f"{candidate}~{seat}"
    seen.add(ref)
    return ref
