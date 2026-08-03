"""T6 — provisions, cases and internal cross references.

Every example in SOURCE_NOTES.md §§3, 4, 8 and 9 appears here, most of them
against the real page they were observed on.
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from tmm_snapshot import config
from tmm_snapshot.citations import (
    instrument_holds,
    _ANCHOR_HEADING_ADDRESS,
    UnknownInstrument,
    extract_cases,
    extract_internal_refs,
    extract_provisions,
    resolve_internal_refs,
)
from tmm_snapshot.links import extract_links
from tmm_snapshot.page import flatten_text, parse_page, resolve_nav
from tmm_snapshot.sitemap import NavPage

from conftest import page_html, page_url


def fragment(html: str):
    return BeautifulSoup(f"<div>{html}</div>", config.HTML_PARSER).div


def provisions(html: str) -> list[dict]:
    body = fragment(html)
    return extract_provisions(body, flatten_text(body))


def by_id(records: list[dict]) -> dict[str, dict]:
    return {record["id"]: record for record in records}


def refs(body, sitemap: dict[str, NavPage], page_ref: str | None = None) -> list[dict]:
    """`extract_internal_refs` as the chunker calls it: from links and text.

    Since 0.8.0 the function reads the anchors the chunk already recorded
    rather than the markup, so that the same reading settles a live chunk and
    a stored one. See ARCHITECTURE.md §Settling.
    """
    return extract_internal_refs(
        extract_links(body), flatten_text(body), sitemap, page_ref
    )


def targets(body, sitemap: dict[str, NavPage], page_ref: str | None = None) -> list[str]:
    return [record["ref"] for record in refs(body, sitemap, page_ref)]


def candidates(*addresses: str) -> list[dict]:
    """Candidate refs in the record shape `resolve_internal_refs` settles."""
    return [
        {"ref": address, "extraction": "href", "mention": "a link"}
        for address in addresses
    ]


def chunk_texts(name: str, sitemap: dict[str, NavPage]) -> dict[str, str]:
    """Every chunk of a real page, keyed by chunk_ref."""
    from tmm_snapshot.chunker import chunk_body

    nav = resolve_nav(page_url(name), sitemap)
    record, body = parse_page(page_html(name), nav)
    return {
        chunk.chunk_ref: chunk for chunk in chunk_body(body, record, nav, sitemap)
    }


# -- §3 provisions from AustLII hrefs -------------------------------------


def test_an_austlii_href_is_a_near_certain_edge():
    """SOURCE_NOTES.md §3. The target='_blank' is noise; the db fragment is
    the instrument."""
    found = provisions(
        '<p>Pursuant to <a target="_blank" href="https://austlii.edu.au/cgi-bin/'
        'viewdb/au/legis/cth/consol_act/tma1995121/s41.html">section 41</a>, an '
        "application must be rejected.</p>"
    )

    assert found == [
        {"id": "TMA1995/s41", "extraction": "href", "mention": "section 41"}
    ]


@pytest.mark.parametrize(
    ("db", "instrument"),
    [
        ("tma1995121", "TMA1995"),
        ("tmr1995264", "TMR1995"),
        # The same Regulations under a second consolidation number, linked from
        # Part 5's Relevant Legislation page.
        ("tmr1995230", "TMR1995"),
        ("aia1901230", "AIA1901"),
    ],
)
def test_every_db_fragment_in_the_source_notes_maps(db, instrument):
    kind = "reg" if instrument.startswith("TMR") else "act"
    symbol = "r" if kind == "reg" else "s"
    found = provisions(
        f'<p><a href="https://austlii.edu.au/cgi-bin/viewdb/au/legis/cth/'
        f'consol_{kind}/{db}/{symbol}7.html">the provision</a></p>'
    )

    assert found[0]["id"] == f"{instrument}/{symbol}7"


def test_an_unreadable_db_fragment_raises_rather_than_dropping_the_edge():
    """A hyperlinked provision is the best evidence this pipeline gets. Losing
    one quietly because the Manual started citing something new is exactly the
    failure rule 3 exists to prevent."""
    with pytest.raises(UnknownInstrument, match="whatever"):
        provisions(
            '<p><a href="https://austlii.edu.au/cgi-bin/viewdb/au/legis/cth/'
            'consol_act/whatever/s7.html">a new instrument</a></p>'
        )


def test_an_unseen_but_well_formed_fragment_is_read_off_the_url():
    found = provisions(
        '<p><a href="https://austlii.edu.au/cgi-bin/viewdb/au/legis/cth/'
        'consol_act/da2003132/s5.html">section 5</a></p>'
    )

    assert found[0]["id"] == "DA2003/s5"


def test_the_links_own_words_carry_the_subsection():
    """A link to s41 whose text says 'sections 41(3) or 41(4)' is two
    provisions, both stated by the authors — flattening them to s41 discards
    what the sentence is actually about."""
    found = provisions(
        '<p><a href="https://austlii.edu.au/cgi-bin/viewdb/au/legis/cth/'
        'consol_act/tma1995121/s41.html">sections 41(3) or 41(4)</a></p>'
    )

    assert [record["id"] for record in found] == ["TMA1995/s41(3)", "TMA1995/s41(4)"]


def test_a_legislation_gov_au_link_is_left_to_the_regex_layer():
    """legislation.gov.au addresses instruments by an opaque series id
    (C2004A02362). There is no deterministic way to read an instrument off
    one, so it produces no href edge."""
    found = provisions(
        '<p>See the <a href="https://www.legislation.gov.au/C2004A02362/latest/'
        'text">Trade Marks Act 1995</a>.</p>'
    )

    assert found == []


@pytest.mark.parametrize(
    ("kind", "db", "node", "identifier"),
    [
        # Both hrefs as they appear on Part 5's Relevant Legislation page,
        # crawl of 28 July 2026. The reg node is 's'-prefixed and the fragment
        # is tmr1995230, neither of which the symbol may be taken from.
        ("act", "tma1995121", "s217a", "TMA1995/s217A"),
        ("reg", "tmr1995230", "s21.11a", "TMR1995/r21.11A"),
        # Part 3A of the Regulations: the suffix is on the first component.
        ("reg", "tmr1995264", "s3a.3", "TMR1995/r3A.3"),
    ],
)
def test_a_lower_case_node_name_yields_the_upper_case_suffix(
    kind, db, node, identifier
):
    """AustLII node names are lower case — `/s217a.html` is section 217A.
    Carrying that case into the id emitted a provision the schema rejects, and
    would have split one provision into two edges depending on whether the
    Manual hyperlinked it or merely mentioned it."""
    found = provisions(
        f'<p><a href="https://austlii.edu.au/cgi-bin/viewdb/au/legis/cth/'
        f'consol_{kind}/{db}/{node}.html">the provision</a></p>'
    )

    assert found[0]["id"] == identifier


def test_a_suffixed_section_still_takes_the_subsection_from_the_anchor():
    """The number in the anchor's words is compared with the number in the
    href. Compared in different cases, a link to s223a reading 'subsection
    223A(2)' matches nothing and the subsection is quietly lost."""
    found = provisions(
        '<p><a href="https://austlii.edu.au/cgi-bin/viewdb/au/legis/cth/'
        'consol_act/tma1995121/s223a.html">subsection 223A(2)</a></p>'
    )

    assert [record["id"] for record in found] == ["TMA1995/s223A(2)"]


