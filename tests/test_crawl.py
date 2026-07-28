"""T7 — orchestration, the skip gates, and idempotence.

`test_a_second_run_changes_nothing` is the enforcement mechanism for rule 2.
Treat a failure of it as a blocker, not a nuisance: a pipeline that rewrites
unchanged files turns every crawl into a thousand-file diff and destroys the
only thing this repository is for.

Every run here is served by tests.conftest.FakeManual over a mock transport.
Nothing touches the network.
"""

from __future__ import annotations

import json

import pytest

from conftest import PAGE_SLUGS, FakeManual, page_url
from tmm_snapshot import config, writer
from tmm_snapshot.crawl import CrawlError, build_parser, page_order, part_sort_key, run


def crawl(manual: FakeManual, tmp_path, *argv: str) -> int:
    """One `python -m tmm_snapshot.crawl` invocation against the fake site."""
    args = build_parser().parse_args(
        [*argv, "--snapshot", str(tmp_path / "snapshot")]
    )
    with manual.fetcher(tmp_path / ".cache") as fetcher:
        return run(args, fetcher=fetcher)


def state(root):
    """Every file in the snapshot, with its bytes. The thing that must not move."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def stamps(root):
    return {
        str(path.relative_to(root)): path.stat().st_mtime_ns
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# -- ordering --------------------------------------------------------------


def test_parts_sort_the_way_the_manual_reads():
    assert sorted(
        ["Part10", "Part2", "Part32B", "Part1", "Part32A"], key=part_sort_key
    ) == ["Part1", "Part2", "Part10", "Part32A", "Part32B"]


def test_page_order_is_stable(sitemap):
    assert [nav.page_ref for nav in page_order(sitemap)] == [
        nav.page_ref for nav in page_order(dict(reversed(list(sitemap.items()))))
    ]


# -- the run ---------------------------------------------------------------


def test_a_crawl_writes_pages_raw_sitemap_and_manifest(manual, tmp_path):
    assert crawl(manual, tmp_path, "--part", "Part32B") == 0

    root = tmp_path / "snapshot"
    assert (root / "sitemap.json").exists()
    assert (root / "manifest.json").exists()

    pages = sorted(p.name for p in (root / "pages" / "Part32B").iterdir())
    assert "TMM-Part32B-2-3.json" in pages
    assert len(pages) == 7
    assert len(list((root / "raw" / "Part32B").iterdir())) == 7

    stored = json.loads((root / "pages/Part32B/TMM-Part32B-2-3.json").read_text("utf-8"))
    assert stored["page"]["part_id"] == "Part32B"
    assert stored["page"]["url"] == page_url("part32b_2_3")
    assert stored["chunks"][0]["page_ref"] == "TMM/Part32B/2/3"


def test_a_second_run_changes_nothing(manual, tmp_path):
    """Rule 2, enforced. A blocker if it fails."""
    crawl(manual, tmp_path, "--part", "Part32B")
    root = tmp_path / "snapshot"

    before, times = state(root), stamps(root)
    crawl(manual, tmp_path, "--part", "Part32B")
    after = state(root)

    assert set(after) == set(before)
    changed = [name for name in before if before[name] != after[name]]
    assert changed == ["manifest.json"], (
        "only manifest.json may change on an unchanged crawl; "
        f"these also did: {changed}"
    )

    untouched = [
        name
        for name, when in stamps(root).items()
        if name != "manifest.json" and when != times[name]
    ]
    assert untouched == [], f"rewritten in place with identical bytes: {untouched}"


def test_the_manifest_carries_the_corpus_measurement(manual, tmp_path):
    crawl(manual, tmp_path, "--part", "Part32B")
    manifest = json.loads((tmp_path / "snapshot" / "manifest.json").read_text("utf-8"))

    assert manifest["corpus"]["pages"] == 61
    assert manifest["corpus"]["parts"] == 4
    assert manifest["corpus"]["raw_files"] == 7
    assert manifest["corpus"]["mean_raw_bytes"] > 0
    assert manifest["run"]["part"] == "Part32B"
    assert manifest["run"]["complete"] is False
    assert manifest["extractor_version"]


# -- the skip gates --------------------------------------------------------


def test_gate_1_skips_a_page_the_site_says_is_unmodified(manual, tmp_path):
    crawl(manual, tmp_path, "--part", "Part32B")

    manual.not_modified = {nav for nav in manual.pages}
    manual.not_modified.add(page_url("part32b_2_3"))
    manual.requests.clear()
    crawl(manual, tmp_path, "--part", "Part32B")

    manifest = json.loads((tmp_path / "snapshot" / "manifest.json").read_text("utf-8"))
    assert manifest["run"]["skipped_not_modified"] == 1
    assert manifest["run"]["pages_parsed"] == 6


def test_gate_2_skips_a_page_whose_body_is_unchanged(manual, tmp_path):
    crawl(manual, tmp_path, "--part", "Part32B")
    crawl(manual, tmp_path, "--part", "Part32B")

    manifest = json.loads((tmp_path / "snapshot" / "manifest.json").read_text("utf-8"))
    assert manifest["run"]["unchanged"] == 7
    assert manifest["run"]["chunks_cut"] == 0, "gate 2 must skip chunking, not just writing"
    assert manifest["run"]["pages_written"] == 0


def test_corpus_chunks_counts_the_disk_and_run_chunks_cut_counts_the_run(
    manual, tmp_path
):
    """The two numbers answer different questions and must not be conflated.

    After the 28 July 2026 crawl `run.chunks` said 2084 while the snapshot held
    2151 — the 67 belonged to 19 pages skipped at gate 2, which are never
    chunked and so were never counted. Nothing was wrong except the name, and
    a reader had no way to tell the shortfall from data loss. `corpus.chunks`
    walks the snapshot; `run.chunks_cut` counts what this run cut.
    """
    crawl(manual, tmp_path, "--part", "Part32B")
    manifest = json.loads((tmp_path / "snapshot" / "manifest.json").read_text("utf-8"))
    first_run = manifest["run"]["chunks_cut"]
    on_disk = manifest["corpus"]["chunks"]
    assert first_run == on_disk > 0, "a first crawl cuts every chunk it stores"

    # Second run: gate 2 skips everything, so nothing is cut and the corpus is
    # unmoved. This is the shape that made the old name misleading.
    crawl(manual, tmp_path, "--part", "Part32B")
    manifest = json.loads((tmp_path / "snapshot" / "manifest.json").read_text("utf-8"))
    assert manifest["run"]["chunks_cut"] == 0
    assert manifest["corpus"]["chunks"] == on_disk


def test_force_reprocesses_everything(manual, tmp_path):
    crawl(manual, tmp_path, "--part", "Part32B")
    crawl(manual, tmp_path, "--part", "Part32B", "--force")

    manifest = json.loads((tmp_path / "snapshot" / "manifest.json").read_text("utf-8"))
    assert manifest["run"]["unchanged"] == 0
    assert manifest["run"]["chunks_cut"] > 0
    assert manifest["run"]["pages_written"] == 0, "reprocessed, but nothing changed"


def test_an_amended_page_is_rewritten_and_reported(manual, tmp_path, capsys):
    crawl(manual, tmp_path, "--part", "Part32B")
    capsys.readouterr()

    # Inside div.field--name-body: an edit anywhere else is not an amendment,
    # and gate 2 is right to skip it.
    amended = manual.body_for(page_url("part32b_2_3")).replace(
        "issues peculiar to these types", "issues peculiar (amended) to these types", 1
    )
    assert amended != manual.body_for(page_url("part32b_2_3"))
    manual.pages[page_url("part32b_2_3")] = amended
    crawl(manual, tmp_path, "--part", "Part32B")

    manifest = json.loads((tmp_path / "snapshot" / "manifest.json").read_text("utf-8"))
    assert manifest["run"]["pages_written"] == 1
    assert manifest["run"]["chunks_changed"] >= 1
    assert manifest["run"]["chunks_changed"] < manifest["run"]["chunks_cut"], (
        "gate 3 should show most of the page unchanged"
    )
    assert "paragraphs amended" in capsys.readouterr().out


# -- flags -----------------------------------------------------------------


def test_dry_run_writes_nothing(manual, tmp_path, capsys):
    assert crawl(manual, tmp_path, "--dry-run", "--limit", "3") == 0
    assert not (tmp_path / "snapshot").exists()
    assert "dry run, nothing written" in capsys.readouterr().out


def test_dry_run_over_an_existing_snapshot_leaves_it_alone(manual, tmp_path):
    crawl(manual, tmp_path, "--part", "Part32B")
    root = tmp_path / "snapshot"
    before = state(root)

    crawl(manual, tmp_path, "--part", "Part32B", "--dry-run")
    assert state(root) == before


def test_limit_stops_after_n_pages_and_takes_the_same_n(manual, tmp_path):
    crawl(manual, tmp_path, "--limit", "5")
    root = tmp_path / "snapshot"
    first = sorted(p.name for p in (root / "pages").rglob("*.json"))
    assert len(first) == 5

    crawl(manual, tmp_path, "--limit", "5")
    assert sorted(p.name for p in (root / "pages").rglob("*.json")) == first


def test_an_archived_page_is_crawled_and_counted(full_manual, tmp_path):
    """The first full crawl died on one of these. SOURCE_NOTES.md §15."""
    assert crawl(full_manual, tmp_path, "--part", "Part23") == 0

    root = tmp_path / "snapshot"
    ref = "TMM/Part23/x-" + PAGE_SLUGS["part23_archived"]
    document = writer.read_page_file(writer.page_path(ref, "Part23", root))
    assert document is not None, "an archived page still gets a record"
    assert document["page"]["archived"] is True
    assert document["chunks"] == [], "no prose left to chunk"

    manifest = json.loads((root / "manifest.json").read_text("utf-8"))
    assert manifest["run"]["archived"] == 1


# -- progress --------------------------------------------------------------


def test_every_page_is_named_on_stderr_before_it_is_processed(manual, tmp_path, capsys):
    """A silent run is indistinguishable from a hung one. §Courtesy: 502 pages
    at a request a second is a quarter of an hour, and a reviewer who cannot
    tell the difference cancels the job — which is the one thing that leaves
    the conditional cache out of step with the snapshot.
    """
    assert crawl(manual, tmp_path, "--limit", "3") == 0
    captured = capsys.readouterr()

    scope = [line for line in captured.err.splitlines() if line.startswith("[")]
    assert len(scope) == 3, "one line per page in scope"
    assert scope[0].startswith("[1/3] TMM/")
    assert all(config.MANUAL_ROOT in line for line in scope), (
        "the line must carry the URL, so a stalled run says what to go and check"
    )

    assert "pages in scope" in captured.err
    assert "3 pages in scope" in captured.out, (
        "progress is the other channel; stdout still carries the report alone"
    )
    assert not captured.out.startswith("["), "no progress chatter on stdout"


def test_a_nav_link_the_site_will_not_serve_is_recorded_and_skipped(
    small_manual, tmp_path, capsys
):
    """The Manual's own nav links Part 1.3 to a URL that 404s. §14."""
    dead = page_url("part32b_2_3")
    small_manual.gone = {dead}
    crawl(small_manual, tmp_path, "--part", "Part32B")

    root = tmp_path / "snapshot"
    assert not writer.page_path("TMM/Part32B/2/3", "Part32B", root).exists()
    assert writer.page_path("TMM/Part32B/2/4", "Part32B", root).exists(), (
        "one rotted link must not cost the pages either side of it"
    )

    manifest = json.loads((root / "manifest.json").read_text("utf-8"))
    assert manifest["run"]["unreachable"] == [
        {"page_ref": "TMM/Part32B/2/3", "status": 404, "url": dead}
    ]
    assert "UNREACHABLE" in capsys.readouterr().out


