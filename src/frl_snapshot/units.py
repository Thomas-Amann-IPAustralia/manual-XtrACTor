"""A provision's blocks, cut into its numbered units.

The same argument as `tmm_snapshot.blocks`, applied to legislation. A section's
text joined into one string is the correct verbatim reading of it and destroys
every boundary in it — and in a statute the boundaries *are* the addresses:
`s41(3)(a)` is not a paragraph of section 41, it is a provision in its own
right that the Manual, the courts and the Regulations all cite directly.

So this records the boundaries the drafter already asserted, from style names
and nothing else, and joins back to the provision's text exactly:

    " ".join(unit.text for unit in units) == provision.text

which `validate` checks over the whole corpus, for the same reason
`tmm_snapshot` checks it over the Manual: it is what stops this drifting into a
second, differently worded copy of the law.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Final

from frl_snapshot.docx import Block, Span
from frl_snapshot.structure import Provision


class UnitError(Exception):
    """A block this module cannot place."""


#: style -> (kind, depth). Depth is the nesting the OPC stylesheet asserts:
#: a `paragraph` (a) sits inside a `subsection` (1), a `paragraphsub` (i)
#: inside that. Reading it from the style rather than from the leading tabs
#: matters because the tabs are presentation and the style is structure — and
#: because a block whose style is unknown must raise rather than be assigned a
#: plausible depth.
_UNIT_STYLES: Final[dict[str, tuple[str, int]]] = {
    "subsection": ("subsection", 0),
    "subsection2": ("text", 0),
    "Definition": ("definition", 0),
    "SubsectionHead": ("heading", 0),
    "Penalty": ("penalty", 0),
    "Item": ("text", 0),
    "Specials": ("special", 0),
    "Tabletext": ("text", 0),
    "Tablea": ("text", 0),
    "Tablei": ("text", 0),
    "TableHeading": ("text", 0),
    "MadeunderText": ("text", 0),
    "ItemHead": ("heading", 0),
    "paragraph": ("paragraph", 1),
    "paragraphsub": ("paragraph", 2),
    "paragraphsub-sub": ("paragraph", 3),
    "<table>": ("table", 0),
}

#: Note styles, and how far below the unit they attach they sit. A note is a
#: child of the provision unit it follows, not a sibling of it — `notepara` is
#: a paragraph *of the note*, so it goes one deeper again.
_NOTE_STYLES: Final[dict[str, int]] = {
    "notetext": 0,
    "noteToPara": 0,
    "notemargin": 0,
    "notepara": 1,
}

#: An unstyled paragraph. Common in the compilation's own preamble, which the
#: Register writes in Word's default style, and legitimate there — so mapped
#: rather than raised on.
_UNSTYLED: Final[tuple[str, int]] = ("text", 0)

#: '(1)', '(a)', '(iv)', '(A)'. The label the drafter set off with a tab.
_LABEL = re.compile(r"^\((?P<label>[0-9a-zA-Z]{1,4})\)$")

#: A defined term to an address segment, spelled exactly as
#: `tmm_snapshot.chunker._slug` spells a heading. Not truncated, for the same
#: reason: a length cap introduces collisions between terms differing only past
#: the cut, and an ambiguous address is worse than a long one.
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _SLUG_STRIP.sub("-", text.lower()).strip("-")


def _defined_term(unit_kind: str, spans: tuple[Span, ...]) -> str | None:
    """The term a `Definition` defines, from its leading bold-italic run.

    The Office of Parliamentary Counsel sets the definiendum in bold italic at
    the head of the paragraph, and it does so in 189 of the corpus's 189
    definitions — every one of them a span starting at offset 0 with weight
    `bold-italic`. Read, not inferred: the style is the drafter's own mark-up
    and this only takes what it already says.

    Returns `None` where the run is absent, in which case the unit falls back to
    a positional address rather than being given a guessed one.
    """
    if unit_kind != "definition" or not spans:
        return None
    leading = spans[0]
    if leading.start != 0 or leading.weight != "bold-italic":
        return None
    return _slug(leading.text) or None


@dataclass(frozen=True)
class Unit:
    """One addressable piece of a provision.

    `text` keeps the label: the document reads '(3) This subsection applies to
    a trade mark if:' and that is what a reader quoting it should get. `number`
    carries the same label parsed out, because that is what the *address* is
    built from. The two are not duplication for the same reason `chunk_ref` and
    `heading_path` are not: one is the words, one is the way in.
    """

    ref: str
    provision_ref: str
    parent_ref: str | None
    ordinal: int
    depth: int
    kind: str
    style: str | None
    number: str | None
    text: str
    emphasis: tuple[Span, ...] = ()
    table: tuple[tuple[str, ...], ...] | None = None
    grid: tuple[tuple[dict, ...], ...] | None = None
    provisions: tuple[dict, ...] = field(default=())
    #: True when a sibling prints the same `number` as this unit. The
    #: Regulations do this twice — r17A.61(2) has two paragraphs (b), and
    #: r20A.22(2)(b) has two subparagraphs (ii) — so a citation to either
    #: address names two different provisions and cannot be resolved to one.
    #: Recorded, not fixed: rule 1, and the same answer `printed_page_ref`
    #: gives to the two Manual pages that both print the address 20.2.
    number_collision: bool = False


@dataclass(frozen=True)
class _Planned:
    """What one block is, and what it sits under — before any address exists.

    `split_units` reads the blocks once into these and addresses them in a
    second pass, because whether an unnumbered unit may be transparent to the
    address is a fact about the units that come *after* it. Same arrangement,
    and the same reason, as `chunker.chunk_body` planning every section before
    it addresses any.
    """

    ordinal: int
    kind: str
    depth: int
    style: str | None
    number: str | None
    term: str | None
    text: str
    emphasis: tuple[Span, ...]
    table: tuple[tuple[str, ...], ...] | None
    grid: tuple[tuple[dict, ...], ...] | None
    parent: int | None
    note_head: bool


def _plan(provision: Provision) -> list[_Planned]:
    """The one reading of the provision's blocks: kind, depth and parentage."""
    planned: list[_Planned] = []
    open_at: dict[int, _Planned] = {}
    last_non_note: _Planned | None = None
    #: The note a `notepara` belongs to — the last note that was *not* itself a
    #: `notepara`. Anchoring on "the last note of any kind" instead would make
    #: paragraph (b) of a note a child of paragraph (a) of it, and section 41's
    #: Note 1 alone would descend five levels.
    last_note_head: _Planned | None = None

    for index, block in enumerate(provision.blocks, start=1):
        style = block.style
        note_offset = _NOTE_STYLES.get(style or "")

        if note_offset is not None:
            # A note attaches to the unit it follows; a `notepara` attaches to
            # the note it is a paragraph of, falling back to the same place a
            # note would go when it opens without one above it.
            anchor = (last_note_head or last_non_note) if note_offset else last_non_note
            depth = (anchor.depth + 1) if anchor is not None else 0
            kind = "note"
            parent = anchor
        else:
            mapped = _UNIT_STYLES.get(style) if style is not None else _UNSTYLED
            if mapped is None:
                raise UnitError(
                    f"{provision.ref}: paragraph style {style!r} is not in the "
                    "unit map. An unmapped style means the Office of "
                    "Parliamentary Counsel's stylesheet has changed; placing "
                    "it at a guessed depth would put the text under the wrong "
                    "provision, which still validates and is still wrong."
                )
            kind, depth = mapped
            parent = _parent_at(open_at, depth)

        text, emphasis = _normalise(block)
        entry = _Planned(
            ordinal=index,
            kind=kind,
            depth=depth,
            style=style,
            number=_number(block, kind),
            term=_defined_term(kind, emphasis),
            text=text,
            emphasis=emphasis,
            table=block.table,
            grid=block.grid,
            parent=parent.ordinal if parent is not None else None,
            note_head=note_offset == 0,
        )
        planned.append(entry)

        open_at[depth] = entry
        for deeper in [key for key in open_at if key > depth]:
            del open_at[deeper]

        if kind == "note":
            if entry.note_head:
                last_note_head = entry
        else:
            last_non_note = entry
            last_note_head = None

    return planned


