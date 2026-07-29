# Architecture

## The shape of the thing

```
robots check ─> fetch ─> sitemap ─> per page: fetch ─> parse ─> chunk ─> extract ─┐
                                                  │                               │
                                            304 / hash match ─> skip              │
                                                                                  v
                                     write <─ resolve cross references <─ chunk inventory
```

Two phases, and the split is not an optimisation — see §Two phases. No state
beyond the previous snapshot on disk, which is read to decide what can be
skipped. The pipeline is a pure function of (live site, previous snapshot) →
new snapshot.

## Settling

A cross reference is a fact about **two** pages, and the skip gates only ever
ask about one of them.

`_resolve_refs` reached only the pages a run re-cut. So a heading renamed on
page B left every unchanged page A that cited it holding an address that no
longer existed: A passed gate 2, was never chunked, and kept refs settled
against an inventory that had moved under it. The crawl exited 0, the snapshot
failed its own validator, and no later crawl repaired it — A was unchanged
every time. Only `--force` cleared it. The reverse was worse for being legal: a
reference that had coarsened to page level because its heading was absent
stayed coarse for ever once the heading came back, and nothing reported it,
because a page-level ref is valid output.

`_settle_stored` closes it. After `_resolve_refs`, every page file the run did
**not** cut is read, its candidates re-derived, and its refs re-settled against
the same inventory. Only pages whose refs actually moved are written; on a
corpus that has not shifted this walks 500 files and writes none.

Two properties make it a re-reading of the same evidence rather than a second
reading of it:

- **`extract_internal_refs` takes `links` and `text`, not markup.** The stored
  `links` hold every anchor's href verbatim and `text` holds the words, so one
  function reads a live chunk and a stored one. Had it kept taking a DOM
  fragment, a page skipped at gate 2 would have needed a second implementation
  over the record, and the two would eventually disagree. Same argument as
  `flatten_spans` walking once for both the text and the offsets.
- **`resolve_internal_refs` is idempotent.** A settled ref is a valid candidate,
  which is what lets a stored record be re-settled without being re-cut. Pinned
  by a test, because the whole pass rests on it.

## Two phases

Everything is cut before anything is written.

An internal cross reference can name a heading rather than a page: 137 of the
Manual's internal links carry a `#fragment` that is the Drupal slug of the
target heading, and 47 of those open with the number the Manual prints. That
number is what the chunker builds the target's `chunk_ref` from, so the address
is fully determined — but whether that heading still exists is a fact about a
*different page*, and the page holding the link cannot know it.

Resolving it where it is found is therefore impossible without guessing, and
guessing is what rule 3 forbids. Before 0.5.0 the pipeline did the honest thing
available to a single pass and coarsened every reference to its page, so all 399
of them addressed pages and none addressed a chunk.

So `_process` stops after chunking and hands back a `Prepared`. Once the whole
scope has been cut, `_chunk_inventory` unions the refs this run produced with
the refs already on disk for pages it skipped — a page whose chunks moved is a
page that failed gate 2 and was re-cut, so the union is exactly the state the
snapshot is about to be in. `_resolve_refs` then settles every candidate against
it, and `_commit` writes.

What is held back is the records and their text, about two megabytes, not the
44 MB of source HTML. A reference whose heading has gone falls back to its page
rather than being dropped: the page half was established by URL and is still
true.

## Two pipelines

`tmm_snapshot` reads the Manual; `frl_snapshot` reads the Act and the
Regulations. They are siblings, not layers — different source, different fetch,
different parse — and neither imports the other's internals. What they share is
stated once and asserted in tests:

- **The reference grammar.** `TMA1995/s41` is what the Manual's citation layer
  emits and what the legislation snapshot uses as a provision ref. That is the
  join between the corpora, and it is the reason `frl_snapshot.references`
  *reuses* `tmm_snapshot.citations` rather than re-implementing it — a second
  reading of the same references would agree with the first until, quietly, it
  did not. `LEGISLATION_NOTES.md` §8.
