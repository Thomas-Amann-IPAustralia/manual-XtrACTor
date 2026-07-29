"""Build the static viewer bundle from `snapshot/`.

This is a *reader* of the snapshot and nothing else. `tmm_snapshot` does not
import it, it never writes inside `snapshot/`, and it adds no field to any
chunk: every chunk object it emits is a strict field-subset of the chunk on
disk, byte-for-byte identical in the fields it keeps. Anything the viewer needs
that the snapshot does not assert — a reverse citation index, a table count, a
facet vocabulary — is emitted *beside* the chunks, never on them, so that no
part of this file can ever become a reason to change the data contract.

Output (all under --out, which is build output and is not committed):

    index.html, app.css, app.js     the viewer, copied from viz/app/
    data/manual.json                parts, pages, facet vocabularies, corpus stats
    data/chunks.json                every chunk minus blocks/tables, plus sibling indexes
    pages/<Part>/<file>.json        the page files verbatim, for the deepest disclosure level

Deterministic: same snapshot in, byte-identical bundle out. No clock is read.

    python viz/build.py --snapshot snapshot --out viz/dist
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# The chunk fields the viewer carries in its index. A strict subset of
# chunk.schema.json — adding a name here is allowed, inventing one is not.
# `blocks` and `tables` are deliberately absent: they are two thirds of the
# corpus by weight and are fetched per page when a reader opens one.
INDEX_CHUNK_FIELDS = (
    "cases",
    "chunk_ref",
    "content_hash",
    "fragment",
    "heading_path",
    "heading_source",
    "headings",
    "internal_refs",
    "kind",
    "links",
    "ordinal",
    "page_ref",
    "provisions",
    "text",
)

# Page record fields carried through verbatim. The remaining keys of the page
# object below (part_title, nav_ordinal, chunk_count, file, retired) are the
# join with sitemap.json and the walk of pages/, and are named so it is obvious
# which side of the line they sit on.
INDEX_PAGE_FIELDS = (
    "amendment_note",
    "archived",
    "content_hash",
    "date_published",
    "h1",
    "images",
    "last_amended",
    "nav_title",
    "page_ref",
    "part_id",
    "url",
)

APP_DIR = Path(__file__).resolve().parent / "app"


class SnapshotError(RuntimeError):
    """The snapshot is not the shape this builder was written against."""


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _page_files(root: Path) -> list[Path]:
    """Every page file under pages/, live and retired, in a stable order."""
    return sorted((root / "pages").rglob("*.json"), key=lambda p: p.as_posix())


def load_snapshot(root: Path) -> dict[str, Any]:
    """Read the snapshot into memory. Raises rather than guessing."""
    if not (root / "sitemap.json").is_file():
        raise SnapshotError(
            f"{root}/sitemap.json is missing — run a crawl before building the viewer"
        )

    sitemap = _read_json(root / "sitemap.json")
    manifest_path = root / "manifest.json"
    manifest = _read_json(manifest_path) if manifest_path.is_file() else {}
    retired_path = root / "retired.json"
    retired = _read_json(retired_path) if retired_path.is_file() else []

    pages: list[dict[str, Any]] = []
    for path in _page_files(root):
        doc = _read_json(path)
        if not isinstance(doc, dict) or "page" not in doc or "chunks" not in doc:
            raise SnapshotError(f"{path} is not a page file: expected keys 'page' and 'chunks'")
        pages.append(
            {
                "path": path,
                "rel": path.relative_to(root / "pages").as_posix(),
                "record": doc["page"],
                "chunks": doc["chunks"],
                "retired": "_retired/" in path.relative_to(root / "pages").as_posix(),
            }
        )

    return {"sitemap": sitemap, "manifest": manifest, "retired": retired, "pages": pages}


def build_manual(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Parts, pages and facet vocabularies — the bundle that paints first."""
    sitemap = snapshot["sitemap"]
    nav = {p["page_ref"]: p for p in sitemap.get("pages", [])}
    part_titles = {p["part_id"]: p.get("part_title", p["part_id"]) for p in sitemap.get("parts", [])}

    pages: list[dict[str, Any]] = []
    part_chunks: dict[str, int] = defaultdict(int)
    part_pages: dict[str, int] = defaultdict(int)

    for entry in snapshot["pages"]:
        record = entry["record"]
        ref = record["page_ref"]
        nav_entry = nav.get(ref)
        if nav_entry is None and not entry["retired"]:
            # Rule 3: a live page absent from the nav has no determinable Part
            # membership beyond what it claims for itself, and this builder is
            # not the place to start inferring one.
            raise SnapshotError(
                f"{ref} has a page file but no sitemap entry, and is not retired — "
                "the snapshot is inconsistent, refusing to guess its place in the nav"
            )

        page = {field: record[field] for field in INDEX_PAGE_FIELDS if field in record}
        part_id = record["part_id"]
        page["part_title"] = part_titles.get(part_id, part_id)
        page["nav_ordinal"] = (nav_entry or {}).get("nav_ordinal", 0)
        page["chunk_count"] = len(entry["chunks"])
        page["file"] = entry["rel"]
        page["retired"] = entry["retired"]
        pages.append(page)

        part_pages[part_id] += 1
        part_chunks[part_id] += len(entry["chunks"])

    pages.sort(key=lambda p: (p["part_id"], p["nav_ordinal"], p["page_ref"]))

    parts = []
    for part in sitemap.get("parts", []):
        part_id = part["part_id"]
        parts.append(
            {
                "part_id": part_id,
                "part_title": part.get("part_title", part_id),
                "page_count": part_pages.get(part_id, 0),
                "chunk_count": part_chunks.get(part_id, 0),
                "nav_page_count": part.get("page_count", 0),
            }
        )
    known = {p["part_id"] for p in parts}
    for part_id in sorted(part_pages):  # a Part that only survives in _retired/
        if part_id not in known:
            parts.append(
                {
                    "part_id": part_id,
                    "part_title": part_titles.get(part_id, part_id),
                    "page_count": part_pages[part_id],
                    "chunk_count": part_chunks[part_id],
                    "nav_page_count": 0,
                }
            )
    parts.sort(key=_part_sort_key)

    return {
        "corpus": snapshot["manifest"].get("corpus", {}),
        "crawled_at": snapshot["manifest"].get("crawled_at"),
        "extractor_version": snapshot["manifest"].get("extractor_version"),
        "facets": _facets(snapshot),
        "pages": pages,
        "parts": parts,
        "retired": snapshot["retired"],
        "source": snapshot["manifest"].get("source", {}),
        "unreachable": snapshot["manifest"].get("run", {}).get("unreachable", []),
    }