def test_a_hyperlink_and_a_mention_of_one_suffixed_provision_are_one_edge():
    """The dedup key is the id, so normalising case is what lets the href
    outrank the prose mention rather than sitting beside it."""
    found = provisions(
        '<p>Under <a href="https://austlii.edu.au/cgi-bin/viewdb/au/legis/cth/'
        'consol_act/tma1995121/s217a.html">section 217A</a> the Registrar may '
        "act. Section 217A applies to the whole Register.</p>"
    )

    assert [record["id"] for record in found] == ["TMA1995/s217A"]
    assert found[0]["extraction"] == "href"


# -- §4 provisions from the prose -----------------------------------------


def test_an_adjacent_instrument_makes_the_edge_explicit():
    """SOURCE_NOTES.md §4, and the worked example in SCHEMA.md."""
    found = provisions(
        "<p>As such the application of section 41 is regulated by section 7 of "
        "the <i>Acts Interpretation Act 1901</i>.</p>"
    )

    assert by_id(found)["AIA1901/s7"] == {
        "id": "AIA1901/s7",
        "extraction": "regex",
        "certainty": "explicit",
        "mention": "section 7 of the Acts Interpretation Act 1901",
    }


def test_a_list_of_sections_is_several_edges_sharing_one_instrument():
    found = provisions(
        "<p>Registrability was governed by sections 24, 25 and 26 of the "
        "<i>Trade Marks Act 1955</i>.</p>"
    )

    assert [record["id"] for record in found] == [
        "TMA1955/s24",
        "TMA1955/s25",
        "TMA1955/s26",
    ]
    assert {record["certainty"] for record in found} == {"explicit"}


def test_a_bare_reference_with_one_instrument_in_scope_defaults():
    found = provisions(
        "<p>The trade mark was examined under section 41 of the "
        "<i>Trade Marks Act 1995</i>. Section 44 was not in issue.</p>"
    )

    assert by_id(found)["TMA1995/s44"]["certainty"] == "default"


