"""T3 — the nav tree as page inventory.

The whole point of this module is that the URL cannot be trusted to say which
Part a page belongs to, so most of what is asserted here is about attribution.
"""

from __future__ import annotations

import json
import re

import pytest

from tmm_snapshot import config
from tmm_snapshot.sitemap import (
    NavAmbiguous,
    NavNotFound,
    build_sitemap,
    write_sitemap,
)

from conftest import fixture_html

BASE = "https://manuals.ipaustralia.gov.au/trademark"


def test_the_slug_collision_pair_resolves_to_different_parts(nav_minimal_html):
    """SOURCE_NOTES.md §2, the failure this repo is shaped around.

    Two pages about section 41 capacity to distinguish share a slug, separated
    only by a Drupal collision counter. One is about plants, the other about
    wines. Attribute one to the wrong Part and every downstream citation about
    wines points at plants.
    """
    pages = build_sitemap(nav_minimal_html)

    plants = pages[f"{BASE}/2.3-section-41--capacity-to-distinguish"]
    wines = pages[f"{BASE}/2.3-section-41--capacity-to-distinguish1"]

    assert plants.part_id == "Part32A"
    assert wines.part_id == "Part32B"
    assert plants.page_ref == "TMM/Part32A/2/3"
    assert wines.page_ref == "TMM/Part32B/2/3"


def test_nesting_three_levels_deep_carries_the_part_down(nav_minimal_html):
    """Part 5 -> 3. Indexing -> Glossary -> List of Top Level Terms.

    The child <ul> is a sibling of its <li>, not a descendant, so a parser
    that trusts the markup's own nesting loses the Part on the way down.
    """
    pages = build_sitemap(nav_minimal_html)

    for slug in (
        "3.-indexing",
        "glossary-of-image-descriptors",
        "list-of-top-level-terms",
        "device-constituents",
    ):
        assert pages[f"{BASE}/{slug}"].part_id == "Part5", slug


def test_a_node_that_is_both_a_page_and_a_parent_is_still_a_page(nav_minimal_html):
    """'3. Indexing and Re-scanning' has children *and* a real href."""
    pages = build_sitemap(nav_minimal_html)
    assert pages[f"{BASE}/3.-indexing"].page_ref == "TMM/Part5/3"


@pytest.mark.parametrize(
    ("slug", "expected"),
    [
        # Page-local numbering: '1. Registrability under section 41 ...'
        ("1.-registrability-under-section-41-of-the-trade-marks-act-1995", "TMM/Part22/1"),
        # A page number that happens to equal its own Part number. It must not
        # be mistaken for a Part qualifier and flattened away.
        ("22.-numerals", "TMM/Part22/22"),
        # Part-qualified numbering: 'Part 32B.2.3 Section 41: ...'
        ("2.3-section-41--capacity-to-distinguish1", "TMM/Part32B/2/3"),
        # Unnumbered pages fall back to the slug, prefixed so that the form is
        # visibly not a dotted address. Matches the worked example in SCHEMA.md.
        (
            "annex-a1-section-41-prior-to-raising-the-bar",
            "TMM/Part22/x-annex-a1-section-41-prior-to-raising-the-bar",
        ),
        ("relevant-legislation44", "TMM/Part22/x-relevant-legislation44"),
    ],
)
def test_page_ref_derivation(nav_minimal_html, slug, expected):
    assert build_sitemap(nav_minimal_html)[f"{BASE}/{slug}"].page_ref == expected


@pytest.mark.parametrize(
    ("slug", "expected"),
    [
        ("relevant-legislation44", "landing"),
        ("relevant-legislation25", "landing"),  # titled 'Part 32B: Landing Page'
        ("annex-a1-section-41-prior-to-raising-the-bar", "annex"),
        ("1.-registrability-under-section-41-of-the-trade-marks-act-1995", "body"),
        ("2.3-section-41--capacity-to-distinguish", "body"),
    ],
)
def test_kind_classification(nav_minimal_html, slug, expected):
    assert build_sitemap(nav_minimal_html)[f"{BASE}/{slug}"].kind == expected


def test_grouping_nodes_are_not_pages(nav_minimal_html):
    """A folder node is a heading with children, not a page of its own."""
    pages = build_sitemap(nav_minimal_html)
    titles = {page.nav_title for page in pages.values()}
    assert "Part 32B.2. Examination of Wine Trade Marks" not in titles
    assert "2. Examination of Plant Trade Marks" not in titles
    assert all(page.url != BASE for page in pages.values())  # 'Home'


