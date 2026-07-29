"""The block stream, cut into the law's own structure.

Containers (Chapter, Part, Division, Subdivision, Schedule) come from
`ActHead1`–`ActHead4`; provisions (a section, a regulation, a Schedule clause,
a Schedule item) come from `ActHead5` and `ItemHead`. Nothing here reads a
number out of an indent or a bracket shape: every boundary is a style name the
drafter applied.

The section is the unit this pipeline treats as a *page*, in the sense
`tmm_snapshot` uses the word — the file on disk, the thing with an amendment
history, the thing a citation names. That is not an arbitrary choice of grain:
"section 41" is how the Manual, the courts and the Act itself all address the
law, and Endnote 4 records amendments against exactly that unit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final, Iterable

from frl_snapshot.config import Instrument
from frl_snapshot.docx import Block


class StructureError(Exception):
    """The document's structure is not the shape this module can read.

    Every raise in this module is a case where the alternative is a plausible
    guess. Rule 3: a missing record is recoverable, a silently wrong one is
    not.
    """


#: `ActHead1`–`ActHead4` are container levels and `ActHead5` is the provision.
#: The level is read from the style name's digit rather than from the word in
#: the heading, because the word is what varies between instruments — the Act
#: has no Chapters and the Regulations use `ActHead1` only for Schedules.
_ACT_HEAD = re.compile(r"^ActHead(?P<level>[1-5])$")

#: 'Part 1—Preliminary', 'Subdivision A—Amending Register'. The separator is an
#: em dash, always, and the non-breaking space in 'Part\xa01' has already been
#: collapsed by `Block.normalised`.
_CONTAINER = re.compile(
    r"^(?P<kind>Chapter|Part|Division|Subdivision|Schedule)\s+"
    r"(?P<number>[^\s—]+)\s*—\s*(?P<title>.+)$"
)

#: '41  Trade mark not distinguishing…', '3A.3  Assisted filing service'.
#: The separator is two spaces, in 717 of 717 provision headings across both
#: instruments. A single space is not a separator — it occurs inside titles.
#:
#: Matched against the block's *raw* text, not its normalised text, and that
#: distinction is the whole reason `Block.text` keeps its whitespace: collapse
#: it first and '1  Short title' becomes '1 Short title', where the separator
#: is indistinguishable from the space inside 'Short title' and the number can
#: only be recovered by guessing how much of the line it is.
_PROVISION = re.compile(
    r"^(?P<number>\d+[A-Z]*(?:\.\d+[A-Z]*)*)(?:\t|\s{2,})(?P<title>.+)$"
)

#: A Schedule item: '3A  Section 133A (note)'. Raw text, as above.
_ITEM = re.compile(r"^(?P<number>\d+[A-Z]*)(?:\t|\s{2,})(?P<title>.+)$")

#: How a container kind spells itself in a reference.
_CONTAINER_PREFIX: Final[dict[str, str]] = {
    "Chapter": "ch",
    "Part": "pt",
    "Division": "div",
    "Subdivision": "sdiv",
    "Schedule": "sch",
}

#: The table of contents mirrors the headings exactly — 315 `TOC5` paragraphs
#: against 315 `ActHead5` in the Act — so carrying it would put every heading
#: in the corpus twice and make a renumbering look like a rewrite. Dropped,
#: and counted, so the drop is visible in the manifest rather than assumed.
_TOC_STYLES: Final[frozenset[str]] = frozenset(
    {"TOC1", "TOC2", "TOC3", "TOC4", "TOC5", "TOC6", "TOC7", "TOC8", "TOC9"}
)

#: Page furniture that reaches the body part of the package.
_FURNITURE_STYLES: Final[frozenset[str]] = frozenset({"Header", "Footer"})

#: Everything from here to the end of the document is endnotes: the
#: abbreviation key, the legislation history and the amendment history. Handled
#: by `endnotes.py`, and never mistaken for law — an endnote table names
#: provisions and would otherwise read as a very strange section.
_ENDNOTES_START: Final[str] = "ENotesHeading1"

#: Instrument-level metadata, each appearing once in the front matter.
_TITLE_STYLES: Final[dict[str, str]] = {
    "ShortT": "short_title",
    "LongT": "long_title",
    "CompiledActNo": "number_and_year",
    "CompiledMadeUnder": "made_under",
}


@dataclass(frozen=True)
class Container:
    """A Chapter, Part, Division, Subdivision or Schedule."""

    ref: str
    kind: str
    number: str
    title: str


#: The address given to the material before the instrument's first numbered
#: heading. Reserved, and deliberately not a number: the drafter gave this
#: material no heading to read one from.
FRONT_MATTER_SEGMENT: Final[str] = "front"


@dataclass(frozen=True)
class Provision:
    """An addressable body of the instrument's text, and its blocks.

    `ref` is the citable address and deliberately does **not** carry the Part.
    `TMA1995/s41` is what `tmm_snapshot.citations` already emits for a Manual
    chunk that cites section 41, and the two strings have to be the same string
    or the join between the corpora is a lookup table nobody maintains. The
    Part is recorded in `containers`, where a reader can find it, rather than
    in the address, where a re-organisation would break every citation to it.

    That is the opposite of the Manual's rule, and for a reason worth keeping
    straight: a Manual page has no number of its own that is unique across the
    corpus, so its `page_ref` must carry the Part. A section number is unique
    within its instrument by construction. Where it is *not* — Schedule clauses
    and Schedule items both restart at 1 in every Schedule — the ref carries
    the Schedule, and `_provision` is where that happens.

    **Every block of the instrument's text lands in exactly one of these.**
    That is a stronger claim than "one per section", and it is the claim worth
    making, because the two kinds beyond `section`/`regulation`/`clause`/`item`
    exist precisely to stop text falling out of the corpus:

    - `container` — a Chapter, Part or Schedule with text sitting *directly*
      under it and no provision heading in between. Schedule 1 of the
      Regulations is a class-of-goods table under `Part 1—Classes of goods` and
      nothing else; Schedule 2 is a bare list of prohibited signs; Schedule 8
      numbers its clauses inline (`1. Subject to clause 1A…`) in body style
      rather than as headings. None of that is reachable from an `ActHead5`,
      and all of it is law.
    - `front-matter` — everything before the first numbered heading. In the Act
      that is the compilation's own preamble *and* the Reader's Guide, which
      Endnote 4 tracks as an amendable provision ("Reader's Guide  am No 140,
      2001") while giving it no number anywhere in the document. Splitting the
      two apart would mean deciding where the compiler stops and the Act starts
      from the shape of the prose, which is exactly the guess rule 3 forbids —
      so both are captured together, at an address that claims nothing about
      which is which.
    """

    ref: str
    instrument: str
    kind: str  # section | regulation | clause | item | container | front-matter
    number: str | None
    title: str | None
    containers: tuple[Container, ...]
    blocks: tuple[Block, ...] = ()

    @property
    def container_ref(self) -> str | None:
        return self.containers[-1].ref if self.containers else None

    @property
    def group(self) -> str:
        """The top-level container, used to shard the files on disk."""
        if self.containers:
            return self.containers[0].ref.split("/")[1]
        if self.kind == "container":
            return self.ref.split("/")[1]
        return f"_{FRONT_MATTER_SEGMENT}"


@dataclass(frozen=True)
class Document:
    """One compiled instrument, cut up."""

    instrument: Instrument
    titles: dict[str, str] = field(default_factory=dict)
    provisions: tuple[Provision, ...] = ()
    containers: tuple[Container, ...] = ()
    endnote_blocks: tuple[Block, ...] = ()
    dropped_toc: int = 0


#: Kinds opened on spec and dropped when they catch nothing.
_SPECULATIVE_KINDS: Final[frozenset[str]] = frozenset({"container", "front-matter"})


def parse_document(blocks: Iterable[Block], instrument: Instrument) -> Document:
    """Cut a block stream into containers, provisions and endnotes."""
    stack: dict[int, Container] = {}
    containers: list[Container] = []
    provisions: list[Provision] = []
    endnote_blocks: list[Block] = []
    titles: dict[str, str] = {}

    body: list[Block] = []
    current: Provision | None = _front_matter(instrument)
    in_endnotes = False
    dropped_toc = 0

    def close() -> None:
        """Emit the open provision, unless it is an empty placeholder.

        A `container` or `front-matter` record is opened speculatively — every
        Part opens one, and most Parts go straight to their first section — so
        only the ones that actually caught text are emitted. A section with an
        empty body is a different thing and *is* emitted: the Act really does
        contain repealed sections whose entire text is a heading.
        """
        nonlocal current, body
        if current is None:
            return
        blocks = tuple(block for block in body if block.normalised() or block.is_table)
        if blocks or current.kind not in _SPECULATIVE_KINDS:
            provisions.append(
                Provision(
                    ref=current.ref,
                    instrument=current.instrument,
                    kind=current.kind,
                    number=current.number,
                    title=current.title,
                    containers=current.containers,
                    blocks=blocks,
                )
            )
        current = None
        body = []

    for block in blocks:
        style = block.style

        if style == _ENDNOTES_START:
            close()
            in_endnotes = True
        if in_endnotes:
            endnote_blocks.append(block)
            continue

        if style in _TOC_STYLES:
            dropped_toc += 1
            continue
        if style in _FURNITURE_STYLES:
            continue

        text = block.normalised()
        raw = block.text.strip()

        if style in _TITLE_STYLES and text:
            titles.setdefault(_TITLE_STYLES[style], text)
            continue

        head = _ACT_HEAD.match(style or "")
        if head is not None:
            level = int(head.group("level"))
            if level < 5:
                close()
                container = _container(raw, level, stack, instrument)
                stack[level] = container
                for deeper in [key for key in stack if key > level]:
                    del stack[deeper]
                containers.append(container)
                # Opened speculatively, so that text sitting directly under the
                # container — a Schedule that is one table, and nothing else —
                # has somewhere to go. Discarded by `close` if nothing arrives.
                current = _container_body(container, stack, instrument)
                continue

            close()
            current = _provision(raw, stack, instrument)
            continue

        if style == "ItemHead":
            close()
            current = _item(raw, stack, instrument)
            continue

        if current is None:
            raise StructureError(
                f"{instrument.code}: {text[:60]!r} sits outside any provision. "
                "Every block of the instrument's text must have an address; "
                "one that does not means a heading was closed without another "
                "being opened, and the text would vanish from the snapshot."
            )
        body.append(block)

    close()

    # Numbered specifically, not merely non-empty. Front matter and container
    # bodies are opened for whatever text turns up, so a document whose
    # stylesheet this module cannot read at all still yields one record holding
    # the lot — which validates, and is a compiled instrument reduced to an
    # undifferentiated blob. The check that catches that is "did anything
    # arrive with a number on it".
    if not any(
        provision.kind not in _SPECULATIVE_KINDS for provision in provisions
    ):
        raise StructureError(
            f"{instrument.code}: no ActHead5 or ItemHead paragraphs found. "
            "Either the download is not a compiled instrument, or the Office "
            "of Parliamentary Counsel has changed its stylesheet — in both "
            "cases every downstream record would be wrong."
        )

    _assert_unique(provisions, instrument)

    return Document(
        instrument=instrument,
        titles=titles,
        provisions=tuple(provisions),
        containers=tuple(containers),
        endnote_blocks=tuple(endnote_blocks),
        dropped_toc=dropped_toc,
    )


def _front_matter(instrument: Instrument) -> Provision:
    return Provision(
        ref=f"{instrument.code}/{FRONT_MATTER_SEGMENT}",
        instrument=instrument.code,
        kind="front-matter",
        number=None,
        title=None,
        containers=(),
    )


def _container_body(
    container: Container, stack: dict[int, Container], instrument: Instrument
) -> Provision:
    """The container itself, as somewhere for its direct text to live."""
    ancestors = tuple(
        stack[key] for key in sorted(stack) if stack[key].ref != container.ref
    )
    return Provision(
        ref=container.ref,
        instrument=instrument.code,
        kind="container",
        number=container.number,
        title=container.title,
        containers=ancestors,
    )


def _words(text: str) -> str:
    """Whitespace collapsed. Applied to what a heading regex captured, never
    to what it matched against — see `_PROVISION`."""
    return " ".join(text.split())


def _container(
    text: str, level: int, stack: dict[int, Container], instrument: Instrument
) -> Container:
    match = _CONTAINER.match(text)
    if match is None:
        raise StructureError(
            f"{instrument.code}: ActHead{level} heading {text!r} is not "
            "'<Kind> <number>—<title>'. Guessing which of Part, Division or "
            "Schedule it is would put every provision under it in the wrong "
            "place, and the wrong place still validates."
        )

    kind = match.group("kind")
    number = _words(match.group("number"))
    prefix = _CONTAINER_PREFIX[kind]
    segment = f"{prefix}{number.lower()}"

    parents = [stack[key] for key in sorted(stack) if key < level]
    # A Schedule starts a new address space. The Regulations set 'Part 1—
    # Classes of goods' inside Schedule 1 and 'Part 1—Costs' inside Schedule 8,
    # alongside the body's own Part 1, so a Part reference that did not carry
    # its Schedule would name three different things.
    for index, parent in enumerate(parents):
        if parent.kind == "Schedule":
            parents = parents[index:]
            break
    else:
        parents = [parent for parent in parents if parent.kind != "Schedule"]

    ref = "/".join([instrument.code, *(_segment(parent) for parent in parents), segment])
    return Container(
        ref=ref, kind=kind, number=number, title=_words(match.group("title"))
    )


def _segment(container: Container) -> str:
    return container.ref.rsplit("/", 1)[-1]


def _schedule(stack: dict[int, Container]) -> Container | None:
    for key in sorted(stack):
        if stack[key].kind == "Schedule":
            return stack[key]
    return None


def _provision(
    text: str, stack: dict[int, Container], instrument: Instrument
) -> Provision:
    match = _PROVISION.match(text)
    if match is None:
        raise StructureError(
            f"{instrument.code}: provision heading {text!r} does not open with "
            "a number followed by two spaces. That separator holds in every "
            "provision heading of both instruments; a heading that breaks it "
            "means the stylesheet moved and the numbers can no longer be read."
        )

    number = _words(match.group("number"))
    containers = tuple(stack[key] for key in sorted(stack))
    schedule = _schedule(stack)

    if schedule is not None:
        # An ActHead5 inside a Schedule is a clause, not a section: Schedule 9
        # of the Regulations opens with '1  Table of fees', and reading that as
        # regulation 1 would collide with regulation 1.1 and with the clause 1
        # of every other Schedule.
        ref = f"{schedule.ref}/c{number.lower()}"
        kind = "clause"
    else:
        ref = f"{instrument.code}/{instrument.symbol}{number}"
        kind = "section" if instrument.symbol == "s" else "regulation"

    return Provision(
        ref=ref,
        instrument=instrument.code,
        kind=kind,
        number=number,
        title=_words(match.group("title")),
        containers=containers,
    )


def _item(
    text: str, stack: dict[int, Container], instrument: Instrument
) -> Provision:
    match = _ITEM.match(text)
    if match is None:
        raise StructureError(
            f"{instrument.code}: Schedule item heading {text!r} does not open "
            "with a number followed by two spaces."
        )

    schedule = _schedule(stack)
    if schedule is None:
        raise StructureError(
            f"{instrument.code}: Schedule item {text!r} appears outside any "
            "Schedule. Item numbers restart in every Schedule, so an item with "
            "no Schedule to hang off has no address that is not a collision."
        )

    number = _words(match.group("number"))
    return Provision(
        ref=f"{schedule.ref}/item{number.lower()}",
        instrument=instrument.code,
        kind="item",
        number=number,
        title=_words(match.group("title")),
        containers=tuple(stack[key] for key in sorted(stack)),
    )


def _assert_unique(provisions: list[Provision], instrument: Instrument) -> None:
    seen: dict[str, Provision] = {}
    for provision in provisions:
        clash = seen.get(provision.ref)
        if clash is not None:
            raise StructureError(
                f"{instrument.code}: two provisions claim {provision.ref!r} — "
                f"{clash.number} {clash.title!r} and "
                f"{provision.number} {provision.title!r}. A duplicate address "
                "makes one of them unreachable and silently overwrites the "
                "other on disk."
            )
        seen[provision.ref] = provision