def _part_sort_key(part: dict[str, Any]) -> tuple[int, str]:
    """Part10 after Part2. The nav's own order, which lexical sort destroys."""
    digits = "".join(c for c in part["part_id"][4:] if c.isdigit())
    return (int(digits) if digits else 0, part["part_id"])


def _facets(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Vocabularies with counts, so every filter control can say how much it holds."""
    instruments: dict[str, int] = defaultdict(int)
    provisions: dict[str, int] = defaultdict(int)
    cases: dict[str, dict[str, Any]] = {}
    kinds: dict[str, int] = defaultdict(int)
    heading_sources: dict[str, int] = defaultdict(int)
    extraction: dict[str, int] = defaultdict(int)
    certainty: dict[str, int] = defaultdict(int)
    amended_years: dict[str, int] = defaultdict(int)

    for entry in snapshot["pages"]:
        amended = entry["record"].get("last_amended")
        if amended:
            amended_years[amended[:4]] += 1
        for chunk in entry["chunks"]:
            kinds[chunk.get("kind", "body")] += 1
            # null is a real value here — the prose above a page's first
            # heading — so it gets a name of its own rather than being dropped.
            heading_sources[chunk.get("heading_source") or "none"] += 1
            for provision in chunk.get("provisions", []):
                pid = provision["id"]
                instruments[pid.split("/", 1)[0]] += 1
                provisions[pid] += 1
                extraction[provision["extraction"]] += 1
                certainty[provision.get("certainty") or "none"] += 1
            for case in chunk.get("cases", []):
                row = cases.setdefault(case["id"], {"citation": case["citation"], "count": 0})
                row["count"] += 1

    def ranked(counts: dict[str, int]) -> list[dict[str, Any]]:
        return [
            {"value": value, "count": count}
            for value, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ]

    return {
        "amended_years": ranked(amended_years),
        "cases": sorted(
            ({"id": cid, **row} for cid, row in cases.items()),
            key=lambda c: (-c["count"], c["id"]),
        ),
        "certainty": ranked(certainty),
        "extraction": ranked(extraction),
        "heading_sources": ranked(heading_sources),
        "instruments": ranked(instruments),
        "kinds": ranked(kinds),
        "provisions": ranked(provisions),
    }


def build_chunks(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Every chunk, minus the two heaviest fields, plus indexes beside them.

    The chunk objects here are field-subsets of the snapshot's own. The derived
    material — which chunk cites which, how many tables a chunk holds — is in
    sibling maps keyed by chunk_ref, never merged into the chunk itself.
    """
    chunks: list[dict[str, Any]] = []
    tables: dict[str, int] = {}
    cited_by: dict[str, list[str]] = defaultdict(list)

    for entry in snapshot["pages"]:
        for chunk in entry["chunks"]:
            ref = chunk["chunk_ref"]
            chunks.append({f: chunk[f] for f in INDEX_CHUNK_FIELDS if f in chunk})
            if chunk.get("tables"):
                tables[ref] = len(chunk["tables"])
            for reference in chunk.get("internal_refs", []):
                cited_by[reference["ref"]].append(ref)

    chunks.sort(key=lambda c: (c["page_ref"], c["ordinal"]))
    return {
        "chunks": chunks,
        "cited_by": {target: sorted(set(refs)) for target, refs in sorted(cited_by.items())},
        "tables": dict(sorted(tables.items())),
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8")


def build_site(snapshot_root: Path, out: Path) -> dict[str, int]:
    """Build the whole bundle. Returns counts for the CLI to report."""
    snapshot = load_snapshot(snapshot_root)
    manual = build_manual(snapshot)
    chunks = build_chunks(snapshot)

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    for name in ("index.html", "app.css", "app.js"):
        shutil.copyfile(APP_DIR / name, out / name)
    # GitHub Pages runs Jekyll over the upload otherwise, which drops _retired/.
    (out / ".nojekyll").write_text("", encoding="utf-8")

    _write_json(out / "data" / "manual.json", manual)
    _write_json(out / "data" / "chunks.json", chunks)

    for entry in snapshot["pages"]:
        destination = out / "pages" / entry["rel"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(entry["path"], destination)

    return {
        "parts": len(manual["parts"]),
        "pages": len(manual["pages"]),
        "chunks": len(chunks["chunks"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshot", type=Path, default=Path("snapshot"), help="snapshot root to read")
    parser.add_argument("--out", type=Path, default=Path("viz/dist"), help="directory to build into")
    args = parser.parse_args(argv)

    try:
        counts = build_site(args.snapshot.resolve(), args.out.resolve())
    except SnapshotError as exc:
        print(f"viz/build.py: {exc}", file=sys.stderr)
        return 1

    print(
        f"built {args.out}: {counts['parts']} parts, {counts['pages']} pages, "
        f"{counts['chunks']} chunks"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
