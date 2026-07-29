"""Provisions, cases and internal cross references.

Owned by T6. The signatures below are fixed — see ARCHITECTURE.md.

Called by the chunker, per chunk. Kept separate because these three functions
carry the densest regex logic in the package and the most test cases.

Two extraction paths, and the distinction between them is the point of the
module. An AustLII href is the Manual's authors telling you what a paragraph is
about; a text match is our inference from seeing 'section 41' in prose. They are
recorded as `extraction: "href"` and `extraction: "regex"` and never collapsed.

Nothing here resolves meaning. Where the source is ambiguous the ambiguity is
recorded — see `_certainty` — and left for a human. Rule 1.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from bs4 import Tag

from tmm_snapshot import config
from tmm_snapshot.fetch import normalise_url
from tmm_snapshot.page import flatten_text
from tmm_snapshot.sitemap import NavPage


class UnknownInstrument(Exception):
    """An AustLII link whose database fragment cannot be read.

    Raised rather than dropped. A hyperlinked provision is the highest
    confidence edge this pipeline produces, and silently discarding one because
    the Manual started citing an instrument we have not seen would lose exactly
    the edges most worth having. Extend AUSTLII_INSTRUMENTS and re-run.
    """


# --------------------------------------------------------------------------
# Instruments
# --------------------------------------------------------------------------

#: AustLII database fragments seen in the Manual, from SOURCE_NOTES.md §3.
#: The fragment is `<abbreviation><year><consolidation number>`, so an unseen
#: instrument is usually derivable — see `_instrument_from_db`. This map is
#: kept as the record of what has actually been observed, and as the check that
#: the derivation agrees with it — not as a whitelist. The trailing digits are a
#: consolidation number, so one instrument has several fragments and the
#: Manual's own pages disagree about which of them to link.
AUSTLII_INSTRUMENTS: dict[str, str] = {
    "tma1995121": "TMA1995",
    "tmr1995264": "TMR1995",
    "tmr1995230": "TMR1995",
    "aia1901230": "AIA1901",
}

#: Instrument titles the extractor can attribute a reference to. Matching is on
#: the full title including the year: 'the Act' is deliberately absent, because
#: it is anaphoric and resolving it is what SOURCE_NOTES.md §4 forbids.
#:
#: 'Trade Mark Regulations 1995' — singular Mark — is the Manual's own typo on
#: the Part 32B landing text, not ours.
INSTRUMENT_TITLES: dict[str, str] = {
    "trade marks act 1995": "TMA1995",
    "trade marks act 1955": "TMA1955",
    "trade marks act 1905": "TMA1905",
    "trade marks regulations 1995": "TMR1995",
    "trade mark regulations 1995": "TMR1995",
    "acts interpretation act 1901": "AIA1901",
}

#: 'the 1995 Act' is a named reference, not an anaphoric one: the year picks
#: the instrument out. Only years with a Trade Marks Act are resolvable —
#: anything else counts towards ambiguity but attributes nothing.
ACT_BY_YEAR: dict[str, str] = {
    "1905": "TMA1905",
    "1955": "TMA1955",
    "1995": "TMA1995",
}

#: What a bare reference is assumed to mean when exactly one instrument is in
#: scope. 'Section 41' in a Trade Marks Manual is the Trade Marks Act; a bare
#: regulation is the Trade Marks Regulations. Recorded as certainty 'default'
#: so a consumer can tell an assumption from a statement.
DEFAULT_INSTRUMENT: dict[str, str] = {"s": "TMA1995", "r": "TMR1995"}

#: The instrument type a title ends in, which is the word that says whether it
#: can hold sections or regulations. Read off the tail rather than searched for
#: anywhere in the string: 'Regulatory Powers Act 2014' is an Act.
_TITLE_KIND = re.compile(r"\bregulations?\s+\d{4}$")

#: A reference word that states no kind. An Act and a set of Regulations both
#: have paragraphs, so 'paragraph 4.12(1)(b)' says nothing about which of them
#: holds it — where 'section' and 'regulation' each do. Left forcing an Act,
#: these could not be attributed to the Regulations even where the Manual named
#: them in the very next words.
_KIND_NEUTRAL = re.compile(r"^(?:sub)?paragraphs?$", re.IGNORECASE)

#: How far past a reference to look for an instrument name. Wide enough to
#: cross 'of the ', narrow enough that the next sentence's instrument is not
#: pulled backwards. SOURCE_NOTES.md §4.
LOOKAHEAD_CHARS = 60


# --------------------------------------------------------------------------
# Patterns
# --------------------------------------------------------------------------

#: A consolidated Act or Regulation on AustLII:
#: /legis/cth/consol_act/tma1995121/s41.html
#:
#: The node's alpha prefix says *what kind of thing* the page is, and it is
#: captured rather than stripped. AustLII writes both a section and a
#: regulation as `sN` — `/consol_reg/tmr1995230/s4.5.html` is regulation 4.5 —
#: so `s` takes its symbol from the instrument. `sch` does not: it is a
#: Schedule, and reading `sch2.html` as `2` produced `TMR1995/r2` for Schedule 2
#: of the Regulations, on the strongest evidence the schema can carry.
_AUSTLII_PROVISION = re.compile(
    r"/legis/cth/consol_(?P<kind>act|reg)/(?P<db>[a-z0-9]+)/"
    r"(?P<prefix>[a-z]+)(?P<node>[0-9][0-9a-z.]*)\.html",
    re.IGNORECASE,
)

#: An AustLII node prefix, and the segment it addresses. `None` means "take the
#: symbol from the instrument", which is the ordinary case. A prefix that is not
#: here raises, for the same reason an unknown database fragment does: the node
#: names something, and guessing which kind of something puts the edge on the
#: wrong provision while looking exactly like a good one.
#: `r` is here because AustLII uses it for instruments drafted as rules, and
#: it means the same thing `s` does: the node is a provision, and the symbol
#: comes from the instrument. Only `s` (938 links) and `sch` (8) occur in this
#: corpus today.
AUSTLII_NODE_PREFIXES: dict[str, str | None] = {"s": None, "r": None, "sch": "sch"}

_DB_FRAGMENT = re.compile(r"^(?P<abbr>[a-z]{2,8})(?P<year>(?:1[6-9]|20)\d{2})\d*$")

#: A provision address: '41', '41(3)', '44(3)(a)', '4.15', '6A', '21.11A'.
#: A letter suffix rides on any dotted component, not only the first: the
#: Regulations have both a Part 3A (r3A.3) and inserted regulations (r21.11A).
_ADDRESS = r"\d{1,4}[A-Z]?(?:\.\d+[A-Z]?)*(?:\([0-9a-zA-Z]{1,3}\))*"

#: A textual reference, possibly to several provisions at once:
#: 'sections 24, 25 and 26', 'subsection 41(3)', 'regulation 4.15', 's 41'.
#: Longest keywords first — alternation takes the first branch that matches, so
#: 'subsection' must be offered before 'section'.
_REFERENCE = re.compile(
    r"\b(?P<word>subsections?|subparagraphs?|subregulations?|sections?"
    r"|paragraphs?|regulations?|regs?\.?|ss?\.?)\s*"
    rf"(?P<addresses>{_ADDRESS}(?:\s*(?:,|;|and|or|to|&)\s*{_ADDRESS})*)",
    re.IGNORECASE,
)

#: Case-insensitive to match _REFERENCE, which embeds _ADDRESS under
#: IGNORECASE: this pattern re-splits the addresses that one captured, so a
#: stricter case rule here would silently truncate 's 217a' to '217'.
_ADDRESS_ONLY = re.compile(_ADDRESS, re.IGNORECASE)

#: The number, and any subsection detail, inside an anchor's own words:
#: 'sections 41(3) or 41(4)' hanging off a link to s41.
_ANCHOR_ADDRESS = re.compile(
    rf"\b(?P<number>\d{{1,4}}[A-Za-z]?(?:\.\d+[A-Za-z]?)*)"
    rf"(?P<sub>(?:\([0-9a-zA-Z]{{1,3}}\))+)"
)

#: Any named instrument, for counting how many are in scope. Deliberately
#: permissive: it feeds the ambiguity test only, never attribution, and
#: over-counting produces a reference flagged for review rather than one
#: confidently attributed to the wrong Act.
#: `Regulations` is optionally singular because Commonwealth drafting switched
#: to it around 2015: the 'Defence Regulation 2016' and the 'Intellectual
#: Property Legislation Amendment (Raising the Bar) Regulation 2013' are both
#: cited in this corpus. Without the singular they are not recognised as titles,
#: so the year is read as a provision number and 13 edges landed on
#: `TMR1995/r2016`, `r2013` and `r1991` at certainty `default`.
_ANY_INSTRUMENT = re.compile(
    r"\b[A-Z][A-Za-z()’'\-]*(?:\s+[A-Za-z()’'\-]+){0,7}"
    r"\s+(?:Act|Regulations?)\s+\d{4}\b"
)

_SHORT_ACT = re.compile(r"\bthe\s+(?P<year>\d{4})\s+Act\b")

#: Neutral citations — '[2018] FCAFC 109' — and reported ones —
#: '(1954) 71 RPC 43'. Courts and series seen are listed in SOURCE_NOTES.md §9;
#: neither pattern whitelists them, because the shape is distinctive on its own
#: and a whitelist would silently drop the first unseen court.
_NEUTRAL_CASE = re.compile(
    r"\[(?P<year>(?:18|19|20)\d{2})\]\s+(?P<court>[A-Z]{2,10})\s+(?P<number>\d{1,4})\b"
)
_REPORTED_CASE = re.compile(
    r"\((?P<year>(?:18|19|20)\d{2})\)\s+(?P<volume>\d{1,3})\s+"
    r"(?P<series>[A-Z]{2,10})\s+(?P<page>\d{1,4})\b"
)

#: A bare cross reference in the prose: 'see part 22.15.7'. Requires at least
#: one dotted component, so 'Part 22 of this Manual' — which names a Part and
#: not a page — is not treated as a page reference. SOURCE_NOTES.md §8.
_BARE_INTERNAL_REF = re.compile(
    r"\bparts?\s+(?P<part>\d{1,3}[A-Z]?)(?P<rest>(?:\.\d+)+)", re.IGNORECASE
)

#: The Manual saying, in its own words, that a bare reference is to the Part
#: the reader is already in: 'see part 2.3.1(c) **of this chapter**'. The
#: adjective slot takes 'this revised chapter', which Part 32A's annex uses.
#:
#: 'of this manual' is deliberately absent and must stay absent: it means the
#: Manual as a whole, so 'Part 29.9 of this manual' is Part 29 and reading it
#: locally would invert this rule into the bug it exists to fix.
_LOCAL_QUALIFIER = re.compile(
    r"\b(?:of|in|at)\s+th(?:is|e\s+(?:present|current))\s+"
    r"(?:\w+\s+){0,2}(?:chapter|part|section)\b",
    re.IGNORECASE,
)

#: How far past a bare reference to look for that qualifier. Wide enough to
#: cross ' and 2.3.2 ' — the Manual writes 'parts 2.3.1 and 2.3.2 of this
#: chapter' and only the first is a match — and cut at a sentence end.
LOCAL_QUALIFIER_CHARS = 48

#: A sentence boundary: a full stop followed by space or end of string. Not a
#: bare full stop, which would cut inside '2.3.2' and hide the qualifier behind
#: the very digits it qualifies.
_SENTENCE_END = re.compile(r"\.(?:\s|$)")

#: The heading number leading a Drupal anchor: the fragment on
#: `/trademark/4.-classification-procedures#4.5-goods-or-services-to-be-grouped`
#: is the target heading's own slug, and it opens with the number the Manual
#: prints. Deliberately the same shape as `chunker._LEADING_ADDRESS`, because
#: the address it reads has to agree with the one the chunker built the target
#: `chunk_ref` from — `tests/test_citations.py` pins the two together, since
#: importing the chunker here would be a cycle.
_ANCHOR_HEADING_ADDRESS = re.compile(r"^(?P<address>\d{1,3}[A-Z]?(?:\.\d+)*)(?=-|$)")

#: Strongest evidence first. Used to collapse the several ways one provision
#: can be mentioned in a passage into the single edge SCHEMA.md asks for.
_PRECEDENCE = {"href": 0, "explicit": 1, "default": 2, "ambiguous": 3}


# --------------------------------------------------------------------------
# Provisions
# --------------------------------------------------------------------------


def _instrument_from_db(fragment: str) -> str:
    """'tma1995121' -> 'TMA1995'.

    The observed map is consulted first so that the three fragments in
    SOURCE_NOTES.md §3 are pinned rather than derived. Anything else is read
    off the fragment, which encodes the abbreviation and the year; a fragment
    that does not have that shape raises, because guessing an instrument is
    guessing what a paragraph is about.
    """
    known = AUSTLII_INSTRUMENTS.get(fragment.lower())
    if known is not None:
        return known

    match = _DB_FRAGMENT.match(fragment.lower())
    if match is None:
        raise UnknownInstrument(
            f"AustLII database fragment {fragment!r} is not "
            "<abbreviation><year><consolidation>; add it to "
            "AUSTLII_INSTRUMENTS rather than letting the citation through "
            "attributed to the wrong instrument"
        )
    return match.group("abbr").upper() + match.group("year")


def _canonical_address(address: str) -> str:
    """'217a' -> '217A', '21.11a' -> '21.11A', '44(3)(a)' -> '44(3)(a)'.

    One provision has one id, so the case of a letter suffix cannot depend on
    where the reference was found. AustLII node names are lower case
    (`/s217a.html`), the prose writes `section 217A`, and both mean section
    217A — left alone they become two edges for one provision, and only one of
    them matches the schema's pattern.

    Paragraph letters inside parentheses are a different address space and are
    left exactly as found: s44(3)(a) and s44(3)(A) are not the same provision.
    """
    number, parenthesis, subsection = address.partition("(")
    return number.upper() + parenthesis + subsection


def _href_edges(fragment: Tag) -> list[tuple[str, str]]:
    """(provision id, mention) from AustLII hyperlinks, in document order.

    The link carries the section; the link's own words carry any subsection.
    'sections 41(3) or 41(4)' hanging off /s41.html is two provisions, both
    stated by the authors, and flattening them to `s41` would lose the detail
    the sentence is actually about.
    """
    edges: list[tuple[str, str]] = []

    for anchor in fragment.find_all("a", href=True):
        match = _AUSTLII_PROVISION.search(str(anchor["href"]))
        if match is None:
            continue

        instrument = _instrument_from_db(match.group("db"))
        prefix = match.group("prefix").lower()
        if prefix not in AUSTLII_NODE_PREFIXES:
            raise UnknownInstrument(
                f"AustLII node prefix {prefix!r} in {anchor['href']!r} is not "
                "one this module can read; add it to AUSTLII_NODE_PREFIXES "
                "rather than letting the citation through addressed as a "
                "section of its instrument"
            )
        segment = AUSTLII_NODE_PREFIXES[prefix]
        mention = flatten_text(anchor)

        if segment is not None:
            # A Schedule. It has no subsection detail to read out of the
            # anchor's words, and the segment is the one the legislation
            # snapshot uses for the same Schedule, so the id is a foreign key
            # onto it exactly as a section id is.
            edges.append((f"{instrument}/{segment}{match.group('node').lower()}", mention))
            continue

        symbol = "s" if match.group("kind").lower() == "act" else "r"
        number = _canonical_address(match.group("node").lower())

        detailed = [
            _canonical_address(found.group("number")) + found.group("sub")
            for found in _ANCHOR_ADDRESS.finditer(mention)
            if _canonical_address(found.group("number")) == number
        ]
        for address in detailed or [number]:
            edges.append((f"{instrument}/{symbol}{address}", mention))

    return edges


def instrument_kind(instrument: str) -> str:
    """'s' if the instrument holds sections, 'r' if it holds regulations.

    An Act is divided into sections and a set of Regulations into regulations,
    and neither ever holds the other's. That makes the reference word and the
    instrument two independent readings of one fact, so where they disagree
    something has gone wrong — see `_named_instrument`.

    Takes either a code ('TMR1995') or the raw lower-cased title that
    `_instruments_in_scope` keeps for an instrument we have no code for. Titles
    reach here only from `_ANY_INSTRUMENT`, which requires the tail
    'Act <year>' or 'Regulations <year>', so the tail is always there to read.
    """
    known = INSTRUMENT_KIND.get(instrument)
    if known is not None:
        return known
    return "r" if _TITLE_KIND.search(instrument.strip().lower()) else "s"


#: Every instrument this module can name, by the type of provision it holds.
#: Derived from the titles rather than written out again, so a new instrument
#: is declared in exactly one place.
INSTRUMENT_KIND: dict[str, str] = {
    code: ("r" if _TITLE_KIND.search(title) else "s")
    for title, code in INSTRUMENT_TITLES.items()
}
INSTRUMENT_KIND.update({code: "s" for code in ACT_BY_YEAR.values()})

#: Whether an instrument's provisions are numbered with dots. This is the same
#: sort of fact as `INSTRUMENT_KIND` — a structural property of the instrument,
#: independent of any reference to it — and it is the second of the two
#: independent readings that catch a misattributed citation.
#:
#: Measured over the legislation snapshot: **0 of the Trade Marks Act's 315
#: section numbers contain a dot, and 401 of the Regulations' 401 regulation
#: numbers do.** So `TMA1995/s4.7` and `TMR1995/r2016` both name addresses their
#: instrument cannot express, and 204 such edges reached the 0.8.0 corpus.
#:
#: **Only instruments whose numbering has actually been checked are listed.**
#: Absence means "not asserted", never "undotted": the Criminal Code Act 1995
#: numbers its sections `6.1`, `11.5`, `137.1`, and the Manual cites all three.
#: Listing it as dotted-or-not without reading it would be the guess rule 1
#: forbids, and getting it wrong would silently drop real edges.
INSTRUMENT_DOTTED: dict[str, bool] = {"TMA1995": False, "TMR1995": True}

#: A provision number, without any subsection detail: the part the numbering
#: rule is about. 's44(3)(a)' -> '44'.
_NUMBER_ONLY = re.compile(r"^[^(]*")

#: A Schedule address — `sch2`. Matched as a whole segment and never by its
#: first character, which is the `s` of a section.
SCHEDULE_ADDRESS = re.compile(r"^sch\d")


def instrument_holds(identifier: str) -> bool:
    """Can the instrument this id names express the address it names?

    Two independent readings of one fact have to agree, and this is the second
    of them. `instrument_kind` compares the reference's *word* against the
    instrument: an Act holds sections and Regulations hold regulations, so
    `TMR1995/s224` is impossible. This compares the *number*: the Trade Marks
    Act numbers its sections without dots and the Regulations number theirs with
    them, so `TMA1995/s4.7` is impossible too.

    The Manual's own Part-internal numbering is also `N.M` — 'see paragraph 6.5'
    means the Manual's paragraph 6.5, and Part 14 has one — which is why a
    dotted address is *dropped* rather than re-attributed to the Regulations.
    The two numbering systems collide, so the fact that `TMR1995/r6.5` exists is
    a coincidence and not evidence: re-attributing would turn a visibly broken
    edge into an invisibly wrong one that resolves. `SOURCE_NOTES.md` §32.

    Unknown instruments pass. This is a check for a contradiction, not a
    whitelist, and an instrument whose numbering nobody has read cannot
    contradict anything.
    """
    instrument, _, address = identifier.partition("/")
    if not address or SCHEDULE_ADDRESS.match(address):
        # A Schedule is neither a section nor a regulation; both rules below
        # are about the two kinds an instrument divides its body into.
        return True

    expected = INSTRUMENT_KIND.get(instrument)
    if expected is not None and address[0] != expected:
        return False

    dotted = INSTRUMENT_DOTTED.get(instrument)
    if dotted is None or address[0] not in {"s", "r"}:
        return True
    return ("." in _NUMBER_ONLY.match(address[1:]).group(0)) is dotted


def _instruments_in_scope(text: str) -> set[str]:
    """Every instrument the passage names, mapped where we recognise it.

    Cardinality is all this is used for: more than one instrument in scope
    turns a bare reference from an assumption into an ambiguity. Unrecognised
    titles are kept under their own surface form so that they still count.
    """
    scope: set[str] = set()

    for match in _ANY_INSTRUMENT.finditer(text):
        title = " ".join(match.group(0).split()).lower()
        scope.add(INSTRUMENT_TITLES.get(title, title))

    for match in _SHORT_ACT.finditer(text):
        year = match.group("year")
        scope.add(ACT_BY_YEAR.get(year, f"the {year} act"))

    return scope


def _lookahead_window(text: str, start: int, stop: int) -> str:
    """The text a reference may be qualified by, and no more.

    Capped at LOOKAHEAD_CHARS, cut at the next reference — an instrument named
    after another section number belongs to that section, not to this one —
    and cut at a full stop, which no instrument title contains.
    """
    window = text[start : min(stop, start + LOOKAHEAD_CHARS)]
    return window.split(".")[0]


def _named_instrument(window: str, symbol: str | None) -> tuple[str, int] | None:
    """The instrument named in a lookahead window, and where its name ends.

    The earliest name wins. A window can hold two — 'of the Trade Marks Act
    1995 and the Acts Interpretation Act 1901' — and it is the first that
    qualifies the reference the window hangs off.

    `symbol` is `None` where the reference's own word states no kind, and then
    an instrument of either kind qualifies and supplies the symbol itself.

    **Only an instrument that could hold the reference counts.** A section
    lives in an Act and a regulation in Regulations, so a title of the wrong
    kind is not this reference's instrument however close it sits. It is
    usually the next column: the Relevant Legislation pages are three-column
    tables, and flattening one to a run of cell text puts 'Section 224 |
    Extension of time | Trade Marks Regulations 1995' on a single line, where a
    60-character lookahead reaches the instrument column of the same row. Left
    unchecked that produced `TMR1995/s224` — a section of the Regulations,
    which does not exist — and recorded it as `explicit`, the confident end of
    the scale. 20 edges in the July 2026 corpus.

    Discarding the name here rather than raising is deliberate: the row is not
    malformed, it says exactly what it means to a reader with the columns back.
    What the extractor may not do is carry the wrong instrument, so the
    reference falls through to the same treatment as an unqualified one and
    ends up `TMA1995/s224` at `default` or `ambiguous`.
    """
    candidates: list[tuple[int, int, str]] = []

    lowered = window.lower()
    for title, code in INSTRUMENT_TITLES.items():
        position = lowered.find(title)
        if position != -1 and symbol in (None, instrument_kind(code)):
            candidates.append((position, position + len(title), code))

    short = _SHORT_ACT.search(window)
    if short is not None and short.group("year") in ACT_BY_YEAR and symbol in (None, "s"):
        candidates.append((short.start(), short.end(), ACT_BY_YEAR[short.group("year")]))

    if not candidates:
        return None
    _, end, code = min(candidates)
    return code, end


def _regex_edges(text: str) -> list[tuple[str, str, str]]:
    """(provision id, certainty, mention) from the prose, in document order."""
    # 'Trade Mark Regulations 1995' contains the keyword 'Regulations' followed
    # by a number, which is a year and not a provision. A reference falling
    # wholly inside an instrument's title is part of the title. Dropped before
    # anything else looks at the matches, so that such a phantom does not also
    # end up truncating the lookahead of the reference in front of it.
    titles = [match.span() for match in _ANY_INSTRUMENT.finditer(text)]
    matches = [
        match
        for match in _REFERENCE.finditer(text)
        if not any(
            start <= match.start() and match.end() <= end for start, end in titles
        )
    ]

    scope = _instruments_in_scope(text)
    edges: list[tuple[str, str, str]] = []

    for index, match in enumerate(matches):
        word = match.group("word").lower()
        neutral = _KIND_NEUTRAL.match(word) is not None
        symbol = "r" if word.removeprefix("sub").startswith("reg") else "s"

        stop = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        window = _lookahead_window(text, match.end(), stop)
        named = _named_instrument(window, None if neutral else symbol)

        if named is not None:
            instrument, offset = named
            # A kind-neutral word takes its symbol from the instrument the
            # source named, which is the only thing in the sentence that states
            # one. Where nothing is named it falls back to a section below,
            # because that is what the great majority of bare 'paragraph N(a)'
            # references in this corpus are.
            if neutral:
                symbol = instrument_kind(instrument)
            certainty = "explicit"
            mention = text[match.start() : match.end() + offset]
        else:
            instrument = DEFAULT_INSTRUMENT[symbol]
            # Only an instrument that could hold this reference competes for
            # it. 'Section 41' is a reference to an Act whatever Regulations
            # the passage also names, and the Manual names both on nearly every
            # page — the Relevant Legislation preamble lists the Act and the
            # Regulations together — so counting every instrument in scope made
            # 39% of the corpus's regex edges ambiguous, a bucket SCHEMA.md
            # says never to hydrate from. What is genuinely in doubt is which
            # *Act*: 'section 26' in a paragraph about the 1955 Act. That case
            # still has two Acts in scope and still comes out ambiguous.
            competing = {
                named_instrument
                for named_instrument in scope
                if instrument_kind(named_instrument) == symbol
            }
            certainty = "ambiguous" if len(competing) > 1 else "default"
            mention = match.group(0)

        mention = " ".join(mention.split())
        for address in _ADDRESS_ONLY.findall(match.group("addresses")):
            identifier = f"{instrument}/{symbol}{_canonical_address(address)}"
            # An address the instrument cannot express is not a reference to
            # that instrument, and there is nothing else here to make it one.
            # Dropped rather than stored flagged: an id asserting a section of
            # the Trade Marks Act that cannot exist is a claim about the law,
            # and `certainty` qualifies which instrument was meant, not whether
            # the provision is real. Same rule `internal_refs` already applies —
            # an unresolvable reference is worse than an absent one, because a
            # consumer will try to follow it. `SOURCE_NOTES.md` §32.
            if not instrument_holds(identifier):
                continue
            edges.append((identifier, certainty, mention))

    return edges


def extract_provisions(body_fragment: Tag, text: str) -> list[dict]:
    """Statutory references, deduplicated.

    Hrefs first (`extraction: "href"`), read from the AustLII db fragment map
    in SOURCE_NOTES.md §3. Then plain-text mentions (`extraction: "regex"`)
    with a certainty of explicit / default / ambiguous.

    `ambiguous` is not a failure mode, it is the mitigation: the Part 22.1
    anaphora case ("section 26 of the Act", meaning the 1955 Act) is
    unresolvable by regex and forbidden to a model. Record the doubt.

    An ambiguous edge still carries the default instrument in its id, because
    the schema has nowhere else to put one — but it carries it alongside the
    flag, which is the difference between a doubtful edge and a silent error.

    'section 41' four times in one passage is one edge, and the strongest
    evidence for it wins: a hyperlink over a named instrument over an
    assumption over an ambiguity.
    """
    best: dict[str, tuple[int, dict]] = {}

    def offer(identifier: str, rank: str, record: dict) -> None:
        score = _PRECEDENCE[rank]
        if identifier not in best or score < best[identifier][0]:
            best[identifier] = (score, record)

    for identifier, mention in _href_edges(body_fragment):
        offer(
            identifier,
            "href",
            {"id": identifier, "extraction": "href", "mention": mention},
        )

    for identifier, certainty, mention in _regex_edges(text):
        offer(
            identifier,
            certainty,
            {
                "id": identifier,
                "extraction": "regex",
                "certainty": certainty,
                "mention": mention,
            },
        )

    return [record for _, (_, record) in sorted(best.items())]


# --------------------------------------------------------------------------
# Cases
# --------------------------------------------------------------------------


def extract_cases(text: str) -> list[dict]:
    """Decisions in neutral and reported styles. See SOURCE_NOTES.md §9.

    Party names are deliberately not extracted — they are unreliable to
    identify and nothing downstream needs them. The id is a rearrangement of
    the citation and nothing more, so it can always be read back.
    """
    found: dict[str, str] = {}

    for match in _NEUTRAL_CASE.finditer(text):
        year, court, number = match.group("year", "court", "number")
        identifier = f"CASE/{year}/{court}/{number}"
        found.setdefault(identifier, f"[{year}] {court} {number}")

    for match in _REPORTED_CASE.finditer(text):
        year, volume, series, page = match.group("year", "volume", "series", "page")
        identifier = f"CASE/{year}/{series}/{volume}/{page}"
        found.setdefault(identifier, f"({year}) {volume} {series} {page}")

    return [
        {"id": identifier, "citation": citation}
        for identifier, citation in sorted(found.items())
    ]


# --------------------------------------------------------------------------
# Internal cross references
# --------------------------------------------------------------------------


def _resolve_dotted(part: str, rest: str, page_refs: frozenset[str]) -> str | None:
    """'22' + '.15.7' -> the deepest page that address falls inside.

    The Manual's bare references address headings, not pages: 'part 22.15.7'
    is a heading on page 22.15, and no page has that address. Trailing
    components are therefore dropped until a page in the inventory is found,
    and if none is, the reference is dropped — a string a consumer will try to
    follow and cannot is worse than an absent one (SOURCE_NOTES.md §8).

    Never shortened as far as the Part: 'TMM/Part22' is not a page.
    """
    components = rest.strip(".").split(".")
    while components:
        candidate = "/".join(
            [config.REF_PREFIX, f"Part{part.upper()}", *components]
        )
        if candidate in page_refs:
            return candidate
        components.pop()
    return None


def _anchor_ref(page_ref: str, href: str) -> str:
    """The candidate ref a hyperlink addresses: a chunk where it names one.

    A Manual link carrying a fragment is aimed at a heading, not at the top of
    a page — `#4.5-goods-or-services-to-be-grouped-together-by-class-number` is
    the Drupal slug of the heading '4.5 Goods or services to be grouped
    together by class number', and it opens with the number the Manual prints.
    That number is what the chunker builds the target's `chunk_ref` from, so
    the address is already determined; nothing here is inferred.

    Returned as a *candidate*, because whether that chunk exists is a fact
    about a different page and cannot be known while this one is being cut.
    `resolve_internal_refs` checks it against the finished inventory and falls
    back to the page. A fragment naming no number — a hand-written anchor —
    yields the page, which is all it can support.
    """
    fragment = urlsplit(href.strip()).fragment
    match = _ANCHOR_HEADING_ADDRESS.match(fragment)
    if match is None:
        return page_ref
    return f"{page_ref}/{match.group('address').replace('.', '/')}"


def internal_ref_key(record: dict) -> tuple[str, ...]:
    """The stable order of the `internal_refs` array. Rule 2.

    Sorted by target, then by everything else, so that reordering the prose
    cannot reorder the file. Same argument as `writer._provision_key`, and it
    lives here because the precedence below has to break ties the same way.
    """
    return (
        str(record.get("ref", "")),
        str(record.get("extraction", "")),
        str(record.get("certainty") or ""),
        str(record.get("mention") or ""),
    )


def _strongest(records: list[dict]) -> list[dict]:
    """One record per target, keeping the best evidence for it. Sorted.

    A passage that both links to a page and names it in prose asserts one
    edge, not two, and the hyperlink is the authors saying so — the same
    collapse `extract_provisions` makes, with the same precedence.
    """
    best: dict[str, tuple[int, dict]] = {}
    for record in records:
        rank = _PRECEDENCE[
            "href" if record["extraction"] == "href" else record["certainty"]
        ]
        target = record["ref"]
        if target not in best or rank < best[target][0]:
            best[target] = (rank, record)
    return sorted((record for _, record in best.values()), key=internal_ref_key)


def _local_reading(
    page_ref: str | None, part: str, rest: str, page_refs: frozenset[str]
) -> str | None:
    """The same digits read as an address inside the Part doing the referring.

    The Manual uses 'part' for both things. 'part 22.15.7' on a Part 32B page
    is Part 22 (SOURCE_NOTES.md §8) — and 'part 2.3.1 of this chapter' on a
    Part 32A page is that Part's own section 2.3.1, not Part 2's page 3. Both
    readings are addresses the inventory can be asked about; this builds the
    second one so that `_bare_edges` can see whether it competes.
    """
    if page_ref is None:
        return None
    segments = page_ref.split("/")
    if len(segments) < 2 or not segments[1].startswith("Part"):
        return None
    own = segments[1][len("Part") :]
    if own.upper() == part.upper():
        # The reference names the Part it sits in, so there is no second
        # reading to compete: both are the same document.
        return None
    return _resolve_dotted(own, f".{part}{rest}", page_refs)


def _bare_edges(
    text: str, page_refs: frozenset[str], page_ref: str | None
) -> list[dict]:
    """Cross references written as prose, with how confidently they were read.

    Three certainties, and they mean what `extract_provisions` means by them.

    `explicit` — the Manual settled it. 'see part 2.3.1(c) **of this chapter**'
    names the Part the reader is in, so the digits are that Part's own address
    and not Part 2's. Reading those four words is reading the source, not
    guessing at it.

    `ambiguous` — both readings resolve against the inventory and nothing in
    the source chooses. The conventional reading is kept, because the schema
    has nowhere else to put a target, and the flag beside it is what stops it
    being mistaken for a fact — exactly the arrangement `extract_provisions`
    uses for a bare 'section 26' with two Acts in scope.

    `default` — one reading, taken by the convention of SOURCE_NOTES.md §8.

    Before 0.8.0 there was no such distinction and no flag, and three
    references on Part 32A — a Part about plant varietal names — were stored
    as confident edges into Part 2, *Filing Requirements*. Two of them sat in
    the same array as the correct edge, which the paragraph's own hyperlink
    had already supplied, with nothing to tell a consumer which was which.
    """
    edges: list[dict] = []

    for match in _BARE_INTERNAL_REF.finditer(text):
        part, rest = match.group("part"), match.group("rest")
        conventional = _resolve_dotted(part, rest, page_refs)
        local = _local_reading(page_ref, part, rest, page_refs)

        window = text[match.end() : match.end() + LOCAL_QUALIFIER_CHARS]
        window = _SENTENCE_END.split(window)[0]
        qualified = _LOCAL_QUALIFIER.search(window) is not None

        if local is not None and qualified:
            target, certainty = local, "explicit"
        elif local is not None and conventional is not None:
            target, certainty = conventional, "ambiguous"
        elif conventional is not None:
            target, certainty = conventional, "default"
        elif local is not None:
            target, certainty = local, "default"
        else:
            # Neither reading names anything in the inventory. Dropped rather
            # than stored: a consumer will try to follow it. SOURCE_NOTES.md §8.
            continue

        edges.append(
            {
                "ref": target,
                "extraction": "regex",
                "certainty": certainty,
                "mention": " ".join(match.group(0).split()),
            }
        )

    return edges


def extract_internal_refs(
    links: list[dict],
    text: str,
    sitemap: dict[str, NavPage],
    page_ref: str | None = None,
) -> list[dict]:
    """Manual-internal cross references, resolved through the sitemap.

    Both hyperlinked and bare dotted forms ("see part 22.15.7"), and **each
    records which it was**. `provisions` has carried `extraction: href|regex`
    since the beginning, for the reason SCHEMA.md gives: a hyperlink is the
    authors telling you what a passage is about and a regex match is our
    inference, and collapsing the two loses the only signal separating them.
    Until 0.8.0 this field collapsed them — 359 of its edges were the Manual's
    own links, 34 were prose read by a rule, and all 417 were bare strings.

    Hyperlinks resolve by URL, which is the only safe key — the same slug
    belongs to two different Parts (SOURCE_NOTES.md §2), so a reference must
    never be resolved by matching slugs or titles. A link's `#fragment` is
    dropped by that lookup and read separately by `_anchor_ref`, which is where
    the sub-section precision in 137 of the Manual's internal links comes from.

    **Takes the chunk's `links` and `text`, not its markup.** That is the
    0.8.0 change and it is not a convenience: a page skipped at gate 2 is never
    parsed, so its refs could never be re-settled against a snapshot that had
    moved under them, and a heading renamed on one page left dangling refs on
    every unchanged page that cited it (ARCHITECTURE.md §Settling). `links`
    holds every anchor's href verbatim and `text` holds the words, so the same
    function reads a live chunk and a stored one, and there is exactly one
    reading of the evidence rather than two that can drift apart.

    `page_ref` is the page doing the referring, and is what lets a bare
    reference be tested against the Part it sits in as well as the Part it
    names. Optional, because a caller that omits it simply gets the
    conventional reading — which is what every caller got before 0.8.0.

    What comes back may hold candidate chunk refs, which are only refs once
    `resolve_internal_refs` has seen the whole snapshot.
    """
    edges: list[dict] = []

    for link in links:
        href = link.get("href")
        if not isinstance(href, str):
            continue
        target = sitemap.get(normalise_url(href))
        if target is None:
            continue
        edges.append(
            {
                "ref": _anchor_ref(target.page_ref, href),
                "extraction": "href",
                "mention": str(link.get("text") or ""),
            }
        )

    page_refs = frozenset(page.page_ref for page in sitemap.values())
    edges.extend(_bare_edges(text, page_refs, page_ref))

    return _strongest(edges)


def resolve_internal_refs(
    refs: list[dict], chunk_refs: frozenset[str], page_refs: frozenset[str]
) -> list[dict]:
    """Candidate refs to refs that resolve, against the finished snapshot.

    A candidate from `_anchor_ref` names a heading on a page that was cut by a
    different call, possibly in a different run. Once the whole snapshot is
    known the question is decidable, so it is decided here rather than guessed
    earlier: the chunk exists and the ref is chunk-level, or it does not and
    the ref falls back to the page the link pointed at.

    Falling back rather than dropping is the difference from `_resolve_dotted`,
    and it is because the page half of the reference was already established by
    URL. The Manual moving a heading should coarsen a citation, not delete one.
    A candidate matching neither is dropped, which cannot happen for a link
    resolved through the sitemap and can for a stale hand-written anchor.

    Idempotent, and that is load-bearing rather than incidental: a settled ref
    is a valid candidate for the next run, which is what lets a page skipped at
    gate 2 be re-settled from its stored record without being re-cut.
    """
    settled: list[dict] = []

    for record in refs:
        ref = record["ref"]
        target: str | None = None

        if ref in chunk_refs or ref in page_refs:
            target = ref
        # The section exists but was long enough to be split, so its address
        # belongs to no single chunk — `TMM/Part14/4/4/8` is held by
        # `...~1` through `...~4`. A link to the heading is aimed at where the
        # section starts, and that is `~1` by construction. 27 of the Manual's
        # 47 addressed anchors land here.
        elif f"{ref}~1" in chunk_refs:
            target = f"{ref}~1"
        else:
            segments = ref.split("/")
            while len(segments) > 1:
                segments.pop()
                candidate = "/".join(segments)
                if candidate in page_refs:
                    target = candidate
                    break

        if target is not None:
            settled.append({**record, "ref": target})

    return _strongest(settled)
