# Australian trade marks corpus — snapshot

An offline, structured snapshot of the Australian trade marks corpus, committed
to this repository and refreshed on a schedule:

- the [IP Australia Trade Marks Manual of Practice and
  Procedure](https://manuals.ipaustralia.gov.au/trademark) — practice;
- the **Trade Marks Act 1995** and **Trade Marks Regulations 1995**, from the
  Federal Register of Legislation — law.

The Manual is published only as rendered HTML: no API, no bulk download, no
change feed. The legislation has an API but serves its text as compiled Word
documents. This repo reads both, parses them into a stable structure, and
commits the result — so the git history becomes a readable amendment log, and
downstream work can build against a fixed, versioned corpus rather than a live
website.

The two halves join without a lookup table. A Manual passage citing section 41
records `provisions[].id == "TMA1995/s41"`, and that is the ref of a provision
record holding the text of section 41: 2,611 of the Manual's 2,687 in-scope
provision edges resolve. Every field on both sides is derived from the source by
regex, href parsing or structural traversal — no model output anywhere in the
pipeline.

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

snapshot/legislation/
  manifest.json            run metadata for the legislation pipeline
  TMA1995/
    instrument.json        which compilation is held, and what amended it
    contents.json          Parts, Divisions and provisions in document order
    endnotes.json          the instrument's own amendment history, verbatim
    provisions/pt4/…json   one file per section, with its numbered units
    raw/…docx              the verbatim compiled document
  TMR1995/…
```

Each page file holds one page record and the chunks cut from it. A chunk is a
retrievable passage — normally the prose under one heading — carrying its
heading ancestry, a content hash, the statutory and case citations extracted
from it, the paragraph, list and table structure its text was flattened from,
and the Manual's own hyperlinks with the offsets into that text where they sit.

Each provision file holds one section, regulation, Schedule clause or Schedule
item, and the numbered units inside it — `s41(3)(a)` is addressed and retrievable
in its own right, because that is how the law is cited. Every unit carries the
Office of Parliamentary Counsel paragraph style it was derived from, so the
evidence for the structure travels with the record.

## Refreshing it

```bash
python -m tmm_snapshot.crawl      # the Manual
python -m frl_snapshot.crawl      # the Act and the Regulations
```

The legislation crawler costs the Register two small JSON requests when nothing
has changed: a compilation has an identifier that changes if and only if the law
was amended, so there is nothing to download or hash until it moves.

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
