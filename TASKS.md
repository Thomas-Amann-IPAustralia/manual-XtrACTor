# Work packages

Sequenced so instances can work in parallel without colliding. The module
signatures in `ARCHITECTURE.md` are the contract between them — implement
against those, not against another instance's code.

Claim a task by opening a draft PR titled `T<n>: <name>` before starting.

**Dependency graph**

```
T1 skeleton
 ├─ T2 fetcher ──┬─ T3 sitemap ──┐
 │               │                ├─ T7 orchestration ─ T8 diff ─ T9 CI
 │               └─ T4 page ──────┤
 ├─ T5 chunker ──────────────────┤
 ├─ T6 citations ────────────────┘
 └─ T10 validator
```

T3–T6 are independently implementable once T1 and T2 land. T5, T6 and T10 need
only fixtures, not the fetcher.

---

## T1 — Skeleton

Package layout per `ARCHITECTURE.md`. `pyproject.toml` (Python 3.11+, deps:
`httpx`, `beautifulsoup4`, `jsonschema`, `pytest`). `config.py` with base URL,
User-Agent including a contact address, rate limit, snapshot paths,
`EXTRACTOR_VERSION`. Vendor `schema/*.json` unchanged. Empty `snapshot/` with a
`.gitkeep`. `pytest` runs and collects zero tests without error.

**Done:** `pip install -e .` works; `python -m tmm_snapshot.crawl --help` prints usage.

---

## T2 — Fetcher

`fetch.py` per the signature in `ARCHITECTURE.md`.

Robots check on every run, not cached across runs. Serial requests, ≥1s delay,
exponential backoff on 429/5xx with a cap. Conditional requests via stored
ETag/Last-Modified; return `status=304` with `html=None` on not-modified. Cache
metadata under `.cache/` (gitignored). Retry transient failures three times, then
raise with the URL in the message.

Also in this task: **measure the corpus.** Crawl the sitemap, count pages, fetch
a sample of 20, record mean page size, extrapolate total. Report in the PR and
write it into `manifest.json`. Verify whether ETag/Last-Modified are actually
sent — if not, say so, because gate 1 of the skip logic depends on it.

**Done:** tests with a mocked transport cover 200/304/429/500 and the delay;
corpus measurement reported in the PR.

---

## T3 — Sitemap

`sitemap.py`. Parse the nav tree into `dict[str, NavPage]` keyed by normalised
URL. Walk nested `<ul>` recursively, carrying the Part down. Handle placeholder
hrefs (`<>`, `#`) on Part nodes. Alpha Part suffixes (`19A`, `32B`). Derive
`page_ref` from the leading number in the nav title, with a slug-derived fallback
for unnumbered pages. Classify `kind` as landing/annex/body.

Assert Part numbers are unique; raise if not. Raise if no nav element is found —
that means the markup changed and everything downstream is invalid.

`write_sitemap` emits `snapshot/sitemap.json`, sorted, byte-stable.

**Done:** fixture covering ≥3 Parts including a 3-level nesting and the
`2.3-section-41--capacity-to-distinguish` / `...1` collision pair; test asserts
those two resolve to `Part32A` and `Part32B` respectively.

---

## T4 — Page parser

`page.py`. Given HTML and a `NavPage`, produce a `PageRecord` and a cleaned body
element.

Extract `h1`, `Date Published`, and the `Amended Reasons` table (most recent row →
`last_amended` + `amendment_note`; note the reason cell can be empty). Strip the
table and heading from the body. Strip nav, header, footer, scripts and the known
boilerplate strings from `SOURCE_NOTES.md` §6. Scope to `<main>` → `.node__content`.
Normalise whitespace, then hash.

Raise `PageNotInSitemap` if the URL is absent from the inventory. Raise if no
`<main>` or equivalent is found.

**Done:** fixtures for a normal page, a Relevant Legislation landing page, and an
Annex; test asserts boilerplate is absent from the cleaned body and that the
amendment table does not leak into it.

---

## T5 — Chunker

`chunker.py`. Cut the cleaned body on `<h2>`–`<h4>`. Never merge across headings.
Never split so a heading is orphaned from its first paragraph.

