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

**`extractor_version`** — which version of this pipeline produced the record. When
a parser bug is fixed, this tells you which snapshots need rebuilding from
`raw/`.

---

## The chunk record

**`chunk_ref`** — the address, and the id. `TMM/Part22/1/1/2` means Part 22,
page 1, heading 1.2. A person can read it and find the source.

Do not add a separate sequential id. A serial number is a citation that breaks
silently: insert a paragraph upstream and `chunk-047` now points at different
text, with nothing to detect it. An address survives where a counter does not.

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

**`kind`** — `body`, `landing`, `annex`, `note`, `table`. `landing` marks
*Relevant Legislation* pages, which are mappings rather than prose and should
usually be excluded from applicant-facing answers.

**`fragment`** — present only when an over-long section had to be split on
paragraph boundaries. `{"index": 1, "count": 2}`.

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
by convention. `ambiguous` means several instruments are in scope and we cannot
tell.

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

Real text, from Part 22.1 heading 1.2:

```json
{
  "chunk_ref": "TMM/Part22/1/1/2",
  "page_ref": "TMM/Part22/1",
  "text": "Section 41 of the Trade Marks Act 1995 was amended by the Intellectual Property Laws Amendment (Raising the Bar) Act 2012. The repealed section 41 is set out in full in Annex A1 to this Part of the Manual. Raising the Bar came into effect on 15 April 2013. It does not contain an application or savings provision in relation to the amendments to section 41. As such the application of section 41 is regulated by section 7 of the Acts Interpretation Act 1901.",
  "heading_path": [
    "Part 22 Section 41 - Capable of Distinguishing",
    "22.1. Registrability under section 41 of the Trade Marks Act 1995",
    "1.2 Intellectual Property Laws Amendment (Raising the Bar) Act 2012"
  ],
  "ordinal": 3,
  "content_hash": "sha256:0dffb00c...",
  "kind": "body",
  "fragment": null,
  "provisions": [
    { "id": "TMA1995/s41", "extraction": "href", "mention": "Section 41" },
    { "id": "AIA1901/s7", "extraction": "regex", "certainty": "explicit",
      "mention": "section 7 of the Acts Interpretation Act 1901" }
  ],
  "cases": [],
  "internal_refs": ["TMM/Part22/x-annex-a1-section-41-prior-to-raising-the-bar"]
}
```

Note the third provision that is **not** there. `section 41` appears four times in
this passage; it is one edge, not four. And `AIA1901/s7` is correctly attributed
away from the Trade Marks Act by the adjacent instrument name — which is exactly
the mechanism that fails on the anaphoric `"section 26 of the Act"` case, and why
`certainty` exists.
