"""T8 — the change report.

The report is the body of the pull request a scheduled crawl opens, and that
pull request is the audit trail. So the thing under test is not really the
markdown: it is whether a reviewer, reading only this, would notice that Part
22 was restructured rather than edited.

`test_the_report_matches_the_golden_file` is the anchor. The two fixture
snapshot states under `fixtures/snapshots/` are hand-built to hold one of every
kind of change at once; when the wording of a section changes, re-render the
golden and read the diff before committing it.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tmm_snapshot.crawl import build_parser as build_parser_for_crawl
from tmm_snapshot.crawl import run as run_crawl
from tmm_snapshot.diff import (
    MAX_LISTED,
    build_parser,
    compare,
    human_ref,
    main,
    read_snapshot,
    render_report,
)
from tmm_snapshot.validate import validate_snapshot

SNAPSHOTS = Path(__file__).parent / "fixtures" / "snapshots"
BEFORE = SNAPSHOTS / "before"
AFTER = SNAPSHOTS / "after"
GOLDEN = SNAPSHOTS / "report.md"


@pytest.fixture
def states(tmp_path) -> tuple[Path, Path]:
    """Writable copies of the two fixture states, for tests that mutate one."""
    before, after = tmp_path / "before", tmp_path / "after"
    shutil.copytree(BEFORE, before)
    shutil.copytree(AFTER, after)
    return before, after


def load(root: Path, relative: str) -> dict:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def save(root: Path, relative: str, document: dict) -> None:
    (root / relative).write_text(
        json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def section(report: str, title: str) -> str:
    """The body of one `## ` section, for asserting on it in isolation."""
    assert f"## {title}" in report, f"no {title!r} section in:\n{report}"
    body = report.split(f"## {title}", 1)[1]
    return body.split("\n## ", 1)[0]


# -- the golden file -------------------------------------------------------


def test_the_report_matches_the_golden_file():
    assert render_report(BEFORE, AFTER) == GOLDEN.read_text(encoding="utf-8")


def test_the_fixture_states_are_snapshots_a_crawl_could_have_written():
    """A golden built on invalid records would prove nothing about a real run."""
    assert validate_snapshot(BEFORE) == []
    assert validate_snapshot(AFTER) == []


def test_rendering_twice_gives_the_same_bytes():
    assert render_report(BEFORE, AFTER) == render_report(BEFORE, AFTER)


# -- what the report has to make a reviewer see ----------------------------


def test_a_restructure_is_called_out_before_the_amendments():
    report = render_report(BEFORE, AFTER)
    assert report.index("## Structure") < report.index("## Pages amended")
    assert "**Part 22: 4 → 5 pages**" in section(report, "Structure")


def test_a_renumbered_page_is_reported_as_a_renumbering_not_just_a_new_page():
    """Same URL, new page_ref. Every citation to the old ref has just broken."""
    structure = section(render_report(BEFORE, AFTER), "Structure")
    assert "`TMM/Part5/2` → `TMM/Part5/3`" in structure


def test_chunk_counts_say_how_much_of_the_page_moved():
    amended = section(render_report(BEFORE, AFTER), "Pages amended (2)")
    assert "| 2 of 3 (+1 new, -1 gone) |" in amended


def test_a_hyperlink_only_amendment_reports_no_paragraphs_changed():
    """The page moved and no chunk text did. See SOURCE_NOTES.md §5."""
    amended = section(render_report(BEFORE, AFTER), "Pages amended (2)")
    assert "| 0 of 2 |" in amended
    assert "Update hyperlinks" in amended


def test_the_manuals_own_reason_is_in_the_report():
    """It is the clue a reviewer separates practice change from tidy-up with."""
    amended = section(render_report(BEFORE, AFTER), "Pages amended (2)")
    assert "Amended following the Raising the Bar review." in amended


def test_retirement_is_distinguished_from_deletion():
    retired = section(render_report(BEFORE, AFTER), "Pages retired (2)")
    assert "**Part 22.3**" in retired
    assert "_retired/" in retired


def test_a_page_back_in_the_nav_is_restored_not_added():
    report = render_report(BEFORE, AFTER)
    assert "**Part 22.5**" in section(report, "Pages restored (1)")
    assert "**Part 22.5**" not in section(report, "Pages added (3)")


def test_a_nav_retitle_is_reported_without_pretending_the_text_moved():
    reworded = section(render_report(BEFORE, AFTER), "Changed around the text (1)")
    assert "**Part 5.1**" in reworded
    assert "`nav_title`: 1. Fees - general → 1. Fees and charges - general" in reworded


def test_an_unreachable_nav_link_is_named_and_not_called_retirement():
    unreachable = section(render_report(BEFORE, AFTER), "Unreachable (1)")
    assert "`TMM/Part1/3`" in unreachable
    assert "returned 404" in unreachable


def test_the_report_never_suggests_merging_itself():
    assert "Never auto-merged" in render_report(BEFORE, AFTER)


# -- the cases the fixtures deliberately leave out -------------------------


def test_the_first_crawl_has_nothing_to_compare_against(tmp_path):
    report = render_report(tmp_path / "nothing-here", AFTER)
    assert report.startswith("# Manual snapshot: first crawl")
    assert "| Part 32B | 1 |" in report
    assert "## Pages added" not in report


def test_an_unchanged_manual_says_so():
    report = render_report(AFTER, AFTER)
    assert report.startswith("# Manual snapshot: no changes")
    assert "none moved" in report


def test_a_partial_run_draws_no_conclusion_about_what_it_did_not_see(states):
    """`--part Part22` never saw Part 5, so Part 5 is not missing. Rule 3."""
    before, after = states
    manifest = load(after, "manifest.json")
    manifest["run"]["complete"] = False
    manifest["run"]["part"] = "Part22"
    save(after, "manifest.json", manifest)

    report = render_report(before, after)
    assert "**Partial run** (`--part Part22`)" in report
    assert "not evidence that the page is gone" in report


def test_a_page_deleted_without_being_retired_is_a_blocker(states):
    """Retirement moves a file. Nothing in the pipeline deletes one."""
    before, after = states
    (after / "pages/Part22/TMM-Part22-4.json").unlink()
    (after / "pages/Part22/TMM-Part22-5.json").unlink()
    (after / "pages/_retired/Part22/TMM-Part22-3.json").unlink()

    report = render_report(before, after)
    gone = section(report, "Pages gone without being retired (1)")
    assert "**Part 22.3**" in gone
    assert "Do not merge without finding out which" in gone
    assert "GONE" in report.splitlines()[0]


def test_a_page_that_changed_without_its_amendment_log_moving_is_flagged(states):
    """The Amended Reasons table is the Manual's change feed (SOURCE_NOTES §5)."""
    before, after = states
    document = load(after, "pages/Part22/TMM-Part22-1.json")
    was = load(before, "pages/Part22/TMM-Part22-1.json")
    document["page"]["last_amended"] = was["page"]["last_amended"]
    document["page"]["amendment_note"] = was["page"]["amendment_note"]
    save(after, "pages/Part22/TMM-Part22-1.json", document)

    report = render_report(before, after)
    assert "**Changed without saying so.**" in report
    assert "- **Part 22.1**" in report.split("**Changed without saying so.**", 1)[1]