def test_the_part_22_1_anaphora_case_is_ambiguous_and_says_so(sitemap):
    """SOURCE_NOTES.md §4, on the real page. 'section 26 of the Act' means the
    1955 Act, named in the previous sentence. No regex resolves this and rule 1
    forbids a model, so the doubt is recorded rather than resolved.

    The test that matters is the negative one: this must never appear as a
    confident Trade Marks Act 1995 edge.
    """
    chunk = chunk_texts("part22_1", sitemap)["TMM/Part22/1/1/1"]
    found = by_id(chunk.provisions)

    assert "section 26 of the Act" in chunk.text
    assert found["TMA1995/s26"]["certainty"] == "ambiguous"
    assert found["TMA1995/s26"]["extraction"] == "regex"

    # The 1955 reading, which the sentence before it states outright.
    assert found["TMA1955/s26"]["certainty"] == "explicit"


def test_the_same_section_four_times_is_one_edge(sitemap):
    """SCHEMA.md §Citations. 'section 41' appears four times in Part 22.1
    heading 1.2; it is one edge, and the hyperlink is the evidence for it."""
    chunk = chunk_texts("part22_1", sitemap)["TMM/Part22/1/1/2"]
    matching = [
        record for record in chunk.provisions if record["id"] == "TMA1995/s41"
    ]

    assert chunk.text.lower().count("section 41") >= 3
    assert len(matching) == 1
    assert matching[0]["extraction"] == "href"


def test_an_instrument_belonging_to_the_next_reference_is_not_borrowed():
    """The lookahead stops at the following reference. Without that, the
    Acts Interpretation Act sits within 60 characters of the section 41 before
    it and both edges come out attributed to it."""
    found = by_id(
        provisions(
            "<p>The application of section 41 is regulated by section 7 of the "
            "<i>Acts Interpretation Act 1901</i>.</p>"
        )
    )

    assert "AIA1901/s41" not in found
    assert "AIA1901/s7" in found


def test_an_instrument_title_is_not_read_as_a_provision_number():
    """'Trade Mark Regulations 1995' contains the keyword 'Regulations'
    followed by a number. That number is a year."""
    found = provisions(
        "<p>Trade Marks Act 1995 Trade Mark Regulations 1995 Wine Australia "
        "Act 2013</p>"
    )

    assert [record["id"] for record in found] == []


def test_regulations_default_to_the_trade_marks_regulations():
    found = provisions("<p>The requirements of regulation 4.15 were met.</p>")

    assert found[0]["id"] == "TMR1995/r4.15"
    assert found[0]["certainty"] == "default"


@pytest.mark.parametrize(
    ("prose", "identifier"),
    [
        ("regulation 21.11A", "TMR1995/r21.11A"),
        ("regulation 3A.3", "TMR1995/r3A.3"),
        ("section 217A", "TMA1995/s217A"),
        # Lower case in the prose is the Manual's, not ours; it addresses the
        # same provision either way.
        ("section 217a", "TMA1995/s217A"),
    ],
)
def test_a_letter_suffix_in_the_prose_survives_the_address(prose, identifier):
    """An inserted regulation carries the suffix on its last component. Read
    without it, 'regulation 21.11A' becomes an edge to regulation 21.11 — a
    different provision, recorded with no sign that anything was dropped."""
    found = provisions(f"<p>The requirements of {prose} were met.</p>")

    assert [record["id"] for record in found] == [identifier]


def test_a_paragraph_letter_keeps_its_own_case():
    """Only the number is normalised. s44(3)(a) and s44(3)(A) are different
    addresses, so upper-casing the whole thing would invent a provision."""
    found = provisions(
        "<p>Rejection under paragraph 44(3)(a) of the "
        "<i>Trade Marks Act 1995</i>.</p>"
    )

    assert [record["id"] for record in found] == ["TMA1995/s44(3)(a)"]


def test_provisions_come_back_sorted_by_id():
    """Rule 2: arrays sorted by a stable key, or every crawl rewrites the
    file."""
    found = provisions(
        "<p>See section 44, section 41 and section 6 of the "
        "<i>Trade Marks Act 1995</i>.</p>"
    )

    assert [record["id"] for record in found] == sorted(
        record["id"] for record in found
    )


# -- §9 cases -------------------------------------------------------------


def test_a_neutral_citation():
    """SOURCE_NOTES.md §9."""
    assert extract_cases("Vokes Ltd v Laminar Air Flow Pty Ltd [2018] FCAFC 109") == [
        {"id": "CASE/2018/FCAFC/109", "citation": "[2018] FCAFC 109"}
    ]


def test_a_reported_citation():
    """SOURCE_NOTES.md §9."""
    assert extract_cases("Wheatcroft Bros Ltd's Trade Marks (1954) 71 RPC 43") == [
        {"id": "CASE/1954/RPC/71/43", "citation": "(1954) 71 RPC 43"}
    ]


@pytest.mark.parametrize("court", ["HCA", "FCAFC", "FCA", "ATMO", "APO"])
def test_every_court_named_in_the_source_notes(court):
    assert extract_cases(f"Something v Another [2021] {court} 7")[0]["id"] == (
        f"CASE/2021/{court}/7"
    )