def test_the_other_placeholder_href_forms_are_also_grouping_nodes():
    """The live site emits an empty href; SOURCE_NOTES.md §2 also records
    '<>' and '#', so all three are treated the same."""
    pages = build_sitemap(fixture_html("synthetic", "nav_placeholder_hrefs.html"))

    assert {page.page_ref for page in pages.values()} == {
        "TMM/Part19A/x-relevant-legislation99",
        "TMM/Part19A/2/1",
        "TMM/Part19A/x-annex-a1---a-worked-example",
    }
    assert pages[f"{BASE}/2.1-a-nested-page"].part_id == "Part19A"


def test_nav_ordinal_restarts_per_part_and_is_contiguous(nav_minimal_html):
    pages = build_sitemap(nav_minimal_html)
    by_part: dict[str, list[int]] = {}
    for page in pages.values():
        by_part.setdefault(page.part_id, []).append(page.nav_ordinal)

    assert set(by_part) == {"Part5", "Part22", "Part32A", "Part32B"}
    for part_id, ordinals in by_part.items():
        assert sorted(ordinals) == list(range(1, len(ordinals) + 1)), part_id


def test_duplicate_part_number_raises():
    """Assumed unique, so it is asserted. If a restructure ever reuses a
    number, page_refs collide and two Parts merge — SOURCE_NOTES.md §12."""
    with pytest.raises(NavAmbiguous, match="Part22 appears twice"):
        build_sitemap(fixture_html("synthetic", "nav_duplicate_part.html"))


def test_a_page_without_a_nav_element_raises():
    with pytest.raises(NavNotFound):
        build_sitemap("<html><body><p>No nav here.</p></body></html>")


def test_an_empty_nav_raises():
    with pytest.raises(NavNotFound):
        build_sitemap('<div class="nested-nav"><ul></ul></div>')


# -- the full inventory ---------------------------------------------------


def test_the_whole_manual_parses(sitemap):
    """Corpus shape as measured on 27 July 2026. A moved count is a
    restructure, which is exactly the event worth being told about."""
    assert len(sitemap) == 502
    assert len({page.part_id for page in sitemap.values()}) == 54


def test_linked_attachments_are_not_pages(sitemap):
    """Part 51 links a .docx flowchart straight out of the nav. It is a
    resource the nav points at, not a page: no <main>, no prose, nothing to
    chunk. See SOURCE_NOTES.md §13."""
    assert all(page.url.startswith(f"{BASE}/") for page in sitemap.values())
    assert not any(page.url.endswith(".docx") for page in sitemap.values())


def test_every_ref_the_inventory_derives_satisfies_the_schema(sitemap):
    schema = json.loads(config.PAGE_SCHEMA_PATH.read_text(encoding="utf-8"))
    page_ref = re.compile(schema["properties"]["page_ref"]["pattern"])
    part_id = re.compile(schema["properties"]["part_id"]["pattern"])

    for page in sitemap.values():
        assert page_ref.match(page.page_ref), page.page_ref
        assert part_id.match(page.part_id), page.part_id


def test_urls_and_refs_are_unique_across_the_whole_manual(sitemap):
    refs = [page.page_ref for page in sitemap.values()]
    assert len(set(refs)) == len(refs)


def test_the_nav_is_the_same_on_every_page(sitemap):
    """The full sidebar renders into every page, so one fetch is the whole
    inventory (SOURCE_NOTES.md §2). If that ever stops being true, the crawl
    needs a different seed strategy."""
    from conftest import page_html

    for name in ("part22_1", "part32b_2_3", "part22_annex"):
        assert build_sitemap(page_html(name)) == sitemap, name


# -- serialisation --------------------------------------------------------


def test_write_sitemap_is_byte_stable(tmp_path, sitemap):
    """Rule 2. Writing the same inventory twice must not touch the file."""
    path = tmp_path / "sitemap.json"

    write_sitemap(sitemap, path)
    first = path.read_bytes()
    stamp = path.stat().st_mtime_ns

    write_sitemap(sitemap, path)
    assert path.read_bytes() == first
    assert path.stat().st_mtime_ns == stamp, "the file was rewritten unchanged"


def test_write_sitemap_output_is_sorted_and_newline_terminated(tmp_path, sitemap):
    path = tmp_path / "sitemap.json"
    write_sitemap(sitemap, path)
    text = path.read_text(encoding="utf-8")

    assert text.endswith("\n")
    document = json.loads(text)
    refs = [page["page_ref"] for page in document["pages"]]
    assert refs == sorted(refs)
    assert [part["part_id"] for part in document["parts"]] == sorted(
        part["part_id"] for part in document["parts"]
    )
    assert sum(part["page_count"] for part in document["parts"]) == len(sitemap)
