# The snapshot viewer

A static page that reads `snapshot/` — both halves of it — and lets you do three
things neither source website can:

- **Filter passages by what the extractor found in them** — which Act a passage
  cites, whether the Manual hyperlinked that citation or the pipeline matched it
  by pattern, how certain a pattern match was, whether a heading was marked up
  or inferred, whether the page has been archived or amended in a given year.
- **Put a page back together from its chunks** and read it whole, so the
  deconstruction can be checked rather than taken on trust. The Manual's own
  hyperlinks come back with it, drawn at the offsets `chunk.links` records; one
  naming a page in the snapshot opens that page here rather than on the live
  site.
- **Read the Act and the Regulations beside the practice, and cross the join.**
  A chunk citing section 41 opens section 41; section 41 lists the 123 chunks
  that cite it, and its subsection (3) lists the 19 that cite that subsection
  exactly. Nothing joins them but the ref both records already carry.
- **See the whole citation graph at once**, at `graph.html` — every Part and
  every cited provision as a node, laid out by a force simulation rather than
  read one filter result at a time. §The cross-reference network, below.

## One set of predicates, two corpora

The filter panel does not grow a second copy of itself for the legislation.
`kind`, the instrument of a citation, `extraction`, `certainty`, the provision
box and the free-text search are fields both halves carry under the same names,
so each control reads both and its count is the sum of both. The predicates only
one half has — Part, heading source, page metadata, case law, and the three
structural flags that name a chunk's own fields — leave the other half out of
the result rather than being reinterpreted for it. A conjunction a provision
cannot satisfy is a conjunction it does not match; that is the honest answer and
it is the one the panel gives.

The corpus checkboxes at the top of the panel are the only new question, and
they are the obvious one: which of the three bodies of text to look in.

Live at
<https://thomas-amann-ipaustralia.github.io/manual-XtrACTor/>, with the
network view a click away at
<https://thomas-amann-ipaustralia.github.io/manual-XtrACTor/graph.html>.

## The cross-reference network

`graph.html`, `graph.js`, `graph.css` — a second page, reading a fourth data
file the first page never touches, `data/graph.json`. The two pages link to
each other (the masthead on each, and a "see it in the network view" link on
every Part and every provision) but share nothing at runtime: `graph.js` does
not import `app.js`, and closing one tab does not lose anything the other
needs.

**Nodes are Parts and provisions, not chunks or units.** 2,460 chunk nodes and
763 provision nodes would be a hairball a force layout cannot make legible —
this repository already has a page-by-page and section-by-section reader for
that resolution, the one above. A Part is the unit the Manual organises
itself by everywhere else in this viewer, so it is the unit here too. A
provision that nothing cites and that cites nothing is left off the map
entirely: a graph is for edges, and `graph.html` is not the place to browse an
instrument's full contents — `index.html`'s legislation view already does
that.

**Three edge kinds, one per citation field `SCHEMA.md` defines**, each
aggregated up from the chunk or unit that carries it to the Part or provision
that owns that chunk or unit, with a weight — how many distinct chunks made
that citation, except provision-to-provision, which `cites` only ever states
as "does A cite B", not how many times:

| Edge kind | Source field | What it means |
|---|---|---|
| `manual_to_law` | a chunk's `provisions` | practice citing the Act or the Regulations |
| `law_to_law` | a provision's `provisions` | the compiled instruments citing themselves |
| `manual_to_manual` | a chunk's `internal_refs` | one Part of the Manual pointing at another |

A same-Part pair is dropped rather than drawn as a self-loop — a Part linking
to its own prose is real (25 chunks do it) but says nothing about how the
Manual's Parts relate to each other, which is what this map is for.

`build_graph` in `viz/build.py` builds this from the three bundles
`build_manual`, `build_chunks` and `build_legislation` already produced, not
from a fifth reading of `snapshot/`: every count in `data/graph.json` is
already sitting in `manual.json`, `chunks.json` or `legislation.json`, keyed
by ref, the same discipline the rest of this file holds itself to.

**The layout is a force simulation written for this page** — repulsion,
springs along each edge, a light pull to centre, collision so nodes don't
stack — because pulling in a charting library would mean loading code from a
CDN, which `viz/README.md` has never allowed. It is seeded from a hash of each
node's own id rather than `Math.random()`, and every force in it is a
deterministic function of the graph, so the same `data/graph.json` settles
into the same picture on every reload instead of a fresh scramble each time.
That is not the byte-stability rule `CLAUDE.md` states for the snapshot —
nothing about a canvas layout is committed — but it is the same instinct
applied to a reader who comes back tomorrow and expects to recognise what
they saw today.