def _transparent(planned: list[_Planned]) -> set[int]:
    """Which unnumbered units may hand their address space to their parent.

    An unnumbered ancestor is *transparent* when its children are addressed
    from its parent rather than from it: section 42 reads `An application …
    must be rejected if: (a) …`, and everyone — the Manual 39 times, the
    courts, the Act's own cross references — cites those `s 42(a)`. Addressing
    them `s42~1(a)` would be internally consistent and would match no citation
    anybody writes. `LEGISLATION_NOTES.md` §6.8.

    Applied to *every* unnumbered unit it merges address spaces the drafter
    kept apart. Section 6 sets eleven definitions each with their own `(a)`,
    so `TMA1995/s6(a)` was claimed eleven times and resolved to whichever came
    first in the document; 51 of the corpus's 63 `number_collision` flags were
    manufactured that way and reported as the law's defect.

    **The test is whether the labels actually collide**, which is a fact about
    the document and not a preference. Section 187 is one sentence broken over
    two unnumbered fragments — `(a) (b)` under the first and `(c) (d)` under
    the second — one continuous series, no collision, and `s 187(c)` is how it
    is cited. Section 6's definitions each restart at `(a)`. So siblings whose
    label sets are disjoint stay transparent, and siblings that would claim one
    another's addresses all become opaque.

    A definition is never transparent regardless: it has an address of its own
    now, and it is a named container rather than a sentence's opening words.
    """
    by_parent: dict[int | None, list[_Planned]] = {}
    for entry in planned:
        if entry.number is not None or entry.term is not None:
            continue
        by_parent.setdefault(entry.parent, []).append(entry)

    labels: dict[int, set[str]] = {}
    for entry in planned:
        if entry.number is None or entry.parent is None:
            continue
        labels.setdefault(entry.parent, set()).add(entry.number)

    transparent: set[int] = set()
    for siblings in by_parent.values():
        seen: set[str] = set()
        clashes = False
        for entry in siblings:
            own = labels.get(entry.ordinal, set())
            if own & seen:
                clashes = True
            seen |= own
        if not clashes:
            transparent.update(entry.ordinal for entry in siblings)
    return transparent


