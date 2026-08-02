# Assessment against the Automation-First Roadmap, Stage 1

An assessment of this repository at `ingest/0.9.0` and `legislation/0.2.0`
against *Automation-First Roadmap for a Trade Marks Examination Knowledge
System*, and specifically against its **Stage 1 — Ingest and structure the
source documents**.

Method: ran the repository's own gates (`pytest -q`, both validators,
`tmm_snapshot.crawl --from-raw --force --dry-run`,
`frl_snapshot.crawl --from-raw --force`), then walked all 500 page files,
2,460 chunks, 12,521 blocks, 2,218 links, 2,713 provision edges, 519 case
edges, 418 internal refs, 763 provisions and 5,813 units and counted what the
roadmap asks for. Every number below was run, not reasoned about.

State at time of assessment: 583 tests pass, both corpora validate, and both
re-derive from stored raw with **zero** files written — the snapshot is a pure
function of `snapshot/raw/` and `snapshot/legislation/*/raw/`.

---

## Verdict

**Agreed, with one qualification and one correction of framing.**

The chunked documents clear Stage 1's quality gate outright, and on several
axes they are past what Stage 1 asks for. Four of Stage 1's six deliverables
are complete. Two — the **version register** and the **source-quality
report** — exist as capability but not as artefacts: the facts are all in the
corpus, nothing assembles them into the thing the roadmap names. Both are a
few hours of deterministic work inside this repo's existing rules.

The qualification is scope, not quality. Stage 1's objective is to convert
"the manual **and related authorities**". Two of the three authority types are
here and are excellent. The third — case law — is cited 519 times across 411
distinct decisions and is not a document in this corpus at all.

The correction of framing matters more than either. **The blocker for moving
forward is not Stage 1. It is Stage 0, which was skipped.** There is no
competency-question catalogue, no gold-standard set, no prohibited-use list
and no evaluation harness anywhere in this repository. That absence took
nothing away from Stage 1 — a deterministic pipeline is checkable against its
own source and this one is checked hard. It takes away everything from Stage 2
onward, where every component is a precision and recall claim and there is
nothing to make the claim against.

---

## Stage 1, requirement by requirement

### Document conversion — what must be extracted

| Roadmap asks for | State | Where |
|---|---|---|
| document title | **Yes** | `page.h1`, `page.nav_title`; `instrument.short_title`, `long_title` |
| version | **Yes** | `last_amended`, `date_published`, `content_hash`, `extractor_version`; `register_id`, `compilation_number`, `compilation_start` |
| headings | **Yes** | `heading_path`, and `headings[]` carrying `level`, `source`, `ref` per ancestor |
| paragraphs | **Yes** | 7,632 `blocks[].kind == "paragraph"` |
| lists | **Yes** | 4,659 `list_item` blocks carrying `depth`; the corpus nests three deep |
| tables | **Yes** | 121 tables, cells with `colspan`, `header_row` set only where the markup said so |
| footnotes | **Partly** | Captured as text. Parts 49/52/55 set footnotes as `<h4>` and the chunker knows not to read the marker as an address (`SOURCE_NOTES.md` §26); legislation `note` units are typed. But a Manual footnote arrives as an ordinary headed chunk with no field saying it is a footnote. |
| page numbers | **N/A / partly** | The Manual is HTML and has none. `printed_page_ref` records the address a page prints about itself where it disagrees with the nav. The compiled `.docx` does have page numbers and they are not captured — `docx.py` treats headers and footers as separate package parts. |
| reading order | **Yes** | `ordinal` on chunks, blocks in document order, `units[].ordinal` |
| hyperlinks | **Yes** | 2,218 links, verbatim `href` plus offsets, with `text[start:end] == link.text` enforced corpus-wide by the validator |

The roadmap names Docling and Tika. Neither is used, and neither should be.
The roadmap says equivalent products may be substituted, and
`LEGISLATION_NOTES.md` §4 already records why a general-purpose converter is
the wrong tool here: it discards `w:pStyle`, which is the entire structure of
a compiled Act. The same argument in `SOURCE_NOTES.md` covers HTML-to-markdown
converters silently dropping the AustLII hrefs the citation layer depends on.
Purpose-built parsers are the right call and the reasoning is already written
down. **This is not a gap.**

### Stable segmentation

The roadmap's ladder, against what exists:

| Rung | Manual | Legislation |
|---|---|---|
| Document | page (500) | instrument (2) |
| Version | `content_hash` + `last_amended` | `register_id` + `compilation_number` |
| Chapter | Part (54) | Part / Division / Subdivision (`contents.json`) |
| Section | chunk (2,460) | provision (763) |
| Paragraph | block (12,521) | unit (5,813) |
| **Sentence** | **absent** | **absent** |

