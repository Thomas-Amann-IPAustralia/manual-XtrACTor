# Review of the 0.5.0 chunks

> **Resolved in `ingest/0.6.0`.** All six findings were acted on; the snapshot
> in this repository is the rebuilt one. This document is kept as the record of
> what was wrong and how it was measured — the rules that replaced it live in
> `SOURCE_NOTES.md` §§23–28. Section 3 was implemented with a tighter rule than
> proposed here, and section 4 with a different one; both are noted in place
> below.

An assessment of `snapshot/` at `ingest/0.5.0` — 500 page files, 2,189 chunks,
12,926 blocks — asking one question: **what would a visualisation of this data
get wrong?**

Method: re-parsed every page in `snapshot/raw/` and compared against the
committed records. Where a fix is proposed it was probed against the whole
corpus first; where it was not probed, that is said.

## What is already sound

Stated first, because it bounds everything below. None of the findings are
about lost or wrong words.

- **Coverage is complete.** Word-level accounting over all 500 pages: every
  word of every cleaned body appears either in a chunk's `text` or in a
  `heading_path`. Zero missing tokens, corpus-wide.
- **Text is clean.** No double spaces, no leading or trailing whitespace, no
  control characters. One soft hyphen, which is genuine source content
  (Part 30.2's censored expletive). Twelve apparent run-together words — `PopSockets`,
  `ConAgra`, `MacBook`, `BitCoin`, `VapoRub` — are all genuine CamelCase in the
  Manual, not flattening artefacts.
- **Addresses hold.** 2,189 chunk_refs, all globally unique. Ordinals contiguous
  on every page. `heading_path[1]` equals the page `h1` on every chunk.
- **`join(blocks) == text`** on all 2,189 chunks.
- **Citations resolve.** 411 internal_refs, none dangling. 2,772 provisions,
  519 cases.
- 361 tests pass; the snapshot validates against `schema/`.

## 1. The Manual's subsection structure is mostly not in headings

**456 numbered subsections across 88 pages are set as bold paragraphs, not as
`<h2>`–`<h4>`.** The chunker cuts on headings and nothing else, so these
sections never become chunks and never enter a `heading_path`. Their text is
swallowed into whatever chunk they fall in.

The scale:

| | |
|---|---|
| Pages with no `<h2>`–`<h4>` at all, yet printing numbered subsections | 46 (178 subsections) |
| Pages with real headings *and* bold pseudo-headings | 43 (288 subsections) |
| Chunks holding 2 or more pseudo-headings | 149 |
| Chunk text sitting under an empty `heading_path` | 731,388 of 1,879,173 chars — **39%** |

Worst cases: `TMM/Part10/3` prints 36 numbered subsections and produces nine
positional chunks with empty heading paths; `TMM/Part47/1` prints 19 across
27,599 characters. A visualiser building a tree from `heading_path` shows those
pages as one undivided wall.

The markup is unambiguous — `<p><strong>1.1.3 Partnerships -</strong></p>` —
but promoting it to a heading is a heuristic, and rule 1 forbids that. What is
deterministic is the *fact of the markup*: a `<p>` whose entire content is a
single `<strong>` or `<b>`. Recording that on the block (`"emphasis": "strong"`)
is read off tag names alone, changes no chunk boundary and no address, and
lets the visualiser render the structure the Manual prints without this
pipeline asserting what it means. 780 paragraphs corpus-wide are wholly bold;
456 of them also open with a section number.

Not probed. It adds a field to `blocks`, so it wants its own decision.

> **As implemented:** stronger than this. The bold paragraphs are promoted to
> real heading boundaries, so they get a `heading_path` and an address, rather
> than only being flagged in `blocks`. The inference is fenced by the Manual's
> own numbering — the number must extend the page's own — which admits 471
> candidates and rejects exactly one across the corpus, and every chunk cut
> that way is marked `heading_source: "emphasis"`. Text with no heading fell
> from 39% to 29%; Part 10.3 went from 9 addressless chunks to 38 nested ones.
> `SOURCE_NOTES.md` §25.

## 2. Every CKEditor table is misfiled as a `text` block

The CMS wraps tables in `<figure class="table canvasRteResponsiveTable">`.
`figure` is in neither `blocks._TRANSPARENT` nor `blocks._KINDS`, so
`extract_blocks` falls through to `kind = "text"` and flattens the entire table
into one block.

- 106 of the corpus's 121 tables are inside a `figure`.
- Only **18 of 121** produce a `table` block.
- 104 chunks carry a table; only **17** have a `table` block.

`tables` still holds the correct grid — that layer is unaffected — but a
consumer reading `blocks` sees `TMM/Part10/x-annex-a1`'s 29-row table as a
single run-on `text` block, and has no way to tell *where in the prose* the
grid from `tables` belongs. Any visualiser that renders `blocks` and `tables`
together will duplicate the content and misplace it.

**Probed.** Adding `figure` to `blocks._TRANSPARENT` recovers all 121 tables as
`table` blocks across 45 pages, exactly matching the `tables` array, and
`join(blocks) == text` still holds corpus-wide. One line. It touches `blocks.py`
only — `chunker._units` should keep treating `figure` as a single unit, which is
what stops a table being split.

## 3. Three footnotes hold false section addresses

Parts 49, 52 and 55 set their footnotes as `<h4>` with the marker in a `<sup>`:

```html
<h4><span class="fontSizeMedium"><sup>2</sup> See AKT Consultants Pty Ltd
    v Alfa Laval Lund AB (2006) 70 IPR 347.</span></h4>
```

`_heading_address` reads `flatten_text(heading)`, which is `"2 See AKT
Consultants…"`, and `_LEADING_ADDRESS` matches the `2`. So footnote 2 is
addressed `TMM/Part55/2/2` — which reads as *Part 55, page 2, heading 2*, the
parent of sections `TMM/Part55/2/2/1` through `/2/2/5`. A citation to that
section resolves to a footnote.

| chunk_ref | what it reads as | what it is |
|---|---|---|
| `TMM/Part55/2/2` | heading 2 | footnote 2 |
| `TMM/Part49/2/1` | heading 1 | footnote 1 |
| `TMM/Part52/4/5` | heading 5 | footnote 5 |

This is not a weak address, it is a wrong one — the failure mode SCHEMA.md's
"a serial number is a citation that breaks silently" argument exists to prevent.

The distinguisher is deterministic and total: **`<sup>` occurs in exactly three
headings in the whole corpus, and is a footnote marker in all three.** Reading
the leading address only when its digits are not inside a `<sup>` sends these
three to the positional form, which is the honest address for a footnote.

> **As implemented:** they fall through to the *slug* form rather than the
> positional one — `TMM/Part55/2/2-see-akt-consultants-…`. That is the existing
> fallback for a heading the Manual does not number, needs no special case, and
> is a stronger address than a position. `TMM/Part55/2/2` now addresses
> section 2.2, as it always read.

Related, and lower stakes: because the footnotes are `<h4>` following the last
`<h3>`, the ancestry logic makes them children of the preceding section.
Footnote 2 carries `heading_path` `['2.5 Consideration of an award of costs…',
'2 See AKT Consultants…']`, so the tree hangs a page-level footnote under
section 2.5. Structurally faithful to the markup, and visibly wrong in a tree.

## 4. 26 container headings are emitted as content

The heading-as-content branch fires whenever a section has no content units.
That condition covers two different situations, and only one of them is the one
the branch was written for.

- **12 are genuine** — the Manual put the proposition *in* the heading. Part 61.3's
  `3.2 Documents that are not made available for public inspection…`, the
  footnotes above, Part 32A's convention titles. Correct behaviour, keep it.
- **26 are containers** whose content lives in the child sections beneath them.
  The Part 14 A13 glossary's 22 alphabet letters produce 22 chunks whose entire
  text is `"A"`, `"B"`, `"C"`…; `TMM/Part5/x-device-constituents` adds 3;
  `TMM/Part28/3` adds one. Their words are already carried in every child
  chunk's `heading_path`, so each is a contentless duplicate occupying an
  address — and 22 one-letter search hits in any index built from this.

Deterministic test: another section's heading ancestry begins with this
heading. `_sections` already computes the whole page before any chunk is cut,
so this is available exactly where `_repeated_labels` is. No words are lost by
suppressing them; the children carry them.

Not probed. It changes ordinals on four pages.

> **As implemented:** both rules, because they turned out to cover different
> cases. A length rule alone would have left the containers — and promoting the
> bold subsections of §1 took them from 26 to 52, since a heading immediately
> followed by its own first subsection also has no content of its own. A
> container rule alone would have left Part 23.2's bare `2.2`, whose `2.2.1`
> and `2.2.2` are siblings in the markup and so do not carry it.
>
> Containers are dropped silently, because their words survive in every child's
> `heading_path`. Headings under five characters with no subsections are
> dropped **loudly**, as a `SuppressedHeading` warning — that one really does
> remove words, and it fires exactly once in 500 pages. `SOURCE_NOTES.md` §27.

## 5. Images cannot be rendered

169 images across 39 pages. **None has alt text** — the attribute is absent in
the source, not dropped. `snapshot/raw/` holds HTML only, so the image bytes are
not in the snapshot; `src` is a site-relative path.

Consequences for a visualisation:

- **8 pages are an image and nothing else** and produce zero chunks
  (`SOURCE_NOTES.md` §16). There is nothing to render and no caption to fall
  back on — flowcharts in Parts 22, 35, 45 and the Part 54 summons formats.
- **Inline images have no position.** They sit loose in containers, and
  `extract_blocks` records a block only `if text := flatten_text(child)`, which
  is empty for an `<img>`. So `page.images` says a page has images and the block
  stream says where nothing is. 11 of the 169 sit inside table figures.

Both are scope decisions rather than defects — snapshotting the image bytes is a
change to what the deliverable *is*, and worth raising as one before a
visualisation promises to show them.

> **As implemented:** the position is recorded and the bytes are still not.
> `blocks` gains an `image` kind carrying `src`, and `chunker._group` no longer
> discards a unit that has an image but no text. 93 of the 169 images now have
> a place in the running order; the other 76 are in sections with no words at
> all, and a chunk needs text to exist. `SOURCE_NOTES.md` §24.

## 6. Numbering and markup disagree on three pages

Nine parent/child pairs where the Manual's own numbering says one heading is
under another but `heading_path` makes them siblings, because both are `<h3>`:

- `TMM/Part2/3` — 2.3.2.1 and 2.3.2.2 not under 2.3.2
- `TMM/Part23/2` — 2.2.1 and 2.2.2 not under 2.2
- `TMM/Part55/2` — the footnote case above

33 numbered parent/child pairs exist corpus-wide, so this is 9 of 33 — a high
rate on a small base. `heading_path` is faithful to the markup, and the markup
is what the pipeline is allowed to read; the disagreement is the Manual's. It
belongs in the record as an observation rather than a fix, but a visualiser
that builds its tree from `chunk_ref` numbering rather than `heading_path` will
draw a different tree, and the two need to agree on which is authoritative.

Also here: `TMM/Part23/2` contains `<h3>2.2</h3>` — a heading with a number and
no words. Its chunk text is literally `"2.2"`. Verbatim and correct; it will
look like a bug in any rendering, and it is not one.

## 7. Observed, no action

- **5 chunks exceed `MAX_CHUNK_CHARS` unsplit**, up to 5,136 chars. Four are a
  single table, one a single unit. By design — `_group` never splits inside a
  unit.
- **21 of 288 continuation fragments start with a lowercase letter.** All are
  list-item boundaries, where the preceding unit ended on a colon. Not
  mid-sentence breaks.
- **`TMM/Part39/x-annex-a1---certificate-of-registration` has zero chunks.** The
  source page body is empty Drupal scaffolding — not archived, no image, no
  words. A source fact, not an extraction failure. Worth a note so it is not
  re-investigated.
- **`cases` carry no party names.** Documented as intentional in SCHEMA.md
  §Citations. Restating only because a visualisation showing `CASE/2011/ATMO/63`
  with nothing beside it is thin, and that is a display decision, not a data one.
- **`certainty` is absent on 840 of 2,772 provisions.** Correct — it is defined
  for regex edges, and those 840 are `href` edges. A consumer must not read
  absent as unknown.

## Suggested order

1. **§2, the `figure` blocks fix.** One line, probed, no address changes, and it
   is the one actively producing wrong output rather than merely thin output.
2. **§3, the `<sup>` footnote addresses.** Small, total, and it is fixing three
   citations that are wrong rather than weak.
3. **§4, container headings.** Straightforward, changes ordinals on four pages.
4. **§1, bold pseudo-headings.** The largest effect on a visualisation and the
   one needing a decision about the block record before any code moves.
5. **§5, images.** A scope question, not a defect.
