# Review of the 0.7.0 extraction

An audit of the pipeline and of `snapshot/` at `ingest/0.7.0` — 500 page files,
2,460 chunks, 12,521 blocks, 2,218 links, 2,802 provisions, 519 cases, 417
internal refs — asking two questions:

1. **What can break the system?**
2. **What is structurally wrong in a way that would harm an ontology built on
   top of this?**

Method: read every module against `ARCHITECTURE.md`, `SCHEMA.md` and
`SOURCE_NOTES.md`; re-derived the whole corpus from `snapshot/raw/` and compared
it byte for byte against the committed records; word-level accounting over all
500 cleaned bodies; and, for each suspected defect, a probe against the whole
corpus or a reproduction against a copy of the snapshot. Every claim below was
run, not reasoned about. Where a defect is latent rather than active, that is
said.

Nothing here proposes a model, an embedding or a heuristic. The three rules
hold throughout, and two of the findings are cases where the pipeline is
currently *breaking* rule 3 by resolving something it should be recording.

---

## What is sound

Stated first, because it bounds everything after it.

- **Reproducible.** `crawl --from-raw --force` over the committed `raw/`
  rewrote nothing: zero byte differences across 500 page files, `sitemap.json`
  included. The snapshot in this repository is exactly what this code produces
  from this source. Rule 2 holds in practice, not just in intent.
- **Coverage is complete.** 313,905 tokens in the 500 cleaned bodies; **one**
  reaches neither a `chunk.text` nor a `heading_path`, and it is Part 23.2's
  bare `2.2`, the single documented `SuppressedHeading` of `SOURCE_NOTES.md`
  §27. No other word of the Manual is missing.
- **Addresses hold.** 2,460 chunk_refs, globally unique. No chunk_ref is also a
  page_ref. No chunk_ref contains a *different* page's page_ref as a prefix.
  Ordinals contiguous from 1 on every page.
- **The stated contracts hold corpus-wide.** `join(blocks) == text` on all
  2,460 chunks. `text[start:end] == link.text` on all 2,218 links. 121 `table`
  blocks against 121 `chunk.tables`. No provision id names a kind of provision
  its instrument cannot hold.
- **433 tests pass; the snapshot validates.**
- **The case extractor is clean.** All 519 edges were inspected by series; the
  unusual ones — `AOJP`, `ROC`, `VLR`, `LGERA` — are genuine report series
  carrying genuine decisions, not regex noise.
- **The politeness and caching layer is right,** including the non-obvious
  part: sending one conditional header rather than two, for the reason given in
  §12.

The findings below are not about lost or garbled words. They are about
**edges** — where the pipeline records a relationship it cannot support, fails
to maintain one it already has, or throws away the evidence that would let a
consumer weigh one.

---

# Part one — correctness

## 1. Three cross references point at the wrong Part

**The most serious finding, and the one the whole repository is built to
prevent.** `SOURCE_NOTES.md` §2 calls misattributing a page to the wrong Part
"the single worst failure available in this codebase". Three `internal_refs`
do exactly that, and they do it with the confident, unqualified string the
schema reserves for a resolved reference.

`_BARE_INTERNAL_REF` reads `part <N>.<M>` as *Part N, page M*. The Manual also
uses the word "part" to mean a section of the Part you are already reading, and
when it does, it says so:

| Chunk | The Manual writes | Stored edge | What it means |
|---|---|---|---|
| `TMM/Part32A/2/1/2-1-1-b-composite-or-fancy-trade-marks` | "see **part 2.3.1(c) of this chapter**" | `TMM/Part2/3` | `TMM/Part32A/2/3` |
| `TMM/Part32A/2/5#1` | "see **parts 2.3.1 and 2.3.2 of this chapter**" | `TMM/Part2/3` | `TMM/Part32A/2/3` |
| `TMM/Part32A/x-annex-5---case-law-summaries/sfr-holdings-inc-2013-atmo-77-seadwarf~1` | "As noted at **part 2.1 of this revised chapter**" | `TMM/Part2/1` | `TMM/Part32A/2/1` |

