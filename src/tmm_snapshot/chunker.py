"""Cleaned body -> chunks.

Owned by T5. The signatures below are fixed — see ARCHITECTURE.md.

The body is cut on `<h2>`–`<h4>` and on nothing else. The Manual's prose is
wrapped several `div.zone` deep in Drupal layout scaffolding, and those zones
break wherever the page author pressed a button — mid-section, around a
call-out, around a single line of example text. They are layout, not structure,
and cutting on them would produce chunks of two words. Headings are the only
boundary the Manual itself asserts.
"""

from __future__ import annotations

import copy
import hashlib
import re
import warnings
from dataclasses import dataclass, field
from typing import NamedTuple

from bs4 import BeautifulSoup, NavigableString, Tag

from tmm_snapshot import config
from tmm_snapshot.blocks import extract_blocks
from tmm_snapshot.citations import (
    extract_cases,
    extract_internal_refs,
    extract_provisions,
)
from tmm_snapshot.page import PageRecord, flatten_text, normalise_text
from tmm_snapshot.sitemap import NavPage
from tmm_snapshot.tables import extract_tables


class ChunkRefCollision(Exception):
    """Two chunks on one page derived the same address.

    A chunk_ref is a citation. Two passages sharing one means every reference
    to it is ambiguous and no consumer can tell which was meant, so this is
    raised rather than resolved with a counter — the address would then be
    stable only until the next crawl. See SCHEMA.md §The chunk record.
    """


class SuppressedHeading(UserWarning):
    """A heading held its section's only content, and held too little of it.

    Warned rather than raised: one page carries 22 of these and raising would
    mean the corpus could not be snapshotted at all. Warned rather than passed
    over in silence because dropping words is exactly the thing this pipeline
    is not allowed to do quietly. See MIN_HEADING_CHUNK_CHARS.
    """


#: Cut here, and nowhere else. `<h1>` is the page title, already on the page
#: record; `<h5>` and `<h6>` are not used for structure in this corpus and are
#: left inside the chunk they fall in.
HEADING_TAGS = ("h2", "h3", "h4")

#: Walked through rather than treated as content. Everything else at a
#: container's own level is a unit of content — including inline elements, so
#: that a stray `<a>` sitting loose in a `div` keeps its href and reaches the
#: citation extractor.
_CONTAINER_TAGS = frozenset({"div", "section", "article", "aside", "main"})

#: A section longer than this is split on paragraph boundaries — never inside
#: one, and never so that a heading is separated from its first paragraph.
#: Approximate by design: folding a short tail back in may carry a fragment
#: over it, and that is preferable to emitting a two-line chunk.
MAX_CHUNK_CHARS = 2400

#: A fragment shorter than this is folded into its neighbour rather than
#: emitted alone. A trailing sentence retrieved without its section is
#: uninterpretable.
MIN_FRAGMENT_CHARS = 120

#: A heading that is its section's entire content is kept (see `chunk_body`),
#: but not below this length. The Manual's alphabet indexes set 'A', 'B', 'C'
#: as headings over the terms filed under them, and Part 23.2 prints a bare
#: '2.2' over its subsections; those carry no words a reader could retrieve,
#: and the letter is already on every child's `heading_path`. Five characters
#: is above every such marker in the corpus and below every real proposition —
#: the shortest of those is Part 32A's 'Divisions I: Principles'.
#:
#: Dropping is announced, never silent: see `SuppressedHeading`.
MIN_HEADING_CHUNK_CHARS = 5

#: A leading dotted address in a heading: '1.2 Intellectual Property Laws...',
#: '2.3.4 Raising a ground for rejection'. Same shape as the nav titles the
#: sitemap reads page_refs from.
_LEADING_ADDRESS = re.compile(r"^(?P<address>\d{1,3}[A-Z]?(?:\.\d+)*)\.?(?=\s|:|$)")

#: The emphasis the Manual sets a heading in when it does not use a heading
#: tag, and the inline elements the CMS wraps around it on the way.
_EMPHASIS_TAGS = frozenset({"strong", "b"})
_WRAPPER_TAGS = frozenset({"span", "em", "u", "i"})