def test_a_page_already_held_survives_the_site_losing_it(small_manual, tmp_path):
    crawl(small_manual, tmp_path, "--part", "Part32B")
    root = tmp_path / "snapshot"
    before = writer.page_path("TMM/Part32B/2/3", "Part32B", root).read_bytes()

    small_manual.gone = {page_url("part32b_2_3")}
    crawl(small_manual, tmp_path, "--part", "Part32B")

    assert writer.page_path("TMM/Part32B/2/3", "Part32B", root).read_bytes() == before


def test_a_site_that_serves_nothing_is_not_a_successful_run(small_manual, tmp_path):
    base = "https://manuals.ipaustralia.gov.au/trademark/"
    small_manual.gone = {
        f"{base}relevant-legislation25",
        f"{base}2.3-section-41--capacity-to-distinguish1",
        f"{base}2.4-section-44--comparison-of-trade-marks",
    }
    with pytest.raises(CrawlError, match="not serving us"):
        crawl(small_manual, tmp_path, "--part", "Part32B")
    assert not (tmp_path / "snapshot" / "manifest.json").exists()


def test_an_unknown_part_is_an_error_not_an_empty_crawl(manual, tmp_path):
    with pytest.raises(CrawlError, match="matched no pages"):
        crawl(manual, tmp_path, "--part", "Part99")