Part 32A is *Examination of Trade Marks for Plants (in Class 31)*. Part 2 is
*Filing Requirements*. A passage about whether a plant varietal name is a
composite trade mark now carries an edge to a page about how to file a
document.

Two aggravations:

- **In two of the three the correct edge is already there, beside the wrong
  one.** `TMM/Part32A/2/5#1` carries `TMM/Part32A/2/3/2/3/1` and
  `TMM/Part32A/2/3/2/3/2` from the paragraph's own hyperlinks *and*
  `TMM/Part2/3` from this misreading, in one flat array, with nothing to tell
  a consumer which is which.
- **The Manual disambiguates it in the source.** "of this chapter" is not
  context a regex has to infer; it is four words sitting immediately after the
  match, in the same string the extractor already has.

Scope, measured: 35 bare references resolve to a Part other than the referring
one. 31 are unambiguous — Part-qualified and usually carrying the target Part's
own title (`Part 13.8 Divisional Applications from Series`). Three are the
above. One more, `Part 5.2.2.6 Checking, approval, publication and
notification` on `TMM/Part9/3`, was flagged by the probe only because
`TMM/Part9/5` also exists; it carries the target's title and is correct.

This is not a case for a model. Two deterministic answers are available and
either would do:

- **Drop, per rule 3.** A bare reference immediately followed by *of this
  chapter / part / manual*-style qualification where the digits also address
  something inside the referring Part is genuinely ambiguous, and an
  unresolvable reference is dropped rather than stored — the rule
  `SOURCE_NOTES.md` §8 already applies to everything else.
- **Prefer the local reading** when the Manual says "of this chapter". That is
  reading what the source says, not guessing.

The first is cheaper and needs no new judgement. Either beats what is there
now, which is the failure mode `SCHEMA.md` names: *a wrong edge that looks
certain*.

## 2. Cross references rot on every crawl that is not `--force`

**Reproduced end to end.** A crawl that changes one heading leaves dangling
`internal_refs` on every unchanged page that pointed at it, exits **0**, and
produces a snapshot that fails its own validator — permanently.

`ARCHITECTURE.md` §Two phases is right about the problem and right about the
mechanism. `_resolve_refs` settles a candidate ref against the finished
inventory. But it only runs over `prepared` — the pages *this run re-cut*. A
page whose own content did not change is skipped at gate 2, never enters
`prepared`, and keeps refs that were resolved against an inventory that no
longer exists.

The reproduction, against a copy of the snapshot: rename Part 14 page 6's
heading `6.5` to `6.51` in `raw/`, then `crawl --from-raw` with no `--force`,
which is the scheduled-crawl path.

```
pages written    1
  TMM/Part14/6: 1 of 18 paragraphs amended
crawl exit=0

$ python -m tmm_snapshot.validate
pages/Part14/TMM-Part14-2.json chunks[2]: internal_ref TMM/Part14/6/6/5 names no page
  or chunk in this snapshot or its sitemap …
pages/Part14/TMM-Part14-4.json chunks[24]: internal_ref TMM/Part14/6/6/5 names no page
  or chunk in this snapshot or its sitemap …
2 validation failure(s)
```

Three further crawls do not clear it — the referring pages are unchanged every
time, so they are skipped every time. `crawl --from-raw --force` clears it
immediately and correctly, coarsening the ref to `TMM/Part14/6`.

The consequences are worse than the two lines above:

- **The crawl reports success.** CI's validator would catch it at PR time, but
  the crawl itself does not, so the manifest records a clean run.
- **The silent direction has no validator at all.** The inverse case — a ref
  that coarsened to page level because the target heading did not exist, and
  whose heading later appears — is *valid* output. It simply stays coarse
  forever. Nothing fails, nothing reports it, and the chunk-level precision
  §22 was written to obtain quietly degrades to page level, one amendment at a
  time. 28 refs address a chunk today; that number can only fall.
