"""T5 — the cleaned body, cut into retrievable passages."""

from __future__ import annotations

import pytest

from tmm_snapshot.chunker import (
    MAX_CHUNK_CHARS,
    MIN_FRAGMENT_CHARS,
    ChunkRefCollision,
    chunk_body,
)
from tmm_snapshot.page import parse_page, resolve_nav
from tmm_snapshot.sitemap import NavPage

from conftest import fixture_html, page_html, page_url

NESTED_NAV = NavPage(
    url="https://manuals.ipaustralia.gov.au/trademark/9.-a-page-with-nested-headings",
    page_ref="TMM/Part22/9",
    part_id="Part22",
    part_title="Part 22 Section 41 - Capable of Distinguishing",
    nav_title="9. A page with nested headings",
    nav_ordinal=9,
    kind="body",
)

REPEATED_NAV = NavPage(
    url=(
        "https://manuals.ipaustralia.gov.au/trademark/"
        "8.-a-page-with-a-repeated-heading-number"
    ),
    page_ref="TMM/Part22/8",
    part_id="Part22",
    part_title="Part 22 Section 41 - Capable of Distinguishing",
    nav_title="8. A page with a repeated heading number",
    nav_ordinal=8,
    kind="body",
)


def chunks(name, sitemap):
    nav = resolve_nav(page_url(name), sitemap)
    record, body = parse_page(page_html(name), nav)
    return chunk_body(body, record, nav, sitemap)


def synthetic(filename, nav):
    record, body = parse_page(fixture_html("synthetic", filename), nav)
    return chunk_body(body, record, nav)


@pytest.fixture(scope="module")
def nested():
    return synthetic("page_nested_headings.html", NESTED_NAV)


# -- cutting --------------------------------------------------------------


def test_a_page_with_numbered_headings_cuts_on_them(sitemap):
    """Part 22.1 carries two numbered <h3>s and prose above the first."""
    found = chunks("part22_1", sitemap)

    assert [chunk.chunk_ref for chunk in found] == [
        "TMM/Part22/1#1",
        "TMM/Part22/1/1/1",
        "TMM/Part22/1/1/2",
    ]
    assert found[1].heading_path[-1] == "1.1 The 1955 Act"


def test_a_chunk_ref_reads_as_part_page_heading(sitemap):
    """SCHEMA.md §The chunk record: TMM/Part22/1/1/2 is Part 22, page 1,
    heading 1.2. The page's own number repeats, and that is the price of an
    address that can be read back to a heading the Manual prints."""
    found = {chunk.chunk_ref: chunk for chunk in chunks("part22_1", sitemap)}

    assert found["TMM/Part22/1/1/2"].heading_path[-1].startswith("1.2 ")


def test_a_page_with_no_sub_headings_is_one_chunk(sitemap):
    """A Relevant Legislation landing page is a mapping, not prose."""
    found = chunks("part22_landing", sitemap)

    assert len(found) == 1
    assert found[0].chunk_ref == "TMM/Part22/x-relevant-legislation44#1"
    assert found[0].heading_path == [
        "Part 22 Section 41 - Capable of Distinguishing",
        "22. Relevant Legislation",
    ]


def test_nothing_merges_across_a_heading(sitemap):
    """Two headings' prose in one chunk means a passage retrieved under the
    wrong heading, which is the whole failure the heading_path exists to
    prevent."""
    found = {chunk.chunk_ref: chunk for chunk in chunks("part22_1", sitemap)}

    assert "1955" in found["TMM/Part22/1/1/1"].text
    assert "Raising the Bar" not in found["TMM/Part22/1/1/1"].text


# -- heading ancestry -----------------------------------------------------


def test_heading_ancestry_runs_from_the_part_down(nested):
    found = {chunk.chunk_ref: chunk for chunk in nested}

    assert found["TMM/Part22/9/9/1/1/1"].heading_path == [
        "Part 22 Section 41 - Capable of Distinguishing",
        "22.9. A page with nested headings",
        "9.1 A numbered second-level heading",
        "9.1.1 A numbered third-level heading",
        "9.1.1.1 A numbered fourth-level heading",
    ]


