# Review of the 0.9.0 extraction — information loss, and deterministic headroom

An audit of `ingest/0.9.0` and `legislation/0.2.0` asking two questions, and
only these two:

1. **Is any information dropped between the source and the structured output?**
2. **Is there further metadata that can be extracted by clear deterministic
   means, to support an ontology built in a downstream repository?**

It deliberately does not re-ask the 0.7.0 and 0.8.0 reviews' question ("what can
break?"), and it does not re-tread `ROADMAP-STAGE-1.md`, which assessed this
snapshot against the roadmap's Stage 1 and found it complete.

Method: ran the repository's own gates; re-derived the cleaned body of all 500
Manual pages from `snapshot/raw/` and subtracted, word by word, everything that
reaches a chunk; did the same for both compiled `.docx` files against every
provision, unit, container and endnote; then walked the markup that survives
neither. Every count below was run, not reasoned about.

State at time of review: **583 tests pass, both validators clean, and both
corpora re-derive from stored raw with zero files written.**

---

## Verdict

**The text conversion is lossless and the pipeline is robust. Do not go looking
for parser bugs — there are none of consequence to find.**

| Corpus | Word occurrences in source | Unaccounted for in output |
|---|---|---|
| Manual (cleaned bodies, 500 pages) | 313,905 | **1** |
| Trade Marks Act 1995 | 60,123 | **0** |
| Trade Marks Regulations 1995 | 79,648 | **0** |

The single Manual token is a bare `<h?>` reading `2.2` on `TMM/Part23/2` — a
numbered anchor heading with no title text, whose children are addressed
`TMM/Part23/2/2/2/1` and `/2` regardless. Nothing is unaddressable and nothing
is unreadable. The legislation figures are exact: the only material the
`.docx` parser declines to carry is the table of contents (which mirrors the
315/402 `ActHead5` headings exactly, and is documented and counted) and the
page headers and footers (which contain zero words).

So the answer to question 1, for *text*, is: **nothing is dropped.**

The answer to question 2 is where this review has content. **Three things the
source asserts are not carried into the structured layer.** None of them
requires a new regex over prose; two are pure markup reads using machinery the
repository already has, and the third is a URL vocabulary the repository has
already scoped as `TASKS.md` §T12. In descending order of value:

| # | What | Volume | Risk |
|---|---|---|---|
| 1 | Inline emphasis on Manual chunks | 5,670 spans, 428 pages | None — markup, no pattern matching |
| 2 | The full per-page amendment history | 1,539 dropped rows | None — `<time datetime>`, already walked |
| 3 | TimeBase provision hrefs (§T12) | 29 new + 58 upgraded edges | Low — one URL shape, two-entry map |

Everything else I looked for is either already captured, deliberately excluded
with a written argument I agree with, or recoverable from what is stored. Those
are listed in §What is not a problem, because a review that only reports gaps
misrepresents the ratio.

---

## Finding 1 — The Manual's inline emphasis reaches nothing

**5,670 non-empty emphasis spans across 428 of the 500 pages leave no trace in
the snapshot.**

| Element | Spans |
|---|---|
| `<i>` | 2,670 |
| `<strong>` | 2,288 |
| `<u>` | 533 |
| `<em>` | 130 |
| `<sup>` | 26 |
| `<b>` | 23 |

This is the same class of evidence as `chunk.links`, and it is missing for the
same reason `links` was missing before `ingest/0.7.0`: flattening to text is the
correct verbatim reading of the words and destroys everything the markup
asserted around them. `links.py`'s own docstring makes the argument. It applies
here unchanged.

**The asymmetry is the tell.** `provision.units[].emphasis` already exists on
the legislation side, and `SCHEMA.md` argues for it in exactly these terms —
*"recorded rather than interpreted, for the same reason `chunk.links` records an
anchor's offsets rather than deciding what it meant"* — noting that it is where
a defined-terms vocabulary and an instrument-citation layer both come from. 822
legislation units carry the field. Zero Manual chunks do, while the Manual sets
5,670 spans. Nothing in `SCHEMA.md` §What is deliberately absent covers this:
the exclusions there are derivable fields, index state and interpretive fields,
and an emphasis span is none of the three.

