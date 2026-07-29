# Trade Marks Manual — snapshot

An offline, structured snapshot of the [IP Australia Trade Marks Manual of
Practice and Procedure](https://manuals.ipaustralia.gov.au/trademark), committed
to this repository and refreshed on a schedule.

The Manual is published only as rendered HTML: no API, no bulk download, no
change feed. This repo crawls it, parses it into a stable structure, and commits
the result — so the git history becomes a readable amendment log, and downstream
work can build against a fixed, versioned corpus rather than a live website.

## Browse it

<https://thomas-amann-ipaustralia.github.io/manual-XtrACTor/> — a static viewer,
built from the snapshot in this repository on every crawl that lands.

It does two things the Manual's own site cannot: filter passages by the metadata
the extraction produced (which Act a passage cites, whether that citation was a
hyperlink or a pattern match, how certain the match was, whether a heading was
marked up or inferred, when the page was last amended), and reassemble any page
from its chunks so the deconstruction can be checked rather than trusted.

The viewer is a reader and nothing more — see `viz/README.md`. It is outside the
pipeline, it never writes to `snapshot/`, and it adds no field to a chunk.

## What is here

```
snapshot/manifest.json     run metadata
snapshot/sitemap.json      the Manual's structure
snapshot/retired.json      pages that left the Manual, and when
snapshot/pages/            page records with their chunks, one file per page
snapshot/raw/              verbatim source HTML
```

Each page file holds one page record and the chunks cut from it. A chunk is a
retrievable passage — normally the prose under one heading — carrying its
heading ancestry, a content hash, the statutory and case citations extracted
from it, the paragraph, list and table structure its text was flattened from,
and the Manual's own hyperlinks with the offsets into that text where they sit.

## What this is not

Not a search engine, not an index, not a chatbot. No embeddings, no LLM
involvement anywhere in the pipeline. Every field is derived from the source HTML
deterministically, so the output is a pure function of the input and any record
can be traced back to a paragraph a person can open and read.

That constraint is deliberate. Downstream tools can add interpretation; this
layer stays checkable.

## The Manual is practice, not law

It states the Registrar's practice under the Trade Marks Act 1995 (Cth) and the
Trade Marks Regulations 1995. It guides examiners toward consistent application;
it is not the legislation, and it does not bind the Registrar's discretion.
Anything built on this snapshot should preserve that distinction.

## Running it

```bash
pip install -e .
python -m tmm_snapshot.crawl --dry-run --limit 5
python -m tmm_snapshot.crawl --part Part22   # one Part
python -m tmm_snapshot.crawl --from-raw      # re-parse without touching the network
python -m tmm_snapshot.validate
python -m tmm_snapshot.diff --before /path/to/previous/snapshot
```

`diff` renders the change report between two snapshot states — what was added,
retired, amended and restructured, with IP Australia's own reason for each
amendment. It is what a scheduled crawl puts in the body of its pull request.

Requests are serial, rate limited and conditional, and `robots.txt` is checked
on every run. A re-crawl of an unchanged Manual costs the site 502 `304`s and
nothing else. Do not run a full crawl on a whim — use `--limit`, or let
scheduled CI do it.

Scheduled crawls open a pull request when anything changes. They are never
auto-merged — the human review is the audit trail.

## Documentation

| | |
|---|---|
| `CLAUDE.md` | Orientation and the non-negotiable rules |
| `ARCHITECTURE.md` | Pipeline stages, module contracts, on-disk layout |
| `SOURCE_NOTES.md` | How the Manual actually behaves, and its traps |
| `SCHEMA.md` | The data contract, explained |
| `TASKS.md` | Sequenced work packages |
| `viz/README.md` | The published viewer, and why it cannot touch the pipeline |
