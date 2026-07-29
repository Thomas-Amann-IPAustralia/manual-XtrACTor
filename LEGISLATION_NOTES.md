# The legislation source, and its quirks

`SOURCE_NOTES.md` for the Trade Marks Act 1995 and the Trade Marks Regulations
1995 as the Federal Register of Legislation publishes them. Everything here was
found in the live API or in the real compiled documents, most of it the hard
way. Read it before writing any parser under `src/frl_snapshot/`.

The Manual's notes and these are separate files because the sources have almost
nothing in common. The Manual is practice, published as rendered HTML by a
Drupal CMS with no API. These are law, published as compiled Word documents
through a public OData API, drafted to a fixed stylesheet by the Office of
Parliamentary Counsel. What they share is the reference grammar — §8 — and that
is deliberate.

---

## 1. Do not scrape the document text off the website

`https://www.legislation.gov.au/{titleId}/latest/text` renders its content
client-side. Measured on the Trade Marks Act 1995:

| Source | Extracted text |
|---|---|
| `/latest/text` via an HTTP client and a readability extractor | **18,002 chars** — nav chrome, breadcrumbs, a table of contents |
| `documents/find(…type='Primary',format='Word')` | **348,772 chars** — the actual Act |

That is 5% of the document, and the 5% containing no legal content. It looks
like a successful scrape: HTTP 200, no block signature, plausible text with the
Act's name in it. Nothing fails loudly, which is the whole problem.

The `.gov.au` estate also runs WAFs that block cloud and CI egress addresses, so
an approach that works from a laptop fails from a runner.

**Use the API for text.**

---

## 2. Two identifier systems, and only one of them is the amendment signal

- **`titleId`** identifies the *law*, permanently. `C2004A04969` is the Trade
  Marks Act 1995 forever, across every amendment. `F1996B00084` is the Trade
  Marks Regulations 1995. `C…A…` is an Act; `F…L…` and `F…B…` are legislative
  instruments.
- **`registerId`** identifies one *compiled version* of that law.
  `C2024C00545` is Compilation 47 of the Act, in force from 14 October 2024.

**A new `registerId` is the amendment signal**, and it is a better one than
anything this repository could compute. It changes if and only if a new
compilation was registered. It is one small JSON GET. It is immune to a
re-render that changes bytes without changing law, which is exactly the failure
mode a content hash has. `config.INSTRUMENTS` maps our codes to `titleId`s;
`instrument.json` stores the `registerId`; `crawl.py` compares them.

As of 29 July 2026: the Act is at Compilation 47 (`C2024C00545`, 14 October
2024) and the Regulations at Compilation 53 (`F2026C00009`, 18 December 2025).
The Regulations move considerably more often than the Act.

### `hasUnincorporatedAmendments` is the gate's blind spot

`false` means the compilation reflects all amendments in force. **`true` means
amendments have been made and have commenced but are not yet incorporated into
any compilation** — the document is legally out of date and `registerId` has
*not* changed. There is nothing newer to fetch in that state, so the flag is
recorded on `instrument.json` and surfaced in the run report. A reader needs to
know the snapshot is behind; a pipeline that ignored this would report the law
as current indefinitely.

---

## 3. The API

```
Base URL:  https://api.prod.legislation.gov.au
Auth:      none for public reads
Protocol:  OData v4
```

### 3.1 Function-call syntax

The `find()` endpoints are OData *functions*, so parameters go inside
parentheses and string values need single quotes:

```
/v1/Versions/Find(titleId='C2004A04969',asAtSpecification='Latest')
```

Do not URL-encode the parens, commas or quotes.

### 3.2 Casing is inconsistent between endpoints

Not a transcription error — it mirrors the live API:

- `Versions/Find(titleId=…, asAtSpecification=…)` — **camelCase**
- `documents/find(titleid=…, asatspecification=…)` — **all lowercase**

### 3.3 Three "optional" parameters that are not optional

`documents/find()` declares `uniqueTypeNumber`, `volumeNumber` and
`rectificationVersionNumber` as optional with a default of `0`. They are not
optional. Omit them and the call returns a bare `404` with an empty body —
identical to the response for a document that genuinely does not exist, which
is what makes the mistake expensive: it reads as missing data rather than as a
malformed request. `api._REQUIRED_DEFAULTS`.

### 3.4 The same URL serves two different things

By default `documents/find()` returns the file. With `Accept: application/json`
it returns *metadata about* the file. A session-level Accept header therefore
returns a description of the Act where the Act was wanted, with a 200 and no
error. `api.download` builds its own headers for this reason, and treats a 200
carrying JSON as a miss.

An HTML error page served as `200` is the other case; guarded by a content-type
and size check.

### 3.5 `Find()` returns a bare object

Not an OData `{"value": [...]}` envelope. Indexing into `["value"]` is the
reflex to resist.

