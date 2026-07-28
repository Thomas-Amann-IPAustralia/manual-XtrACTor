"""T4 — page-level metadata, and a body clean enough to chunk."""

from __future__ import annotations

from datetime import date

import pytest
from bs4 import BeautifulSoup

from tmm_snapshot import config
from tmm_snapshot.page import (
    PageNotInSitemap,
    UnrecognisedMarkup,
    content_hash,
    normalise_text,
    parse_page,
    resolve_nav,
)
from tmm_snapshot.sitemap import NavPage

from conftest import fixture_html, page_html, page_url


def parse(name, sitemap):
    nav = resolve_nav(page_url(name), sitemap)
    return parse_page(page_html(name), nav)


def body_text(name, sitemap):
    _, body = parse(name, sitemap)
    return normalise_text(body.get_text(" "))


# -- metadata -------------------------------------------------------------


def test_a_normal_page(sitemap):
    record, _ = parse("part22_1", sitemap)

    assert record.page_ref == "TMM/Part22/1"
    assert record.part_id == "Part22"
    assert record.h1 == (
        "22.1. Registrability under section 41 of the Trade Marks Act 1995"
    )
    assert record.nav_title == "1. Registrability under section 41 of the Trade Marks Act 1995"
    assert record.date_published == date(2022, 12, 19)
    assert record.last_amended == date(2022, 12, 19)
    assert record.amendment_note == "Minor updates."
    assert record.extractor_version == config.EXTRACTOR_VERSION
    assert record.content_hash.startswith("sha256:")


def test_a_relevant_legislation_landing_page(sitemap):
    record, body = parse("part22_landing", sitemap)

    assert record.page_ref == "TMM/Part22/x-relevant-legislation44"
    assert record.h1 == "22. Relevant Legislation"
    assert resolve_nav(page_url("part22_landing"), sitemap).kind == "landing"
    assert "What is a trade mark?" in normalise_text(body.get_text(" "))


def test_an_annex(sitemap):
    record, _ = parse("part22_annex", sitemap)

    assert record.page_ref == "TMM/Part22/x-annex-a1-section-41-prior-to-raising-the-bar"
    assert record.h1 == "22. Annex A1 Section 41 prior to Raising the Bar"
    assert record.amendment_note == "Reviewed- no changes."


# -- archived pages (SOURCE_NOTES.md §15) ----------------------------------


def test_an_archived_page_is_recorded_with_no_body(sitemap):
    """No `div.field--name-body` at all, only the banner. The page is emptied,
    not misunderstood, and its amendment history is the point of keeping it.
    """
    record, body = parse("part23_archived", sitemap)

    assert record.archived is True
    assert record.part_id == "Part23"
    assert record.h1.startswith("Annex A4 - How to supply evidence of use")
    assert normalise_text(body.get_text(" ")) == "", "no prose left to chunk"

    # The reason not to drop the page: the archival is itself an amendment.
    assert record.last_amended == date(2023, 10, 10)
    assert record.amendment_note == "Not required."


def test_an_archived_page_yields_no_chunks(sitemap):
    from tmm_snapshot.chunker import chunk_body

    nav = resolve_nav(page_url("part23_archived"), sitemap)
    record, body = parse("part23_archived", sitemap)

    assert chunk_body(body, record, nav, sitemap) == []


def test_a_live_page_is_not_archived(sitemap):
    record, _ = parse("part22_1", sitemap)
    assert record.archived is False


def test_a_missing_body_without_the_banner_still_raises(sitemap):
    """The alarm must survive the exemption. A content wrapper that vanishes
    with no banner to explain it is still the markup moving under us.
    """
    html = page_html("part23_archived").replace(
        "This page has been archived.", "This page is temporarily unavailable."
    )
    nav = resolve_nav(page_url("part23_archived"), sitemap)

    with pytest.raises(UnrecognisedMarkup, match="content wrapper"):
        parse_page(html, nav)


def test_the_banner_is_matched_on_the_whole_string_not_a_substring(sitemap):
    """`div.alert` is Bootstrap, and the Manual uses it for ordinary in-body
    callouts. Only the exact sentence means 'archived'.
    """
    html = page_html("part23_archived").replace(
        "<p>This page has been archived.</p>",
        "<p>Note: This page has been archived. See the successor page.</p>",
    )
    nav = resolve_nav(page_url("part23_archived"), sitemap)

    with pytest.raises(UnrecognisedMarkup):
        parse_page(html, nav)


def test_the_two_colliding_pages_keep_their_own_parts(sitemap):
    plants, _ = parse("part32a_2_3", sitemap)
    wines, _ = parse("part32b_2_3", sitemap)

    assert (plants.part_id, wines.part_id) == ("Part32A", "Part32B")
    assert plants.content_hash != wines.content_hash


