"""Deterministic serialisation to snapshot/.

Owned by T7. The signatures below are fixed — see ARCHITECTURE.md.

This module is where rule 2 is enforced. Every writer here must compare against
the bytes already on disk and skip the write when they are identical: do not
rely on git to notice a no-op change, rely on git to notice *nothing*, because
the file was never touched.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from tmm_snapshot import config
from tmm_snapshot.chunker import Chunk
from tmm_snapshot.page import PageRecord

#: Pages that vanished from the nav are moved under pages/_retired/, and the
#: run they vanished in is recorded in this index. The index sits at the
#: snapshot root rather than inside pages/ so that everything under pages/ is a
#: page file and the validator can walk the tree without special cases.
RETIRED_INDEX_NAME = "retired.json"


def _serialise(document: dict[str, Any]) -> str:
    """The one way this pipeline turns a document into bytes.

    Sorted keys, two-space indent, real UTF-8, trailing newline. Stated once
    here so that no caller can serialise a snapshot file a second way.
    """
    return json.dumps(document, **config.JSON_DUMP_KWARGS) + "\n"  # type: ignore[arg-type]


def _write_if_changed(path: Path, text: str) -> bool:
    """Write `text` to `path` only if the bytes differ. True if written."""
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except (OSError, UnicodeDecodeError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def utcnow() -> str:
    """Now, as the schema's date-time. Seconds resolution is plenty."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------


def file_stem(page_ref: str) -> str:
    """'TMM/Part22/1' -> 'TMM-Part22-1'. Deterministic, sortable, no collisions."""
    return page_ref.replace("/", "-")


def page_path(page_ref: str, part_id: str, root: Path) -> Path:
    return Path(root) / "pages" / part_id / f"{file_stem(page_ref)}.json"


def retired_path(page_ref: str, part_id: str, root: Path) -> Path:
    return Path(root) / "pages" / "_retired" / part_id / f"{file_stem(page_ref)}.json"


def raw_path(page_ref: str, root: Path) -> Path:
    """snapshot/raw/<Part>/<stem>.html. The Part comes out of the ref itself."""
    part_id = page_ref.split("/")[1]
    return Path(root) / "raw" / part_id / f"{file_stem(page_ref)}.html"


def iter_page_files(root: Path, *, retired: bool = False) -> Iterator[Path]:
    """Every page file in the snapshot, in a stable order.

    Retired pages are excluded by default: they are history, not inventory.
    """
    pages = Path(root) / "pages"
    if not pages.is_dir():
        return
    retired_dir = pages / "_retired"
    for path in sorted(pages.rglob("*.json")):
        if (retired_dir in path.parents) == retired:
            yield path


