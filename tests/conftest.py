"""Shared fixture loading.

Every fixture is HTML saved from the live site and committed. Nothing in the
test suite may touch the network — see CLAUDE.md §Working here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tmm_snapshot.sitemap import NavPage, build_sitemap

FIXTURES = Path(__file__).parent / "fixtures"

#: Real pages, saved 27 July 2026, keyed by the slug they were fetched from.
PAGE_SLUGS = {
    "part22_1": "1.-registrability-under-section-41-of-the-trade-marks-act-1995",
    "part22_landing": "relevant-legislation44",
    "part22_annex": "annex-a1-section-41-prior-to-raising-the-bar",
    "part32a_2_3": "2.3-section-41--capacity-to-distinguish",
    "part32b_2_3": "2.3-section-41--capacity-to-distinguish1",
}


def fixture_html(*parts: str) -> str:
    return FIXTURES.joinpath(*parts).read_text(encoding="utf-8")


def page_html(name: str) -> str:
    return fixture_html("pages", f"{PAGE_SLUGS[name]}.html")


def page_url(name: str) -> str:
    return f"https://manuals.ipaustralia.gov.au/trademark/{PAGE_SLUGS[name]}"


@pytest.fixture(scope="session")
def manual_root_html() -> str:
    """A full Manual page, as fetched. The nav inventory comes from this."""
    return fixture_html("manual_root.html")


@pytest.fixture(scope="session")
def sitemap(manual_root_html: str) -> dict[str, NavPage]:
    return build_sitemap(manual_root_html)


@pytest.fixture(scope="session")
def nav_minimal_html() -> str:
    """Parts 5, 22, 32A and 32B, lifted verbatim out of the full nav.

    Part 5 carries the three-level nesting; 32A and 32B carry the colliding
    `2.3-section-41--capacity-to-distinguish` slug pair.
    """
    return fixture_html("nav_minimal.html")