- **It is not the referring page's fault, so no amount of re-crawling fixes
  it.** The repair requires a full forced rebuild, which nothing schedules and
  nothing prompts.

The fix is a change to which pages `_resolve_refs` reaches, not to how it
resolves. A page holding a candidate whose target moved must be re-settled even
though its own bytes did not change. The cheapest correct form: keep the
*candidate* refs (not just the resolved ones) for every page in scope, and
re-settle all of them against `_chunk_inventory` each run. That means reading
the stored refs of skipped pages — which `_chunk_inventory` already walks every
page file to do — and rewriting only the pages whose settled refs actually
moved, so rule 2 is untouched.

## 3. The page hash cannot see a change in nesting

`canonical_body` emits an opening token per element and never a closing one, so
the canonical string does not encode the tree. Two structurally different
bodies canonicalise identically:

```python
a = "<div><p>a</p><p>b</p></div>"        # two paragraphs
b = "<div><p>a<p>b</p></p></div>"        # one paragraph containing another

canonical_body(a) == canonical_body(b)   # '<div>\n<p>\na\n<p>\nb'
content_hash(a)   == content_hash(b)     # True
flatten_text(a)   == flatten_text(b)     # True — 'a b'

extract_blocks(a) # [{'kind':'paragraph','text':'a'}, {'kind':'paragraph','text':'b'}]
extract_blocks(b) # [{'kind':'paragraph','text':'a b'}]
```

Same hash, same chunk text, **different `blocks`**. Gate 2 compares the page
record, the record carries this hash, so a page whose block structure changed
is skipped and the snapshot keeps asserting the old shape. The same holds for a
`<figure>` boundary moving around a following paragraph, which changes what
`chunker._group` treats as one unit and therefore how a long section fragments
— which changes `chunk_ref`s.

`ARCHITECTURE.md` §Skip logic is explicit that normalisation must let the hash
"ignore the classes and ids Drupal rewrites while still noticing a changed
`href`". It notices the href. It does not notice the nesting, and nesting is
what `blocks` and the fragment boundaries are made of.

No evidence this has fired on the live corpus — the 0.7.0 records are exactly
what the current code produces from the current `raw/`. It is a hole in the
gate, not a corruption. Appending a closing token per element in
`canonical_body` closes it; that changes every `content_hash` in the corpus, so
it is an `EXTRACTOR_VERSION` bump and a full rebuild, which is the same cost
`SOURCE_NOTES.md` §4 already prices for the block-boundary fix. Doing both in
one change costs one rebuild rather than two.

## 4. `extract_images` can order its output two ways

```
PYTHONHASHSEED=0  ({'src': 'a.png', 'alt': None}, {'src': 'a.png', 'alt': ''})
PYTHONHASHSEED=1  ({'src': 'a.png', 'alt': ''},  {'src': 'a.png', 'alt': None})
```

`seen` is a `set`, and the sort key is `(src, alt or "")`, which collapses
`None` and `""` to the same value. Two entries sharing a `src` where one
carries no `alt` attribute and the other an empty one therefore tie, and
`sorted` falls back to set iteration order, which is hash-seed dependent.

Latent today: no image in the corpus carries an `alt` attribute at all, so no
tie exists. It is triggered by precisely the amendment the field was added to
detect — *"Accessibility fix – alternative text for images"*, one of the
Manual's own reasons on 28 pages. The first page where IP Australia adds an
empty `alt` beside a bare one starts rewriting itself on alternate runs.

Sorting on `(src, alt is None, alt or "")` — or on the repr — makes the key
total and the output stable.

---

# Part two — structure, and what it costs the ontology

Everything in this part is working as designed. It is here because the design
loses information the graph you have described will want, and the cheapest time
to keep it is before the corpus is seeded.

## 5. `internal_refs` records no provenance, and it is the one edge type that should

This is the largest structural gap.

`provisions` carries `extraction: href|regex` and `certainty:
explicit|default|ambiguous`, and `SCHEMA.md` is emphatic about why: *"The
Manual hyperlinks Act sections to AustLII, so an `href` edge is the authors
telling you what the paragraph is about. A `regex` edge is our inference…
Collapse them into one field and you lose the only signal separating them."*

