"""Orchestration and CLI for the legislation snapshot.

    python -m frl_snapshot.crawl                     # probe, fetch what moved
    python -m frl_snapshot.crawl --from-raw --force  # re-parse, no network
    python -m frl_snapshot.crawl --dry-run           # report, write nothing

The skip gate is one small JSON GET per instrument. `Versions/Find` returns the
`registerId` of the current compilation, and that identifier changes if and
only if a new compilation was registered — so comparing it to the one on disk
answers "has this law been amended" exactly, without downloading anything and
without hashing anything. It is a better gate than the Manual's conditional
GET: semantically meaningful rather than incidental, and it cannot be defeated
by a CMS rewriting an id attribute.

The gate has one blind spot and it is recorded rather than papered over.
`hasUnincorporatedAmendments` true means amendments have commenced but are not
yet in any compilation: the document on the Register is out of date and its
`registerId` has not moved. Nothing can be fetched in that state — there is no
newer document to fetch — so the flag is written to `instrument.json` and
surfaced in the run report, and a reader knows the snapshot is behind.

**Never treat a failed probe as "unchanged".** An API error raises. Recording
a law as current because the Register did not answer is the failure mode that
freezes a snapshot silently for months, which is the one thing worse than a
crawl that stops.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from frl_snapshot import config, docx, endnotes, references, structure, units, writer
from frl_snapshot.api import ApiError, FrlClient, Version
from frl_snapshot.config import Instrument


class CrawlError(Exception):
    """The run cannot honestly continue."""


@dataclass
class InstrumentResult:
    code: str
    status: str  # 'amended' | 'unchanged' | 'new' | 'reparsed'
    register_id: str | None = None
    compilation_number: str | None = None
    provisions: int = 0
    units_cut: int = 0
    files_written: int = 0
    removed: list[str] = field(default_factory=list)
    has_unincorporated_amendments: bool | None = None
    #: How this run got the bytes: 'api', 'site' or 'raw'. Reported, never
    #: written to instrument.json — it describes the run, not the document,
    #: and a field that flips between --from-raw and a live crawl would
    #: rewrite the file on every alternation for no change in content.
    source: str = "raw"
    note: str | None = None


def _stored_state(code: str, root: Path) -> dict[str, Any] | None:
    return writer.read_json(root / code / writer.INSTRUMENT_FILENAME)


def _verify_size(client: FrlClient, version: Version, data: bytes) -> None:
    """Check the download against the Register's own byte count.

    A truncated body is still a well-formed zip that parses into a shorter Act,
    and the shorter Act validates. This is the only check that catches it
    before it overwrites a good snapshot.
    """
    try:
        renditions = client.documents(version.register_id)
    except ApiError:
        return  # advisory; the parse-level guards still apply
    for rendition in renditions:
        if rendition.get("format") == "Word" and rendition.get("type") == "Primary":
            expected = rendition.get("sizeInBytes")
            if isinstance(expected, int) and expected != len(data):
                raise CrawlError(
                    f"{version.title_id}: downloaded {len(data)} bytes but the "
                    f"Register says the document is {expected}. Refusing to "
                    "overwrite the snapshot with a partial download."
                )
            return


def process(
    instrument: Instrument,
    *,
    root: Path,
    client: FrlClient | None,
    from_raw: bool,
    force: bool,
    dry_run: bool,
    now: str,
) -> InstrumentResult:
    stored = _stored_state(instrument.code, root)

    if from_raw:
        if stored is None:
            raise CrawlError(
                f"{instrument.code}: --from-raw needs a snapshot to re-parse "
                "and there is none on disk."
            )
        register_id = str(stored["register_id"])
        data = writer.read_raw(instrument.code, register_id, root)
        if data is None:
            raise CrawlError(
                f"{instrument.code}: no raw document for {register_id} under "
                f"{writer.raw_path(instrument.code, register_id, root)}."
            )
        version = _version_from_stored(stored)
        status = "reparsed"
        source = "raw"
    else:
        if client is None:  # pragma: no cover - guarded by the CLI
            raise CrawlError("a live run needs a client")
        version = client.version(instrument.title_id)
        known = stored.get("register_id") if stored else None
        if known == version.register_id and not force:
            return InstrumentResult(
                code=instrument.code,
                status="unchanged",
                register_id=version.register_id,
                compilation_number=version.compilation_number,
                has_unincorporated_amendments=version.has_unincorporated_amendments,
            )

        status = (
            "new"
            if known is None
            else ("amended" if known != version.register_id else "reparsed")
        )

        # A --force re-cut of a compilation already on disk costs the Register
        # nothing: the raw document for a given registerId can never change,
        # because a registerId names one immutable compilation.
        data = writer.read_raw(instrument.code, version.register_id, root)
        source = "raw"
        if data is None:
            source = "api"
            data = client.download(instrument.title_id, start_date=version.start_date)
            if data is None:
                raise CrawlError(
                    f"{instrument.code}: the Register served no Word document "
                    f"for {instrument.title_id} at compilation "
                    f"{version.compilation_number}. Both documents/find() and "
                    "the site fallback returned nothing."
                )
            _verify_size(client, version, data)

    document = structure.parse_document(docx.read_document(data), instrument)
    sections = endnotes.split_endnotes(document.endnote_blocks, instrument.code)

    cut: list[tuple[structure.Provision, list[units.Unit]]] = []
    unit_total = 0
    for provision in document.provisions:
        pieces = units.split_units(provision)
        pieces = [
            _with_references(unit) for unit in pieces
        ]
        unit_total += len(pieces)
        cut.append((provision, pieces))

    result = InstrumentResult(
        code=instrument.code,
        status=status,
        register_id=version.register_id,
        compilation_number=version.compilation_number,
        provisions=len(document.provisions),
        units_cut=unit_total,
        has_unincorporated_amendments=version.has_unincorporated_amendments,
        source=source,
    )

    if dry_run:
        return result

    written = 0
    if writer.write_raw(instrument.code, version.register_id, data, root):
        written += 1
    for provision, pieces in cut:
        record = writer.provision_document(
            provision, pieces, instrument.name, now
        )
        if writer.write_provision(provision, record, root):
            written += 1
    if writer.write_contents(
        instrument.code, writer.contents_document(document), root
    ):
        written += 1
    if writer.write_endnotes(
        instrument.code, writer.endnotes_document(instrument.code, sections, now), root
    ):
        written += 1
    if writer.write_instrument(
        instrument.code,
        writer.instrument_document(
            document,
            version,
            digest=writer.sha256(data),
            size=len(data),
            unit_count=unit_total,
            captured_at=now,
        ),
        root,
    ):
        written += 1

    result.removed = writer.prune_provisions(
        instrument.code, {provision.ref for provision, _ in cut}, root
    )
    result.files_written = written
    return result


def _with_references(unit: units.Unit) -> units.Unit:
    """Attach the statutory references the unit's own words carry."""
    from dataclasses import replace

    found = references.extract_provisions(unit.text)
    return replace(unit, provisions=tuple(found))


