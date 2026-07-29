"""The numbered tree inside a provision."""

from __future__ import annotations

import pytest
from legislation_fixtures import fixture_docx, synthetic

from frl_snapshot import config
from frl_snapshot.docx import read_document
from frl_snapshot.structure import parse_document
from frl_snapshot.units import UnitError, split_units


def _document(name: str, code: str):
    return parse_document(read_document(fixture_docx(name)), config.INSTRUMENTS[code])


def _provision(name: str, code: str, ref: str):
    document = _document(name, code)
    return next(p for p in document.provisions if p.ref == ref)


@pytest.fixture(scope="module")
def section41_units():
    return split_units(_provision("tma1995-slice", "TMA1995", "TMA1995/s41"))


def test_subsection_and_paragraph_addresses(section41_units):
    refs = [unit.ref for unit in section41_units]
    assert "TMA1995/s41(1)" in refs
    assert "TMA1995/s41(3)(a)" in refs
    assert "TMA1995/s41(4)(b)(iii)" in refs


def test_a_paragraph_is_a_child_of_its_subsection(section41_units):
    paragraph = next(u for u in section41_units if u.ref == "TMA1995/s41(3)(a)")
    assert paragraph.parent_ref == "TMA1995/s41(3)"
    assert paragraph.depth == 1
    assert paragraph.kind == "paragraph"


def test_unit_text_keeps_the_label(section41_units):
    subsection = next(u for u in section41_units if u.ref == "TMA1995/s41(3)")
    assert subsection.text.startswith("(3) This subsection applies")
    assert subsection.number == "(3)"


def test_units_join_back_to_the_provision_text():
    """The invariant that stops `text` and `units` drifting apart.

    Checked here over both fixtures and by `validate` over the whole corpus.
    """
    for name, code in (("tma1995-slice", "TMA1995"), ("tmr1995-slice", "TMR1995")):
        for provision in _document(name, code).provisions:
            units = split_units(provision)
            joined = " ".join(unit.text for unit in units)
            expected = " ".join(block.normalised() for block in provision.blocks)
            assert joined == expected, provision.ref


def test_consecutive_notes_are_siblings(section41_units):
    """Section 41 carries Note 1, Note 2 and Note 3 under the same paragraph.

    Anchoring each note on the previous one would nest them, and section 41
    alone would descend five levels.
    """
    notes = [
        unit
        for unit in section41_units
        if unit.kind == "note" and unit.text.startswith("Note ")
    ]
    assert len(notes) >= 3
    depths = {note.depth for note in notes if note.parent_ref == notes[0].parent_ref}
    assert len(depths) == 1


def test_a_notepara_belongs_to_its_note(section41_units):
    """Note 1 of section 41 has paragraphs (a) and (b), which are siblings."""
    paragraphs = [
        unit
        for unit in section41_units
        if unit.kind == "note" and unit.text.startswith(("(a)", "(b)"))
    ]
    assert len(paragraphs) == 2
    assert paragraphs[0].parent_ref == paragraphs[1].parent_ref
    assert paragraphs[0].depth == paragraphs[1].depth


def test_a_run_in_heading_parents_nothing():
    """How far a SubsectionHead reaches is a judgement, not a fact of markup."""
    units = split_units(
        _provision("tma1995-slice", "TMA1995", "TMA1995/front")
    )
    headings = [unit for unit in units if unit.kind == "heading"]
    if headings:
        assert not any(unit.parent_ref == headings[0].ref for unit in units)


def test_definitions_carry_their_term_as_emphasis():
    """The defined term is the leading bold-italic run. Recorded, not asserted."""
    units = split_units(_provision("tma1995-slice", "TMA1995", "TMA1995/s6"))
    definitions = [unit for unit in units if unit.kind == "definition"]
    assert definitions
    first = definitions[0]
    assert first.emphasis
    span = first.emphasis[0]
    assert span.weight == "bold-italic"
    assert first.text[span.start : span.end] == span.text
    assert first.text.startswith(span.text)


def test_emphasis_offsets_survive_normalisation():
    """The spans are measured against raw text with tabs; the record holds the
    collapsed text. Every offset in the corpus depends on the re-basing."""
    for name, code in (("tma1995-slice", "TMA1995"), ("tmr1995-slice", "TMR1995")):
        for provision in _document(name, code).provisions:
            for unit in split_units(provision):
                for span in unit.emphasis:
                    assert unit.text[span.start : span.end] == span.text


def test_the_regulations_duplicate_paragraph_letter_is_recorded_not_fixed():
    """r17A.61(2) really does have two paragraphs (b).

    Both keep '(b)' as their printed number, both are flagged, and only the
    second takes a positional suffix so the addresses stay distinct.
    """
    units = split_units(_provision("tmr1995-slice", "TMR1995", "TMR1995/r17A.61"))
    flagged = [unit for unit in units if unit.number_collision]
    assert len(flagged) == 2
    assert [unit.number for unit in flagged] == ["(b)", "(b)"]
    assert [unit.ref for unit in flagged] == [
        "TMR1995/r17A.61(2)(b)",
        "TMR1995/r17A.61(2)(b)~2",
    ]


def test_the_regulations_duplicate_subparagraph_number():
    units = split_units(_provision("tmr1995-slice", "TMR1995", "TMR1995/r20A.22"))
    flagged = [unit.ref for unit in units if unit.number_collision]
    assert flagged == [
        "TMR1995/r20A.22(2)(b)(ii)",
        "TMR1995/r20A.22(2)(b)(ii)~2",
    ]


def test_unit_refs_are_unique_within_a_provision():
    for name, code in (("tma1995-slice", "TMA1995"), ("tmr1995-slice", "TMR1995")):
        for provision in _document(name, code).provisions:
            refs = [unit.ref for unit in split_units(provision)]
            assert len(refs) == len(set(refs)), provision.ref


def test_ordinals_are_contiguous_from_one():
    for name, code in (("tma1995-slice", "TMA1995"), ("tmr1995-slice", "TMR1995")):
        for provision in _document(name, code).provisions:
            units = split_units(provision)
            assert [unit.ordinal for unit in units] == list(range(1, len(units) + 1))


def test_a_table_becomes_a_unit_with_its_grid():
    units = split_units(_provision("tmr1995-slice", "TMR1995", "TMR1995/sch9/c1"))
    tables = [unit for unit in units if unit.kind == "table"]
    assert tables
    assert tables[0].grid is not None
    assert any(cell["heading"] for row in tables[0].grid for cell in row)


def test_specials_is_not_mistaken_for_a_heading():
    """'131A  Definitions' inside Schedule 3 is the text of a section being
    inserted into a modified Part 13, and it appears identically in Schedules
    3, 4 and 5. Read as a provision it would collide three ways and with the
    real section 131A of the Act."""
    units = split_units(_provision("tmr1995-slice", "TMR1995", "TMR1995/sch3/item1"))
    specials = [unit for unit in units if unit.kind == "special"]
    assert specials
    assert specials[0].ref.startswith("TMR1995/sch3/item1")


def test_an_unmapped_style_raises():
    """A style this module has never seen means the stylesheet moved."""
    document = synthetic(
        ("ActHead5", "1\tShort title"),
        ("SomeNewOpcStyle", "\t(1)\tWords."),
    )
    parsed = parse_document(read_document(document), config.INSTRUMENTS["TMA1995"])
    with pytest.raises(UnitError, match="not in the unit map"):
        split_units(parsed.provisions[0])
