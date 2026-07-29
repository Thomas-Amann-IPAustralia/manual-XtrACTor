# CLAUDE.md

Read this first. It is loaded into every session, so it is deliberately short.
Follow the links when you need depth.

## What this repo does

Commits a structured offline snapshot of the Australian trade marks corpus, in
two halves that share one reference grammar:

- **The Manual.** Scrapes the **IP Australia Trade Marks Manual of Practice and
  Procedure** (`manuals.ipaustralia.gov.au/trademark`), which is published only
  as rendered HTML. `src/tmm_snapshot/`, written to `snapshot/pages/`.
- **The law.** Reads the **Trade Marks Act 1995** and **Trade Marks Regulations
  1995** from the Federal Register of Legislation's API as compiled Word
  documents. `src/frl_snapshot/`, written to `snapshot/legislation/`.

The snapshot is the deliverable. Git history is the amendment history.

The two halves join without a lookup table: a Manual chunk citing section 41
carries `provisions[].id == "TMA1995/s41"`, and that is the ref of a provision
record in the legislation snapshot. 2,603 of the Manual's 2,776 in-scope
provision edges resolve. Keeping that true is a constraint on both pipelines —
`LEGISLATION_NOTES.md` §8.

## What this repo does NOT do

No embeddings. No vector store. No retrieval. No API. No chatbot. No LLM calls
anywhere in the pipeline, at any stage, for any reason.

If a task seems to need one of those, you have misread the task. Stop and ask.

## The three rules

**1. Deterministic extraction only.**
Every field in the output is derived from source HTML by regex, href parsing or
structural traversal. Run the pipeline twice on unchanged input and the output is
byte-identical. No model output, no heuristic that "usually" works, no inferred
meaning. Where the source is genuinely ambiguous, record the ambiguity in the
data and move on — do not resolve it.

**2. Byte-stable output.**
A page file must not change unless the page's content changed. This is what makes
`git diff` between crawls a readable amendment log. Practically: sort JSON keys,
sort arrays by a stable key, do not write a fresh timestamp into a file whose
content did not change. Run-level timing goes in `snapshot/manifest.json`, never
in page files. Getting this wrong turns every crawl into a thousand-file diff and
destroys the point of the repo.

**3. Fail loud, never guess.**
If a page is not reachable from the navigation tree, you cannot determine which
Part it belongs to — raise, do not infer it from the URL. If the markup has
changed shape, raise. A missing record is recoverable. A silently wrong record
corrupts every downstream answer and nobody finds out.

## Orientation

| Document | Read it when |
|---|---|
| `ARCHITECTURE.md` | Before writing any code. Pipeline stages, module boundaries, function signatures, on-disk layout. |
| `SOURCE_NOTES.md` | Before writing any parser for the Manual. Its real quirks, each already discovered the hard way. |
| `LEGISLATION_NOTES.md` | Before touching `frl_snapshot/`. The Register's API, the OPC stylesheet, and where the compiled documents fight back. |
| `SCHEMA.md` | Whenever you touch the output shape. The data contract, in prose. |
| `schema/*.json` | The contract itself. Machine-checkable. Output must validate. |
| `TASKS.md` | To find your work package and its done-criteria. |
| `viz/README.md` | Before touching the published viewer. It reads the snapshot and is not part of the pipeline — no field exists on a chunk for its benefit. |

## Working here

- Python 3.11+. Type hints throughout. Standard library first.
- Dependencies: `httpx`, `beautifulsoup4`, `jsonschema`, `pytest`. Adding one is a
  decision to raise, not to make.
- Tests run offline against fixtures in `tests/fixtures/`. Never write a test that
  hits the live site.
- Every parser change needs a fixture demonstrating the case it handles.
- Module boundaries in `ARCHITECTURE.md` are fixed. Other instances are working
  against those signatures in parallel. Changing one is a breaking change — raise
  it, do not just do it.

## Before you commit

```bash
pytest -q                        # all tests
python -m tmm_snapshot.validate  # Manual output validates against schema/
python -m frl_snapshot.validate  # legislation output, plus the cross-corpus join
python -m tmm_snapshot.crawl --from-raw --force --dry-run
python -m frl_snapshot.crawl --from-raw --force        # 2s, no network
```

The third one is the check that a parser change did not move the corpus, and
**`--force` is what makes it one**. Without it the run stops at gate 2, reports
`chunks cut 0`, and says a corpus is clean that a chunker change would have
rewritten from end to end. With it, every page is re-cut from `snapshot/raw/`
and `pages written` is the count of files your change would alter — 25 seconds,
no network, and it is how you find out whether you owe an `EXTRACTOR_VERSION`
bump.

`frl_snapshot.crawl --from-raw --force` is the same check for the legislation
half and needs no `--dry-run`: it re-cuts both instruments from the stored
`.docx` and reports `files written`, which is the count of files your change
would alter. Zero means the corpus did not move.

`tmm_snapshot.crawl --dry-run --limit 5` is a live fetch of a Commonwealth
agency site. Run it when you have changed the fetching, not on every commit.
The legislation crawler is gentler — two small JSON probes unless a compilation
actually changed — but the same rule applies.

Commit messages: `<area>: <what changed>`, e.g. `chunker: split on h4 headings`.

## Scope discipline

This repo is small on purpose. The temptations, in the order you will encounter
them:

- *"The section-26 anaphora bug could be fixed with a quick model call."* No.
  Rule 1. Record it as `certainty: "ambiguous"` and leave it.
- *"I could add embeddings so the snapshot is immediately useful."* No. Different
  repo, different lifecycle. The snapshot is an input to that work, not part of it.
- *"This parser would be cleaner with a general-purpose HTML-to-markdown library."*
  Probably, and it would also silently drop the AustLII hrefs the whole citation
  layer depends on. See `SOURCE_NOTES.md`.
- *"The nav tree is huge and repeated on every page — I'll skip parsing it."* It is
  the only reliable source of Part membership. See `SOURCE_NOTES.md` §2.
- *"Mammoth converts the .docx to HTML in one line."* It also discards every
  `w:pStyle`, which is the entire structure of a compiled Act. Same trap as the
  point above it. See `LEGISLATION_NOTES.md` §4.
- *"Endnote 4 lists every amendment per provision — I'll resolve the labels to
  refs."* Two thirds of them parse and the rest are `Div 2 of Part 3` and
  `Reader's Guide`. See `LEGISLATION_NOTES.md` §7.

## Courtesy to the source

This is a Commonwealth agency site and we are pulling the whole of it.

- Honour `robots.txt`. Check it on every run, do not cache the verdict.
- One request at a time. Minimum 1s delay between requests, and back off on any
  429 or 5xx.
- Identify the crawler in the User-Agent with a contact address.
- Cache aggressively: send `If-None-Match` / `If-Modified-Since` and treat 304 as
  "unchanged", so a re-crawl costs the site almost nothing.
- Never run the full crawl from a laptop on a whim. Scheduled CI, or `--limit`.