def _version_from_stored(stored: dict[str, Any]) -> Version:
    """Rebuild the version record from `instrument.json` for an offline run.

    `--from-raw` re-parses what is already on disk, so the compilation identity
    has to come from disk too. Anything the stored record does not carry stays
    absent rather than being invented.
    """
    return Version(
        title_id=str(stored.get("title_id", "")),
        register_id=str(stored["register_id"]),
        compilation_number=stored.get("compilation_number"),
        name=stored.get("name"),
        start=(f"{stored['compilation_start']}T00:00:00" if stored.get("compilation_start") else None),
        end=None,
        status=stored.get("status"),
        is_latest=None,
        has_unincorporated_amendments=stored.get("has_unincorporated_amendments"),
        registered_at=stored.get("registered_at"),
        reasons=tuple(
            {
                "affect": record.get("affect"),
                "markdown": record.get("markdown"),
                "affectedByTitle": {
                    "titleId": record.get("title_id"),
                    "name": record.get("name"),
                    "provisions": record.get("provisions"),
                    "seriesType": record.get("series_type"),
                    "year": record.get("year"),
                    "number": record.get("number"),
                },
            }
            for record in stored.get("amendments", [])
        ),
    )


def _corpus(root: Path) -> dict[str, int]:
    provisions = 0
    unit_count = 0
    raw_bytes = 0
    instruments = 0
    for code in sorted(config.INSTRUMENTS):
        directory = root / code
        if not directory.is_dir():
            continue
        instruments += 1
        for path in writer.iter_provision_files(code, root):
            record = writer.read_json(path)
            if record is None:
                continue
            provisions += 1
            unit_count += len(record.get("units", []))
        raw_dir = directory / writer.RAW_DIRNAME
        if raw_dir.is_dir():
            raw_bytes += sum(path.stat().st_size for path in raw_dir.glob("*.docx"))
    return {
        "instruments": instruments,
        "provisions": provisions,
        "units": unit_count,
        "raw_bytes": raw_bytes,
    }