def test_a_sibling_heading_closes_the_deeper_ones_above_it(nested):
    found = {chunk.chunk_ref: chunk for chunk in nested}

    assert found["TMM/Part22/9/9/1/2"].heading_path[-2:] == [
        "9.1 A numbered second-level heading",
        "9.1.2 A sibling of the third-level heading",
    ]


def test_a_highlighted_digit_does_not_truncate_the_address(sitemap):
    """Part 28.3 prints `3.<span class="highlightColorYellow">2</span>.1`, an
    editor's yellow highlight left inside a heading number. Read with a
    separator that heading is '3. 2 .1', whose leading address is '3' — which
    is how crawl #5 derived TMM/Part28/3/3 for both 3.2.1 and 3.3 and died on
    the collision. SOURCE_NOTES.md §7."""
    found = {chunk.chunk_ref: chunk for chunk in chunks("part28_3", sitemap)}

    assert found["TMM/Part28/3/3/2/1"].heading_path[-1] == "3.2.1"
    assert found["TMM/Part28/3/3/3"].heading_path[-1] == (
        "3.3 Whether instances of confusion have in fact occurred"
    )


def test_an_unnumbered_heading_falls_back_to_its_position(nested):
    """SOURCE_NOTES.md §7. The Manual did not number it, so we do not invent a
    number for it — the ordinal is the only address it has."""
    unnumbered = [
        chunk
        for chunk in nested
        if chunk.heading_path[-1] == "An unnumbered second-level heading"
    ]

    assert [chunk.chunk_ref for chunk in unnumbered] == ["TMM/Part22/9#6"]


def test_prose_above_the_first_heading_keeps_the_page_in_its_path(nested):
    assert nested[0].chunk_ref == "TMM/Part22/9#1"
    assert nested[0].heading_path == [
        "Part 22 Section 41 - Capable of Distinguishing",
        "22.9. A page with nested headings",
    ]


# -- splitting ------------------------------------------------------------


def test_an_over_long_section_splits_on_paragraph_boundaries(nested):
    split = [chunk for chunk in nested if chunk.chunk_ref.startswith("TMM/Part22/9/9/3")]

    assert [chunk.chunk_ref for chunk in split] == [
        "TMM/Part22/9/9/3~1",
        "TMM/Part22/9/9/3~2",
    ]
    assert [chunk.fragment for chunk in split] == [
        {"index": 1, "count": 2},
        {"index": 2, "count": 2},
    ]
    for chunk in split:
        assert chunk.text.startswith("Paragraph ")


def test_the_fragments_of_a_split_section_share_one_address(nested):
    """'#3~1', '#3~2' — one section, two fragments. Not two sections."""
    split = [chunk for chunk in nested if chunk.fragment is not None]
    bases = {chunk.chunk_ref.split("~")[0] for chunk in split}

    assert len(bases) == 1


def test_a_short_tail_folds_into_the_previous_fragment(nested):
    """A trailing sentence retrieved on its own is uninterpretable."""
    tail = [chunk for chunk in nested if chunk.chunk_ref == "TMM/Part22/9/9/3~2"][0]

    assert "A short trailing sentence." in tail.text
    assert not any(len(chunk.text) < MIN_FRAGMENT_CHARS for chunk in nested if chunk.fragment)


def test_an_unsplit_chunk_carries_no_fragment(nested):
    assert nested[0].fragment is None


def test_a_real_annex_splits(sitemap):
    """Annex A1 sets out the whole of the repealed section 41."""
    found = chunks("part22_annex", sitemap)

    assert len(found) == 2
    assert all(chunk.fragment is not None for chunk in found)
    assert all(len(chunk.text) < MAX_CHUNK_CHARS * 1.5 for chunk in found)


# -- the record -----------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["part22_1", "part22_landing", "part22_annex", "part32a_2_3", "part32b_2_3"]
)
def test_ordinals_are_contiguous_from_one(name, sitemap):
    """T10 asserts this too. It is what makes previous/next arithmetic instead
    of a stored pointer."""
    found = chunks(name, sitemap)

    assert [chunk.ordinal for chunk in found] == list(range(1, len(found) + 1))