`internal_refs` is a flat array of strings. The same distinction exists and is
discarded. Recomputed from the stored records:

| Where the ref came from | Refs |
|---|---|
| An href naming a page in the nav — the authors' own link | 359 |
| A bare `part N.M` in the prose — our inference | 34 |
| Both, in one chunk | 21 |

Eight per cent of the Manual-to-Manual edge set is regex inference stored
identically to an authored hyperlink — and finding 1 shows that at least three
of those 34 are wrong. A consumer cannot filter them out, because there is
nothing to filter on. The rule the repository applies to statute, it does not
apply to itself.

Also lost, and all of it deterministic:

- **The anchor text.** `provisions` keeps `mention`; `internal_refs` keeps no
  equivalent, so the words the Manual hung the reference on are gone.
- **The href.** Recoverable from `links` only by matching hrefs back through
  `normalise_url`, which is a join the consumer must reimplement.
- **Position.** `links` has offsets; `internal_refs` is sorted and
  deduplicated, so where in the passage the reference sat is not recoverable
  without the guess `links` was introduced to avoid.
- **Multiplicity.** Two references to one page are one entry.

For a knowledge graph this is the difference between an edge you can weight and
an edge you cannot. The retrieval design you describe — structured search
first — wants exactly this: *follow authored links; offer regex-derived
neighbours as suggestions; route the ambiguous ones to review.* None of those
three is expressible against the current field.

The shape that fixes it is the one `provisions` already uses, and it is a
strictly additive change:

```json
{ "ref": "TMM/Part14/6/6/5", "extraction": "href", "mention": "6.5 Claims for class headings" }
{ "ref": "TMM/Part22/15",    "extraction": "regex", "certainty": "default", "mention": "part 22.15.7" }
```

That also gives finding 1 somewhere honest to put itself: a locally-qualified
bare reference becomes `certainty: "ambiguous"` rather than a confident wrong
answer, and rule 3 is satisfied without dropping anything.

## 6. The heading tree is not addressable

`heading_path` is a flat list of strings. `chunker._Heading` carries a `level`
and a `source`; neither reaches the output, and only the leaf's `source`
survives as `heading_source`. Consequences, measured:

- **899 of 2,460 chunks have an ancestor heading that owns no `chunk_ref`.**
  `SOURCE_NOTES.md` §27 is right not to chunk a heading whose content lives in
  its subsections — but it means the parent node of those 899 chunks exists in
  `heading_path` as a string and nowhere else. Building a `hasParent` edge
  requires string-matching heading text within a page, which is precisely the
  fragile join `chunk_ref` exists to replace.
- **The level is gone.** `SOURCE_NOTES.md` §28 documents nine parent/child
  pairs where the Manual's numbering and its markup disagree about nesting, and
  says `heading_path` follows the markup. A consumer cannot see that it did,
  because the depth that decision was made on is not in the record.
- **`heading_source` describes the leaf only.** One chunk today
  (`TMM/Part29/9#7`) is marked `"markup"` while sitting under an ancestor that
  was promoted from a bold paragraph. `SCHEMA.md` tells a consumer that
  filtering to `markup` yields "strictly what the Manual marked up". For that
  chunk it does not, and the record cannot say so.

None of this needs an inference. The chunker has the level and the source of
every heading in the path at the moment it builds `heading_path`, and throws
them away one line later. Carrying them — either as a parallel array or by
making `heading_path` an array of objects — is a schema change, not a new
reading of the source. Given the ontology is the goal and the corpus is still
unseeded, this is the change with the best ratio of cost to future pain.

A related point, not a defect: **a `chunk_ref` cannot be split back into page
and heading without the record.** `TMM/Part60/4/13/4/13/2/1` is page
`TMM/Part60/4/13`, heading `4.13.2.1`, and nothing in the string says where the
boundary is. There are no collisions today — I checked all 2,460 — and
`page_ref` is always on the chunk, so this is safe as long as a `chunk_ref` is
never used as a bare citation key without its record. It is worth stating as an
invariant and pinning with a test, because a graph is exactly the place where
bare keys start travelling on their own.

