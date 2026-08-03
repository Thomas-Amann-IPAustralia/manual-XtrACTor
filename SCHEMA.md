# Data contract

The machine-checkable version is `schema/page.schema.json` and
`schema/chunk.schema.json`. Output must validate against them; CI enforces it.
This document explains what each field is for, because a schema tells you the
shape and not the reason.

## Two corpora

This contract covers the Manual: a **page** record and the **chunk** records cut
from it, in `schema/page.schema.json` and `schema/chunk.schema.json`.

The legislation snapshot has its own two, in `schema/instrument.schema.json` and
`schema/provision.schema.json`, described in §The legislation records below.
They are separate files rather than an extension of these because a compiled Act
is not a web page and forcing one shape over both would mean nullable fields
everywhere and a validator that could not tell a missing value from an
inapplicable one.

What the two corpora *do* share is the provision id — see §Citations, and
`LEGISLATION_NOTES.md` §8. That is the join, and it is the only thing either
schema assumes about the other.

## Two levels

A **page** is one URL on the Manual site. A **chunk** is one retrievable passage
cut from it — normally the prose under a single heading.

Facts true of the page (its URL, title, publication and amendment dates) live on
the page record, once. Facts true of a passage live on the chunk. Part 22.1
yields one page record and several chunks; copying the page's amendment date onto
each chunk would store the same fact three times and give three chances for it to
drift.

On disk they share a file — `{"page": {...}, "chunks": [...]}` — because they are
written and reviewed together. They are still two records.

---

## The page record

**`page_ref`** — stable address, e.g. `TMM/Part22/1`. Derived from the Part and
the leading number in the nav title. This is the identity of the page across
crawls, and the filename is derived from it.

**`part_id`** — `Part22`, `Part32B`. **From the navigation tree only.** Never from
the URL. `SOURCE_NOTES.md` §2 explains what goes wrong otherwise, and it is the
single worst failure available in this codebase.

**`url`**, **`nav_title`**, **`h1`** — where it came from and what it calls itself.
`url` is what a human clicks to verify a citation, so it must be exact.

**`content_hash`** — SHA-256 of the normalised page body. The cheap gate: hash
matches, skip parsing entirely. Normalise before hashing — Drupal emits
per-request tokens, so raw HTML differs on every fetch even when nothing changed.

**`date_published`** — from the page's own field.

**`last_amended`**, **`amendment_note`** — the most recent row of the page's
`Amended Reasons` table, in IP Australia's own words: *"Minor updates."*, *"Update
hyperlinks"*. Paired with a hash diff this separates substantive practice change
from cosmetic edits, which is the judgement a human reviewer needs to make on
every crawl PR. It is the most valuable metadata on the page.

**`amendments`** — *all* of that table, newest first, as
`{"date", "reason"}`. 2,039 rows across the 500 pages, reaching back to 2021;
493 pages carry more than one and one carries thirteen. `last_amended` and
`amendment_note` are `amendments[0]`'s two fields and are kept because they are
what most consumers want and what the crawler's skip logic compares — but they
are *derived* from this array in `parse_page`, never parsed from the table a
second time, and `validate._amendment_failures` pins the agreement over the
whole snapshot. Two readings of one table is how the two come to disagree.

This is a deliberate exception to §What is deliberately absent's rule against
storing a derivation, and the exception is bounded: the derivation is written
once, at the point the array is built, and checked corpus-wide.

Until `ingest/0.10.0` the parser read every row and returned only the newest,
so three quarters of the publisher's own change log stopped at the parser. Two
things depend on the rest of it. **A time axis**: *what did this page say on a
given date*, and *were its last five changes substantive or hyperlink
maintenance* — the judgement the paragraph above says the field exists to
support, which needs the history to make. And **the period before the first
crawl**: after that `git` is the amendment log, which is the whole premise of
this repository, but git cannot reach back before it started and this table
can.

Order is newest-first with ties in document order. Same-day rows have no other
key to separate them, so any sort that reordered a tie would rewrite the file
on alternate runs — rule 2. `reverse=True` on a stable sort inverts ties, which
is why `_amendments` negates the date instead.

