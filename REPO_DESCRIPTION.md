# What this repo does

This repository commits a structured, offline snapshot of the Australian trade
marks corpus. It has two halves that share one reference grammar:

- **The Manual.** `src/tmm_snapshot/` scrapes the IP Australia *Trade Marks
  Manual of Practice and Procedure*
  (`manuals.ipaustralia.gov.au/trademark`), which is published only as
  rendered HTML — no API, no bulk download, no change feed. The output is
  written to `snapshot/pages/`, one file per Manual page, each holding the
  page's chunks: retrievable passages (normally the prose under one heading)
  with their heading ancestry, a content hash, extracted statutory and case
  citations, and the source's own hyperlinks with text offsets.

- **The law.** `src/frl_snapshot/` reads the **Trade Marks Act 1995** and the
  **Trade Marks Regulations 1995** from the Federal Register of Legislation's
  API, which serves compiled instruments as Word documents. The output is
  written to `snapshot/legislation/`, with one file per section, regulation,
  Schedule clause or Schedule item, and the numbered units inside it —
  `s41(3)(a)` is addressed and retrievable in its own right, because that is
  how the law is cited.

The two halves join without a lookup table: a Manual chunk citing section 41
carries `provisions[].id == "TMA1995/s41"`, and that is the ref of a
provision record in the legislation snapshot. 2,611 of the Manual's 2,687
in-scope provision edges resolve.

The snapshot itself is the deliverable — not an index, not a search engine,
not a chatbot. Git history over the snapshot is the amendment history: a
page or provision file changes only when its underlying content changed, so
`git diff` between crawls is a readable log of what IP Australia or the
Register changed and when.

## How it's built

Three rules govern both pipelines, laid out in full in `CLAUDE.md`:

1. **Deterministic extraction only.** Every output field comes from source
   HTML or `.docx` structure via regex, href parsing, or structural
   traversal — no model output, no heuristics, no LLM calls anywhere in the
   pipeline. Genuine source ambiguity is recorded as data, not resolved by
   guessing.
2. **Byte-stable output.** Unchanged input produces byte-identical output on
   a re-run, so a page or provision file only moves when its content did.
   Run metadata lives in `snapshot/manifest.json`, never in individual page
   files.
3. **Fail loud, never guess.** Anything the code cannot determine from the
   source with certainty — a page's place in the navigation tree, an
   unexpected markup shape — raises rather than being inferred.

## Repository layout

| Path | Contents |
|---|---|
| `src/tmm_snapshot/` | The Manual crawler, parser and chunker |
| `src/frl_snapshot/` | The legislation crawler and parser |
| `snapshot/` | The committed output: Manual pages, raw HTML, and legislation provisions |
| `schema/` | JSON Schemas the output must validate against |
| `viz/` | A published static viewer that reads the snapshot; not part of the pipeline |
| `tests/` | Offline tests against fixtures — never against the live sites |

See `CLAUDE.md` for the full orientation, `ARCHITECTURE.md` for pipeline
stages and module contracts, `SOURCE_NOTES.md` and `LEGISLATION_NOTES.md` for
the quirks of each source, and `SCHEMA.md` for the data contract in prose.