def test_an_extractor_bump_is_one_line_and_not_a_page_each(states):
    """A version bump rewrites every file. Listing them all buries the run."""
    before, after = states
    for path in (after / "pages").rglob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        document["page"]["extractor_version"] = "ingest/0.2.0"
        path.write_text(json.dumps(document, sort_keys=True, indent=2) + "\n", "utf-8")

    report = render_report(before, after)
    rebuilt = section(report, "Rebuilt by a new extractor")
    assert "`ingest/0.2.0` in place of `ingest/0.1.0`" in rebuilt
    assert "- **Part 22.5**" not in rebuilt


def test_a_long_list_is_capped_rather_than_truncated_by_github(states):
    """GitHub cuts a pull request body at 65 536 characters, mid-sentence."""
    before, after = states
    extra = MAX_LISTED + 5
    template = load(after, "pages/Part22/TMM-Part22-4.json")
    for index in range(100, 100 + extra):
        document = json.loads(json.dumps(template))
        document["page"]["page_ref"] = f"TMM/Part22/{index}"
        document["chunks"] = []
        save(after, f"pages/Part22/TMM-Part22-{index}.json", document)

    # The three the fixture already adds, plus the ones just written.
    total = extra + 3
    added = section(render_report(before, after), f"Pages added ({total})")
    assert added.count("\n- **Part") == MAX_LISTED
    assert f"- … and {total - MAX_LISTED} more." in added


