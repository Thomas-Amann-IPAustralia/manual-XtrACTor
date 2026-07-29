"""T7 — deterministic serialisation.

Rule 2 lives here. A page file must not change unless the page's content
changed, because that is what makes `git diff` between crawls a readable
amendment log rather than a thousand-file wall of noise.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from conftest import page_html, page_url
from tmm_snapshot import writer
from tmm_snapshot.chunker import Chunk, chunk_body
from tmm_snapshot.page import PageRecord, parse_page


@pytest.fixture
def parsed(sitemap):
    """Part 22.1, parsed and chunked — a real page with real citations."""
    nav = sitemap[page_url("part22_1")]
    record, body = parse_page(page_html("part22_1"), nav)
    return record, chunk_body(body, record, nav, sitemap)


def record(**overrides) -> PageRecord:
    fields = {
        "page_ref": "TMM/Part22/1",
        "part_id": "Part22",
        "url": "https://manuals.ipaustralia.gov.au/trademark/x",
        "nav_title": "1. Registrability",
        "h1": "22.1. Registrability",
        "content_hash": "sha256:" + "0" * 64,
        "date_published": date(2020, 1, 1),
        "last_amended": date(2024, 6, 1),
        "amendment_note": "Minor updates.",
        "extractor_version": "ingest/0.1.0",
    }
    return PageRecord(**{**fields, **overrides})


def chunk(**overrides) -> Chunk:
    fields = {
        "chunk_ref": "TMM/Part22/1/1",
        "page_ref": "TMM/Part22/1",
        "text": "Some text.",
        "heading_path": ["Part 22", "22.1", "1. Heading"],
        "ordinal": 1,
        "content_hash": "sha256:" + "1" * 64,
        "kind": "body",
        "fragment": None,
        "provisions": [],
        "cases": [],
        "internal_refs": [],
    }
    return Chunk(**{**fields, **overrides})


# -- paths -----------------------------------------------------------------


def test_filenames_derive_from_the_page_ref(tmp_path):
    path = writer.page_path("TMM/Part22/1", "Part22", tmp_path)
    assert path == tmp_path / "pages" / "Part22" / "TMM-Part22-1.json"
    assert writer.raw_path("TMM/Part32B/2/3", tmp_path) == (
        tmp_path / "raw" / "Part32B" / "TMM-Part32B-2-3.html"
    )


# -- rule 2 ----------------------------------------------------------------


def test_unchanged_content_does_not_touch_the_file(tmp_path, parsed):
    page, chunks = parsed
    assert writer.write_page(page, chunks, tmp_path) is True

    path = writer.page_path(page.page_ref, page.part_id, tmp_path)
    before = path.stat().st_mtime_ns

    assert writer.write_page(page, chunks, tmp_path) is False
    assert path.stat().st_mtime_ns == before, "the file was rewritten in place"


def test_crawled_at_survives_a_crawl_that_changed_nothing(tmp_path, parsed):
    page, chunks = parsed
    writer.write_page(page, chunks, tmp_path, now="2026-01-01T00:00:00Z")
    writer.write_page(page, chunks, tmp_path, now="2026-07-27T09:00:00Z")

    path = writer.page_path(page.page_ref, page.part_id, tmp_path)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["page"]["crawled_at"] == "2026-01-01T00:00:00Z"


def test_crawled_at_moves_when_the_content_does(tmp_path, parsed):
    page, chunks = parsed
    writer.write_page(page, chunks, tmp_path, now="2026-01-01T00:00:00Z")

    amended = record(
        page_ref=page.page_ref,
        part_id=page.part_id,
        content_hash="sha256:" + "a" * 64,
    )
    assert writer.write_page(amended, chunks, tmp_path, now="2026-07-27T09:00:00Z")

    path = writer.page_path(page.page_ref, page.part_id, tmp_path)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["page"]["crawled_at"] == "2026-07-27T09:00:00Z"


def test_a_renamed_nav_title_is_a_change(tmp_path):
    """A Part renamed in the nav must not slip through gate 2."""
    writer.write_page(record(), [chunk()], tmp_path, now="2026-01-01T00:00:00Z")
    renamed = record(nav_title="1. Registrability, renamed")

    assert writer.page_fields_unchanged(
        json.loads(
            writer.page_path("TMM/Part22/1", "Part22", tmp_path).read_text("utf-8")
        )["page"],
        renamed,
    ) is False
    assert writer.write_page(renamed, [chunk()], tmp_path) is True


def test_raw_is_written_verbatim_and_only_once(tmp_path):
    html = "<html>\n  <body>x</body>\n</html>\n"
    assert writer.write_raw("TMM/Part22/1", html, tmp_path) is True
    assert writer.write_raw("TMM/Part22/1", html, tmp_path) is False
    assert writer.raw_path("TMM/Part22/1", tmp_path).read_text("utf-8") == html
    assert writer.read_raw("TMM/Part22/1", tmp_path) == html


# -- serialisation ---------------------------------------------------------


def test_serialisation_is_sorted_indented_and_newline_terminated(tmp_path, parsed):
    page, chunks = parsed
    writer.write_page(page, chunks, tmp_path)
    text = writer.page_path(page.page_ref, page.part_id, tmp_path).read_text("utf-8")

    assert text.endswith("\n")
    assert '\n  "page": {' in text
    # ensure_ascii=False, so the Manual's curly apostrophes read as themselves
    # in a diff rather than as ’.
    assert "’" in text
    assert (
        json.dumps(json.loads(text), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        == text
    )


def test_arrays_are_sorted_by_a_stable_key(tmp_path):
    unsorted = chunk(
        provisions=[
            {"id": "TMA1995/s44", "extraction": "regex", "certainty": "default"},
            {"id": "AIA1901/s7", "extraction": "href"},
            {"id": "TMA1995/s41", "extraction": "href"},
        ],
        cases=[
            {"id": "CASE/2018/FCAFC/109", "citation": "[2018] FCAFC 109"},
            {"id": "CASE/1954/RPC/43", "citation": "(1954) 71 RPC 43"},
        ],
        internal_refs=[
            {"ref": "TMM/Part22/15", "extraction": "href", "mention": "22.15"},
            {"ref": "TMM/Part12/9", "extraction": "href", "mention": "Part 12.9"},
            {"ref": "TMM/Part22/15", "extraction": "href", "mention": "22.15"},
        ],
    )
    writer.write_page(record(), [unsorted], tmp_path)
    stored = json.loads(
        writer.page_path("TMM/Part22/1", "Part22", tmp_path).read_text("utf-8")
    )
    written = stored["chunks"][0]

    assert [p["id"] for p in written["provisions"]] == [
        "AIA1901/s7",
        "TMA1995/s41",
        "TMA1995/s44",
    ]
    assert [c["id"] for c in written["cases"]] == [
        "CASE/1954/RPC/43",
        "CASE/2018/FCAFC/109",
    ]
    assert [r["ref"] for r in written["internal_refs"]] == [
        "TMM/Part12/9",
        "TMM/Part22/15",
    ]


def test_reordered_citations_produce_identical_bytes(tmp_path):
    """The order a citation appears in a sentence is not a change to the page."""
    provisions = [
        {"id": "TMA1995/s41", "extraction": "href"},
        {"id": "AIA1901/s7", "extraction": "regex", "certainty": "explicit"},
    ]
    writer.write_page(record(), [chunk(provisions=provisions)], tmp_path)
    assert (
        writer.write_page(
            record(), [chunk(provisions=list(reversed(provisions)))], tmp_path
        )
        is False
    )


def test_chunks_are_written_in_ordinal_order(tmp_path):
    chunks = [
        chunk(chunk_ref="TMM/Part22/1/3", ordinal=3),
        chunk(chunk_ref="TMM/Part22/1/1", ordinal=1),
        chunk(chunk_ref="TMM/Part22/1/2", ordinal=2),
    ]
    writer.write_page(record(), chunks, tmp_path)
    stored = json.loads(
        writer.page_path("TMM/Part22/1", "Part22", tmp_path).read_text("utf-8")
    )
    assert [c["ordinal"] for c in stored["chunks"]] == [1, 2, 3]


def test_render_page_reports_a_change_without_making_one(tmp_path, parsed):
    """What --dry-run relies on."""
    page, chunks = parsed
    path, _, changed = writer.render_page(page, chunks, tmp_path)
    assert changed is True
    assert not path.exists()


# -- retirement ------------------------------------------------------------


def test_a_vanished_page_is_moved_not_deleted(tmp_path):
    writer.write_page(record(), [chunk()], tmp_path)
    gone = writer.retire(tmp_path, live_refs=set(), retired_at="2026-07-27T00:00:00Z")

    assert gone == ["TMM/Part22/1"]
    assert not writer.page_path("TMM/Part22/1", "Part22", tmp_path).exists()
    assert writer.retired_path("TMM/Part22/1", "Part22", tmp_path).exists()

    index = writer.read_retired(tmp_path)
    assert index["TMM/Part22/1"]["retired_at"] == "2026-07-27T00:00:00Z"


def test_a_live_page_is_left_alone(tmp_path):
    writer.write_page(record(), [chunk()], tmp_path)
    assert writer.retire(tmp_path, {"TMM/Part22/1"}, "2026-07-27T00:00:00Z") == []
    assert writer.page_path("TMM/Part22/1", "Part22", tmp_path).exists()
    assert not (tmp_path / writer.RETIRED_INDEX_NAME).exists()


def test_a_returning_page_drops_its_retired_copy(tmp_path):
    """Otherwise two files claim the same chunk_refs and neither can be cited."""
    writer.write_page(record(), [chunk()], tmp_path)
    writer.retire(tmp_path, set(), "2026-07-27T00:00:00Z")

    assert writer.unretire(tmp_path, "TMM/Part22/1", "Part22") is True
    assert not writer.retired_path("TMM/Part22/1", "Part22", tmp_path).exists()
    assert writer.read_retired(tmp_path) == {}
    assert not (tmp_path / writer.RETIRED_INDEX_NAME).exists()


def test_retired_pages_are_not_retired_twice(tmp_path):
    writer.write_page(record(), [chunk()], tmp_path)
    writer.retire(tmp_path, set(), "2026-07-27T00:00:00Z")
    assert writer.retire(tmp_path, set(), "2026-08-27T00:00:00Z") == []


# -- manifest --------------------------------------------------------------


def test_the_manifest_is_the_one_file_that_always_changes(tmp_path):
    writer.write_manifest(tmp_path, {"crawled_at": "2026-07-27T00:00:00Z"})
    path = tmp_path / "manifest.json"
    first = path.stat().st_mtime_ns

    writer.write_manifest(tmp_path, {"crawled_at": "2026-07-27T01:00:00Z"})
    assert path.stat().st_mtime_ns != first
    assert json.loads(path.read_text("utf-8"))["crawled_at"] == "2026-07-27T01:00:00Z"