def split_units(provision: Provision) -> list[Unit]:
    """The provision's blocks as a nested, addressed unit list."""
    planned = _plan(provision)
    transparent = _transparent(planned)

    units: list[Unit] = []
    #: The address each unit would have if nothing collided, parallel to
    #: `units`. Kept so the *first* claimant of a duplicated number can be
    #: flagged too — it is as ambiguous as the second, and only the second
    #: gets a suffix.
    bases: list[str] = []
    claimed: dict[str, int] = {}
    collided: set[str] = set()
    # ref -> next unnumbered child index, so a note or an unlabelled paragraph
    # gets a positional address that is stable while its siblings are.
    unnumbered: dict[str, int] = {}
    #: ordinal -> the ref its children should build their addresses from. For a
    #: numbered unit and a definition that is its own ref; for a transparent
    #: unnumbered one it is whatever *its* parent would have given.
    address_of: dict[int, str] = {}
    ref_of: dict[int, str] = {}

    for entry in planned:
        parent_ref = ref_of[entry.parent] if entry.parent is not None else provision.ref
        address_parent = (
            address_of[entry.parent] if entry.parent is not None else provision.ref
        )

        if entry.number is not None:
            base = f"{address_parent}{entry.number}"
        elif entry.term is not None:
            # A definition is addressed by the term it defines. Positionally it
            # was `s6~6`, which is a serial number in alphabetical order:
            # inserting one definition repointed every later one, and every
            # `parent_ref` under them, with nothing to detect it. That is the
            # exposure `SOURCE_NOTES.md` §18 measured on the Manual's glossary
            # and removed the same way.
            base = f"{address_parent}/{entry.term}"
        else:
            # Skip past any seat a suffixed collision already took, so an
            # unnumbered unit never lands on an address that exists and never
            # reads as a numbering collision, which it cannot be.
            seat = unnumbered.get(parent_ref, 0) + 1
            while f"{parent_ref}~{seat}" in claimed:
                seat += 1
            unnumbered[parent_ref] = seat
            base = f"{parent_ref}~{seat}"

        # The suffix is allocated from `claimed` rather than composed and
        # trusted. `f"{base}~{n}"` can name an address an unnumbered sibling
        # already took — a note under `(a)` seats itself at `(a)~1`, `(a)~2`,
        # and a second paragraph `(a)` composes `(a)~2` on top of it — which
        # `_assert_unique` then raised on, aborting the whole instrument.
        if base in claimed:
            collided.add(base)
            ref = _free(base, claimed)
        else:
            claimed[base] = 1
            ref = base
        claimed.setdefault(ref, 1)
        bases.append(base)

        ref_of[entry.ordinal] = ref
        address_of[entry.ordinal] = (
            address_parent if entry.ordinal in transparent else ref
        )

        units.append(
            Unit(
                ref=ref,
                provision_ref=provision.ref,
                parent_ref=parent_ref if entry.parent is not None else None,
                ordinal=entry.ordinal,
                depth=entry.depth,
                kind=entry.kind,
                style=entry.style,
                number=entry.number,
                text=entry.text,
                emphasis=entry.emphasis,
                table=entry.table,
                grid=entry.grid,
            )
        )

    # The first claimant of a duplicated number kept the bare address, so it
    # is the one unit in the group carrying no sign that anything is wrong.
    # Flag the whole group: a citation to '(b)' is ambiguous between them, and
    # which of the two happens to hold the unsuffixed ref says nothing.
    units = [
        replace(unit, number_collision=True) if base in collided else unit
        for unit, base in zip(units, bases)
    ]
    _assert_unique(units, provision)
    return units


