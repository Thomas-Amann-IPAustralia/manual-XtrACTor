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
from dataclasses import dataclass, field

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

#: A leading dotted address in a heading: '1.2 Intellectual Property Laws...',
#: '2.3.4 Raising a ground for rejection'. Same shape as the nav titles the
#: sitemap reads page_refs from.
_LEADING_ADDRESS = re.compile(r"^(?P<address>\d{1,3}[A-Z]?(?:\.\d+)*)\.?(?=\s|:|$)")


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


def _units(body: Tag) -> list[tuple[str, Tag | NavigableString]]:
    """Headings and content units, in document order.

    Drupal wraps the prose in `div.zone > div.section12 > div#... > div`, and
    the headings are not children of the body field but great-grandchildren of
    it, so this walks the tree rather than iterating children
    (SOURCE_NOTES.md §6). Only containers are walked through: a `<p>`, `<ul>`
    or `<table>` is one unit, kept whole, because splitting inside one is
    forbidden and because its hrefs are the high-confidence citation layer.
    """
    found: list[tuple[str, Tag | NavigableString]] = []

    def visit(node: Tag) -> None:
        for child in node.children:
            if isinstance(child, NavigableString):
                if normalise_text(str(child)):
                    found.append(("unit", child))
            elif isinstance(child, Tag):
                if child.name in HEADING_TAGS:
                    found.append(("heading", child))
                elif child.name in _CONTAINER_TAGS:
                    visit(child)
                else:
                    found.append(("unit", child))

    visit(body)
    return found


def _sections(
    body: Tag,
) -> list[tuple[list[Tag], list[Tag | NavigableString]]]:
    """(heading ancestry, content units) per section, in document order.

    The first section carries no heading — the prose above the page's first
    subheading — and is dropped when it is empty. Ancestry is recovered from
    heading level, so an `<h4>` under an `<h3>` under an `<h2>` carries all
    three, and an `<h2>` after them clears the deeper two.
    """
    sections: list[tuple[list[Tag], list[Tag | NavigableString]]] = []
    ancestry: list[Tag] = []
    current: list[Tag | NavigableString] = []
    heading_path: list[Tag] = []

    for kind, node in _units(body):
        if kind == "heading":
            assert isinstance(node, Tag)
            if heading_path or current:
                sections.append((list(heading_path), current))
            level = int(node.name[1])
            ancestry = [tag for tag in ancestry if int(tag.name[1]) < level]
            ancestry.append(node)
            heading_path = list(ancestry)
            current = []
        else:
            current.append(node)

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
    sized = [(unit, length) for unit, length in measured if length]

    groups: list[list[Tag | NavigableString]] = []
    lengths: list[int] = []
    for unit, length in sized:
        if groups and lengths[-1] + length <= MAX_CHUNK_CHARS:
            groups[-1].append(unit)
            lengths[-1] += length
        else:
            groups.append([unit])
            lengths.append(length)

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


def _heading_address(headings: list[Tag]) -> tuple[str, bool] | None:
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
    leaf = flatten_text(headings[-1])
    match = _LEADING_ADDRESS.match(leaf)
    if match is not None:
        return match.group("address").replace(".", "/"), True
    slug = _slug(leaf)
    return (slug, False) if slug else None


def _repeated_labels(sections: list[tuple[list[Tag], list]]) -> frozenset[str]:
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
    headings: list[Tag],
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

    sections = _sections(body)
    repeated = _repeated_labels(sections)

    for headings, units in sections:
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
            if not headings or not flatten_text(headings[-1]):
                continue
            groups = [[headings[-1]]]

        heading_path = [
            nav.part_title,
            page.h1 or nav.nav_title,
            *(flatten_text(heading) for heading in headings),
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
                )
            )

    return chunks
