# `manual-XtrACTor` — knowledge index

*Written for orientation in a **different** repo (the ontology work). It
describes what exists in `manual-XtrACTor`, so you know what you can consume
and what you must not expect it to do.*

Repo: `Thomas-Amann-IPAustralia/manual-XtrACTor` · Python 3.11+ ·
deps: `httpx`, `beautifulsoup4`, `jsonschema`, `pytest`.

---

## 1. What it is

A committed, offline, **deterministically extracted** snapshot of the Australian
trade marks corpus. Two halves, one shared reference grammar:

| Half | Source | Code | Output |
|---|---|---|---|
| **The Manual** | IP Australia Trade Marks Manual of Practice and Procedure (`manuals.ipaustralia.gov.au/trademark`) — rendered HTML only, no API | `src/tmm_snapshot/` | `snapshot/pages/` |
| **The law** | Trade Marks Act 1995 + Trade Marks Regulations 1995, via Federal Register of Legislation API (compiled `.docx`) | `src/frl_snapshot/` | `snapshot/legislation/` |

The snapshot **is** the deliverable; git history is the amendment log.
Published viewer: <https://thomas-amann-ipaustralia.github.io/manual-XtrACTor/>

### The three rules it lives by
1. **Deterministic extraction only** — every field derived by regex, href
   parsing or structural traversal. Same input → byte-identical output.
2. **Byte-stable output** — a file changes only if its content changed.
3. **Fail loud, never guess** — ambiguity is *recorded* (`certainty:
   "ambiguous"`), never resolved.

### What it explicitly does NOT contain
No embeddings, no vector store, no retrieval, no API, no chatbot, **no LLM calls
anywhere in the pipeline**. No concepts, topics, summaries, rules, conditions,
exceptions, difficulty ratings or relevance scores. No defined-term vocabulary
(spans are recorded; picking the definiendum is interpretation). No amendment
edges resolved from Endnote 4. All of that is deliberately left to a downstream
repo — i.e. probably yours.

---

## 2. Current corpus, measured

Manual (`ingest/0.11.0`): **500 pages** across **54 Parts**, **2,460 chunks**,
12,521 blocks (7,632 paragraph / 4,659 list_item / 121 table / 93 image),
2,218 hyperlinks, **2,717 provision edges**, **519 case edges** (411 distinct
decisions), **418 internal refs**.
Chunk kinds present: `body` 1,683, `annex` 725, `landing` 52.

Legislation (`legislation/0.2.0`): 2 instruments, **763 provisions**
(TMA1995 316, TMR1995 447), **5,813 numbered units**.

**The join:** 2,611 of 2,687 in-scope Manual provision edges resolve (97%).

583 tests pass; both corpora validate; both re-derive from stored raw with zero
files written.

---

## 3. On-disk layout (what you'd consume)

```
snapshot/manifest.json          run metadata, corpus counts, extractor_version
snapshot/sitemap.json           the Manual's nav structure (source of Part membership)
snapshot/retired.json           pages that left the Manual, and when
snapshot/pages/PartNN/*.json    {"page": {...}, "chunks": [...]} — one file per page
snapshot/raw/PartNN/*.html      verbatim source HTML
snapshot/legislation/
  manifest.json
  TMA1995/ | TMR1995/
    instrument.json             which compilation is held, and what amended it
    contents.json               Parts/Divisions/provisions in document order
    endnotes.json               the instrument's own amendment history, verbatim
    provisions/ptN/*.json       one file per section/regulation/Schedule clause
    raw/*.docx                  the verbatim compiled document
exports/cases.csv               519 rows, one per case-citation position
viz/                            static viewer (reader only, outside the pipeline)
schema/*.json                   the machine-checkable contract
```

---

## 4. The record shapes

