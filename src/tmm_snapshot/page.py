"""Page-level metadata extraction.

Owned by T4. The signatures below are fixed — see ARCHITECTURE.md.
"""

from __future__ import annotations

import hashlib
import re
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

#: The banner an archived page carries in place of its prose, and the exact
#: words it carries. See SOURCE_NOTES.md §15.
#:
#: Matched on the whole normalised string, not on a substring and not on the
#: selector alone: `div.alert` is a Bootstrap class the CMS uses for ordinary
#: in-body callouts too, and the thing being decided here is whether a page
#: with no body field is a page the Manual has emptied or a page whose markup
#: we have stopped understanding. Reworded banner, unrecognised page, raise —
#: which is the answer that gets a human to look.
ARCHIVED_SELECTOR = "div.alert[role='alert']"
ARCHIVED_STRING = "This page has been archived."

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

#: Elements that separate words from their neighbours. Everything not listed
#: is inline — `<span>`, `<i>`, `<a>`, `<strong>` — and must not introduce a
#: space, because the CMS wraps instrument names in nested inline elements
#: mid-sentence. See flatten_text.
_TEXT_BREAK_TAGS = frozenset(
    {
        "address",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "li",
        "ol",
        "p",
        "pre",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
)

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
    #: The Manual says this page is archived. It keeps its nav entry, its
    #: title and its amendment history, and has no prose left to chunk. Not
    #: the same as retirement, which is a page leaving the nav altogether.
    archived: bool = False
    #: Every image in the page's content, as `{"src": ..., "alt": ...}`. Eight
    #: pages of the Manual are *only* an image — a flowchart, a cross-search
    #: class table, the format of a summons — and without this they record as
    #: indistinguishable from a page with nothing on it. See extract_images.
    images: tuple[dict[str, str | None], ...] = ()
    #: The address the page's own `<h1>` prints, where that is not `page_ref`.
    #: Null on 498 of 500 pages. See `printed_page_ref` for the two it is not,
    #: and why the disagreement is recorded rather than reconciled.
    printed_page_ref: str | None = None


def normalise_text(text: str) -> str:
    """Collapse whitespace and drop zero-width characters.

    The one transformation applied to the Manual's words. Everything else is
    verbatim: no summarising, no reordering, no expanding abbreviations.
    """
    return " ".join(text.translate(_ZERO_WIDTH).replace("\xa0", " ").split())


@dataclass
class _Span:
    """A tracked element and the range of parts its content occupies."""

    tag: Tag
    first: int
    last: int


def _flatten_parts(
    node: Tag, track: frozenset[str]
) -> tuple[list[str], list[_Span]]:
    """The strings `flatten_text` joins, and where the tracked elements sit.

    One walk, so that `flatten_text` and `flatten_spans` cannot drift into two
    readings of the same tree. A span is recorded where its element opens, so
    the spans come back in document order however deeply they nest.

    A tracked element's own break separators are outside its span: they are the
    gap between it and its neighbour, not part of its words.
    """
    parts: list[str] = []
    spans: list[_Span] = []

    def visit(item: object) -> None:
        if isinstance(item, Comment):
            return
        if isinstance(item, NavigableString):
            parts.append(str(item))
            return
        if not isinstance(item, Tag):
            return
        breaks = item.name in _TEXT_BREAK_TAGS
        if breaks:
            parts.append(" ")
        span: _Span | None = None
        if item.name in track:
            span = _Span(item, len(parts), len(parts))
            spans.append(span)
        for child in item.children:
            visit(child)
        if span is not None:
            span.last = len(parts)
        if breaks:
            parts.append(" ")

    visit(node)
    return parts, spans


def flatten_text(node: Tag) -> str:
    """Element to normalised text, breaking on block elements only.

    `get_text(" ")` is wrong for this corpus in both directions. With a
    separator it inserts a space inside a sentence, because the CMS wraps
    instrument names in nested `<span><i><i>` and the separator lands before
    the following full stop: *'Trade Marks Act 1955 .'*. Without one it welds
    adjacent list items and paragraphs into a single word.

    Inline elements therefore contribute no separator — the source's own
    whitespace already sits inside the text nodes — and block elements
    contribute one on each side.
    """
    parts, _ = _flatten_parts(node, frozenset())
    return normalise_text("".join(parts))


def _normalised_positions(raw: str) -> tuple[str, list[int | None]]:
    """`normalise_text`, and where in its output each input character landed.

    The position list is `None` for a character the normalisation removed — a
    zero-width, or a space swallowed by the run it belongs to — and the index
    of the output character otherwise. It is what turns an element's place in
    the source string into its place in the words, and it exists here, beside
    the normalisation it mirrors, because the two must never disagree:
    `tests/test_links.py` asserts the string it returns is `normalise_text`'s
    over every saved page.
    """
    out: list[str] = []
    at: list[int | None] = []
    pending = False

    for character in raw:
        if ord(character) in _ZERO_WIDTH:
            at.append(None)
            continue
        if character == "\xa0":
            character = " "
        if character.isspace():
            # A run of whitespace becomes one space, and only once something
            # has been emitted for it to follow — which is `str.split()`
            # dropping the leading run, and `" ".join` collapsing the rest.
            pending = bool(out)
            at.append(None)
            continue
        if pending:
            out.append(" ")
            pending = False
        at.append(len(out))
        out.append(character)

    return "".join(out), at


def flatten_spans(
    node: Tag, names: frozenset[str]
) -> tuple[str, list[tuple[Tag, int, int]]]:
    """`flatten_text`, plus where each named element's words sit in it.

    Returns the text and, in document order, `(element, start, end)` such that
    `text[start:end] == flatten_text(element)` — the element's own words, at
    the offsets they occupy in the whole. That equality is the contract, and it
    is checked over the whole snapshot in `validate._link_failures` rather than
    only in a test, because an offset that has drifted by one is a citation
    pointing at the wrong words and looks like nothing at all.

    An element with no words of its own — the five empty `<a>` elements the CMS
    has left in the corpus — comes back as an empty span at the point it sits,
    which keeps the equality true rather than special-casing it away.
    """
    parts, spans = _flatten_parts(node, names)
    raw = "".join(parts)

    # Part index -> offset into `raw`, so a span's part boundaries become
    # character boundaries.
    offsets = [0]
    for part in parts:
        offsets.append(offsets[-1] + len(part))

    text, positions = _normalised_positions(raw)

    found: list[tuple[Tag, int, int]] = []
    for span in spans:
        emitted = [
            position
            for position in positions[offsets[span.first] : offsets[span.last]]
            if position is not None
        ]
        if emitted:
            found.append((span.tag, emitted[0], emitted[-1] + 1))
            continue
        # Nothing of this element survived normalisation, so it has no words to
        # be found by — only a place. That place is where the next word starts,
        # and the empty span there says 'a link sat here and said nothing',
        # which is what the source says.
        following = next(
            (
                position
                for position in positions[offsets[span.last] :]
                if position is not None
            ),
            len(text),
        )
        found.append((span.tag, following, following))

    return text, found


def extract_images(body: Tag) -> tuple[dict[str, str | None], ...]:
    """Every image in the cleaned body, as `{"src": ..., "alt": ...}`.

    The Manual carries 169 of them across 39 pages, and on eight of those the
    image *is* the page: Part 22's "Capable of Distinguishing" flowchart, three
    of the Part 14 cross-search class tables, the Part 54 summons formats. Those
    pages yield no chunks because there is no text in them to chunk, and until
    this field existed a consumer reading the snapshot could not tell them from
    a page that is genuinely blank — of which the corpus holds exactly one,
    Part 39's Annex A1. See SOURCE_NOTES.md §16.

    `src` is recorded exactly as written. Every one in the corpus today is
    root-relative — `/sites/default/files/trademark/image/...` — and resolving
    that against the site root is a join the consumer can do and this pipeline
    should not: rewriting a URL is a transformation, and the raw HTML is the
    thing this record has to stay faithful to.

    `alt` distinguishes absent from empty. `null` means the element carried no
    `alt` attribute at all; `""` means it carried an empty one, which is how
    HTML spells "decorative, skip me". The difference is the whole content of
    *"Accessibility fix – alternative text for images"*, which is one of the
    Manual's own amendment reasons on 28 pages, so collapsing the two would
    hide exactly the change that note describes.

    Sorted and de-duplicated on `(src, alt)`: an image used twice on a page is
    one image, and sorting is what stops a reordering of the prose rewriting
    the record. Same reasoning as `internal_refs` — ARCHITECTURE.md
    §Byte-stability.

    **The sort key has to separate a missing `alt` from an empty one**, or the
    sort is not a total order and rule 2 fails. `(src, alt or "")` collapses
    `None` and `""` onto one key, so two entries sharing a `src` tie, and
    `sorted` falls back to the iteration order of a set of strings — which
    varies with `PYTHONHASHSEED`, so the page rewrites itself on alternate
    runs. No image in the corpus carries an `alt` today, which is exactly why
    this was invisible: it is triggered by the amendment the field exists to
    detect, *"Accessibility fix – alternative text for images"*.
    """
    seen = {
        (str(image["src"]), None if image.get("alt") is None else str(image["alt"]))
        for image in body.find_all("img")
        if image.get("src")
    }
    return tuple(
        {"src": src, "alt": alt}
        for src, alt in sorted(
            seen, key=lambda pair: (pair[0], pair[1] is not None, pair[1] or "")
        )
    )


#: The address a page prints about itself in its own `<h1>`, in the two forms
#: the Manual writes: Part-qualified ('Part 20.2. Definition of sign',
#: '20.2. Background to definition of a trade mark') and page-local
#: ('16. Surnames', on Part 22). Same shape as `sitemap._LEADING_ADDRESS`,
#: because it is the same numbering read off a different element.
_H1_ADDRESS = re.compile(
    r"^(?:Part\s+)?(?P<address>\d{1,3}[A-Z]?(?:\.\d+)*)\.?(?=\s|:|$)"
)


def printed_page_ref(h1: str | None, nav: NavPage) -> str | None:
    """The page_ref this page's own `<h1>` prints, when it is not its page_ref.

    `page_ref` comes from the nav, and must — the nav is the only reliable
    source of Part membership and the only thing that keeps two colliding
    slugs apart (SOURCE_NOTES.md §2). But the page also prints an address, and
    on two of the Manual's 500 pages the two disagree:

        TMM/Part20/3   nav '3. Definition of sign'
                       h1  'Part 20.2. Definition of sign'
        TMM/Part20/2   h1  '20.2. Background to definition of a trade mark'

    Two pages print 20.2. That is the Manual's defect, not ours, and rule 1
    says to record an ambiguity rather than resolve it — so the nav still
    decides the address and this field says, deterministically, that the page
    itself says otherwise. Without it a bare 'part 20.2' in some other Part
    resolves to `TMM/Part20/2` with nothing anywhere suggesting it might have
    meant the other one.

    The second case is milder and is the whole of the rest: Part 1's
    introduction is `Part 1. Introduction` in the nav, which qualifies down to
    no page-local address at all, so its `page_ref` is the slug form — while
    its `<h1>` prints `Part 1.1.` and `TMM/Part1/1` is claimed by nobody.

    `None` where the `<h1>` prints no address (14 pages), where it prints the
    Part's own number and no more — `20. Relevant Legislation` — or where it
    agrees, which is the other 484.
    """
    match = _H1_ADDRESS.match(h1 or "")
    if match is None:
        return None

    address = match.group("address")
    number = nav.part_id[len("Part") :]
    if address == number:
        return None
    local = address[len(number) + 1 :] if address.startswith(f"{number}.") else address
    if not local:
        return None

    printed = f"{nav.page_ref.split('/')[0]}/{nav.part_id}/{local.replace('.', '/')}"
    return printed if printed != nav.page_ref else None


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


def _is_archived(main: Tag) -> bool:
    """Does the page carry the Manual's 'archived' banner, word for word?

    Structural and exact — a selector plus one string equality, no substring
    matching and no inference from the slug. See ARCHIVED_SELECTOR.
    """
    for alert in main.select(ARCHIVED_SELECTOR):
        for paragraph in alert.find_all("p"):
            if normalise_text(paragraph.get_text(" ")) == ARCHIVED_STRING:
                return True
    return False


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
        # The close is what makes this a rendering of the *tree*. Without it
        # the canonical form is a flat sequence of opening tags, and two
        # different shapes collapse onto one string: `<p>a</p><p>b</p>` and
        # `<p>a<p>b</p></p>` both read as '<p> a <p> b'. They hash alike, they
        # flatten to the same `chunk.text`, and they produce different
        # `blocks` — so gate 2 skipped a page whose structure had moved and
        # left the snapshot asserting the old one. Found in the 0.7.0 review.
        parts.append(f"</{node.name}>")

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

    # Read before the body is extracted, and independently of whether one was
    # found: the banner sits beside the body field rather than inside it, and
    # a page can carry both.
    archived = _is_archived(main)

    if body is None:
        if not archived:
            raise UnrecognisedMarkup(
                f"none of {BODY_SELECTORS} found in {nav.url}; the content "
                "wrapper has changed and chunking the whole page would pull "
                "in the nav"
            )
        # An archived page has no body field at all — the Manual takes the
        # prose away and leaves the banner, the title and the amendment table.
        # That is a page with no content, which is a fact about the Manual, and
        # not a page we have failed to understand. It is recorded and yields no
        # chunks; the empty element keeps the return type honest.
        body = soup.new_tag("div")

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
        archived=archived,
        images=extract_images(body),
        printed_page_ref=printed_page_ref(h1, nav),
    )
    return record, body