## 7. Two pages claim address 20.2, and nothing records it

`TMM/Part20/3` — nav title `3. Definition of sign` — prints its own `<h1>` as
**`Part 20.2. Definition of sign`**. `TMM/Part20/2` prints `20.2. Background to
definition of a trade mark`. Both are in the source; the canonical URL confirms
the served page.

The pipeline takes the nav, which is correct — §2 is the reason the nav is
load-bearing — and records nothing about the conflict. So a bare reference to
"Part 20.2" resolves confidently to `TMM/Part20/2`, and if the author meant the
page that *prints* 20.2 the edge is wrong, silently. The two fields disagree in
the record and no field says they disagree.

This is the case CLAUDE.md rule 1 covers directly: *"Where the source is
genuinely ambiguous, record the ambiguity in the data and move on — do not
resolve it."* The disagreement is deterministically detectable — compare the
`<h1>`'s leading address against `page_ref`, which is two lines — and there are
exactly two pages in the corpus where it fires:

| page_ref | h1 | h1 implies |
|---|---|---|
| `TMM/Part20/3` | `Part 20.2. Definition of sign` | `TMM/Part20/2` — **a different, real page** |
| `TMM/Part1/x-1.-introduction7` | `Part 1.1. Introduction` | `TMM/Part1/1` — unclaimed |

The second is milder and worth a separate note. §2 decided not to invent `1.1`
for `Part 1. Introduction`, because the nav title qualifies down to nothing —
and that reasoning is sound *about the nav*. But the page itself prints
`Part 1.1.` in its `<h1>`, which is not an inference, and `TMM/Part1/1` is
claimed by nobody. The Manual does say it; it says it somewhere the sitemap
parser does not look.

## 8. `_repeated_labels` counts headings that never become chunks

A latent regression of the §18 fix. `_repeated_labels` counts slug addresses
over *all* sections, including those `chunk_body` later declines to emit —
container headings (§27) and empty ones. A label that appears once as a
never-chunked parent and once as a real section is therefore treated as
repeated, and the real section is demoted to the positional form:

```
<h2>Disclaimer</h2><h3>Sub one</h3><p>…</p>     # 'Disclaimer' never chunked
<h2>Other</h2><p>…</p>
<h2>Disclaimer</h2><p>the real disclaimer text</p>

  TMM/Part9/1/sub-one
  TMM/Part9/1/other
  TMM/Part9/1#3          <- positional, though no other chunk claims the slug
```

Zero impact today: all 498 positional refs are accounted for — 496 page
preambles at `#1`, and the two Part 29.9 `XYZ Company` sections §19 documents.
But the demotion is silent, and what it silently reintroduces is the exact
exposure §18 measured and removed: a positional address that moves when
anything above it moves. Counting only the sections that are actually emitted
fixes it.

Worth noting alongside: a positional `#N` is inflated by how *earlier* sections
fragmented, so it depends on `MAX_CHUNK_CHARS`. Both Part 29.9 refs are already
in that state — `#7` and `#9` sit behind two split sections. Tuning the chunk
size would move them.

## 9. `corpus.pages` is not counted from the snapshot

`ARCHITECTURE.md` is careful about this: *"`corpus.*` describes the snapshot
**on disk**, counted by walking it, and is true whatever the run did."* Two of
its seven fields are not:

```json
"corpus": { "pages": 502, "parts": 54, "raw_files": 500, "chunks": 2460 }
```

`pages` and `parts` come from `len(sitemap)`, not from `iter_page_files`. 502 is
the nav inventory; there are 500 page files, because two nav entries 404
(§14). A consumer computing "pages yielding no chunks" as `corpus.pages` minus
the 485 pages that have them gets **17**; the answer is **15**. Two pages that
were never fetched read as two pages that came back empty — which is the
specific misreading the corpus/run split was introduced to prevent.

