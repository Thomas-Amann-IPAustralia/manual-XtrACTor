"""Page-level metadata extraction.

Owned by T4. The signatures below are fixed — see ARCHITECTURE.md.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from tmm_snapshot import config
from tmm_snapshot.fetch import normalise_url
from tmm_snapshot.sitemap import NavPage


class PageNotInSitemap(Exception):
    """A fetched URL is absent from the nav inventory.

    Raised, never worked around. Without a nav entry the page's Part is
    unknowable, and guessing it from the slug produces a record that is
    confidently wrong. See SOURCE_NOTES.md §2.
    """


class UnrecognisedMarkup(Exception):
    """The page is not shaped the way the parser expects.

    A missing record is recoverable; a silently wrong one is not. Every field
    this parser cannot locate with certainty raises rather than defaulting.
    """


#: Where the content lives. The live site wraps the prose in a Drupal body
#: field; `.node__content` is kept as a fallback because SOURCE_NOTES.md §6
#: records it and other node types on the same install may still use it.
BODY_SELECTORS = ("div.field--name-body", "div.node__content")

#: The <h1>, in its own Drupal block.
TITLE_SELECTOR = "div.block-page-title-block h1"

#: The 'Date Published' field, and the label that identifies it.
PUBLISHED_SELECTOR = "div.py-3"
PUBLISHED_LABEL = "Date Published"

#: The per-page amendment log. See SOURCE_NOTES.md §5.
AMENDED_SELECTOR = "div.view-amended-reasons"
AMENDED_REASON_SELECTOR = "td.views-field-field-amended-reason"
AMENDED_DATE_SELECTOR = "td.views-field-field-date-amended"

#: Stripped from the body before chunking. Scoping to the body field already
#: excludes all of these on the live site; they are listed because the day the
#: scoping breaks is the day they would otherwise land in a chunk and be
#: retrieved as if they were practice. See SOURCE_NOTES.md §6.
BOILERPLATE_STRINGS = (
    "Skip to main content",
    "Back to top",
    "This document is controlled. Its accuracy can only be guaranteed when "
    "viewed electronically.",
    "IP Australia | Delivering a world leading IP system",
)

#: Removed wholesale from the body: chrome, scripts, and the metadata blocks
#: whose content is lifted onto the page record instead.
_STRIP_TAGS = ("script", "style", "noscript", "nav", "header", "footer")
_STRIP_SELECTORS = (
    "div.nested-nav",
    AMENDED_SELECTOR,
    "div.views-element-container",
    "div.block-page-title-block",
)

#: Attributes that carry meaning rather than presentation, and so belong in
#: the content hash. `href` is the important one: 'Update hyperlinks' is a
#: real amendment reason, and a hash over text alone would skip the page.
_MEANINGFUL_ATTRS = ("alt", "colspan", "datetime", "href", "name", "rowspan", "src")

#: Zero-width characters. The CMS sprinkles these through the prose — the
#: opening line of Part 22.1 carries seven consecutive ZWSPs — and they are
#: invisible noise in both the text and the hash.
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍﻿"), None)


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


def normalise_text(text: str) -> str:
    """Collapse whitespace and drop zero-width characters.

    The one transformation applied to the Manual's words. Everything else is
    verbatim: no summarising, no reordering, no expanding abbreviations.
    """
    return " ".join(text.translate(_ZERO_WIDTH).replace("\xa0", " ").split())


def resolve_nav(url: str, sitemap: dict[str, NavPage]) -> NavPage:
    """Look a fetched URL up in the inventory, or raise.

    The only sanctioned way to get from a URL to a Part. There is deliberately
    no fallback: see SOURCE_NOTES.md §2.
    """
    key = normalise_url(url)
    try:
        return sitemap[key]
    except KeyError:
        raise PageNotInSitemap(
            f"{key} is not in the nav inventory, so its Part is unknown; "
            "it must not be inferred from the URL slug"
        ) from None


def _parse_time(element: Tag | None, what: str) -> date | None:
    """Read a Drupal <time datetime="..."> as a date.

    Returns None when there is no <time> at all, and raises when there is one
    the parser cannot read — an unreadable date is a markup change, and
    recording it as null would hide that.
    """
    if element is None:
        return None
    stamp = element.get("datetime")
    if not stamp:
        raise UnrecognisedMarkup(f"{what}: <time> carries no datetime attribute")
    try:
        return datetime.fromisoformat(str(stamp)).date()
    except ValueError:
        raise UnrecognisedMarkup(
            f"{what}: cannot read {stamp!r} as a datetime"
        ) from None


def _date_published(main: Tag) -> date | None:
    for block in main.select(PUBLISHED_SELECTOR):
        label = block.find("strong")
        if label is None or normalise_text(label.get_text(" ")) != PUBLISHED_LABEL:
            continue
        return _parse_time(block.find("time"), PUBLISHED_LABEL)
    return None


def _amendment(main: Tag) -> tuple[date | None, str | None]:
    """The most recent row of the page's Amended Reasons table.

    Rows are served newest-first, but that is a rendering choice, so the row
    is chosen by comparing dates rather than by trusting the order. Ties go to
    the first row in document order, which keeps the output byte-stable.

    The reason cell is often empty (SOURCE_NOTES.md §5) and can hold several
    paragraphs; both are normal, neither is an error.
    """
    table = main.select_one(AMENDED_SELECTOR)
    if table is None:
        return None, None

    best: tuple[date, str | None] | None = None
    rows = 0
    for row in table.select("tbody tr"):
        date_cell = row.select_one(AMENDED_DATE_SELECTOR)
        if date_cell is None:
            continue
        amended = _parse_time(date_cell.find("time"), "Amended Reasons")
        if amended is None:
            continue
        rows += 1

        reason_cell = row.select_one(AMENDED_REASON_SELECTOR)
        reason = normalise_text(reason_cell.get_text(" ")) if reason_cell else ""

        if best is None or amended > best[0]:
            best = (amended, reason or None)

    if rows == 0:
        raise UnrecognisedMarkup(
            "an Amended Reasons block is present but no dated rows could be "
            "read from it"
        )

    assert best is not None
    return best


def _assert_is_the_expected_page(soup: BeautifulSoup, nav: NavPage) -> None:
    """Check the served page is the one the nav entry describes.

    Manual URLs redirect, and a redirect that lands on a different node would
    otherwise file that node's content under this Part. Given how freely slugs
    collide across Parts, that is the failure worth spending a check on.
    """
    canonical = soup.find("link", rel="canonical")
    if canonical is None or not canonical.get("href"):
        return
    served = normalise_url(str(canonical["href"]))
    if served != nav.url:
        raise PageNotInSitemap(
            f"fetched {nav.url} but the page says it is {served}; the content "
            f"served is not the nav entry {nav.page_ref}, and filing it under "
            f"{nav.part_id} would attribute it to the wrong Part"
        )


def _clean_body(body: Tag) -> Tag:
    """Strip chrome, scripts, metadata blocks and known boilerplate."""
    for tag in body.find_all(_STRIP_TAGS):
        tag.decompose()
    for selector in _STRIP_SELECTORS:
        for tag in body.select(selector):
            tag.decompose()
    for comment in body.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()

    boilerplate = {normalise_text(text) for text in BOILERPLATE_STRINGS}
    for tag in body.find_all(("a", "div", "p", "span", "li", "h2")):
        if normalise_text(tag.get_text(" ")) in boilerplate:
            tag.decompose()

    return body


def canonical_body(body: Tag) -> str:
    """Deterministic rendering of the cleaned body, for hashing.

    Keeps structure, the meaningful attributes and the text; drops classes,
    ids, styles and comments, which the CMS rewrites without the Manual having
    changed. Normalise first, then hash — ARCHITECTURE.md §Skip logic.
    """
    parts: list[str] = []

    def visit(node: object) -> None:
        if isinstance(node, Comment):
            return
        if isinstance(node, NavigableString):
            if text := normalise_text(str(node)):
                parts.append(text)
            return
        if not isinstance(node, Tag):
            return
        attrs = [
            f"{name}={normalise_text(str(node[name]))}"
            for name in _MEANINGFUL_ATTRS
            if node.get(name)
        ]
        parts.append("<" + "|".join([node.name, *attrs]) + ">")
        for child in node.children:
            visit(child)

    for child in body.children:
        visit(child)
    return "\n".join(parts)


def content_hash(body: Tag) -> str:
    digest = hashlib.sha256(canonical_body(body).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def parse_page(html: str, nav: NavPage) -> tuple[PageRecord, Tag]:
    """Return the page record and the cleaned body element for the chunker.

    Strips nav, header, footer, scripts, the known boilerplate of
    SOURCE_NOTES.md §6, and the Amended Reasons table — after reading the
    amendment metadata out of it.

    Raises PageNotInSitemap if the URL is not in the inventory, and raises if
    the markup shape is unrecognised.
    """
    soup = BeautifulSoup(html, config.HTML_PARSER)
    _assert_is_the_expected_page(soup, nav)

    main = soup.find("main")
    if main is None:
        main = soup.find(id="main-content")
    if not isinstance(main, Tag):
        raise UnrecognisedMarkup(
            f"no <main> and no #main-content in {nav.url}; the page shell has "
            "changed and the content can no longer be located"
        )

    title = main.select_one(TITLE_SELECTOR) or main.find("h1")
    h1 = normalise_text(title.get_text(" ")) if title else None

    date_published = _date_published(main)
    last_amended, amendment_note = _amendment(main)

    body: Tag | None = None
    for selector in BODY_SELECTORS:
        if (body := main.select_one(selector)) is not None:
            break
    if body is None:
        raise UnrecognisedMarkup(
            f"none of {BODY_SELECTORS} found in {nav.url}; the content wrapper "
            "has changed and chunking the whole page would pull in the nav"
        )

    body = _clean_body(body.extract())

    record = PageRecord(
        page_ref=nav.page_ref,
        part_id=nav.part_id,
        url=nav.url,
        nav_title=nav.nav_title,
        h1=h1,
        content_hash=content_hash(body),
        date_published=date_published,
        last_amended=last_amended,
        amendment_note=amendment_note,
        extractor_version=config.EXTRACTOR_VERSION,
    )
    return record, body