# -- the small deterministic parts -----------------------------------------


@pytest.mark.parametrize(
    "page_ref,expected",
    [
        ("TMM/Part22/1", "Part 22.1"),
        ("TMM/Part32B/2/3", "Part 32B.2.3"),
        ("TMM/Part19A", "Part 19A"),
        ("TMM/Part22/x-annex-a1-section-41", "Part 22.x-annex-a1-section-41"),
        ("not-a-ref", "not-a-ref"),
    ],
)
def test_a_page_ref_reads_as_the_manual_addresses_itself(page_ref, expected):
    assert human_ref(page_ref) == expected


def test_pages_are_listed_in_reading_order_not_lexical_order(states):
    """Lexically Part22/10 comes before Part22/2, which reads as a mistake."""
    before, after = states
    template = load(after, "pages/Part22/TMM-Part22-4.json")
    for index in (10, 7):
        document = json.loads(json.dumps(template))
        document["page"]["page_ref"] = f"TMM/Part22/{index}"
        document["chunks"] = []
        save(after, f"pages/Part22/TMM-Part22-{index}.json", document)

    added = [
        page.page_ref
        for page in compare(read_snapshot(before), read_snapshot(after)).added
    ]
    assert added == [
        "TMM/Part5/3",
        "TMM/Part22/4",
        "TMM/Part22/7",
        "TMM/Part22/10",
        "TMM/Part32B/2/3",
    ]


def test_a_pipe_in_a_title_does_not_break_the_table(states):
    before, after = states
    document = load(after, "pages/Part22/TMM-Part22-1.json")
    document["page"]["amendment_note"] = "Updated 41(3) | 41(4)\nand the annex."
    save(after, "pages/Part22/TMM-Part22-1.json", document)

    row = next(
        line
        for line in render_report(before, after).splitlines()
        if line.startswith("| **Part 22.1**")
    )
    assert row.replace("\\|", "").count("|") == 5, "the escaped pipe opened a cell"
    assert "Updated 41(3) \\| 41(4) and the annex." in row


def test_a_corrupt_page_file_does_not_take_the_whole_report_down(states):
    """The validator is what fails on a bad record. A report that crashed
    instead of printing would hide every other change in the run."""
    before, after = states
    (after / "pages/Part22/TMM-Part22-1.json").write_text("{not json", encoding="utf-8")

    report = render_report(before, after)
    assert "Part 22.4" in report


# -- against what the pipeline actually writes -----------------------------


def test_a_recrawl_of_an_unchanged_manual_reports_nothing(manual, tmp_path):
    """The report agrees with rule 2, over snapshots the pipeline wrote itself.

    Everything above this line reads hand-built fixtures, which proves the
    report and not the reader. This crawls a stand-in Manual twice and asserts
    the second run has nothing to say — the same property
    `test_a_second_run_changes_nothing` asserts in bytes, asserted in prose.
    """
    root = tmp_path / "snapshot"
    args = build_parser_for_crawl().parse_args(
        ["--part", "Part32B", "--snapshot", str(root)]
    )
    with manual.fetcher(tmp_path / ".cache") as fetcher:
        assert run_crawl(args, fetcher=fetcher) == 0
        before = tmp_path / "before"
        shutil.copytree(root, before)
        assert run_crawl(args, fetcher=fetcher) == 0

    report = render_report(before, root)
    assert report.startswith("# Manual snapshot: no changes")
    assert "**Partial run** (`--part Part32B`)" in report


# -- the CLI ---------------------------------------------------------------


def test_the_cli_writes_the_report_where_it_is_told(tmp_path):
    out = tmp_path / "nested" / "report.md"
    assert main(["--before", str(BEFORE), "--after", str(AFTER), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == GOLDEN.read_text(encoding="utf-8")


def test_the_cli_prints_to_stdout_by_default(capsys):
    assert main(["--before", str(BEFORE), "--after", str(AFTER)]) == 0
    assert capsys.readouterr().out == GOLDEN.read_text(encoding="utf-8")


def test_before_is_required():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--after", str(AFTER)])