- **The three rules, and the serialisation settings that make rule 2 hold.**
  `frl_snapshot.config.JSON_DUMP_KWARGS` is `tmm_snapshot`'s, imported rather
  than restated.

The one deliberate asymmetry is in the address. A Manual `page_ref` carries its
Part because the nav is the only thing that makes a page unique. A provision ref
does **not** carry its Part, because a section number is already unique within
its instrument and putting the Part in the address would break every citation
the moment a Part was reorganised. Where a number genuinely is not unique —
Schedule clauses and items restart at 1 in every Schedule — the Schedule is in
the ref.

## Repository layout

```
CLAUDE.md               orientation, loaded every session
ARCHITECTURE.md         this file
SOURCE_NOTES.md         the Manual's quirks
LEGISLATION_NOTES.md    the Register's quirks
SCHEMA.md               data contract in prose
TASKS.md                work packages
schema/
  page.schema.json      contract: page record
  chunk.schema.json     contract: chunk record
src/tmm_snapshot/
  __init__.py
  config.py             constants, URLs, rate limits, UA string
  fetch.py              HTTP with caching, politeness, retries
  sitemap.py            nav tree -> page inventory
  page.py               page-level metadata extraction
  chunker.py            body -> chunks
  citations.py          provisions, cases, internal refs
  tables.py             table markup -> the grid
  blocks.py             chunk markup -> the paragraphs and list items
  links.py              chunk markup -> the hyperlinks, and where they sit
  writer.py             deterministic serialisation to snapshot/
  diff.py               compare two snapshots, emit a change report
  crawl.py              orchestration, CLI entry point
  validate.py           validate snapshot/ against schema/
src/frl_snapshot/
  config.py             the instrument registry, API base, politeness
  api.py                the Register's OData API, and only what we need of it
  docx.py               .docx -> ordered stream of styled blocks. One reading.
  structure.py          block stream -> containers and provisions
  units.py              a provision's blocks -> its numbered tree. Plan, then address.
  endnotes.py           the compilation's own amendment history
  references.py         statutory cross references, via tmm_snapshot.citations
  writer.py             deterministic serialisation to snapshot/legislation/
  crawl.py              orchestration, CLI entry point
  validate.py           validate snapshot/legislation/ and the cross-corpus join
tests/
  fixtures/             saved HTML, committed, never fetched at test time
  test_*.py
snapshot/               THE DELIVERABLE — see below
viz/                    the published viewer — a READER of snapshot/, see below
  build.py              snapshot/ -> static bundle. Not a package; src/ cannot import it.
  app/                  index.html, app.css, app.js. No dependencies, no build step.
.github/workflows/
  crawl.yml             scheduled crawl, opens a PR on change
  pages.yml             build viz/ from snapshot/ and deploy to GitHub Pages
```

**`viz/` is downstream of everything else and has no way back upstream.** It
reads both halves of the snapshot and writes a bundle to `viz/dist/`, which is
gitignored and rebuilt on deploy. It adds no field to a chunk and none to a
provision: every chunk and provision object in the bundle is a strict
field-subset of the record on disk, and `tests/test_viz_build.py` fails if that
stops being true or if a build so much as changes a byte under `snapshot/`.
Anything the viewer needs that the pipeline does not assert — a reverse citation
index, a table count, the join from a Manual chunk to the provision it cites —
is derived at build time and emitted beside those records. `viz/README.md` for
the rest.

## Snapshot layout

```
snapshot/
  manifest.json                       run metadata; the only file that changes every run
  sitemap.json                        the nav tree as inventory
  retired.json                        what vanished, and in which run
  pages/
    Part22/
      TMM-Part22-1.json               page record + its chunks
      TMM-Part22-15.json
    Part32B/
      TMM-Part32B-2-3.json
    _retired/
      Part32B/
        TMM-Part32B-2-3.json          gone from the nav, kept so citations resolve
  raw/
    Part22/
      TMM-Part22-1.html               verbatim source, unmodified
  legislation/
    manifest.json                     run metadata for the legislation pipeline
    TMA1995/
      instrument.json                 identity + compilation state + amendments
      contents.json                   the structure in document order
      endnotes.json                   the instrument's own amendment history
      provisions/
        pt4/
          TMA1995-s41.json            the section, and its numbered units
      raw/
        TMA1995-C2024C00545.docx      verbatim compiled document
    TMR1995/
      provisions/
        sch3/
          TMR1995-sch3-item1.json
```

