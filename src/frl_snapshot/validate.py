"""Validate snapshot/legislation/ against schema/ and against its own invariants.

    python -m frl_snapshot.validate

Reports every failure with a file and a JSON path rather than stopping at the
first, and exits non-zero if there is one. Schema validation is the floor; the
checks that matter most are the ones a schema cannot express, and each exists
because the thing it checks can be wrong while the file stays well-formed:

- **The join.** `" ".join(unit.text) == provision.text`. Without it the two
  fields drift into differently worded copies of the same law and nothing says
  which is right.
- **Emphasis offsets.** `text[start:end] == span.text`. An offset out by one
  underlines the wrong words and validates perfectly.
- **Ref uniqueness and parentage.** A duplicated address silently resolves to
  whichever record was written last.
- **Inventory agreement.** `contents.json` and the files on disk must name the
  same provisions, or a repealed section stays reachable through the inventory
  and a new one is invisible to it.

The last check is a *report*, not a failure: how many of the Manual's provision
edges land on a provision this corpus holds. That number is the join between
the two snapshots, and watching it is how a bad citation regex gets noticed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterator

from jsonschema import Draft202012Validator

from frl_snapshot import config, writer
from tmm_snapshot import config as tmm_config


def _load(path: Path) -> Draft202012Validator:
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


def _schema_failures(
    validator: Draft202012Validator, path: Path, document: dict[str, Any]
) -> Iterator[str]:
    for error in sorted(validator.iter_errors(document), key=lambda e: list(e.path)):
        location = "/".join(str(part) for part in error.path) or "<root>"
        yield f"{path}: {location}: {error.message}"


def _provision_failures(path: Path, document: dict[str, Any]) -> Iterator[str]:
    units = document.get("units", [])

    joined = " ".join(unit.get("text", "") for unit in units)
    if joined != document.get("text", ""):
        yield (
            f"{path}: units do not join back to text "
            f"({len(joined)} chars joined vs {len(document.get('text', ''))} stored)"
        )

    for ordinal, unit in enumerate(units, start=1):
        if unit.get("ordinal") != ordinal:
            yield (
                f"{path}: units/{ordinal - 1}/ordinal is {unit.get('ordinal')!r}, "
                f"expected {ordinal} — ordinals must be contiguous from 1"
            )

    refs = {unit.get("ref") for unit in units}
    for unit in units:
        parent = unit.get("parent_ref")
        if parent is not None and parent not in refs:
            yield (
                f"{path}: unit {unit.get('ref')!r} has parent_ref {parent!r}, "
                "which is not a unit of this provision"
            )

        text = unit.get("text", "")
        for index, span in enumerate(unit.get("emphasis", [])):
            start, end = span.get("start", 0), span.get("end", 0)
            if text[start:end] != span.get("text"):
                yield (
                    f"{path}: unit {unit.get('ref')!r} emphasis/{index} covers "
                    f"{text[start:end]!r}, not {span.get('text')!r}"
                )

    for unit in units:
        if unit.get("content_hash") != writer.sha256(unit.get("text", "")):
            yield f"{path}: unit {unit.get('ref')!r} content_hash does not match its text"

    if document.get("content_hash") != writer.sha256(document.get("text", "")):
        yield f"{path}: content_hash does not match text"


def validate(root: Path) -> tuple[list[str], dict[str, Any]]:
    """Every failure found, and a summary worth printing on success."""
    failures: list[str] = []
    provision_schema = _load(config.PROVISION_SCHEMA_PATH)
    instrument_schema = _load(config.INSTRUMENT_SCHEMA_PATH)

    seen_refs: dict[str, Path] = {}
    unit_refs: set[str] = set()
    totals = {"instruments": 0, "provisions": 0, "units": 0}

    for code in sorted(config.INSTRUMENTS):
        directory = root / code
        if not directory.is_dir():
            continue
        totals["instruments"] += 1

        instrument_path = directory / writer.INSTRUMENT_FILENAME
        instrument = writer.read_json(instrument_path)
        if instrument is None:
            failures.append(f"{instrument_path}: missing or unreadable")
            continue
        failures.extend(
            _schema_failures(instrument_schema, instrument_path, instrument)
        )

        contents_path = directory / writer.CONTENTS_FILENAME
        contents = writer.read_json(contents_path) or {}
        inventory = {
            entry.get("ref") for entry in contents.get("provisions", [])
        }

        on_disk: set[str] = set()
        for path in writer.iter_provision_files(code, root):
            document = writer.read_json(path)
            if document is None:
                failures.append(f"{path}: unreadable JSON")
                continue

            failures.extend(_schema_failures(provision_schema, path, document))
            failures.extend(_provision_failures(path, document))

            ref = document.get("ref")
            if ref in seen_refs:
                failures.append(
                    f"{path}: ref {ref!r} is also claimed by {seen_refs[ref]}"
                )
            else:
                seen_refs[str(ref)] = path
            on_disk.add(str(ref))

            if document.get("instrument") != code:
                failures.append(
                    f"{path}: instrument is {document.get('instrument')!r} but "
                    f"the file sits under {code}"
                )

            unit_refs.update(
                str(unit.get("ref")) for unit in document.get("units", [])
            )
            totals["provisions"] += 1
            totals["units"] += len(document.get("units", []))

        for missing in sorted(inventory - on_disk):
            failures.append(
                f"{contents_path}: names {missing!r}, which has no file on disk"
            )
        for extra in sorted(on_disk - inventory):
            failures.append(
                f"{contents_path}: does not name {extra!r}, which is on disk"
            )

    summary = dict(totals)
    summary["addressable"] = len(seen_refs) + len(unit_refs)
    summary["manual_edges"] = _manual_coverage(seen_refs.keys() | unit_refs)
    return failures, summary


def _manual_coverage(known: set[str]) -> dict[str, int]:
    """How many of the Manual's provision edges land on a provision we hold.

    A report, never a failure. The Manual legitimately cites instruments this
    corpus does not carry — the Acts Interpretation Act, the Criminal Code, the
    repealed 1955 Act — so an unresolved edge is usually correct. The number to
    watch is the *resolved* count against `TMA1995` and `TMR1995` specifically:
    if it falls, a citation regex or a numbering assumption has moved.
    """
    counts = {"total": 0, "in_scope": 0, "resolved": 0}
    pages = tmm_config.PAGES_DIR
    if not pages.is_dir():
        return counts

    for path in pages.rglob("*.json"):
        document = writer.read_json(path)
        if document is None:
            continue
        for chunk in document.get("chunks", []):
            for edge in chunk.get("provisions", []):
                identifier = str(edge.get("id", ""))
                counts["total"] += 1
                if identifier.split("/", 1)[0] not in config.INSTRUMENTS:
                    continue
                counts["in_scope"] += 1
                if identifier in known:
                    counts["resolved"] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m frl_snapshot.validate")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)

    root = args.root or config.snapshot_root()
    if not root.is_dir():
        print(f"no legislation snapshot at {root}", file=sys.stderr)
        return 1

    failures, summary = validate(root)
    for failure in failures:
        print(failure, file=sys.stderr)

    edges = summary["manual_edges"]
    print(
        f"{summary['instruments']} instruments, {summary['provisions']} provisions, "
        f"{summary['units']} units, {summary['addressable']} addressable refs"
    )
    if edges["in_scope"]:
        print(
            f"Manual provision edges: {edges['resolved']}/{edges['in_scope']} "
            f"in-scope edges resolve ({edges['total']} edges total)"
        )

    if failures:
        print(f"{len(failures)} failures", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