`heading_path` is `[part label, page h1, ...heading ancestry]`. `chunk_ref` uses
the heading's leading number where present (`1.2` → `.../1/2`), else an ordinal
fallback. Sections over ~2400 characters split on paragraph boundaries only, each
fragment carrying `fragment: {index, count}` and a `~n` ref suffix. Fragments
under ~120 characters fold into the previous rather than being emitted alone.

Hash each chunk's text.

**Done:** fixtures for a page with numbered `<h3>`s, a page with no sub-headings,
and one long enough to split; test asserts refs are unique within a page and
stable across two runs.

---

## T6 — Citations

`citations.py`. The densest regex work; give it the most tests.

Provisions from AustLII hrefs first (`extraction: "href"`), using the db-fragment
map in `SOURCE_NOTES.md` §3. Then plain-text mentions (`extraction: "regex"`) with
the ~60-character instrument lookahead, setting `certainty` to
`explicit`/`default`/`ambiguous`. Mark `ambiguous` when the chunk names more than
one instrument and the reference is bare. Deduplicate: `section 41` four times in
one passage is one edge.

Cases in both neutral and reported styles. Internal refs from hrefs and from bare
dotted addresses (`see part 22.15.7`), resolved through the sitemap; **drop
unresolvable ones**.

**Done:** tests covering every example in `SOURCE_NOTES.md` §§3, 4, 8, 9 —
including an explicit test that the Part 22.1 anaphora case produces
`certainty: "ambiguous"` and is **not** silently attributed to `TMA1995`.

---

## T7 — Writer and orchestration

`writer.py` and `crawl.py`.

Serialisation: `sort_keys=True, indent=2, ensure_ascii=False`, trailing newline,
arrays sorted by stable key. **Compare against the existing file and skip the
write when bytes are identical.** Run timestamps go in `manifest.json` only.

`crawl.py` wires it together with the three skip gates from `ARCHITECTURE.md`.
CLI: `--dry-run`, `--limit N`, `--part PartNN`, `--force` (ignore skip gates),
`--from-raw` (re-parse `snapshot/raw/` without network — needed after every
parser fix).

Retire vanished pages to `snapshot/pages/_retired/`.

**Done:** an idempotence test — run twice over fixtures, assert zero files changed
on the second run. This test is the enforcement mechanism for rule 2; treat a
failure as a blocker, not a nuisance.

---

## T8 — Diff and change report

`diff.py`. Compare two snapshot states and emit markdown for a PR body: pages
added/removed/retired, pages changed with their `amendment_note`, chunk-level
counts (*"Part 22.1: 3 of 14 paragraphs amended"*), and sitemap structural
changes called out loudly — a Part's page count moving usually means a
restructure, not an edit.

**Done:** golden-file test over two fixture snapshot states.

---

## T9 — CI

`.github/workflows/crawl.yml`. Scheduled weekly (a guess — see `SOURCE_NOTES.md`
§12) plus `workflow_dispatch`. Crawl, validate, and if anything changed open a PR
with the T8 report in the body.

**Never auto-merge.** The human review is the audit trail: somebody confirms
whether an amendment is substantive practice change or a link tidy-up. That
judgement is the reason this repo exists in the form it does.

Also add a `ci.yml` running `pytest` and the validator on every push.

**Done:** dispatched run against `--limit 5` produces a PR with a readable report.

---

## T10 — Validator

`validate.py`. Walk `snapshot/pages/`, validate every page and chunk against
`schema/*.json`, report all failures with file and JSON path rather than stopping
at the first. Exit non-zero on any failure.

Beyond schema validation, assert the invariants a schema cannot express: every
`chunk.page_ref` resolves to a page in the same file; `chunk_ref` values are
globally unique; every `internal_refs` target exists in the snapshot; `ordinal`
values within a page are contiguous from 1.

Independent of everything else — implementable from `schema/` and a fixture
snapshot alone, so it can be picked up first if T1 has landed.

**Done:** passes on a good fixture snapshot; fails with a useful message on a
deliberately corrupted one.

---

## T11 — Image interpretation (later, and not in this pipeline)

**Not started, and deliberately not scheduled.** Recorded here so the gap is
tracked rather than rediscovered.