@pytest.mark.parametrize("series", ["RPC", "CLR", "FCR", "ALR", "IPR", "ATR"])
def test_every_reported_series_named_in_the_source_notes(series):
    assert extract_cases(f"Something v Another (1998) 42 {series} 118")[0]["id"] == (
        f"CASE/1998/{series}/42/118"
    )


def test_both_styles_appear_on_the_real_plants_page(sitemap):
    chunks = chunk_texts("part32a_2_3", sitemap)
    found = {case["id"] for chunk in chunks.values() for case in chunk.cases}

    assert "CASE/1954/RPC/71/43" in found
    assert "CASE/2007/ATMO/4" in found


def test_one_decision_cited_twice_is_one_case():
    text = "See [2018] FCAFC 109. As held in [2018] FCAFC 109, the mark fails."

    assert len(extract_cases(text)) == 1


# -- §8 internal cross references -----------------------------------------


def test_a_hyperlinked_cross_reference_resolves_through_the_sitemap(sitemap):
    """SOURCE_NOTES.md §8, and the worked example in SCHEMA.md."""
    body = fragment(
        '<p>The repealed section is set out in <a href="/trademark/'
        'annex-a1-section-41-prior-to-raising-the-bar">Annex A1</a>.</p>'
    )

    assert targets(body, sitemap) == [
        "TMM/Part22/x-annex-a1-section-41-prior-to-raising-the-bar"
    ]


def test_a_cross_reference_written_with_the_other_scheme_still_resolves(sitemap):
    """The Manual links to itself as http:// as well as relatively."""
    body = fragment(
        '<p><a href="http://manuals.ipaustralia.gov.au/trademark/'
        'annex-a1-section-41-prior-to-raising-the-bar">Annex A1</a></p>'
    )

    assert targets(body, sitemap) == [
        "TMM/Part22/x-annex-a1-section-41-prior-to-raising-the-bar"
    ]


def test_a_bare_dotted_reference_resolves_to_the_page_it_falls_inside(sitemap):
    """SOURCE_NOTES.md §8, on the real Part 32B page: 'see part 22.15.7'.
    22.15.7 is a heading, not a page — no page has that address — so it
    resolves to page 22.15, which is the deepest address the inventory
    actually holds."""
    body = fragment("<p>As with such trade marks (see part 22.15.7) examiners…</p>")

    assert targets(body, sitemap) == ["TMM/Part22/15"]


def test_an_unresolvable_reference_is_dropped_not_stored(sitemap):
    """A string a consumer will try to follow and cannot is worse than an
    absent one."""
    body = fragment(
        '<p>See part 99.4, and <a href="/trademark/a-page-that-does-not-exist">'
        "this</a>.</p>"
    )

    assert targets(body, sitemap) == []


def test_a_part_without_a_dotted_address_is_not_a_page_reference(sitemap):
    """'Part 22 of this Manual' names a Part. TMM/Part22 is not a page."""
    body = fragment("<p>As discussed in Part 22 of this Manual…</p>")

    assert targets(body, sitemap) == []


def test_a_reference_to_the_page_it_sits_on_is_kept(sitemap):
    """A self-reference is a datapoint, not noise — do not filter it.

    22 chunks in the corpus carry one, and they are the Manual pointing at
    another part of the same page: *'in light of paragraph 4.3'*, the A-Z index
    at the top of the INN-stems annex. That the target is a sibling chunk
    rather than another page is exactly what a retrieval layer needs to know,
    and it is only knowable because the ref was kept.

    Filtering these out on the grounds that a page linking to itself 'says
    nothing' would throw the fact away, and nothing downstream could recover
    it — the anchor is gone by the time the text is flattened.
    """
    body = fragment(
        '<p>See <a href="/trademark/annex-a1-section-41-prior-to-raising-the-bar">'
        "the discussion above</a>.</p>"
    )
    on_that_very_page = "TMM/Part22/x-annex-a1-section-41-prior-to-raising-the-bar"

    assert targets(body, sitemap) == [on_that_very_page]


def test_an_external_link_is_never_an_internal_reference(sitemap):
    body = fragment(
        '<p><a href="https://en.wikipedia.org/wiki/Trade_mark">Wikipedia</a> and '
        '<a href="https://austlii.edu.au/cgi-bin/viewdb/au/legis/cth/consol_act/'
        'tma1995121/s41.html">section 41</a></p>'
    )

    assert targets(body, sitemap) == []


# -- an instrument that cannot hold the provision it is next to -----------


def test_a_section_is_never_attributed_to_the_regulations():
    """The Relevant Legislation pages are three-column tables, and a chunk
    renders one as a run of cell text. The lookahead then reaches the
    instrument column of the same row, which named the Regulations while the
    reference column named a section. 20 edges came out `TMR1995/s224` — a
    section of the Regulations, which does not exist — and every one of them
    was recorded `explicit`."""
    found = by_id(
        provisions(
            "<p>Section 224 Extension of time Trade Marks Regulations 1995</p>"
        )
    )

    assert "TMR1995/s224" not in found
    assert found["TMA1995/s224"]["certainty"] != "explicit"


