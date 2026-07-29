# Review of the 0.8.0 extraction

An audit of both pipelines and of `snapshot/` at `ingest/0.8.0` and
`legislation/0.1.0` — 500 page files, 2,460 chunks, 12,521 blocks, 2,218 links,
2,802 provision edges, 519 cases, 418 internal refs, and 763 provisions holding
5,813 units across two instruments — asking the same two questions as the 0.7.0
review:

1. **What can break the system?**
2. **What is structurally wrong in a way that would harm an ontology built on
   top of this?**

The legislation half has never been reviewed. It is where most of this document
is, and that is not a criticism of it — it is where the unexamined surface was.

Method: read every module against `ARCHITECTURE.md`, `SCHEMA.md`,
`SOURCE_NOTES.md` and `LEGISLATION_NOTES.md`; re-derived both corpora from
`snapshot/raw/` and `snapshot/legislation/*/raw/` and compared byte for byte;
re-derived both again under four values of `PYTHONHASHSEED`; walked every
provision, unit, chunk, block, link and edge in the committed output; and, for
each suspected defect, either a corpus-wide probe or a reproduction against a
copy of the snapshot. Every count below was run, not reasoned about. Where a
defect is latent rather than active, that is said.

Nothing here proposes a model, an embedding or a heuristic. Every fix suggested
is a regex, a shape check or a traversal, and two of them are the repository
applying to one corpus a rule it already applies to the other.

---

## What is sound

Stated first, because it bounds everything after it.

- **Both pipelines are reproducible.** `tmm_snapshot.crawl --from-raw --force
  --dry-run` re-cut all 500 pages and 2,460 chunks and would have written
  **zero** files. `frl_snapshot.crawl --from-raw --force` re-cut 763 provisions
  and 5,813 units from the stored `.docx` and wrote **zero** files. The
  snapshot in this repository is exactly what this code produces from this
  source.
- **Both are hash-seed deterministic.** Re-derived under `PYTHONHASHSEED`
  0–2 (Manual) and 0–3 (legislation): byte-identical every time, `sitemap.json`
  and `contents.json` included. This is the check that caught finding 4 of the
  0.7.0 review, and nothing like it survives.
- **545 tests pass. Both validators are clean.**
- **The 0.7.0 settling fix holds, verified by reproduction.** Renaming Part 14
  page 6's heading `6.5` to `6.51` in a copy of `raw/` and running a *non*-forced
  `--from-raw` crawl now re-settles the two uncut pages that cite it, names both
  in the run report, coarsens both refs to `TMM/Part14/6`, and the snapshot
  validates. That was the most serious finding of the last review and it is
  genuinely closed.
- **The address spaces hold.** 5,813 unit refs, all distinct. No unit ref is
  also a provision ref. Every `parent_ref` names a unit of its own provision.
  418 internal refs and 3,028 `headings[].ref` entries, none dangling. Heading
  levels strictly increase on all 2,460 chunks.
- **The reference grammar joins.** 2,603 of 2,776 in-scope Manual provision
  edges land on a record. No edge lands on a `note` unit.
- **The Manual's documentation is accurate.** Every count in `SCHEMA.md` and
  `SOURCE_NOTES.md` I could measure — 12,521 blocks, 2,218 links, 121 tables,
  418 refs (378 href / 40 regex, 38 default / 2 explicit, 28 chunk-level),
  3,028 heading entries, 1,473/491/496 `heading_source`, 169 images, 93 image
  blocks, 4 loose text blocks — matches the corpus exactly. The 0.7.0 drift was
  cleaned up properly.

**No bug in this review corrupts a word of text.** As at 0.7.0, the findings are
about **edges and addresses** — where the pipeline asserts a relationship it
cannot support, or gives a thing an address that will not survive the next
amendment.

---

# Part one — correctness

## 1. A definition is transparent to the address, and it should not be

**The most serious structural defect, and it is in the corpus now.**

`LEGISLATION_NOTES.md` §6.8 is right about section 42: its paragraphs hang off
an *unnumbered* opening subsection, everyone cites them `s 42(a)`, and
addressing them `s42~1(a)` would match no citation anybody writes. So
`units.split_units` makes an unnumbered ancestor transparent to the address:

```python
address_of[ref] = ref if number is not None else address_parent
```

That is correct where a provision has **one** unnumbered ancestor bearing
numbered children. It is wrong where it has several, because they then all
address into the same space. Measured: **10 provisions, 73 units.**

Section 6 of the Act is the definitions section, and it is the worst case. Each
definition is a `Definition`-styled unit, which carries no `(1)`-shaped label,
so each is unnumbered — and eleven of them have their own `(a)`, `(b)`, `(c)`:

