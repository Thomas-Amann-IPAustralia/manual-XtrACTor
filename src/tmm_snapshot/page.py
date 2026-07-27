"""Page-level metadata extraction.

Owned by T4. The signatures below are fixed — see ARCHITECTURE.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from bs4 import Tag

from tmm_snapshot.sitemap import NavPage


class PageNotInSitemap(Exception):
    """A fetched URL is absent from the nav inventory.

    Raised, never worked around. Without a nav entry the page's Part is
    unknowable, and guessing it from the slug produces a record that is
    confidently wrong. See SOURCE_NOTES.md §2.
    """


@dataclass(frozen=True)
class PageRecord:
    """Everything constant across the chunks cut from one page.

    Carries no run timestamp: a page file must not change when the page did
    not. Run timing belongs in snapshot/manifest.json. See ARCHITECTURE.md
    §Byte-stability.
    """

    page_ref: str
    part_id: str
    url: str
    nav_title: str
    h1: str | None
    content_hash: str
    date_published: date | None
    last_amended: date | None
    amendment_note: str | None
    extractor_version: str


def parse_page(html: str, nav: NavPage) -> tuple[PageRecord, Tag]:
    """Return the page record and the cleaned body element for the chunker.

    Strips nav, header, footer, scripts, the known boilerplate of
    SOURCE_NOTES.md §6, and the Amended Reasons table — after reading the
    amendment metadata out of it.

    Raises PageNotInSitemap if the URL is not in the inventory, and raises if
    the markup shape is unrecognised.
    """
    raise NotImplementedError("T4")