**`archived`** — the page carries the Manual's own *"This page has been
archived."* banner. It keeps its nav entry, its title and its whole `Amended
Reasons` table, and has had its prose removed, so it yields no chunks: expect
`chunks: []` and a `content_hash` over an empty body. `SOURCE_NOTES.md` §15.

Three states, and consumers need all three kept apart. `archived` is the Manual
saying a page is no longer current. `run.unreachable` in `manifest.json` is a
nav entry the site would not serve (§14). Retirement — the file moving to
`pages/_retired/` — is the page leaving the nav altogether. A page can be
archived for years while staying exactly where it is in the tree, and reading
that as removal would misreport it.

**`images`** — every image in the page's content, `{"src", "alt"}`, sorted and
de-duplicated. Usually empty; 39 pages have one or more, and on eight of those
the image *is* the page — a flowchart, a cross-search class table, the format
of a summons. `SOURCE_NOTES.md` §16.

This is what makes those eight legible. They yield no chunks, because there is
no text in them to chunk, so a consumer reading page files alone used to see
`"chunks": []` and have no way to tell them from a blank page. So there is a
**fourth** state to keep apart from the three above: `chunks: []` with a
non-empty `images` is a page whose content this pipeline cannot render as
text — not a page the Manual has withdrawn, and not one it never wrote.

`src` is verbatim, root-relative as the source writes it; resolving it against
the site root is the consumer's join. `alt` is `null` when the element carried
no attribute and `""` when it carried an empty one — HTML's way of saying
"decorative". Do not collapse those: *"Accessibility fix – alternative text for
images"* is one of the Manual's own amendment reasons, on 28 pages, and the
difference between the two values is its entire content.

The image bytes are **not** stored. For those eight pages the snapshot records
that the Manual said something in a picture, and where the picture was, but not
what it said. That is a known gap, not an oversight — see `TASKS.md` §T11.

**`printed_page_ref`** — the address the page's own `<h1>` prints, on the two
pages where that is not its `page_ref`, and `null` on the other 498.

`page_ref` comes from the nav and must: the nav is the only reliable source of
Part membership and the only thing keeping two colliding slugs apart. But the
page prints an address too, and on two of them the two disagree —
`TMM/Part20/3` prints *"Part 20.2. Definition of sign"* while `TMM/Part20/2`
prints *"20.2. Background to definition of a trade mark"*, so **two pages claim
20.2**. That is the Manual's defect, not ours, and rule 1 says to record an
ambiguity rather than resolve it. The nav still decides the address; this says
the page disagrees. Without it a bare *"part 20.2"* elsewhere resolves to one
of them with nothing anywhere suggesting it might have meant the other.

The second is milder: Part 1's introduction is *"Part 1. Introduction"* in the
nav, which qualifies down to no page-local address at all, so its `page_ref` is
the slug form — while its `<h1>` prints *"Part 1.1."* and `TMM/Part1/1` is
claimed by nobody. `SOURCE_NOTES.md` §31.

**`crawled_at`** — when *this version of the page* was first seen. Not when the
crawler last looked: that is a property of the run and lives in
`manifest.json`.

The distinction is not pedantry, it is rule 2. A field that moved on every
crawl would rewrite all 502 page files every week and bury the amendment log in
noise. So it is written once and carried forward unchanged for as long as
everything else in the record is unchanged; only a crawl that actually altered
the page moves it. Read alongside `last_amended` it gives you both dates that
matter — when IP Australia says they changed the page, and when we first saw
that they had.

**`extractor_version`** — which version of this pipeline produced the record. When
a parser bug is fixed, this tells you which snapshots need rebuilding from
`raw/`.

Because it sits in the record, a bump to it changes every page file on the next
run whether or not the Manual moved. That is intended — it is the signal that
the corpus was rebuilt — but it means bumping it is a decision about a
thousand-file diff, not a version-string tidy-up.

---

## The chunk record

**`chunk_ref`** — the address, and the id. `TMM/Part22/1/1/2` means Part 22,
page 1, heading 1.2. A person can read it and find the source.

Do not add a separate sequential id. A serial number is a citation that breaks
silently: insert a paragraph upstream and `chunk-047` now points at different
text, with nothing to detect it. An address survives where a counter does not.

Three forms, strongest first:

| Form | Example | Chunks |
|---|---|---|
| The heading's own number | `TMM/Part22/1/1/2` | 1,166 |
| A slug of the heading's text | `TMM/Part14/x-…-a13/adhesive` | 796 |
| Position on the page | `TMM/Part47/1#1` | 498 |

**The slug form** covers headings the Manual writes but does not number —
*Adhesive*, *Applications for services*, *Disclaimer*. It replaced positional
addressing for these in `ingest/0.4.0`, and `SOURCE_NOTES.md` §18 has the
measurements. The short version: 627 of those 777 are one page, the Part 14
Annex A13 glossary, which the Manual itself calls *non-exhaustive* — so
inserting a single term used to repoint every citation after it, silently. A
slug is unmoved by an insertion, because the new term simply gets its own.

What a slug does not survive is the heading being reworded. That is the trade
and it is the right way round: a reworded heading changes the chunk text too,
so it lands in the diff — where a shifted ordinal landed nowhere. Two headings
that slug alike on one page raise `ChunkRefCollision` rather than being
resolved with a counter; none do today.

**The positional form** is left for the prose above a page's first heading,
which has no heading to be named by. It is not the exposure it looks like: a
section with no heading *is* the page preamble, so it is the first section by
construction and nothing can be inserted ahead of it. 496 of the 498 sit at
`#1` for that reason, and a test pins it.

The other two are Part 29.9, where the Manual titles both worked examples
`XYZ Company` and so has given them nothing to tell each other apart by. Those
genuinely can shift, and there is no address available that would not — see
`_repeated_labels`. Two chunks in 2,460 is the whole of the exposure.

**`page_ref`** — the join back to the page.

**`text`** — the words, verbatim, whitespace-normalised and nothing else. No
summarising, no reordering, no expanding abbreviations. This is the only string
the system is ever permitted to quote to an applicant or an examiner.