### What it is worth, measured

I classified every italic run and then checked it against the case citations the
pipeline already extracts:

- **695 italic runs are instrument titles** — *Trade Marks Act 1995* — which is
  the same convention the OPC uses and the same reason `LEGISLATION_NOTES.md`
  gives for keeping italic spans on units.
- **395 italic runs are case names** in `X v Y` form.
- **437 of the corpus's 522 case-citation positions (83.7%) are immediately
  preceded by an italic run.** 354 distinct citations get a name; **332 of them
  get exactly one name across every occurrence.**

522 rather than the 519 rows in `exports/cases.csv` because this counts every
occurrence and that file counts one row per decision per chunk; its own
`occurrences_in_chunk` column reconciles the two (516 positions at 1, 3 at more).

That last number matters because it contradicts something this repository
currently asserts. `exports/README.md` says:

> **Party names are absent from 501 of 519 positions.** Not a gap this
> repository can close deterministically — it is what an external register is
> for, and the reason this file exists.

The premise is that the only markup evidence is a jade.io anchor whose text
happens to contain the citation, of which there are 18. But the Manual's authors
mark the case name far more often than they hyperlink it — they italicise it,
which is the legal-writing convention — and reading `<i>` is not a different
kind of act from reading `<a href>`. **18 → 437 is available, and it is
markup, not inference.**

Worked example, `TMM/Part19A/1#1`:

```
<i>Self Care IP Holdings Pty Ltd v Allergan Australia Pty Ltd</i> [2023] HCA 8 at [23] (‘Self Care’)
        ^ 55 characters of case name                             ^ the edge the chunk already carries
```

Today the chunk records `CASE/2023/HCA/8` and the string `[2023] HCA 8`. The
name is in `text` and unfindable; the fact that the Manual set it as a name is
gone. And note what follows the citation: `(‘Self Care’)` — the Manual's own
short form. There are **90 such parenthetical short forms, 80 distinct**, and
they include `Cantarella`, which is the roadmap's own Stage 2.4 worked example
of a reference that must resolve to a stable identifier.

There is a second, free result. The 85 positions with *no* preceding italic run
are mostly a citation printed immediately after another citation —
`[1963] HCA 66; (1963) 109 CLR 407`. A citation that the authors did not give a
name to, sitting beside one they did, is precisely the parallel-citation signal
`exports/cases.csv` currently derives from punctuation adjacency alone and uses
to propose its 11 alias pairs. Emphasis corroborates it independently.

### How to do it

Mirror `links.py`. The machinery already exists and needs no change:

```python
# src/tmm_snapshot/emphasis.py — the whole module, essentially
_EMPHASIS = frozenset({"i", "em", "strong", "b", "u", "sup"})

def extract_emphasis(fragment: Tag) -> list[dict]:
    text, spans = flatten_spans(fragment, _EMPHASIS)
    return [
        {"kind": tag.name, "text": text[start:end], "start": start, "end": end}
        for tag, start, end in spans
        if end > start
    ]
```

`page.flatten_spans` already takes the element names to track as an argument and
already guarantees `text[start:end] == flatten_text(element)`; that equality is
already enforced corpus-wide by `validate._link_failures`, and the same check
extends to this field for free.

Three implementation notes, each measured:

- **Record the element name, not a merged weight.** 1,271 of the 5,670 spans are
  co-extensive with another — `<u><i>Trade Marks Act 1995</i></u>` is two spans
  at identical offsets. The legislation side collapses bold+italic into
  `weight: "bold-italic"` because a Word run carries both properties at once;
  HTML nests instead, and merging nested elements into a synthetic weight would
  be a transformation this record cannot afford. Keep them separate and let the
  consumer intersect.
- **Empty spans.** 128 emphasis elements normalise to nothing. `links` keeps
  these as zero-width spans; do the same, or filter them — but decide it
  explicitly rather than inheriting it.
- **Blast radius.** 1,029 of 2,460 chunks would gain the array, across roughly
  428 page files. That is an `EXTRACTOR_VERSION` bump, so it should be batched
  with Finding 2 rather than shipped separately — two corpus-wide rewrites where
  one would do.