**`snapshot/legislation/` is a sibling of `pages/`, not a child.**
`tmm_snapshot.validate` walks `snapshot/pages/` and would otherwise try these
files against the Manual's schema.

**Why the section is the file.** It is the citable unit — everything cites
"section 41", never "Part 3, seventh paragraph" — it is the unit Endnote 4
records amendments against, and it is a readable size for a diff. Its
subsections and paragraphs live inside it, exactly as a Manual page's chunks
live inside the page file, and for the same reason: one file per unit gives
thousands of tiny files, one file for the Act gives an unreadable diff.

**Three things a provision file deliberately does not carry**, each of which
would turn one amendment into a whole-corpus diff:

- `register_id` — changes on every compilation. It lives on `instrument.json`,
  which is one file and *should* move every time.
- An instrument-wide ordinal — inserting section 41A would renumber everything
  after it. Document order lives in `contents.json`, the analogue of
  `sitemap.json`.
- How the bytes were obtained — that is a property of the run, so it is in
  `manifest.json`. Left on the record it flips between `api` and `raw` and makes
  `--from-raw` and a live crawl rewrite the file at each other.

**Why keep the raw `.docx`.** Same two reasons as the Manual's raw HTML: it is
what a parser fix is re-run against without going back to the Register, and it
is the audit artefact. Unlike the HTML it is a zip, so it diffs as a binary
blob and contributes nothing readable to a pull request — the readable diff for
this corpus is the provision files, which are finer-grained than the Manual's
page files. It is safe to store verbatim because the Register pins every zip
entry's timestamp, so re-fetching an unchanged compilation gives identical
bytes.

`retired.json` sits at the snapshot root rather than inside `pages/_retired/`
so that everything under `pages/` is a page file and the validator can walk the
tree without special cases.

**`manifest.json` has two blocks and they answer different questions.**
`corpus.*` describes the snapshot **on disk**, counted by walking it, and is
true whatever the run did. `run.*` describes **only what this run touched**.
`corpus.pages` and `corpus.parts` were the exception until 0.8.0 and should not
have been — they counted the nav inventory, so the block reported 502 pages
beside 500 files and a reader working out how many pages yield no chunks got 17
rather than 15. How many were in scope is `run.pages_in_scope`; the inventory's
own counts are in `sitemap.json`.
They are not expected to agree, and a reader who assumes they should will
misread a healthy crawl as data loss: after the 28 July 2026 crawl `run.chunks`
said 2084 while the snapshot held 2151, the 67 belonging to 19 pages skipped at
gate 2 — never chunked, so never counted. Nothing was wrong except the name.
That field is now `run.chunks_cut`, and `corpus.chunks` carries the disk total.
Keep the distinction when adding any future count: a number under `run` is a
number about the run.

**Why page-level files.** One file per chunk gives thousands of tiny files and a
diff that is hard to read. One file for everything gives a diff that is
impossible to read. One file per page means a Manual amendment shows up as a
handful of changed files, and inside each you can see which paragraph moved.

**Why keep raw HTML.** It is the ground truth. It lets you re-parse the whole
corpus after a parser fix without re-crawling, which you will need to do several
times. It is also the audit artefact — the evidence for what the Manual actually
said on a date. Keep it unmodified and uncompressed: git packs it well, and a
gzipped file diffs as a binary blob.

**Filenames.** Derive from `page_ref` by replacing `/` with `-`. `TMM/Part22/1`
becomes `TMM-Part22-1.json`. Deterministic, sortable, no collisions.