**`heading_path`** — the full breadcrumb, outermost first:

```json
[
  "Part 22 Section 41 - Capable of Distinguishing",
  "22.1. Registrability under section 41 of the Trade Marks Act 1995",
  "1.2 Intellectual Property Laws Amendment (Raising the Bar) Act 2012"
]
```

Without this a chunk is uninterpretable once separated from its page. Two
passages about capacity to distinguish exist in Part 32A (plants) and Part 32B
(wines) and say different things; the ancestry is what tells them apart. The leaf
heading is the last element — do not store it again separately.

**`ordinal`** — position on the page. Gives previous and next by arithmetic
instead of stored pointers.

**`content_hash`** — SHA-256 of `text`. Drives selective re-processing. Without
it, every downstream consumer reprocesses the entire corpus on every crawl to
catch three edited sentences.

**`kind`** — `body`, `landing`, `annex`. Inherited from the page's nav entry:
`landing` marks *Relevant Legislation* pages, which are mappings rather than
prose and should usually be excluded from applicant-facing answers.

The schema's enum also lists `note` and `table`, and **neither is emitted**.
That is deliberate, and the reason is worth stating because the obvious change
is the wrong one. `kind` answers *"what sort of page is this passage from?"*;
whether a passage contains a table answers *"what is in it?"* Those are two
axes, and a field that tries to carry both has to lose one — a table on an
annex page would have to stop being marked as annex content. So a chunk with a
table is found by `tables != []`, which is also strictly more precise: it
distinguishes a chunk that is only a table from one that is prose *and* a
table, which a single `kind` value never could.

**`heading_source`** — how the leaf of `heading_path` was found, and the only
field in this schema recording an inference.

| Value | Chunks | Means |
|---|---|---|
| `"markup"` | 1,473 | An `<h2>`–`<h4>`. The Manual asserted the boundary. |
| `"emphasis"` | 491 | A bold paragraph numbered against the page's own number, promoted to a heading. |
| `null` | 496 | The prose above a page's first heading. |

`emphasis` exists because 456 of the Manual's numbered subsections across 88
pages are set as `<p><strong>3.1 …</strong></p>` rather than as headings.
Cutting on markup alone left 39% of the corpus text with no heading at all and
Part 10.3 — which prints 36 numbered subsections — as nine addressless chunks.

The promotion is fenced by the Manual's own addressing, not by typography: the
paragraph must be wholly bold *and* open with a number that extends this page's
number. Across the corpus that admits 471 candidates and rejects exactly one.
`SOURCE_NOTES.md` §25 has the rule and its measurements.

**Read this field before trusting a boundary.** A consumer that wants strictly
what the Manual marked up filters to `markup`; one that wants the structure the
Manual *prints* takes both. Neither has to guess which it is getting, and that
is the whole reason the field is here rather than the inference being silent.

**`headings`** — one entry per heading in `heading_path[2:]`, outermost first,
carrying the three things about an ancestor that a list of strings cannot say.

```json
[
  {"level": 2, "source": "markup",   "ref": null},
  {"level": 3, "source": "markup",   "ref": "TMM/Part22/1/1"},
  {"level": 4, "source": "emphasis", "ref": "TMM/Part22/1/1/2"}
]
```

**`level`** is depth on one scale for both kinds of heading: the digit of an
`<h2>`–`<h4>`, and for an inferred heading the number of components in the
number the Manual printed — `3.1` sits where an `<h3>` sits and `3.1.1` where an
`<h4>` does. It is what the chunker keys ancestry on, and without it a consumer
cannot see the nesting that was read, which matters on the three pages where
the Manual's numbering and its markup disagree (`SOURCE_NOTES.md` §28).

**`source`** is `heading_source`, for every ancestor rather than the leaf alone.
One chunk in the corpus is cut on an `<h3>` while sitting under a heading
promoted from a bold paragraph, so filtering to `heading_source == "markup"`
does not by itself give you an ancestry the Manual marked up.

**`ref`** is the chunk holding that heading's own section, and `null` where it
holds none — the ordinary case for a heading whose content lives entirely in
its subsections (`SOURCE_NOTES.md` §27). 836 of the corpus's 3,028 entries are
null, and they sit on 831 chunks. **This is what makes the heading tree addressable:** the parent of a
chunk is the last entry before it with a `ref`, and the page where there is
none. Before `ingest/0.8.0` the only route to an ancestor was to match its text
within the page — the fragile join `chunk_ref` exists to replace. Where a
section was long enough to split, this is its opening fragment, which is where
a link to the heading is aimed.

**The ancestor's text is deliberately not repeated here.** It is
`heading_path[2:][i]`. Storing it twice would give two representations of one
fact and a way for them to disagree, so instead the correspondence is checked:
`validate._heading_failures` asserts one entry per heading, in order, with the
leaf agreeing with `heading_source`, over the whole snapshot. Same arrangement
as `blocks` joining back to `text`.

**`fragment`** — present only when an over-long section had to be split on
paragraph boundaries. `{"index": 1, "count": 2}`.

**`blocks`** — the paragraphs and list items `text` was flattened from, in
document order. 12,521 of them across 2,460 chunks, so unlike `tables` this is
populated nearly everywhere.

