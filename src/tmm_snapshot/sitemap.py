"""Navigation tree -> page inventory.

Owned by T3. The signatures below are fixed — see ARCHITECTURE.md.

The nav is load-bearing, not convenient: the URL does not tell you which Part a
page belongs to, because Drupal slugs collide across Parts. Read
SOURCE_NOTES.md §2 before touching this module.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from tmm_snapshot import config
from tmm_snapshot.fetch import normalise_url


class NavNotFound(Exception):
    """No navigation tree in the page.

    The markup changed shape, and everything downstream of the nav — which is
    to say every page's Part — is invalid. Raise, never carry on.
    """


class NavAmbiguous(Exception):
    """The nav yielded two of something that must be unique: a Part number, a
    page_ref or a URL. A collision here silently merges two different pages.
    """


#: The nav lives in this container on every Manual page.
NAV_SELECTOR = "div.nested-nav"

#: Part nodes look like 'Part 22 Section 41 - Capable of Distinguishing' and
#: 'Part 32B Examination of Trade Marks for Wines (in Class 33)'. The number
#: takes an alpha suffix and must never be parsed as an int.
_PART_HEADING = re.compile(r"^Part\s+(?P<number>\d{1,3}[A-Z]?)\b\s*(?P<title>.*)$")

#: A leading dotted address in a nav title: '2.3 Section 41: ...',
#: '32B.2.3 Section 41: ...', '1. Fees - general', '22. Numerals'.
_LEADING_ADDRESS = re.compile(r"^(?P<address>\d{1,3}[A-Z]?(?:\.\d+)*)\.?(?=\s|:|$)")

#: Hrefs the nav uses for nodes that are headings rather than pages. The live
#: site emits an empty string; SOURCE_NOTES.md §2 also records '<>' and '#'.
_PLACEHOLDER_HREFS = frozenset({"", "#", "<>"})

#: Titles marking a Part's mapping page rather than its prose. See SCHEMA.md —
#: 'landing' chunks are usually excluded from applicant-facing answers.
_LANDING_TITLES = frozenset({"relevant legislation", "landing page"})

#: Every Manual page lives under this path. The nav also links to uploaded
#: attachments — Part 51 links a .docx flowchart out of /sites/default/files —
#: and those are not pages: they have no <main>, no Amended Reasons and no
#: prose to chunk. They are excluded here rather than left to fail in the page
#: parser on every single crawl. See SOURCE_NOTES.md §13.
_MANUAL_PATH_PREFIX = "/trademark/"


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


def _clean(text: str) -> str:
    """Collapse whitespace, including the non-breaking kind the CMS emits."""
    return " ".join(text.replace("\xa0", " ").split())


def _strip_part_prefix(nav_title: str, part_number: str) -> str:
    """Remove a leading 'Part <this Part's number>' from a nav title.

    Nav titles use two conventions and the Manual mixes them freely, even
    within one Part:

        'Part 32B.2.3 Section 41: ...'  -> Part-qualified
        '2.3 Section 41: ...'           -> page-local

    Only a *leading* 'Part ' triggers the strip. That is what keeps Part 22's
    page '22. Numerals' addressed as 22/22, instead of its leading 22 being
    mistaken for the Part number and flattened away.
    """
    if not nav_title.startswith("Part "):
        return nav_title

    remainder = nav_title[len("Part ") :].lstrip()
    match = _LEADING_ADDRESS.match(remainder)
    if match is None:
        return nav_title

    head, _, tail = match.group("address").partition(".")
    if head != part_number:
        # 'Part N ...' naming something other than its own Part. Leave it be
        # rather than guessing what was meant.
        return nav_title

    rest = remainder[match.end() :].lstrip(" .:")
    return f"{tail} {rest}".strip() if tail else rest


def _slug_of(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def _is_manual_page(url: str) -> bool:
    """Is this nav target a Manual page, as opposed to a linked resource?

    Deliberately a whitelist of one path on one host. Anything else — an
    uploaded document, another IP Australia site, an external link — is a
    resource the nav happens to point at, not a page of the Manual, and
    treating it as one would put a binary through the page parser.
    """
    return url.startswith(f"{config.MANUAL_ROOT}/")


def _page_ref(nav_title: str, url: str, part_id: str, part_number: str) -> str:
    """The page's stable address, e.g. 'TMM/Part22/1'.

    From the leading number in the nav title where there is one, and from the
    URL slug where there is not — Relevant Legislation, Glossary and Annex
    pages carry no number. The slug-derived form is prefixed 'x-' so that it
    is visibly not a dotted address, matching the convention in SCHEMA.md.

    Never the raw slug alone: slugs collide across Parts (SOURCE_NOTES.md §2),
    and it is the Part in front of it that keeps the two apart.
    """
    local = _strip_part_prefix(nav_title, part_number)

    match = _LEADING_ADDRESS.match(local)
    if match is not None:
        address = match.group("address").replace(".", "/")
        return f"{config.REF_PREFIX}/{part_id}/{address}"

    return f"{config.REF_PREFIX}/{part_id}/x-{_slug_of(url)}"


def _kind(nav_title: str, part_number: str) -> str:
    """Classify the page as landing, annex or body.

    Structural only: 'Relevant Legislation' and 'Landing Page' are mapping
    pages, 'Annex ...' is an appendix, everything else is prose. Nothing here
    reads the page's content.
    """
    local = _strip_part_prefix(nav_title, part_number).lstrip(" .:-")
    lowered = local.lower()

    if lowered in _LANDING_TITLES:
        return "landing"
    if lowered.startswith("annex"):
        return "annex"
    return "body"


def _nav_root(html: str) -> Tag:
    soup = BeautifulSoup(html, config.HTML_PARSER)
    container = soup.select_one(NAV_SELECTOR)
    if container is None:
        raise NavNotFound(
            f"no {NAV_SELECTOR} in the page: the Manual's markup has changed "
            "shape and Part membership can no longer be determined"
        )
    root = container.find("ul")
    if root is None:
        raise NavNotFound(f"{NAV_SELECTOR} contains no <ul>")
    return root


def _walk(ul: Tag, depth: int, entries: list[tuple[int, Tag]]) -> None:
    """Collect (depth, <a>) pairs in document order.

    The nav is not nested the way it renders. A child <ul> is a *sibling* of
    the <li> it belongs to, not a descendant of it:

        <li><a class="folder" href="">Part 1 Introduction, Quality</a></li>
        <ul><li><a href="/trademark/1.-introduction7">Part 1. Introduction</a></li></ul>

    That is invalid HTML, and it is why config.HTML_PARSER is pinned: a
    correcting parser rearranges the tree and the ancestry comes out wrong.
    Recursing into <ul> children while tracking depth recovers the ancestry
    the markup means rather than the one it states.
    """
    for child in ul.children:
        if not isinstance(child, Tag):
            continue
        if child.name == "li":
            anchor = child.find("a")
            if anchor is not None:
                entries.append((depth, anchor))
        elif child.name == "ul":
            _walk(child, depth + 1, entries)


def build_sitemap(html: str) -> dict[str, NavPage]:
    """Parse the nav tree out of any Manual page. Keyed by normalised URL.

    Raises if no nav element is found: that means the markup changed shape and
    everything downstream of it is invalid.
    """
    entries: list[tuple[int, Tag]] = []
    _walk(_nav_root(html), 0, entries)

    pages: dict[str, NavPage] = {}
    seen_refs: dict[str, str] = {}
    seen_parts: dict[str, str] = {}

    part_id: str | None = None
    part_number: str | None = None
    part_title: str | None = None
    ordinal = 0

    for depth, anchor in entries:
        title = _clean(anchor.get_text(" "))
        href = (anchor.get("href") or "").strip()

        if depth == 0:
            heading = _PART_HEADING.match(title)
            if heading is None:
                # 'Home', and anything else top-level that is not a Part. Not
                # a Manual page: no Part, and so no page_ref.
                part_id = part_number = part_title = None
                continue

            part_number = heading.group("number")
            part_id = f"Part{part_number}"
            part_title = title
            ordinal = 0

            if part_id in seen_parts:
                raise NavAmbiguous(
                    f"{part_id} appears twice in the nav "
                    f"({seen_parts[part_id]!r} and {title!r}); page_refs would "
                    "collide across two different Parts"
                )
            seen_parts[part_id] = title
            continue

        if href in _PLACEHOLDER_HREFS:
            # A grouping node: 'Part 32B.2. Examination of Wine Trade Marks'
            # is a heading with children, not a page of its own.
            continue

        if part_id is None or part_number is None or part_title is None:
            raise NavAmbiguous(
                f"nav entry {title!r} ({href}) has no Part ancestor; its Part "
                "membership is unknowable and must not be guessed from the URL"
            )

        url = normalise_url(href)
        if not _is_manual_page(url):
            continue

        if url in pages:
            raise NavAmbiguous(
                f"{url} appears twice in the nav "
                f"(as {pages[url].nav_title!r} and {title!r})"
            )

        ordinal += 1
        ref = _page_ref(title, url, part_id, part_number)
        if ref in seen_refs:
            raise NavAmbiguous(
                f"page_ref {ref} derived twice, from {seen_refs[ref]!r} and "
                f"{title!r}; two pages cannot share an address"
            )
        seen_refs[ref] = title

        pages[url] = NavPage(
            url=url,
            page_ref=ref,
            part_id=part_id,
            part_title=part_title,
            nav_title=title,
            nav_ordinal=ordinal,
            kind=_kind(title, part_number),
        )

    if not pages:
        raise NavNotFound("the nav parsed to zero pages")

    return pages


def write_sitemap(pages: dict[str, NavPage], path: Path) -> None:
    """Serialise the inventory to snapshot/sitemap.json, sorted and stable.

    Sorted lexically by page_ref rather than by nav order: nav order is a
    property of the run, and reordering one Part would otherwise rewrite the
    whole file. Carries no timestamp — run metadata belongs in manifest.json.
    See ARCHITECTURE.md §Byte-stability.
    """
    ordered = sorted(pages.values(), key=lambda page: page.page_ref)

    counts: dict[str, int] = {}
    titles: dict[str, str] = {}
    for page in ordered:
        counts[page.part_id] = counts.get(page.part_id, 0) + 1
        titles[page.part_id] = page.part_title

    document = {
        "parts": [
            {
                "part_id": part_id,
                "part_title": titles[part_id],
                "page_count": counts[part_id],
            }
            for part_id in sorted(counts)
        ],
        "pages": [asdict(page) for page in ordered],
    }

    serialised = json.dumps(document, **config.JSON_DUMP_KWARGS) + "\n"  # type: ignore[arg-type]

    # Rule 2: do not touch the file when the bytes are unchanged. Rely on git
    # to notice *nothing*, rather than on git to notice a no-op.
    if path.exists() and path.read_text(encoding="utf-8") == serialised:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialised, encoding="utf-8")