#: A section number of at least two components, optionally carrying a
#: paragraph letter — '3.1', '3.1.1', '2.1.2(a)'. The trailing lookahead is
#: `_LEADING_ADDRESS`'s, and does the same job: it is what separates the
#: heading '3.1 Ownership' from the sentence '3.15% of applications'.
_NUMBERED_HEADING = re.compile(
    r"^(?P<number>\d{1,3}(?:\.\d{1,3})+)(?P<paragraph>\([a-z0-9]{1,3}\))?\.?(?=\s|:|$)"
)


@dataclass
class Chunk:
    """One retrievable passage — normally the prose under a single heading.

    `chunk_ref` is the address *and* the id. Do not add a sequential id: a
    counter is a citation that breaks silently when a paragraph is inserted
    upstream. See SCHEMA.md §The chunk record.
    """

    chunk_ref: str
    page_ref: str
    text: str
    heading_path: list[str]
    ordinal: int
    content_hash: str
    kind: str
    fragment: dict | None
    provisions: list[dict]
    cases: list[dict]
    internal_refs: list[str]
    #: The grid of any table in this chunk. `text` renders a table as a run of
    #: cell text, which is the right verbatim reading and tells you nothing
    #: about which cell sat under which column; this is where that survives.
    #: Empty for the great majority of chunks. See tables.py.
    tables: list[dict] = field(default_factory=list)
    #: The paragraphs and list items `text` was flattened from, in order. Same
    #: argument as `tables`, applied to the prose: joining them reproduces
    #: `text` exactly, so nothing here is a second copy of the words in a
    #: different shape — it is the shape itself. See blocks.py.
    blocks: list[dict] = field(default_factory=list)
    #: How the leaf of `heading_path` was found: 'markup' for an `<h2>`-`<h4>`,
    #: 'emphasis' for a bold numbered paragraph promoted by
    #: `_inferred_heading`, None for the prose above a page's first heading.
    #:
    #: The pipeline is otherwise a pure reading of the markup, and 'emphasis'
    #: is the one place it is not. Recording which it was is what keeps that
    #: honest — a consumer that wants only the Manual's own structure filters
    #: on 'markup' and loses nothing it was entitled to.
    heading_source: str | None = None


class _Heading(NamedTuple):
    """A heading, its depth, and whether the Manual marked it up as one."""

    tag: Tag
    level: int
    #: 'markup' for an h2-h4, 'emphasis' for a bold paragraph promoted by
    #: `_inferred_heading`. Rides through to `Chunk.heading_source` so that no
    #: consumer has to take the two for the same kind of assertion.
    source: str


def page_number(page_ref: str) -> str | None:
    """The Manual's own number for a page: 'TMM/Part60/2/4' -> '2.4'.

    None where any segment after the Part is not a number, which is the
    slug-derived `page_ref` of an unnumbered page (`x-annex-a13-...`). Such a
    page has no number for a subsection to continue, so `_inferred_heading`
    can promote nothing on it — which is the correct answer, not a gap.
    """
    segments = page_ref.split("/")[2:]
    if not segments or not all(re.fullmatch(r"\d{1,3}", s) for s in segments):
        return None
    return ".".join(segments)


def _sole_child(node: Tag) -> Tag | NavigableString | None:
    """The node's only child that is not whitespace, or None if it has others."""
    children = [
        child
        for child in node.children
        if isinstance(child, Tag) or str(child).strip()
    ]
    return children[0] if len(children) == 1 else None


def _wholly_emphasised(node: Tag) -> bool:
    """True when the unit's entire content is one `<strong>` or `<b>`.

    Wholly, not partly. A paragraph that bolds its opening clause and then
    continues in roman is a paragraph making a point, not a heading, and the
    difference is the whole of the control here. The CMS wraps the emphasis in
    `<span class="fontSizeLarge">` and occasionally an `<em>` or `<u>`, so a
    chain of single inline wrappers is walked through on the way in.

    A bare `<strong>` sitting loose in a layout div satisfies this by being
    one. The corpus has two, and they are what shows the `<p>` to be
    incidental: Part 35.1 sets '1.5 Differences between a certification trade
    mark and a standard trade mark' that way and Part 32A sets an unnumbered
    instrument name. Testing the emphasis rather than the wrapper takes the
    first and the number test in `_inferred_heading` declines the second.
    """
    if node.name in _EMPHASIS_TAGS:
        return True
    if node.name != "p":
        return False
    inner = node
    while True:
        only = _sole_child(inner)
        if isinstance(only, Tag) and only.name in _WRAPPER_TAGS:
            inner = only
            continue
        break
    only = _sole_child(inner)
    return (
        isinstance(only, Tag)
        and only.name in _EMPHASIS_TAGS
        and flatten_text(only) == flatten_text(node)
    )