The argument is the same one `tables` makes, applied to the prose. `text` joins
a section's blocks with single spaces, which is the correct verbatim reading and
leaves nothing to say where one ended. At the length the Manual writes that is
not a cosmetic loss: Part 61.3's ten-item list of documents exempt from public
inspection arrives as one run-on line, the source's own semicolons give out
halfway down it, and a ten-item list of statutory exceptions and a single
paragraph are the same string.

```json
[
  {"kind": "paragraph", "text": "A trade mark may also simply include…"},
  {"kind": "list_item", "text": "a document:", "depth": 1},
  {"kind": "list_item", "text": "whose production the Registrar…", "depth": 2}
]
```

`kind` is `paragraph`, `list_item`, `table`, `heading`, `image` or `text`, read
off the element name — `heading` is an `<h5>` or `<h6>`, since `<h2>`–`<h4>` are
chunk boundaries and `<h1>` is the page title, and `text` is inline content
Drupal left loose in a layout `div`. `depth` rides on a list item and counts the
lists enclosing it, from 1; the corpus nests three deep.

**`image` is the only kind with no `text`,** and carries `src` plus `alt` where
the Manual wrote one — which across 169 images it never has. The bytes are not
in the snapshot; the block says *an image sat here*, which is the one thing
`PageRecord.images` cannot say. 93 images have a position this way. The other 76
are in sections with no words, and a chunk needs text to exist, so they stay
recorded at page level only. `SOURCE_NOTES.md` §24.

**Joining every block's `text` with single spaces reproduces `text` exactly.**
Blocks with no `text` — images — are stepped over, which is why they carry no
empty string: one would put a stray space into the join.
That is the contract, it is enforced in `validate.py` over the whole snapshot,
and it is what keeps `blocks` from drifting into a second, differently worded
copy of the chunk. A list item holds its own words only — the items nested under
it are their own blocks and are not repeated in their parent, or the blocks
would add up to more than the chunk. `SOURCE_NOTES.md` §19.

**`links`** — every hyperlink in the chunk, in document order, with the offsets
into `text` at which the Manual set it. 2,218 of them across 759 chunks on 423
pages. `SOURCE_NOTES.md` §29.

```json
{
  "href": "http://www.timebase.com.au/IPAust/index.cfm?id=tmact:217a",
  "text": "section 217A",
  "start": 260,
  "end": 272
}
```

`text` is the words with the markup gone, and the markup that went included
every `<a>` on the page. `provisions` and `internal_refs` each kept the part of
an anchor they are about — the provision it names, the page it resolves to —
deduplicated, sorted, and with the URL and the position discarded. **792 of the
2,218 reached neither**: every legislation.gov.au and TimeBase link to the Acts,
every jade.io link to a decision, and 47 internal links naming Manual pages that
are not in the nav. Part 61.2 links *section 217A* to TimeBase rather than to
AustLII, which is why the passage records that citation as a `default` guess
from its prose while the authors' own statement of it sat in an href nobody was
keeping.

**`text[start:end]` is the link's own words.** That equality is the contract and
`validate.py` checks it over every link in the snapshot. Offsets rather than a
search for the words: 91 anchors share their words with another anchor in the
same chunk, and matching them up afterwards would be a guess between the two.
`start == end` for the five anchors in the corpus that hold no words at all —
one of them is where `TMA1995/s42` on Part 32A.1 comes from — and records the
point they sat at.

**`emphasis`** — every italic, bold, underlined and superscript stretch of the
chunk, in document order, with the offsets into `text` at which the Manual set
it. 5,146 spans across 1,029 chunks.

```json
{ "kind": "i", "text": "Cantarella Bros Pty Ltd v Modena Trading Pty Ltd",
  "start": 137, "end": 185 }
```

The same field the legislation half has carried since `legislation/0.1.0` as
`provision.units[].emphasis`, and the same argument `links` makes: flattening
to `text` is the correct verbatim reading of the words and destroys everything
the markup asserted around them. Reading `<i>` is not a different kind of act
from reading `<a href>` — both are the authors marking a span.

What rides on it, neither of which is asserted here:

- **The Manual italicises case names.** 437 of the corpus's 522 case-citation
  positions are immediately preceded by an italic run holding the decision's
  parties, and 332 distinct citations get exactly one such name across every
  occurrence. Before `ingest/0.10.0` the only markup evidence for a party name
  was a jade.io anchor whose own text contained the citation, of which there
  are 18.
- **It italicises instrument titles**, 695 times — the `certainty: "explicit"`
  evidence of `citations.py`, written in markup rather than in prose.

That a name sits beside a citation is an adjacency a consumer can walk.
Asserting the two belong to each other is a merge, and merges belong
downstream — §What is deliberately absent.

`kind` is the element verbatim, and the Manual's choice between `<i>` and
`<em>`, or `<b>` and `<strong>`, is not normalised: which one the CMS emitted
is a fact about the markup, and this layer has nowhere to put the claim that
the two mean the same thing. `sup` is a footnote marker — `SOURCE_NOTES.md` §26
establishes that a superscript is never a heading number, a fact the chunker
has always acted on and never recorded.

