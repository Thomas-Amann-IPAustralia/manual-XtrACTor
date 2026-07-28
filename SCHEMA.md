# Data contract

The machine-checkable version is `schema/page.schema.json` and
`schema/chunk.schema.json`. Output must validate against them; CI enforces it.
This document explains what each field is for, because a schema tells you the
shape and not the reason.

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
| The heading's own number | `TMM/Part22/1/1/2` | 784 |
| A slug of the heading's text | `TMM/Part14/x-…-a13/adhesive` | 777 |
| Position on the page | `TMM/Part47/1#1` | 590 |

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

**The positional form** is left only for the prose above a page's first
heading, which has no heading to be named by. It is not the exposure it looks
like: a section with no heading *is* the page preamble, so it is the first
section by construction and nothing can be inserted ahead of it. All 590 sit
at `#1`, and a test pins that.

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

**`fragment`** — present only when an over-long section had to be split on
paragraph boundaries. `{"index": 1, "count": 2}`.

**`blocks`** — the paragraphs and list items `text` was flattened from, in
document order. 12,926 of them across 2,189 chunks, so unlike `tables` this is
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

`kind` is `paragraph`, `list_item`, `table`, `heading` or `text`, read off the
element name — `heading` is an `<h5>` or `<h6>`, since `<h2>`–`<h4>` are chunk
boundaries and `<h1>` is the page title, and `text` is inline content Drupal
left loose in a layout `div`. `depth` rides on a list item and counts the lists
enclosing it, from 1; the corpus nests three deep.

**Joining every block's `text` with single spaces reproduces `text` exactly.**
That is the contract, it is enforced in `validate.py` over the whole snapshot,
and it is what keeps `blocks` from drifting into a second, differently worded
copy of the chunk. A list item holds its own words only — the items nested under
it are their own blocks and are not repeated in their parent, or the blocks
would add up to more than the chunk. `SOURCE_NOTES.md` §19.

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
through the sitemap. If a reference does not resolve — a bare "see part 22.15.7"
pointing at something that no longer exists — **drop it**. An unresolvable string
in this field is worse than an absent one, because a consumer will try to follow it.

**Chunk-level refs come from a link's `#fragment`**, which is the slug of the
target heading and opens with the number the Manual prints. 32 of the 411 refs
address a chunk; the rest address a page, either because the anchor named no
heading number (the Part 5 glossary anchors on single letters) or because the
heading it named is no longer there. That second case **coarsens to the page
rather than dropping** — the page half was established by URL and is still
true. Settling any of this needs the whole snapshot, which is why it happens
once per run rather than per chunk: `ARCHITECTURE.md` §Two phases,
`SOURCE_NOTES.md` §22.

**A reference to the page it sits on is kept, not filtered.** 22 chunks carry
one. They are not noise and not a bug: they are the Manual pointing at another
part of the same page — *"in light of paragraph 4.3"*, the A–Z index at the top
of the INN-stems annex, the "refer to the comments above" in Part 21.3. That
the target is a sibling chunk rather than another page is precisely what a
retrieval layer needs in order to offer the right next passage, and it is only
knowable because the ref was kept: by the time the text is flattened the anchor
is gone and nothing downstream can recover it.

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
  "internal_refs": [
    "TMM/Part12/9",
    "TMM/Part22/x-annex-a1-section-41-prior-to-raising-the-bar"
  ]
}
```

Note the fourth provision that is **not** there. `section 41` appears four times in
this passage; it is one edge, not four, and the hyperlink is the evidence for it.
And `AIA1901/s7` is correctly attributed away from the Trade Marks Act by the
adjacent instrument name — which is exactly the mechanism that fails on the
anaphoric `"section 26 of the Act"` case, and why `certainty` exists.

The chunk runs on past the section's last paragraph into the *Note* below it,
which the CMS renders in a `div.zone` of its own. That is deliberate: zones are
layout, not structure (`SOURCE_NOTES.md` §7), and the Note is prose belonging to
heading 1.2 — it is where `TMA1995/s6` and `TMM/Part12/9` come from. Arrays are
sorted by id, so the reading order of the provisions is not the order they appear
in the text.
