"""The viewer bundle builder.

Two things are worth testing here and they are both about the boundary rather
than the pixels: the builder must not add a field to a chunk, and it must not
touch the snapshot it reads. Everything else it does is presentation, and
presentation is not what this repository is for.
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