**One record per element, never a merged weight.** 1,271 spans are co-extensive
with another, because HTML nests where Word does not:
`<u><i>Trade Marks Act 1995</i></u>` is one stretch of words carrying two
assertions. The legislation side's `weight: "bold-italic"` exists only because
a Word run carries both properties on one element. A consumer wanting the
intersection can take it from two records; it cannot un-take it from one.

Not deduplicated and not sorted, for the reasons `links` is neither — including
the 193 spans where the CMS nested an element directly inside an identical one
(`<i><i>x</i></i>`, `SOURCE_NOTES.md` §4) and two records therefore share a
`kind` *and* their offsets. **A consumer counting spans should deduplicate on
`(kind, start, end)`**, which gives 4,953 of the 5,146.

Empty spans *are* dropped, which is the one place this and `links` differ: an
anchor with no words still records a place the Manual put a link, while an
`<i>` around nothing asserts nothing about any words.

**524 spans reach no chunk**, and they are this field's gap — the same gap
`links` has. Emphasis inside an `<h2>`–`<h4>` is inside a heading, and a
heading's words reach the snapshot as a `heading_path` string with no structure
to hang an offset on. Nearly all of them are the bold numbered paragraphs
`_inferred_heading` promotes (`SOURCE_NOTES.md` §25), so the emphasis that was
lost is the emphasis the chunker already read as structure.

`href` is verbatim, root-relative for a Manual page and absolute otherwise.
Resolving it, against the site root or against the nav, is a join the consumer
does. **Not deduplicated:** two links to one target are two links, which is the
difference from `internal_refs` and follows from what the field is for.

The five anchors the field does not reach are inside `<h2>`–`<h4>` headings that
open subsections, whose words reach the snapshot as a `heading_path` string with
nothing to hang an offset on. They are listed page by page in `SOURCE_NOTES.md`
§29 rather than left to be discovered.

**`tables`** — the grid of every table in the chunk, in document order. Empty
on the great majority of chunks; 121 tables live across 45 pages, and some of
those pages are essentially nothing else. `SOURCE_NOTES.md` §17.

`text` renders a table as a run of cell text — *"Owner Name Address Description
Individual Surname + Given name/s…"* — which is the right verbatim reading and
tells you nothing about which cell sat under which column. Both are kept:
`text` for quoting, `tables` for structure.

```json
{
  "ordinal": 1,
  "rows": 7,
  "columns": 4,
  "header_row": null,
  "cells": [
    [{"text": "Owner"}, {"text": "Name"}],
    [{"text": "Applicant details", "colspan": 2}]
  ]
}
```

**`header_row`** indexes into `cells`; it never copies the row out. It is set
only where the markup says so — a `<thead>` holding one row, or a first row of
all `<th>` — which is true of 2 of the Manual's 121 tables. The other 119 have
a first row that reads exactly like a header and declares nothing, and this
pipeline will not promote it: that is an inference about meaning, and rule 1
forbids it. Null means *the source did not say*, not *there is no header*.

`columns` counts spanned width, so a two-cell row whose first cell is
`colspan="2"` is three columns wide. Spans are recorded on the cell and never
expanded into the positions they cover — which cells a merge occupies is a
rendering question, and answering it means writing cells the Manual never
wrote. Ragged rows are stored ragged for the same reason. A cell holding only
an image has `"text": ""`; the image is on the page record.

---

## Citations

The reason this repo produces structured output rather than plain text.

### `provisions`

Statutory references — Act sections and Regulations.

```json
{
  "id": "TMA1995/s44(3)(a)",
  "extraction": "href",
  "certainty": "explicit",
  "mention": "subsection 44(3)(a)"
}
```

**`id`** carries everything derivable. `TMA1995/s44(3)(a)` yields instrument
`TMA1995` and root `TMA1995/s44` by parsing. Derive them where you need them —
generated columns, a helper function — rather than storing three fields that can
disagree.

**`id`** names a section, a regulation or a Schedule — `TMR1995/sch2`, the same
segment the legislation snapshot gives that Schedule. Two invariants hold over
it and `validate.py` enforces both, because an id that names nothing is worse
than an absent edge: the instrument must be able to hold that *kind* of
provision (`TMR1995/s224` is not a thing), and it must be able to express that
*number* (`TMA1995/s4.7` is not either — the Act numbers none of its sections
with a dot, the Regulations number all of theirs with one). A regex edge failing
either is dropped at extraction. `SOURCE_NOTES.md` §§20, 32.

**`extraction`** — `href` or `regex`, and the distinction is load-bearing.
The Manual hyperlinks Act sections to AustLII, so an `href` edge is the authors
telling you what the paragraph is about. A `regex` edge is our inference from
seeing "section 41" in prose. Both are useful; only one is near-certain. Collapse
them into one field and you lose the only signal separating them.

**`certainty`** — for regex edges. `explicit` means the instrument was named
adjacent. `default` means a bare "section N", assumed to be the Trade Marks Act
by convention. `ambiguous` means several instruments *of that kind* are in scope
and we cannot tell which.

