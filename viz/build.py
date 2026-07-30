"""Build the static viewer bundle from `snapshot/`.

This is a *reader* of the snapshot and nothing else. `tmm_snapshot` and
`frl_snapshot` do not import it, it never writes inside `snapshot/`, and it
adds no field to any chunk or provision: every chunk and provision object it
emits is a strict field-subset of the record on disk, byte-for-byte identical
in the fields it keeps. Anything the viewer needs that the snapshot does not
assert — a reverse citation index, a table count, a facet vocabulary, the
Manual-to-legislation join — is emitted *beside* those records, never on them,
so that no part of this file can ever become a reason to change the data
contract.

Output (all under --out, which is build output and is not committed):

    index.html, app.css, app.js      the viewer, copied from viz/app/
    graph.html, graph.css, graph.js  the cross-reference network view, copied from viz/app/
    data/manual.json                 parts, pages, facet vocabularies, corpus stats
    data/chunks.json                 every chunk minus blocks/tables, plus sibling indexes
    data/legislation.json            instruments, contents, provisions minus units, plus
                                     the citation graph and the join with the Manual
    data/graph.json                  Parts and cited provisions as nodes, the three citation
                                     fields as edges — a view over the three bundles above,
                                     not a fourth reading of the snapshot
    pages/<Part>/<file>.json        the page files verbatim, for the deepest disclosure level
    legislation/<code>/…            the instrument, contents, endnote and provision files verbatim

The legislation half is optional: a snapshot with no `legislation/` directory
builds a Manual-only bundle, and the viewer notices and says so.

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

# The provision fields the viewer carries in its index. A strict subset of
# provision.schema.json, and the same bargain the chunk index strikes: `units`
# is absent — it is the bulk of the corpus and is fetched per provision when a
# reader opens one — while `text` is present, because the units' text joined
# with single spaces *is* that string, so a provision paints and searches
# before its structure arrives.
INDEX_PROVISION_FIELDS = (
    "containers",
    "content_hash",
    "heading_path",
    "instrument",
    "kind",
    "number",
    "ref",
    "text",
    "title",
)

# Instrument fields carried through verbatim from instrument.json. Everything
# on the record except `document`, which describes the stored .docx rather than
# the law and is of no use to a reader.
INDEX_INSTRUMENT_FIELDS = (
    "amendments",
    "captured_at",
    "code",
    "compilation_number",
    "compilation_start",
    "counts",
    "extractor_version",
    "has_unincorporated_amendments",
    "long_title",
    "made_under",
    "name",
    "number_and_year",
    "register_id",
    "registered_at",
    "short_title",
    "status",
    "symbol",
    "title_id",
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


def load_legislation(root: Path) -> dict[str, Any] | None:
    """Read `snapshot/legislation/` into memory, or None if it was never crawled.

    The two halves of the snapshot are crawled by separate pipelines and a
    checkout can legitimately hold one without the other, so an absent
    directory is a shape the viewer supports rather than an error. A *present*
    directory missing the files an instrument is made of is an error: that is a
    half-written corpus, and rule 3 says raise.
    """
    base = root / "legislation"
    if not base.is_dir():
        return None

    manifest_path = base / "manifest.json"
    manifest = _read_json(manifest_path) if manifest_path.is_file() else {}

    instruments: list[dict[str, Any]] = []
    for directory in sorted(p for p in base.iterdir() if p.is_dir()):
        record_path = directory / "instrument.json"
        contents_path = directory / "contents.json"
        for required in (record_path, contents_path):
            if not required.is_file():
                raise SnapshotError(
                    f"{required} is missing — the legislation snapshot is incomplete, "
                    "refusing to build a partial instrument"
                )
        provisions = []
        for path in sorted((directory / "provisions").rglob("*.json"), key=lambda p: p.as_posix()):
            doc = _read_json(path)
            if not isinstance(doc, dict) or "ref" not in doc or "units" not in doc:
                raise SnapshotError(f"{path} is not a provision file: expected keys 'ref' and 'units'")
            provisions.append({"path": path, "rel": path.relative_to(base).as_posix(), "record": doc})
        instruments.append(
            {
                "dir": directory,
                "record": _read_json(record_path),
                "contents": _read_json(contents_path),
                "endnotes": (directory / "endnotes.json").is_file(),
                "provisions": provisions,
            }
        )

    return {"manifest": manifest, "instruments": instruments}


def build_legislation(legislation: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """The Act and the Regulations, and the edges that tie them to the Manual.

    Same rule as `build_chunks`: the provision objects here are field-subsets
    of the records on disk, and everything derived — the cross-reference graph,
    the reverse index from a provision to the Manual chunks citing it, the unit
    and table counts, the file each record was read from — sits beside them in
    maps keyed by ref.

    The join needs no lookup table. A Manual chunk's `provisions[].id` is
    already this corpus's own ref grammar (`LEGISLATION_NOTES.md` §8), so an
    edge either names a provision here, or names a unit inside one, or names
    nothing this snapshot holds — and the third case is counted and reported
    rather than coerced into one of the first two.
    """
    instruments: list[dict[str, Any]] = []
    containers: dict[str, list[dict[str, Any]]] = {}
    provisions: list[dict[str, Any]] = []
    files: dict[str, str] = {}
    unit_counts: dict[str, int] = {}
    table_counts: dict[str, int] = {}
    owner: dict[str, str] = {}          # unit ref -> the provision holding it
    known: set[str] = set()             # provision refs
    edges: list[tuple[str, str]] = []   # (citing provision ref, cited id)
    # A provision's outgoing references, gathered off its units and deduplicated
    # — the same shape a chunk carries in `provisions`, so one predicate reads
    # both corpora. Beside the provisions, never on them: the record's own
    # statement of this is on the units, and the units are not in the index.
    by_provision: dict[str, dict[tuple[str, str, str], dict[str, Any]]] = defaultdict(dict)

    kinds: dict[str, int] = defaultdict(int)
    per_instrument: dict[str, int] = defaultdict(int)
    units_per_instrument: dict[str, int] = defaultdict(int)
    cited_instruments: dict[str, int] = defaultdict(int)
    extraction: dict[str, int] = defaultdict(int)
    certainty: dict[str, int] = defaultdict(int)

    for entry in legislation["instruments"]:
        record = entry["record"]
        code = record["code"]
        contents = entry["contents"]
        containers[code] = contents.get("containers", [])

        # contents.json is the instrument's own document order. A provision
        # file with no entry in it, or an entry with no file, means the two
        # disagree about what the instrument contains — which is not something
        # to paper over with a sort key.
        order = {row["ref"]: row["ordinal"] for row in contents.get("provisions", [])}
        found = {entry_p["record"]["ref"] for entry_p in entry["provisions"]}
        missing = sorted(set(order) - found)
        extra = sorted(found - set(order))
        if missing or extra:
            raise SnapshotError(
                f"{code}: contents.json and provisions/ disagree — "
                f"{len(missing)} listed without a file, {len(extra)} filed without a listing "
                f"(first: {(missing or extra)[0]})"
            )

        for provision_entry in sorted(entry["provisions"], key=lambda e: order[e["record"]["ref"]]):
            provision = provision_entry["record"]
            ref = provision["ref"]
            known.add(ref)
            provisions.append({f: provision[f] for f in INDEX_PROVISION_FIELDS if f in provision})
            files[ref] = provision_entry["rel"]
            units = provision.get("units", [])
            unit_counts[ref] = len(units)
            tables = sum(1 for unit in units if unit.get("table"))
            if tables:
                table_counts[ref] = tables
            kinds[provision["kind"]] += 1
            per_instrument[code] += 1
            units_per_instrument[code] += len(units)
            for unit in units:
                if "ref" in unit:
                    owner[unit["ref"]] = ref
                for reference in unit.get("provisions", []):
                    edges.append((ref, reference["id"]))
                    cited_instruments[reference["id"].split("/", 1)[0]] += 1
                    extraction[reference["extraction"]] += 1
                    certainty[reference.get("certainty") or "none"] += 1
                    row = {
                        "id": reference["id"],
                        "extraction": reference["extraction"],
                        "certainty": reference.get("certainty"),
                        "unit": unit.get("ref"),
                    }
                    key = (row["id"], row["extraction"], row["certainty"] or "")
                    by_provision[ref].setdefault(key, row)

        # As with a page object: the verbatim fields first, then the three
        # derived keys, named so it is obvious which side of the line they sit
        # on. A provision object gets no such treatment — everything derived
        # about one is in the sibling maps below, keyed by its ref.
        instruments.append(
            {
                **{f: record[f] for f in INDEX_INSTRUMENT_FIELDS if f in record},
                "provision_count": per_instrument[code],
                "unit_count": units_per_instrument[code],
                "endnotes": entry["endnotes"],
            }
        )

    def resolve(identifier: str) -> str | None:
        """The provision an id names: itself, or the one holding the unit."""
        if identifier in known:
            return identifier
        return owner.get(identifier)

    cites: dict[str, set[str]] = defaultdict(set)
    cited_by: dict[str, set[str]] = defaultdict(set)
    # Which provision holds a cited unit, for the unit refs anything actually
    # cites. `TMA1995/s41(3)(a)` is a provision of the Act in the citing
    # sense and a unit of section 41 in the storage sense, and a consumer
    # cannot get from one to the other by string surgery — `TMA1995/s4` is a
    # prefix of `TMA1995/s41`. So the mapping is stated, not implied.
    unit_owners: dict[str, str] = {}
    for source, identifier in edges:
        target = resolve(identifier)
        if target is None:
            continue
        if identifier != target:
            unit_owners[identifier] = target
        if target == source:
            continue
        cites[source].add(target)
        cited_by[target].add(source)

    # The join, in the direction the Manual points. An edge is in scope if it
    # names an instrument this snapshot holds; whether it lands is then a fact,
    # not a judgement, and the miss rate is worth reporting rather than hiding.
    in_corpus = set(per_instrument)
    manual_by_provision: dict[str, set[str]] = defaultdict(set)
    manual_by_unit: dict[str, set[str]] = defaultdict(set)
    scoped = resolved = 0
    unresolved: dict[str, int] = defaultdict(int)
    for entry in snapshot["pages"]:
        for chunk in entry["chunks"]:
            for reference in chunk.get("provisions", []):
                identifier = reference["id"]
                if identifier.split("/", 1)[0] not in in_corpus:
                    continue
                scoped += 1
                target = resolve(identifier)
                if target is None:
                    unresolved[identifier] += 1
                    continue
                resolved += 1
                manual_by_provision[target].add(chunk["chunk_ref"])
                if identifier != target:
                    unit_owners[identifier] = target
                    manual_by_unit[identifier].add(chunk["chunk_ref"])

    def ranked(counts: dict[str, int]) -> list[dict[str, Any]]:
        return [
            {"value": value, "count": count}
            for value, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ]

    def sorted_map(index: dict[str, set[str]]) -> dict[str, list[str]]:
        return {key: sorted(values) for key, values in sorted(index.items())}

    return {
        "captured_at": legislation["manifest"].get("crawled_at"),
        "cited_by": sorted_map(cited_by),
        "cited_by_manual": sorted_map(manual_by_provision),
        "cited_by_manual_units": sorted_map(manual_by_unit),
        "cites": sorted_map(cites),
        "containers": {code: containers[code] for code in sorted(containers)},
        "corpus": legislation["manifest"].get("corpus", {}),
        "edges": {
            ref: sorted(rows.values(), key=lambda row: (row["id"], row["extraction"]))
            for ref, rows in sorted(by_provision.items())
        },
        "extractor_version": legislation["manifest"].get("extractor_version"),
        "facets": {
            "certainty": ranked(certainty),
            "extraction": ranked(extraction),
            "instruments": ranked(cited_instruments),
            "kinds": ranked(kinds),
        },
        "files": dict(sorted(files.items())),
        "instruments": instruments,
        "join": {
            "chunks": len({ref for refs in manual_by_provision.values() for ref in refs}),
            "edges": scoped,
            "provisions": len(manual_by_provision),
            "resolved": resolved,
            # Every one of them, not a sample: a reader who wants to know why
            # the number is not 100% is owed the list, and it is small.
            "unresolved": ranked(unresolved),
            "unresolved_edges": scoped - resolved,
        },
        "provisions": provisions,
        "tables": dict(sorted(table_counts.items())),
        "unit_owners": dict(sorted(unit_owners.items())),
        "units": dict(sorted(unit_counts.items())),
    }


def build_graph(
    manual: dict[str, Any], chunks: dict[str, Any], law: dict[str, Any] | None
) -> dict[str, Any]:
    """The cross-reference network: every Part, and every cited provision, as a node.

    A view over the three bundles above, not a fourth reading of the snapshot —
    every count here is already sitting in `manual`, `chunks` or `law`, keyed by
    ref exactly as `viz/README.md` requires. Nodes are Parts and provisions, not
    chunks: 2,460 chunk nodes would be a hairball, not a map, and a Part is
    already the unit the Manual organises itself by on every other screen of
    this viewer. A provision with nothing citing it and nothing it cites is left
    out — a graph is for edges, and the legislation view already lists an
    instrument's full contents for the reader who wants that.

    Three edge kinds, one per citation field `SCHEMA.md` defines: a chunk's
    `provisions` (`manual_to_law`), a chunk's `internal_refs` (`manual_to_manual`),
    and a provision's own `provisions` — the instrument's internal
    cross-reference graph, already surfaced as `cites`/`cited_by` in
    build_legislation (`law_to_law`). Edges are aggregated to Part/provision
    grain and carry a `weight` — the number of distinct citing chunks, except
    `law_to_law`, which `cites` only ever states as "does A cite B", not how
    many times.
    """
    page_part: dict[str, str] = {page["page_ref"]: page["part_id"] for page in manual["pages"]}
    chunk_page: dict[str, str] = {chunk["chunk_ref"]: chunk["page_ref"] for chunk in chunks["chunks"]}

    def part_of(ref: str) -> str | None:
        """The Part owning a page_ref or a chunk_ref — whichever `ref` is."""
        return page_part.get(chunk_page.get(ref, ref))

    nodes: dict[str, dict[str, Any]] = {}
    for part in manual["parts"]:
        part_id = part["part_id"]
        nodes[f"part:{part_id}"] = {
            "id": f"part:{part_id}",
            "kind": "part",
            "label": "Part " + part_id[4:],
            "title": part.get("part_title", part_id),
            "part_id": part_id,
            "chunks": part.get("chunk_count", 0),
            "pages": part.get("page_count", 0),
        }

    # Part -> Part, from a chunk's own internal_refs. The same rule
    # build_legislation applies to a provision citing itself: a Part linking to
    # its own prose is real — 25 chunks do it, SCHEMA.md's internal_refs — but it
    # draws no edge on a map of Parts, so a same-Part pair is dropped rather
    # than kept as a self-loop.
    #
    # build_chunks does not validate that a target resolves to anything in this
    # snapshot either (SCHEMA.md's internal_refs is a crawl-time contract, not
    # one this builder re-checks) — a target this lenient pass can't place on
    # the map is skipped here for the same reason, not raised.
    manual_edges: dict[tuple[str, str], int] = defaultdict(int)
    for target_ref, citing_chunks in chunks["cited_by"].items():
        target_part = part_of(target_ref)
        if target_part is None:
            continue
        for chunk_ref in citing_chunks:
            source_part = part_of(chunk_ref)
            if source_part and source_part != target_part:
                manual_edges[(source_part, target_part)] += 1

    edges: list[dict[str, Any]] = [
        {"source": f"part:{source}", "target": f"part:{target}", "kind": "manual_to_manual", "weight": weight}
        for (source, target), weight in manual_edges.items()
    ]

    if law is not None:
        provisions_by_ref = {provision["ref"]: provision for provision in law["provisions"]}
        touched = set(law.get("cited_by_manual", {})) | set(law.get("cites", {})) | set(law.get("cited_by", {}))

        for ref in sorted(touched):
            provision = provisions_by_ref[ref]
            nodes[f"prov:{ref}"] = {
                "id": f"prov:{ref}",
                "kind": "provision",
                "label": ref.split("/", 1)[1],
                "title": provision.get("title"),
                "ref": ref,
                "instrument": provision["instrument"],
                "provision_kind": provision["kind"],
                "manual_citations": len(law.get("cited_by_manual", {}).get(ref, [])),
                "law_citations": len(law.get("cites", {}).get(ref, [])) + len(law.get("cited_by", {}).get(ref, [])),
            }

        # Part -> provision, aggregated from the join build_legislation already
        # resolved: cited_by_manual's chunk_refs are the citing side, the ref
        # they are filed under is the provision — section, regulation, whatever
        # unit a subsection citation resolved up to — a citation landed on.
        law_edges: dict[tuple[str, str], int] = defaultdict(int)
        for ref, citing_chunks in law.get("cited_by_manual", {}).items():
            for chunk_ref in citing_chunks:
                source_part = part_of(chunk_ref)
                if source_part:
                    law_edges[(source_part, ref)] += 1
        edges.extend(
            {"source": f"part:{source}", "target": f"prov:{ref}", "kind": "manual_to_law", "weight": weight}
            for (source, ref), weight in law_edges.items()
        )

        # Provision -> provision, the instrument's own cross-reference graph.
        edges.extend(
            {"source": f"prov:{source}", "target": f"prov:{target}", "kind": "law_to_law", "weight": 1}
            for source, targets in law.get("cites", {}).items()
            for target in targets
        )

    edges.sort(key=lambda edge: (edge["kind"], edge["source"], edge["target"]))
    return {"nodes": sorted(nodes.values(), key=lambda node: node["id"]), "edges": edges}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8")


def build_site(snapshot_root: Path, out: Path) -> dict[str, int]:
    """Build the whole bundle. Returns counts for the CLI to report."""
    snapshot = load_snapshot(snapshot_root)
    manual = build_manual(snapshot)
    chunks = build_chunks(snapshot)
    legislation = load_legislation(snapshot_root)
    law = build_legislation(legislation, snapshot) if legislation else None
    graph = build_graph(manual, chunks, law)

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    for name in ("index.html", "app.css", "app.js", "graph.html", "graph.css", "graph.js"):
        shutil.copyfile(APP_DIR / name, out / name)
    # GitHub Pages runs Jekyll over the upload otherwise, which drops _retired/.
    (out / ".nojekyll").write_text("", encoding="utf-8")

    _write_json(out / "data" / "manual.json", manual)
    _write_json(out / "data" / "chunks.json", chunks)
    _write_json(out / "data" / "graph.json", graph)

    for entry in snapshot["pages"]:
        destination = out / "pages" / entry["rel"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(entry["path"], destination)

    if law is not None:
        _write_json(out / "data" / "legislation.json", law)
        # The instrument, contents and endnote files keep their snapshot names,
        # so the viewer addresses them by convention (legislation/<code>/…) and
        # only the provision files, whose names are sanitised refs, need the
        # `files` map to be found.
        for entry in legislation["instruments"]:
            code = entry["record"]["code"]
            for name in ("instrument.json", "contents.json", "endnotes.json"):
                source = entry["dir"] / name
                if source.is_file():
                    destination = out / "legislation" / code / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
            for provision in entry["provisions"]:
                destination = out / "legislation" / provision["rel"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(provision["path"], destination)

    counts = {
        "parts": len(manual["parts"]),
        "pages": len(manual["pages"]),
        "chunks": len(chunks["chunks"]),
    }
    if law is not None:
        counts["instruments"] = len(law["instruments"])
        counts["provisions"] = len(law["provisions"])
    return counts


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

    line = (
        f"built {args.out}: {counts['parts']} parts, {counts['pages']} pages, "
        f"{counts['chunks']} chunks"
    )
    if "provisions" in counts:
        line += f", {counts['instruments']} instruments, {counts['provisions']} provisions"
    else:
        line += " — no legislation/ in this snapshot, building the Manual half alone"
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