Either count them from disk, or move them under a third key that describes the
inventory. The numbers are both worth having; they are answers to different
questions and the block they sit in claims they are answers to one.

## 10. Nothing local tells you a chunker change moved the corpus

Gate 2 compares the **page record** only. A change confined to the chunker,
`blocks`, `links`, `tables` or `citations` alters no page field, so every page
passes gate 2 and the corpus is never re-cut. The control is
`EXTRACTOR_VERSION`, which sits in the page record and forces a rebuild when
bumped — documented in `SCHEMA.md`, and correct.

Nothing enforces it, and the pre-commit checklist cannot catch a missed bump:

```
$ python -m tmm_snapshot.crawl --from-raw --dry-run
  unchanged        500 (gate 2)
  chunks cut       0
```

The dry run short-circuits at gate 2 and never chunks anything, so it reports a
clean corpus for a chunker change that would rewrite half of it. The third
command in CLAUDE.md's list is a live fetch of five pages, which does not touch
the question either. The tests cover fixtures; they do not cover the corpus.

Adding `--force` to a `--from-raw --dry-run` gives exactly the missing check —
"would this change any of the 500 page files?" — in about 25 seconds and with
no network. It is the command that found the byte-identical result at the top
of this review, and it belongs in CLAUDE.md's pre-commit list in place of, or
beside, the live one.

---

## Documentation drift

The prose docs are the specification here, and other instances work from them,
so counts that no longer match the output are a correctness problem rather than
a tidiness one. Measured against `snapshot/`:

| Claim | Where | Stated | Actual |
|---|---|---|---|
| internal_refs | `SCHEMA.md`, `SOURCE_NOTES.md` §22 | 411, 32 chunk-level | **417, 28** |
| ambiguous provision edges | `SOURCE_NOTES.md` §21 | 134 | **118** |
| regex provision edges | `SOURCE_NOTES.md` §21 | 1,939 | **1,952** |
| loose inline `text` blocks | `blocks.py` docstring | 1,454 | **4** |
| anchors reaching no other field | `links.py` docstring vs `chunker.Chunk` | 792 vs 766 | 792 |
| Manual links not in the nav | `SOURCE_NOTES.md` §29 | 47 | **44** |
| image-only pages | `page.schema.json` | "Nine pages" | **8** (§16 says 8) |
| chunks / % heading-addressed | `SOURCE_NOTES.md` §18 | 1,561 of 2,151 (72%) | 1,561 of **2,460 (63%)** |

The last is the one to fix rather than footnote: §12's table is explicitly *"the
reading taken on the day"* and may stand, but §18 states its result in the
present tense against a corpus that has since grown by 309 chunks.

`blocks.py`'s 1,454 is worth a second look — it is not drift, it is the
measurement from *before* the §23 `figure` fix, and the fix is what took it to
4. The docstring records the disease as if it were the cure.

---

## What I would do, in order

1. **Finding 1** — three wrong Part edges, in the data now. Drop the
   locally-qualified bare references, or read them locally. Smallest change,
   largest correctness gain.
2. **Finding 2** — cross-reference rot. Everything else degrades gracefully;
   this one degrades on a schedule and leaves the snapshot failing its own
   validator with the crawl reporting success.
3. **Finding 5** — provenance on `internal_refs`. Additive, and it is the field
   the retrieval layer will lean on hardest. Doing it at the same time as 1
   gives the ambiguous case somewhere to live.
4. **Finding 6** — heading level and per-ancestor source. Do it before the
   corpus is seeded, not after.
5. **Findings 3, 4, 7, 8, 9, 10** — one rebuild carries 3 and 7 together, and
   `SOURCE_NOTES.md` §4's deferred block-boundary fix should ride along with
   them rather than pay for a third full-corpus diff.

Findings 3, 4 and 8 are latent — no wrong byte in today's snapshot. They are in
this list because each one fires on an ordinary Manual amendment, and each
fires silently.
