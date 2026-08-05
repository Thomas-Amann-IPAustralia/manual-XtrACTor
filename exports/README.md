# Exports

Flat files derived from `snapshot/`, for consumers that want a table rather
than a tree.

Same standing as `viz/`: **these read the snapshot and are not part of the
pipeline.** No field exists in a chunk record for their benefit, nothing here
is an input to a crawl, and deleting the whole directory would not change what
`tmm_snapshot.crawl` writes. They are regenerated from the committed snapshot,
never edited by hand.

Every export is a pure function of `snapshot/`. Re-running a generator against
an unchanged snapshot produces byte-identical output, for the same reason page
files are byte-stable — a table that moves on its own is a table nobody can
diff.

---

## `STATS.md`

The corpus, counted. One Markdown report describing how big the Manual is, how
it is shaped, how often it links to itself, how often it cites the Act, the
Regulations and the courts, and what its publisher's own amendment log says
about it.

```bash
python exports/build_stats.py
```

Written to be read rather than joined — it is the only export that is prose,
and the counterpart to `cases.csv` for someone who wants to know what is in
this corpus before deciding what to do with it. Every number is counted off
`snapshot/pages/` and `snapshot/legislation/`; nothing is estimated except the
reading-time figure, which says so.

Where a count is of something the extractor marked as an inference — a `regex`
provision edge, a heading promoted from a bold paragraph — the report says so
beside the number. The point is not to make the corpus look more certain than
it is: several of the more interesting figures are measurements of exactly how
much of it rests on a convention.

**One caveat on reproducibility.** Token counts cannot be derived from the
snapshot with the standard library, because a token is whatever a tokeniser
says it is. If `tiktoken` is importable the report carries counts under two
encodings and names them; if it is not, the report says the counts were not
computed. That is the only line whose output depends on the environment rather
than the snapshot, and reading the report tells you which happened.
**`tiktoken` is not a dependency of this repository** and nothing else here
imports it. The committed `STATS.md` was generated with it installed.

### Regenerating

```bash
python exports/build_stats.py
git diff --stat exports/STATS.md      # empty unless the snapshot moved
```

---

## `cases.csv`

Every case citation in the Manual, one row per **position**.

```bash
python exports/build_cases.py
```

519 rows carrying 411 distinct decisions across 221 chunks on the Manual's 500
pages, 438 of them with the decision's party names. Written for one job: joining this corpus to an external register of
decisions. **The join key is `citation`**, or `case_id`, which is the same fact
addressed rather than printed.

A row is one decision cited in one chunk. A decision cited in eight chunks —
`[1999] FCA 1020`, the most-cited in the corpus — has eight rows.
`corpus_citation_count` carries the total on every one of them, so the register
of 411 falls out of a `GROUP BY case_id` without a second pass.

### Columns

**The decision.** Repeated on each of its rows.

| Column | Notes |
|---|---|
| `case_id` | `CASE/2024/FCA/1277`, `CASE/1963/CLR/109/407`. The id the chunk record carries, unchanged. One id ↔ one citation string, corpus-wide. |
| `citation` | As the Manual printed it. The join key. |
| `citation_style` | `neutral` (379 positions, 289 decisions) or `reported` (140 / 122). SCHEMA.md's own two styles. |
| `year`, `court_or_series`, `number`, `volume`, `first_page` | Parsed from `citation`. Neutral fills `number`; reported fills `volume` and `first_page`. The middle token is usually a court and occasionally a report series cited bracket-style (`AC`), which is why the column is named for both. |
| `corpus_citation_count` | Positions this decision has across the whole corpus. |
| `parties` | **Only from markup the Manual set around the case name**, never read out of running prose. 438 rows: 18 from an anchor, 420 from an italic run. See below. |
| `parties_source` | `anchor` or `emphasis`, and empty where there is no name. Which markup the name came from, because the two are not equally strong. |
| `jade_href` | The jade.io link on the anchor, where there was one. 18 rows. |
| `parallel_citation` | The citation printed immediately beside this one. 30 rows. Evidence of an alias, not an assertion of one. |
| `parallel_case_id` | Set where that neighbour is itself a decision in this corpus. 24 rows, 11 distinct pairs. |

**The position.**

| Column | Notes |
|---|---|
| `chunk_ref` | The passage. Joins to `snapshot/pages/<part>/<page>.json`. |
| `page_ref`, `part_id`, `part_title`, `page_title` | Where it sits, at three widths. |
| `heading_path` | Full breadcrumb, joined with ` > `. |
| `chunk_ordinal` | Position of the chunk on its page. |
| `char_offset` | Where the citation starts in `chunk.text`. |
| `occurrences_in_chunk` | Times the citation appears in that chunk. 516 positions are 1; 3 are more. |
| `url` | The page a human opens to check the row. |
| `context` | 140 characters of `chunk.text` either side. |