Five of six rungs, and the identifiers are **better than the roadmap's own
example**. The roadmap proposes
`tmem:manual/2026-01/chapter-4/section-3/paragraph-12`. This repo emits
`TMM/Part22/1/1/2` and `TMA1995/s41(3)(a)` — citable addresses a person can
read and verify, not positional counters. `SCHEMA.md` §`chunk_ref` gives the
argument, and it is the right one: a serial number is a citation that breaks
silently, because inserting a paragraph upstream repoints every reference
after it with nothing to detect the change. The slug form for unnumbered
headings exists precisely because the Part 14 glossary demonstrated that
failure at scale (627 chunks on one page the Manual itself calls
*non-exhaustive*).

Sentence-level segmentation is the one rung missing, and it is a real
dependency for later stages, not a cosmetic one — Stage 2.3's example output
carries `"source_sentence_id"`, and Stage 4's proposition extraction keys on
sentence-level modal indicators (*must*, *may*, *unless*, *subject to*).
**It should not be built here.** See §Moving into Stage 2.

### Source fingerprinting

The roadmap asks for a checksum per document **and per passage**, sufficient
to detect new documents, amended passages, removed passages and unchanged
content.

All four, at every level. `page.content_hash` over the normalised body,
`chunk.content_hash` over `text`, `unit.content_hash` over each unit,
`instrument.document.content_hash` over the `.docx` bytes. The Drupal
per-request-token problem is handled by normalising before hashing, which is
the detail that makes the whole mechanism work — without it every fetch looks
like an amendment.

Change detection goes further than Stage 1 requires and lands in Stage 10
territory: `diff.py` renders a change report that is a pure function of two
snapshot states (no clock, no network, no git), the scheduled crawl opens a
pull request with that report as its body and never auto-merges, and page
retirement moves files to `pages/_retired/` rather than deleting them. The
human judgement the roadmap wants — substantive practice change or hyperlink
tidy-up — is made on IP Australia's own `amendment_note`, present on 500 of
500 pages.

### Quality gate

> The parser must reliably preserve: headings; paragraph boundaries;
> citations; page references; the link between extracted text and its original
> source.

| Gate | State |
|---|---|
| headings | Preserved, and the inference is labelled. `heading_source` is `markup` (1,473), `emphasis` (491) or `null` (496). A consumer wanting only what the Manual marked up filters to `markup`; one wanting the structure the Manual *prints* takes both. Neither has to guess. |
| paragraph boundaries | Preserved and **verified**: joining every block's text with single spaces reproduces `chunk.text` exactly, enforced corpus-wide. Same contract holds on the legislation side between units and provision text. |
| citations | 2,713 provision edges (963 distinct ids), 519 case edges (411 distinct), 418 internal refs, 2,218 links. |
| page references | `internal_refs` resolve to `page_ref` or `chunk_ref` through the sitemap, or are **dropped** — an unresolvable string is worse than an absent one because a consumer will follow it. `printed_page_ref` records the two pages whose printed address disagrees with the nav. |
| text ↔ source | `page.url` is exact and clickable; `page_ref` and `chunk_ref` are readable addresses; raw HTML for all 500 pages and both `.docx` files are committed, so any record can be re-derived and challenged. |

**The gate is met, and on two of the five rows it is met with a corpus-wide
invariant rather than a spot check.**

### Deliverables

| Deliverable | State |
|---|---|
| structured source corpus | **Complete.** 500 pages / 2,460 chunks; 763 provisions / 5,813 units. |
| stable identifiers | **Complete, and past the requirement.** |
| version register | **Partial.** Every fact is on the records; nothing assembles them. The *historical* axis lives in git history, which is a defensible design decision that is nowhere stated as one. |
| document metadata | **Complete.** |
| change-detection process | **Complete, and past the requirement.** |
| source-quality report | **Partial.** The validators emit two summary lines. `REVIEW-0.5.0.md`, `REVIEW-0.7.0.md` and `REVIEW-0.8.0.md` are excellent audits, and they are one-off documents written by hand, not a regenerated artefact. |

---

## Where the repository is already past Stage 1

Three things are worth naming, because they are load-bearing for later stages
and were arrived at independently of the roadmap.

**1. The confidence model already exists, and it maps onto the roadmap's tiers
almost exactly.** The roadmap §2 asks that every machine-generated result carry
an extraction method, a confidence signal and an exact supporting passage. This
corpus does:

