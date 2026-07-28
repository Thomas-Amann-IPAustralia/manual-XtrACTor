# Architecture

## The shape of the thing

```
robots check ─> fetch ─> sitemap ─> per page: fetch ─> parse ─> chunk ─> extract ─> write
                                                  │
                                            304 / hash match ─> skip
```

One pass. No state beyond the previous snapshot on disk, which is read to decide
what can be skipped. The pipeline is a pure function of (live site, previous
snapshot) → new snapshot.

## Repository layout

```
CLAUDE.md               orientation, loaded every session
ARCHITECTURE.md         this file
SOURCE_NOTES.md         the Manual's quirks
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
  writer.py             deterministic serialisation to snapshot/
  diff.py               compare two snapshots, emit a change report
  crawl.py              orchestration, CLI entry point
  validate.py           validate snapshot/ against schema/
tests/
  fixtures/             saved HTML, committed, never fetched at test time
  test_*.py
snapshot/               THE DELIVERABLE — see below
.github/workflows/
  crawl.yml             scheduled crawl, opens a PR on change
```

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
```

`retired.json` sits at the snapshot root rather than inside `pages/_retired/`
so that everything under `pages/` is a page file and the validator can walk the
tree without special cases.

**`manifest.json` has two blocks and they answer different questions.**
`corpus.*` describes the snapshot **on disk**, counted by walking it, and is
true whatever the run did. `run.*` describes **only what this run touched**.
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

def parse_page(html: str, nav: NavPage) -> tuple[PageRecord, Tag]:
    """Returns the record and the cleaned body element for the chunker.
    Raises if the page is not in the sitemap or the markup shape is unrecognised."""
```

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

def chunk_body(body: Tag, page: PageRecord, nav: NavPage,
               sitemap: dict[str, NavPage] | None = None) -> list[Chunk]:
```

`tables` and `PageRecord.images` are additions made after the review of the
first complete crawl, and both are defaulted, so every existing caller and
every existing test still compiles against the original shape. What they are
for is in `SOURCE_NOTES.md` §§16–17: the pipeline was dropping 121 tables' worth
of structure and 169 images on the floor, and eight pages whose entire content
is an image were recording as indistinguishable from blank.

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
def extract_internal_refs(body_fragment: Tag, sitemap: dict[str, NavPage]) -> list[str]:
```

Called by the chunker, per chunk. Kept separate because they carry the densest
regex logic and the most test cases.

### `tables.py`

```python
def extract_tables(body_fragment: Tag) -> list[dict]:
```

Also called by the chunker, per chunk, and separate for the same reason. Turns
table markup into the grid — rows, cells, spans, and a header row only where
the markup declares one. `SOURCE_NOTES.md` §17 for what the Manual's tables
actually look like and why the first row is never assumed to be a header.

### `writer.py`

```python
def write_page(page: PageRecord, chunks: list[Chunk], root: Path) -> bool:
    """Returns True if bytes changed on disk."""
def write_raw(page_ref: str, html: str, root: Path) -> bool:
def write_manifest(root: Path, stats: dict) -> None:
```

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

## Skip logic

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
