"""Provisions, cases and internal cross references.

Owned by T6. The signatures below are fixed — see ARCHITECTURE.md.

Called by the chunker, per chunk. Kept separate because these three functions
carry the densest regex logic in the package and the most test cases.
"""

from __future__ import annotations

from bs4 import Tag

from tmm_snapshot.sitemap import NavPage


def extract_provisions(body_fragment: Tag, text: str) -> list[dict]:
    """Statutory references, deduplicated.

    Hrefs first (`extraction: "href"`), read from the AustLII db fragment map
    in SOURCE_NOTES.md §3. Then plain-text mentions (`extraction: "regex"`)
    with a certainty of explicit / default / ambiguous.

    `ambiguous` is not a failure mode, it is the mitigation: the Part 22.1
    anaphora case ("section 26 of the Act", meaning the 1955 Act) is
    unresolvable by regex and forbidden to a model. Record the doubt.
    """
    raise NotImplementedError("T6")


def extract_cases(text: str) -> list[dict]:
    """Decisions in neutral and reported styles. See SOURCE_NOTES.md §9."""
    raise NotImplementedError("T6")


def extract_internal_refs(
    body_fragment: Tag, sitemap: dict[str, NavPage]
) -> list[str]:
    """Manual-internal cross references, resolved through the sitemap.

    Both hyperlinked and bare dotted forms ("see part 22.15.7"). Unresolvable
    targets are dropped: a string a consumer will try to follow and cannot is
    worse than an absent one.
    """
    raise NotImplementedError("T6")