```
TMA1995/s6~6    "Australia includes the following external Territories:"
  TMA1995/s6(a)      "(a) Christmas Island;"
TMA1995/s6~18   "date of registration ... means:"
  TMA1995/s6(a)~2    "(a) in relation to the registration of a trade mark ..."
TMA1995/s6~30   "filing date ... means:"
  TMA1995/s6(a)~5    "(a) in relation to an application for the registration ..."
```

Nobody cites "section 6(a)". The citable address is *section 6, definition of
**Australia**, paragraph (a)*, and the definiendum — the one thing that makes
these eleven paragraphs tell each other apart — is not in the address at all.
Which of the eleven holds the unsuffixed `TMA1995/s6(a)` is decided by document
order, so a bare `TMA1995/s6(a)` resolves to *Christmas Island*.

Two aggravations:

- **51 of the corpus's 63 `number_collision` flags are manufactured by this,
  not by the drafter.** `SCHEMA.md` says that flag means *route to review, never
  hydrate from it silently*, and `LEGISLATION_NOTES.md` §6.7 describes it as a
  defect *in the compiled instrument*. In `TMA1995/s6`, `TMR1995/r17A.29` and
  `TMR1995/r17A.48` the drafter numbered nothing twice — each definition's
  paragraphs are perfectly unambiguous in the document. The ambiguity is ours,
  and it is being reported as the law's.
- **It is not only definitions.** `TMR1995/sch8/pt2/div1` and `div2` hit the
  same thing through unnumbered `subsection` units, because Schedule 8 numbers
  its clauses inline (§6.5) and so presents as a flat run of unnumbered
  subsections each bearing `(a)`/`(b)`.

The kinds of transparent ancestor involved: 23 `definition`, 7 `subsection`,
3 `text`.

**Latent for the join, active in the corpus.** No Manual provision edge lands on
any of the 73 addresses today, because the Manual does not cite `s6(a)`. So
nothing is currently resolving to Christmas Island. But 83 units carry an
address that is not the way anyone cites them, and 51 carry a flag saying the
law is defective when it is not.

The fix needs no new reading of the source. A `Definition` is a *named*
container — the name is right there, and finding 4 shows it is deterministically
available — so it should never be transparent. More generally, transparency is
safe only where the unnumbered ancestor is the provision's sole one bearing
numbered children, which is exactly the section-42 shape §6.8 was written for.
Either rule fixes all 10 provisions.

## 2. Nothing checks a provision number against the shape its instrument can hold

**204 edges across both corpora, and 121 of them point away from a record that
is sitting in the snapshot.**

`validate._provision_failures` already enforces one invariant of this exact
kind, and its docstring explains why:

> An Act is divided into sections and Regulations into regulations, so
> `TMR1995/s224` names something that does not exist … 20 such edges reached the
> July 2026 snapshot from a lookahead that crossed a table's column boundary,
> every one of them recorded as `explicit`, which is the confident end of the
> scale.

The check stops at the symbol. It never looks at the number, and the number
carries the same fact:

| Measured over the legislation corpus | |
|---|---|
| Trade Marks Act section numbers containing a dot | **0 of 315** |
| Trade Marks Regulations regulation numbers containing a dot | **401 of 401** |

So `TMA1995/s4.7` is structurally impossible and `TMR1995/r2016` is too. Both
are in the corpus:

| Shape | Manual | Legislation | Total |
|---|---|---|---|
| `TMA1995/s<dotted>` — a dotted address as an Act section | 78 | 84 | **162** |
| `TMR1995/r<undotted>` — an undotted address as a regulation | 19 | 23 | **42** |

**159 of the 162 carry `certainty: "default"`** — *"assumed to be the Trade
Marks Act by convention"*. The convention is being applied where the number's
own shape disproves it.

And the damage is not that the edge fails to resolve. **121 of the 162 (75%)
name a regulation that exists in this snapshot:**

```
TMA1995/s21.28(1)(a)   (regex/default)  "paragraph 21.28(1)(a)"   ->  TMR1995/r21.28(1)(a) exists
TMA1995/s4.14(3)(j)(i) (regex/default)  "subparagraph 4.14(3)(j)(i)" -> TMR1995/r4.14(3)(j)(i) exists
TMA1995/s1.1           (regex/default)  "paragraph 1.1"           ->  TMR1995/r1.1 exists
```

The undotted bucket holds two further sub-classes worth naming, both false
edges rather than misattributed ones:

