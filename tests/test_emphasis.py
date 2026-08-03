"""The emphasis, and the offsets that put it back where it was.

`test_links.py`'s tests, pointed at the other field that positions markup in
the words, and for the same reason: a span whose offsets have drifted by one
character emphasises the wrong words while looking perfectly well-formed. The
invariant is checked over every saved page rather than over a sample.

The tests that carry weight here are the ones about nesting. HTML nests where
Word does not, so the legislation side's `weight: "bold-italic"` spelling has
no honest equivalent, and the decision to record one span per element rather
than merge them is pinned below.
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from tmm_snapshot import config
from tmm_snapshot.chunker import chunk_body
from tmm_snapshot.emphasis import EMPHASIS_TAGS, extract_emphasis
from tmm_snapshot.page import parse_page, resolve_nav

from conftest import PAGE_SLUGS, page_html, page_url


def fragment(html: str):
    return BeautifulSoup(f"<div>{html}</div>", config.HTML_PARSER).div


def emphasis(html: str) -> list[dict]:
    return extract_emphasis(fragment(html))


# -- the invariant --------------------------------------------------------


@pytest.mark.parametrize("name", sorted(PAGE_SLUGS))
def test_every_span_names_the_words_it_claims(name, sitemap):
    """`text[start:end] == span.text`, over every chunk of every saved page.

    The same corpus-wide contract `validate._emphasis_failures` enforces on the
    snapshot. Checked here too so a chunker change that moves the text is
    caught before anything is written.
    """
    nav = resolve_nav(page_url(name), sitemap)
    record, body = parse_page(page_html(name), nav)

    for chunk in chunk_body(body, record, nav, sitemap):
        for span in chunk.emphasis:
            assert chunk.text[span["start"] : span["end"]] == span["text"], (
                f"{chunk.chunk_ref} emphasis at [{span['start']}, "
                f"{span['end']}) does not name its own words"
            )


@pytest.mark.parametrize("name", sorted(PAGE_SLUGS))
def test_no_span_is_empty(name, sitemap):
    """Unlike `links`, which keeps zero-width anchors deliberately.

    An anchor with no words records a place the Manual put a link; an `<i>`
    around nothing asserts nothing about any words, and the corpus's 128 of
    them are CMS residue.
    """
    nav = resolve_nav(page_url(name), sitemap)
    record, body = parse_page(page_html(name), nav)

    for chunk in chunk_body(body, record, nav, sitemap):
        for span in chunk.emphasis:
            assert span["start"] < span["end"]
            assert span["text"] != ""


# -- nesting --------------------------------------------------------------


def test_nested_elements_are_two_spans_not_one_merged_weight():
    """`<u><i>x</i></u>` is one stretch of words carrying two assertions.

    1,271 of the corpus's spans are co-extensive with another. The legislation
    side spells the same situation `weight: "bold-italic"`, but only because a
    Word run carries both properties on one element — merging here would invent
    a thing the source does not have, and a consumer wanting the intersection
    can take it from two records and cannot un-take it from one.
    """
    found = emphasis("<p><u><i>Trade Marks Act 1995</i></u></p>")

    assert [(span["kind"], span["start"], span["end"]) for span in found] == [
        ("u", 0, 20),
        ("i", 0, 20),
    ]
    assert {span["text"] for span in found} == {"Trade Marks Act 1995"}


def test_document_order_is_outermost_first_where_they_nest():
    """The order `flatten_spans` returns, and the order the file keeps.

    A span is recorded where its element opens, so an enclosing element comes
    back before the one it encloses however deeply they nest.
    """
    found = emphasis("<p>a <strong>bold <em>and italic</em></strong> b</p>")

    assert [span["kind"] for span in found] == ["strong", "em"]
    assert [span["text"] for span in found] == ["bold and italic", "and italic"]


# -- what is recorded, and what is not ------------------------------------


def test_the_manual_s_choice_of_element_is_not_normalised():
    """`<i>` and `<em>` are different records, as are `<b>` and `<strong>`.

    Which of the pair the CMS emitted is a fact about the markup. Collapsing
    them would be asserting the two mean the same thing, and this pipeline has
    nowhere to put that claim.
    """
    found = emphasis("<p><i>one</i> <em>two</em> <b>three</b> <strong>four</strong></p>")

    assert [span["kind"] for span in found] == ["i", "em", "b", "strong"]


def test_a_repeated_phrase_is_two_spans():
    """Not deduplicated, for the reason `links` is not: two spans of the same
    words are two spans, and a set would lose the second of every pair."""
    found = emphasis("<p><i>Bali</i> and again <i>Bali</i></p>")

    assert len(found) == 2
    assert found[0]["start"] != found[1]["start"]
    assert {span["text"] for span in found} == {"Bali"}


def test_an_empty_element_records_nothing():
    found = emphasis("<p>before <i></i> after</p>")

    assert found == []


def test_nothing_outside_the_emphasis_tags_is_recorded():
    """`<span>` is how the CMS carries a highlight colour, and a heading number
    broken up by one is SOURCE_NOTES.md §7's problem, not this field's."""
    found = emphasis('<p><span class="fontSizeMedium">plain</span> <i>emphasised</i></p>')

    assert [span["kind"] for span in found] == ["i"]
    assert set(EMPHASIS_TAGS) == {"b", "em", "i", "strong", "sup", "u"}


# -- the cases this field was written for ---------------------------------


def test_a_footnote_marker_is_recorded_as_a_superscript(sitemap):
    """SOURCE_NOTES.md §26: a `<sup>` is a footnote marker and never a heading
    number. The chunker has always acted on that and never recorded it; Part
    55.2's marker is now visible in the output rather than only in control
    flow."""
    nav = resolve_nav(page_url("part55_2"), sitemap)
    record, body = parse_page(page_html("part55_2"), nav)

    superscripts = [
        span
        for chunk in chunk_body(body, record, nav, sitemap)
        for span in chunk.emphasis
        if span["kind"] == "sup"
    ]

    assert superscripts, "Part 55.2 sets its footnote marker in a <sup>"
    assert all(span["text"].strip() for span in superscripts)


def test_an_italic_case_name_sits_immediately_before_its_citation(sitemap):
    """The 437-of-522 result, on one real page.

    This asserts adjacency and nothing more. That the italic run *is* the
    decision's party names is a reading a consumer makes; the pipeline records
    that the Manual set those words apart and where they sit relative to a
    citation it already extracts.
    """
    nav = resolve_nav(page_url("part28_3"), sitemap)
    record, body = parse_page(page_html("part28_3"), nav)

    adjacent = 0
    for chunk in chunk_body(body, record, nav, sitemap):
        if not chunk.cases:
            continue
        for span in chunk.emphasis:
            if span["kind"] not in {"i", "em"}:
                continue
            following = chunk.text[span["end"] : span["end"] + 2]
            if following.lstrip().startswith(("[", "(")):
                adjacent += 1

    assert adjacent, (
        "Part 28.3 cites decisions and italicises their names; if this is zero "
        "the field has stopped reaching the words it was built for"
    )


def test_a_nested_identical_element_is_two_records(sitemap):
    """The CMS emits `<i><i>x</i></i>` — SOURCE_NOTES.md §4's `<span><i><i>`
    shape — so two records share a kind *and* their offsets. 193 of the
    corpus's spans. Kept rather than collapsed: collapsing asserts the two are
    one assertion, which is true of how they render and is still a
    normalisation, and it is the direction that cannot be undone."""
    found = emphasis("<p><i><i>ordinary signification</i></i></p>")

    assert found == [
        {"kind": "i", "text": "ordinary signification", "start": 0, "end": 22},
        {"kind": "i", "text": "ordinary signification", "start": 0, "end": 22},
    ]
    # And the documented dedupe key recovers the one assertion.
    assert len({(s["kind"], s["start"], s["end"]) for s in found}) == 1