"Of that kind" is doing work. An Act holds sections and Regulations hold
regulations, so the reference's own word already fixes which of the two it
addresses, and naming both — which nearly every page does, since the Relevant
Legislation preamble lists them together — is not an ambiguity. Counting them
as one put 39% of regex edges in a bucket nothing may hydrate from.
`SOURCE_NOTES.md` §21.

The same fact is an invariant on `id`: `TMR1995/s224` names a section of the
Regulations, and there is no such thing. `validate.py` rejects it.
`SOURCE_NOTES.md` §20.

That last value exists because of a real, unfixable case: Part 22.1 says
*"considered under section 26 of the Act"* where "the Act" means the 1955 Act from
the previous sentence. Read alone it looks like the 1995 Act. No regex resolves
this, and rule 1 forbids a model. So we record the doubt and let downstream use
it — ambiguous edges feed a human review queue and nothing else.

The principle generalises: **a wrong edge that knows it might be wrong is
survivable; a wrong edge that looks certain is not.**

**`mention`** — the surface form. Debugging aid while the extractor is immature.
Droppable later; kept optional for that reason.

### `cases`

Court and tribunal decisions, in two styles: neutral (`[2018] FCAFC 109`) and
reported (`(1954) 71 RPC 43`). Capture citation and canonical id. Party names are
unreliable to extract and nothing needs them yet.

### `internal_refs`

Cross references to other Manual pages, resolved to `page_ref` or `chunk_ref`
through the sitemap, and **carrying how each was found**. If a reference does
not resolve — a bare "see part 22.15.7" pointing at something that no longer
exists — **drop it**. An unresolvable string in this field is worse than an
absent one, because a consumer will try to follow it.

```json
{ "ref": "TMM/Part12/9", "extraction": "href", "mention": "9. Divisional Applications" }
{ "ref": "TMM/Part22/15", "extraction": "regex", "certainty": "default",
  "mention": "part 22.15.7" }
```

**`extraction` is the same distinction `provisions` draws, and it is
load-bearing for the same reason.** An href is the Manual's authors linking one
passage to another; a regex edge is our reading of *"see part 22.15.7"* in the
prose. 378 of the corpus's 418 edges are the first and 40 are the second. Until
`ingest/0.8.0` this field was an array of bare strings and the two were
indistinguishable — the rule this repository applies to statute, it was not
applying to itself.

**`certainty`**, for regex edges, means what it means on a provision.

| Value | Edges | Means |
|---|---|---|
| `default` | 38 | Read by the convention of `SOURCE_NOTES.md` §8 — `part 22.15.7` names Part 22 — with nothing competing. |
| `explicit` | 2 | The Manual settled it in its own words: *"part 2.3.1(c) **of this chapter**"* says the digits are this Part's address, not Part 2's. |
| `ambiguous` | 0 | Both readings resolve and nothing chooses. The conventional target is kept, because the record has nowhere else to put one, and the flag beside it is what stops it being read as a fact. |

That `ambiguous` is empty is a measurement, not an assumption: every bare
reference in the corpus either names its own Part, names a Part no local
reading competes with, or is settled by the Manual's own qualifier — and the
one place two page-level readings did compete, Part 9.3's *"Part 5.2.2.6"*, the
authors had also hyperlinked, so the href edge carried it. `SOURCE_NOTES.md`
§30 has the rule and what it was found by.

**Chunk-level refs come from a link's `#fragment`**, which is the slug of the
target heading and opens with the number the Manual prints. 28 of the 418 refs
address a chunk; the rest address a page, either because the anchor named no
heading number (the Part 5 glossary anchors on single letters) or because the
heading it named is no longer there. That second case **coarsens to the page
rather than dropping** — the page half was established by URL and is still
true. Settling any of this needs the whole snapshot, which is why it happens
once per run rather than per chunk: `ARCHITECTURE.md` §Two phases and
§Settling, `SOURCE_NOTES.md` §22.

**A reference to the page it sits on is kept, not filtered.** 25 chunks carry
one. They are not noise and not a bug: they are the Manual pointing at another
part of the same page — *"in light of paragraph 4.3"*, the A–Z index at the top
of the INN-stems annex, the "refer to the comments above" in Part 21.3. That
the target is a sibling chunk rather than another page is precisely what a
retrieval layer needs in order to offer the right next passage, and it is only
knowable because the ref was kept: by the time the text is flattened the anchor
is gone and nothing downstream can recover it.

**One record per target.** A passage that both links to a page and names it in
prose asserts one edge, and the hyperlink is the stronger evidence for it — the
same collapse `provisions` makes, with the same precedence. This is where the
Part 9.3 case above resolves itself.

---

## What is deliberately absent

**Derivable fields.** `part_id` on the chunk (split `chunk_ref`), `heading`
(last element of `heading_path`), `instrument` and `root_id` (parse the provision
id), `token_count` (count the text), `previous`/`next` (ordinal arithmetic).
Compute these where needed. Storing them invites disagreement between two
representations of the same fact.

**Index state.** No embedding model, dimension, or timestamp. What model you
indexed with is a property of the index, not of the paragraph, and it belongs in
whatever repo does the indexing.