- **A year read as a provision number.** `TMR1995/r2016` from *"Defence
  **Regulation 2016**, part 14"*, `TMR1995/r2013` from *"Intellectual Property
  Legislation Amendment (Raising the Bar) **Regulation 2013**"*, `TMR1995/r1991`.
  13 edges. These name instruments of other portfolios and are attributed to
  the Trade Marks Regulations at `default`.
- **Schedules.** `TMR1995/r1`, `r2`, `r9` — finding 3.

This is the cheapest large correctness win available. The invariant is two
comparisons, it is the same one already written for the symbol, and it fires on
edges the pipeline currently states with confidence. What to *do* with a
violation is a separate call — re-attribute where the sibling instrument holds
the number (121 of them), or demote to `ambiguous` and route to review — but
storing it as `default` against an instrument that cannot hold it is the failure
mode `SCHEMA.md` names: *a wrong edge that looks certain*.

## 3. An AustLII `sch` node is read as a section number

`citations._href_edges` strips the node's alpha prefix and keeps the digits:

```python
number = _canonical_address(re.sub(r"^[a-z]+", "", match.group("node").lower()))
```

For `/consol_act/tma1995121/s41.html` that is right. For
`/consol_reg/tmr1995230/sch2.html` — Schedule 2 of the Regulations — it yields
`2`, and combined with the `consol_reg` symbol gives **`TMR1995/r2`**.

Surveyed across every AustLII link in the corpus, only two node prefixes occur:

| Prefix | Links | Verdict |
|---|---|---|
| `s` | 938 | correct — AustLII uses `s` for regulations too, and the instrument supplies the symbol |
| `sch` | 8 | **all wrong** |

All eight are `extraction: "href"` — the class `SCHEMA.md` calls *"the authors
telling you what the paragraph is about"*, and the strongest evidence the schema
can carry. And all three correct targets already exist in the legislation
snapshot: `TMR1995/sch1`, `TMR1995/sch2`, `TMR1995/sch9`. Reading the prefix
instead of discarding it turns eight confidently-wrong unresolvable edges into
eight correct resolving ones.

Note that finding 2's invariant catches these as a side effect — `r2` is
undotted — but the cause is different and so is the repair. Finding 2 says the
edge is impossible; this says what it should have been.

---

# Part two — structure, and what it costs the ontology

## 4. Every definition is addressed by position

**189 definition units. 100% of them addressed `~n`.** Section 6 alone holds 76.

`SCHEMA.md` states the objection to this in its own words, about `chunk_ref`:

> Do not add a separate sequential id. A serial number is a citation that breaks
> silently: insert a paragraph upstream and `chunk-047` now points at different
> text, with nothing to detect it. An address survives where a counter does not.

And `SOURCE_NOTES.md` §18 records the Manual half discovering this the hard way
on the Part 14 glossary — 627 non-exhaustive terms where *"inserting a single
term used to repoint every citation after it, silently"* — and fixing it by
slugging the heading text.

The legislation half has the identical problem and did not get the identical
fix. Definitions are set in alphabetical order, so inserting *"certification
trade mark"* into section 6 shifts `~n` for every definition after it, and every
`parent_ref` pointing at one. Nothing detects it, because a positional address
is valid output — the same silent-degradation shape as 0.7.0's finding 2.

**The fix needs no inference and the evidence is already in the record.**
`LEGISLATION_NOTES.md` §5 notes that the leading bold-italic run of a
`Definition` is the defined term, and `emphasis` records it. Measured:

- 189 of 189 definitions carry a leading emphasis span **at offset 0**.
- All 189 are `weight: "bold-italic"`.
- Slugging that term produces **zero collisions** within any provision.

So `TMA1995/s6/australia` — or whatever spelling the repo prefers — is available
deterministically today, for all 189, by reading a field the snapshot already
holds. It is the §18 fix, applied to the corpus that has not had it.

Two things this would also buy, both of which finding 1 is about: the definition
becomes a node the graph can name, and its paragraphs get an address that says
which definition they belong to.

**Do this before the corpus is seeded, not after.** It repoints 189 unit refs
and the `parent_ref` of everything under them; done later it repoints them in
whatever is built on top as well.

## 5. Three gaps in the validators, and one that aborts a crawl

The validators are the reason a defect in this repository gets found rather than
shipped, so gaps in them are worth listing even where nothing is currently
wrong.

**`frl_snapshot.validate` never checks unit-ref uniqueness across provisions.**
It collects them with `unit_refs.update(...)` into a `set`, so two provisions
claiming one unit address merge silently and `summary["addressable"]` quietly
under-reports. There are no duplicates today — I checked all 5,813 — and the
prefixing makes a cross-provision clash unlikely, but "unlikely" is what the
per-provision `_assert_unique` also guards against, and that one raises.