def _inferred_heading(node: Tag, number: str | None) -> int | None:
    """The heading level of a bold paragraph the Manual numbered, or None.

    **This is the one inference in the pipeline, and it is fenced in on three
    sides.** 456 of the Manual's numbered subsections across 88 pages are set
    as bold paragraphs rather than `<h2>`-`<h4>`, so cutting on headings alone
    left 39% of the corpus text under an empty `heading_path` — Part 10.3
    prints 36 numbered subsections and produced nine addressless chunks. The
    structure is there in the source and the markup declines to name it.

    Typography alone would not be enough to act on: the corpus has 898 wholly
    bold paragraphs and only 471 are headings. What makes this decidable is
    that the Manual numbers its subsections against the page's own number, so
    a candidate must:

    1. be a unit whose entire content is one `<strong>` or `<b>` — a `<p>`
       wrapping one, or a bare one the CMS left loose in a layout div;
    2. open with a dotted number of at least two components, bounded by
       whitespace, a colon or end of string; and
    3. carry a number that extends **this page's** number by at least one
       component — '3.1' and '3.1.1' on page 3, '2.4.1' on page 2.4.

    Rule 3 is what makes it a reading of the Manual's own addressing scheme
    rather than a guess about formatting, and it is decisive: across the whole
    corpus it admits 471 candidates and rejects exactly one dotted bold
    paragraph — Part 60.4.25's '4.24.5 No Request for Transformation', whose
    number belongs to a different page. That one is left in the prose, because
    a heading whose number contradicts its page is precisely the case rule 3
    of CLAUDE.md says not to resolve.

    The level is read off the number, not off the typography: '3.1' is two
    components and sits where an `<h3>` sits, '3.1.1' where an `<h4>` does. A
    paragraph letter is one level deeper again, which the corpus confirms —
    Part 32A sets '2.1.2(a)' under a real `<h3>2.1.2</h3>`.

    Chunks cut here are marked `heading_source: "emphasis"`, so nothing
    downstream has to treat this as equivalent to markup. See
    SOURCE_NOTES.md §25.
    """
    if number is None or not _wholly_emphasised(node):
        return None
    match = _NUMBERED_HEADING.match(flatten_text(node))
    if match is None:
        return None
    found = match.group("number")
    if not found.startswith(f"{number}."):
        return None
    depth = 1 + len(found.split(".")) + (1 if match.group("paragraph") else 0)
    return depth


def _units(body: Tag, number: str | None = None) -> list[tuple[str, object, int]]:
    """Headings and content units, in document order, each with its level.

    Drupal wraps the prose in `div.zone > div.section12 > div#... > div`, and
    the headings are not children of the body field but great-grandchildren of
    it, so this walks the tree rather than iterating children
    (SOURCE_NOTES.md §6). Only containers are walked through: a `<p>`, `<ul>`
    or `<table>` is one unit, kept whole, because splitting inside one is
    forbidden and because its hrefs are the high-confidence citation layer.

    A `<p>` reached here is always at container level — never inside a `<li>`
    or a `<td>`, because a list and a table are each one unit and are not
    descended into. That is what lets `_inferred_heading` be asked without a
    guard against promoting a bold line inside a table cell.
    """
    found: list[tuple[str, object, int]] = []

    def visit(node: Tag) -> None:
        for child in node.children:
            if isinstance(child, NavigableString):
                if normalise_text(str(child)):
                    found.append(("unit", child, 0))
            elif isinstance(child, Tag):
                if child.name in HEADING_TAGS:
                    found.append(("markup", child, int(child.name[1])))
                elif (level := _inferred_heading(child, number)) is not None:
                    found.append(("emphasis", child, level))
                elif child.name in _CONTAINER_TAGS:
                    visit(child)
                else:
                    found.append(("unit", child, 0))

    visit(body)
    return found