**Anything interpretive.** No concepts, topics, summaries, rule extractions,
conditions, exceptions, difficulty ratings, or relevance scores. Not because they
are worthless — some are valuable — but because they cannot be produced
deterministically, and mixing them into this layer destroys the property that
makes it trustworthy: that the output is a pure function of the source.

A later repo can add an enrichment layer keyed on `chunk_ref`, regenerated on its
own cadence, never cited. That separation is the point. If enrichment vanished
tomorrow, every answer already given from this snapshot would still be verifiable
by a person opening the Manual at that address.

---

## Worked example

Part 22.1 heading 1.2, exactly as the pipeline emits it:

```json
{
  "chunk_ref": "TMM/Part22/1/1/2",
  "page_ref": "TMM/Part22/1",
  "text": "Section 41 of the Trade Marks Act 1995 was amended by the Intellectual Property Laws Amendment (Raising the Bar) Act 2012. The repealed section 41 is set out in full in Annex A1 to this Part of the Manual. Raising the Bar came into effect on 15 April 2013. It does not contain an application or savings provision in relation to the amendments to section 41. As such the application of section 41 is regulated by section 7 of the Acts Interpretation Act 1901. Note: Section 6 of the Act defines the filing date of a divisional application as the filing date of the parent application. For more information in relation to Raising the Bar and divisional applications see: • Part 12 Divisional Applications – 9. Divisional Applications and the Intellectual Property Laws Amendment (Raising the Bar) Act 2012",
  "heading_path": [
    "Part 22 Section 41 - Capable of Distinguishing",
    "22.1. Registrability under section 41 of the Trade Marks Act 1995",
    "1.2 Intellectual Property Laws Amendment (Raising the Bar) Act 2012"
  ],
  "ordinal": 3,
  "content_hash": "sha256:883e53ab...",
  "kind": "body",
  "fragment": null,
  "provisions": [
    { "id": "AIA1901/s7", "extraction": "regex", "certainty": "explicit",
      "mention": "section 7 of the Acts Interpretation Act 1901" },
    { "id": "TMA1995/s41", "extraction": "href", "mention": "Section 41" },
    { "id": "TMA1995/s6", "extraction": "href", "mention": "Section 6" }
  ],
  "cases": [],
  "headings": [
    { "level": 3, "source": "markup", "ref": "TMM/Part22/1/1/2" }
  ],
  "internal_refs": [
    { "ref": "TMM/Part12/9", "extraction": "href",
      "mention": "9. Divisional Applications and the Intellectual Property Laws Amendment (Raising the Bar) Act 2012" },
    { "ref": "TMM/Part22/x-annex-a1-section-41-prior-to-raising-the-bar",
      "extraction": "href", "mention": "Annex A1" }
  ],
  "links": [
    { "href": "https://austlii.edu.au/…/tma1995121/s41.html",
      "text": "Section 41", "start": 0, "end": 10 },
    { "href": "/trademark/annex-a1-section-41-prior-to-raising-the-bar",
      "text": "Annex A1", "start": 169, "end": 177 },
    { "href": "https://austlii.edu.au/…/tma1995121/s6.html",
      "text": "Section 6", "start": 465, "end": 474 },
    { "href": "/trademark/9.-divisional-applications-and-the-intellectual-property-laws-amendment-raising-the-bar-act-2012",
      "text": "9. Divisional Applications and the Intellectual Property Laws Amendment (Raising the Bar) Act 2012",
      "start": 705, "end": 803 }
  ]
}
```

Note the fourth provision that is **not** there. `section 41` appears four times in
this passage; it is one edge, not four, and the hyperlink is the evidence for it.
And `AIA1901/s7` is correctly attributed away from the Trade Marks Act by the
adjacent instrument name — which is exactly the mechanism that fails on the
anaphoric `"section 26 of the Act"` case, and why `certainty` exists.

`headings` is the ancestry the `heading_path` above cannot describe: one entry,
because there is one heading between the page title and this chunk, at level 3
because the Manual marked it up as an `<h3>`, and holding this very chunk. Its
text is not repeated — it is the last element of `heading_path`.

Both `internal_refs` here are `extraction: "href"`, and both mentions are the
words the Manual hung the link on. The second is the same anchor the third
`links` entry records; one field says which page, the other says where the
anchor sat, and neither says it twice.

`links` is the same passage read a third way. The first entry is the href
`TMA1995/s41` was extracted from, so the evidence for that edge is now in the
record beside it rather than only in the raw HTML; the second and fourth are the
two `internal_refs`, at the words the Manual hung them on. Nothing is
duplicated — one field says which provision, one says which page, and this one
says where the anchor was.

The chunk runs on past the section's last paragraph into the *Note* below it,
which the CMS renders in a `div.zone` of its own. That is deliberate: zones are
layout, not structure (`SOURCE_NOTES.md` §7), and the Note is prose belonging to
heading 1.2 — it is where `TMA1995/s6` and `TMM/Part12/9` come from. Arrays are
sorted by id, so the reading order of the provisions is not the order they appear
in the text.


---

## The legislation records