**Nothing validates `number_collision`.** It is the flag `SCHEMA.md` tells
consumers to route to review, and finding 1 shows it can be set for a reason
that is not the documented one. A check that its count matches the addresses
actually duplicated would have caught finding 1 on the day it landed.

**`tmm_snapshot.validate._heading_failures` never checks `headings[].ref`.** It
checks the count against `heading_path` and the leaf's `source`, but not the
field `SCHEMA.md` calls *"what makes the heading tree addressable"*. All 3,028
entries resolve today; nothing would say so if they stopped.

**And the collision suffix in `units.split_units` can compose an address that is
already taken.** Reproduced:

```python
Block("subsection", "(1)\tOpening.")
Block("paragraph",  "(a)\tFirst.")     # -> TMA1995/s9(1)(a)
Block("notetext",   "Note: one.")      # -> TMA1995/s9(1)(a)~1
Block("notetext",   "Note: two.")      # -> TMA1995/s9(1)(a)~2
Block("paragraph",  "(a)\tSecond.")    # -> base claimed, composes ~2  -- CLASH

UnitError: TMA1995/s9: two units claim 'TMA1995/s9(1)(a)~2' —
  'Note: two.' and '(a) Second.'
```

`ref = f"{base}~{claimed[base]}"` is composed without asking whether that string
is free, and the unnumbered-seat counter allocates into the same space. It
raises rather than corrupting, which is rule 3 working — but it aborts the
instrument, so an ordinary compilation would stop the crawl dead. The error also
blames the drafter for a clash that is between a note and a paragraph.

Nine provisions carry collisions today and in none of them does the colliding
parent have an unnumbered sibling, so it does not fire. Six of those nine
already contain notes elsewhere. It is one note in the wrong place away.
Allocating the suffix from the same `claimed` set — loop until free — closes it,
and **fixing finding 1 removes 51 of the 63 collisions and most of the surface**.

---

## Documentation drift

Measured against `snapshot/legislation/`. The Manual's docs are clean; these are
all in the legislation half, and the first two are consequences of finding 1
rather than tidiness problems.

| Claim | Where | Stated | Actual |
|---|---|---|---|
| Provisions numbering something twice | `LEGISLATION_NOTES.md` §6.7, `units.py` `number_collision` docstring | "The Regulations do this twice" — 4 units, 2 provisions, one instrument | **63 units, 9 provisions, both instruments** |
| A real section 131A | `LEGISLATION_NOTES.md` §6.3 | "and once with **the real section 131A**" | The Act holds s130, s130A, s131. **There is no section 131A.** The eight `TMA1995/s131A` edges correctly do not resolve — 131A exists only in the territory-modified Act the Regulations' Schedules construct |

`LEGISLATION_NOTES.md` §8's headline figure — 2,603 of 2,776 — is accurate, as
are §5's 717 provision headings and §6.4's 315 `TOC5` against 315 `ActHead5`.

---

## What I would do, in order

1. **Finding 2** — the number-shape invariant. 204 edges wrong in the corpus
   now, 121 of them pointing away from a record that exists, and the check is
   the one already written for the symbol. Largest correctness gain for the
   least new judgement, and it is the field the retrieval layer leans on
   hardest.
2. **Finding 1** — stop making a definition transparent to the address. It is
   the only finding that is currently mis-describing the law as defective, it
   removes 51 spurious `number_collision` flags, and it shrinks finding 5's
   crash surface as a side effect.
3. **Finding 4** — slug the defined term. Do it in the same change as 1: they
   touch the same addresses, and doing them apart repoints the same 189 units
   twice. This is the change with the best ratio of cost to future pain, for the
   same reason finding 6 of the 0.7.0 review was — the corpus is still unseeded.
4. **Finding 3** — read the AustLII node prefix. Eight edges, self-contained,
   and it converts them from wrong to correct rather than merely to absent.
5. **Finding 5** — the validator gaps and the suffix allocation. The suffix fix
   is three lines and should not wait, because the failure is a stopped crawl.

**On `EXTRACTOR_VERSION`.** Findings 2 and 3 change `chunk.provisions` and so
move the Manual corpus: that is an `ingest` bump and a full-page rewrite, and
they should ride together. Findings 1, 4 and 5 change unit refs and so move the
legislation corpus: that is a `legislation` bump. The two halves version
independently, so this is two rebuilds, not one — but each is one rebuild rather
than three, and `--from-raw --force` prices both without touching the network.

Findings 3 and 5 are the only ones where no wrong byte is in today's snapshot
for the Manual and the legislation corpus respectively. They are in this list
because each fires on an ordinary amendment, and one of them fires by stopping
the crawl.