def test_a_regulation_is_never_attributed_to_the_act():
    """The same rule the other way round, which the corpus has not shown but
    the markup allows."""
    found = by_id(
        provisions("<p>Regulation 21.6 Costs Trade Marks Act 1995</p>")
    )

    assert "TMA1995/r21.6" not in found
    assert "TMR1995/r21.6" in found


def test_an_instrument_of_the_right_kind_still_qualifies_across_the_bleed():
    """Discarding the wrong-kind title must not discard a right-kind one
    sitting behind it in the same window."""
    found = by_id(
        provisions(
            "<p>Section 224, Trade Mark Regulations 1995, Trade Marks "
            "Act 1995.</p>"
        )
    )

    assert found["TMA1995/s224"]["certainty"] == "explicit"


# -- what 'ambiguous' is actually for -------------------------------------


def test_the_act_and_the_regulations_together_do_not_make_a_section_ambiguous():
    """Nearly every page of the Manual names both, because the Relevant
    Legislation preamble lists them together. Counting them as competing
    instruments made 757 of 1939 regex edges ambiguous — a bucket SCHEMA.md
    says never to hydrate from — for references whose own word already says
    which kind of instrument they address."""
    found = by_id(
        provisions(
            "<p>Trade Marks Act 1995 Trade Marks Regulations 1995. An "
            "application must be rejected under section 41.</p>"
        )
    )

    assert found["TMA1995/s41"]["certainty"] == "default"


def test_a_bare_regulation_is_not_made_ambiguous_by_an_act():
    found = by_id(
        provisions(
            "<p>The Trade Marks Act 1995 applies, and reg 21.6 sets the "
            "costs.</p>"
        )
    )

    assert found["TMR1995/r21.6"]["certainty"] == "default"


def test_two_acts_in_scope_still_make_a_bare_section_ambiguous():
    """The case the flag exists for, and the one SOURCE_NOTES.md §4 forbids
    resolving: which Act 'section 26' means is genuinely undecidable here."""
    found = by_id(
        provisions(
            "<p>Registrability was governed by the Trade Marks Act 1955. "
            "Marks were considered under section 26 of the Act. The Trade "
            "Marks Act 1995 replaced it.</p>"
        )
    )

    assert found["TMA1995/s26"]["certainty"] == "ambiguous"


# -- a cross reference that names a heading -------------------------------


def test_the_anchor_address_pattern_agrees_with_the_chunkers():
    """`_ANCHOR_HEADING_ADDRESS` reads the number out of a link's fragment and
    `chunker._LEADING_ADDRESS` reads it out of the heading itself. They have to
    agree or a link lands on a chunk_ref the chunker never built, and the
    modules cannot import each other. So the agreement is pinned here."""
    from tmm_snapshot.chunker import _LEADING_ADDRESS

    for address in ("4", "4.5", "22.15.7", "3A", "9.20"):
        heading = _LEADING_ADDRESS.match(f"{address} Some heading text")
        anchor = _ANCHOR_HEADING_ADDRESS.match(f"{address}-some-heading-text")
        assert heading is not None and anchor is not None
        assert heading.group("address") == anchor.group("address") == address


def test_a_link_to_a_heading_addresses_the_chunk_not_the_page(sitemap):
    """137 of the Manual's internal links carry a fragment naming a
    sub-section. All 399 internal_refs resolved to bare pages before this."""
    body = fragment(
        '<p>See <a href="/trademark/4.-classification-procedures-in-'
        'examination#4.5-goods-or-services-to-be-grouped-together-by-class-'
        'number">4.5</a>.</p>'
    )
    assert targets(body, sitemap) == ["TMM/Part14/4/4/5"]


def test_a_fragment_naming_no_number_stays_a_page_reference(sitemap):
    """The Part 5 glossary and the Part 14 A13 index anchor on single letters.
    A letter addresses no heading number, and 90 of the 137 are these."""
    body = fragment(
        '<p>See <a href="/trademark/4.-classification-procedures-in-'
        'examination#a">A</a>.</p>'
    )

    assert targets(body, sitemap) == ["TMM/Part14/4"]


def test_a_candidate_resolves_to_the_chunk_when_the_chunk_exists():
    assert resolve_internal_refs(
        candidates("TMM/Part14/4/4/5"),
        frozenset({"TMM/Part14/4/4/5"}),
        frozenset({"TMM/Part14/4"}),
    ) == candidates("TMM/Part14/4/4/5")


