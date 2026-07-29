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

from conftest import FakeManual
from tmm_snapshot.crawl import build_parser, run
from tmm_snapshot.validate import main, validate_snapshot

HASH = "sha256:" + "0" * 64


def page(**overrides) -> dict:
    return {
        "amendment_note": "Minor updates.",
        "archived": False,
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


def ref(target: str, **overrides) -> dict:
    """One internal_refs record. Since 0.8.0 the field carries provenance."""
    return {"ref": target, "extraction": "href", "mention": "a link", **overrides}


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


@pytest.mark.parametrize(
    "identifier",
    [
        "TMA1995/s41",
        "TMA1995/s41A",
        "TMA1995/s44(3)(a)",
        "TMA1995/s223A(2)(b)",
        "AIA1901/s7",
        "TMR1995/r4.15",
        # Part 3A of the Regulations (TM Headstart). A letter suffix rides on
        # any dotted component, not only the last one — the original pattern
        # allowed r3A and r4.15 but rejected the r3A.3 the Manual actually
        # cites, so the first real crawl failed validation. See SOURCE_NOTES §3.
        #
        # `TMR1995/r3A` was in this list until the 0.8.0 review and was never a
        # real id: the Regulations hold 3A.1 and 3A.3 but no bare 3A, and every
        # one of their 401 regulation numbers is dotted. It is now rejected by
        # the numbering invariant — SOURCE_NOTES §32.
        "TMR1995/r3A.3",
        "TMR1995/r21.21A",
        # A Schedule, from an AustLII `sch` node. Neither a section nor a
        # regulation, and the same segment the legislation snapshot uses.
        "TMR1995/sch2",
    ],
)
def test_a_real_provision_id_is_accepted(tmp_path, identifier):
    write(
        tmp_path,
        {
            "page": page(),
            "chunks": [
                chunk(provisions=[{"id": identifier, "extraction": "href"}])
            ],
        },
    )
    assert validate_snapshot(tmp_path) == []


@pytest.mark.parametrize(
    "identifier",
    ["TMA1995/r4..5", "TMA1995/s4.", "tma1995/s44", "TMA1995/x44"],
)
def test_a_malformed_provision_id_is_rejected(tmp_path, identifier):
    """Widening the pattern for r3A.3 must not turn it into a sieve."""
    write(
        tmp_path,
        {
            "page": page(),
            "chunks": [
                chunk(provisions=[{"id": identifier, "extraction": "href"}])
            ],
        },
    )
    only(validate_snapshot(tmp_path), identifier)


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
        {"page": page(), "chunks": [chunk(internal_refs=[ref("TMM/Part99/1")])]},
    )
    only(validate_snapshot(tmp_path), "names no page or chunk")