def _sections(
    body: Tag, number: str | None = None
) -> list[tuple[list[_Heading], list[Tag | NavigableString]]]:
    """(heading ancestry, content units) per section, in document order.

    The first section carries no heading — the prose above the page's first
    subheading — and is dropped when it is empty. Ancestry is recovered from
    heading level, so a level-4 heading under a level-3 under a level-2 carries
    all three, and a level-2 after them clears the deeper two.

    Level, not tag name, because a heading here is either an `<h2>`-`<h4>` or a
    bold numbered paragraph `_inferred_heading` promoted, and the second has no
    tag name to read a depth from. For markup the level is still the digit in
    the tag, so nothing about a page without inferred headings changes.
    """
    sections: list[tuple[list[_Heading], list[Tag | NavigableString]]] = []
    ancestry: list[_Heading] = []
    current: list[Tag | NavigableString] = []
    heading_path: list[_Heading] = []

    for kind, node, level in _units(body, number):
        if kind == "unit":
            current.append(node)  # type: ignore[arg-type]
            continue
        assert isinstance(node, Tag)
        if heading_path or current:
            sections.append((list(heading_path), current))
        ancestry = [head for head in ancestry if head.level < level]
        ancestry.append(_Heading(node, level, kind))
        heading_path = list(ancestry)
        current = []

    if heading_path or current:
        sections.append((list(heading_path), current))

    return sections


def _fragment_of(units: list[Tag | NavigableString]) -> Tag:
    """A detached element holding copies of the units, for citation extraction.

    Copies, because the citation extractors walk the fragment and the caller's
    body must come back unmodified — `crawl --from-raw` re-parses the same
    document more than once.
    """
    holder = BeautifulSoup("<div></div>", config.HTML_PARSER).div
    assert holder is not None
    for unit in units:
        holder.append(copy.copy(unit))
    return holder


def _unit_text(unit: Tag | NavigableString) -> str:
    if isinstance(unit, Tag):
        return flatten_text(unit)
    return normalise_text(str(unit))


def _has_image(unit: Tag | NavigableString) -> bool:
    """Whether a unit carries an image and so is not empty after all.

    A unit is measured by its text, and an `<img>` has none — so an image the
    CMS left loose between two paragraphs was dropped before the fragment was
    built, and `blocks` could not record that it had ever been there. It is
    kept from here on, and `blocks._image` records the position. The words are
    unaffected: an image contributes nothing to `chunk.text` either way.
    """
    if not isinstance(unit, Tag):
        return False
    return unit.name == "img" or unit.find("img") is not None


def _group(units: list[Tag | NavigableString]) -> list[list[Tag | NavigableString]]:
    """Split a section into fragments on unit boundaries only.

    Units are paragraphs, lists and tables: never split inside one. The first
    fragment therefore always keeps the section's first paragraph, which is
    what stops a heading being orphaned from its opening text.

    A fragment that would come out shorter than MIN_FRAGMENT_CHARS is folded
    into its neighbour instead. That can carry a fragment past
    MAX_CHUNK_CHARS, which is why that limit is approximate: a chunk slightly
    over length is a smaller problem than a chunk holding one orphaned
    sentence.
    """
    measured = ((unit, len(_unit_text(unit))) for unit in units)
    sized = [
        (unit, length) for unit, length in measured if length or _has_image(unit)
    ]

    groups: list[list[Tag | NavigableString]] = []
    lengths: list[int] = []
    for unit, length in sized:
        if groups and lengths[-1] + length <= MAX_CHUNK_CHARS:
            groups[-1].append(unit)
            lengths[-1] += length
        else:
            groups.append([unit])
            lengths.append(length)

    # A group of nothing but images has no text to be a chunk of, and
    # `chunk.text` may not be empty. The image is still on the page record,
    # which is where a page that is *only* an image is recorded; what is being
    # kept here is an image's position among words, which only exists when
    # there are words. See SOURCE_NOTES.md §24.
    keep = [index for index, length in enumerate(lengths) if length]
    groups = [groups[index] for index in keep]
    lengths = [lengths[index] for index in keep]

    folded: list[list[Tag | NavigableString]] = []
    folded_lengths: list[int] = []
    for group, length in zip(groups, lengths):
        if folded and length < MIN_FRAGMENT_CHARS:
            folded[-1].extend(group)
            folded_lengths[-1] += length
        else:
            folded.append(group)
            folded_lengths.append(length)

    if len(folded) > 1 and folded_lengths[0] < MIN_FRAGMENT_CHARS:
        head = folded.pop(0)
        folded[0][:0] = head

    return folded


