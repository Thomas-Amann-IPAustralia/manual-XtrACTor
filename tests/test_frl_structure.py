"""Containers and provisions, over real slices of both instruments.

Every case here was found in the live documents, not invented: the fixtures are
verbatim `word/document.xml` extracts, so a test that passes is a statement
about the Trade Marks Act and Regulations as the Register actually compiles
them.
"""

from __future__ import annotations

import pytest
from legislation_fixtures import fixture_docx, synthetic

from frl_snapshot import config
from frl_snapshot.docx import read_document
from frl_snapshot.structure import StructureError, parse_document


@pytest.fixture(scope="module")
def act():
    return parse_document(
        read_document(fixture_docx("tma1995-slice")), config.INSTRUMENTS["TMA1995"]
    )


@pytest.fixture(scope="module")
def regulations():
    return parse_document(
        read_document(fixture_docx("tmr1995-slice")), config.INSTRUMENTS["TMR1995"]
    )


def test_section_ref_is_what_the_manual_cites(act):
    """The join between the corpora, asserted rather than assumed.

    `tmm_snapshot.citations` emits 'TMA1995/s41' for a Manual chunk citing
    section 41. If this ever stops being the ref, the two snapshots stop
    joining and nothing else in either of them would notice.
    """
    refs = {provision.ref for provision in act.provisions}
    assert "TMA1995/s41" in refs

    from frl_snapshot.references import extract_provisions

    edges = extract_provisions("An application under section 41 of the Trade Marks Act 1995.")
    assert any(edge["id"] == "TMA1995/s41" for edge in edges)


def test_section_ref_does_not_carry_its_part(act):
    """A section number is unique instrument-wide; the Part is not in the address."""
    section = next(p for p in act.provisions if p.ref == "TMA1995/s41")
    assert section.containers[0].ref == "TMA1995/pt4"
    assert "pt4" not in section.ref
    assert section.group == "pt4"


def test_regulation_number_keeps_its_letter_suffix(regulations):
    refs = {provision.ref for provision in regulations.provisions}
    assert "TMR1995/r17A.61" in refs
    assert "TMR1995/r20A.22" in refs


def test_acthead5_inside_a_schedule_is_a_clause(regulations):
    """Schedule 9 opens '1  Table of fees'.

    Read as a regulation that is `TMR1995/r1`, which collides with nothing
    today and would collide with the clause 1 of every other Schedule the
    moment a second one was included.
    """
    clause = next(p for p in regulations.provisions if p.kind == "clause")
    assert clause.ref == "TMR1995/sch9/c1"
    assert clause.number == "1"


def test_schedule_item_is_namespaced_by_its_schedule(regulations):
    item = next(p for p in regulations.provisions if p.kind == "item")
    assert item.ref == "TMR1995/sch3/item1"


def test_schedule_with_no_provision_heading_still_has_an_address(regulations):
    """Schedule 2 is a bare list of prohibited signs.

    No Part, no ActHead5, no ItemHead — and eight paragraphs of operative law.
    Before `kind: container` existed this fell into a bucket called front
    matter and was indistinguishable from the compiler's preamble.
    """
    schedule = next(
        p for p in regulations.provisions if p.ref == "TMR1995/sch2"
    )
    assert schedule.kind == "container"
    assert schedule.blocks
    assert any("Austrade" in block.normalised() for block in schedule.blocks)


def test_front_matter_is_addressable(act):
    front = next(p for p in act.provisions if p.kind == "front-matter")
    assert front.ref == "TMA1995/front"
    assert front.number is None
    assert any("READER" in block.normalised().upper() for block in front.blocks)


def test_table_of_contents_is_dropped(act):
    """315 TOC5 paragraphs mirror 315 ActHead5 headings in the full Act."""
    assert act.dropped_toc >= 1
    for provision in act.provisions:
        for block in provision.blocks:
            assert not (block.style or "").startswith("TOC")


def test_instrument_titles(act, regulations):
    assert act.titles["short_title"] == "Trade Marks Act 1995"
    assert act.titles["long_title"] == "An Act relating to trade marks"
    assert regulations.titles["made_under"] == "Trade Marks Act 1995"


def test_endnotes_are_not_law(act):
    """An endnote table names provisions and must never become one."""
    assert act.endnote_blocks
    for provision in act.provisions:
        assert not (provision.title or "").startswith("Endnote")


def test_every_block_lands_somewhere(regulations):
    """The accounting rule: no text falls out of the corpus silently."""
    landed = sum(len(provision.blocks) for provision in regulations.provisions)
    assert landed > 0
    total_words = sum(
        len(block.normalised())
        for provision in regulations.provisions
        for block in provision.blocks
    )
    assert total_words > 1000


def test_unparseable_container_heading_raises():
    """Guessing whether 'Chapter' is a Part would misplace everything under it."""
    document = synthetic(
        ("ActHead2", "Part the first, being about things"),
        ("ActHead5", "1\tShort title"),
    )
    with pytest.raises(StructureError, match="ActHead2"):
        parse_document(read_document(document), config.INSTRUMENTS["TMA1995"])


def test_provision_heading_without_the_two_space_separator_raises():
    """717 of 717 real provision headings use two spaces. A single one is a
    signal that the stylesheet moved, not a case to accommodate."""
    document = synthetic(("ActHead5", "41 Trade mark not distinguishing"))
    with pytest.raises(StructureError, match="two spaces"):
        parse_document(read_document(document), config.INSTRUMENTS["TMA1995"])


def test_document_with_no_provisions_raises():
    document = synthetic((None, "Just some words."))
    with pytest.raises(StructureError, match="ActHead5"):
        parse_document(read_document(document), config.INSTRUMENTS["TMA1995"])


def test_schedule_item_outside_a_schedule_raises():
    document = synthetic(("ItemHead", "1\tAfter section 131"))
    with pytest.raises(StructureError, match="outside any Schedule"):
        parse_document(read_document(document), config.INSTRUMENTS["TMR1995"])


def test_parts_inside_a_schedule_are_namespaced():
    """The Regulations set 'Part 1' three times: in the body, in Schedule 1 and
    in Schedule 8. Without the Schedule in the ref they are one address."""
    document = synthetic(
        ("ActHead2", "Part 1—Preliminary"),
        ("ActHead5", "1.1\tName of regulations"),
        ("ActHead1", "Schedule 1—Classification"),
        ("ActHead2", "Part 1—Classes of goods"),
        ("ActHead5", "1\tFirst clause"),
    )
    parsed = parse_document(read_document(document), config.INSTRUMENTS["TMR1995"])
    refs = [container.ref for container in parsed.containers]
    assert refs == ["TMR1995/pt1", "TMR1995/sch1", "TMR1995/sch1/pt1"]
    assert {p.ref for p in parsed.provisions} >= {
        "TMR1995/r1.1",
        "TMR1995/sch1/c1",
    }


def test_duplicate_provision_address_raises():
    document = synthetic(
        ("ActHead5", "41\tTrade mark"),
        ("subsection", "\t(1)\tWords."),
        ("ActHead5", "41\tTrade mark again"),
    )
    with pytest.raises(StructureError, match="claim"):
        parse_document(read_document(document), config.INSTRUMENTS["TMA1995"])