Eight pages of the Manual are an image and nothing else — Part 22's "Capable of
Distinguishing" flowchart, three of the Part 14 cross-search class tables, the
Part 54 summons formats — and 169 images sit across 39 pages in total. None
carries any `alt` text. `SOURCE_NOTES.md` §16.

As of `ingest/0.3.0` the snapshot records **that** each image exists and
**where** it is (`page.images`, `{"src", "alt"}`). It does not record what the
image says, because nothing deterministic can read a flowchart. So for those
eight pages the archive holds no evidence of the Manual's actual content — a
real gap, and the reason this task exists.

Recovering it needs OCR or a vision model. **Neither may run in this pipeline.**
CLAUDE.md is not negotiable on that point and this task does not reopen it:
rule 1 is that every field is derived from source HTML by regex, href parsing or
structural traversal, and an OCR string is neither deterministic nor
byte-stable — re-run the same model on the same PNG and the output can differ,
which alone would break rule 2 and turn every crawl into a thousand-file diff.

So T11 is a **downstream enrichment layer**, in the same place as embeddings and
for the same reason: a separate repo, keyed on `page_ref` and `image.src`,
regenerated on its own cadence, never cited as the Manual's words. See §What is
deliberately absent in `SCHEMA.md` — this is that argument applied to pictures
instead of prose.

What this repo should do when that work starts:

1. **Fetch and store the image bytes**, so there is something stable to read
   and an audit artefact that survives IP Australia reorganising
   `/sites/default/files/`. That part *is* deterministic and could live here,
   under `snapshot/media/`, keyed by a hash of the bytes. Raise it before
   building it — it changes the repo's size profile and `ARCHITECTURE.md` says
   to stop and reconsider at a gigabyte.
2. Leave interpretation to the consumer. An extracted caption is an inference
   about meaning; it belongs beside embeddings, not beside `chunk.text`.

**Done:** not applicable — this is a placeholder, not a work package. Before
implementing any of it, raise the scope question rather than deciding it.

---

## T12 — Provision hrefs that are not AustLII

**Landed as `ingest/0.11.0`, half accepted and half declined.** Both scope
questions below were settled in `SCHEMA.md` §`provisions` and
`SOURCE_NOTES.md` §35 before `citations.py` was touched, as this task asked.

**Decision 1 — TimeBase: taken.** 101 anchors, 44 distinct URLs, two
instruments. 4 edges added, 76 upgraded out of `regex` (67 `default`, 8
`explicit`, 1 `ambiguous`), 0 removed. Cross-corpus resolution 2,611/2,687 →
2,615/2,691. The 13 provisions linked to both sites in one passage agree in all
13, which is the check that the grammar is read right.

**Decision 2 — Federal Register: declined**, with the counts. The 475 anchors
resolve to 9 distinct URLs, and the two commonest name the Act and the
Regulations *together* as boilerplate on nearly every Relevant Legislation
page. Using them as a scope signal would put both instruments in scope every
time, which §21 already established is not an ambiguity and is exactly the
noise that made 39% of regex edges ambiguous before it was fixed.

The original statement of the task follows.

**Not started.** Opened by the 0.7.0 review so the gap is tracked rather than
rediscovered. It is a change to what `extraction: "href"` asserts, which is why
it was not folded into the change that found it.

`citations._href_edges` reads one URL shape — an AustLII `consol_act` or
`consol_reg` node — and that is what makes a provision edge `href` rather than
`regex`. The Manual also links its provisions to TimeBase (101 anchors,
`?id=tmact:217a`) and to the Federal Register of Legislation (475 anchors,
`C2004A04969`), and every one of those references currently reaches the
snapshot through the prose alone, at `default` or `ambiguous`. Part 61.2 is the
worked case: three references to section 217A, two of them hyperlinked, all
three recorded as a guess. `SOURCE_NOTES.md` §29.

Since `ingest/0.7.0` every one of those hrefs is in `chunk.links`, so the work
is now a reading of the snapshot rather than a re-crawl.

Two things to settle before writing any of it, both of which are decisions and
not implementation details:

1. **A TimeBase id names a provision; a Federal Register id names an
   instrument.** `?id=tmact:217a` is section 217A. `C2004A04969` is the Trade
   Marks Act 1995 and nothing narrower, so a link to it is evidence about which
   *instrument* an adjacent reference means — enough to lift `default` to
   `explicit`, not to produce an edge on its own. Those are two different
   changes and only the first produces an `href` edge.
