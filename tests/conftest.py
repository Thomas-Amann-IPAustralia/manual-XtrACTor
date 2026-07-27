"""Shared fixture loading.

Every fixture is HTML saved from the live site and committed. Nothing in the
test suite may touch the network — see CLAUDE.md §Working here.
"""

from __future__ import annotations

import copy
import re
from functools import lru_cache
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from tmm_snapshot import config
from tmm_snapshot.fetch import Fetcher, normalise_url
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


# --------------------------------------------------------------------------
# A stand-in Manual, for the orchestration tests
# --------------------------------------------------------------------------

#: Written by hand rather than with BeautifulSoup: `body_for` is called once
#: per page per crawl, and re-parsing 88 KB of markup to change one attribute
#: is the difference between a fast test suite and a slow one.
_CANONICAL = re.compile(r'<link[^>]*rel="canonical"[^>]*>')

ROBOTS = "User-agent: *\nDisallow: /admin/\nDisallow: /user/login\n"


@lru_cache(maxsize=None)
def _served(nav_fixture: tuple[str, ...]) -> tuple[str, dict[str, str], str]:
    """The bodies a fake site serves, built once per nav fixture.

    Every real Manual page renders the whole nav, and the pipeline relies on
    that: `--from-raw` rebuilds the inventory out of a stored page rather than
    out of `sitemap.json`, so that a fix to the sitemap parser takes effect on
    a re-parse. A fake site whose pages carry a different nav from its seed is
    therefore not a small inaccuracy — it is two different Manuals, and the
    two would disagree about which cross references resolve.

    So the saved pages get the fixture's nav grafted into them, and the whole
    site describes one Manual.
    """
    nav_html = fixture_html(*nav_fixture)
    nav = BeautifulSoup(nav_html, config.HTML_PARSER).select_one("div.nested-nav")
    assert nav is not None, f"{nav_fixture} has no nav to serve"

    def with_nav(html: str) -> str:
        soup = BeautifulSoup(html, config.HTML_PARSER)
        existing = soup.select_one("div.nested-nav")
        assert existing is not None
        existing.replace_with(copy.copy(nav))
        return str(soup)

    pages = {page_url(name): with_nav(page_html(name)) for name in PAGE_SLUGS}
    return nav_html, pages, pages[page_url("part22_1")]


class FakeManual:
    """An offline stand-in for the Manual, served over a mock transport.

    The saved pages are served at their own URLs. Every other nav target is
    served a copy of one of them with its canonical link rewritten to the URL
    that was asked for — enough for the page parser, which checks that the page
    it was served is the page the nav named, and cheaper than saving 502
    fixtures to exercise a loop.

    Nothing here reaches the network. `requests` records what a run asked for,
    so a test can assert on the skip gates by counting fetches.
    """

    def __init__(self, *nav_fixture: str) -> None:
        self.nav_html, pages, self.template = _served(nav_fixture)
        self.pages = dict(pages)
        self.requests: list[str] = []
        self.etag: str | None = None
        self.not_modified: set[str] = set()
        #: URLs the site 404s on, as the real nav's link to /trademark/1.5
        #: does. See SOURCE_NOTES.md §14.
        self.gone: set[str] = set()

    def body_for(self, url: str) -> str:
        if url in self.pages:
            return self.pages[url]
        replacement = f'<link href="{url}" rel="canonical"/>'
        body, count = _CANONICAL.subn(lambda _: replacement, self.template)
        assert count == 1, "the template lost its canonical link"
        return body

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)

        if url == config.ROBOTS_URL:
            return httpx.Response(200, text=ROBOTS)

        normalised = normalise_url(url)
        if normalised in self.gone:
            return httpx.Response(404, text="Not found")
        if normalised in self.not_modified:
            return httpx.Response(304)

        headers = {"ETag": self.etag} if self.etag else {}
        if normalised == normalise_url(config.SITEMAP_SEED_URL):
            return httpx.Response(200, headers=headers, text=self.nav_html)
        return httpx.Response(200, headers=headers, text=self.body_for(normalised))

    def fetcher(self, cache_dir: Path) -> Fetcher:
        """A Fetcher wired to this site, with the rate limit turned off."""
        return Fetcher(
            cache_dir, delay_s=0.0, transport=httpx.MockTransport(self.__call__)
        )


@pytest.fixture
def manual() -> FakeManual:
    """Parts 5, 22, 32A and 32B — 61 pages, served offline."""
    return FakeManual("nav_minimal.html")


@pytest.fixture
def small_manual() -> FakeManual:
    """One Part, three pages. For the tests that need a *complete* crawl."""
    return FakeManual("synthetic", "nav_one_part.html")