def test_a_candidate_resolves_to_the_opening_fragment_of_a_split_section():
    """A section long enough to split holds its address across `~1`..`~n` and
    no single chunk owns the bare form. The link is aimed at where the section
    starts, which is `~1` by construction. 27 of the 47 addressed anchors."""
    assert resolve_internal_refs(
        candidates("TMM/Part14/4/4/8"),
        frozenset({"TMM/Part14/4/4/8~1", "TMM/Part14/4/4/8~2"}),
        frozenset({"TMM/Part14/4"}),
    ) == candidates("TMM/Part14/4/4/8~1")


def test_a_candidate_whose_heading_has_gone_falls_back_to_its_page():
    """Coarsened, not dropped: the page half was established by URL and is
    still true. The Manual moving a heading should weaken a citation, not
    delete one."""
    assert resolve_internal_refs(
        candidates("TMM/Part27/3/2/2"), frozenset(), frozenset({"TMM/Part27/3"})
    ) == candidates("TMM/Part27/3")


def test_a_candidate_naming_nothing_at_all_is_dropped():
    assert resolve_internal_refs(
        candidates("TMM/Part99/1/2/3"), frozenset(), frozenset({"TMM/Part27/3"})
    ) == []


# -- §8 the two things 'part N.M' can mean --------------------------------


def test_a_hyperlinked_reference_records_that_it_was_hyperlinked(sitemap):
    """The distinction `provisions` has always drawn, applied to the field it
    was missing from. Until 0.8.0 an authored link and a regex hit on the
    prose were both a bare string, and 34 of the corpus's 417 edges were the
    second kind with nothing saying so."""
    body = fragment(
        '<p>See <a href="/trademark/annex-a1-section-41-prior-to-raising-'
        'the-bar">Annex A1</a>.</p>'
    )

    assert refs(body, sitemap) == [
        {
            "ref": "TMM/Part22/x-annex-a1-section-41-prior-to-raising-the-bar",
            "extraction": "href",
            "mention": "Annex A1",
        }
    ]


def test_a_bare_reference_records_that_it_was_read_from_the_prose(sitemap):
    body = fragment("<p>As with such trade marks (see part 22.15.7) examiners…</p>")

    assert refs(body, sitemap) == [
        {
            "ref": "TMM/Part22/15",
            "extraction": "regex",
            "certainty": "default",
            "mention": "part 22.15.7",
        }
    ]


def test_of_this_chapter_means_this_chapter(sitemap):
    """The finding that made this field carry a certainty at all.

    Part 32A — *Examination of Trade Marks for Plants* — writes 'see part
    2.3.1(c) of this chapter'. `part 2.3.1` read by the convention of §8 is
    Part 2, *Filing Requirements*, and that is what the snapshot stored: a
    confident edge from a passage about plant varietal names to a page about
    how to file a document, in the Part where SOURCE_NOTES.md §2 says
    misattribution is the worst failure available.

    The Manual disambiguates it in four words sitting in the same string, so
    reading them is reading the source rather than guessing at it.
    """
    body = fragment(
        "<p>…rather than an identifier of trade source. (For more information, "
        "see part 2.3.1(c) of this chapter) A PBR result…</p>"
    )

    assert refs(body, sitemap, "TMM/Part32A/2/1") == [
        {
            "ref": "TMM/Part32A/2/3",
            "extraction": "regex",
            "certainty": "explicit",
            "mention": "part 2.3.1",
        }
    ]


def test_the_qualifier_is_found_past_a_second_number(sitemap):
    """'parts 2.3.1 and 2.3.2 of this chapter' — only the first is a match,
    and the qualifier sits behind the second. A full-stop brake would cut
    inside '2.3.2' and hide it, which is why the brake is a sentence end."""
    body = fragment(
        "<p>Words which have a specific meaning to plants should be taken into "
        "consideration (see parts 2.3.1 and 2.3.2 of this chapter).</p>"
    )

    assert [r["ref"] for r in refs(body, sitemap, "TMM/Part32A/2/5")] == [
        "TMM/Part32A/2/3"
    ]


def test_of_this_manual_is_not_of_this_chapter(sitemap):
    """'the Manual' is the whole Manual, so 'Part 22.15.7 of this manual' is
    Part 22 — the reading the rule above must not invert."""
    body = fragment("<p>See part 22.15.7 of this manual for the practice.</p>")

    assert [r["ref"] for r in refs(body, sitemap, "TMM/Part32A/2/1")] == [
        "TMM/Part22/15"
    ]


def test_two_readings_and_nothing_choosing_is_ambiguous(sitemap):
    """Both readings name a page and the Manual does not say which. The
    conventional target is kept, because the record has nowhere else to put
    one, and the flag beside it is what stops it being read as a fact — the
    arrangement `extract_provisions` already uses for a bare 'section 26'."""
    body = fragment("<p>The requirements set out at part 2.3 apply.</p>")
    found = refs(body, sitemap, "TMM/Part1/2")

    assert found == [
        {
            "ref": "TMM/Part2/3",
            "extraction": "regex",
            "certainty": "ambiguous",
            "mention": "part 2.3",
        }
    ]

    # Read from a page in Part 2 there is no second reading to compete, and
    # the same sentence is a plain 'default'.
    assert refs(body, sitemap, "TMM/Part2/1")[0]["certainty"] == "default"


