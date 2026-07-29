"""The reference layer, and the contract between the two corpora.

The tests that matter here are not about regexes — `tests/test_citations.py`
owns those. They are about the two snapshots continuing to speak the same
language: an id emitted by the Manual's citation layer has to be an address
this corpus actually holds, and nothing else in either pipeline would notice if
that stopped being true.
"""

from __future__ import annotations

import pytest
from legislation_fixtures import fixture_docx

from frl_snapshot import config
from frl_snapshot.docx import read_document
from frl_snapshot.references import extract_provisions
from frl_snapshot.structure import parse_document
from frl_snapshot.units import split_units
from tmm_snapshot import citations


@pytest.mark.parametrize("code", sorted(config.INSTRUMENTS))
def test_the_instrument_symbol_agrees_with_the_manual(code):
    """An Act holds sections and Regulations hold regulations.

    Two independent readings of one fact — `config.Instrument.symbol` here and
    `citations.instrument_kind` there. Where they disagree, one corpus is
    addressing provisions the other does not have.
    """
    instrument = config.INSTRUMENTS[code]
    assert citations.instrument_kind(code) == instrument.symbol


def test_a_manual_style_edge_resolves_to_a_provision_ref():
    document = parse_document(
        read_document(fixture_docx("tma1995-slice")), config.INSTRUMENTS["TMA1995"]
    )
    refs = {provision.ref for provision in document.provisions}
    for provision in document.provisions:
        refs.update(unit.ref for unit in split_units(provision))

    edges = citations.extract_provisions(
        __import__("bs4").BeautifulSoup("", "html.parser"),
        "See section 41 of the Trade Marks Act 1995 and subsection 41(3).",
    )
    identifiers = {edge["id"] for edge in edges}
    assert "TMA1995/s41" in identifiers
    assert "TMA1995/s41" in refs
    assert "TMA1995/s41(3)" in refs


def test_every_edge_from_this_corpus_is_a_regex_edge():
    """A compiled instrument carries no hyperlinks — 0 `w:hyperlink` elements
    in either document — so there is no href evidence to be had. That is the
    truth about the source, and it reaches the snapshot as such."""
    edges = extract_provisions("An application under section 41 must be rejected.")
    assert edges
    assert {edge["extraction"] for edge in edges} == {"regex"}


def test_a_bare_section_reference_defaults_to_the_act():
    edges = extract_provisions("The Registrar must act under section 41.")
    edge = next(edge for edge in edges if edge["id"] == "TMA1995/s41")
    assert edge["certainty"] == "default"


def test_a_bare_regulation_reference_defaults_to_the_regulations():
    edges = extract_provisions("See regulation 4.15 for the approved form.")
    edge = next(edge for edge in edges if edge["id"] == "TMR1995/r4.15")
    assert edge["certainty"] == "default"


def test_the_anaphoric_the_act_is_still_not_resolved():
    """Inside the Regulations 'the Act' means the Trade Marks Act 1995, and
    inside the Act it means itself. Both are resolvable by a human in one step
    and neither is resolved here: teaching `citations` a rule that depends on
    which document is being read would change what a Manual edge means."""
    edges = extract_provisions("A person may apply under section 26 of the Act.")
    edge = next(edge for edge in edges if edge["id"].endswith("/s26"))
    assert edge["certainty"] in {"default", "ambiguous"}
    assert edge["extraction"] == "regex"


def test_references_found_in_the_real_text_address_real_provisions():
    """The instrument's internal cross-reference graph, for free: because the
    ids are this corpus's own refs, a provision edge is an internal edge."""
    document = parse_document(
        read_document(fixture_docx("tmr1995-slice")), config.INSTRUMENTS["TMR1995"]
    )
    found: set[str] = set()
    for provision in document.provisions:
        for unit in split_units(provision):
            for edge in extract_provisions(unit.text):
                found.add(edge["id"])
    assert any(identifier.startswith("TMR1995/r") for identifier in found)
    assert any(identifier.startswith("TMA1995/s") for identifier in found)
