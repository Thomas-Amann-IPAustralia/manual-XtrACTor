"""Deterministic serialisation of the legislation snapshot.

Rule 2 is enforced here, the same way `tmm_snapshot.writer` enforces it: every
writer compares against the bytes on disk and skips the write when they are
identical. Do not rely on git to notice a no-op — rely on git to notice
*nothing*, because the file was never opened for writing.

Two decisions specific to this corpus are worth stating, because both are ways
a careless layout would turn one amendment into a whole-corpus diff.

**No `register_id` on a provision file.** It changes on every compilation, so
carrying it would rewrite all 316 files of the Act every time one section was
amended, and the readable diff — the entire point — would be gone. The
compilation identity lives on `instrument.json`, which is one file and *should*
change every time.

**No instrument-wide ordinal on a provision file.** Inserting section 41A would
renumber every section after it and rewrite them all. Document order lives in
`contents.json`, the analogue of the Manual's `sitemap.json`: an inserted
section changes the inventory, which is true and is one file.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from frl_snapshot import config
from frl_snapshot.api import Version
from frl_snapshot.docx import Span
from frl_snapshot.endnotes import Endnote
from frl_snapshot.references import provision_key
from frl_snapshot.structure import Container, Document, Provision
from frl_snapshot.units import Unit

PROVISIONS_DIRNAME = "provisions"
RAW_DIRNAME = "raw"
INSTRUMENT_FILENAME = "instrument.json"
CONTENTS_FILENAME = "contents.json"
ENDNOTES_FILENAME = "endnotes.json"


def _serialise(document: dict[str, Any]) -> str:
    """The one way this pipeline turns a document into bytes."""
    return json.dumps(document, **config.JSON_DUMP_KWARGS) + "\n"  # type: ignore[arg-type]


def _write_if_changed(path: Path, text: str) -> bool:
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except (OSError, UnicodeDecodeError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def utcnow() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def sha256(value: str | bytes) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def file_stem(ref: str) -> str:
    """'TMR1995/sch3/item1' -> 'TMR1995-sch3-item1'.

    The Manual's rule, applied to a longer address: replace the separator,
    change nothing else. Deterministic, sortable, and no provision ref carries
    a character a filesystem objects to — the parentheses that would are only
    ever in *unit* refs, which live inside a file rather than naming one.
    """
    return ref.replace("/", "-")


def provision_path(provision: Provision, root: Path) -> Path:
    return (
        root
        / provision.instrument
        / PROVISIONS_DIRNAME
        / provision.group
        / f"{file_stem(provision.ref)}.json"
    )


def raw_path(code: str, register_id: str, root: Path) -> Path:
    return root / code / RAW_DIRNAME / f"{code}-{register_id}.docx"


def iter_provision_files(code: str, root: Path) -> Iterator[Path]:
    directory = root / code / PROVISIONS_DIRNAME
    if directory.is_dir():
        yield from sorted(directory.rglob("*.json"))


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def _span_document(span: Span) -> dict[str, Any]:
    return {
        "text": span.text,
        "start": span.start,
        "end": span.end,
        "weight": span.weight,
    }


def _table_document(unit: Unit) -> dict[str, Any] | None:
    if unit.grid is None:
        return None
    return {
        "rows": [
            [
                {
                    "text": cell["text"],
                    "colspan": cell["colspan"],
                    "heading": cell["heading"],
                    "continues": cell["continues"],
                }
                for cell in row
            ]
            for row in unit.grid
        ]
    }


def _unit_document(unit: Unit) -> dict[str, Any]:
    document: dict[str, Any] = {
        "ref": unit.ref,
        "parent_ref": unit.parent_ref,
        "ordinal": unit.ordinal,
        "depth": unit.depth,
        "kind": unit.kind,
        "style": unit.style,
        "number": unit.number,
        "text": unit.text,
        "content_hash": sha256(unit.text),
    }
    if unit.number_collision:
        document["number_collision"] = True
    if unit.emphasis:
        # Document order, not sorted: an emphasis span is positional, and two
        # spans of the same words are two spans. Same argument as chunk.links.
        document["emphasis"] = [_span_document(span) for span in unit.emphasis]
    if unit.provisions:
        document["provisions"] = sorted(unit.provisions, key=provision_key)
    table = _table_document(unit)
    if table is not None:
        document["table"] = table
    return document


def provision_document(
    provision: Provision,
    units: list[Unit],
    instrument_name: str,
    captured_at: str,
) -> dict[str, Any]:
    text = " ".join(unit.text for unit in units)
    heading = (
        f"{provision.number}  {provision.title}"
        if provision.number and provision.title
        else (provision.title or provision.ref)
    )
    return {
        "ref": provision.ref,
        "instrument": provision.instrument,
        "kind": provision.kind,
        "number": provision.number,
        "title": provision.title,
        "containers": [container.ref for container in provision.containers],
        "heading_path": [
            instrument_name,
            *(f"{c.kind} {c.number}—{c.title}" for c in provision.containers),
            heading,
        ],
        "text": text,
        "content_hash": sha256(text),
        "units": [_unit_document(unit) for unit in units],
        "captured_at": captured_at,
        "extractor_version": config.EXTRACTOR_VERSION,
    }


def _content_of(document: dict[str, Any]) -> dict[str, Any]:
    """Everything except the field that says when we looked."""
    return {key: value for key, value in document.items() if key != "captured_at"}


def write_provision(
    provision: Provision, document: dict[str, Any], root: Path
) -> bool:
    """Write a provision file, carrying `captured_at` forward when unchanged.

    `captured_at` means *when this version of the provision was first seen*,
    not when the run happened — so a re-crawl that finds the same words must
    not move it. When the run happened is a property of the run and lives in
    `manifest.json`.
    """
    path = provision_path(provision, root)
    stored = read_json(path)
    if stored is not None and _content_of(stored) == _content_of(document):
        document = {**document, "captured_at": stored.get("captured_at", document["captured_at"])}
    return _write_if_changed(path, _serialise(document))


def _container_document(container: Container) -> dict[str, Any]:
    parent = container.ref.rsplit("/", 1)[0]
    return {
        "ref": container.ref,
        "kind": container.kind,
        "number": container.number,
        "title": container.title,
        "parent_ref": parent if "/" in parent else None,
    }


def contents_document(document: Document) -> dict[str, Any]:
    """The instrument's structure, in document order.

    The analogue of the Manual's `sitemap.json`: the inventory, separate from
    the records, so that an insertion moves one file rather than every file
    after it.
    """
    return {
        "instrument": document.instrument.code,
        "containers": [_container_document(c) for c in document.containers],
        "provisions": [
            {
                "ref": provision.ref,
                "kind": provision.kind,
                "number": provision.number,
                "title": provision.title,
                "container_ref": provision.container_ref,
                "ordinal": ordinal,
            }
            for ordinal, provision in enumerate(document.provisions, start=1)
        ],
    }


def _amendment_documents(version: Version) -> list[dict[str, Any]]:
    """The `reasons[]` array, flattened to a stable shape.

    Defensive because the structured fields are unreliable: `affectedByTitle`
    and `amendedByTitle` can each be null while the other holds the id, and
    `seriesType` is nullable even where it is populated elsewhere. The
    `markdown` blob is kept whatever happens, because it is the only field
    that is always there and it names the amending instrument in prose.
    """
    records: list[dict[str, Any]] = []
    for reason in version.reasons:
        if not isinstance(reason, dict):
            continue
        reference: dict[str, Any] = {}
        for field in ("affectedByTitle", "amendedByTitle"):
            candidate = reason.get(field)
            if isinstance(candidate, dict) and candidate.get("titleId"):
                reference = candidate
                break
        records.append(
            {
                "affect": reason.get("affect"),
                "markdown": reason.get("markdown"),
                "title_id": reference.get("titleId"),
                "name": reference.get("name"),
                "provisions": reference.get("provisions"),
                "series_type": reference.get("seriesType"),
                "year": reference.get("year"),
                "number": reference.get("number"),
            }
        )
    records.sort(key=lambda record: json.dumps(record, sort_keys=True))
    return records


def instrument_document(
    document: Document,
    version: Version,
    *,
    digest: str,
    size: int,
    unit_count: int,
    captured_at: str,
) -> dict[str, Any]:
    instrument = document.instrument
    return {
        "code": instrument.code,
        "title_id": instrument.title_id,
        "name": instrument.name,
        "symbol": instrument.symbol,
        "short_title": document.titles.get("short_title"),
        "long_title": document.titles.get("long_title"),
        "number_and_year": document.titles.get("number_and_year"),
        "made_under": document.titles.get("made_under"),
        "register_id": version.register_id,
        "compilation_number": version.compilation_number,
        "compilation_start": version.start_date,
        "status": version.status,
        "registered_at": version.registered_at,
        "has_unincorporated_amendments": version.has_unincorporated_amendments,
        "amendments": _amendment_documents(version),
        "document": {
            "format": "Word",
            "content_hash": digest,
            "bytes": size,
        },
        "counts": {
            "containers": len(document.containers),
            "provisions": len(document.provisions),
            "units": unit_count,
        },
        "captured_at": captured_at,
        "extractor_version": config.EXTRACTOR_VERSION,
    }


def endnotes_document(
    code: str, sections: list[Endnote], captured_at: str
) -> dict[str, Any]:
    return {
        "instrument": code,
        "endnotes": [
            {
                "ref": section.ref,
                "number": section.number,
                "title": section.title,
                "paragraphs": list(section.paragraphs),
                "tables": [
                    {"rows": [list(row) for row in table]} for table in section.tables
                ],
            }
            for section in sections
        ],
        "captured_at": captured_at,
        "extractor_version": config.EXTRACTOR_VERSION,
    }


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def write_instrument(code: str, document: dict[str, Any], root: Path) -> bool:
    path = root / code / INSTRUMENT_FILENAME
    stored = read_json(path)
    if stored is not None and _content_of(stored) == _content_of(document):
        document = {**document, "captured_at": stored.get("captured_at", document["captured_at"])}
    return _write_if_changed(path, _serialise(document))


def write_contents(code: str, document: dict[str, Any], root: Path) -> bool:
    return _write_if_changed(root / code / CONTENTS_FILENAME, _serialise(document))


def write_endnotes(code: str, document: dict[str, Any], root: Path) -> bool:
    path = root / code / ENDNOTES_FILENAME
    stored = read_json(path)
    if stored is not None and _content_of(stored) == _content_of(document):
        document = {**document, "captured_at": stored.get("captured_at", document["captured_at"])}
    return _write_if_changed(path, _serialise(document))


def write_raw(code: str, register_id: str, data: bytes, root: Path) -> bool:
    """The compiled `.docx`, verbatim.

    Kept for the same two reasons the Manual keeps its raw HTML: it is the
    ground truth a parser fix can be re-run against without going back to the
    Register, and it is the audit artefact — the evidence for what the law
    actually said on a date.

    Unlike the Manual's HTML it is a zip, so it diffs as a binary blob and
    contributes nothing readable to a pull request. The readable diff for this
    corpus is the provision files, which are finer-grained than the Manual's
    page files. Verified byte-stable across downloads: the Register pins every
    entry's zip timestamp to 1980-01-01, so re-fetching an unchanged
    compilation produces identical bytes.
    """
    path = raw_path(code, register_id, root)
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def read_raw(code: str, register_id: str, root: Path) -> bytes | None:
    path = raw_path(code, register_id, root)
    try:
        return path.read_bytes()
    except OSError:
        return None


def prune_provisions(code: str, live_refs: set[str], root: Path) -> list[str]:
    """Delete provision files whose refs are no longer in the instrument.

    A repealed section leaves the compiled document altogether — unlike a
    Manual page, which lingers in the nav — so there is nothing to retire it
    *to*. The evidence that it existed is the previous compilation's `.docx`,
    still on disk, plus git history. Returns what was removed, for the report.
    """
    removed: list[str] = []
    for path in iter_provision_files(code, root):
        stored = read_json(path)
        ref = (stored or {}).get("ref")
        if ref is None or ref in live_refs:
            continue
        path.unlink()
        removed.append(str(ref))
    for directory in sorted(
        (root / code / PROVISIONS_DIRNAME).glob("*"), reverse=True
    ):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    return sorted(removed)


def write_manifest(root: Path, stats: dict[str, Any]) -> None:
    _write_if_changed(root / "manifest.json", _serialise(stats))


def read_manifest(root: Path) -> dict[str, Any] | None:
    return read_json(root / "manifest.json")