@pytest.mark.parametrize(
    "name", ["part22_1", "part22_landing", "part22_annex", "part32a_2_3", "part32b_2_3"]
)
def test_chunk_refs_are_unique_within_a_page(name, sitemap):
    found = chunks(name, sitemap)

    assert len({chunk.chunk_ref for chunk in found}) == len(found)


@pytest.mark.parametrize(
    "name", ["part22_1", "part22_landing", "part22_annex", "part32a_2_3", "part32b_2_3"]
)
def test_two_runs_over_one_fixture_agree_exactly(name, sitemap):
    """Rule 2, at the chunk level. If this ever fails, every crawl rewrites
    every page and the git history stops being an amendment log."""
    first = chunks(name, sitemap)
    second = chunks(name, sitemap)

    assert first == second


def test_the_kind_comes_from_the_nav_entry(sitemap):
    """Structural, from the sitemap. Nothing here reads the page's content to
    decide what sort of page it is."""
    assert {chunk.kind for chunk in chunks("part22_landing", sitemap)} == {"landing"}
    assert {chunk.kind for chunk in chunks("part22_annex", sitemap)} == {"annex"}
    assert {chunk.kind for chunk in chunks("part22_1", sitemap)} == {"body"}


def test_the_hash_is_of_the_text_alone(sitemap):
    found = chunks("part22_1", sitemap)

    assert all(chunk.content_hash.startswith("sha256:") for chunk in found)
    assert len({chunk.content_hash for chunk in found}) == len(found)


def test_text_is_the_manuals_own_words(sitemap):
    """SCHEMA.md's worked example, verbatim. Nested <span><i><i> around the
    instrument names must not leave a space before the full stop, and adjacent
    paragraphs must not be welded into one word."""
    found = {chunk.chunk_ref: chunk for chunk in chunks("part22_1", sitemap)}

    assert found["TMM/Part22/1/1/2"].text.startswith(
        "Section 41 of the Trade Marks Act 1995 was amended by the Intellectual "
        "Property Laws Amendment (Raising the Bar) Act 2012. The repealed "
        "section 41 is set out in full in Annex A1 to this Part of the Manual. "
        "Raising the Bar came into effect on 15 April 2013."
    )


def test_the_body_is_not_consumed_by_chunking(sitemap):
    """crawl --from-raw re-parses the same document, and the citation
    extractors walk the fragments. They must be copies."""
    nav = resolve_nav(page_url("part22_1"), sitemap)
    record, body = parse_page(page_html("part22_1"), nav)

    first = chunk_body(body, record, nav, sitemap)
    second = chunk_body(body, record, nav, sitemap)

    assert first == second


# -- citations reach the chunk --------------------------------------------


def test_citations_are_extracted_before_the_text_is_flattened(sitemap):
    """SOURCE_NOTES.md §3. Run the body through a text extractor first and the
    entire high-confidence citation layer goes with the hrefs."""
    found = {chunk.chunk_ref: chunk for chunk in chunks("part22_1", sitemap)}
    provisions = found["TMM/Part22/1/1/2"].provisions

    assert {record["id"] for record in provisions} >= {"TMA1995/s41", "AIA1901/s7"}
    assert any(record["extraction"] == "href" for record in provisions)


def test_internal_refs_need_the_inventory(sitemap):
    """Without a sitemap a reference cannot be resolved, and an unresolved
    reference is dropped rather than guessed."""
    nav = resolve_nav(page_url("part22_1"), sitemap)
    record, body = parse_page(page_html("part22_1"), nav)

    with_inventory = chunk_body(body, record, nav, sitemap)
    without = chunk_body(body, record, nav)

    assert any(chunk.internal_refs for chunk in with_inventory)
    assert not any(chunk.internal_refs for chunk in without)


# -- failing loud ---------------------------------------------------------


def test_a_repeated_heading_number_raises():
    """Two passages sharing an address means every citation of it is
    ambiguous. Rule 3: a missing record is recoverable, a wrong one is not."""
    with pytest.raises(ChunkRefCollision, match="TMM/Part22/8/8/1"):
        synthetic("page_repeated_heading_number.html", REPEATED_NAV)