The filters (edge kind, instrument, a "declutter" weight threshold) only
change what is drawn and clickable; the simulation keeps running on the whole
graph underneath, so toggling a filter off and back on does not re-scramble
the layout. The side panel a click opens is the accessible path through the
graph — every neighbour listed there is a real button, reachable without
touching the canvas at all, with its own link back into `index.html`'s reader
for the passage or the provision itself.

## It is a reader, and only a reader

This directory is outside the pipeline and stays there.

- `tmm_snapshot` and `frl_snapshot` do not import it; `viz/build.py` is not a
  package and cannot be imported from `src/`.
- It never writes inside `snapshot/`, and `tests/test_viz_build.py` asserts that
  by hashing the tree before and after a build.
- **It adds no field to a chunk, and none to a provision.** Every chunk and
  provision object in the bundle is a strict field-subset of the record on disk,
  byte-equal in the fields it keeps. Anything the viewer needs that the snapshot
  does not assert — the reverse citation indexes, a table count, the facet
  vocabularies, the Manual-to-legislation join — is emitted *beside* those
  records in maps keyed by ref, never merged into them, and the tests fail if
  that stops being true.
- The build is deterministic: same snapshot in, byte-identical bundle out.
- The legislation half is optional. A snapshot with no `legislation/` directory
  builds a Manual-only bundle and the page carries on without it.

If the viewer ever seems to want a new field on a chunk or a provision, the
answer is no. Derive it in `viz/build.py` and put it in a sibling structure.

The join is the example worth reading. Showing "cited by the Manual" on a
provision needs an edge from a chunk to a section, and there was no temptation
to add one to either record, because both already carry the same string:
`chunk.provisions[].id` is `provision.ref` (`LEGISLATION_NOTES.md` §8). The
builder reverses that into `cited_by_manual`, resolves the ids that name a unit
rather than a provision through `unit_owners` — a stated map, because
`TMA1995/s4` is a prefix of `TMA1995/s41` and string surgery would silently
mis-file it — and counts the 76 in-scope ids that land on nothing, which the
page reports rather than hides.

`links` is worth reading as the example of the rule holding. It was added to the
data because the snapshot was losing 2,218 of the Manual's hyperlinks
(`SOURCE_NOTES.md` §29), not because the viewer wanted them, and it carries
offsets into `chunk.text` and nothing else. Drawing a link inside the right
paragraph or the right table cell needs to know where each block and cell sits
in that text, and that is derived here from a contract the snapshot already
asserts — the blocks' text joined with single spaces *is* the chunk's text — in
`app.js`'s `blockStarts` and `renderTable`. No field was added for it.

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
graph.html, graph.css, graph.js the cross-reference network view
data/manual.json                parts, pages, facet vocabularies, corpus stats  (~400 KB)
data/chunks.json                every chunk minus blocks/tables, plus sibling indexes  (~4 MB)
data/legislation.json           instruments, contents, every provision minus units,
                                plus the citation graph and the join  (~1.3 MB)
data/graph.json                 728 nodes (54 Parts, 674 cited provisions) and 2,641 edges
                                (~400 KB)
pages/<Part>/<file>.json        the page files verbatim  (~9 MB)
legislation/<code>/…            instrument.json, contents.json, endnotes.json and every
                                provision file, verbatim  (~6 MB)
```

Tiers of loading, matching the tiers of disclosure: `manual.json` paints the
Parts immediately, `legislation.json` and `chunks.json` arrive behind it and
turn the filters on, and a page's or a provision's own file is fetched only when
a reader opens it and wants the structure inside — the paragraphs and tables of
a chunk, the subsections and notes of a section.

`legislation.json` carries each provision's `text` for the same reason
`chunks.json` carries a chunk's: the units' text joined with single spaces *is*
that string, so the words paint and search before the structure arrives. The
units themselves, which are two thirds of that corpus by weight, do not.

## Publishing

`.github/workflows/pages.yml` builds and deploys on every push to `main` that
touches `snapshot/` or `viz/`, so a merged crawl republishes the viewer without
anybody doing anything. It needs **Settings → Pages → Source = GitHub Actions**
set once on the repository.

Nothing generated is committed. The published site is rebuilt from the snapshot
each time, which is the only way it can be trusted to be showing the snapshot.