def test_the_most_recent_amendment_row_wins_regardless_of_row_order():
    """Rows are served newest-first, but that is a rendering choice. This
    fixture puts the newest row last, and its reason cell is empty — both are
    normal, per SOURCE_NOTES.md §5."""
    nav = NavPage(
        url="https://manuals.ipaustralia.gov.au/trademark/1.-a-page-with-a-blank-reason",
        page_ref="TMM/Part22/1",
        part_id="Part22",
        part_title="Part 22 Section 41 - Capable of Distinguishing",
        nav_title="1. A page with a blank reason",
        nav_ordinal=1,
        kind="body",
    )
    record, _ = parse_page(
        fixture_html("synthetic", "page_blank_amendment_reason.html"), nav
    )

    assert record.last_amended == date(2021, 11, 9)
    assert record.amendment_note is None
    assert record.date_published == date(2021, 11, 9)


# -- the cleaned body -----------------------------------------------------


@pytest.mark.parametrize(
    "name", ["part22_1", "part22_landing", "part22_annex", "part32b_2_3"]
)
def test_boilerplate_never_reaches_the_body(name, sitemap):
    """SOURCE_NOTES.md §6. Anything left here gets chunked, and then gets
    retrieved as though it were practice."""
    text = body_text(name, sitemap)

    for phrase in (
        "Skip to main content",
        "Back to top",
        "This document is controlled",
        "Delivering a world leading IP system",
        "Accessibility",
        "Privacy",
    ):
        assert phrase not in text, phrase


@pytest.mark.parametrize(
    "name", ["part22_1", "part22_landing", "part22_annex", "part32b_2_3"]
)
def test_the_amendment_table_never_reaches_the_body(name, sitemap):
    """It is metadata, and it would otherwise match every search for a date."""
    text = body_text(name, sitemap)

    assert "Amended Reason" not in text
    assert "Date Amended" not in text
    assert "Date Published" not in text


def test_the_nav_never_reaches_the_body(sitemap):
    """The whole Manual's table of contents renders into every page. Naive
    text extraction pulls all 500-odd nav titles into every chunk."""
    text = body_text("part22_1", sitemap)

    assert "Part 32B Examination of Trade Marks for Wines" not in text
    assert len(text) < 5_000, "the body looks like it still contains the nav"


def test_the_body_keeps_its_hrefs(sitemap):
    """SOURCE_NOTES.md §3. The AustLII links are the entire high-confidence
    citation layer; a body stripped to text takes them with it."""
    _, body = parse("part22_1", sitemap)
    hrefs = [a.get("href") for a in body.find_all("a")]

    assert any("austlii.edu.au" in href and "tma1995121/s41" in href for href in hrefs)
    assert "/trademark/annex-a1-section-41-prior-to-raising-the-bar" in hrefs


def test_headings_survive_for_the_chunker(sitemap):
    _, body = parse("part22_1", sitemap)
    headings = [h.get_text(" ", strip=True) for h in body.find_all(["h2", "h3", "h4"])]

    assert headings == [
        "1.1 The 1955 Act",
        "1.2 Intellectual Property Laws Amendment (Raising the Bar) Act 2012",
    ]


def test_zero_width_characters_are_stripped(sitemap):
    """The opening line of Part 22.1 carries seven consecutive ZWSPs."""
    assert "​" in page_html("part22_1")
    assert "​" not in body_text("part22_1", sitemap)


def test_normalise_text_collapses_whitespace_and_nbsp():
    assert normalise_text("  a  b\n\tc ​ ") == "a b c"


# -- hashing --------------------------------------------------------------


def test_the_hash_is_stable_across_repeated_parses(sitemap):
    """Rule 2 begins here: an unstable hash rewrites the page file on every
    crawl and the diff stops being an amendment log."""
    first, _ = parse("part22_1", sitemap)
    second, _ = parse("part22_1", sitemap)
    assert first.content_hash == second.content_hash


def test_the_hash_ignores_presentational_churn(sitemap):
    """Drupal rewrites classes, ids and inline styles without the Manual
    having changed a word."""
    nav = resolve_nav(page_url("part22_1"), sitemap)
    original = page_html("part22_1")
    churned = original.replace(
        'class="clearfix text-formatted field field--name-body',
        'style="margin:0" data-build="17851" class="clearfix text-formatted field field--name-body',
    ).replace('id="zone1"', 'id="zone1" data-nonce="abc123"')

    assert churned != original
    assert parse_page(churned, nav)[0].content_hash == (
        parse_page(original, nav)[0].content_hash
    )