**Size.** Measured in Task 2: 502 pages averaging 88 KB, so `snapshot/raw/` is
about 44 MB, and after the first crawl only changed pages are rewritten. See
`SOURCE_NOTES.md` §12; the numbers move into `manifest.json` when
`write_manifest` lands. If the repo ever passes roughly a gigabyte, raise it
rather than reaching for Git LFS unilaterally — a separate data repo may be the
better answer.

## Byte-stability

This deserves its own section because it is the rule most easily broken by
accident.

- `json.dump(..., sort_keys=True, indent=2, ensure_ascii=False)` and a trailing
  newline. Always.
- Arrays sorted by a stable key: provisions by `id`, cases by `id`,
  `internal_refs` lexically. Chunks by `ordinal` (already stable).
- **No run timestamp in a page file.** A page record may carry a
  `first_seen`-style date, but only if it is written once and never rewritten
  while content is unchanged. `page.schema.json` requires a `crawled_at`, and
  that is how it is satisfied: the writer carries the stored value forward
  whenever every other field in the document matches, so it means *when this
  version of the page was first seen*. When the run happened is a property of
  the run, and lives in `manifest.json`.
- The writer must compare against the existing file and skip the write entirely
  when bytes are identical. Do not rely on git to notice — rely on git to notice
  *nothing*, because you did not touch the file.

Test for this explicitly: run the pipeline twice over a fixture set and assert
zero files changed on the second run.

## Module boundaries

These signatures are fixed. Instances work against them in parallel. Changing one
is a breaking change to raise, not to make.

### `fetch.py`

```python
@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int            # 200, 304, or error status
    html: str | None       # None on 304 or error
    etag: str | None
    last_modified: str | None

class Fetcher:
    def __init__(self, cache_dir: Path, delay_s: float = 1.0, ua: str = ...): ...
    def check_robots(self) -> None: ...          # raises if disallowed
    def get(self, url: str) -> FetchResult: ...  # sends conditional headers
```

### `sitemap.py`

```python
@dataclass(frozen=True)
class NavPage:
    url: str
    page_ref: str          # 'TMM/Part22/1'
    part_id: str           # 'Part22'
    part_title: str
    nav_title: str
    nav_ordinal: int
    kind: str              # 'body' | 'landing' | 'annex'

def build_sitemap(html: str) -> dict[str, NavPage]:  # keyed by normalised url
def write_sitemap(pages: dict[str, NavPage], path: Path) -> None:
```

### `page.py`

```python
@dataclass(frozen=True)
class PageRecord:
    page_ref: str
    part_id: str
    url: str
    nav_title: str
    h1: str | None
    content_hash: str
    date_published: date | None
    last_amended: date | None
    amendment_note: str | None
    extractor_version: str
    archived: bool = False
    images: tuple[dict[str, str | None], ...] = ()   # added by the 0.3.0 review
    printed_page_ref: str | None = None              # added by the 0.7.0 review

def parse_page(html: str, nav: NavPage) -> tuple[PageRecord, Tag]:
    """Returns the record and the cleaned body element for the chunker.
    Raises if the page is not in the sitemap or the markup shape is unrecognised."""

def flatten_text(node: Tag) -> str:
def flatten_spans(node: Tag, names: frozenset[str]) -> tuple[str, list[tuple[Tag, int, int]]]:
```

`flatten_text` is the corpus's one reading of an element as words, and every
other module takes it from here rather than calling `get_text` — which is wrong
for this markup in both directions, for the reasons in its docstring.

`flatten_spans` is the 0.7.0 addition and returns the same string plus, for each
named element, the offsets its own words occupy in it. Both run the same walk,
so an element's span cannot come to disagree with the text it is a span of.

### `chunker.py`