def test_a_link_and_a_mention_of_one_page_are_one_edge(sitemap):
    """One target, one record, and the hyperlink is the stronger evidence for
    it — the same collapse `extract_provisions` makes."""
    body = fragment(
        '<p>See <a href="/trademark/2.-what-is-a-trade-mark">Part 22.15</a>, '
        "and see part 22.15.7.</p>"
    )
    found = [r for r in refs(body, sitemap) if r["ref"] == "TMM/Part22/15"]

    assert len(found) == 1
    assert found[0]["extraction"] == "regex"


def test_settling_is_idempotent():
    """A settled ref is a valid candidate for the next run, which is what lets
    a page skipped at gate 2 be re-settled from its stored record without
    being cut again. ARCHITECTURE.md §Settling."""
    once = resolve_internal_refs(
        candidates("TMM/Part14/4/4/5"),
        frozenset({"TMM/Part14/4/4/5"}),
        frozenset({"TMM/Part14/4"}),
    )
    twice = resolve_internal_refs(
        once, frozenset({"TMM/Part14/4/4/5"}), frozenset({"TMM/Part14/4"})
    )

    assert once == twice == candidates("TMM/Part14/4/4/5")


# --------------------------------------------------------------------------
# The 0.8.0 review: the node prefix, and the numbering invariant
# --------------------------------------------------------------------------


def test_a_schedule_href_addresses_the_schedule_not_a_regulation():
    """`/consol_reg/tmr1995230/sch2.html` is Schedule 2 of the Regulations.

    Stripping the node's alpha prefix read it as `2` and produced
    `TMR1995/r2` — a regulation, on `extraction: "href"`, which is the
    strongest evidence the schema can carry. Eight edges in the 0.8.0 corpus.
    The segment emitted now is the one the legislation snapshot uses for the
    same Schedule, so the id is a foreign key onto it.
    """
    found = provisions(
        '<p><a href="http://www.austlii.edu.au/cgi-bin/viewdb/au/legis/cth/'
        'consol_reg/tmr1995230/sch2.html">Schedule 2</a></p>'
    )

    assert [record["id"] for record in found] == ["TMR1995/sch2"]
    assert found[0]["extraction"] == "href"


def test_an_unreadable_node_prefix_raises_rather_than_guessing_the_kind():
    with pytest.raises(UnknownInstrument, match="node prefix"):
        provisions(
            '<p><a href="https://austlii.edu.au/cgi-bin/viewdb/au/legis/cth/'
            'consol_act/tma1995121/pt3.html">a Part</a></p>'
        )


@pytest.mark.parametrize(
    ("identifier", "held"),
    [
        ("TMA1995/s41", True),
        ("TMA1995/s223A(2)(b)", True),
        # The Act numbers none of its 315 sections with a dot.
        ("TMA1995/s4.7", False),
        ("TMA1995/s21.28(1)(a)", False),
        # The Regulations number all 401 of theirs with one.
        ("TMR1995/r4.15", True),
        ("TMR1995/r2016", False),
        ("TMR1995/r17A", False),
        # The kind check that came before it still holds.
        ("TMR1995/s224", False),
        # A Schedule is neither, and neither rule applies to it.
        ("TMR1995/sch2", True),
        # An instrument whose numbering nobody has read cannot contradict
        # anything: the Criminal Code really does number sections 6.1 and
        # 137.1, and a whitelist that guessed would drop real edges.
        ("AIA1901/s7", True),
        ("CCA1995/s137.1", True),
    ],
)
def test_instrument_holds_reads_the_number_as_well_as_the_word(identifier, held):
    assert instrument_holds(identifier) is held


def test_a_dotted_address_is_not_attributed_to_the_act():
    """'see paragraph 4.3' is the Manual's own paragraph 4.3 far more often
    than it is anything statutory, and the Act cannot hold a dotted section
    number at all. Dropped rather than re-attributed to the Regulations: the
    Manual's Part-internal numbering and the Regulations' numbering are the
    same shape, so `TMR1995/r4.3` existing is a coincidence, not evidence.
    """
    assert provisions("<p>These are stated in paragraph 4.3.</p>") == []


def test_an_undotted_regulation_address_is_dropped():
    assert provisions("<p>See Regulation 17A for the procedure.</p>") == []


def test_a_named_instrument_ending_in_a_singular_regulation_is_a_title():
    """'Defence Regulation 2016' is an instrument, not regulation 2016.

    Commonwealth drafting went singular around 2015, and without it the year
    was read as a provision number: `TMR1995/r2016` at certainty `default`.
    """
    assert provisions(
        "<p>A term prohibited by the Defence Regulation 2016 (Cth).</p>"
    ) == []