def test_a_cross_reference_forward_to_a_later_page_resolves(tmp_path):
    """Files are walked in name order; a reference is not required to be."""
    write(
        tmp_path,
        {"page": page(), "chunks": [chunk(internal_refs=[ref("TMM/Part22/2")])]},
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
        {"page": page(), "chunks": [chunk(internal_refs=[ref("TMM/Part35/4")])]},
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


# -- an instrument that cannot hold the provision it names ----------------


def test_a_section_of_the_regulations_is_caught(tmp_path):
    """The schema checks the shape of an id and the shape is fine, so nothing
    below this saw it. 20 such edges reached the July 2026 snapshot."""
    write(
        tmp_path,
        {
            "page": page(),
            "chunks": [
                chunk(
                    provisions=[
                        {
                            "id": "TMR1995/s224",
                            "extraction": "regex",
                            "certainty": "explicit",
                        }
                    ]
                )
            ],
        },
    )
    only(validate_snapshot(tmp_path), "TMR1995/s224 addresses TMR1995")


def test_a_regulation_of_the_act_is_caught(tmp_path):
    write(
        tmp_path,
        {
            "page": page(),
            "chunks": [
                chunk(
                    provisions=[
                        {"id": "TMA1995/r21.6", "extraction": "regex"}
                    ]
                )
            ],
        },
    )
    only(validate_snapshot(tmp_path), "TMA1995/r21.6 addresses TMA1995")


def test_an_instrument_of_unknown_kind_is_left_alone(tmp_path):
    """Only instruments this pipeline knows the kind of are checked. An id
    from an AustLII href carries its kind structurally."""
    write(
        tmp_path,
        {
            "page": page(),
            "chunks": [
                chunk(provisions=[{"id": "PBRA1994/s26", "extraction": "href"}])
            ],
        },
    )
    assert validate_snapshot(tmp_path) == []


# -- blocks that do not add up --------------------------------------------


def test_blocks_that_lose_a_paragraph_are_caught(tmp_path):
    """`blocks` is the shape of the text, never a second copy of the words. A
    dropped paragraph fails here and nowhere else."""
    write(
        tmp_path,
        {
            "page": page(),
            "chunks": [
                chunk(
                    text="First sentence. Second sentence.",
                    blocks=[{"kind": "paragraph", "text": "First sentence."}],
                )
            ],
        },
    )
    only(validate_snapshot(tmp_path), "blocks are the shape of the text")


def test_blocks_that_add_back_up_pass(tmp_path):
    write(
        tmp_path,
        {
            "page": page(),
            "chunks": [
                chunk(
                    text="First sentence. Second sentence.",
                    blocks=[
                        {"kind": "paragraph", "text": "First sentence."},
                        {"kind": "paragraph", "text": "Second sentence."},
                    ],
                )
            ],
        },
    )
    assert validate_snapshot(tmp_path) == []


# -- links whose offsets have drifted --------------------------------------


def test_a_link_whose_offsets_name_other_words_is_caught(tmp_path):
    """The offsets are what put a hyperlink back where the Manual set it. One
    that has drifted underlines the wrong words and is well-formed while doing
    it, so the schema cannot see it and this is the only check that can."""
    write(
        tmp_path,
        {
            "page": page(),
            "chunks": [
                chunk(
                    text="Under section 217A a fee applies.",
                    links=[
                        {
                            "href": "/act/s217a",
                            "text": "section 217A",
                            "start": 5,
                            "end": 17,
                        }
                    ],
                )
            ],
        },
    )
    only(validate_snapshot(tmp_path), "name different words")


def test_a_link_running_past_the_end_of_the_text_is_caught(tmp_path):
    write(
        tmp_path,
        {
            "page": page(),
            "chunks": [
                chunk(
                    text="Short.",
                    links=[
                        {"href": "/a", "text": "Short.", "start": 0, "end": 40}
                    ],
                )
            ],
        },
    )
    only(validate_snapshot(tmp_path), "is not a span of a")


def test_a_link_that_names_its_own_words_passes(tmp_path):
    write(
        tmp_path,
        {
            "page": page(),
            "chunks": [
                chunk(
                    text="Under section 217A a fee applies.",
                    links=[
                        {
                            "href": "/act/s217a",
                            "text": "section 217A",
                            "start": 6,
                            "end": 18,
                        }
                    ],
                )
            ],
        },
    )
    assert validate_snapshot(tmp_path) == []


# -- the ancestry, checked rather than trusted -----------------------------


def test_headings_must_describe_the_heading_path(tmp_path):
    """`headings` deliberately does not repeat the ancestor's text — that is
    `heading_path[2:]`. What makes storing one fact once safe is checking the
    correspondence over the whole snapshot."""
    write(
        tmp_path,
        {
            "page": page(),
            "chunks": [
                chunk(
                    heading_path=["Part 22", "22.1", "1. Heading"],
                    heading_source="markup",
                    headings=[],
                )
            ],
        },
    )
    only(validate_snapshot(tmp_path), "headings holds 0 entries")


def test_the_leaf_of_headings_must_agree_with_heading_source(tmp_path):
    write(
        tmp_path,
        {
            "page": page(),
            "chunks": [
                chunk(
                    heading_path=["Part 22", "22.1", "1. Heading"],
                    heading_source="markup",
                    headings=[{"level": 3, "source": "emphasis", "ref": None}],
                )
            ],
        },
    )
    only(validate_snapshot(tmp_path), "leaf of headings says")


def test_a_heading_ref_naming_no_chunk_is_caught(tmp_path):
    """A heading's `ref` is an address like any other. Null says the heading
    owns no chunk; a string that names nothing is a broken one."""
    write(
        tmp_path,
        {
            "page": page(),
            "chunks": [
                chunk(
                    heading_path=["Part 22", "22.1", "1. Heading"],
                    heading_source="markup",
                    headings=[
                        {"level": 3, "source": "markup", "ref": "TMM/Part22/1/9/9"}
                    ],
                )
            ],
        },
    )
    only(validate_snapshot(tmp_path), "names no page or chunk")


def test_a_chunk_with_no_heading_carries_no_source(tmp_path):
    write(
        tmp_path,
        {
            "page": page(),
            "chunks": [
                chunk(
                    heading_path=["Part 22", "22.1"],
                    heading_source="markup",
                    headings=[],
                )
            ],
        },
    )
    only(validate_snapshot(tmp_path), "on a chunk with no headings")


@pytest.mark.parametrize(
    "identifier", ["TMA1995/s4.7", "TMA1995/s21.28(1)(a)", "TMR1995/r2016"]
)
def test_a_number_its_instrument_cannot_express_is_rejected(tmp_path, identifier):
    """The second of two independent readings of one fact.

    `INSTRUMENT_KIND` compares the reference's word against the instrument and
    catches `TMR1995/s224`. This compares the number: the Act numbers none of
    its 315 sections with a dot and the Regulations number all 401 of theirs
    with one, so these three name addresses that cannot exist. 204 such edges
    reached the 0.8.0 corpus, 159 of them at certainty `default`.
    """
    write(
        tmp_path,
        {
            "page": page(),
            "chunks": [
                chunk(provisions=[{"id": identifier, "extraction": "regex"}])
            ],
        },
    )
    only(validate_snapshot(tmp_path), identifier)
