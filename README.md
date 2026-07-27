# Trade Marks Manual — snapshot

An offline, structured snapshot of the [IP Australia Trade Marks Manual of
Practice and Procedure](https://manuals.ipaustralia.gov.au/trademark), committed
to this repository and refreshed on a schedule.

The Manual is published only as rendered HTML: no API, no bulk download, no
change feed. This repo crawls it, parses it into a stable structure, and commits
the result — so the git history becomes a readable amendment log, and downstream
work can build against a fixed, versioned corpus rather than a live website.

## What is here

```
snapshot/manifest.json     run metadata
snapshot/sitemap.json      the Manual's structure
snapshot/pages/            page records with their chunks, one file per page
snapshot/raw/              verbatim source HTML
```

Each page file holds one page record and the chunks cut from it. A chunk is a
retrievable passage — normally the prose under one heading — carrying its
heading ancestry, a content hash, and the statutory and case citations extracted
from it.

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
python -m tmm_snapshot.crawl --from-raw      # re-parse without touching the network
python -m tmm_snapshot.validate
```

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