def content_hash(text: str) -> str:
    """SHA-256 of the chunk's normalised text.

    Of the text alone, unlike the page hash: a chunk that reads identically
    after a class attribute changed has not changed.
    """
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _slug(text: str) -> str:
    """Heading text to an address segment: 'Aged care' -> 'aged-care'.

    Not truncated. The longest in the corpus is 112 characters, which is
    unwieldy and honest; a length cap would introduce collisions between
    headings that differ only past the cut, and an ambiguous address is a worse
    problem than a long one. `page_ref` already carries segments longer than
    this for the same reason.
    """
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _is_footnote_marker(heading: Tag) -> bool:
    """True when the heading's leading number is a superscript footnote marker.

    Parts 49, 52 and 55 set their footnotes as `<h4>`, and the marker is a
    `<sup>`: `<h4><sup>2</sup> See AKT Consultants Pty Ltd v Alfa Laval Lund
    AB (2006) 70 IPR 347.</h4>`. Flattened that reads '2 See AKT...', whose
    leading address is '2' — so footnote 2 took the address TMM/Part55/2/2,
    which reads as heading 2 of the page and is the parent of the real
    sections TMM/Part55/2/2/1 to /2/2/5. A citation to the section resolved to
    the footnote.

    That is a wrong address rather than a weak one, and the distinction the
    markup already draws is enough to avoid it: `<sup>` appears in exactly
    three headings in the corpus and is a footnote marker in all three, while
    no heading number the Manual prints is superscript. So a leading number
    that came out of a `<sup>` is not read as an address, and the heading
    falls through to the slug form like any other heading the Manual did not
    number. See SOURCE_NOTES.md §26.
    """
    marker = heading.find("sup")
    if not isinstance(marker, Tag):
        return False
    superscript = flatten_text(marker)
    return bool(superscript) and flatten_text(heading).startswith(superscript)


def _heading_address(headings: list[_Heading]) -> tuple[str, bool] | None:
    """The address segment a leaf heading supplies, and whether the Manual
    printed it as a number.

    Split out from `_chunk_ref` so that a page's headings can be counted before
    any of them is used — see `_repeated_labels`.

    Read through `flatten_text`, not `get_text(" ")`: the CMS lets an editor
    highlight a single digit of a heading's number, and the separator then
    lands inside the number — `3.<span>2</span>.1` reads as '3. 2 .1', whose
    leading address is '3'. See SOURCE_NOTES.md §7.
    """
    if not headings:
        return None
    tag = headings[-1].tag
    leaf = flatten_text(tag)
    match = _LEADING_ADDRESS.match(leaf)
    if match is not None and not _is_footnote_marker(tag):
        return match.group("address").replace(".", "/"), True
    slug = _slug(leaf)
    return (slug, False) if slug else None


def _opens_a_subsection(
    sections: list[tuple[list[_Heading], list]], index: int
) -> bool:
    """Whether the section at `index` has a subsection beneath it.

    Sections come in document order and their ancestries are a stack, so the
    section immediately after this one either extends its ancestry — and is
    therefore its child — or closes it. Testing the next section alone is
    enough, and identity is what is compared: two headings that read alike are
    still two headings.
    """
    headings = sections[index][0]
    if not headings or index + 1 >= len(sections):
        return False
    following = sections[index + 1][0]
    return len(following) > len(headings) and all(
        here.tag is there.tag for here, there in zip(headings, following)
    )