### 3.6 Endpoints that are in the spec and do not work

`/v1/Affect` and `/v1/_AffectsSearch` both return **404** live (checked 29 July
2026) despite appearing in the OpenAPI spec and the entity-set index. Do not
build on them.

---

## 4. Take the Word document, not the PDF

Live figures for the Act, Compilation 47:

| Format | Size | Notes |
|---|---|---|
| `Word` | 261 KB | **What we take.** Carries the OPC stylesheet — see §5. |
| `Pdf` | 910 KB | The only `isAuthorised: true` rendition. Bad for extraction. |
| `Epub` | 197 KB | HTML in a zip; usable, structurally noisier. |

If legal authority ever matters, keep the PDF alongside rather than instead.

**The bytes are stable.** Downloading the same compilation twice returns
byte-identical files: every zip entry's timestamp is pinned to 1980-01-01. That
is what lets `snapshot/legislation/*/raw/*.docx` be stored verbatim without
breaking rule 2.

### Do not convert to HTML on the way in

The obvious approach is Mammoth to HTML and then a readability extractor, and
it is wrong here for the same reason a general-purpose HTML-to-markdown library
is wrong for the Manual (`SOURCE_NOTES.md`): it silently discards the one thing
the whole extraction depends on. Every structural fact about the law is carried
in a `w:pStyle` name. Convert first and the hierarchy has to be guessed back out
of leading tabs and bracket shapes, which is the guess rule 1 forbids.

`zipfile` and `xml.etree` are enough. No dependency was added.

---

## 5. The OPC stylesheet is the structure

The Office of Parliamentary Counsel drafts every Commonwealth instrument to a
fixed template. The style names *are* the schema:

| Style | Means | Becomes |
|---|---|---|
| `ShortT`, `LongT`, `CompiledActNo`, `CompiledMadeUnder` | instrument identity | `instrument.json` |
| `ActHead1` | Chapter or Schedule | container |
| `ActHead2` | Part | container |
| `ActHead3` | Division | container |
| `ActHead4` | Subdivision | container |
| `ActHead5` | section / regulation / Schedule clause | **provision** |
| `ItemHead` | Schedule amendment item | **provision** |
| `subsection` | `(1)` | unit |
| `subsection2` | unnumbered prose | unit |
| `paragraph` | `(a)` | unit, depth 1 |
| `paragraphsub` | `(i)` | unit, depth 2 |
| `paragraphsub-sub` | `(A)` | unit, depth 3 |
| `Definition` | a defined term | unit, term in `emphasis` |
| `SubsectionHead` | run-in heading | unit, parents nothing |
| `Penalty` | penalty | unit |
| `notetext`, `noteToPara`, `notemargin` | a note | unit, child of what it follows |
| `notepara` | a paragraph of a note | unit, child of the note |
| `Specials` | text as it will read once modified | unit — see §6.3 |
| `TOC1`–`TOC9` | table of contents | **dropped** — see §6.4 |
| `ENote*` | endnotes | `endnotes.json` |

An unmapped style raises. That is deliberate: a style nobody has seen means the
template moved, and placing it at a guessed depth puts text under the wrong
provision, which still validates and is still wrong.

### The two-space separator

A provision heading is `41  Trade mark not distinguishing…` — number, **two
spaces**, title. This holds in 717 of 717 provision headings across both
instruments. A single space is not a separator; it occurs inside titles.

This is why `docx.Block.text` keeps its whitespace and `Block.normalised()` is
a separate call. Collapse first and `1  Short title` becomes `1 Short title`,
where the separator cannot be told from the space inside the title and the
number can only be recovered by guessing how much of the line it is. The
heading regexes match raw text; only what they capture is normalised.

Container headings use an em dash: `Part 1—Preliminary`, with a non-breaking
space after the word.

---

## 6. Where the documents fight back

### 6.1 Part numbering restarts inside every Schedule

The Regulations set `Part 1—Preliminary` in the body, `Part 1—Classes of goods`
inside Schedule 1, and `Part 1—Costs` inside Schedule 8. Three different things
with one printed address. A container ref that did not carry its Schedule would
merge them.

Schedule clauses and Schedule items restart too: every Schedule has an item 1.
So `TMR1995/sch3/item1` and `TMR1995/sch9/c1`, never `TMR1995/item1`.

### 6.2 An `ActHead5` inside a Schedule is a clause, not a regulation

Schedule 9 of the Regulations opens `1  Table of fees`. Read as a regulation
that is `TMR1995/r1`, which collides with the clause 1 of every other Schedule
and sits oddly beside regulation 1.1. `structure._provision` reads the
container stack and calls it `TMR1995/sch9/c1`. The abbreviation key in
Endnote 2 confirms the word: `c = clause(s)`.

