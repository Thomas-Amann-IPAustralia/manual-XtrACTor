"""The hyperlinks, and the offsets that put them back where they were.

`text` is the words with the markup gone, and until `links.py` the markup that
went included every `<a>` the Manual set. The tests that matter here are the
ones about offsets, because a link whose span has drifted by one character
underlines the wrong words while looking perfectly well-formed — the same shape
of failure `test_blocks.py` guards against, and the reason both invariants are
checked over every saved page rather than over a sample.
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from tmm_snapshot import config
from tmm_snapshot.chunker import chunk_body
from tmm_snapshot.links import extract_links
from tmm_snapshot.page import (
    _normalised_positions,
    flatten_spans,
    flatten_text,
    normalise_text,
    parse_page,
    resolve_nav,
)

from conftest import PAGE_SLUGS, page_html, page_url


def fragment(html: str):
    return BeautifulSoup(f"<div>{html}</div>", config.HTML_PARSER).div


def links(html: str) -> list[dict]:
    return extract_links(fragment(html))


# -- the invariant --------------------------------------------------------


def test_the_offsets_name_the_words_the_link_holds():
    body = fragment(
        "<p>Under <a href='/act/s217a'>section 217A</a> of the Act, a fee "
        "applies.</p>"
    )
    found = extract_links(body)
    text = flatten_text(body)

    assert text[found[0]["start"] : found[0]["end"]] == found[0]["text"] == "section 217A"


@pytest.mark.parametrize("name", sorted(PAGE_SLUGS))
def test_every_link_of_every_real_page_names_its_own_words(name, sitemap):
    """Over every saved page, not a sample. `validate._link_failures` makes the
    same assertion over the whole snapshot; this one fails at the parser."""
    nav = resolve_nav(page_url(name), sitemap)
    record, body = parse_page(page_html(name), nav)

    for chunk in chunk_body(body, record, nav, sitemap):
        for link in chunk.links:
            assert (
                chunk.text[link["start"] : link["end"]] == link["text"]
            ), f"{chunk.chunk_ref} {link['href']}"


@pytest.mark.parametrize("name", sorted(PAGE_SLUGS))
def test_the_positions_agree_with_the_normalisation_they_mirror(name, sitemap):
    """`_normalised_positions` re-implements `normalise_text` in order to say
    where each character went. If the two ever disagree every offset in the
    snapshot is wrong, so the equality is asserted on real markup rather than
    trusted to the two functions being read side by side."""
    nav = resolve_nav(page_url(name), sitemap)
    _, body = parse_page(page_html(name), nav)
    raw = str(body.get_text())

    assert _normalised_positions(raw)[0] == normalise_text(raw)


def test_flatten_spans_returns_the_text_flatten_text_would():
    body = fragment(
        "<p>A paragraph with <a href='/a'>a link</a> in it.</p>"
        "<ul><li>An item with <a href='/b'>another</a>.</li></ul>"
    )

    assert flatten_spans(body, frozenset({"a"}))[0] == flatten_text(body)


# -- what is recorded ------------------------------------------------------


def test_the_href_is_recorded_as_written():
    """Root-relative for a Manual page, absolute for everything else, and
    resolved neither way. Same rule as an image's `src`: rewriting a URL is a
    transformation, and this record has to stay faithful to the source."""
    found = links('<p><a href="/trademark/2.-accessing-documents">Part 61.2</a></p>')

    assert found[0]["href"] == "/trademark/2.-accessing-documents"


def test_links_come_back_in_document_order():
    found = links(
        "<p><a href='/one'>First</a> then <a href='/two'>second</a> then "
        "<a href='/three'>third</a>.</p>"
    )

    assert [link["text"] for link in found] == ["First", "second", "third"]
    assert [link["start"] for link in found] == sorted(
        link["start"] for link in found
    )


def test_two_links_with_the_same_words_are_two_links():
    """91 anchors in the corpus share their words with another anchor in the
    same chunk. A consumer matching a link to its position by searching for the
    words would have to guess between them; the offsets do not."""
    found = links(
        "<p>See <a href='/first'>the Act</a> and again <a href='/second'>the "
        "Act</a>.</p>"
    )

    assert len(found) == 2
    assert found[0]["text"] == found[1]["text"] == "the Act"
    assert found[0]["start"] != found[1]["start"]


def test_an_anchor_with_no_href_is_not_a_link():
    """`<a name="...">` is an anchor point, not a link — the same test
    `citations.extract_internal_refs` applies."""
    assert links('<p><a name="top">A target</a>.</p>') == []


def test_a_wordless_anchor_keeps_its_href_and_records_where_it_sat():
    """Five anchors in the corpus hold no words at all. One of them is where
    Part 32A.1's TMA1995/s42 edge comes from, so dropping them would lose a
    citation the pipeline already reads. The empty span keeps the offsets
    honest: text[start:end] is '', which is exactly what the anchor holds."""
    body = fragment("<p>Before <a href='/s42.html'> </a>after.</p>")
    found = extract_links(body)
    text = flatten_text(body)

    assert found[0]["href"] == "/s42.html"
    assert found[0]["text"] == ""
    assert found[0]["start"] == found[0]["end"]
    assert text[found[0]["start"] : found[0]["end"]] == ""


# -- the shapes the CMS produces ------------------------------------------


def test_a_link_spanning_a_wrapper_still_names_its_own_words():
    """The CMS wraps link text in `<span>` and `<em>` freely, and those
    contribute no separator — the same rule `flatten_text` applies to a
    sentence."""
    found = links(
        "<p>Under <a href='/s41'><span>section </span><em>41</em></a> of the "
        "Act.</p>"
    )

    assert found[0]["text"] == "section 41"


def test_a_link_inside_a_list_item_is_offset_against_the_whole_chunk():
    """Offsets are into `chunk.text`, which joins the items — so the second
    item's link sits past the first item's words, not at the start of its
    own."""
    body = fragment(
        "<ul><li>An item of some length.</li>"
        "<li>An item with <a href='/a'>a link</a>.</li></ul>"
    )
    found = extract_links(body)
    text = flatten_text(body)

    assert found[0]["start"] > len("An item of some length.")
    assert text[found[0]["start"] : found[0]["end"]] == "a link"


def test_a_link_in_a_table_cell_is_recorded_like_any_other():
    """27 of the corpus's links sit in a table cell, most of them on the
    Relevant Legislation pages, which are nothing but tables of them."""
    body = fragment(
        "<table><tbody><tr><td>Section 224</td>"
        "<td><a href='/s224.html'>Extension of time</a></td></tr></tbody></table>"
    )
    found = extract_links(body)
    text = flatten_text(body)

    assert text[found[0]["start"] : found[0]["end"]] == "Extension of time"


def test_zero_width_characters_do_not_shift_a_link():
    """The CMS sprinkles zero-width spaces through the prose — the opening line
    of Part 22.1 carries seven consecutive ones. They are dropped from `text`,
    so an offset counted before they were dropped would be wrong by as many."""
    body = fragment(
        "<p>​​Before <a href='/a'>the link</a>​ after.</p>"
    )
    found = extract_links(body)
    text = flatten_text(body)

    assert text[found[0]["start"] : found[0]["end"]] == "the link"


# -- the page that prompted the field --------------------------------------


def test_part_61_2_keeps_its_link_to_section_217a(sitemap):
    """The Manual links `section 217A` to TimeBase rather than to AustLII, so
    `_href_edges` never saw it and the provision is recorded as a guess from
    the prose. The link itself is now in the record whatever the citation layer
    made of it."""
    nav = resolve_nav(page_url("part61_2"), sitemap)
    record, body = parse_page(page_html("part61_2"), nav)
    chunks = {chunk.chunk_ref: chunk for chunk in chunk_body(body, record, nav, sitemap)}

    chunk = chunks["TMM/Part61/2/2/2"]
    hrefs = {link["text"]: link["href"] for link in chunk.links}

    assert hrefs["section 217A"] == (
        "http://www.timebase.com.au/IPAust/index.cfm?id=tmact:217a"
    )
    assert hrefs["Schedule 9"] == (
        "http://www.timebase.com.au/IPAust/index.cfm?id=tmreg:sch9"
    )


def test_the_page_that_prompted_the_field_records_every_anchor(sitemap):
    """Every `<a href>` in the cleaned body reaches a chunk on this page. The
    corpus-wide figure is 2,218 of 2,223; the five that do not are inside
    headings that open subsections, of which this page has none."""
    nav = resolve_nav(page_url("part61_2"), sitemap)
    record, body = parse_page(page_html("part61_2"), nav)
    anchors = sorted(str(a["href"]) for a in body.find_all("a", href=True))

    recorded = sorted(
        link["href"]
        for chunk in chunk_body(body, record, nav, sitemap)
        for link in chunk.links
    )

    assert recorded == anchors
