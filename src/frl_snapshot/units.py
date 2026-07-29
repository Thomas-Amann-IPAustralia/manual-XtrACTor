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


def split_units(provision: Provision) -> list[Unit]:
    """The provision's blocks as a nested, addressed unit list."""
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
    # depth -> the unit currently open at that depth, for parent lookup.
    open_at: dict[int, Unit] = {}
    last_non_note: Unit | None = None
    #: The note a `notepara` belongs to — the last note that was *not* itself a
    #: `notepara`. Anchoring on "the last note of any kind" instead would make
    #: paragraph (b) of a note a child of paragraph (a) of it, and section 41's
    #: Note 1 alone would descend five levels.
    last_note_head: Unit | None = None

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
        number = _number(block, kind)

        parent_ref = parent.ref if parent is not None else provision.ref
        if number is not None:
            base = f"{parent_ref}{number}"
        else:
            seat = unnumbered.get(parent_ref, 0) + 1
            unnumbered[parent_ref] = seat
            base = f"{parent_ref}~{seat}"

        # Resolved here rather than in a pass afterwards, because a unit's
        # children are addressed from its ref: suffixing a parent later would
        # leave every descendant pointing at an address that no longer exists.
        if base in claimed:
            collided.add(base)
            claimed[base] += 1
            ref = f"{base}~{claimed[base]}"
        else:
            claimed[base] = 1
            ref = base
        bases.append(base)

        unit = Unit(
            ref=ref,
            provision_ref=provision.ref,
            parent_ref=parent_ref if parent is not None else None,
            ordinal=index,
            depth=depth,
            kind=kind,
            style=style,
            number=number,
            text=text,
            emphasis=emphasis,
            table=block.table,
            grid=block.grid,
        )
        units.append(unit)

        open_at[depth] = unit
        for deeper in [key for key in open_at if key > depth]:
            del open_at[deeper]

        if kind == "note":
            if not note_offset:
                last_note_head = unit
        else:
            last_non_note = unit
            last_note_head = None

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


def _parent_at(open_at: dict[int, Unit], depth: int) -> Unit | None:
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