def test_a_kind_neutral_word_takes_the_symbol_from_the_instrument_named():
    """An Act and a set of Regulations both have paragraphs, so 'paragraph'
    states no kind. Left forcing a section, a paragraph the Manual explicitly
    attributed to the Regulations could not be attributed to them at all."""
    found = by_id(
        provisions(
            "<p>Under paragraph 4.12(1)(b) of the Trade Marks Regulations "
            "1995, an extension applies.</p>"
        )
    )

    assert "TMR1995/r4.12(1)(b)" in found
    assert found["TMR1995/r4.12(1)(b)"]["certainty"] == "explicit"


def test_a_bare_kind_neutral_word_still_reads_as_a_section():
    """The great majority of bare 'paragraph N(a)' references in this corpus
    are the Act, and nothing in the sentence says otherwise."""
    assert "TMA1995/s44(3)(a)" in by_id(
        provisions("<p>Rejected under paragraph 44(3)(a).</p>")
    )


# -- §35 provisions from TimeBase hrefs -----------------------------------


def test_a_timebase_href_is_an_href_edge():
    """SOURCE_NOTES.md §35. The Manual links its provisions two ways, and both
    are the authors stating what the passage is about. The address is in the
    query string rather than the path; nothing else differs."""
    found = provisions(
        '<p>See <a href="http://www.timebase.com.au/IPAust/index.cfm?id='
        'tmact:217a">Section 217A</a> for the fee.</p>'
    )

    assert found == [
        {"id": "TMA1995/s217A", "extraction": "href", "mention": "Section 217A"}
    ]


def test_a_timebase_regulation_takes_its_symbol_from_the_instrument():
    found = provisions(
        '<p><a href="http://www.timebase.com.au/IPAust/index.cfm?id='
        'tmreg:21.11a">Regulation 21.11A</a></p>'
    )

    assert [record["id"] for record in found] == ["TMR1995/r21.11A"]


def test_a_timebase_schedule_addresses_the_schedule():
    """The same segment the AustLII `sch` prefix produces, and the same ref the
    legislation snapshot holds — so either route is a foreign key onto it."""
    found = provisions(
        '<p><a href="http://www.timebase.com.au/IPAust/index.cfm?id='
        'tmreg:sch9">Schedule 9</a></p>'
    )

    assert [record["id"] for record in found] == ["TMR1995/sch9"]


def test_a_timebase_anchor_s_words_carry_the_subsection():
    """`_addressed` is shared with the AustLII path, so the anchor-words rule
    applies identically: the link carries the provision and its own words carry
    the detail the sentence is about."""
    found = provisions(
        '<p><a href="http://www.timebase.com.au/IPAust/index.cfm?id='
        'tmact:44">subsections 44(1) and 44(2)</a></p>'
    )

    assert [record["id"] for record in found] == ["TMA1995/s44(1)", "TMA1995/s44(2)"]


def test_an_unknown_timebase_fragment_raises():
    """The precedent `UnknownInstrument` sets for AustLII, and stricter for a
    reason: a TimeBase fragment carries no year, so there is nothing in it to
    derive an instrument from the way `_DB_FRAGMENT` can."""
    with pytest.raises(UnknownInstrument):
        provisions(
            '<p><a href="http://www.timebase.com.au/IPAust/index.cfm?id='
            'patact:15">section 15</a></p>'
        )


def test_a_timebase_link_beats_the_guess_from_the_prose(sitemap):
    """Part 61.2 is the case SOURCE_NOTES.md §29 opened and §35 closes.

    Three references to section 217A on the page, two of them hyperlinked to
    TimeBase rather than AustLII. Every one of them used to be recorded as a
    guess from the prose while the authors' own statement sat in an href
    nobody was reading.
    """
    chunks = chunk_texts("part61_2", sitemap)

    edges = [
        edge
        for chunk in chunks.values()
        for edge in chunk.provisions
        if edge["id"] == "TMA1995/s217A"
    ]

    assert edges, "Part 61.2 cites section 217A"
    assert any(edge["extraction"] == "href" for edge in edges), (
        "the TimeBase anchors on this page state section 217A outright"
    )


def test_a_federal_register_link_is_not_a_provision_edge():
    """T12's second decision, declined. `C2004A04969` names the Trade Marks Act
    and nothing narrower, so there is no provision in it to extract — and the
    475 anchors in the corpus resolve to 9 distinct URLs, two of which sit
    together as boilerplate naming the Act and the Regulations at once."""
    found = provisions(
        '<p>See the <a href="https://www.legislation.gov.au/C2004A04969/latest/'
        'text">Trade Marks Act 1995 (Cth)</a>.</p>'
    )

    assert found == []