| Roadmap tier | This corpus | Count |
|---|---|---|
| Tier 1 — deterministic, auto-accept | `extraction: "href"` — the Manual's authors linking the provision themselves | 850 edges |
| Tier 2 — probabilistic, low risk | `extraction: "regex"`, `certainty: "explicit"` or `"default"` | 1,743 edges |
| Tier 3 — route to review | `certainty: "ambiguous"` | 120 edges on 39 chunks |

`SCHEMA.md` states the principle as *"a wrong edge that knows it might be wrong
is survivable; a wrong edge that looks certain is not"*, which is the roadmap's
§6 review policy in one sentence. The `certainty: "ambiguous"` value exists
because of the Part 22.1 anaphora case — *"section 26 of the Act"* where "the
Act" is the 1955 Act from the previous sentence — and it is recorded rather
than resolved. The `number_collision` flag on legislation units is the same
mechanism applied to a defect in the Regulations.

**Stage 2 does not need to build a confidence framework. It needs to adopt this
one.**

**2. The cross-corpus join is live.** 2,611 of 2,687 in-scope Manual provision
edges resolve to a provision or unit record in the legislation snapshot, with
no lookup table — the Manual's `provisions[].id` *is* the legislation corpus's
`ref`. That is the roadmap's Stage 6 "citesProvision" edge, already asserted and
already validated, ahead of schedule by five stages.

**3. Evidence is kept beside every inference.** `links[]` retains the href a
provision edge was extracted from, `style` retains the `w:pStyle` a unit's kind
was derived from, `heading_source` says how a boundary was found, `emphasis`
records bold-italic spans without deciding what they mean. A consumer can
disagree with any derivation without re-reading the source. This is what
Stage 6's provenance requirements will need, and building it retroactively is
usually impossible.

---

## What is genuinely not there

Four items, ranked by what they cost.

### 1. Stage 0 was never done — and it is the actual blocker

No competency-question catalogue. No gold-standard dataset. No prohibited-use
list. No evaluation measures. No retrieval or reasoning test set. The roadmap
puts this before Stage 1 and calls it *"one of the most important uses of
expert time"*, and its closing recommendation is to begin with it.

Stage 1 survived the omission because a deterministic pipeline can be checked
against its own source, and this one is checked unusually hard: 583 tests,
corpus-wide invariants, and a `--from-raw --force` gate that reports exactly
how many files a parser change would move.

Nothing after Stage 1 has that property. YAKE keyphrases, entity recognition,
synonym clusters, relation extraction, retrieval ranking — every one is a
precision/recall claim, and there is currently nothing to make the claim
against. Building Stage 2 first means discovering at Stage 7 that the
vocabulary was wrong, with no measurement able to say when it went wrong.

**This is the single highest-value next piece of work, and it is expert time,
not engineering time.**

### 2. Case law is cited and absent

519 case edges, 411 distinct decisions, ids minted in a stable scheme
(`CASE/2024/FCA/1277`, `CASE/1963/CLR/109/407`). No case is a document in this
corpus, and three problems follow:

- **The ids resolve to nothing.** The provision half has a resolution target;
  the case half does not. `CASE/2024/FCA/1277` is a well-formed address for a
  record that does not exist.
- **One decision has two identities.** 289 distinct neutral-style ids and 122
  reported-style, with 50 chunks carrying both styles. Nothing links
  `[2014] HCA 48` to `(2014) 254 CLR 337`. Any count of "material citing
  Cantarella" is currently wrong.
- **24 jade.io anchors reach no edge at all** — the Manual's authors naming a
  decision, in an href, discarded.

Stage 2.4 explicitly wants *"the Cantarella decision"* resolved to a stable
identifier, and the pilot competency questions in Stage 0 include *"Which
cases interpret the relevant test?"* and *"What manual material cites a
particular case?"*. Neither is answerable today.

Fetching judgments is a separate question with real licensing and robots
constraints and should not be assumed. **A case register does not require
it** — see the recommendations.

### 3. Two Stage 1 deliverables are unassembled

The version register and the source-quality report. Both are pure derivations
over data already in the corpus, both are byte-stable, and both are inside
rule 1. Details in §What I would do.

### 4. Eight pages are a picture, and one is in the obvious pilot

`TMM/Part22/x-annex-a2-flowchart-of--capable-of-distinguishing-` is the
"Capable of Distinguishing" flowchart — the decision procedure for section 41,
in a corpus whose most likely pilot area is section 41. The snapshot records
that an image sat there and where; it holds no evidence of what it says.