def _repeated_labels(sections: list[tuple[list[_Heading], list]]) -> frozenset[str]:
    """Slug addresses the page prints more than once.

    A *number* printed twice is a numbering mistake, and the Manual's numbering
    is what a citation to it rests on — that stays a `ChunkRefCollision`, loud,
    for a human to take up with the Manual's authors.

    A repeated *label* is not a mistake and there is nobody to take it up with.
    Part 29.9 sets the applicant of each worked example as a heading and calls
    both of them 'XYZ Company'; Part 29.4 does the same with the specimen mark
    PLATYPUS. The Manual never promised that a label would identify a section,
    only that a number would, so there is no defect here to report and no
    correction to ask for — and raising would mean the corpus could not be
    snapshotted at all.

    Such a heading therefore falls back to the positional form. It is the
    weaker address and it is the honest one: the Manual has given these two
    sections nothing to tell them apart by.
    """
    seen: dict[str, int] = {}
    for headings, _ in sections:
        address = _heading_address(headings)
        if address is not None and not address[1]:
            seen[address[0]] = seen.get(address[0], 0) + 1
    return frozenset(label for label, count in seen.items() if count > 1)


def _chunk_ref(
    page_ref: str,
    headings: list[_Heading],
    ordinal: int,
    repeated: frozenset[str] = frozenset(),
) -> str:
    """The chunk's address.

    Three forms, strongest first.

    **The heading's own number**, where it has one, appended whole: heading
    '1.2' on page TMM/Part22/1 is TMM/Part22/1/1/2, which reads as 'Part 22,
    page 1, heading 1.2' (SCHEMA.md §The chunk record). The page's number
    repeats, and that redundancy is the price of an address that can be read
    back to a heading the Manual actually prints.

    **A slug of the heading's text**, where the Manual numbers the heading but
    not with a number — 'Adhesive', 'Applications for services'. 777 chunks are
    addressed this way and 627 of them are the Part 14 Annex A13 glossary,
    which the Manual describes as non-exhaustive and therefore expects to add
    to. Positional addresses on that page meant inserting one term silently
    repointed every citation after it; a slug means an insertion changes no
    existing address at all, because the new term simply gets its own.

    What a slug does *not* survive is the heading being reworded. That is the
    trade, and it is the right way round: a reworded heading changes the chunk
    text too, so it shows up in the diff, where a shifted ordinal showed up
    nowhere. See SOURCE_NOTES.md §18.

    No `x-` prefix, unlike the slug fallback on `page_ref`. There it marks a
    segment that could otherwise be mistaken for the Part-local number the
    Manual prints; here a segment of words is self-evidently not a heading
    number, and chunk_refs are meant to be read by people.

    **Position** — '#3' — for the prose above the page's first heading, which
    has no heading to be named by, for a heading whose text is punctuation
    only, and for a heading whose *label* the page prints more than once
    (`repeated`, from `_repeated_labels` — a repeated *number* still raises).
    The first is common and costs nothing: a section with no heading is the
    page preamble, so it is always ordinal 1 and nothing can be inserted ahead
    of it. The second has never been seen. The third is two sections on
    Part 29.9.
    """
    address = _heading_address(headings)
    if address is not None and address[0] not in repeated:
        return f"{page_ref}/{address[0]}"
    return f"{page_ref}#{ordinal}"