```python
@dataclass
class Chunk:
    chunk_ref: str
    page_ref: str
    text: str
    heading_path: list[str]
    ordinal: int
    content_hash: str
    kind: str
    fragment: dict | None
    provisions: list[dict]
    cases: list[dict]
    internal_refs: list[str]
    tables: list[dict] = field(default_factory=list)   # added by the 0.3.0 review
    blocks: list[dict] = field(default_factory=list)   # added by the 0.5.0 review
    heading_source: str | None = None                  # added by the 0.6.0 review
    links: list[dict] = field(default_factory=list)    # added by the 0.7.0 review
    headings: list[dict] = field(default_factory=list) # added by the 0.7.0 review

def chunk_body(body: Tag, page: PageRecord, nav: NavPage,
               sitemap: dict[str, NavPage] | None = None) -> list[Chunk]:
```

`tables`, `blocks`, `heading_source`, `links` and `PageRecord.images` are
additions made after reviewing a complete crawl, and all five are defaulted, so
every existing caller and every existing test still compiles against the
original shape. What they are for is in `SOURCE_NOTES.md` §§16–19 and §§23–29:
the pipeline was dropping 121 tables' worth of structure and 169 images on the
floor, eight pages whose entire content is an image were recording as
indistinguishable from blank, 18,735 paragraphs and list items were flattening
into 2,151 undifferentiated strings, and 2,218 hyperlinks were being discarded
with the markup that carried them.

**`heading_source` is the one field recording an inference, and it is why the
inference is allowed.** 456 of the Manual's numbered subsections are set as
bold paragraphs rather than `<h2>`–`<h4>`, so cutting on markup alone left 39%
of the corpus text with no heading at all. The chunker now promotes a bold
paragraph whose number extends the page's own number, and marks every chunk cut
that way `"emphasis"` rather than `"markup"`. A consumer that wants strictly
what the Manual marked up filters on the field and loses nothing it was
entitled to. `SOURCE_NOTES.md` §25 for the rule and the one case it declines.

One consequence for anyone changing `chunker._sections`: heading ancestry is
now keyed on an explicit **level**, not on the tag name, because an inferred
heading has no tag name to read a depth from. For an `<h2>`–`<h4>` the level is
still the digit in the tag, so a page with no inferred headings cuts exactly as
before.

The `sitemap` argument is an addition made by T5, not part of the original
contract. `internal_refs` are resolved through the inventory and dropped when
they do not resolve, so the chunker cannot produce them without it. It is
optional and defaults to none-resolvable, so the three-argument form still
works — but a caller that omits it gets empty `internal_refs`, and the only
caller that should is a test.

### `citations.py`

```python
def extract_provisions(body_fragment: Tag, text: str) -> list[dict]:
def extract_cases(text: str) -> list[dict]:
def extract_internal_refs(links: list[dict], text: str, sitemap: dict[str, NavPage],
                          page_ref: str | None = None) -> list[dict]:
def resolve_internal_refs(refs: list[dict], chunk_refs: frozenset[str],
                          page_refs: frozenset[str]) -> list[dict]:
def internal_ref_key(record: dict) -> tuple[str, ...]:
```

The last two signatures changed in `ingest/0.8.0` and both changes are the
0.7.0 review being acted on. `extract_internal_refs` reads the chunk's links
and words rather than its markup, so that one function settles a live chunk and
a stored one — see §Settling. And both now carry records rather than bare
strings, because a cross reference has a provenance and the field was throwing
it away: 378 of the corpus's 418 edges are the Manual's own hyperlinks and 40
are our reading of its prose, and nothing said which was which.

The first three are called by the chunker, per chunk. Kept separate because they
carry the densest regex logic and the most test cases.

`resolve_internal_refs` is called once per run by `crawl.py`, not by the chunker,
and is the 0.5.0 addition. A link carrying a `#fragment` names a heading on
another page, and `extract_internal_refs` can only get as far as a *candidate*
chunk_ref because whether that heading still exists is a fact about a page this
one has not read. See §Two phases below.

### `tables.py`

```python
def extract_tables(body_fragment: Tag) -> list[dict]:
```

Also called by the chunker, per chunk, and separate for the same reason. Turns
table markup into the grid — rows, cells, spans, and a header row only where
the markup declares one. `SOURCE_NOTES.md` §17 for what the Manual's tables
actually look like and why the first row is never assumed to be a header.