2. **`extraction` currently means one thing.** SCHEMA.md says an `href` edge is
   the authors telling you what the paragraph is about, and a consumer filtering
   on it is filtering for that. Adding a second URL vocabulary is fine; doing it
   silently is not, because it changes what an existing filter returns.

**Done:** both scope questions raised with counts and decided in `SCHEMA.md`
and `SOURCE_NOTES.md` §35 before `citations.py` was touched; `pytest -q` green;
both validators clean; `--from-raw --force --dry-run` reports 0 against the
rebuilt corpus.

---

---

## T13 — The legislation snapshot

**Landed as `legislation/0.1.0`.** `src/frl_snapshot/`, writing
`snapshot/legislation/`. Read `LEGISLATION_NOTES.md` before changing any of it.

The Trade Marks Act 1995 and Trade Marks Regulations 1995, read from the Federal
Register of Legislation's OData API as compiled Word documents and cut on the
Office of Parliamentary Counsel's paragraph styles. 763 provisions, 5,813 units.

The design decisions worth knowing before touching it, each argued where it
lives: the `.docx` is read through `zipfile` rather than converted to HTML
(§4 — no dependency added, and conversion discards the styles that *are* the
structure); the section is the file; a provision ref does not carry its Part;
and 2,611 of the Manual's 2,687 in-scope provision edges resolve against it,
which is what the shared ref grammar was for (§8).

**Done:** `pytest -q` green; `python -m frl_snapshot.validate` clean;
`python -m frl_snapshot.crawl --from-raw --force --dry-run` reports zero files
written on an unchanged corpus.

---

## T14 — Amendment edges from Endnote 4

**Not started, and deliberately not scheduled.** Recorded so the gap is tracked
rather than rediscovered.

Every compilation carries its own amendment history: Endnote 3 lists every
amending instrument, Endnote 4 lists 317 rows of `provision affected | how
affected` for the Act alone. Both are captured verbatim in
`snapshot/legislation/<CODE>/endnotes.json`.

What is *not* done is resolving the provision column to refs — which would give
the graph `provision ←amended by→ instrument`, per provision, back to 1995. It
is the single most valuable edge set available in this corpus and it is not
deterministic in the way the rest of the pipeline is. The column holds `s 41`,
`s 41(3)(a)`, `ss 41–43`, `Part 1`, `Div 2 of Part 3`, `Sch 1`, `Reader's Guide`
and `List of terms`. A resolver that handles the easy 60% and quietly mangles
the rest is exactly the silently-wrong record rule 3 exists to prevent.

Before writing any of it, settle two things — both decisions, not implementation
details:

1. **What an unresolvable row becomes.** Dropped is wrong (it loses history);
   guessed is forbidden. Probably a record carrying the label verbatim and no
   ref, with the resolution rate reported the way the §8 coverage figure is.
2. **What a range means.** `ss 41–43` is three edges or one; `Div 2 of Part 3`
   is an edge to a container, which nothing in this snapshot currently addresses
   as an amendable thing.

**Done:** not applicable — raise the scope question first, with counts.

---

## T15 — Point-in-time compilations

**Not started.** The snapshot holds the *latest* compilation of each instrument.

The Register serves every historical one: `/v1/Versions?$filter=titleId eq '…'`
lists each with the exact window it was in force, and
`documents/find(registerId='…')` fetches it. So a point-in-time archive is
reachable without any new parsing — it is a layout question, not an extraction
one, and the answer changes the repository's shape (one file per provision per
version, or a version axis inside each file).

Worth it for one concrete reason: the Manual's Annexes discuss superseded
numbering — `TMA1995/s41(6)` is the pre-2012 section 41 — and those citations
cannot resolve against a latest-only corpus.

**Done:** not applicable — raise the layout question before building.

---

## Not in scope

Embeddings, vector stores, retrieval, ranking, an API, a UI, a chatbot, any LLM
call, and any interpretive field (concepts, summaries, extracted rules) —
including any reading of an image's contents, whether by OCR or by model
(see T11). If a task looks like it needs one of these, it does not — raise it
instead.

The snapshot is an input to that later work, not a part of it.