`TASKS.md` §T11 tracks this correctly and rules OCR out of this pipeline for
the right reason: an OCR string is neither deterministic nor byte-stable, so
it would break rules 1 and 2 together. That is not in dispute. What matters
here is that it is a **known hole in the pilot's content**, and Stage 0's
gold-standard set should be written knowing the hole exists rather than
discovering it during evaluation. The other seven are three Part 14
cross-search class tables, two Part 54 form formats, and two more flowcharts.

---

## Moving into Stage 2

### The architectural decision, first

**Stage 2 onward must not be built in this repository**, and the repository
already says so in three places: CLAUDE.md's three rules, `SCHEMA.md` §What is
deliberately absent, and `TASKS.md` §Not in scope. That instruction is correct
and should be held.

The reason is worth restating in roadmap terms, because the pressure to
relax it will be constant. This corpus's value is that it is a **pure function
of the source**: every field is derived by regex, href parsing or structural
traversal, it re-derives byte-identically, and any record can be checked by a
person opening the Manual at that address. A YAKE keyphrase, an embedding
cluster or an LLM-extracted relation has none of those properties. Mixed into
the same files, they do not gain the corpus's trustworthiness — the corpus
loses it, and `git diff` between crawls stops being a readable amendment log,
which is the entire point of the repository.

So: **a second repository, consuming this snapshot, keyed on `chunk_ref`,
`page_ref` and provision `ref`, regenerated on its own cadence, never cited as
the Manual's words.** If the enrichment layer vanished tomorrow, every answer
already given from this snapshot would still be verifiable. That separation is
what makes the automation-first approach safe for a legal corpus, and this
repository has already paid for it.

### What Stage 2 gets for free

| Stage 2 task | Already done | Remaining |
|---|---|---|
| 2.2 known entity recognition — legislative provisions | 2,713 edges, 963 distinct ids, method and certainty on each | Nothing. Adopt it. |
| 2.2 — Act and regulation names | Both instruments identified, titled, dated, compiled | Nothing. |
| 2.2 — manual sections | 2,460 addressable chunks with full ancestry | Nothing. |
| 2.4 citation resolution — provisions | 2,611/2,687 in-scope edges resolve | 76 edges across 51 ids (below) |
| 2.4 — internal cross-references | 418 refs, resolved or dropped, `href` vs `regex` distinguished | Nothing. |
| 2.4 — cases | ids minted in a stable scheme | Register + alias table (§2 above) |
| 2.1 keyphrase extraction | `chunk.text` + `heading_path`, 1.87M characters over 2,460 chunks | Run YAKE downstream |
| 2.3 new entity discovery | `emphasis` spans on legislation units — 189 of 189 definitions carry their defined term as a leading bold-italic run, and all 189 are addressed by it | Seed the vocabulary from these before asking a model for candidates |

That last row is worth dwelling on. The roadmap's Stage 3 wants a SKOS
vocabulary built from clustered candidate phrases. **The Act and Regulations
already contain 189 drafter-authored definitions, each with its term recorded
as a span and addressed by that term** (`TMA1995/s6/australia`). Those are not
candidates — they are the legislature's own controlled vocabulary, and they
should be the spine of the SKOS scheme, with YAKE and embedding clusters
hanging off it rather than competing with it. Starting from statutory
definitions and extending outward is both cheaper and more defensible than
clustering 2,460 chunks of prose and hoping the legal distinctions survive.

### The 76 unresolved provision edges

51 distinct ids, and the shape is informative: `TMA1995/s15(1)(a)`,
`TMA1995/s26(3)`, `TMA1995/s41(6)`, `TMA1995/s11C`, `TMA1995/s170A`. These are
mostly **subsection-level addresses the drafter did not label as separate
units**, plus repealed provisions the Manual's annexes discuss —
`TMA1995/s41(6)` is the pre-2012 section 41, which cannot resolve against a
latest-only corpus by construction.

