# The snapshot viewer

A static page that reads `snapshot/` and lets you do two things the Manual's own
website cannot:

- **Filter passages by what the extractor found in them** — which Act a passage
  cites, whether the Manual hyperlinked that citation or the pipeline matched it
  by pattern, how certain a pattern match was, whether a heading was marked up
  or inferred, whether the page has been archived or amended in a given year.
- **Put a page back together from its chunks** and read it whole, so the
  deconstruction can be checked rather than taken on trust.

Live at
<https://thomas-amann-ipaustralia.github.io/manual-XtrACTor/>.

## It is a reader, and only a reader

This directory is outside the pipeline and stays there.

- `tmm_snapshot` does not import it; `viz/build.py` is not a package and cannot
  be imported from `src/`.
- It never writes inside `snapshot/`, and `tests/test_viz_build.py` asserts that
  by hashing the tree before and after a build.
- **It adds no field to a chunk.** Every chunk object in the bundle is a strict
  field-subset of the chunk on disk, byte-equal in the fields it keeps. Anything
  the viewer needs that the snapshot does not assert — the reverse citation
  index, a table count, the facet vocabularies — is emitted *beside* the chunks,
  never merged into them, and the tests fail if that stops being true.
- The build is deterministic: same snapshot in, byte-identical bundle out.

If the viewer ever seems to want a new field on a chunk, the answer is no. Derive
it in `viz/build.py` and put it in a sibling structure.

## Running it locally

```bash
python viz/build.py --snapshot snapshot --out viz/dist
python -m http.server -d viz/dist 8000
```

Then open <http://localhost:8000>. `viz/dist/` is build output and is not
committed.

Standard library only, no build step, no npm, no CDN. The page loads nothing
from another origin — outbound links to AustLII and to the live Manual are
links, not requests.

## What gets built

```
index.html, app.css, app.js     the viewer
data/manual.json                parts, pages, facet vocabularies, corpus stats  (~400 KB)
data/chunks.json                every chunk minus blocks/tables, plus sibling indexes  (~3 MB)
pages/<Part>/<file>.json        the page files verbatim  (~8 MB)
```

Three files, three tiers of loading, matching the three tiers of disclosure:
`manual.json` paints the Parts immediately, `chunks.json` arrives behind it and
turns the filters on, and a page's own file is fetched only when a reader opens
that page and wants the paragraph and table structure inside a chunk.

## Publishing

`.github/workflows/pages.yml` builds and deploys on every push to `main` that
touches `snapshot/` or `viz/`, so a merged crawl republishes the viewer without
anybody doing anything. It needs **Settings → Pages → Source = GitHub Actions**
set once on the repository.

Nothing generated is committed. The published site is rebuilt from the snapshot
each time, which is the only way it can be trusted to be showing the snapshot.
