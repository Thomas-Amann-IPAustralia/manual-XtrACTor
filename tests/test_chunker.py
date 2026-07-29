"""T5 — the cleaned body, cut into retrievable passages."""

from __future__ import annotations

import re

import pytest

from tmm_snapshot.chunker import (
    MAX_CHUNK_CHARS,
    MIN_FRAGMENT_CHARS,
    MIN_HEADING_CHUNK_CHARS,
    ChunkRefCollision,
    SuppressedHeading,
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


def synthetic_from(html, nav=NESTED_NAV):
    """Chunk a fixture that a test has edited, to model a Manual amendment."""
    record, body = parse_page(html, nav)
    return chunk_body(body, record, nav)


def body_of(markup, nav=NESTED_NAV):
    """Chunk `markup` inside a real page shell.

    `parse_page` locates the prose through the Drupal shell and raises when it
    cannot, so a bare fragment is not a page. This grafts the markup into a
    saved fixture's body field, which is the same substitution the amendment
    tests above do by hand.
    """
    shell = fixture_html("synthetic", "page_nested_headings.html")
    field = shell.index("field--name-body")
    opening = shell.index(">", field) + 1
    closing = shell.rindex("</div>", opening, shell.index("views-element-container"))
    return synthetic_from(shell[:opening] + markup + shell[closing:], nav)


@pytest.fixture(scope="module")
def nested_html():
    return fixture_html("synthetic", "page_nested_headings.html")


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


def test_an_unnumbered_heading_is_addressed_by_a_slug_of_its_text(nested):
    """SOURCE_NOTES.md §§7, 18. The Manual did not number it, so we do not
    invent a number — but its own words are an address, and a positional one
    is not: it moves whenever anything above it does."""
    unnumbered = [
        chunk
        for chunk in nested
        if chunk.heading_path[-1] == "An unnumbered second-level heading"
    ]

    assert [chunk.chunk_ref for chunk in unnumbered] == [
        "TMM/Part22/9/an-unnumbered-second-level-heading"
    ]


def test_a_numbered_heading_still_wins_over_its_text(nested):
    """The Manual's own number is the strongest address available and is not
    displaced by the slug fallback."""
    numbered = [
        chunk for chunk in nested if chunk.chunk_ref.startswith("TMM/Part22/9/9/")
    ]

    assert numbered, "the fixture has numbered headings"
    for chunk in numbered:
        # Digits and separators only — a dotted '9.1.1' becomes '/9/1/1'.
        assert re.fullmatch(r"TMM/Part22/9(/\d+[A-Z]?)+(~\d+)?", chunk.chunk_ref)


def test_inserting_a_section_does_not_move_a_slug_addressed_chunk(nested_html):
    """The whole point of the change. Under positional addressing every ref
    after an insertion silently repointed; a slug is unmoved, and the new
    section simply gets an address of its own.

    Annex A13 is where this bites: 627 slug-addressed chunks on one page, in a
    glossary the Manual calls non-exhaustive.
    """
    before = {chunk.chunk_ref for chunk in synthetic_from(nested_html)}

    inserted = nested_html.replace(
        "<h2>", '<h2>A brand new section</h2><p>Inserted at the top.</p><h2>', 1
    )
    after = {chunk.chunk_ref for chunk in synthetic_from(inserted)}

    assert "TMM/Part22/9/a-brand-new-section" in after
    assert before - after == set(), "no existing address may be displaced"


def test_a_heading_of_punctuation_alone_falls_back_to_position(nested_html):
    """A slug of nothing is not an address. Never seen in the corpus; this is
    what happens if the CMS produces one."""
    odd = nested_html.replace(
        "An unnumbered second-level heading", "— — —", 1
    )
    refs = [chunk.chunk_ref for chunk in synthetic_from(odd)]

    assert any("#" in ref for ref in refs)


def test_prose_above_the_first_heading_keeps_the_page_in_its_path(nested):
    assert nested[0].chunk_ref == "TMM/Part22/9#1"
    assert nested[0].heading_path == [
        "Part 22 Section 41 - Capable of Distinguishing",
        "22.9. A page with nested headings",
    ]


def test_the_page_preamble_is_always_ordinal_1_and_so_cannot_shift(nested_html):
    """Why `#N` was left in place for headingless sections rather than
    replaced. A section with no heading is the prose above the *first*
    heading, so it is the first section by construction — there is no
    insertion that puts anything ahead of it. 496 of the corpus's 498
    positional chunks sit at #1 for that reason; the other two are Part 29.9's
    repeated label, which has no stable address available at all.
    """
    inserted = nested_html.replace(
        "<h2>", '<h2>A brand new section</h2><p>Inserted at the top.</p><h2>', 1
    )

    assert synthetic_from(inserted)[0].chunk_ref == "TMM/Part22/9#1"


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


# -- a heading that is the section ----------------------------------------

HEADING_ONLY_NAV = NavPage(
    url=(
        "https://manuals.ipaustralia.gov.au/trademark/"
        "9.-a-page-whose-headings-carry-the-content"
    ),
    page_ref="TMM/Part22/9",
    part_id="Part22",
    part_title="Part 22 Section 41 - Capable of Distinguishing",
    nav_title="9. A page whose headings carry the content",
    nav_ordinal=9,
    kind="body",
)

REPEATED_LABEL_NAV = NavPage(
    url=(
        "https://manuals.ipaustralia.gov.au/trademark/"
        "10.-a-page-with-a-repeated-heading-label"
    ),
    page_ref="TMM/Part22/10",
    part_id="Part22",
    part_title="Part 22 Section 41 - Capable of Distinguishing",
    nav_title="10. A page with a repeated heading label",
    nav_ordinal=10,
    kind="body",
)


@pytest.fixture(scope="module")
def heading_only():
    return synthetic("page_heading_only_sections.html", HEADING_ONLY_NAV)


def test_a_heading_with_nothing_under_it_is_still_chunked(heading_only):
    """Part 61.3 states two of its four sections entirely in their own
    heading. Dropping the section lost the words outright — the page has four
    propositions and the snapshot held two."""
    found = {chunk.chunk_ref: chunk for chunk in heading_only}

    assert "TMM/Part22/9/9/2" in found
    assert found["TMM/Part22/9/9/2"].text == (
        "9.2 Documents that are not made available for public inspection can "
        "be requested under the Freedom of Information Act."
    )


def test_a_heading_only_section_keeps_its_citations(heading_only):
    """Parts 49, 52 and 55 set their footnotes as an `<h4>`. Part 55.2's
    reference to AKT Consultants Pty Ltd v Alfa Laval Lund AB reached no case
    list at all while those headings were being dropped."""
    cases = {case["id"] for chunk in heading_only for case in chunk.cases}

    assert "CASE/2006/IPR/70/347" in cases


def test_an_empty_heading_is_not_chunked(heading_only):
    """The CMS leaves behind headings holding only a stripped image or a
    non-breaking space. There is nothing in one to record."""
    assert all(chunk.text for chunk in heading_only)


def test_a_heading_only_section_reads_as_its_own_leaf(heading_only):
    found = {chunk.chunk_ref: chunk for chunk in heading_only}
    chunk = found["TMM/Part22/9/9/2"]

    assert chunk.heading_path[-1] == chunk.text


# -- a label the Manual reuses --------------------------------------------


def test_a_repeated_heading_label_falls_back_to_position():
    """Part 29.9 calls the applicant of both worked examples 'XYZ Company'.
    That is not a numbering defect and there is nobody to correct it, so the
    two sections take positional addresses rather than the run failing."""
    found = [chunk.chunk_ref for chunk in synthetic(
        "page_repeated_heading_label.html", REPEATED_LABEL_NAV
    )]

    assert "TMM/Part22/10#2" in found
    assert "TMM/Part22/10#4" in found
    assert not any(ref.endswith("/xyz-company") for ref in found)


def test_a_label_used_once_still_addresses_by_slug():
    """The fallback is scoped to the labels that actually repeat: the other
    headings on the same page keep their slugs."""
    found = [chunk.chunk_ref for chunk in synthetic(
        "page_repeated_heading_label.html", REPEATED_LABEL_NAV
    )]

    assert "TMM/Part22/10/grown-in-australia" in found
    assert "TMM/Part22/10/casino-s-best-beef" in found


# -- a heading the Manual set in bold instead of marking up ----------------

EMPHASIS_NAV = NavPage(
    url=(
        "https://manuals.ipaustralia.gov.au/trademark/"
        "7.-a-page-whose-subsections-are-bold-paragraphs"
    ),
    page_ref="TMM/Part22/7",
    part_id="Part22",
    part_title="Part 22 Section 41 - Capable of Distinguishing",
    nav_title="7. A page whose subsections are bold paragraphs",
    nav_ordinal=7,
    kind="body",
)


@pytest.fixture(scope="module")
def emphasis():
    return synthetic("page_emphasis_headings.html", EMPHASIS_NAV)


def test_a_bold_numbered_paragraph_becomes_a_heading(emphasis):
    """456 of the Manual's numbered subsections are set as bold paragraphs
    rather than <h2>-<h4>. Cutting on markup alone left 39% of the corpus
    text with no heading_path at all."""
    found = {chunk.chunk_ref: chunk for chunk in emphasis}

    assert "TMM/Part22/7/7/1" in found
    assert found["TMM/Part22/7/7/1"].heading_path[-1] == (
        "7.1 Ownership of the trade mark"
    )
    assert found["TMM/Part22/7/7/1"].text == (
        "An applicant must be the owner of the trade mark."
    )


def test_an_inferred_heading_is_marked_as_inferred(emphasis):
    """The one inference in the pipeline, and the only thing keeping it
    honest is that a consumer can see which boundaries were the Manual's."""
    found = {chunk.chunk_ref: chunk for chunk in emphasis}

    assert found["TMM/Part22/7/7/1"].heading_source == "emphasis"
    assert found["TMM/Part22/7#1"].heading_source is None


def test_a_marked_up_heading_still_reads_as_markup(sitemap):
    found = chunks("part22_1", sitemap)

    assert [chunk.heading_source for chunk in found] == [None, "markup", "markup"]


def test_the_level_comes_from_the_number_not_the_typography(emphasis):
    """'7.1.1' is one component deeper than '7.1', so it nests under it —
    there is no tag name to read a depth from."""
    found = {chunk.chunk_ref: chunk for chunk in emphasis}

    assert found["TMM/Part22/7/7/1/1"].heading_path[-2:] == [
        "7.1 Ownership of the trade mark",
        "7.1.1 Joint owners",
    ]


def test_a_paragraph_letter_nests_one_level_deeper(emphasis):
    """Part 32A sets '2.1.2(a)' under a real <h3>2.1.2</h3>, so a paragraph
    letter is a level and not a sibling."""
    found = {chunk.chunk_ref: chunk for chunk in emphasis}
    chunk = found["TMM/Part22/7/7-3-a-a-paragraph-letter"]

    assert chunk.heading_path[-2:] == [
        "7.3 A heading with no paragraph wrapper",
        "7.3(a) A paragraph letter",
    ]


def test_a_bold_paragraph_with_no_number_is_left_in_the_prose(emphasis):
    """898 paragraphs in the corpus are wholly bold and only 471 are
    headings. Typography alone does not decide this."""
    text = " ".join(chunk.text for chunk in emphasis)

    assert "Suggested Alternatives" in text
    assert not any("suggested" in chunk.chunk_ref for chunk in emphasis)


def test_a_number_belonging_to_another_page_is_left_in_the_prose(emphasis):
    """Part 60.4.25 prints '4.24.5 No Request for Transformation'. A heading
    whose number contradicts its page is what rule 3 says not to resolve."""
    text = " ".join(chunk.text for chunk in emphasis)

    assert "6.4 A number belonging to another page" in text


def test_a_partly_bold_paragraph_is_not_a_heading(emphasis):
    """A paragraph that emphasises its opening clause and continues in roman
    is a paragraph making a point."""
    text = " ".join(chunk.text for chunk in emphasis)

    assert "7.2 A bolded opening and then the sentence continues" in text


def test_digits_that_are_a_quantity_are_not_an_address(emphasis):
    """The lookahead that bounds the number is what separates the heading
    '7.1 Ownership' from the sentence '7.15% of applications'."""
    text = " ".join(chunk.text for chunk in emphasis)

    assert "7.15% of applications are affected" in text


def test_a_bare_strong_with_no_paragraph_wrapper_is_a_heading(emphasis):
    """Part 35.1 sets '1.5 Differences between a certification trade mark
    and a standard trade mark' as a <strong> loose in a layout div."""
    found = {chunk.chunk_ref: chunk for chunk in emphasis}

    assert found["TMM/Part22/7/7/3"].heading_path[-1] == (
        "7.3 A heading with no paragraph wrapper"
    )


def test_a_subsection_number_with_no_words_still_addresses(emphasis):
    """The Manual numbers 12 subsections and gives them no title. The number
    is the whole heading, and it is still the Manual's own address."""
    found = {chunk.chunk_ref: chunk for chunk in emphasis}

    assert found["TMM/Part22/7/7/1/2"].heading_path[-1] == "7.1.2"


def test_the_worst_real_page_recovers_its_structure(sitemap):
    """Part 10.3 prints 36 numbered subsections, every one a bold paragraph.
    It used to arrive as nine chunks with no heading_path at all."""
    found = chunks("part10_3", sitemap)
    addressed = [chunk for chunk in found if chunk.heading_path[2:]]

    assert len(found) > 30
    assert len(addressed) == len(found) - 1  # all but the page preamble
    assert "TMM/Part10/3/3/1/1" in {chunk.chunk_ref for chunk in found}


# -- a footnote is not a section ------------------------------------------


def test_a_superscript_marker_is_not_a_heading_number(sitemap):
    """Parts 49, 52 and 55 set footnotes as an <h4> whose marker is a <sup>.
    Flattened, '2 See AKT Consultants...' opens with '2', and footnote 2 took
    TMM/Part55/2/2 — which reads as heading 2 and is the parent of this
    page's real sections 2.1 to 2.5."""
    found = {chunk.chunk_ref for chunk in chunks("part55_2", sitemap)}

    assert "TMM/Part55/2/2" not in found
    assert "TMM/Part55/2/2/2" in found
    assert any("akt-consultants" in ref for ref in found)


def test_the_sections_of_that_page_keep_their_own_addresses(sitemap):
    found = {chunk.chunk_ref: chunk for chunk in chunks("part55_2", sitemap)}

    assert found["TMM/Part55/2/2/2"].heading_path[-1] == (
        "2.2 The general rule for award of costs"
    )


def test_a_superscript_elsewhere_in_a_heading_is_left_alone():
    """The test is that the leading number came out of the <sup>, not that
    the heading contains one anywhere."""
    found = body_of("<h3>3.1 Areas over 5 m<sup>2</sup></h3><p>Prose.</p>")

    assert found[0].chunk_ref == "TMM/Part22/9/3/1"


# -- a heading that only names the sections below it -----------------------


def test_a_heading_with_subsections_is_not_chunked_as_content():
    """The heading-as-content branch is for the heading that *is* the
    proposition. A heading with subsections beneath it did not hold its
    section's content — they do, and each already carries it in
    heading_path."""
    found = body_of(
        "<h3>3.1 A container</h3><h4>3.1.1 A subsection</h4><p>Prose.</p>"
    )

    assert [chunk.chunk_ref for chunk in found] == ["TMM/Part22/9/3/1/1"]
    assert found[0].heading_path[-2:] == ["3.1 A container", "3.1.1 A subsection"]


def test_a_short_heading_holding_its_own_content_is_dropped_loudly():
    """Part 23.2 prints a bare <h3>2.2</h3> over its subsections, and the
    Part 14 glossary sets 'A', 'B', 'C' over the terms filed under them.
    Dropping words is the one thing this pipeline may not do quietly."""
    with pytest.warns(SuppressedHeading, match="2.2"):
        found = body_of(
            "<h3>2.2</h3><h3>2.2.1 A sibling in the markup</h3><p>Prose.</p>"
        )

    assert [chunk.chunk_ref for chunk in found] == ["TMM/Part22/9/2/2/1"]


def test_a_long_heading_holding_its_own_content_is_kept(heading_only):
    """The length rule is scoped to markers. Part 61.3's propositions are
    the reason the branch exists and they stay."""
    found = {chunk.chunk_ref: chunk for chunk in heading_only}

    assert len(found["TMM/Part22/9/9/2"].text) >= MIN_HEADING_CHUNK_CHARS


# -- the ancestry a heading_path cannot describe ---------------------------


def test_every_heading_carries_its_level_its_source_and_its_chunk():
    """`heading_path` is a list of strings, so a consumer could see *that* a
    chunk sat under '2.3' and not what depth it was cut at, whether the Manual
    marked it up or the chunker inferred it, or how to address it."""
    cut = body_of(
        "<h2>9 Outer</h2><p>Outer prose.</p>"
        "<h3>9.1 Inner</h3><p>Inner prose.</p>"
        "<p><strong>9.1.1 Promoted</strong></p><p>Promoted prose.</p>"
    )
    leaf = {chunk.heading_path[-1]: chunk for chunk in cut}

    # The level of an inferred heading comes from the number the Manual
    # printed, not from a tag name it does not have: '9.1.1' is three
    # components and so sits where an <h4> sits.
    assert leaf["9.1.1 Promoted"].headings == [
        {"level": 2, "source": "markup", "ref": "TMM/Part22/9/9"},
        {"level": 3, "source": "markup", "ref": "TMM/Part22/9/9/1"},
        {"level": 4, "source": "emphasis", "ref": "TMM/Part22/9/9/1/1"},
    ]


def test_a_heading_holding_no_chunk_of_its_own_says_so_with_a_null_ref():
    """A heading whose content lives in its subsections is not cut
    (SOURCE_NOTES.md §27), so there is nothing to address — and 899 of the
    corpus's chunks have such an ancestor. Before 0.8.0 the only way to reach
    one was to match its text within the page, which is the fragile join
    `chunk_ref` exists to replace."""
    cut = body_of("<h2>9 Container</h2><h3>9.1 Inner</h3><p>Inner prose.</p>")

    assert [chunk.chunk_ref for chunk in cut] == ["TMM/Part22/9/9/1"]
    assert cut[0].headings == [
        {"level": 2, "source": "markup", "ref": None},
        {"level": 3, "source": "markup", "ref": "TMM/Part22/9/9/1"},
    ]


def test_a_split_sections_heading_is_held_by_its_opening_fragment():
    """Where a section had to be split its address belongs to no single chunk,
    and a link to the heading is aimed at where the section starts —
    SOURCE_NOTES.md §22, applied to the ancestry."""
    long_prose = "".join(f"<p>{'word ' * 200}</p>" for _ in range(6))
    cut = body_of(f"<h2>9 Long</h2>{long_prose}")

    assert len(cut) > 1
    assert {chunk.headings[-1]["ref"] for chunk in cut} == {"TMM/Part22/9/9~1"}


def test_the_headings_array_describes_the_heading_path_exactly():
    """The ancestor's text is deliberately not repeated — it is
    `heading_path[2:]`. What makes that safe is the correspondence being
    checked rather than trusted."""
    for chunk in body_of(
        "<p>Lead-in.</p><h2>9 Outer</h2><p>a</p><h3>9.1 Inner</h3><p>b</p>"
    ):
        assert len(chunk.headings) == len(chunk.heading_path) - 2
        if chunk.headings:
            assert chunk.headings[-1]["source"] == chunk.heading_source
        else:
            assert chunk.heading_source is None


def test_a_heading_that_is_never_cut_does_not_claim_a_label():
    """`_repeated_labels` used to count every section `_sections` produced,
    including the ones `chunk_body` then declines to cut. A label printed once
    as a never-chunked container and once as a real section read as repeated,
    and the real section was demoted to the positional form although nothing
    else claimed its slug — silently reintroducing the exposure
    SOURCE_NOTES.md §18 measured and removed."""
    cut = body_of(
        "<h2>Disclaimer</h2><h3>Sub one</h3><p>Sub prose.</p>"
        "<h2>Other</h2><p>Other prose.</p>"
        "<h2>Disclaimer</h2><p>The real disclaimer text.</p>"
    )

    assert [chunk.chunk_ref for chunk in cut] == [
        "TMM/Part22/9/sub-one",
        "TMM/Part22/9/other",
        "TMM/Part22/9/disclaimer",
    ]


def test_two_sections_that_really_do_share_a_label_still_fall_back():
    """Part 29.9 titles both worked examples 'XYZ Company'. Both are cut, so
    both compete, and the positional form is the honest answer."""
    cut = body_of(
        "<h2>XYZ Company</h2><p>The first example.</p>"
        "<h2>XYZ Company</h2><p>The second example.</p>"
    )

    assert [chunk.chunk_ref for chunk in cut] == ["TMM/Part22/9#1", "TMM/Part22/9#2"]