### 6.3 `131A  Definitions` appears three times and is not a section

Schedules 3, 4 and 5 of the Regulations each modify Part 13 of the Act for a
different external territory, and each inserts a section 131A. The inserted
text is set in the `Specials` style and *looks exactly like a section heading*.
Treated as one it would collide three ways with itself and once with the real
section 131A. It is a unit inside its Schedule item, addressed from there, and
`kind: "special"` says what it is.

### 6.4 The table of contents duplicates every heading

315 `TOC5` paragraphs against 315 `ActHead5` headings in the Act. Carrying it
would put every heading in the corpus twice and make a renumbering look like a
rewrite. Dropped, and counted in the manifest so the drop is visible rather
than assumed.

### 6.5 Law sits directly under a container, with no provision heading

This is the one that silently ate content. Schedule 2 of the Regulations is a
bare list of prohibited signs — `Austrade`, `C.E.S.`, `Olympic Champion` — with
no Part, no `ActHead5`, no `ItemHead`. Schedule 1 is a class table under a Part
and nothing else. Schedule 8 numbers its clauses *inline* (`1. Subject to
clause 1A…`) in body style rather than as headings.

None of it is reachable from a provision heading, and all of it is operative
law. `kind: "container"` gives the container itself an address so the text has
somewhere to go. Before that existed it fell into a bucket called front matter
and was indistinguishable from the compiler's preamble.

Schedule 8's inline clause numbering is *not* promoted to structure. The
drafter did not mark it up, so recording it as a heading would be an inference;
the numbers are visible in the text and a consumer can read them.

### 6.6 The Act's Reader's Guide has no number and is amendable

Endnote 4 lists `Reader's Guide` and `List of terms` as provisions affected by
amendments — they are part of the Act — but the document gives them no number
anywhere. They sit before Part 1, mixed in with the compilation's own preamble
("About this compilation", "Compilation No. 47").

Splitting the compiler's words from the Act's would mean deciding where one
stops and the other starts from the shape of the prose. Both are captured
together at `TMA1995/front`, `kind: "front-matter"`, which claims nothing about
which is which. It is addressable and diffable; it is not pretending to be a
section.

### 6.7 The Regulations number two provisions twice

Real defects in the compiled instrument, not in the reader:

- **`r17A.61(2)`** has two paragraphs lettered **(b)**.
- **`r20A.22(2)(b)`** has two subparagraphs numbered **(ii)**.

A citation to either address names two different provisions. This is the same
class of problem as the two Manual pages that both print the address 20.2
(`SOURCE_NOTES.md` §31), and it gets the same answer: record the ambiguity,
do not resolve it. Both units keep their printed `number`, both carry
`number_collision: true`, and only the second takes a positional `~2` suffix so
the addresses stay distinct. Which one holds the unsuffixed ref is arbitrary,
which is precisely what the flag says.

### 6.8 A provision's paragraphs can hang off an unnumbered subsection

Section 42 reads `An application … must be rejected if: (a) …; or (b) …`. The
opening words are an *unnumbered* subsection, so a naive tree addresses the
paragraphs `s42~1(a)`. Everyone — the Manual 39 times, the courts, the Act's own
cross references — cites them `s 42(a)` and `s 42(b)`.

A unit therefore builds its address from the nearest **numbered** ancestor,
while `parent_ref` keeps recording the true tree. Sections 15, 42, 53 and 62
are all this shape. Getting it wrong cost 62 of the Manual's provision edges
their target.

### 6.9 Notes attach to what they follow, and nothing more is claimed

`notetext` carries no indication of scope. Section 41's Note 1, Note 2 and
Note 3 all follow subparagraph (4)(b)(iii) and plainly concern the whole
section. The parser records them as children of the unit they follow, because
that is a fact of document order, and records the style verbatim so a consumer
can disagree. Consecutive notes are siblings, and a `notepara` belongs to its
note rather than to the previous `notepara` — without that rule section 41
alone descends five levels.

---

## 7. The endnotes are the instrument's own amendment history

Every compilation ends with four endnotes. Two are valuable:

- **Endnote 3, legislation history** — 46 rows for the Act: every amending Act
  with its number, year, assent date and commencement.
- **Endnote 4, amendment history** — 317 rows: one per provision touched, as
  `s 41 | am No 45, 2006`.

This is the same thing the Manual carries in its per-page "Amended Reasons"
table, and it is captured for the same reason — except that it reaches back to
1995 and is per provision.

**The provision labels are not resolved to refs, on purpose.** That parse looks
trivial on the rows that are section numbers and is not trivial at all on the
rest: the column also holds `Reader's Guide`, `List of terms`, `Part 1`,
`Div 2 of Part 3`, `ss 41–43`, `s 41(3)(a)` and `Sch 1`. A resolver that
handles the easy 60% and quietly mangles the rest is exactly the silently-wrong
record rule 3 exists to prevent. Turning Endnote 4 into amendment edges is
ontology work with its own error model — the layer above this one. Deferred,
not forgotten; `TASKS.md` T14.