def test_the_hash_notices_a_changed_hyperlink(sitemap):
    """'Update hyperlinks' is one of the Manual's own amendment reasons. A
    hash over text alone would skip that page and the amendment would be
    invisible in the diff."""
    nav = resolve_nav(page_url("part22_1"), sitemap)
    original = page_html("part22_1")
    relinked = original.replace("tma1995121/s41.html", "tma1995121/s41A.html")

    assert relinked != original
    assert parse_page(relinked, nav)[0].content_hash != (
        parse_page(original, nav)[0].content_hash
    )


def test_the_hash_notices_a_changed_word(sitemap):
    nav = resolve_nav(page_url("part22_1"), sitemap)
    original = page_html("part22_1")
    edited = original.replace("came into effect on 15 April 2013", "came into effect on 16 April 2013")

    assert edited != original
    assert parse_page(edited, nav)[0].content_hash != (
        parse_page(original, nav)[0].content_hash
    )


def test_the_hash_is_insensitive_to_reformatted_whitespace(sitemap):
    nav = resolve_nav(page_url("part22_1"), sitemap)
    original = page_html("part22_1")
    reflowed = original.replace("</p>", "</p>\n    \n")

    assert reflowed != original
    assert parse_page(reflowed, nav)[0].content_hash == (
        parse_page(original, nav)[0].content_hash
    )


def test_content_hash_helper_matches_the_schema_pattern(sitemap):
    _, body = parse("part22_1", sitemap)
    digest = content_hash(body)
    assert len(digest) == len("sha256:") + 64
    assert digest[7:].islower()


# -- failing loud ---------------------------------------------------------


def test_a_url_outside_the_inventory_raises(sitemap):
    with pytest.raises(PageNotInSitemap, match="not in the nav inventory"):
        resolve_nav(
            "https://manuals.ipaustralia.gov.au/trademark/a-page-that-does-not-exist",
            sitemap,
        )


def test_resolve_nav_normalises_before_looking_up(sitemap):
    """The Manual links to itself over http, over https and relatively."""
    slug = "1.-registrability-under-section-41-of-the-trade-marks-act-1995"
    expected = resolve_nav(page_url("part22_1"), sitemap)

    for variant in (
        f"http://manuals.ipaustralia.gov.au/trademark/{slug}",
        f"/trademark/{slug}",
        f"https://manuals.ipaustralia.gov.au/trademark/{slug}/",
        f"https://manuals.ipaustralia.gov.au/trademark/{slug}#1.1-the-1955-act",
    ):
        assert resolve_nav(variant, sitemap) == expected, variant


def test_a_page_served_under_another_identity_raises(sitemap):
    """A redirect that lands on a different node would otherwise file that
    node's content under this Part — the §2 failure, arrived at sideways."""
    nav = resolve_nav(page_url("part22_1"), sitemap)
    impostor = page_html("part22_1").replace(
        "/trademark/1.-registrability-under-section-41-of-the-trade-marks-act-1995",
        "/trademark/2.3-section-41--capacity-to-distinguish1",
    )

    with pytest.raises(PageNotInSitemap, match="wrong Part"):
        parse_page(impostor, nav)


def test_a_page_with_no_main_raises(sitemap):
    nav = resolve_nav(page_url("part22_1"), sitemap)
    with pytest.raises(UnrecognisedMarkup, match="no <main>"):
        parse_page("<html><body><p>Nothing recognisable.</p></body></html>", nav)


def test_a_page_with_no_body_field_raises(sitemap):
    nav = resolve_nav(page_url("part22_1"), sitemap)
    soup = BeautifulSoup(page_html("part22_1"), config.HTML_PARSER)
    soup.select_one("div.field--name-body").decompose()

    with pytest.raises(UnrecognisedMarkup, match="content wrapper"):
        parse_page(str(soup), nav)


def test_an_unreadable_date_raises_rather_than_recording_null(sitemap):
    """A null would say 'the Manual does not date this page'. A markup change
    would then be indistinguishable from a fact."""
    nav = resolve_nav(page_url("part22_1"), sitemap)
    broken = page_html("part22_1").replace(
        '<time datetime="2022-12-19T12:00:00Z" class="datetime">19 Dec 2022</time>',
        '<time class="datetime">19 Dec 2022</time>',
        1,
    )
    assert broken != page_html("part22_1")

    with pytest.raises(UnrecognisedMarkup, match="datetime"):
        parse_page(broken, nav)


