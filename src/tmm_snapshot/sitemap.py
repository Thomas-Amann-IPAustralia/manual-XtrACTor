"""Navigation tree -> page inventory.

Owned by T3. The signatures below are fixed — see ARCHITECTURE.md.

The nav is load-bearing, not convenient: the URL does not tell you which Part a
page belongs to, because Drupal slugs collide across Parts. Read
SOURCE_NOTES.md §2 before touching this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NavPage:
    """One page as the sidebar nav describes it.

    `part_id` comes from the nav ancestry and from nowhere else. Deriving it
    from the URL is the single worst failure available in this codebase.
    """

    url: str
    page_ref: str
    part_id: str
    part_title: str
    nav_title: str
    nav_ordinal: int
    kind: str


def build_sitemap(html: str) -> dict[str, NavPage]:
    """Parse the nav tree out of any Manual page. Keyed by normalised URL.

    Raises if no nav element is found: that means the markup changed shape and
    everything downstream of it is invalid.
    """
    raise NotImplementedError("T3")


def write_sitemap(pages: dict[str, NavPage], path: Path) -> None:
    """Serialise the inventory to snapshot/sitemap.json, sorted and stable."""
    raise NotImplementedError("T3")