### What is asserted, and what is only recorded

The repository's rule 1 applies here. Nothing in this file is inferred meaning,
and the two columns that look like they might be are worth being explicit about.

**`parties` is the Manual's words, not ours.** SCHEMA.md's judgement that party
names are unreliable to extract *from prose* stands, and this export does not
reopen it. Every name here comes from markup the authors set around the name
themselves, in one of two shapes:

- **`anchor`** — an `<a>` whose own text contains the citation:
  *"Registrar of Trade Marks v Woolworths Ltd [1999] FCA 1020"*, hyperlinked to
  jade.io. Everything before the citation in that anchor is the party name
  because the authors wrote it that way. 18 rows, and the stronger of the two:
  the name and the citation are inside one element, so no adjacency has to be
  read at all.
- **`emphasis`** — an italic run ending immediately before the citation:
  *"`<i>`Self Care IP Holdings Pty Ltd v Allergan Australia Pty Ltd`</i>`
  [2023] HCA 8"*. 420 rows. Italicising a case name is the legal-writing
  convention and hyperlinking one is not, which is why there are twenty times
  as many.

The 81 positions still blank are mostly a citation printed straight after
another — `[1963] HCA 66; (1963) 109 CLR 407` — where the second carries no
name of its own. A blank is the correct value there: it is not that the name is
missing, it is that the Manual gave the decision one name and cited it twice,
which is the parallel-citation signal `parallel_citation` records.

**This is a correction.** Until `ingest/0.10.0` this file said party names were
*"not a gap this repository can close deterministically"*, and that was wrong.
It assumed the only markup evidence was a hyperlink. Reading `<i>` is not a
different kind of act from reading `<a href>` — both are the authors marking a
span — and the Manual marks case names far more often than it links them. The
spans reached the snapshot as `chunk.emphasis` in `ingest/0.10.0`;
`SOURCE_NOTES.md` §34 has the measurement.

**The adjacency is read here and not in the pipeline**, and that division is
the point of this directory. `chunk.emphasis` records that the Manual set those
words apart and where they sit; concluding the words are therefore *this
decision's parties* is a reading. A reading belongs downstream of the corpus,
in a file that can be regenerated when the reading improves, and no field
exists on a chunk for this script's benefit.

**`parallel_citation` is adjacency, and adjacency is evidence.** Two citations
separated only by `;` or `,` are the drafter's convention for one decision
cited two ways. Reading that is a traversal. Concluding the two are the same
decision is a merge, and the merge is a human's:

```
(1929) 41 CLR 475  == [1929] HCA 6
(1946) 72 CLR 175  == [1946] HCA 15
(1963) 109 CLR 407 == [1963] HCA 66
(1980) 144 CLR 13  == [1980] HCA 13
(1994) 49 FCR 89   == [1994] FCA 1001
(1999) 91 FCR 167  == [1999] FCA 816
(2005) 68 IPR 153  == [2006] AIPC 92
(2006) 70 IPR 599  == [2006] FCA 1663
(2007) 74 IPR 246  == [2007] FCAFC 184
(2008) 77 IPR 69   == [2008] FCA 934
(2013) 217 FCR 327 == [2013] FCA 559
```

**If all eleven hold, the corpus's 411 ids are 400 decisions.** They are not
merged here, and `case_id` is left as the chunk records have it, because
merging would put a decision in this file that no chunk cites and break the
join back to `snapshot/`. Merge downstream, against a real register.

Six more rows carry a neighbour printed without its year — `[2016] FCA 729`
beside `338 ALR 134` — which this corpus has no edge for and an external
register can resolve.

### Known defects in the source, exported as written

- **`(1904) 21 ROC 617`** is a mis-set `RPC`, in Part 30.2. Exported as the
  Manual prints it. Correcting it here would put a citation in the CSV that
  the Manual does not make; it belongs in a review queue, with the alias pairs.
- **11 of the 411 ids are probably duplicates** of another id in the same file.
  See above.
- **Party names are absent from 81 of 519 positions**, and most of those are
  the second half of a parallel citation rather than a decision the Manual
  never named. 356 of the 411 decisions carry a name, and 336 of those carry
  exactly one across every position — so `GROUP BY case_id` gives a register
  with a name on nearly all of it.

### Regenerating

Cheap, offline, and byte-stable:

```bash
python exports/build_cases.py
git diff --stat exports/cases.csv     # empty unless the snapshot moved
```

A non-empty diff after a crawl means the Manual's case citations changed, which
is exactly what it should mean.
