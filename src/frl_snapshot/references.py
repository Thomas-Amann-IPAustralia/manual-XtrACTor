"""Statutory cross references in the instruments' own text.

This module is thin on purpose. `tmm_snapshot.citations` already holds the
grammar — the address shapes, the instrument lookahead, the certainty ladder,
the `TMA1995/s44(3)(a)` id format — and it was tuned against a corpus that
cites these two instruments on nearly every page. Re-implementing it here would
produce a second reading of the same references that agreed with the first
until, quietly, it did not.

So the reuse is deliberate, and the one adaptation needed is small enough to
state in full: `extract_provisions` takes a markup fragment *and* the text,
because the Manual hyperlinks its provisions to AustLII and an href is stronger
evidence than prose. A compiled instrument carries no hyperlinks at all —
0 `w:hyperlink` elements in either document — so the fragment is empty and
every edge from this corpus is `extraction: "regex"`. That is not a limitation
being worked around, it is the truth about the source, and it reaches the
snapshot as such.

**What is knowingly not resolved.** Inside the Act, 'this Act' and 'the Act'
are anaphoric to the instrument holding them; inside the Regulations, 'the Act'
means the Trade Marks Act 1995. Both are resolvable by a human in one step and
neither is resolved here, because `citations` deliberately omits 'the Act' from
its instrument table (SOURCE_NOTES.md §4) and teaching it a rule that depends
on which document is being read would change what a Manual edge means. A bare
'section 41' still lands on `TMA1995/s41` at `certainty: "default"`, which is
correct for both instruments — the Act has sections and the Regulations cite
the Act's sections — and that is the whole of what this corpus needs.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from tmm_snapshot import citations
from tmm_snapshot.config import HTML_PARSER

#: An empty fragment, so `citations.extract_provisions` finds no hrefs and
#: falls through to its prose reading. Built once: it is immutable in use, and
#: `find_all` on it is a no-op.
#:
#: Passing this rather than adding a text-only entry point to `citations` keeps
#: that module's signature exactly as ARCHITECTURE.md fixes it — the boundaries
#: there are a contract with other instances, and widening one to save a line
#: here is the sort of change CLAUDE.md says to raise rather than make.
_NO_MARKUP = BeautifulSoup("", HTML_PARSER)


def extract_provisions(text: str) -> list[dict]:
    """Statutory references in a unit's words, deduplicated and sorted.

    Returns the same records the Manual's chunks carry — `id`, `extraction`,
    `certainty`, `mention` — so a consumer filtering provision edges filters
    both corpora with one predicate.
    """
    return citations.extract_provisions(_NO_MARKUP, text)


def provision_key(record: dict) -> tuple[str, ...]:
    """Sort key for a provision edge. Byte-stability depends on it."""
    return (
        str(record.get("id", "")),
        str(record.get("extraction", "")),
        str(record.get("certainty") or ""),
        str(record.get("mention") or ""),
    )
