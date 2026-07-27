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
  pages/
    Part22/
      TMM-Part22-1.json               page record + its chunks
      TMM-Part22-15.json
    Part32B/
      TMM-Part32B-2-3.json
  raw/
    Part22/
      TMM-Part22-1.html               verbatim source, unmodified
```

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
- **No run timestamp in a page file.** `crawled_at` belongs in `manifest.json`.
  A page record may carry a `first_seen`-style date, but only if it is written
  once and never rewritten while content is unchanged.
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

def chunk_body(body: Tag, page: PageRecord, nav: NavPage) -> list[Chunk]:
```

### `citations.py`

```python
def extract_provisions(body_fragment: Tag, text: str) -> list[dict]:
def extract_cases(text: str) -> list[dict]:
def extract_internal_refs(body_fragment: Tag, sitemap: dict[str, NavPage]) -> list[str]:
```

Called by the chunker, per chunk. Kept separate because they carry the densest
regex logic and the most test cases.

### `writer.py`

```python
def write_page(page: PageRecord, chunks: list[Chunk], root: Path) -> bool:
    """Returns True if bytes changed on disk."""
def write_raw(page_ref: str, html: str, root: Path) -> bool:
def write_manifest(root: Path, stats: dict) -> None:
```

## Skip logic

Three gates, cheapest first:

1. **HTTP 304.** Conditional request returned not-modified. Skip everything.
2. **Page hash unchanged.** Fetched, but the normalised body hashes the same as
   the stored record. Skip parsing and writing.
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

## CI

`.github/workflows/crawl.yml` runs on a schedule (weekly is a reasonable start;
tune once the real amendment cadence is known). It crawls, and if anything
changed it opens a pull request with the change report from `diff.py` in the
body. A human merges. That review step is the audit trail — it is where somebody
confirms whether an amendment was substantive practice change or a hyperlink
tidy-up, using the Manual's own `amendment_note` as the clue.

Never auto-merge. The point is the human read.