def _free(base: str, claimed: dict[str, int]) -> str:
    """The next `base~n` nobody has taken, and claim it.

    `claimed` counts how many units wanted each base *and* holds every address
    actually handed out, so the suffix cannot land on a seat an unnumbered
    sibling already occupies. Composing `f"{base}~{claimed[base]}"` and trusting
    it could, and `_assert_unique` then aborted the instrument.
    """
    claimed[base] += 1
    seat = claimed[base]
    while f"{base}~{seat}" in claimed:
        seat += 1
    return f"{base}~{seat}"


def _parent_at(open_at: dict[int, "_Planned"], depth: int) -> "_Planned | None":
    """The nearest open unit shallower than `depth`.

    A `heading` never parents anything — `SubsectionHead` sets a run-in title
    over the subsections that follow it, and how far that title reaches is a
    judgement about meaning, not a fact the markup states. It is emitted in
    document order, where a reader can see what it precedes, and claims no
    scope it was not given.
    """
    for level in sorted((key for key in open_at if key < depth), reverse=True):
        candidate = open_at[level]
        if candidate.kind != "heading":
            return candidate
    return None


def _number(block: Block, kind: str) -> str | None:
    """'(1)', '(a)' — the label, read from the raw tab-separated text.

    Notes and headings are never numbered here even when they open with
    something bracket-shaped: 'Note 1:' is a label the drafter wrote into the
    prose, not an address anyone cites.
    """
    if kind in {"note", "heading", "table"}:
        return None
    segments = [segment for segment in block.text.split("\t") if segment.strip()]
    if not segments:
        return None
    match = _LABEL.match(segments[0].strip())
    return f"({match.group('label')})" if match else None


def _normalise(block: Block) -> tuple[str, tuple[Span, ...]]:
    """The block's words, and its emphasis spans re-based onto them.

    `Block.text` keeps the tabs and non-breaking spaces the parser needs;
    `Block.normalised` collapses them. The spans were measured against the
    first and have to be carried onto the second, or every offset in the
    corpus is silently wrong by the number of tabs to its left.

    Recomputed here rather than re-derived by searching for the span's text in
    the normalised string, because a span whose words occur twice would match
    the wrong one — the same reason `page.flatten_spans` walks once for both.
    """
    raw = block.text
    out: list[str] = []
    index_map: list[int] = []
    pending = False

    for character in raw:
        if character.isspace():
            index_map.append(len(out))
            pending = bool(out)
            continue
        if pending:
            out.append(" ")
            pending = False
        index_map.append(len(out))
        out.append(character)
    index_map.append(len(out))

    text = "".join(out)

    spans: list[Span] = []
    for span in block.spans:
        bounds = _bounds(raw, span.start, span.end)
        if bounds is None:
            continue
        first, last = bounds
        start, end = index_map[first], index_map[last] + 1
        words = " ".join(span.text.split())
        if not words or text[start:end] != words:
            # Not droppable silently: an offset that does not land on its own
            # words is evidence the walk and the collapse disagree, and every
            # other span in the corpus rests on them agreeing.
            raise UnitError(
                f"emphasis span {span.text!r} does not re-base onto "
                f"{text[start:end]!r}"
            )
        spans.append(Span(text=words, start=start, end=end, weight=span.weight))

    return text, tuple(spans)


def _bounds(raw: str, start: int, end: int) -> tuple[int, int] | None:
    """The first and last non-space character positions inside [start, end)."""
    first = next((i for i in range(start, end) if not raw[i].isspace()), None)
    if first is None:
        return None
    last = next(i for i in range(end - 1, first - 1, -1) if not raw[i].isspace())
    return first, last


def _assert_unique(units: list[Unit], provision: Provision) -> None:
    seen: dict[str, Unit] = {}
    for unit in units:
        clash = seen.get(unit.ref)
        if clash is not None:
            raise UnitError(
                f"{provision.ref}: two units claim {unit.ref!r} — "
                f"{clash.text[:60]!r} and {unit.text[:60]!r}. The drafter "
                "numbered two provisions the same, or the depth map placed "
                "them under the same parent; either way one address would "
                "resolve to the wrong words."
            )
        seen[unit.ref] = unit