`<sup>` deserves a line of its own. `SOURCE_NOTES.md` §26 already establishes
that a `<sup>` in a heading is a footnote marker and never a heading number, and
the chunker acts on that. Recording the 26 spans makes the same fact visible on
the *body* side, which is the half `ROADMAP-STAGE-1.md` flagged as only partly
covered ("a Manual footnote arrives as an ordinary headed chunk with no field
saying it is a footnote"). This does not fully close that, but it puts the
evidence in the record instead of only in the chunker's control flow.

---

## Finding 2 — Three quarters of the Manual's own amendment history is discarded

**The source carries 2,039 amendment rows. The snapshot keeps 500 — the newest
one per page. 1,539 rows are dropped, and 493 of the 500 pages have more than
one.**

| Rows on a page | Pages |
|---|---|
| 1 | 7 |
| 2 | 54 |
| 3 | 141 |
| 4 | 142 |
| 5 | 84 |
| 6 | 39 |
| 7–13 | 33 |

`page._amendment` already walks every row — it iterates the whole table to pick
the maximum date, then returns a single `(date, reason)` pair and lets the rest
fall on the floor. The table is then stripped from the body before chunking, so
the rows exist nowhere in the structured output.

Each dropped row is a date and IP Australia's own words for what changed on it:

| Occurrences | Reason |
|---|---|
| 741 | Update hyperlinks |
| 128 | Page renamed. Links updated. |
| 50 | Hyperlinks updated |
| 45 | Terminology updated to reflect legislative changes. |
| 43 | Accessibility fix – alternative text for images |
| 37 | Part reviewed: Minor content updates, links to legislation updated… |
| 31 | Content updated. |
| 20 | Turn off publish date, add Act/Reg links. |
| 15 | Updated to reflect new legislation - Administrative Review Tribunal Act 2024… |

The history runs from **2021-01-29** to the present.

### Why this one is not cosmetic

`SOURCE_NOTES.md` §5 calls this table *"as close to a change feed as the Manual
has, and the single most useful metadata on the page"*, and then instructs the
parser to capture the most recent row. The instruction is not argued anywhere —
unlike every other exclusion in this repository, which carries a paragraph
explaining itself. I think it is simply an early decision that was never
revisited, and three things now depend on revisiting it:

1. **Git history does not substitute for it.** The repository's premise is that
   `git diff` between crawls is the amendment log — and it is, *from the first
   crawl forward*. This table is the only record of the four years before that,
   and it is per page, dated, and in the publisher's own words. The rows are
   still in `snapshot/raw/`, so nothing is destroyed; they are simply not in the
   layer that downstream consumes.
2. **It is the roadmap's Time module, already written by the publisher.** Stage 0
   lists *"What guidance was current on a specified date?"* as a competency
   question. Stage 9 Level 3 defines impact analysis over amendment. Stage 1's
   unfinished **version register** deliverable is largely this table.
3. **It separates substantive change from tidy-up at scale.** With one row per
   page you can say a page changed recently. With all 2,039 you can say that of
   the last five changes to Part 22.1, four were hyperlink maintenance — which
   is the judgement `SOURCE_NOTES.md` §5 says the field exists to support, and
   it needs the history to make it.

### How to do it

`_amendment` becomes `_amendments`, returning every row it already reads:

```python
"amendments": [
  {"date": "2022-12-19", "reason": "Minor updates."},
  {"date": "2022-04-20", "reason": "Update hyperlinks"},
  {"date": "2021-11-09", "reason": None}
]
```

`last_amended` and `amendment_note` stay exactly as they are and become
derivations of `amendments[0]`, so nothing downstream breaks and the two
representations cannot disagree. Sort descending by date, ties broken by
document order — which is what `_amendment` already does to pick its maximum, so
byte-stability comes for free. A blank reason stays `null`; §5 already notes the
cell can be empty and that a reason may span several `<p>`s.

Roughly 493 page files change. Batch with Finding 1.

---

## Finding 3 — `TASKS.md` §T12, with the counts it asked for

T12 was opened by the 0.7.0 review and says: *raise the scope question first,
with counts, and decide the two questions in `SCHEMA.md` before touching
`citations.py`.* Here are the counts, and my answer to both questions.

**Decision 1 — TimeBase ids name a provision. Take them.**

The Manual links provisions to TimeBase in a fully regular form:
`?id=tmact:217a`, `?id=tmreg:21.11a`, `?id=tmreg:sch9`. 101 anchors, 44 distinct
URLs. Reading them with the same grammar `_href_edges` already applies to
AustLII:

| Outcome | Edges |
|---|---|
| New edges the corpus does not have at all | **29** |
| `regex`/`default` → `href` | 51 |
| `regex`/`explicit` → `href` | 5 |
| `regex`/`ambiguous` → `href` | **2** |
| Already an `href` edge from an AustLII link on the same chunk | 13 |

That last row is the check that the mapping is right: 13 provisions are linked
to *both* AustLII and TimeBase in the same passage, and the two URL vocabularies
agree on the provision in all 13. The two `ambiguous` edges are the strongest
single argument — those are passages the schema says never to hydrate from,
where the Manual's authors had hyperlinked the answer all along.

Part 61.2 is the worked case `SOURCE_NOTES.md` §29 already describes: three
references to section 217A, two hyperlinked, all three currently recorded as a
guess.

The whole change is a regex and a two-entry map beside `AUSTLII_INSTRUMENTS`:

```python
TIMEBASE_INSTRUMENTS = {"tmact": "TMA1995", "tmreg": "TMR1995"}
_TIMEBASE = re.compile(r"timebase\.com\.au/IPAust/index\.cfm\?id="
                       r"(?P<db>tmact|tmreg):(?P<node>[0-9a-z.]+)", re.I)
```

`_canonical_address` and the `sch` handling already do the rest. Follow
`UnknownInstrument`'s precedent and raise on an unseen `db` fragment rather than
dropping the edge.

The `SCHEMA.md` change T12 point 2 correctly insists on: state that
`extraction: "href"` means *the Manual's authors hyperlinked this provision*,
and list both URL vocabularies that count as evidence for it. Since
`ingest/0.7.0` every href is verbatim in `chunk.links`, so a consumer who wants
only AustLII-backed edges can still get them — but they must be told the filter
changed.

**Decision 2 — Federal Register ids name an instrument. Decline them.**

T12 proposes using the 475 Federal Register anchors as evidence about *which
instrument* an adjacent reference means, lifting `default` to `explicit`. **I
recommend against it, and the counts are why:** those 475 anchors resolve to
only **9 distinct URLs**, and the two commonest are
`C2004A04969/latest/text` (the Act) and `F1996B00084/latest/text` (the
Regulations) — which appear *together*, as boilerplate, on the Relevant
Legislation page of nearly every Part. An href-derived scope signal there would
put both instruments in scope on the same page, every time. `SOURCE_NOTES.md`
§21 already settled what that means: naming the Act and the Regulations together
is not an ambiguity, and treating it as one is what made 39% of the corpus's
regex edges ambiguous before it was fixed. This would reintroduce the same noise
through a different door, for a signal that is boilerplate rather than
authorial.

Worth recording separately, though: `C2004A04969` is the `title_id` in
`snapshot/legislation/TMA1995/instrument.json`. The Manual and the legislation
snapshot independently agree on the instrument's permanent Register identifier.
That is a free cross-corpus consistency check, not an edge.

---

## Finding 4 (small) — 23 hyperlinked references to statutory containers

23 AustLII anchors point at `/consol_act/tma1995121/` with no node — the
instrument's contents page — and carry anchor text naming a container: *"Part
16"*, *"Division 2 of Part 8"*, *"Schedule 7"*. They reach no edge, because
`_AUSTLII_PROVISION` requires a node segment.

`snapshot/legislation/*/contents.json` addresses exactly these:
`TMA1995/pt16`, `TMA1995/pt8/div2`, `TMR1995/sch7`. So there is a resolution
target and a hyperlink asserting the reference.

Low volume, and I raise it as optional. If it is done, **read the container only
from the anchor's own words on such a link, never from prose.** `SOURCE_NOTES.md`
§30 records that the Manual writes "part" for two different things, and a prose
rule for *"Part 16 of the Act"* would collide with the Manual's own Part
numbering across the whole corpus. That is the regex whack-a-mole to avoid; the
23 hyperlinked cases are not.

---

## What is not a problem

Checked, and either correct or correctly excluded. Recorded so the next review
does not spend the time again.

**Legislation extraction is complete.** Every `w:pStyle` in both documents maps
to a unit, a container, a provision heading, an endnote or the TOC. The TOC drop
is right and is already argued and counted (315 `TOC5` against 315 `ActHead5` in
the Act — carrying it would put every heading in the corpus twice). Headers and
footers carry zero words. All 17 tables in the two documents are accounted for:
10 as unit tables, 7 in `endnotes.json`. 189 of 189 definitions carry their
defined term as a leading bold-italic span and are addressed by it.

**Nothing is silently dropped from the citation layer.** The pipeline drops
edges it cannot resolve — 8 bare `part N.M` mentions and 44 internal hrefs whose
target is not in the nav — but in every case the evidence survives: the words
are in `chunk.text` and the href is verbatim in `chunk.links`. Dropping the
*edge* while keeping the *evidence* is the right call and is already argued in
`SCHEMA.md`. The 792 anchors that reach neither `provisions` nor `internal_refs`
are likewise all present in `links`.

**Page-level metadata is complete.** Everything inside `<main>` and outside the
body field is either captured (`Date Published`, the amendment table) or
redundant with the sitemap (`div.nested-nav`, which is a breadcrumb). There is
no unread metadata block.

**These should not be built here**, and the repository is right to say so:
sentence segmentation (offsets into an immutable `chunk.text`, downstream — the
argument in `ROADMAP-STAGE-1.md` is correct), Endnote 4 amendment edges
(`TASKS.md` §T14 — the provision column holds `Div 2 of Part 3` and *Reader's
Guide*, and a resolver that handles 60% is the silently-wrong record rule 3
exists to prevent), image OCR (§T11), party-name *resolution* as opposed to
recording, short-form resolution, and any keyphrase, concept or modality field.

**Point-in-time compilations (§T15) remain the one open layout question** and
this review does not change that assessment. It gates the 76 unresolved
provision edges, most of which are superseded numbering the Manual's annexes
discuss.

---

## Recommended order

1. **Findings 1 and 2 together, as one `ingest/0.10.0`.** Both are markup or
   attribute reads with no pattern matching over prose, both are byte-stable by
   construction, and both rewrite most page files — so they should rewrite them
   once. Fixtures: a page with nested `<u><i>`, a page with a `<sup>` footnote
   marker, and a page with a 13-row amendment table.
2. **Finding 3, as a separate change**, because it alters what
   `extraction: "href"` asserts and that belongs in its own diff with its own
   `SCHEMA.md` paragraph. Decline the Federal Register half.
3. **Correct `exports/README.md`** once Finding 1 lands, and regenerate
   `cases.csv` — `parties` goes from 18 rows to roughly 437, which is the
   difference between a column that exists and a column that is usable as a join
   key against an external register.
4. **Finding 4 only if it is free** once Finding 3's plumbing is in place.

None of this changes a module boundary in `ARCHITECTURE.md`. Finding 1 adds one
module in the shape of `links.py`; Finding 2 widens one return type inside
`page.py`; Finding 3 adds a map and a regex to `citations.py`.

---

## In one paragraph

The conversion is sound. 313,905 words of Manual prose and 139,771 words of
legislation reach the structured layer with one token unaccounted for between
them, both corpora re-derive from stored raw with zero files written, and every
exclusion in the legislation half is argued and counted. What is missing is not
text but *markup evidence*: the Manual italicises its case names 437 times and
the snapshot cannot see it, it bolds and underlines 2,844 more runs and the
snapshot cannot see those either, and it publishes 2,039 dated amendment rows of
which the snapshot keeps 500. All three are readable by the same means the
repository already uses for hyperlinks and `<time>` attributes — no new
inference, no pattern matching over meaning, no brittleness. They are worth
taking because the ontology work downstream needs exactly the two things they
supply: a resolvable identity for the 411 cited decisions, and a time axis for
the guidance.