`schema/instrument.schema.json` and `schema/provision.schema.json`. The same
two-level split as the Manual, for the same reason: everything constant across a
compilation is stored once and joined, rather than copied onto every record.

### The instrument record

One per law, at `snapshot/legislation/<CODE>/instrument.json`. Identity
(`code`, `title_id`, `name`, `symbol`), the titles the document states about
itself, the compilation being held (`register_id`, `compilation_number`,
`compilation_start`), the Register's own `amendments` array for that
compilation, a digest of the `.docx` it was read from, and counts.

`register_id` is the load-bearing field. It identifies one compiled version and
changes if and only if a new compilation is registered, which is the whole
amendment-detection mechanism. `has_unincorporated_amendments` is its blind
spot, recorded because a reader needs to know when the snapshot is behind the
law in force.

### The provision record

One per section, regulation, Schedule clause, Schedule item, container body or
front-matter block, at
`snapshot/legislation/<CODE>/provisions/<group>/<CODE>-<ref>.json`.

**`ref` is the citable address and the id**, chosen to equal what
`tmm_snapshot.citations` already emits: a Manual chunk carrying
`provisions[].id == "TMA1995/s41"` is a foreign key onto the record whose `ref`
is `TMA1995/s41`. It does not carry the Part — a section number is unique within
its instrument, and an address that carried the Part would break every citation
to it the moment a Part was reorganised.

`text` is verbatim and whitespace-normalised, and is **exactly** the join of the
units' text with single spaces. The validator checks that equality over the
whole corpus, the same way it checks that a Manual chunk's blocks join back to
its text, and for the same reason: it is what stops the two fields drifting into
differently worded copies of the law.

`units` is the tree the drafter asserted — `subsection`, `paragraph`,
`definition`, `note`, `penalty`, `heading`, `table`, `text`, `special`. In a
statute the boundaries are the addresses: `s41(3)(a)` is not a paragraph of
section 41, it is a provision cited in its own right. Each unit carries:

- **`ref`**, built from the nearest *numbered* ancestor plus its own printed
  label, so `s42(a)` — how everyone cites it — rather than `s42~1(a)`, which
  would be internally consistent and match no citation anybody writes. A unit
  with no label of its own takes the positional suffix `~n`, which says plainly
  that the number is ours and not the drafter's.

  An unnumbered ancestor is skipped **only where doing so collides with
  nothing**. Section 187's two unnumbered fragments carry one continuous series
  `(a)`–`(d)` and are skipped; section 6's eleven definitions each restart at
  `(a)` and are not. `LEGISLATION_NOTES.md` §6.8.

  **A definition is addressed by the term it defines** — `TMA1995/s6/australia`,
  and its paragraphs `TMA1995/s6/australia(a)`. Definitions are listed
  alphabetically, so a positional `~n` was a serial number that an insertion
  silently repointed: the failure `chunk_ref` avoids for exactly the same
  reason, and the one `SOURCE_NOTES.md` §18 removed from the Manual's glossary.
  The term is the leading bold-italic run the drafter already set, present on
  189 of 189. `LEGISLATION_NOTES.md` §6.8a.
- **`parent_ref`**, which records the true tree even where the address skips a
  rung.
- **`style`**, the `w:pStyle` verbatim. This is the evidence every other field
  on the unit was derived from, kept so a consumer can disagree with the
  derivation without re-reading the `.docx`. It is the legislation half's
  `heading_source`.
- **`number_collision`**, present and true where a sibling prints the same
  number. The Regulations do this twice, and those four units are the only ones
  in the corpus that carry it. Same contract as `certainty: "ambiguous"` —
  route to review, never hydrate from it silently. `validate.py` checks that a
  flagged unit really does share its printed number with a sibling: the flag
  says the *instrument* is defective, and must never be set by an address this
  pipeline chose.
- **`emphasis`**, bold and italic spans with offsets satisfying
  `text[start:end] == span.text`. Recorded, not interpreted, for the same reason
  `chunk.links` records an anchor's offsets rather than deciding what it meant:
  the leading bold-italic run of a `Definition` is the defined term, and
  legislation italicises the names of other instruments, so a defined-terms
  vocabulary and an instrument-citation layer both come from here — without
  either being asserted here.
- **`provisions`**, in the Manual's own shape, so one predicate filters both
  corpora. Every edge is `extraction: "regex"`: a compiled instrument carries no
  hyperlinks at all. Because the ids are this corpus's own refs, these double as
  the instrument's internal cross-reference graph.

### What is deliberately absent here too

Everything in §What is deliberately absent applies unchanged. Two additions
specific to this corpus:

- **Amendment edges from Endnote 4.** The endnotes are captured verbatim, both
  columns, in `endnotes.json`. Resolving `s 41` to `TMA1995/s41` is easy on the
  rows that are section numbers and is not possible without guessing on
  `Div 2 of Part 3` or `Reader's Guide`. `LEGISLATION_NOTES.md` §7.
- **Defined terms as a vocabulary.** The spans are recorded; deciding which of
  them is the definiendum, and linking uses of a term to its definition, is
  interpretation. It belongs beside embeddings.
