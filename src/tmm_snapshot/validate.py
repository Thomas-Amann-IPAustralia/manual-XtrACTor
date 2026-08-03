"""Validate snapshot/ against schema/.

Owned by T10. Independent of the rest of the pipeline: implementable from
schema/ and a fixture snapshot alone.

Beyond schema validation this module asserts the invariants a schema cannot
express — every chunk.page_ref resolving to the page in its own file, globally
unique chunk_refs, internal_refs targets existing in the snapshot, ordinals
contiguous from 1, a provision id naming a kind of provision its instrument
actually holds, a chunk's blocks adding back up to its text, and a link's
offsets naming the words the link says it holds.

Reports every failure with file and JSON path rather than stopping at the
first, and exits non-zero if there were any.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

from jsonschema import Draft202012Validator

from tmm_snapshot import config
from tmm_snapshot.citations import (
    INSTRUMENT_DOTTED,
    INSTRUMENT_KIND,
    SCHEDULE_ADDRESS,
    instrument_holds,
)

#: Retired pages are validated too. They stay in the snapshot precisely so that
#: old citations keep resolving, and a citation resolving to a malformed record
#: is no better than one that does not resolve at all.
RETIRED_SEGMENT = "_retired"

#: Fields the schema declares as `format: date` and `format: date-time`.
#: jsonschema treats a format it cannot check as valid and says nothing, unless
#: extra packages are installed — so these are checked here rather than left to
#: a dependency this repo has not agreed to take on.
_DATE_FIELDS = ("date_published", "last_amended")
_DATE_TIME_FIELDS = ("crawled_at",)


@lru_cache(maxsize=None)
def _validator(path: Path) -> Draft202012Validator:
    return Draft202012Validator(json.loads(Path(path).read_text(encoding="utf-8")))


def _where(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _schema_failures(
    document: Any, validator: Draft202012Validator, where: str
) -> list[str]:
    """Every schema violation in one record, not just the first."""
    return [
        f"{where}: {error.json_path}: {error.message}"
        for error in sorted(validator.iter_errors(document), key=lambda e: str(e.path))
    ]


def _date_failures(page: dict[str, Any], where: str) -> list[str]:
    failures: list[str] = []
    for name in _DATE_FIELDS:
        value = page.get(name)
        if value is None:
            continue
        try:
            date.fromisoformat(str(value))
        except (TypeError, ValueError):
            failures.append(f"{where}: page.{name}: {value!r} is not a date")

    for name in _DATE_TIME_FIELDS:
        value = page.get(name)
        if value is None:
            continue
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            failures.append(f"{where}: page.{name}: {value!r} is not a date-time")
            continue
        if parsed.tzinfo is None:
            failures.append(
                f"{where}: page.{name}: {value!r} carries no timezone, so it "
                "names a different instant to every reader"
            )
    return failures


def _page_documents(root: Path) -> Iterator[tuple[Path, dict[str, Any] | None]]:
    """Every page file under the snapshot, retired ones included, sorted."""
    pages = Path(root) / "pages"
    if not pages.is_dir():
        return
    for path in sorted(pages.rglob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            yield path, None
            continue
        yield path, document if isinstance(document, dict) else None


def _inventory_refs(root: Path) -> set[str]:
    """page_refs from snapshot/sitemap.json, or an empty set if there is none.

    The inventory is part of the snapshot, and it is what the chunker resolved
    cross references against — so a reference naming a page the inventory holds
    is resolvable even in a snapshot that has not crawled that page yet. A
    reference naming nothing in *either* is what this check is for: it means
    the extractor invented a target, which is the failure that puts a broken
    citation in front of a reader.
    """
    try:
        document = json.loads((Path(root) / "sitemap.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    pages = document.get("pages", []) if isinstance(document, dict) else []
    return {
        page["page_ref"]
        for page in pages
        if isinstance(page, dict) and isinstance(page.get("page_ref"), str)
    }


def _provision_failures(chunk: dict[str, Any], at: str) -> list[str]:
    """Provision ids whose instrument cannot hold the provision they name.

    An Act is divided into sections and Regulations into regulations, so
    `TMR1995/s224` names something that does not exist — section 224 is in the
    Act. The schema's pattern cannot see this: it checks the shape of an id,
    and the shape is fine. 20 such edges reached the July 2026 snapshot from a
    lookahead that crossed a table's column boundary, every one of them
    recorded as `explicit`, which is the confident end of the scale.

    Only instruments this pipeline knows the kind of are checked. An id from an
    AustLII href carries its kind structurally and cannot disagree with itself.
    """
    failures: list[str] = []
    provisions = chunk.get("provisions")
    if not isinstance(provisions, list):
        return failures

    for index, provision in enumerate(provisions):
        if not isinstance(provision, dict):
            continue
        identifier = provision.get("id")
        if not isinstance(identifier, str) or "/" not in identifier:
            continue
        instrument, _, address = identifier.partition("/")
        expected = INSTRUMENT_KIND.get(instrument)
        if expected is None or not address:
            continue
        if SCHEDULE_ADDRESS.match(address):
            # A Schedule, addressed by the same segment the legislation
            # snapshot uses. It is not a section or a regulation and neither
            # rule below applies to it.
            continue
        if address[0] != expected:
            holds = "sections" if expected == "s" else "regulations"
            failures.append(
                f"{at} provisions[{index}]: {identifier} addresses "
                f"{instrument} as if it held "
                f"{'regulations' if address[0] == 'r' else 'sections'}, but it "
                f"holds {holds}; the instrument and the reference word "
                "disagree and one of them is wrong"
            )
        elif not instrument_holds(identifier):
            dotted = INSTRUMENT_DOTTED[instrument]
            failures.append(
                f"{at} provisions[{index}]: {identifier} names a provision "
                f"number {'without' if dotted else 'with'} a dot, and "
                f"{instrument} numbers every one of its provisions "
                f"{'with' if dotted else 'without'} one; the instrument cannot "
                "express this address, so the edge names nothing"
            )

    return failures


def _block_failures(chunk: dict[str, Any], at: str) -> list[str]:
    """Blocks that do not add back up to the chunk's text.

    `blocks` records the shape `text` was flattened from and must never become
    a second, drifting copy of the words. Joining them reproduces `text`
    exactly, so this is a total check rather than a sample: a dropped
    paragraph, a list item counted twice under its parent, or a block whose
    words were edited all fail here and nowhere else.
    """
    blocks = chunk.get("blocks")
    text = chunk.get("text")
    if not isinstance(blocks, list) or not isinstance(text, str):
        return []

    joined = " ".join(
        block["text"]
        for block in blocks
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    )
    if joined == text:
        return []
    return [
        f"{at}: joining blocks gives {len(joined)} characters and text holds "
        f"{len(text)}; blocks are the shape of the text and cannot hold "
        "different words from it"
    ]


def _link_failures(chunk: dict[str, Any], at: str) -> list[str]:
    """Links whose offsets do not name the words they claim.

    `text[start:end] == link.text` is the whole contract of the field: the
    offsets are what put a hyperlink back where the Manual set it, and an
    offset that has drifted underlines the wrong words while looking perfectly
    well-formed. The schema can check that the numbers are integers and no
    more, so the check lives here and runs over every link in the snapshot.
    """
    failures: list[str] = []
    links = chunk.get("links")
    text = chunk.get("text")
    if not isinstance(links, list) or not isinstance(text, str):
        return failures

    for index, link in enumerate(links):
        if not isinstance(link, dict):
            continue
        start, end, words = link.get("start"), link.get("end"), link.get("text")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        if not isinstance(words, str):
            continue
        if not 0 <= start <= end <= len(text):
            failures.append(
                f"{at} links[{index}]: [{start}, {end}) is not a span of a "
                f"{len(text)}-character text"
            )
            continue
        if text[start:end] != words:
            failures.append(
                f"{at} links[{index}]: text[{start}:{end}] is "
                f"{text[start:end]!r}, but the link says its words are "
                f"{words!r}; the offsets are what put the link back where the "
                "Manual set it, and these name different words"
            )

    return failures


def _emphasis_failures(chunk: dict[str, Any], at: str) -> list[str]:
    """Emphasis spans whose offsets do not name the words they claim.

    `_link_failures`' contract, applied to the other field that positions
    markup in the words, and load-bearing for the same reason: a span drifted
    by one character emphasises the wrong words and looks perfectly
    well-formed. The schema can say the numbers are integers and no more.

    Stricter than links in one respect — an empty span is a failure rather than
    the ordinary case. `links` keeps zero-width anchors because an anchor with
    no words still records a place the Manual put a link; `emphasis.py` drops
    empty elements, so one reaching a file means the extractor emitted
    something it does not believe in.
    """
    failures: list[str] = []
    spans = chunk.get("emphasis")
    text = chunk.get("text")
    if not isinstance(spans, list) or not isinstance(text, str):
        return failures

    for index, span in enumerate(spans):
        if not isinstance(span, dict):
            continue
        start, end, words = span.get("start"), span.get("end"), span.get("text")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        if not isinstance(words, str):
            continue
        if not 0 <= start < end <= len(text):
            failures.append(
                f"{at} emphasis[{index}]: [{start}, {end}) is not a non-empty "
                f"span of a {len(text)}-character text"
            )
            continue
        if text[start:end] != words:
            failures.append(
                f"{at} emphasis[{index}]: text[{start}:{end}] is "
                f"{text[start:end]!r}, but the span says its words are "
                f"{words!r}; the offsets are what put the emphasis back where "
                "the Manual set it, and these name different words"
            )

    return failures


def _amendment_failures(page: dict[str, Any], where: str) -> list[str]:
    """`amendments` that has stopped agreeing with its own head.

    `last_amended` and `amendment_note` are `amendments[0]`, and are fields
    because they are what most consumers read. Two representations of one fact
    is exactly the arrangement SCHEMA.md §What is deliberately absent warns
    about, and it is permitted here only because `parse_page` derives one from
    the other rather than reading the table twice. This is the check that keeps
    that true over the whole snapshot rather than at the one call site.

    Order is checked too: newest first is what makes `[0]` the head.
    """
    failures: list[str] = []
    rows = page.get("amendments")
    if not isinstance(rows, list):
        return failures

    dates = [row.get("date") for row in rows if isinstance(row, dict)]
    for index, value in enumerate(dates):
        try:
            date.fromisoformat(str(value))
        except (TypeError, ValueError):
            failures.append(
                f"{where}: page.amendments[{index}].date: {value!r} is not a date"
            )
    # ISO-8601 dates sort lexicographically, which is why this compares the
    # strings rather than re-parsing them.
    if dates != sorted(dates, reverse=True):
        failures.append(
            f"{where}: page.amendments is not newest-first, so amendments[0] "
            "is not the row last_amended names"
        )

    head = rows[0] if rows and isinstance(rows[0], dict) else None
    expected_date = head.get("date") if head else None
    expected_note = head.get("reason") if head else None

    if page.get("last_amended") != expected_date:
        failures.append(
            f"{where}: page.last_amended is {page.get('last_amended')!r} but "
            f"amendments[0].date is {expected_date!r}; they are one fact and "
            "one of them has drifted"
        )
    if page.get("amendment_note") != expected_note:
        failures.append(
            f"{where}: page.amendment_note is {page.get('amendment_note')!r} "
            f"but amendments[0].reason is {expected_note!r}; they are one fact "
            "and one of them has drifted"
        )
    return failures


def _heading_failures(chunk: dict[str, Any], at: str) -> list[str]:
    """`headings` that has stopped describing `heading_path`.

    `headings` carries a level, a source and an addressable ref for each
    ancestor, and deliberately not the ancestor's text — that is
    `heading_path[2:]`, and storing it twice would give two representations of
    one fact and a way for them to disagree (SCHEMA.md §What is deliberately
    absent). What makes that safe is checking the correspondence here, over the
    whole snapshot, rather than trusting it: one entry per heading, in the same
    order, and the leaf agreeing with `heading_source`.
    """
    failures: list[str] = []
    headings = chunk.get("headings")
    path = chunk.get("heading_path")
    if not isinstance(headings, list) or not isinstance(path, list):
        return failures

    # heading_path is [part_title, page title, *headings], so everything after
    # the first two is a heading and must have an entry.
    expected = max(len(path) - 2, 0)
    if len(headings) != expected:
        failures.append(
            f"{at}: headings holds {len(headings)} entries and heading_path "
            f"names {expected}; the two are one ancestry read two ways and "
            "cannot differ in length"
        )
        return failures

    source = chunk.get("heading_source")
    leaf = headings[-1].get("source") if headings else None
    if headings and leaf != source:
        failures.append(
            f"{at}: heading_source is {source!r} but the leaf of headings says "
            f"{leaf!r}; both name how the same heading was found"
        )
    if not headings and source is not None:
        failures.append(
            f"{at}: heading_source is {source!r} on a chunk with no headings; "
            "only the prose above a page's first heading has none, and its "
            "source is null"
        )
    return failures


def _location_failures(
    path: Path, where: str, page_ref: str, part_id: Any
) -> list[str]:
    """Is the record filed where its own fields say it should be?

    The filename is derived from the page_ref and the directory from the
    part_id (ARCHITECTURE.md §Snapshot layout). When they disagree the file is
    findable by neither, and a Part has quietly acquired a page belonging to
    another one — the failure this repo guards against above all others.
    """
    failures: list[str] = []
    expected = f"{page_ref.replace('/', '-')}.json"
    if path.name != expected:
        failures.append(f"{where}: page_ref {page_ref} belongs in a file named {expected}")

    if not isinstance(part_id, str):
        return failures
    if path.parent.name not in (part_id, RETIRED_SEGMENT):
        failures.append(
            f"{where}: part_id {part_id} belongs in pages/{part_id}/, not "
            f"pages/{path.parent.name}/"
        )
    if page_ref.split("/")[1:2] != [part_id]:
        failures.append(f"{where}: page_ref {page_ref} does not name part_id {part_id}")
    return failures


def _has_crawled(root: Path) -> bool:
    """Has a crawl ever written here?

    A snapshot that has never been crawled holds nothing to validate, and
    saying so is not the same as passing: `snapshot/` is empty in a fresh
    checkout, and a validator that fails there is a validator everybody learns
    to ignore. A snapshot that *has* been crawled and holds no pages is the
    opposite — a run that wrote a manifest and nothing else — and that is a
    failure loud enough to stop a commit.
    """
    return (root / "manifest.json").exists()


def validate_snapshot(root: Path) -> list[str]:
    """Return a list of human-readable failures. Empty means valid."""
    root = Path(root)
    if not (root / "pages").is_dir():
        if _has_crawled(root):
            return [
                f"{root}: manifest.json records a crawl, but there is no "
                "pages/ directory for it to have written"
            ]
        return []

    page_validator = _validator(config.PAGE_SCHEMA_PATH)
    chunk_validator = _validator(config.CHUNK_SCHEMA_PATH)

    failures: list[str] = []
    page_refs: dict[str, str] = {}
    chunk_refs: dict[str, str] = {}

    #: Everything a cross reference is allowed to resolve to.
    targets: set[str] = _inventory_refs(root)

    #: Cross references, held back until every file has been read: a reference
    #: forward to a page not yet walked is perfectly legal.
    pending: list[tuple[str, str]] = []

    for path, document in _page_documents(root):
        where = _where(path, root)

        if document is None:
            failures.append(f"{where}: not readable as a JSON object")
            continue

        page = document.get("page")
        chunks = document.get("chunks")

        if not isinstance(page, dict):
            failures.append(f"{where}: no 'page' object")
            continue
        if not isinstance(chunks, list):
            failures.append(f"{where}: 'chunks' is not a list")
            chunks = []

        failures.extend(_schema_failures(page, page_validator, f"{where} page"))
        failures.extend(_date_failures(page, where))
        failures.extend(_amendment_failures(page, where))

        page_ref = page.get("page_ref")
        if not isinstance(page_ref, str):
            failures.append(f"{where}: page.page_ref is missing or not a string")
            continue

        failures.extend(_location_failures(path, where, page_ref, page.get("part_id")))

        if page_ref in page_refs:
            failures.append(
                f"{where}: page_ref {page_ref} is already claimed by "
                f"{page_refs[page_ref]}"
            )
        page_refs[page_ref] = where
        targets.add(page_ref)

        ordinals: list[int] = []
        for index, chunk in enumerate(chunks):
            at = f"{where} chunks[{index}]"
            if not isinstance(chunk, dict):
                failures.append(f"{at}: not an object")
                continue

            failures.extend(_schema_failures(chunk, chunk_validator, at))

            chunk_ref = chunk.get("chunk_ref")
            if isinstance(chunk_ref, str):
                if chunk_ref in chunk_refs:
                    failures.append(
                        f"{at}: chunk_ref {chunk_ref} is already claimed by "
                        f"{chunk_refs[chunk_ref]}; a chunk_ref is a citation, "
                        "and two passages cannot share one"
                    )
                chunk_refs[chunk_ref] = at
                targets.add(chunk_ref)

            if chunk.get("page_ref") != page_ref:
                failures.append(
                    f"{at}: page_ref {chunk.get('page_ref')!r} does not match "
                    f"the record it is filed with ({page_ref})"
                )

            ordinal = chunk.get("ordinal")
            if isinstance(ordinal, int) and not isinstance(ordinal, bool):
                ordinals.append(ordinal)

            failures.extend(_provision_failures(chunk, at))
            failures.extend(_block_failures(chunk, at))
            failures.extend(_link_failures(chunk, at))
            failures.extend(_emphasis_failures(chunk, at))
            failures.extend(_heading_failures(chunk, at))

            references = chunk.get("internal_refs")
            if isinstance(references, list):
                pending.extend(
                    (at, reference["ref"])
                    for reference in references
                    if isinstance(reference, dict)
                    and isinstance(reference.get("ref"), str)
                )

            # A heading's `ref` is an address like any other, and a null one is
            # the Manual's own answer for a heading that owns no chunk.
            headings = chunk.get("headings")
            if isinstance(headings, list):
                pending.extend(
                    (f"{at} headings", heading["ref"])
                    for heading in headings
                    if isinstance(heading, dict)
                    and isinstance(heading.get("ref"), str)
                )

        expected = list(range(1, len(ordinals) + 1))
        if ordinals != expected:
            failures.append(
                f"{where}: ordinals are {ordinals}, expected {expected} — "
                "position on the page is what gives previous and next by "
                "arithmetic, and a gap in it silently breaks adjacency"
            )

    for at, ref in pending:
        if ref not in targets:
            failures.append(
                f"{at}: {ref} names no page or chunk in this snapshot or its "
                "sitemap; an unresolvable reference is dropped, not stored, "
                "because a consumer will try to follow it"
            )

    if not page_refs and _has_crawled(root):
        failures.append(
            f"{root}: manifest.json records a crawl, but pages/ holds no page "
            "records"
        )

    return failures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tmm_snapshot.validate",
        description=(
            "Validate the snapshot against schema/ and the invariants a "
            "schema cannot express. Exits non-zero on any failure."
        ),
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=config.SNAPSHOT_DIR,
        metavar="DIR",
        help="snapshot directory to validate (default: %(default)s)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.snapshot)
    failures = validate_snapshot(root)

    for failure in failures:
        print(failure, file=sys.stderr)
    if failures:
        print(f"{len(failures)} validation failure(s)", file=sys.stderr)
        return 1

    if not _has_crawled(root):
        print(f"{root}: nothing crawled yet, nothing to validate", file=sys.stderr)
        return 0

    pages = len(list((root / "pages").rglob("*.json")))
    print(f"{root}: {pages} page file(s) valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