def read_page_file(path: Path) -> dict[str, Any] | None:
    """Load a page file, or None if it is absent or unreadable.

    Unreadable is treated as absent on purpose: the only callers are the skip
    logic and the retirement sweep, and a corrupt file should be rewritten
    rather than trusted.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return document if isinstance(document, dict) else None


# --------------------------------------------------------------------------
# Page files
# --------------------------------------------------------------------------


def _provision_key(provision: dict) -> tuple[str, ...]:
    return (
        str(provision.get("id", "")),
        str(provision.get("extraction", "")),
        str(provision.get("certainty") or ""),
        str(provision.get("mention") or ""),
    )


def _case_key(case: dict) -> tuple[str, ...]:
    return (str(case.get("id", "")), str(case.get("citation", "")))


def _chunk_document(chunk: Chunk) -> dict[str, Any]:
    """One chunk, with every array in its stable order.

    Sorted by id rather than by order of appearance: the reading order of a
    citation list is a property of the sentence it came from, not of the chunk,
    and letting it drive the file order means moving one paragraph rewrites
    every list on the page. See SCHEMA.md §Worked example.
    """
    document = asdict(chunk)
    document["provisions"] = sorted(chunk.provisions, key=_provision_key)
    document["cases"] = sorted(chunk.cases, key=_case_key)
    document["internal_refs"] = sorted(set(chunk.internal_refs))
    return document


def _page_document(page: PageRecord, crawled_at: str) -> dict[str, Any]:
    return {
        "amendment_note": page.amendment_note,
        "archived": page.archived,
        "content_hash": page.content_hash,
        "crawled_at": crawled_at,
        "date_published": _iso(page.date_published),
        "extractor_version": page.extractor_version,
        "h1": page.h1,
        "images": [dict(image) for image in page.images],
        "last_amended": _iso(page.last_amended),
        "nav_title": page.nav_title,
        "page_ref": page.page_ref,
        "part_id": page.part_id,
        "url": page.url,
    }


def _content_of(document: dict[str, Any]) -> dict[str, Any]:
    """The document minus its timestamp — everything derived from the source.

    Two documents with the same content are the same record, however long ago
    it was first seen.
    """
    page = document.get("page")
    fields = {k: v for k, v in page.items() if k != "crawled_at"} if isinstance(page, dict) else {}
    return {"page": fields, "chunks": document.get("chunks", [])}


def page_fields_unchanged(stored_page: dict[str, Any] | None, page: PageRecord) -> bool:
    """Does a stored page record already say exactly what this one says?

    Gate 2 of the skip logic. Deliberately compares every field rather than
    `content_hash` alone: a Part renamed in the nav changes `nav_title` and
    `part_id` without touching a word of the body, and a hash-only gate would
    skip the page and leave the snapshot asserting the old name. The timestamp
    is excluded because it is not derived from the source.
    """
    if not isinstance(stored_page, dict):
        return False
    current = _page_document(page, crawled_at="")
    return {k: v for k, v in stored_page.items() if k != "crawled_at"} == {
        k: v for k, v in current.items() if k != "crawled_at"
    }


def render_page(
    page: PageRecord,
    chunks: list[Chunk],
    root: Path,
    *,
    now: str | None = None,
) -> tuple[Path, str, bool]:
    """The bytes a page file would hold, and whether they differ from disk.

    Separated out so that `--dry-run` can report what a crawl would change
    without writing it; `write_page` is this plus the write.

    **On `crawled_at`.** The schema requires it and rule 2 forbids a run
    timestamp in a page file. Both are satisfied by writing it once and keeping
    it for as long as the content is unchanged — the `first_seen`-style date
    ARCHITECTURE.md §Byte-stability permits. It is therefore carried over from
    the existing file whenever everything else in the document matches, and
    refreshed only by a crawl that actually changed the page. Read it as 'when
    this version of the page was first seen', never as 'when we last looked':
    that question is answered by manifest.json.
    """
    path = page_path(page.page_ref, page.part_id, root)
    existing = read_page_file(path)

    ordered = sorted(chunks, key=lambda chunk: chunk.ordinal)
    document: dict[str, Any] = {
        "chunks": [_chunk_document(chunk) for chunk in ordered],
        "page": _page_document(page, crawled_at=""),
    }

    carried: str | None = None
    if existing is not None and _content_of(existing) == _content_of(document):
        stamp = existing.get("page", {}).get("crawled_at")
        if isinstance(stamp, str) and stamp:
            carried = stamp

    document["page"] = _page_document(page, crawled_at=carried or now or utcnow())
    serialised = _serialise(document)

    changed = True
    try:
        changed = path.read_text(encoding="utf-8") != serialised
    except (OSError, UnicodeDecodeError):
        pass
    return path, serialised, changed


def write_page(
    page: PageRecord,
    chunks: list[Chunk],
    root: Path,
    *,
    now: str | None = None,
) -> bool:
    """Write snapshot/pages/<Part>/<page_ref>.json. True if bytes changed.

    `now` is an addition to the signature in ARCHITECTURE.md rather than a
    change to it: keyword-only, defaulted, and there so that a test can pin the
    timestamp.
    """
    path, serialised, changed = render_page(page, chunks, root, now=now)
    if not changed:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialised, encoding="utf-8")
    return True


def write_raw(page_ref: str, html: str, root: Path) -> bool:
    """Write snapshot/raw/<Part>/<page_ref>.html verbatim. True if changed.

    Unmodified and uncompressed: this is the audit artefact and the input to
    every re-parse. A gzipped file diffs as a binary blob.
    """
    return _write_if_changed(raw_path(page_ref, root), html)


def read_raw(page_ref: str, root: Path) -> str | None:
    """The stored source of a page, or None. The input to `crawl --from-raw`."""
    try:
        return raw_path(page_ref, root).read_text(encoding="utf-8")
    except OSError:
        return None


# --------------------------------------------------------------------------
# Retirement
# --------------------------------------------------------------------------


def read_retired(root: Path) -> dict[str, dict[str, str]]:
    """The retirement index, keyed by page_ref. Empty when nothing has gone."""
    try:
        raw = (Path(root) / RETIRED_INDEX_NAME).read_text(encoding="utf-8")
        document = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return {}
    entries = document.get("retired", []) if isinstance(document, dict) else []
    return {
        entry["page_ref"]: entry
        for entry in entries
        if isinstance(entry, dict) and "page_ref" in entry
    }


def _write_retired_index(root: Path, entries: dict[str, dict[str, str]]) -> None:
    path = Path(root) / RETIRED_INDEX_NAME
    if not entries:
        path.unlink(missing_ok=True)
        return
    document = {"retired": [entries[ref] for ref in sorted(entries)]}
    _write_if_changed(path, _serialise(document))


def retire(root: Path, live_refs: set[str], retired_at: str) -> list[str]:
    """Move pages absent from the inventory to pages/_retired/. Returns refs.

    A page that disappears from the nav is not deleted. Old citations must stay
    resolvable, and a Part being restructured is exactly the event you most
    want a record of — see ARCHITECTURE.md §Retirement and SOURCE_NOTES.md §10.

    The raw HTML stays where it is: it is the evidence for what the Manual said
    on a date, and that does not stop being true when the page goes.

    Callers must pass a `live_refs` derived from a *complete* crawl. A filtered
    run knows nothing about the Parts it did not visit, and retiring from one
    would empty the snapshot.
    """
    entries = read_retired(root)
    gone: list[str] = []

    for path in iter_page_files(root):
        document = read_page_file(path)
        page = document.get("page", {}) if document else {}
        page_ref = page.get("page_ref") if isinstance(page, dict) else None
        if not isinstance(page_ref, str) or page_ref in live_refs:
            continue

        part_id = str(page.get("part_id", ""))
        destination = retired_path(page_ref, part_id, root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        path.replace(destination)
        entries[page_ref] = {
            "page_ref": page_ref,
            "part_id": part_id,
            "retired_at": retired_at,
            "url": str(page.get("url", "")),
        }
        gone.append(page_ref)

    if gone:
        _write_retired_index(root, entries)
    return sorted(gone)


def unretire(root: Path, page_ref: str, part_id: str) -> bool:
    """Drop a retired copy of a page that has come back. True if there was one.

    A restructure that renames a page and then renames it back would otherwise
    leave two files claiming the same chunk_refs, which the validator rejects
    and a consumer cannot disambiguate.
    """
    path = retired_path(page_ref, part_id, root)
    if not path.exists():
        return False
    path.unlink()
    entries = read_retired(root)
    if entries.pop(page_ref, None) is not None:
        _write_retired_index(root, entries)
    return True


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------


def write_manifest(root: Path, stats: dict) -> None:
    """Write snapshot/manifest.json — the only file that changes every run.

    No skip check here, deliberately: run timing belongs in exactly one file
    and this is it. What a run records is the caller's business; this function
    only decides how it is spelled.
    """
    path = Path(root) / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_serialise(dict(stats)), encoding="utf-8")