`TASKS.md` §T15 already scopes the fix (point-in-time compilations, reachable
from the Register's `/v1/Versions` endpoint with no new parsing) and correctly
flags it as a layout question to raise rather than build. **Worth raising
now**, because Stage 7 wants "retrieval of current rather than superseded
sources" as a measured quantity, and Stage 9's impact analysis is defined over
provision amendment. Both need a version axis in the legislation corpus.

### Sentence segmentation — build it downstream, and version it

The missing rung, and the recommendation is to key it as `chunk_ref` plus
character offsets into `chunk.text` — `TMM/Part22/1/1/2#s3` with
`{"start": 412, "end": 587}` — in the enrichment repo, not here.

Two reasons. First, sentence splitting on legal prose fails in ways that are
silent and specific: `s. 41(3)(a)`, `No. 119, 1995`, `cf.`, `[2024] FCA 1277 at
[255]`, and the Manual's numbered bold sub-headings. A splitter good enough for
Stage 4 will need several revisions, and each one would be a corpus-wide diff
here. Second, offsets into an immutable `chunk.text` mean a re-split costs
nothing upstream and every sentence id stays verifiable against a hash that did
not move. The corpus stays byte-stable; the segmentation improves on its own
cadence. That is the same argument `SCHEMA.md` makes for embeddings, applied to
one rung of the ladder.

### The one thing to watch

The roadmap's operating model — *"machines extract, cluster, link and propose;
experts define, approve and resolve exceptions"* — assumes machine proposals
are clearly marked as proposals. This corpus has never contained one, so the
distinction has never had to be enforced across a boundary. When Stage 2
starts, the named-graph discipline the roadmap specifies at Stage 6
(authoritative / machine-extracted / expert-approved / inferred / superseded,
kept apart) needs to be in place from the **first** enrichment record, not
retrofitted when the graph is populated. The cheapest way to guarantee it is
the repository split above: this snapshot is the authoritative graph by
construction, and everything in the other repository is a candidate until a
human says otherwise.

---

## What I would do, in order

**1. Stage 0, properly, before any Stage 2 code.** *(expert time)*
Pick the pilot — Part 22 is the natural candidate: 31 pages, 128 chunks,
anchored on `TMA1995/s41`, connected to Parts 21, 23 and 26 and to most of the
cited case law. Write the competency questions, build the gold-standard set at
the sizes the roadmap gives (100–300 entities, 50–100 concepts, 50–100
relationships, 20–50 search questions, 20–50 retrieval questions), and write
the prohibited-use list. Note the Part 22 flowchart hole while writing it.
This is the roadmap's own closing recommendation and it is the one piece
nothing else can substitute for.

**2. Close the two open Stage 1 deliverables.** *(small, in this repo, inside rule 1)*

- **`snapshot/versions.json`** — one generated index: every `page_ref` with its
  `content_hash`, `last_amended`, `date_published`, `crawled_at` and
  `extractor_version`; every instrument with its `register_id`,
  `compilation_number` and `compilation_start`. Byte-stable by construction
  since every input already is. State in `ARCHITECTURE.md` that the historical
  axis is git history and that this file is the current-state index — right
  now that is a real design decision sitting undocumented.
- **`snapshot/quality.json` plus a rendered report** — turn the standing facts
  into a regenerated artefact instead of a hand-written review: 2 unreachable
  nav entries, 6 archived pages, 15 pages yielding no chunks (8 image-only, 6
  archived, 1 other), 496 chunks with no heading, 120 ambiguous provision
  edges on 39 chunks, 76 unresolved in-scope edges across 51 ids, 600
  authority anchors reaching no edge (475 Federal Register, 101 TimeBase, 24
  jade.io), and the `_repeated_labels` cases. This is Stage 1's
  source-quality report and, unchanged, it is also Stage 10's monitoring
  dashboard.

**3. Build the case register.** *(machine proposes, human approves — the roadmap's pattern exactly)*
Not the judgments — the register. One record per decision: canonical id,
every citation string seen, court, year, and the neutral↔reported alias. The
machine half is deterministic from what is already extracted: the citation
strings, the 24 jade.io hrefs, and co-occurrence within a chunk. The alias
decision — *is `[2014] HCA 48` the same decision as `(2014) 254 CLR 337`* — is
a judgement, so it goes to a review queue with the evidence attached. 411
decisions, of which 50 chunks already show both styles together, is a bounded
piece of expert work with a large payoff: it makes two Stage 0 competency
questions answerable and closes the largest hole in the citation layer.

**4. Raise T15 — point-in-time compilations.** A layout decision, not an
extraction one, and it gates Stage 7's currency measurement and Stage 9's
impact analysis. `TASKS.md` asks for it to be raised before building; this is
raising it.

**5. Then start the enrichment repository**, keyed on `chunk_ref`, with
sentence segmentation as its first module, YAKE and the statutory-definition
spine as its second, and the confidence tiers already in this schema as its
governance model.

---

## In one paragraph

Stage 1 is done. The chunked documents clear its quality gate, exceed its
identifier and provenance requirements, and in the cross-corpus join and the
`href`/`regex`/`certainty` tiering they have already built two things the
roadmap does not ask for until Stages 6 and 2 respectively. Two deliverables
need assembling and one authority type is missing, and neither is large. What
is large is that Stage 0 was skipped, and everything after Stage 1 is
unmeasurable until it is done. Build the gold-standard set before writing a
line of Stage 2.