def chunk_body(
    body: Tag,
    page: PageRecord,
    nav: NavPage,
    sitemap: dict[str, NavPage] | None = None,
) -> list[Chunk]:
    """Cut the cleaned body on h2-h4, never merging across headings.

    Citations are extracted per chunk from the DOM fragment *before* the text
    is flattened — the AustLII hrefs are the high-confidence citation layer and
    text extraction discards them. See SOURCE_NOTES.md §3.

    `sitemap` is the page inventory, needed to resolve internal cross
    references; without it `internal_refs` is empty, because an unresolved
    reference is dropped rather than guessed. It is an addition to the
    signature in ARCHITECTURE.md, which predates the discovery that resolution
    needs the inventory — see the note there.
    """
    inventory = sitemap or {}
    chunks: list[Chunk] = []
    seen: dict[str, int] = {}
    ordinal = 0

    sections = _sections(body, page_number(page.page_ref))
    repeated = _repeated_labels(sections)

    for index, (headings, units) in enumerate(sections):
        groups = _group(units)
        if not groups:
            # A heading with nothing under it, because the Manual put the
            # section's content *in* the heading. Part 61.3 states two of its
            # four propositions that way — '3.2 Documents that are not made
            # available for public inspection can be requested under the
            # Freedom of Information Act' is the whole of section 3.2 — and
            # Parts 49, 52 and 55 set their footnotes as `<h4>`. Dropping the
            # section lost the words entirely, and with them the citations
            # inside them: Part 55.2's reference to AKT Consultants Pty Ltd v
            # Alfa Laval Lund AB (2006) 70 IPR 347 reached no case list.
            #
            # The heading is therefore chunked as its own content. That is the
            # verbatim reading — those words are on the page and belong to no
            # other section — and it leaves the leaf of `heading_path` equal to
            # `text`, which is honest about where the words came from.
            # An empty heading carries nothing to chunk. The CMS leaves them
            # behind — six pages have an `<h3>` holding only a stripped image
            # or a non-breaking space — and they were already invisible before
            # this branch existed. Nothing is lost by leaving them so.
            leaf = flatten_text(headings[-1].tag) if headings else ""
            if not leaf:
                continue
            # A heading with subsections beneath it did not hold its section's
            # content — the subsections do. This branch exists for the heading
            # that *is* the proposition, and such a heading has nothing under
            # it by definition. Chunking a container instead produces a
            # passage whose whole text is a title that every one of its
            # children already carries in `heading_path`, so no words leave
            # the corpus here and none are said twice. Unlike the length rule
            # below, that costs nothing and is not announced.
            if _opens_a_subsection(sections, index):
                continue
            # Nor is a heading that holds only a marker. See
            # MIN_HEADING_CHUNK_CHARS — the alphabet letters over the Part 14
            # glossary and Part 23.2's bare '2.2' are addresses for the
            # sections below them, not passages anybody can retrieve.
            if len(leaf) < MIN_HEADING_CHUNK_CHARS:
                warnings.warn(
                    f"{page.page_ref}: heading {leaf!r} is its section's only "
                    f"content and is shorter than {MIN_HEADING_CHUNK_CHARS} "
                    "characters, so no chunk was cut for it",
                    SuppressedHeading,
                    stacklevel=2,
                )
                continue
            groups = [[headings[-1].tag]]

        heading_path = [
            nav.part_title,
            page.h1 or nav.nav_title,
            *(flatten_text(heading.tag) for heading in headings),
        ]
        # One address per section, so that a section which had to be split
        # reads as '#3~1', '#3~2' rather than '#3~1', '#4~2'.
        base = _chunk_ref(page.page_ref, headings, ordinal + 1, repeated)

        for index, group in enumerate(groups, start=1):
            ordinal += 1
            fragment = _fragment_of(group)
            text = flatten_text(fragment)
            ref = f"{base}~{index}" if len(groups) > 1 else base

            if ref in seen:
                raise ChunkRefCollision(
                    f"{ref} was derived twice on {page.page_ref} (chunks "
                    f"{seen[ref]} and {ordinal}); two passages cannot share an "
                    "address, and the Manual's own heading numbering is what "
                    "must be corrected"
                )
            seen[ref] = ordinal

            chunks.append(
                Chunk(
                    chunk_ref=ref,
                    page_ref=page.page_ref,
                    text=text,
                    heading_path=list(heading_path),
                    ordinal=ordinal,
                    content_hash=content_hash(text),
                    kind=nav.kind,
                    fragment=(
                        {"index": index, "count": len(groups)}
                        if len(groups) > 1
                        else None
                    ),
                    provisions=extract_provisions(fragment, text),
                    cases=extract_cases(text),
                    internal_refs=extract_internal_refs(fragment, inventory),
                    tables=extract_tables(fragment),
                    blocks=extract_blocks(fragment),
                    heading_source=headings[-1].source if headings else None,
                )
            )

    return chunks