def render_report(results: list[InstrumentResult]) -> str:
    lines = ["# Legislation snapshot", ""]
    for result in sorted(results, key=lambda item: item.code):
        lines.append(
            f"- **{result.code}** — {result.status}"
            + (
                f", compilation {result.compilation_number} ({result.register_id})"
                if result.register_id
                else ""
            )
        )
        if result.status != "unchanged":
            lines.append(
                f"  - {result.provisions} provisions, {result.units_cut} units, "
                f"{result.files_written} files written"
            )
        if result.removed:
            lines.append(f"  - removed: {', '.join(result.removed)}")
        if result.has_unincorporated_amendments:
            lines.append(
                "  - **has unincorporated amendments** — amendments have "
                "commenced but are not in this compilation, so the snapshot "
                "is behind the law in force."
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m frl_snapshot.crawl",
        description="Snapshot the Trade Marks Act and Regulations from the "
        "Federal Register of Legislation.",
    )
    parser.add_argument(
        "--instrument",
        action="append",
        choices=sorted(config.INSTRUMENTS),
        help="Limit the run to one instrument. Repeatable.",
    )
    parser.add_argument(
        "--from-raw",
        action="store_true",
        help="Re-parse snapshot/legislation/*/raw/ without touching the "
        "network. Run this after every parser change.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore the registerId gate and re-cut everything.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report, write nothing."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Snapshot root. Defaults to snapshot/legislation/.",
    )
    args = parser.parse_args(argv)

    root = args.root or config.snapshot_root()
    codes = args.instrument or sorted(config.INSTRUMENTS)
    started = writer.utcnow()

    client: FrlClient | None = None
    results: list[InstrumentResult] = []
    try:
        if not args.from_raw:
            client = FrlClient()
            client.check_robots()
        for code in codes:
            results.append(
                process(
                    config.INSTRUMENTS[code],
                    root=root,
                    client=client,
                    from_raw=args.from_raw,
                    force=args.force,
                    dry_run=args.dry_run,
                    now=started,
                )
            )
    except (ApiError, CrawlError, structure.StructureError, units.UnitError,
            docx.DocumentShapeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        if client is not None:
            client.close()

    print(render_report(results), end="")

    if not args.dry_run:
        writer.write_manifest(
            root,
            {
                "corpus": _corpus(root),
                "crawled_at": started,
                "finished_at": writer.utcnow(),
                "extractor_version": config.EXTRACTOR_VERSION,
                "run": {
                    "dry_run": False,
                    "force": args.force,
                    "from_raw": args.from_raw,
                    "instruments": codes,
                    "amended": sorted(
                        r.code for r in results if r.status == "amended"
                    ),
                    "unchanged": sorted(
                        r.code for r in results if r.status == "unchanged"
                    ),
                    "files_written": sum(r.files_written for r in results),
                    "provisions_cut": sum(r.provisions for r in results),
                    "units_cut": sum(r.units_cut for r in results),
                    "removed": sorted(
                        ref for r in results for ref in r.removed
                    ),
                    "sources": {r.code: r.source for r in sorted(results, key=lambda i: i.code)},
                    "unincorporated_amendments": sorted(
                        r.code for r in results if r.has_unincorporated_amendments
                    ),
                },
            },
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
