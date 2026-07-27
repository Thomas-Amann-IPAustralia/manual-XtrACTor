"""T10 — schema validation and the invariants a schema cannot express.

The snapshot is the deliverable, so this is the last thing standing between a
corrupt record and a citation that resolves to the wrong passage. It reports
every failure it finds rather than stopping at the first: a run that fixes one
problem per invocation is a run nobody uses.

Built from hand-written records rather than from pipeline output, so that a
validator failure means the validator, and a corrupted case can be constructed
exactly. One test at the end walks a real snapshot end to end.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import FakeManual
from tmm_snapshot.crawl import build_parser, run
from tmm_snapshot.validate import main, validate_snapshot

HASH = "sha256:" + "0" * 64


def page(**overrides) -> dict:
    return {
        "amendment_note": "Minor updates.",
        "content_hash": HASH,
        "crawled_at": "2026-07-27T09:00:00Z",
        "date_published": "2020-01-01",
        "extractor_version": "ingest/0.1.0",
        "h1": "22.1. Registrability",
        "last_amended": "2024-06-01",
        "nav_title": "1. Registrability",
        "page_ref": "TMM/Part22/1",
        "part_id": "Part22",
        "url": "https://manuals.ipaustralia.gov.au/trademark/x",
        **overrides,
    }


def chunk(**overrides) -> dict:
    return {
        "cases": [],
        "chunk_ref": "TMM/Part22/1/1",
        "content_hash": HASH,
        "fragment": None,
        "heading_path": ["Part 22", "22.1"],
        "internal_refs": [],
        "kind": "body",
        "ordinal": 1,
        "page_ref": "TMM/Part22/1",
        "provisions": [],
        "text": "Some text.",
        **overrides,
    }


def write(root: Path, document: dict, *, name: str | None = None) -> Path:
    part_id = document["page"]["part_id"]
    stem = name or document["page"]["page_ref"].replace("/", "-")
    path = root / "pages" / part_id / f"{stem}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def snapshot(tmp_path) -> Path:
    """A minimal, entirely valid snapshot."""
    write(tmp_path, {"page": page(), "chunks": [chunk()]})
    return tmp_path


def only(failures: list[str], fragment: str) -> str:
    matched = [failure for failure in failures if fragment in failure]
    assert matched, f"nothing mentioned {fragment!r}; got {failures}"
    return matched[0]


# -- the happy path --------------------------------------------------------


def test_a_good_snapshot_passes(snapshot):
    assert validate_snapshot(snapshot) == []


def test_a_snapshot_nobody_has_crawled_yet_has_nothing_to_validate(tmp_path):
    """`snapshot/` is empty in a fresh checkout, and that is not a defect."""
    assert validate_snapshot(tmp_path / "nowhere") == []
    (tmp_path / "pages").mkdir()
    assert validate_snapshot(tmp_path) == []


def test_a_crawl_that_wrote_no_pages_is_a_failure(tmp_path):
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    assert "no pages/ directory" in validate_snapshot(tmp_path)[0]

    (tmp_path / "pages").mkdir()
    assert "holds no page records" in validate_snapshot(tmp_path)[0]


# -- schema ----------------------------------------------------------------


def test_a_missing_required_field_is_reported_with_its_path(tmp_path):
    document = {"page": page(), "chunks": [chunk()]}
    del document["page"]["content_hash"]
    write(tmp_path, document)

    failure = only(validate_snapshot(tmp_path), "content_hash")
    assert "TMM-Part22-1.json" in failure


def test_a_malformed_hash_is_rejected(tmp_path):
    write(tmp_path, {"page": page(), "chunks": [chunk(content_hash="deadbeef")]})
    only(validate_snapshot(tmp_path), "deadbeef")


def test_an_undeclared_field_is_rejected(tmp_path):
    """additionalProperties: false. An interpretive field must not creep in."""
    write(tmp_path, {"page": page(), "chunks": [chunk(summary="A summary.")]})
    only(validate_snapshot(tmp_path), "summary")


def test_an_unreadable_date_is_reported(tmp_path):
    """jsonschema cannot check `format` without extra packages. This can."""
    write(tmp_path, {"page": page(last_amended="1 June 2024"), "chunks": [chunk()]})
    only(validate_snapshot(tmp_path), "is not a date")


def test_a_timestamp_without_a_timezone_is_reported(tmp_path):
    write(tmp_path, {"page": page(crawled_at="2026-07-27T09:00:00"), "chunks": [chunk()]})
    only(validate_snapshot(tmp_path), "no timezone")


def test_every_failure_is_reported_not_just_the_first(tmp_path):
    document = {
        "page": page(content_hash="nonsense"),
        "chunks": [chunk(ordinal=4, text=""), chunk(chunk_ref="TMM/Part22/1/2")],
    }
    write(tmp_path, document)
    failures = validate_snapshot(tmp_path)
    assert len(failures) >= 3


# -- invariants ------------------------------------------------------------


def test_a_chunk_filed_under_the_wrong_page_is_caught(tmp_path):
    write(
        tmp_path,
        {"page": page(), "chunks": [chunk(page_ref="TMM/Part32B/2/3")]},
    )
    only(validate_snapshot(tmp_path), "does not match the record it is filed with")


def test_chunk_refs_are_globally_unique(tmp_path):
    write(tmp_path, {"page": page(), "chunks": [chunk()]})
    write(
        tmp_path,
        {
            "page": page(page_ref="TMM/Part22/2"),
            "chunks": [chunk(page_ref="TMM/Part22/2")],
        },
    )
    only(validate_snapshot(tmp_path), "already claimed by")


def test_ordinals_must_be_contiguous_from_one(tmp_path):
    write(
        tmp_path,
        {
            "page": page(),
            "chunks": [
                chunk(ordinal=1),
                chunk(chunk_ref="TMM/Part22/1/3", ordinal=3),
            ],
        },
    )
    only(validate_snapshot(tmp_path), "ordinals are [1, 3]")


def test_an_unresolvable_cross_reference_is_caught(tmp_path):
    write(
        tmp_path,
        {"page": page(), "chunks": [chunk(internal_refs=["TMM/Part99/1"])]},
    )
    only(validate_snapshot(tmp_path), "names no page or chunk")


def test_a_cross_reference_forward_to_a_later_page_resolves(tmp_path):
    """Files are walked in name order; a reference is not required to be."""
    write(
        tmp_path,
        {"page": page(), "chunks": [chunk(internal_refs=["TMM/Part22/2"])]},
    )
    write(
        tmp_path,
        {
            "page": page(page_ref="TMM/Part22/2"),
            "chunks": [chunk(chunk_ref="TMM/Part22/2/1", page_ref="TMM/Part22/2")],
        },
    )
    assert validate_snapshot(tmp_path) == []


def test_a_reference_to_a_page_in_the_inventory_resolves(tmp_path):
    """A partial snapshot is incomplete, not corrupt."""
    write(
        tmp_path,
        {"page": page(), "chunks": [chunk(internal_refs=["TMM/Part35/4"])]},
    )
    assert validate_snapshot(tmp_path) != []

    (tmp_path / "sitemap.json").write_text(
        json.dumps({"pages": [{"page_ref": "TMM/Part35/4"}]}), encoding="utf-8"
    )
    assert validate_snapshot(tmp_path) == []


def test_a_record_filed_under_the_wrong_name_is_caught(tmp_path):
    write(tmp_path, {"page": page(), "chunks": [chunk()]}, name="something-else")
    only(validate_snapshot(tmp_path), "belongs in a file named")


def test_a_record_filed_under_the_wrong_part_is_caught(tmp_path):
    """The failure this repository guards against above all others."""
    document = {
        "page": page(part_id="Part32B"),
        "chunks": [chunk()],
    }
    write(tmp_path, document, name="TMM-Part22-1")
    failures = validate_snapshot(tmp_path)
    only(failures, "does not name part_id Part32B")


def test_a_corrupt_file_is_reported_rather_than_skipped(tmp_path):
    write(tmp_path, {"page": page(), "chunks": [chunk()]})
    (tmp_path / "pages" / "Part22" / "TMM-Part22-2.json").write_text("{oops")
    only(validate_snapshot(tmp_path), "not readable")


def test_retired_pages_are_validated_too(tmp_path):
    """They exist so old citations keep resolving. A broken one resolves badly."""
    path = tmp_path / "pages" / "_retired" / "Part22" / "TMM-Part22-9.json"
    path.parent.mkdir(parents=True)
    document = {"page": page(page_ref="TMM/Part22/9"), "chunks": [chunk(text="")]}
    path.write_text(json.dumps(document), encoding="utf-8")
    write(tmp_path, {"page": page(), "chunks": [chunk()]})

    only(validate_snapshot(tmp_path), "TMM-Part22-9.json")


# -- the CLI ---------------------------------------------------------------


def test_exit_codes(snapshot, capsys):
    assert main(["--snapshot", str(snapshot)]) == 0

    write(snapshot, {"page": page(page_ref="TMM/Part22/2"), "chunks": [chunk()]})
    assert main(["--snapshot", str(snapshot)]) == 1
    assert "validation failure(s)" in capsys.readouterr().err


# -- against the real thing ------------------------------------------------


def test_a_crawled_snapshot_validates(small_manual: FakeManual, tmp_path):
    root = tmp_path / "snapshot"
    args = build_parser().parse_args(["--snapshot", str(root)])
    with small_manual.fetcher(tmp_path / ".cache") as fetcher:
        run(args, fetcher=fetcher)

    assert validate_snapshot(root) == []