---

## 8. The reference grammar is shared with the Manual, deliberately

`tmm_snapshot.citations` already emits `TMA1995/s41`, `TMA1995/s44(3)(a)` and
`TMR1995/r3A.3` for Manual chunks. Those are the strings this corpus uses as
its own provision and unit refs. **A Manual chunk's `provisions[].id` is a
foreign key into this snapshot with no transformation in between.**

That is why `config.Instrument.code` must not be changed casually, and why
`test_frl_references.py` asserts that `config.Instrument.symbol` agrees with
`citations.instrument_kind` — two independent readings of one fact, so a
disagreement means one corpus is addressing provisions the other does not have.

`frl_snapshot.references` reuses `citations.extract_provisions` rather than
re-implementing it, passing an empty markup fragment. Two consequences:

- **Every edge from this corpus is `extraction: "regex"`.** A compiled
  instrument carries no hyperlinks at all — zero `w:hyperlink` elements in
  either document — so there is no href evidence to be had. That is a fact
  about the source, not a gap in the reading.
- **Because the ids are this corpus's own refs, provision edges double as the
  instrument's internal cross-reference graph**, at no extra cost.

### What is knowingly not resolved

Inside the Act, "this Act" and "the Act" are anaphoric to the instrument
holding them; inside the Regulations, "the Act" means the Trade Marks Act 1995.
Both are obvious to a human and neither is resolved, because `citations`
deliberately omits "the Act" from its instrument table (`SOURCE_NOTES.md` §4)
and teaching it a rule that depends on which document is being read would
change what a *Manual* edge means. A bare `section 41` lands on `TMA1995/s41`
at `certainty: "default"`, which is correct for both instruments.

### The coverage figure

`python -m frl_snapshot.validate` reports how many of the Manual's in-scope
provision edges resolve. At `legislation/0.1.0`: **2,603 of 2,776**.

It is a report, never a failure. The 173 that do not resolve are worth
understanding rather than fixing:

- Manual citation defects — `TMA1995/s21.28(1)(a)`, `TMA1995/s2.1.1` and 98
  others are dotted addresses that are regulation numbers or the Manual's own
  heading numbers, written as sections.
- References to superseded numbering — `TMA1995/s41(6)` is the pre-2012 section
  41, discussed in a Manual Annex about the law before Raising the Bar. The
  snapshot holds the *latest* compilation, so this correctly does not resolve.
- `TMA1995/s26(3)` — the Part 22.1 anaphora case, which `SOURCE_NOTES.md` §4
  says is the 1955 Act and unresolvable by regex.

**Watch the number, not the failures.** If it falls, a citation regex or a
numbering assumption has moved.

---

## 9. Courtesy

Volume is trivial — two version probes and, when something changed, two
document downloads. The politeness rules still apply, and one is stricter than
the Manual's:

- `www.legislation.gov.au/robots.txt` asks for **`Crawl-delay: 10`**, and
  disallows `/assets/`. Honoured on that host, checked on every run and never
  cached across runs.
- `api.prod.legislation.gov.au` serves **no robots.txt at all** (404). Nothing
  is asserted about it, so the general 1s delay applies.
- One request at a time; back off on 429 and 5xx.
- A `--force` re-cut of a compilation already on disk costs the Register
  nothing: a `registerId` names one immutable compilation, so the stored `.docx`
  is reused rather than re-fetched.

---

## 10. Adding another instrument

One entry in `config.INSTRUMENTS` and a fixture. The pipeline has nothing else
keyed on which law it is reading. Obvious candidates, none in scope today:

- **Trade Marks Act 1955** — `SOURCE_NOTES.md` §4's anaphora case turns on it,
  and having it would let the Part 22.1 ambiguity be checked rather than
  recorded.
- **Acts Interpretation Act 1901** — the Manual cites it and the Act's Reader's
  Guide names it as directly relevant.
- The Trade Marks Amendment Acts, for point-in-time work.

Each is a scope decision. Raise it, do not just add it — and note that the 1955
Act in particular would change what "in scope" means in the §8 coverage figure.

---

## 11. What this snapshot is not

It holds the **latest compilation** of each instrument. It is not a
point-in-time archive: `/v1/Versions?$filter=titleId eq '…'&$orderby=start desc`
lists every historical compilation with the exact window it was in force, and
`documents/find(registerId='…')` fetches any of them. Building that is a
different shape of repository — one file per provision per version — and a
decision to raise rather than make.

What it does keep is the previous `.docx` under `raw/`, so the compilation this
snapshot replaced is still on disk and in git history.