def test_a_page_with_no_amendment_table_records_nulls(sitemap):
    """Absent is different from unreadable: not every node need carry one."""
    nav = resolve_nav(page_url("part22_1"), sitemap)
    soup = BeautifulSoup(page_html("part22_1"), config.HTML_PARSER)
    soup.select_one("div.view-amended-reasons").decompose()

    record, _ = parse_page(str(soup), nav)
    assert record.last_amended is None
    assert record.amendment_note is None


# --------------------------------------------------------------------------
# Images
# --------------------------------------------------------------------------
#
# 169 of them across 39 pages, and on nine of those the image IS the page: a
# flowchart, a cross-search class table, the format of a summons. Those pages
# yield no chunks because there is no text in them to chunk, so until this was
# recorded they were indistinguishable from a page with nothing on it.

#: Part 22 Annex A2 — a real page whose entire content is one flowchart.
IMAGE_ONLY_SLUG = "annex-a2-flowchart-of--capable-of-distinguishing-"


def image_only(sitemap):
    url = f"https://manuals.ipaustralia.gov.au/trademark/{IMAGE_ONLY_SLUG}"
    nav = resolve_nav(url, sitemap)
    return parse_page(fixture_html("pages", f"{IMAGE_ONLY_SLUG}.html"), nav)


def test_an_image_only_page_records_its_image(sitemap):
    record, _ = image_only(sitemap)
    assert [image["src"] for image in record.images] == [
        "/sites/default/files/trademark/image/capable_of_distinguishing_flowchart.png"
    ]


def test_an_image_only_page_is_distinguishable_from_an_empty_one(sitemap):
    """The whole point. No chunks, not archived, but demonstrably not blank."""
    record, body = image_only(sitemap)
    assert body.get_text(strip=True) == ""
    assert record.archived is False
    assert record.images != ()


def test_a_missing_alt_is_null_not_empty_string(sitemap):
    """'no alt attribute' and 'an empty alt attribute' are different facts.

    The second is how HTML spells 'decorative, skip me'. Collapsing them would
    hide exactly what 'Accessibility fix - alternative text for images' — one
    of the Manual's own amendment reasons, on 28 pages — describes.
    """
    record, _ = image_only(sitemap)
    assert record.images[0]["alt"] is None


def with_images_in_body(name, markup, sitemap):
    """Parse a real page with `markup` appended inside its body field.

    Into the body field specifically: an `<img>` in the page title block or the
    chrome is not content, and `extract_images` reads the cleaned body for the
    same reason the chunker does.
    """
    nav = resolve_nav(page_url(name), sitemap)
    soup = BeautifulSoup(page_html(name), config.HTML_PARSER)
    body = soup.select_one("div.field--name-body")
    assert body is not None
    body.append(BeautifulSoup(markup, config.HTML_PARSER))
    return parse_page(str(soup), nav)[0]


def test_an_empty_alt_is_recorded_as_empty_string(sitemap):
    record = with_images_in_body("part22_1", '<img src="/x.png" alt="">', sitemap)
    assert {"src": "/x.png", "alt": ""} in list(record.images)


def test_alt_text_is_recorded_when_the_source_carries_it(sitemap):
    record = with_images_in_body(
        "part22_1", '<img src="/y.png" alt="A stylised platypus">', sitemap
    )
    assert {"src": "/y.png", "alt": "A stylised platypus"} in list(record.images)


def test_a_page_with_no_images_records_none(sitemap):
    record, _ = parse(name="part22_landing", sitemap=sitemap)
    assert record.images == ()


def test_images_are_sorted_and_deduplicated(sitemap):
    """Rule 2: an image used twice is one image, and reordering the prose
    around it must not rewrite the record."""
    record = with_images_in_body(
        "part22_1",
        '<img src="/b.png"><img src="/a.png"><img src="/b.png">',
        sitemap,
    )
    added = [
        image["src"] for image in record.images if image["src"] in ("/a.png", "/b.png")
    ]
    assert added == ["/a.png", "/b.png"]


def test_the_same_src_with_different_alt_is_two_records(sitemap):
    """Different alt text is a different fact about the same file, and the
    accessibility amendments are precisely edits to alt text."""
    record = with_images_in_body(
        "part22_1",
        '<img src="/c.png" alt="first"><img src="/c.png" alt="second">',
        sitemap,
    )
    alts = [image["alt"] for image in record.images if image["src"] == "/c.png"]
    assert alts == ["first", "second"]


def test_an_image_without_a_src_is_not_recorded(sitemap):
    """There is nothing to record and nothing a consumer could fetch."""
    record = with_images_in_body("part22_1", '<img alt="orphan">', sitemap)
    assert all(image["src"] for image in record.images)
    assert "orphan" not in [image["alt"] for image in record.images]