def test_from_raw_reparses_without_the_network(manual, tmp_path):
    crawl(manual, tmp_path, "--part", "Part32B")
    root = tmp_path / "snapshot"
    before = state(root)

    args = build_parser().parse_args(
        ["--from-raw", "--force", "--part", "Part32B", "--snapshot", str(root)]
    )
    manual.requests.clear()
    assert run(args) == 0

    assert manual.requests == [], "--from-raw must not touch the network"
    after = state(root)
    assert {k: v for k, v in after.items() if k != "manifest.json"} == {
        k: v for k, v in before.items() if k != "manifest.json"
    }


def test_from_raw_needs_stored_source(tmp_path):
    args = build_parser().parse_args(
        ["--from-raw", "--snapshot", str(tmp_path / "snapshot")]
    )
    with pytest.raises(CrawlError, match="holds none"):
        run(args)


# -- retirement ------------------------------------------------------------


def test_a_page_that_leaves_the_nav_is_retired(small_manual, tmp_path):
    crawl(small_manual, tmp_path)
    root = tmp_path / "snapshot"
    assert writer.page_path("TMM/Part32B/2/3", "Part32B", root).exists()

    gone = '<li><a href="/trademark/2.3-section-41--capacity-to-distinguish1">Part 32B.2.3 Section 41: Capacity to Distinguish</a></li>'
    assert gone in small_manual.nav_html
    small_manual.nav_html = small_manual.nav_html.replace(gone, "")
    crawl(small_manual, tmp_path)

    assert not writer.page_path("TMM/Part32B/2/3", "Part32B", root).exists()
    assert writer.retired_path("TMM/Part32B/2/3", "Part32B", root).exists()
    assert writer.read_retired(root)["TMM/Part32B/2/3"]["part_id"] == "Part32B"
    # The evidence for what the Manual said on a date stays where it is.
    assert writer.raw_path("TMM/Part32B/2/3", root).exists()


def test_a_returning_page_is_taken_back_out_of_retirement(small_manual, tmp_path):
    crawl(small_manual, tmp_path)
    root = tmp_path / "snapshot"

    gone = '<li><a href="/trademark/2.3-section-41--capacity-to-distinguish1">Part 32B.2.3 Section 41: Capacity to Distinguish</a></li>'
    kept = small_manual.nav_html
    small_manual.nav_html = kept.replace(gone, "")
    crawl(small_manual, tmp_path)

    small_manual.nav_html = kept
    crawl(small_manual, tmp_path)

    assert writer.page_path("TMM/Part32B/2/3", "Part32B", root).exists()
    assert not writer.retired_path("TMM/Part32B/2/3", "Part32B", root).exists()


def test_a_filtered_run_retires_nothing(small_manual, tmp_path):
    """A run that saw one Part knows nothing about the Parts it did not visit."""
    crawl(small_manual, tmp_path)
    root = tmp_path / "snapshot"
    live = sorted(p.name for p in (root / "pages").rglob("*.json"))

    crawl(small_manual, tmp_path, "--limit", "1")
    assert sorted(p.name for p in (root / "pages").rglob("*.json")) == live
    assert not (root / writer.RETIRED_INDEX_NAME).exists()