**Page**: `page_ref` (`TMM/Part22/1`), `part_id` (from nav tree only, never the
URL), `url`, `nav_title`, `h1`, `content_hash`, `date_published`,
`last_amended`, `amendment_note` (IP Australia's own words).

**Chunk** — one retrievable passage, normally the prose under one heading:
`chunk_ref` (`TMM/Part22/1/1/2`), `page_ref`, `ordinal`, `kind`
(`body|landing|annex|note|table`), `text` (flattened), `heading_path`,
`headings`, `heading_source` (`markup|emphasis`), `content_hash`, `fragment`,
`blocks` (paragraph/list_item/table/heading/image/text — the structure the text
was flattened from), `tables`, `links` (verbatim hrefs + char offsets into
`text`), `emphasis` (b/em/i/strong/sup/u spans), and the three citation arrays:

- **`provisions[]`** — `{id, extraction, certainty, mention}`.
  `id` = `TMA1995/s44(3)(a)`, `TMR1995/r3A.3`, `TMR1995/sch2`.
  `extraction`: `href` (authors' own link — AustLII path form *and* TimeBase
  query form; Federal Register links deliberately not read) vs `regex` (our
  inference from prose). `certainty` (regex only): `explicit` (instrument named
  adjacent) / `default` (bare "section N" → the Act by convention) /
  `ambiguous` (several instruments *of that kind* in scope — feeds a human
  review queue, nothing else).
- **`cases[]`** — neutral (`[2018] FCAFC 109`) and reported (`(1954) 71 RPC 43`)
  styles, citation + canonical `case_id`.
- **`internal_refs[]`** — `{ref, extraction, certainty, mention}`, resolved to a
  `page_ref` or `chunk_ref`. Unresolvable refs are dropped, not stored. 378 href
  / 40 regex. Self-page refs are kept on purpose (25 chunks).

**Provision**: `ref` (`TMA1995/s41`), `instrument`, `kind`, `number`, `title`,
`text`, `heading_path`, `containers`, `content_hash`, `extractor_version`,
`captured_at`, `units[]`.
**Unit**: `ref` (`TMA1995/s41(3)(a)`), `parent_ref`, `kind`, `number`, `depth`,
`ordinal`, `text`, `content_hash`, `style` (the OPC `w:pStyle` it was derived
from — the evidence travels with the record).

**Derivable and therefore absent**: `part_id` on a chunk, `heading`,
`instrument`/`root_id` (parse the id), `token_count`, `previous`/`next`.

---

## 5. The join — the thing that matters most downstream

A Manual chunk's `provisions[].id` **is** a provision `ref` in the legislation
snapshot, with no transformation and no lookup table. `TMA1995/s41` on a chunk
and `TMA1995/s41` in `snapshot/legislation/TMA1995/provisions/pt4/` are the same
string. Unit refs extend it: `TMA1995/s41(3)(a)`.

Two invariants are enforced by `validate.py`: the instrument must be able to
hold that *kind* of provision (`TMR1995/s224` is not a thing), and to express
that *number* (`TMA1995/s4.7` is not — the Act uses no dots, the Regulations
always do).

Because legislation refs use the same grammar, provision edges inside the Act
double as its internal cross-reference graph for free. Every legislation edge is
`extraction: "regex"` — compiled instruments contain zero hyperlinks.

The 76 unresolved edges are mostly Manual citation defects (dotted addresses
written as sections), references to superseded numbering (pre-2012 s 41), and
the Part 22.1 anaphora case (`s 26` meaning the 1955 Act). Watch the coverage
number, not the failures.

---

## 6. Documentation map (what to read for what)

| File | Lines | Read it for |
|---|---|---|
| `CLAUDE.md` | 153 | The rules. Loaded into every session. |
| `README.md` | 135 | Public overview. |
| `ARCHITECTURE.md` | 644 | Pipeline stages, module contracts, on-disk layout, byte-stability, settling, skip logic, CI. |
| `SOURCE_NOTES.md` | 1,832 | **35 numbered sections of hard-won Manual quirks** — nav tree as the only Part source, AustLII hrefs, plain-text refs being inferences, per-page amendment logs, inconsistent heading numbering, tables, image-only pages, archived pages, bold-not-heading subsections, TimeBase links. The single most valuable file if you re-read the HTML. |
| `LEGISLATION_NOTES.md` | 491 | The Register's API, why not to scrape the site, why `.docx` not PDF, the OPC stylesheet as structure, where documents fight back, endnotes, **§8 the shared reference grammar**. |
| `SCHEMA.md` | 860 | The data contract in prose, with a worked example. |
| `schema/*.json` | — | `page`, `chunk`, `instrument`, `provision`. Machine-checkable. |
| `TASKS.md` | 391 | Work packages T1–T10 and their done-criteria. |
| `Automation-First Roadmap …md` | 1,428 | **The programme this repo is Stage 1 of.** Stages 0–7: evaluation set, ingest, terminology extraction, controlled vocabulary, relations/propositions/rules, **Stage 5 formalise the ontology**, Stage 6 knowledge graph + SHACL, Stage 7 ontology-enhanced search. |
| `ROADMAP-STAGE-1.md` | 433 | Measured assessment of this repo against Stage 1. Verdict: 4 of 6 deliverables complete; version register and source-quality report missing as *artefacts*; case law is cited but not a document here; **Stage 0 was skipped** — no competency questions, gold set, prohibited-use list or eval harness anywhere. |
| `REVIEW-0.5/0.7/0.8/0.9.0.md` | — | Per-version review records. |
| `viz/README.md` | — | The viewer, and why it may not touch the pipeline. |
| `exports/README.md` | — | `cases.csv` columns and the join key. |

---

## 7. Commands (all offline except the crawlers)

```bash
pip install -e .
pytest -q                                                 # all tests
python -m tmm_snapshot.validate                            # Manual vs schema/
python -m frl_snapshot.validate                            # legislation + cross-corpus join
python -m tmm_snapshot.crawl --from-raw --force --dry-run  # re-cut corpus, ~25s, no network
python -m frl_snapshot.crawl --from-raw --force --dry-run  # same for legislation, ~2s
python -m tmm_snapshot.diff --before /path/to/prev/snapshot
python exports/build_cases.py
```

CI: `.github/workflows/{ci,crawl,legislation,pages}.yml`. Scheduled crawls open
a PR when anything changes; never auto-merged.

---

## 8. If you are the ontology repo

- **Consume, don't re-derive.** `chunk_ref` and provision `ref` are stable keys.
  Key your enrichment on them; regenerate on your own cadence; never write back
  into `snapshot/`.
- **Everything interpretive belongs to you**, by design: concepts, terminology,
  relations, propositions, rules, defined-term vocabulary, embeddings, the
  knowledge graph. Roadmap Stages 2–7.
- **Preserve the signals.** `extraction` (href vs regex) and `certainty`
  (explicit/default/ambiguous) are the trust metadata. Collapsing them loses the
  only thing separating an authors' assertion from our inference. Ambiguous
  edges are for a human queue.
- **The Manual is practice, not law.** It states the Registrar's practice; it is
  not the legislation and does not bind the Registrar's discretion. Any ontology
  over both must keep the two distinguishable.
- **Stage 0 is still missing** — competency questions, gold standard, evaluation
  harness. `ROADMAP-STAGE-1.md` argues that is the real blocker, not Stage 1.