### `blocks.py`

```python
def extract_blocks(body_fragment: Tag) -> list[dict]:
```

The same argument as `tables.py`, applied to the prose. `chunk.text` joins a
section's paragraphs and list items with single spaces, which is the correct
verbatim reading and destroys every boundary in it. This records the boundaries
the markup already asserts, from tag names and tree depth alone.

Joining the blocks' text reproduces `chunk.text` exactly. That is asserted in
`validate.py` over the whole snapshot and in `tests/test_blocks.py` over every
saved page, and it is what stops `blocks` drifting into a second, differently
worded copy of the chunk. `SOURCE_NOTES.md` §19.

Two things about the walk, both found by the 0.6.0 review. `<figure>` is
transparent here and **opaque** in `chunker._CONTAINER_TAGS`: the CMS wraps
every table in one, so to the chunker the figure is a single unit that cannot
be split across a fragment boundary, while to this module it is scaffolding
hiding the grid. And an `image` block is the only block with no `text` — an
`<img>` contributes no words, and a block carrying `""` would put a stray space
into the join above. `SOURCE_NOTES.md` §§23–24.

### `links.py`

```python
def extract_links(fragment: Tag) -> list[dict]:
```

The 0.7.0 addition, and the same argument a third time: `chunk.text` is the
words with the markup gone, and every `<a>` the Manual set went with it.
`provisions` and `internal_refs` kept what each was about — the provision
named, the page resolved to — deduplicated, sorted and positionless; 792 of the
corpus's 2,218 anchors matched neither and reached the snapshot in no form at
all. `SOURCE_NOTES.md` §29.

A link carries `href` verbatim and the offsets into `chunk.text` where its own
words sit, so `text[start:end] == link.text`. That is checked in
`validate._link_failures` over the whole snapshot and not in a test alone,
because an offset drifted by one underlines the wrong words while remaining
perfectly well-formed. The offsets come from `page.flatten_spans`, which walks
the tree once for both the text and the spans — a second walk would be a second
reading of the same markup, and the two would eventually disagree.

Unlike every other list on a chunk, `links` is neither sorted nor deduplicated
by the writer: document order is the Manual's own order, and two links to one
target are two links.

### `writer.py`

```python
def write_page(page: PageRecord, chunks: list[Chunk], root: Path) -> bool:
    """Returns True if bytes changed on disk."""
def rewrite_settled(path: Path, document: dict, now: str) -> bool:
def write_raw(page_ref: str, html: str, root: Path) -> bool:
def write_manifest(root: Path, stats: dict) -> None:
```

`rewrite_settled` is the narrow companion `_settle_stored` needs: a page skipped
at gate 2 was never parsed, so there is no `PageRecord` to rebuild one from, and
inventing one to satisfy `write_page`'s signature would invent the fields it
could not read. It takes a document read from disk with nothing but its
`internal_refs` changed.

### `diff.py`

```python
def read_snapshot(root: Path) -> Snapshot:      # a directory, loaded for comparison
def compare(before: Snapshot, after: Snapshot) -> Changes:
def render_report(before: Path, after: Path) -> str:
```

Added by T8; `render_report` is the signature the skeleton carried. A pure
function of two directories — no clock, no network, no git — so the same pair
renders the same bytes twice. Reading and comparing are separate from
rendering because the comparison is the part with an opinion: what counts as
retirement, what counts as a page merely renamed in the nav, and what a
partial run is not allowed to conclude.

## Skip logic — legislation

One gate, and it is better than anything the Manual can have. `Versions/Find`
returns the `registerId` of the current compilation, which changes if and only
if a new compilation was registered. Comparing it to the stored one answers
"has this law been amended" exactly, for one small JSON GET, with no download
and no hashing. It cannot be defeated by a re-render that changes bytes without
changing law — which is precisely what a content hash cannot distinguish.

Its blind spot is `hasUnincorporatedAmendments`, and that is recorded rather
than papered over: true means amendments have commenced but are in no
compilation yet, so the document is out of date and `registerId` has not moved.
Nothing can be fetched in that state, so the flag reaches `instrument.json` and
the run report.

