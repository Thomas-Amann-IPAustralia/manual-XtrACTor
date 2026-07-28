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

#: How far past a reference to look for an instrument name. Wide enough to
#: cross 'of the ', narrow enough that the next sentence's instrument is not
#: pulled backwards. SOURCE_NOTES.md §4.
LOOKAHEAD_CHARS = 60


# --------------------------------------------------------------------------
# Patterns
# --------------------------------------------------------------------------

#: A consolidated Act or Regulation on AustLII:
#: /legis/cth/consol_act/tma1995121/s41.html
_AUSTLII_PROVISION = re.compile(
    r"/legis/cth/consol_(?P<kind>act|reg)/(?P<db>[a-z0-9]+)/"
    r"(?P<node>[a-z]+[0-9][0-9a-z.]*)\.html",
    re.IGNORECASE,
)

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
_ANY_INSTRUMENT = re.compile(
    r"\b[A-Z][A-Za-z()’'\-]*(?:\s+[A-Za-z()’'\-]+){0,7}"
    r"\s+(?:Act|Regulations)\s+\d{4}\b"
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
        symbol = "s" if match.group("kind").lower() == "act" else "r"
        number = _canonical_address(
            re.sub(r"^[a-z]+", "", match.group("node").lower())
        )
        mention = flatten_text(anchor)

        detailed = [
            _canonical_address(found.group("number")) + found.group("sub")
            for found in _ANCHOR_ADDRESS.finditer(mention)
            if _canonical_address(found.group("number")) == number
        ]
        for address in detailed or [number]:
            edges.append((f"{instrument}/{symbol}{address}", mention))

    return edges


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


def _named_instrument(window: str) -> tuple[str, int] | None:
    """The instrument named in a lookahead window, and where its name ends.

    The earliest name wins. A window can hold two — 'of the Trade Marks Act
    1995 and the Acts Interpretation Act 1901' — and it is the first that
    qualifies the reference the window hangs off.
    """
    candidates: list[tuple[int, int, str]] = []

    lowered = window.lower()
    for title, code in INSTRUMENT_TITLES.items():
        position = lowered.find(title)
        if position != -1:
            candidates.append((position, position + len(title), code))

    short = _SHORT_ACT.search(window)
    if short is not None and short.group("year") in ACT_BY_YEAR:
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
        symbol = "r" if word.removeprefix("sub").startswith("reg") else "s"

        stop = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        window = _lookahead_window(text, match.end(), stop)
        named = _named_instrument(window)

        if named is not None:
            instrument, offset = named
            certainty = "explicit"
            mention = text[match.start() : match.end() + offset]
        else:
            instrument = DEFAULT_INSTRUMENT[symbol]
            certainty = "ambiguous" if len(scope) > 1 else "default"
            mention = match.group(0)

        mention = " ".join(mention.split())
        for address in _ADDRESS_ONLY.findall(match.group("addresses")):
            identifier = f"{instrument}/{symbol}{_canonical_address(address)}"
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


def extract_internal_refs(
    body_fragment: Tag, sitemap: dict[str, NavPage]
) -> list[str]:
    """Manual-internal cross references, resolved through the sitemap.

    Both hyperlinked and bare dotted forms ("see part 22.15.7"). Unresolvable
    targets are dropped: a string a consumer will try to follow and cannot is
    worse than an absent one.

    Hyperlinks resolve by URL, which is the only safe key — the same slug
    belongs to two different Parts (SOURCE_NOTES.md §2), so a reference must
    never be resolved by matching slugs or titles.
    """
    refs: set[str] = set()

    for anchor in body_fragment.find_all("a", href=True):
        target = sitemap.get(normalise_url(str(anchor["href"])))
        if target is not None:
            refs.add(target.page_ref)

    page_refs = frozenset(page.page_ref for page in sitemap.values())
    for match in _BARE_INTERNAL_REF.finditer(flatten_text(body_fragment)):
        resolved = _resolve_dotted(
            match.group("part"), match.group("rest"), page_refs
        )
        if resolved is not None:
            refs.add(resolved)

    return sorted(refs)
