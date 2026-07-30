"""The viewer bundle builder.

Three things are worth testing here and they are all about the boundary rather
than the pixels: the builder must not add a field to a chunk or to a provision,
it must not touch the snapshot it reads, and the join it derives between the
two halves must be the snapshot's own — an id that lands, landing, and one that
does not, counted rather than coerced. Everything else it does is presentation,
and presentation is not what this repository is for.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# viz/ is not a package and is deliberately not importable from src/ — the
# pipeline must never be able to reach it. Load it by path instead.
_spec = importlib.util.spec_from_file_location("viz_build", REPO / "viz" / "build.py")
viz = importlib.util.module_from_spec(_spec)
sys.modules["viz_build"] = viz
_spec.loader.exec_module(viz)


CHUNK = {
    "blocks": [
        {"kind": "paragraph", "text": "The first paragraph."},
        {"kind": "list_item", "text": "an item", "depth": 1},
    ],
    "cases": [{"citation": "[2018] FCAFC 109", "id": "CASE/2018/FCAFC/109"}],
    "chunk_ref": "TMM/Part22/1#1",
    "content_hash": "sha256:" + "0" * 64,
    "fragment": None,
    "heading_path": ["Part 22", "22.1. Something"],
    "heading_source": None,
    "internal_refs": [
        {"ref": "TMM/Part35/4", "extraction": "href", "mention": "Part 35.4"}
    ],
    "kind": "body",
    "ordinal": 1,
    "page_ref": "TMM/Part22/1",
    "provisions": [{"extraction": "href", "id": "TMA1995/s41", "mention": "section 41"}],
    "tables": [],
    "text": "The first paragraph. an item",
}

PAGE = {
    "amendment_note": "Minor updates.",
    "archived": False,
    "content_hash": "sha256:" + "1" * 64,
    "crawled_at": "2026-07-28T17:18:39Z",
    "date_published": "2022-12-19",
    "extractor_version": "ingest/0.6.0",
    "h1": "22.1. Something",
    "images": [],
    "last_amended": "2022-12-19",
    "nav_title": "1. Something",
    "page_ref": "TMM/Part22/1",
    "part_id": "Part22",
    "url": "https://manuals.ipaustralia.gov.au/trademark/22.1",
}


INSTRUMENT = {
    "amendments": [],
    "captured_at": "2026-07-28T17:18:39Z",
    "code": "TMA1995",
    "compilation_number": "47",
    "compilation_start": "2024-10-14",
    "counts": {"containers": 1, "provisions": 2, "units": 3},
    "document": {"bytes": 12, "content_hash": "sha256:" + "3" * 64, "format": "Word"},
    "extractor_version": "legislation/0.2.0",
    "has_unincorporated_amendments": False,
    "long_title": "An Act relating to trade marks",
    "made_under": None,
    "name": "Trade Marks Act 1995",
    "number_and_year": "No. 119, 1995",
    "register_id": "C2024C00545",
    "registered_at": "2024-10-14T13:40:38.9539588",
    "short_title": "Trade Marks Act 1995",
    "status": "InForce",
    "symbol": "s",
    "title_id": "C2004A04969",
}

CONTENTS = {
    "containers": [
        {"kind": "Part", "number": "4", "parent_ref": None, "ref": "TMA1995/pt4", "title": "Application"}
    ],
    "instrument": "TMA1995",
    "provisions": [
        {
            "container_ref": "TMA1995/pt4",
            "kind": "section",
            "number": "41",
            "ordinal": 1,
            "ref": "TMA1995/s41",
            "title": "Trade mark not distinguishing",
        },
        {
            "container_ref": "TMA1995/pt4",
            "kind": "section",
            "number": "177",
            "ordinal": 2,
            "ref": "TMA1995/s177",
            "title": "Additional ground",
        },
    ],
}

PROVISION = {
    "captured_at": "2026-07-28T17:18:39Z",
    "containers": ["TMA1995/pt4"],
    "content_hash": "sha256:" + "2" * 64,
    "extractor_version": "legislation/0.2.0",
    "heading_path": ["Trade Marks Act 1995", "Part 4—Application", "41  Trade mark not distinguishing"],
    "instrument": "TMA1995",
    "kind": "section",
    "number": "41",
    "ref": "TMA1995/s41",
    "text": "(1) An application must be rejected. (a) unless section 177 applies.",
    "title": "Trade mark not distinguishing",
    "units": [
        {
            "content_hash": "sha256:" + "4" * 64,
            "depth": 0,
            "kind": "subsection",
            "number": "(1)",
            "ordinal": 1,
            "parent_ref": None,
            "ref": "TMA1995/s41(1)",
            "style": "subsection",
            "text": "(1) An application must be rejected.",
        },
        {
            "content_hash": "sha256:" + "5" * 64,
            "depth": 1,
            "kind": "paragraph",
            "number": "(a)",
            "ordinal": 2,
            "parent_ref": "TMA1995/s41(1)",
            "provisions": [
                {"certainty": "default", "extraction": "regex", "id": "TMA1995/s177", "mention": "section 177"}
            ],
            "ref": "TMA1995/s41(1)(a)",
            "style": "paragraphsub",
            "text": "(a) unless section 177 applies.",
        },
    ],
}

SECOND_PROVISION = {
    **PROVISION,
    "content_hash": "sha256:" + "6" * 64,
    "heading_path": ["Trade Marks Act 1995", "Part 4—Application", "177  Additional ground"],
    "number": "177",
    "ref": "TMA1995/s177",
    "text": "(1) An additional ground.",
    "title": "Additional ground",
    "units": [
        {
            "content_hash": "sha256:" + "7" * 64,
            "depth": 0,
            "kind": "subsection",
            "number": "(1)",
            "ordinal": 1,
            "parent_ref": None,
            "ref": "TMA1995/s177(1)",
            "style": "subsection",
            "text": "(1) An additional ground.",
        }
    ],
}


def write_legislation(root: Path) -> Path:
    """The other half of the snapshot, one instrument deep."""
    base = root / "legislation"
    (base / "TMA1995" / "provisions" / "pt4").mkdir(parents=True)
    (base / "manifest.json").write_text(
        json.dumps(
            {
                "corpus": {"instruments": 1, "provisions": 2, "units": 3},
                "crawled_at": "2026-07-28T17:30:00Z",
                "extractor_version": "legislation/0.2.0",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    where = base / "TMA1995"
    (where / "instrument.json").write_text(json.dumps(INSTRUMENT, sort_keys=True), encoding="utf-8")
    (where / "contents.json").write_text(json.dumps(CONTENTS, sort_keys=True), encoding="utf-8")
    (where / "endnotes.json").write_text(
        json.dumps({"endnotes": [{"number": 4, "paragraphs": [], "ref": "TMA1995/endnote4", "tables": [], "title": "Amendment history"}]}, sort_keys=True),
        encoding="utf-8",
    )
    for provision in (PROVISION, SECOND_PROVISION):
        name = provision["ref"].replace("/", "-") + ".json"
        (where / "provisions" / "pt4" / name).write_text(
            json.dumps(provision, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
    return base


def write_snapshot(root: Path, *, in_sitemap: bool = True, retired: bool = False) -> Path:
    """A minimal but shaped-correctly snapshot."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "corpus": {"chunks": 1, "pages": 1, "parts": 1},
                "crawled_at": "2026-07-28T17:23:08Z",
                "extractor_version": "ingest/0.6.0",
                "run": {"unreachable": []},
                "source": {"manual_root": "https://manuals.ipaustralia.gov.au/trademark"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (root / "sitemap.json").write_text(
        json.dumps(
            {
                "parts": [{"part_id": "Part22", "part_title": "Part 22 Section 41", "page_count": 1}],
                "pages": (
                    [
                        {
                            "kind": "body",
                            "nav_ordinal": 1,
                            "nav_title": PAGE["nav_title"],
                            "page_ref": PAGE["page_ref"],
                            "part_id": "Part22",
                            "part_title": "Part 22 Section 41",
                            "url": PAGE["url"],
                        }
                    ]
                    if in_sitemap
                    else []
                ),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    where = root / "pages" / ("_retired/Part22" if retired else "Part22")
    where.mkdir(parents=True)
    (where / "TMM-Part22-1.json").write_text(
        json.dumps({"chunks": [CHUNK], "page": PAGE}, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return root


def digest(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_builds_the_expected_bundle(tmp_path):
    snapshot = write_snapshot(tmp_path / "snapshot")
    out = tmp_path / "dist"
    counts = viz.build_site(snapshot, out)

    assert counts == {"parts": 1, "pages": 1, "chunks": 1}
    for name in ("index.html", "app.css", "app.js", ".nojekyll"):
        assert (out / name).is_file()
    assert (out / "pages" / "Part22" / "TMM-Part22-1.json").read_text(encoding="utf-8") == (
        snapshot / "pages" / "Part22" / "TMM-Part22-1.json"
    ).read_text(encoding="utf-8")

    manual = json.loads((out / "data" / "manual.json").read_text(encoding="utf-8"))
    assert manual["parts"][0]["chunk_count"] == 1
    assert manual["pages"][0]["part_title"] == "Part 22 Section 41"
    assert manual["pages"][0]["file"] == "Part22/TMM-Part22-1.json"
    assert {"value": "TMA1995", "count": 1} in manual["facets"]["instruments"]
    # null heading_source is a value, not an absence, and keeps a name.
    assert {"value": "none", "count": 1} in manual["facets"]["heading_sources"]


def test_index_chunks_are_a_strict_subset_of_the_stored_chunk(tmp_path):
    """Rule: the viewer adds no field to a chunk. Mechanised here."""
    snapshot = write_snapshot(tmp_path / "snapshot")
    out = tmp_path / "dist"
    viz.build_site(snapshot, out)

    bundle = json.loads((out / "data" / "chunks.json").read_text(encoding="utf-8"))
    (indexed,) = bundle["chunks"]

    assert set(indexed) <= set(CHUNK), "the viewer invented a chunk field"
    for field, value in indexed.items():
        assert value == CHUNK[field], f"the viewer rewrote {field}"

    # Derived material sits beside the chunks, never on them.
    assert set(bundle) == {"chunks", "cited_by", "tables"}
    assert bundle["cited_by"] == {"TMM/Part35/4": ["TMM/Part22/1#1"]}


def test_index_fields_are_all_in_the_chunk_schema():
    schema = json.loads((REPO / "schema" / "chunk.schema.json").read_text(encoding="utf-8"))
    assert set(viz.INDEX_CHUNK_FIELDS) <= set(schema["properties"])


def test_page_fields_are_all_in_the_page_schema():
    schema = json.loads((REPO / "schema" / "page.schema.json").read_text(encoding="utf-8"))
    assert set(viz.INDEX_PAGE_FIELDS) <= set(schema["properties"])


def test_build_is_deterministic_and_leaves_the_snapshot_alone(tmp_path):
    snapshot = write_snapshot(tmp_path / "snapshot")
    before = digest(snapshot)

    viz.build_site(snapshot, tmp_path / "one")
    viz.build_site(snapshot, tmp_path / "two")

    assert digest(snapshot) == before, "the builder wrote inside snapshot/"
    assert digest(tmp_path / "one") == digest(tmp_path / "two")


def test_a_live_page_missing_from_the_nav_is_raised_not_guessed(tmp_path):
    snapshot = write_snapshot(tmp_path / "snapshot", in_sitemap=False)
    with pytest.raises(viz.SnapshotError, match="no sitemap entry"):
        viz.build_site(snapshot, tmp_path / "dist")


def test_a_retired_page_is_carried_without_a_nav_entry(tmp_path):
    snapshot = write_snapshot(tmp_path / "snapshot", in_sitemap=False, retired=True)
    viz.build_site(snapshot, tmp_path / "dist")

    manual = json.loads((tmp_path / "dist" / "data" / "manual.json").read_text(encoding="utf-8"))
    (page,) = manual["pages"]
    assert page["retired"] is True
    assert page["file"] == "_retired/Part22/TMM-Part22-1.json"


def test_a_snapshot_that_was_never_crawled_says_so(tmp_path):
    (tmp_path / "snapshot").mkdir()
    with pytest.raises(viz.SnapshotError, match="sitemap.json is missing"):
        viz.build_site(tmp_path / "snapshot", tmp_path / "dist")


def add_page(root: Path, page_ref: str, provisions: list[dict]) -> None:
    """A second page, so a test can put its own citation edges in the corpus."""
    sitemap = json.loads((root / "sitemap.json").read_text(encoding="utf-8"))
    page = {**PAGE, "page_ref": page_ref, "url": PAGE["url"] + "-b"}
    sitemap["pages"].append(
        {
            "kind": "body",
            "nav_ordinal": 2,
            "nav_title": page["nav_title"],
            "page_ref": page_ref,
            "part_id": page["part_id"],
            "part_title": "Part 22 Section 41",
            "url": page["url"],
        }
    )
    (root / "sitemap.json").write_text(json.dumps(sitemap, sort_keys=True), encoding="utf-8")
    chunk = {**CHUNK, "chunk_ref": page_ref + "#1", "page_ref": page_ref, "provisions": provisions}
    (root / "pages" / page["part_id"] / (page_ref.replace("/", "-") + ".json")).write_text(
        json.dumps({"chunks": [chunk], "page": page}, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def test_the_legislation_half_is_built_beside_the_manual(tmp_path):
    snapshot = write_snapshot(tmp_path / "snapshot")
    write_legislation(snapshot)
    out = tmp_path / "dist"

    counts = viz.build_site(snapshot, out)
    assert counts == {"parts": 1, "pages": 1, "chunks": 1, "instruments": 1, "provisions": 2}

    # The provision, instrument, contents and endnote files are carried through
    # byte for byte, the same bargain the page files get.
    stored = snapshot / "legislation" / "TMA1995" / "provisions" / "pt4" / "TMA1995-s41.json"
    carried = out / "legislation" / "TMA1995" / "provisions" / "pt4" / "TMA1995-s41.json"
    assert carried.read_text(encoding="utf-8") == stored.read_text(encoding="utf-8")
    for name in ("instrument.json", "contents.json", "endnotes.json"):
        assert (out / "legislation" / "TMA1995" / name).is_file()

    law = json.loads((out / "data" / "legislation.json").read_text(encoding="utf-8"))
    (instrument,) = law["instruments"]
    assert instrument["provision_count"] == 2
    assert instrument["unit_count"] == 3
    assert law["files"]["TMA1995/s41"] == "TMA1995/provisions/pt4/TMA1995-s41.json"
    assert law["units"] == {"TMA1995/s41": 2, "TMA1995/s177": 1}
    # Document order, from contents.json — not the order the files sort in.
    assert [p["ref"] for p in law["provisions"]] == ["TMA1995/s41", "TMA1995/s177"]
    assert {"value": "section", "count": 2} in law["facets"]["kinds"]
    # The instrument's own cross-reference graph, for free: s41 points at s177.
    assert law["cites"] == {"TMA1995/s41": ["TMA1995/s177"]}
    assert law["cited_by"] == {"TMA1995/s177": ["TMA1995/s41"]}


def test_index_provisions_are_a_strict_subset_of_the_stored_provision(tmp_path):
    """Rule: the viewer adds no field to a provision either. Mechanised here."""
    snapshot = write_snapshot(tmp_path / "snapshot")
    write_legislation(snapshot)
    out = tmp_path / "dist"
    viz.build_site(snapshot, out)

    law = json.loads((out / "data" / "legislation.json").read_text(encoding="utf-8"))
    indexed = next(p for p in law["provisions"] if p["ref"] == "TMA1995/s41")

    assert set(indexed) <= set(PROVISION), "the viewer invented a provision field"
    for field, value in indexed.items():
        assert value == PROVISION[field], f"the viewer rewrote {field}"
    assert "units" not in indexed, "the units are the third tier, not the index"

    # Everything derived sits beside the provisions, keyed by ref.
    for key in ("cited_by", "cited_by_manual", "cites", "edges", "files", "tables", "unit_owners", "units"):
        assert key in law


def test_index_provision_and_instrument_fields_are_in_their_schemas():
    provision = json.loads((REPO / "schema" / "provision.schema.json").read_text(encoding="utf-8"))
    instrument = json.loads((REPO / "schema" / "instrument.schema.json").read_text(encoding="utf-8"))
    assert set(viz.INDEX_PROVISION_FIELDS) <= set(provision["properties"])
    assert set(viz.INDEX_INSTRUMENT_FIELDS) <= set(instrument["properties"])


def test_the_join_lands_by_ref_and_counts_what_does_not(tmp_path):
    """The whole of the join: an id is a ref, or it is nothing. Never coerced."""
    snapshot = write_snapshot(tmp_path / "snapshot")
    write_legislation(snapshot)
    add_page(
        snapshot,
        "TMM/Part22/2",
        [
            # A unit address: the Manual cites the paragraph, the snapshot files
            # it under the section holding it.
            {"extraction": "regex", "id": "TMA1995/s41(1)(a)", "mention": "paragraph 41(1)(a)"},
            # A section this compilation does not have. In scope, so it counts.
            {"extraction": "regex", "id": "TMA1995/s999", "mention": "section 999"},
            # Out of scope entirely — a different Act, which this snapshot does
            # not hold, so it is not a miss.
            {"extraction": "regex", "id": "AIA1901/s7", "mention": "section 7"},
        ],
    )
    out = tmp_path / "dist"
    viz.build_site(snapshot, out)
    law = json.loads((out / "data" / "legislation.json").read_text(encoding="utf-8"))

    assert law["cited_by_manual"]["TMA1995/s41"] == ["TMM/Part22/1#1", "TMM/Part22/2#1"]
    assert law["cited_by_manual_units"] == {"TMA1995/s41(1)(a)": ["TMM/Part22/2#1"]}
    assert law["unit_owners"]["TMA1995/s41(1)(a)"] == "TMA1995/s41"
    assert law["join"]["edges"] == 3, "AIA1901 is not in this corpus and is not counted against it"
    assert law["join"]["resolved"] == 2
    assert law["join"]["unresolved_edges"] == 1
    assert law["join"]["unresolved"] == [{"value": "TMA1995/s999", "count": 1}]


def test_a_legislation_snapshot_that_disagrees_with_itself_is_raised(tmp_path):
    snapshot = write_snapshot(tmp_path / "snapshot")
    write_legislation(snapshot)
    (snapshot / "legislation" / "TMA1995" / "provisions" / "pt4" / "TMA1995-s177.json").unlink()

    with pytest.raises(viz.SnapshotError, match="disagree"):
        viz.build_site(snapshot, tmp_path / "dist")


def test_a_half_written_instrument_is_raised_not_skipped(tmp_path):
    snapshot = write_snapshot(tmp_path / "snapshot")
    write_legislation(snapshot)
    (snapshot / "legislation" / "TMA1995" / "contents.json").unlink()

    with pytest.raises(viz.SnapshotError, match="contents.json is missing"):
        viz.build_site(snapshot, tmp_path / "dist")


def test_a_snapshot_without_legislation_builds_the_manual_alone(tmp_path):
    snapshot = write_snapshot(tmp_path / "snapshot")
    out = tmp_path / "dist"
    counts = viz.build_site(snapshot, out)

    assert "provisions" not in counts
    assert not (out / "data" / "legislation.json").exists()
    assert not (out / "legislation").exists()

    # The network view still has a Part-only map to show — it does not need
    # the legislation half, the same bargain build_manual and build_chunks
    # already strike.
    graph = json.loads((out / "data" / "graph.json").read_text(encoding="utf-8"))
    assert [n["id"] for n in graph["nodes"]] == ["part:Part22"]
    assert graph["edges"] == []


def test_build_graph_aggregates_part_to_part_edges_and_drops_self_loops():
    """build_graph is a pure view over the three bundles above it — exercised
    directly here, without going through a snapshot on disk at all."""
    manual = {
        "parts": [
            {"part_id": "Part1", "part_title": "Part 1 Title", "chunk_count": 3, "page_count": 1},
            {"part_id": "Part2", "part_title": "Part 2 Title", "chunk_count": 1, "page_count": 1},
        ],
        "pages": [
            {"page_ref": "TMM/Part1/1", "part_id": "Part1"},
            {"page_ref": "TMM/Part2/1", "part_id": "Part2"},
        ],
    }
    chunks = {
        "chunks": [
            {"chunk_ref": "TMM/Part1/1#1", "page_ref": "TMM/Part1/1"},
            {"chunk_ref": "TMM/Part1/1#2", "page_ref": "TMM/Part1/1"},
            {"chunk_ref": "TMM/Part2/1#1", "page_ref": "TMM/Part2/1"},
        ],
        # Part1's two chunks both link to Part2 — a real cross-Part edge,
        # weight 2. Part1's second chunk also links within Part1: a same-Part
        # pair a map of Parts has no use for, and it must not appear as a
        # self-loop.
        "cited_by": {
            "TMM/Part2/1": ["TMM/Part1/1#1", "TMM/Part1/1#2"],
            "TMM/Part1/1": ["TMM/Part1/1#2"],
        },
    }

    graph = viz.build_graph(manual, chunks, None)

    assert {n["id"] for n in graph["nodes"]} == {"part:Part1", "part:Part2"}
    assert graph["edges"] == [
        {"source": "part:Part1", "target": "part:Part2", "kind": "manual_to_manual", "weight": 2}
    ]


def test_build_graph_adds_a_provision_node_only_when_something_touches_it():
    manual = {
        "parts": [{"part_id": "Part1", "part_title": "Part 1", "chunk_count": 1, "page_count": 1}],
        "pages": [{"page_ref": "TMM/Part1/1", "part_id": "Part1"}],
    }
    chunks = {
        "chunks": [{"chunk_ref": "TMM/Part1/1#1", "page_ref": "TMM/Part1/1"}],
        "cited_by": {},
    }
    law = {
        "provisions": [
            {"ref": "TMA1995/s1", "instrument": "TMA1995", "kind": "section", "title": "Cited"},
            {"ref": "TMA1995/s2", "instrument": "TMA1995", "kind": "section", "title": "Never touched"},
        ],
        "cited_by_manual": {"TMA1995/s1": ["TMM/Part1/1#1"]},
        "cites": {},
        "cited_by": {},
    }

    graph = viz.build_graph(manual, chunks, law)

    nodes = {n["id"]: n for n in graph["nodes"]}
    # s2 cites nothing and nothing cites it — no edge to draw, so it is left
    # off the map entirely, the same bargain the docstring states.
    assert set(nodes) == {"part:Part1", "prov:TMA1995/s1"}
    assert nodes["prov:TMA1995/s1"]["label"] == "s1"
    assert nodes["prov:TMA1995/s1"]["manual_citations"] == 1
    assert graph["edges"] == [
        {"source": "part:Part1", "target": "prov:TMA1995/s1", "kind": "manual_to_law", "weight": 1}
    ]


def test_graph_is_built_beside_the_manual_and_the_legislation(tmp_path):
    """The integration path: build_site's own manual/chunks/law bundles, fed
    through build_graph, for the same minimal fixture the rest of this file
    uses."""
    snapshot = write_snapshot(tmp_path / "snapshot")
    write_legislation(snapshot)
    out = tmp_path / "dist"
    viz.build_site(snapshot, out)

    graph = json.loads((out / "data" / "graph.json").read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in graph["nodes"]}
    edges = {(e["source"], e["target"], e["kind"]): e for e in graph["edges"]}

    # s177 is cited by nothing in the Manual, but s41(1)(a) cites it, so it is
    # on the map via law_to_law alone — proof the inclusion rule is "has an
    # edge", not "the Manual cites it".
    assert set(nodes) == {"part:Part22", "prov:TMA1995/s41", "prov:TMA1995/s177"}
    assert nodes["prov:TMA1995/s177"]["manual_citations"] == 0
    assert edges[("part:Part22", "prov:TMA1995/s41", "manual_to_law")]["weight"] == 1
    assert edges[("prov:TMA1995/s41", "prov:TMA1995/s177", "law_to_law")]["weight"] == 1
    # CHUNK's own internal_refs target, TMM/Part35/4, does not resolve to a
    # Part in this minimal fixture (there is no Part35 page at all) — the same
    # leniency build_chunks itself extends to that field, so it is dropped
    # rather than raised on.
    assert len(graph["edges"]) == 2


@pytest.mark.skipif(
    not (REPO / "snapshot" / "sitemap.json").is_file(),
    reason="no snapshot in this checkout",
)
def test_the_real_snapshot_builds_and_no_chunk_gains_a_field(tmp_path):
    out = tmp_path / "dist"
    counts = viz.build_site(REPO / "snapshot", out)
    assert counts["chunks"] > 0

    stored = {}
    for path in (REPO / "snapshot" / "pages").rglob("*.json"):
        for chunk in json.loads(path.read_text(encoding="utf-8"))["chunks"]:
            stored[chunk["chunk_ref"]] = chunk

    bundle = json.loads((out / "data" / "chunks.json").read_text(encoding="utf-8"))
    assert len(bundle["chunks"]) == len(stored)
    for indexed in bundle["chunks"]:
        original = stored[indexed["chunk_ref"]]
        assert set(indexed) <= set(original)
        for field, value in indexed.items():
            assert value == original[field]


@pytest.mark.skipif(
    not (REPO / "snapshot" / "sitemap.json").is_file(),
    reason="no snapshot in this checkout",
)
def test_the_real_snapshot_graph_has_no_self_loops_and_omits_uncited_provisions(tmp_path):
    out = tmp_path / "dist"
    viz.build_site(REPO / "snapshot", out)

    graph = json.loads((out / "data" / "graph.json").read_text(encoding="utf-8"))
    law = json.loads((out / "data" / "legislation.json").read_text(encoding="utf-8"))
    manual = json.loads((out / "data" / "manual.json").read_text(encoding="utf-8"))
    node_ids = {n["id"] for n in graph["nodes"]}

    assert node_ids, "the real corpus should yield a non-empty graph"
    part_nodes = [n for n in graph["nodes"] if n["kind"] == "part"]
    provision_nodes = [n for n in graph["nodes"] if n["kind"] == "provision"]
    # Every Part is always on the map; a provision needs an edge to earn a
    # place on it, and this corpus has plenty that never get one.
    assert len(part_nodes) == len(manual["parts"])
    assert 0 < len(provision_nodes) < len(law["provisions"])

    seen = set()
    for edge in graph["edges"]:
        assert edge["kind"] in {"manual_to_law", "law_to_law", "manual_to_manual"}
        assert edge["source"] != edge["target"], "a map of Parts/provisions has no use for a self-loop"
        assert edge["source"] in node_ids and edge["target"] in node_ids
        assert edge["weight"] >= 1
        key = (edge["source"], edge["target"], edge["kind"])
        assert key not in seen, f"duplicate edge {key}"
        seen.add(key)


@pytest.mark.skipif(
    not (REPO / "snapshot" / "sitemap.json").is_file(),
    reason="no snapshot in this checkout",
)
def test_law_to_law_is_the_one_unweighted_edge_kind(tmp_path):
    """`weight` counts citing chunks on two kinds and is a fixed 1 on the third.

    Not a fact about presentation, but the viewer has two behaviours resting on
    it, and both were wrong before it was stated here. `graph.js` exempts
    `law_to_law` from the declutter threshold — applying a "cited fewer than n
    times" rule to a kind that is always 1 hid all of them at the first notch —
    and draws it at a fixed low ink, because normalising a weight against a
    maximum equal to itself puts every one of those edges at the top of the
    scale. If build_graph ever learns how many times one provision cites
    another, this fails, and those are the two places to revisit.
    """
    out = tmp_path / "dist"
    viz.build_site(REPO / "snapshot", out)
    graph = json.loads((out / "data" / "graph.json").read_text(encoding="utf-8"))

    by_kind: dict[str, set[int]] = {}
    for edge in graph["edges"]:
        by_kind.setdefault(edge["kind"], set()).add(edge["weight"])

    assert by_kind["law_to_law"] == {1}, "cites states only that A cites B, never how many times"
    for kind in ("manual_to_law", "manual_to_manual"):
        assert max(by_kind[kind]) > 1, f"{kind} is a count of citing chunks and should vary"