**A failed probe raises.** Treating an API error as "unchanged" freezes the
snapshot silently, which is worse than a crawl that stops.

## Skip logic — the Manual

Three gates, cheapest first:

1. **HTTP 304.** Conditional request returned not-modified. Skip everything.
2. **Page record unchanged.** Fetched and parsed, but every field of the record
   — the normalised body hash included — already says what the stored record
   says. Skip chunking, extraction and writing.

   The hash alone is not enough, and that is worth stating because it looks
   like it should be. A Part renamed in the nav changes `nav_title` and
   `part_id` without touching a word of the body; a hash-only gate skips the
   page and leaves the snapshot asserting the old name indefinitely. The saving
   this gate exists for is chunking and citation extraction, and comparing ten
   more strings does not touch it.
3. **Chunk hash unchanged.** Page changed somewhere, but this chunk did not.
   Still written (it lives in the page file), but flagged as unchanged in the
   run report so the diff tooling can summarise "3 of 14 paragraphs amended".

Gate 2 must compare the *normalised body*, not the raw HTML.

As measured in July 2026 the raw HTML happens to be byte-stable between fetches
(`SOURCE_NOTES.md` §12), so this is not currently load-bearing for the reason
originally given — but normalise anyway, for two that outlast it. The stability
is the CMS's to withdraw without telling us. And normalisation is what lets the
hash ignore the classes and ids Drupal rewrites while still noticing a changed
`href` — which matters, because *"Update hyperlinks"* is one of the Manual's own
amendment reasons and a text-only hash would skip those pages entirely.

## Retirement

A page that disappears from the nav is not deleted. Move it to
`snapshot/pages/_retired/` and record the run in which it vanished. Old citations
must stay resolvable, and a Part being restructured is exactly the event you most
want a record of.

Only a complete crawl may retire anything. A run filtered by `--part` or
`--limit` has not seen the inventory it would be drawing conclusions from, and
retiring from one would empty the snapshot.

Retirement means *gone from the nav*. A page still in the nav that the site
will not serve is a different thing — see `SOURCE_NOTES.md` §14 — and is
recorded in the run report and `manifest.json` under `run.unreachable`, with
whatever record we already hold left untouched. The raw HTML of a retired page
also stays where it is: it is the evidence for what the Manual said on a date,
and that does not stop being true when the page goes.

## CI

`.github/workflows/crawl.yml` runs on a schedule (weekly is a reasonable start;
tune once the real amendment cadence is known). It crawls, and if anything
changed it opens a pull request with the change report from `diff.py` in the
body. A human merges. That review step is the audit trail — it is where somebody
confirms whether an amendment was substantive practice change or a hyperlink
tidy-up, using the Manual's own `amendment_note` as the clue.

Never auto-merge. The point is the human read.

Three things about how it is wired (T9):

- **The 'before' state is a copy of `snapshot/` taken from the checkout before
  the crawl runs.** The report therefore describes exactly what the pull
  request's own diff shows, including — when last week's crawl is still
  unmerged and this week's branches from the same base — both weeks at once.
  That is the honest answer to "what would merging this change".
- **A run where only `manifest.json` moved opens nothing.** The manifest
  carries the run timestamp and so differs on every crawl; a pull request for
  it would be a pull request with nothing to review, every week, and the habit
  that teaches a reviewer is the one this arrangement exists to prevent.
- **`.cache/` is carried between runs.** It holds the `Last-Modified` and
  `ETag` values that make gate 1 fire, and without it every scheduled crawl
  costs the site 502 full responses instead of 502 `304`s.

`.github/workflows/ci.yml` runs `pytest` and the validator on every push. It
does not run `crawl --dry-run --limit 5`, which CLAUDE.md lists as the third
pre-commit check: that one is a live fetch of a Commonwealth agency site, and
firing it on every push to every branch is the whim the courtesy rules rule
out. Run it locally; the scheduled crawl is what exercises the network in CI.
