# Source notes: how the Manual actually behaves

Field observations from the live site (`manuals.ipaustralia.gov.au/trademark`),
verified July 2026. Each of these cost time to discover. Read before writing a
parser; re-read when a parser surprises you.

The site is Drupal 10. Treat markup as unstable and structure as stable.

---

## 1. The Manual is practice, not law

It states the Registrar's practice under the **Trade Marks Act 1995 (Cth)** and
the **Trade Marks Regulations 1995**. It guides examiners toward consistent
application; it is not the legislation, and it does not bind the Registrar's
discretion.

This is not a philosophical aside — it shapes the data model. The Manual, the Act
and case law are three separate corpora. This repo snapshots **only the Manual**.
Act text and case text are never inlined, only referenced by identifier. An
answer that blurs "IP Australia's stated practice" with "the law" is wrong even
when every fact in it is accurate.

---

## 2. The navigation tree is the only reliable source of Part membership

The full sidebar nav — every Part, every child page, in order — is rendered into
**every single page**. Fetch one page and you have the complete inventory.

This is not merely convenient. It is load-bearing, because **the URL does not
tell you which Part a page belongs to.**

### The slug collision trap

```
/trademark/2.3-section-41--capacity-to-distinguish     ->  Part 32A.2.3  (plants, class 31)
/trademark/2.3-section-41--capacity-to-distinguish1    ->  Part 32B.2.3  (wines, class 33)
```

Identical slug. The trailing `1` is a Drupal collision counter, not a Part
number, not a version, not a sequence. The same pattern appears throughout:

```
/trademark/relevant-legislation28   ->  Part 20
/trademark/relevant-legislation44   ->  Part 22
/trademark/1.-introduction1         ->  Part 32A
/trademark/1.-introduction7         ->  some other Part entirely
```

Two pages about section 41 capacity to distinguish, saying **different things**,
because one concerns plant varietal names and the other geographical indications
for wine. Attribute one to the wrong Part and every downstream citation about
wines points at plants.

**Therefore:** parse the nav once per crawl into an inventory keyed by normalised
URL. Look every page up in it. If a page is not there, raise — do not fall back
to slug parsing. Ever.

### Nav shape

The tree is in `div.nested-nav`, which appears exactly once per page.

Top-level `<li>` items are Parts, labelled `Part 22 Section 41 - Capable of
Distinguishing`. Their `href` is a placeholder — the live site emits an **empty
string**, and `<>` and `#` have also been seen — not a real link. Children are
pages. Nesting can go three deep (Part 32B → `Part 32B.2. Examination of Wine
Trade Marks` → `Part 32B.2.3 Section 41: ...`), so walk recursively and carry
the Part down.

**The nesting is not where the markup says it is.** A child `<ul>` is emitted as
a *sibling* of the `<li>` it belongs to, never as a descendant:

```html
<li><a class="folder" href="">Part 1 Introduction, Quality</a></li>
<ul><li><a href="/trademark/1.-introduction7">Part 1. Introduction</a></li></ul>
```

That is invalid HTML, and it has two consequences that cost real time:

1. `li.find_all('ul')` finds nothing. Ancestry has to be recovered by walking a
   `<ul>`'s children in order and treating a nested `<ul>` as belonging to the
   `<li>` before it.
2. **The parser choice is load-bearing.** `html.parser` preserves the shape as
   written. `lxml` and `html5lib` "correct" it into a different tree and the
   Part ancestry silently comes out wrong. `config.HTML_PARSER` is pinned for
   this reason; changing it misattributes pages without failing.

`class="folder"` marks a node with children. A node can carry both a real href
and `folder` — `3. Indexing and Re-scanning` is a page *and* a parent — so
"has children" is not "is not a page".

Part numbers take alpha suffixes: `19A`, `19B`, `32A`, `32B`. Do not parse as int.

### Nav title numbering is inconsistent, even within one Part

Two conventions are mixed freely:

```
Part 32B.2.3 Section 41: Capacity to Distinguish   Part-qualified
2.3 Section 41: Capacity to Distinguish            page-local (Part 32A)
```

Strip the qualifier only when the title *starts* with `Part ` and the leading
component matches that Part's own number. Otherwise Part 22's page
`22. Numerals` has its leading `22` mistaken for the Part number and flattened
away.

Some titles are qualified down to nothing: `Part 1. Introduction`, inside Part 1,
leaves no page-local address at all. Those fall back to the slug form like any
other unnumbered page. Do not invent `1.1` for it — the Manual does not say that.

---

## 3. Act sections are already hyperlinked to AustLII

Statutory references in the prose carry real links, confirmed live in Part 22.1
(they also carry `target="_blank"`, which is noise):

```html
<a href="https://austlii.edu.au/cgi-bin/viewdb/au/legis/cth/consol_act/tma1995121/s41.html" target="_blank">section 41</a>
```

The db fragment identifies the instrument:

| fragment | instrument |
|---|---|
| `tma1995121` | Trade Marks Act 1995 |
| `tmr1995264` | Trade Marks Regulations 1995 |
| `tmr1995230` | Trade Marks Regulations 1995 (Part 5's Relevant Legislation page, 28 July 2026) |
| `aia1901230` | Acts Interpretation Act 1901 |

The trailing digits are a consolidation number, so **one instrument has several
fragments** and the Manual's own pages disagree about which to link. Do not treat
the table as a whitelist: read the abbreviation and year off the fragment, and
keep the table as the record of what has been seen and the check that the
derivation agrees with it.

These give near-certain Manual→provision edges straight from the markup, with no
inference. Record them with `extraction: "href"`.

The link addresses a whole section; the **link's own words carry the
subsection**, and sometimes more than one:

```html
<a href=".../tma1995121/s41.html">sections 41(3) or 41(4)</a>
```

That is two provisions, both stated by the authors. Read the numbers out of the
anchor text and keep only those whose section matches the href — an anchor
reading "here" or "this provision" then falls back to the bare section.

**AustLII node names are lower case, and always `s`-prefixed.** Section 217A is
`consol_act/tma1995121/s217a.html`; regulation 21.11A is
`consol_reg/tmr1995230/s21.11a.html` — `s`, not `r`, even for a regulation, so the
symbol comes from `consol_act` / `consol_reg` and never from the node name.

The prose beside the link writes `section 217A`. Upper-case the number and its
letter suffix when building the id, or one provision becomes two edges —
`TMA1995/s217a` from the href and `TMA1995/s217A` from the mention — and only the
second matches the schema. Found on Part 5's Relevant Legislation page, crawl of
28 July 2026. Paragraph letters inside parentheses are a separate address space
and keep the case they were written in: `s44(3)(a)` is not `s44(3)(A)`.

A letter suffix also rides on **any** dotted component, not only the first: the
Regulations have a Part 3A (`r3A.3`) and inserted regulations (`r21.11A`).

Not every legislative link is AustLII. `legislation.gov.au` links appear too, and
they address instruments by an opaque series id (`C2004A02362`) with no
deterministic route back to an abbreviation. They produce no href edge; the
surrounding prose usually names the instrument anyway, so the regex layer picks
them up.

**Consequence for tooling:** do not run the body through a generic
HTML-to-markdown or text-extraction library before extracting citations. Those
libraries discard or flatten hrefs, and the entire high-confidence citation layer
goes with them. Extract citations from the DOM, then extract text.

---

## 4. Plain-text section references are inferences, and sometimes wrong

Not every reference is hyperlinked. Text mentions must be regexed, and regex
cannot see context.

### The anaphora problem — a real, unresolved bug

Part 22.1 contains, across consecutive sentences:

> "...registrability of trade marks was governed by sections 24, 25 and 26 of the
> **Trade Marks Act 1955**."
>
> "Trade marks which did not meet the stringent tests for Part A were considered
> under **section 26 of the Act** for registration in Part B of the Register."

The second "the Act" means the **1955** Act. A lookahead for a named instrument
finds nothing adjacent and defaults to the Trade Marks Act 1995. Wrong.

The mitigation is a scope window: look ahead ~60 characters for a named
instrument. That correctly attributes `section 7 of the Acts Interpretation Act
1901` to `AIA1901/s7`, and correctly attributes `sections 24, 25 and 26 of the
Trade Marks Act 1955`. It does not solve the anaphoric case, and **no regex
will.**

**Do not attempt to solve this with a model.** Rule 1. Instead:

- Record `extraction: "regex"` so the edge is distinguishable from a hyperlinked one.
- Record `certainty: "explicit" | "default" | "ambiguous"`.
- Mark `ambiguous` when the chunk mentions more than one instrument and the
  reference is bare. That flag is the whole mitigation: downstream, ambiguous
  regex edges are used for nothing except a human review queue.

A wrong edge that knows it might be wrong is fine. A wrong edge that looks
certain is not.

### The lookahead needs two brakes, not one

Sixty characters is wide enough to reach backwards into the *next* reference's
instrument. In Part 22.1:

> "...in relation to the amendments to **section 41**. As such the application of
> section 41 is regulated by **section 7 of the Acts Interpretation Act 1901**."

The Acts Interpretation Act sits about sixty characters after the second
`section 41`, so a plain window attributes it to `AIA1901/s41`. Cut the window at
the next reference, and at the next full stop — no instrument title contains one.

### Two brakes are not enough either: the Relevant Legislation pages

**Known defect, unfixed. Found on the first live crawl, 27 July 2026.**

Both brakes above are prose brakes, and the Relevant Legislation landing pages
are not prose. They are a list: one provision per block, no full stops anywhere,
each instrument's name appearing as a *heading above its own group*. Normalisation
joins those blocks with single spaces, so by the time the regex layer sees the
text the boundaries are gone. On Part 4's page:

> "...Paragraph 231(2)(e) Remission of fee **Section 256** Fees (transitional
> provision) **Trade Marks Regulations 1995 (Cth)** Reg 21.21 What fees are
> payable..."

`Section 256` is the last entry under the *Act*. `Trade Marks Regulations 1995`
is the heading of the group that follows it. No full stop separates them and no
reference intervenes, so neither brake fires, and the window attributes an Act
section to the Regulations — emitting `TMR1995/s256` with
`certainty: "explicit"`. An `s` provision under a Regulations instrument is a
contradiction in terms, and "explicit" is the strongest claim the schema can
make. This is the exact failure §4 opens by warning about: a wrong edge that
looks certain.

The missing brake is a **block boundary**. The information exists — the DOM has
it, and `extract_provisions` already receives the body fragment — but it is
destroyed before the regex layer runs, so the fix is a decision about where
normalisation happens rather than a regex tweak, and it is left for a human:

- Deriving a block-aware string inside `citations.py` keeps `text` and every
  `content_hash` untouched, but duplicates `page.py`'s normalisation contract in
  a second place, which is how the two drift apart.
- Preserving a separator in the normalised text is cleaner and fixes it once,
  but changes every `content_hash` in the corpus — a full re-crawl and a
  thousand-file diff. Cheap now, while the snapshot is unseeded; expensive later.

A cheap interim guard, if the above is deferred: an `s` provision resolving to a
Regulations instrument (or `r` to an Act) is structurally impossible — reject it,
or downgrade it to `ambiguous`, rather than publishing it as explicit.

### An instrument title contains a keyword and a number

`Trade Mark Regulations 1995` — note the Manual's own singular *Mark*, on the
Part 32B landing text — matches any pattern looking for *regulation* followed by a
number, and yields the phantom provision `TMR1995/r1995`. A reference falling
wholly inside a named instrument's title is part of the title. Drop it before
anything else looks at it, or it also truncates the lookahead of the real
reference in front of it.

### 'the 1995 Act' is a name; 'the Act' is not

The year picks the instrument out, so `section 41 of the 1995 Act` is explicit.
`section 26 of the Act` is the anaphora above. Both forms count towards *how many
instruments are in scope*, which is what turns a bare reference from an
assumption into an ambiguity — and so does a title we do not recognise, such as
the `Wine Australia Act 2013` on the Part 32B page. Erring towards ambiguity puts
a reference in front of a human; erring the other way does not.

---

## 5. Every page carries its own amendment log

Near the bottom, under an `Amended Reasons` heading:

| Amended Reason | Date Amended |
|---|---|
| Minor updates. | 19 Dec 2022 |
| Update hyperlinks | 20 Apr 2022 |
|  | 09 Nov 2021 |

IP Australia's own words for what changed. This is as close to a change feed as
the Manual has, and it is the single most useful metadata on the page: paired
with a content hash diff, it distinguishes a substantive practice change from a
link tidy-up without anyone reading the diff.

Capture the most recent row as `last_amended` and `amendment_note`. Note the
third row above — reason can be blank. Handle it. A reason cell can also hold
several `<p>`s, which is one reason spread over two sentences, not two reasons.

Both dates come from a Drupal `<time>` element that carries a machine-readable
attribute, so nothing here needs a date-string parser:

```html
<time datetime="2022-12-19T12:00:00Z" class="datetime">19 Dec 2022</time>
```

Attribute *order* varies between the served markup and anything re-serialised
by BeautifulSoup, so match on the element and read the attribute — never on a
literal `<time class=... datetime=...>` string.

Rows are served newest-first, but that is a rendering choice and not a contract.
Pick the most recent row by comparing dates, breaking ties on document order, so
that a reordered table does not change the output.

The block lives in `div.view-amended-reasons`, outside the body field. Its
wrapper carries a `js-view-dom-id-<hash>` class; ignore it, and never let it
into a hash.

Separately, pages carry a `Date Published` field, in `div.py-3` labelled by a
`strong.field-label-inline`. Different thing; capture both.

Strip the table and its heading from the body before chunking. It is metadata,
not content, and it will otherwise pollute a chunk and match on searches for
dates.

---

## 6. Boilerplate on every page

Remove before chunking, or it lands in a chunk and gets retrieved:

- `Skip to main content`
- `Back to top`
- `This document is controlled. Its accuracy can only be guaranteed when viewed
  electronically.`
- The whole footer: `IP Australia | Delivering a world leading IP system`, About
  Us, Disclaimer, Privacy, Accessibility, etc.
- The nav tree itself. Obvious, but note that naive text extraction pulls the
  entire Manual's table of contents into every single page.

Scope to `<main>` / `#main-content`, then to the content wrapper, then strip the
known boilerplate strings.

**The content wrapper is `div.field--name-body`, not `.node__content`.**
`.node__content` does not exist anywhere on this install; it was a guess from
generic Drupal and it is wrong. Checked against a 20-page sample spread across
the Manual: `<main>`, `div.field--name-body`, `link[rel=canonical]`,
`div.view-amended-reasons`, `div.py-3` and `div.block-page-title-block h1` are
present on all of them.

Scoping to the body field removes every boilerplate string above on its own —
they all live in the header, the footer or the nav column. Strip them anyway.
The day the scoping breaks is the day they end up in a chunk and get quoted back
to an examiner as though they were practice.

Note that `<main>` **contains the nav column** (`div.col-lg-3.nested-nav`), so
`main.get_text()` pulls the entire Manual's table of contents — about 25 KB and
500 titles — into every page. Scoping to `<main>` alone is not scoping.

Inside the body field the prose is wrapped several divs deep in Drupal layout
scaffolding (`div.zone > div.section12 > div#section1control1 > div`), and some
of those zones are empty. Headings are therefore *not* direct children of the
body field; walk in document order rather than iterating children.

The prose carries stray zero-width spaces (`U+200B`) — the opening line of Part
22.1 has seven consecutively — and non-breaking spaces. Strip the former and
fold the latter when normalising, or they show up in the text and in the hash.

`get_text()` is wrong for this corpus whichever separator you give it. Instrument
names are wrapped in nested inline elements mid-sentence —
`<span><i><i>Trade Marks Act 1955</i></i></span>.` — so `get_text(" ")` produces
*"Trade Marks Act 1955 ."*, and the text stops matching the Manual's own words.
`get_text("")` fixes that and welds adjacent paragraphs and list items into one
word instead. Break on block elements only; the source's own whitespace already
sits inside the text nodes.

---

## 7. Heading numbering is inconsistent across Parts

The page `<h1>` sometimes carries a full dotted address and sometimes does not:

```
22.1. Registrability under section 41 of the Trade Marks Act 1995     -> '22.1'
32A.2.3 Section 41: Capacity to Distinguish                           -> '32A.2.3'
Relevant Legislation                                                  -> none
```

Within a page, sub-headings are `<h3>` numbered like `1.1 The 1955 Act`,
`1.2 Intellectual Property Laws Amendment (Raising the Bar) Act 2012`. Sometimes
`<h2>`. Sometimes unnumbered.

Derive `page_ref` from the nav title's leading number where present, and fall
back to a slug-derived form for unnumbered pages (Relevant Legislation, Glossary,
Annexes). Never fall back to the raw slug alone — see §2.

`chunk_ref` follows the same shape one level down: the heading's own number
where it has one, a slug of the heading's text where it does not. §18 has the
measurements and the reason position was not good enough.

### A heading number can be broken up by inline markup

Part 28.3 prints two headings whose numbers an editor has partly highlighted:

```html
<h4>3.<span class="highlightColorYellow">2</span>.1</h4>
<h4>3.<span class="highlightColorYellow">3</span> &nbsp;Whether instances of confusion have in fact occurred</h4>
```

The highlight is a leftover from drafting and carries no meaning, but it splits
the number across three text nodes. Read with `get_text(" ")` those headings are
`3. 2 .1` and `3. 3 Whether...`, and the leading address of both is `3` — so
both address as `TMM/Part28/3/3` and crawl #5 died on the collision, correctly:
two passages cannot share an address.

Read heading text through `flatten_text`, which contributes a separator on block
elements only. The source's own whitespace is already inside the text nodes, so
`3.<span>2</span>.1` reads back as `3.2.1`. This is the same failure
`flatten_text` was written for in prose — *'Trade Marks Act 1955 .'* — arriving
in a heading, where it corrupts an address rather than a sentence.

Note that this is *not* the same as a genuinely repeated heading number, which
still raises: there the Manual really has printed one address twice, and the
Manual is what has to be corrected.

### Headings are the only boundary the Manual asserts

`div.zone` looks like structure and is not. Zones break wherever the page author
pressed a button: around a call-out, around a single line of example text
(`FANTASIA Dianthus 'Londaison'`), around nothing at all — Part 32A.2.3 has
fourteen of them, four empty. Cutting on zones produces chunks of two words.

Two consequences for the chunker. It cuts on `<h2>`–`<h4>` and on nothing else,
which means a call-out in its own zone stays in the chunk of the heading it falls
under. And a *sub*-heading is sometimes not a heading element at all —
`2.3.5(b) Evidence of use` is a bare `div` in its own zone — so it is not a
boundary, because there is no deterministic way to tell it from a line of
emphasised prose.

Note also that the page's opening prose frequently belongs to a numbered heading
that has no heading element: Part 32A.2.3 prints no `<h3>` for 2.3.1 even though
2.3.2 through 2.3.5 are all there. That prose addresses by position, not number.

---

## 8. Cross references come in two forms

Hyperlinked:

```html
<a href="http://manuals.ipaustralia.gov.au/trademark/annex-a1-...">Annex A1</a>
```

And bare text: `see part 22.15.7`, lowercase, no link (Part 32B.2.3). Both are
worth capturing. Resolve hyperlinked ones through the sitemap — by URL, never by
slug or title, because slugs collide across Parts.

**Bare references address headings, not pages.** No page has the address
`22.15.7`: pages in the inventory bottom out at `TMM/Part22/15`, and `.7` is a
heading on it. Resolving the full address alone therefore drops nearly every bare
reference. Shorten the address one component at a time until a page in the
inventory matches, and stop before the Part — `TMM/Part22` is not a page. If
nothing matches, **drop it** rather than storing an unresolvable string.

A reference like `Part 22 of this Manual` names a Part and not a page, so
requiring at least one dotted component keeps it out.

---

## 9. Case citations appear in two styles

Neutral, mostly modern:

```
Vokes Ltd v Laminar Air Flow Pty Ltd [2018] FCAFC 109
```

Reported, mostly older, and common in the specialist Parts:

```
Wheatcroft Bros Ltd's Trade Marks (1954) 71 RPC 43
```

Courts seen: `HCA`, `FCAFC`, `FCA`, `ATMO`, `APO`. Reported series seen: `RPC`,
`CLR`, `FCR`, `ALR`, `IPR`, `ATR`. Both styles need patterns; neither is
hyperlinked.

Capture the citation and a canonical id. Do not attempt to resolve party names —
they are unreliable to extract and nothing downstream needs them yet.

---

## 10. Amendments are not just edits

The Manual is periodically overhauled Part by Part under an external academic
review arrangement, not merely tweaked. Expect occasional runs where a whole Part
is restructured: pages renamed, split, merged, renumbered.

Design for this rather than being surprised by it. Concretely: retire pages
rather than deleting them (`ARCHITECTURE.md` §Retirement), diff the sitemap as
well as the pages, and make the change report loud when a Part's page count moves.

Legislative amendments drive Manual updates too. The Trade Marks Amendment
(International Registrations, Hearings and Oppositions) Regulations 2025 took
effect November–December 2025, and the corresponding Manual Parts followed.

---

## 11. There is no API and no bulk download

Rendered HTML only. No JSON, no XML, no change feed, no sitemap.xml worth using.
Crawl-and-diff is not a design choice, it is the only option.

The Act and Regulations themselves are on the Federal Register of Legislation
(`legislation.gov.au`) with point-in-time compilations, and are **out of scope for
this repo** — but they are why `provision_id` uses stable, addressable identifiers
rather than free text. A later repo joins on those ids.

---

## 12. The corpus, measured

First measured 27 July 2026 (T2) from a 20-page sample, and **re-measured
28 July 2026 from the first complete crawl**. Re-measure again when a crawl
reports a materially different count — a moved page count is usually a
restructure, not an edit.

| | | |
|---|---|---|
| | **Measured (full crawl)** | *Estimated (n=20)* |
| Parts | 54 | *54* |
| Pages | 502 | *502* |
| Non-page nav links | 1 (see §13) | *1* |
| Nav links that 404 | **2** (see §14) | *1* |
| Pages that are only an image | 8 (see §16) | *not seen* |
| Images in page content | 169, across 39 pages | *not seen* |
| Tables in page content | 121, across 45 pages | *not seen* |
| Chunks | 2151 | *not estimated* |
| Chunks addressed by a heading | 1561 (72%, see §18) | *not seen* |
| Mean page size | 88.6 KB | *88.4 KB (median 84.6, range 81–109)* |
| `snapshot/raw/` | 44.3 MB | *~44 MB* |

Well inside the gigabyte at which `ARCHITECTURE.md` says to stop and reconsider,
and it only grows by the pages that actually change. In the repository it costs
far less than that: 49 MB of working tree packs to about 2.6 MB, because every
page carries the same 80 KB of sidebar nav and git deltas it away.

**The size estimates held; the counts did not.** Extrapolating page size from 20
pages was accurate to 0.2%. Extrapolating *incident* counts from the same sample
was not, and could not have been: a sample of 20 sees the 404 that happens to be
on page 3 of Part 1 and cannot see the one in Part 27. Read the estimated column
as what was knowable that day, not as a measurement that drifted.

These numbers are now measured by every run and written to
`snapshot/manifest.json` under `corpus` (T7). The table stays as the reading
taken on the day, to compare a later run against.

### Settled since

- **`robots.txt`.** Stock Drupal. Disallows `/core/`, `/admin/`, `/user/login`
  and friends; says nothing about `/trademark`, and sets no `Crawl-delay`. Still
  check it on every run — this is a snapshot of one day, not a licence.
- **ETag / Last-Modified.** Both sent on every response. Both are honoured *on
  their own* — and sending both at once is answered `200` every time. Corrected
  27 July 2026 (T7), having found gate 1 firing on nothing:

  ```
  If-None-Match: "1785133603-gzip"           -> 200
  If-None-Match: "1785133603"                -> 304
  If-Modified-Since: <date>                  -> 304
  If-Modified-Since: <date> + If-None-Match  -> 200
  ```

  Two separate things are going on. The Manual is served by Apache with
  mod_deflate, which appends `-gzip` to the ETag it sends but compares an
  incoming `If-None-Match` against the unsuffixed value — so echoing back the
  ETag the server itself gave us can never match. And RFC 9110 gives
  `If-None-Match` precedence, so a request carrying both has its date check
  ignored. Sending both is therefore not belt and braces: the broken validator
  silently disables the working one, for every page.

  `fetch.py` sends `If-Modified-Since` alone where a `Last-Modified` is known,
  and falls back to `If-None-Match` only where one is not. It does not strip
  the `-gzip` suffix: that would be guessing at a server's bug from the outside
  and would break the day the server stopped having it. Gate 1 now returns
  `304` for every unchanged page, and a re-crawl costs the site almost nothing.
- **Raw HTML is stable between fetches.** Two fetches of the same unchanged page
  were byte-identical — no per-request tokens, no rotating asset URLs, at least
  while `x-drupal-cache: HIT`. Normalise before hashing anyway: the guarantee is
  the CMS's to withdraw, and the normalisation is also what makes the hash
  ignore class churn while still noticing a changed `href`.
- **Part numbering is globally unique.** All 54 confirmed distinct. Still
  asserted when building the sitemap, because a restructure could break it.

### Still not verified

- **Real amendment cadence.** Unknown. The weekly CI schedule is a guess. Measure
  it over the first two months and tune.

---

## 13. The nav links to things that are not pages

Part 51 links a `.docx` flowchart straight out of the sidebar:

```
/sites/default/files/trademark/document/revocation-of-acceptance-for-matters-relating-to-oh-flowchart.docx
```

It is a resource the nav points at, not a page of the Manual: no `<main>`, no
`Amended Reasons`, no prose to chunk. One today, and no reason to expect it to
stay one.

The inventory therefore admits only nav targets under
`manuals.ipaustralia.gov.au/trademark/`. Everything else — uploaded documents,
other IP Australia sites, external links — is excluded, deterministically and by
path, rather than being discovered at parse time on every crawl. This is the one
place the pipeline drops something rather than raising, and it is narrow on
purpose: the rule is a whitelist of one path, so anything genuinely surprising
still surfaces as a missing page rather than as a mangled one.

---

## 14. The nav links to pages that are not there

Two of them, both the Manual's own sidebar pointing at nothing:

```
Part 1.3. Practice Change Procedure   /trademark/1.5                        -> 404
Part 27.2. Legal submissions          /trademark/27.2.---legal-submissions  -> 404
```

Neither is a redirect and neither is a moved page.

The first was found on the first live run of the orchestration (T7, 27 July
2026), where it aborted the crawl on the third page of the first Part. The
second was not found until the first *complete* crawl, on 28 July 2026 — and
the gap is the point. Until then no run had ever reached Part 27: the T7 run
was `--limit 20` and stopped inside Part 5, and the run after it died about 185
pages in on the archived-page markup of §15, which sits in Part 23. A count of
rotted links taken from a partial crawl is a count of the rotted links in the
part that was crawled.

So: when a run reports a number of unreachable pages that differs from the
table in §12, check how far the last run that measured it actually got before
concluding the Manual has changed.

This is distinct from §13. There the nav points at something real that is not a
page, and the target is excluded by path before anything is fetched. Here the
nav points at a page-shaped URL that the site will not serve, and there is no
way to know that without asking.

So the crawler records them and carries on. A 404 hands us nothing, which means
nothing can be silently wrong — rule 3's failure mode is not available — while
abandoning 500 good pages to protect against it is simply losing the snapshot.
The run names each page in its report and in `manifest.json` under
`run.unreachable`, no record is written for it, and any record already held is
left exactly as it was. The pages stay in the nav, so they are *not* retired:
retirement means gone from the inventory, and these are present but unserved.

Two things this deliberately does not do. It does not guess a substitute URL —
`1.5` looks like it wants to be a dotted address, and acting on that is exactly
the inference rule 1 forbids. And it does not shrug off a site-wide failure: a
run where *nothing* in scope could be fetched raises, because that is not a
rotted link, that is the site refusing us, and a manifest reporting a successful
crawl of nothing would be a lie.

---

## 15. Some pages are archived, and have no body field at all

An archived page keeps its nav entry, its `<h1>` and its complete `Amended
Reasons` table, and has its prose removed. In place of the body field it
carries a banner:

```html
<div class="alert alert-warning py-3 my-3" role="alert">
  <p>This page has been archived.</p>
  <p class="mb-0 pb-0">If you would like to submit feedback, please
     <a href="...">contact us</a>.</p>
</div>
```

`div.field--name-body` is **absent**, not empty. §6 says that wrapper is present
on every page; that was measured on a 20-page sample and it is wrong for this
class of page. Found on the first full crawl (28 July 2026), which died about
185 pages in on:

```
/trademark/annex-a4---how-to-supply-evidence-of-use-of-a-trade-mark-under-
subsection-415---for-trade-marks-with-a-filing-date-prior-to-15-april-2013
```

The parser had raised `UnrecognisedMarkup`, which was the right instinct
applied to the wrong page: a missing content wrapper usually does mean the
markup has moved under us, and chunking on regardless would pull the whole nav
into a record. But this page is not misunderstood. It states its own condition,
in a fixed element, in fixed words.

So the banner is matched structurally and exactly — `div.alert[role='alert']`
containing a `<p>` whose normalised text equals `This page has been archived.` —
and a page with no body field is archived **only** if that banner is there.
Without it, the raise stands. The distinction is the whole point: it keeps the
"the site has changed shape" alarm working while stopping it firing on a page
the Manual has merely emptied.

An archived page is recorded, not skipped: `archived: true` on the page record,
the amendment history preserved, `chunks: []`, and a `content_hash` over an
empty body. Preserving the history is the reason not to drop it — the archival
itself shows up as a row in the table (*"Not required."*, 10 Oct 2023 on Annex
A4), and that row is the Manual telling you when it stopped being practice.

Not to be confused with either neighbour. §14 is a nav entry the site will not
serve — nothing is returned, so nothing is recorded. Retirement is a page gone
from the nav, and the file moves to `pages/_retired/`. Archived pages sit in the
tree, serve a 200, and are current in the only sense the crawler can check.

---

## 16. Eight pages are an image and nothing else

Found on the review of the first complete crawl (28 July 2026). These pages
serve a 200, carry a normal `div.field--name-body`, are not archived — and the
body holds one `<img>` and no text at all:

```
Part 14  Annex A10, A11, A12   cross-search class tables
Part 22  Annex A2              'Capable of Distinguishing' flowchart
Part 35  Annex A1              Certification Trade Marks flow chart
Part 45  Annex A1              flow chart of production of copies
Part 54  Annex A2, A3          format of a summons, of a notice requiring production
```

Corpus-wide there are 169 images across 39 pages; on these eight the image *is*
the page. **None of the 169 carries any `alt` text** — not an empty `alt`, no
attribute at all — which is worth knowing because *"Accessibility fix –
alternative text for images"* is one of the Manual's own amendment reasons, on
28 pages. Whatever that fix was, it did not reach any image in the Manual.

Two neighbours that look like this class and are not, both worth keeping
straight because a consumer filtering on `chunks: []` will meet them:

- **Part 14 Annexes A6–A9** are the same kind of cross-search class table, but
  each carries a one-line heading above the image — *"CROSS SEARCH CLASSES
  PRE-JUNE 2000"* — so each yields exactly one chunk of that heading and
  nothing else. Text-bearing by the letter of it; no more legible than A10–A12.
- **Part 39 Annex A1**, *"Certificate of Registration"*, has no image **and** no
  text. Its body field holds nothing but empty Drupal layout divs. It is a stub
  in the source, and the empty record is the correct reading of it — the one
  page in the corpus where `chunks: []` and `images: []` together are the whole
  truth.

The chunker is right to yield nothing for them: there is no text to chunk, and
inventing a caption from the filename would be exactly the inference rule 1
forbids. But until the review, a consumer reading `pages/*.json` saw
`"chunks": []` and could not tell an image-only page from a blank one — the
`<img>` existed only in `snapshot/raw/`.

So `page.images` records every image in the body as `{"src", "alt"}`. `src`
verbatim, because rewriting a URL is a transformation this record cannot
afford; `alt` distinguishing null (no attribute) from `""` (an empty one,
HTML's spelling of "decorative"), because collapsing those two hides precisely
the amendment described above.

Three things this does **not** do, each on purpose:

- **It does not fetch the image.** The bytes are not in the snapshot, so for
  these eight pages the repository holds no evidence of what the Manual actually
  said — only that it said it in a picture, and where the picture was. If
  IP Australia moves `/sites/default/files/`, that content is gone from the
  archive. That is a real gap and it is recorded as one.
- **It does not read the image.** No OCR, no model, no caption. See TASKS.md
  §T11 for where that belongs, which is not in this pipeline.
- **It does not treat an image-only page as empty.** `archived` is the Manual
  saying a page is no longer current; `chunks: []` with a non-empty `images` is
  a page whose content this pipeline cannot render as text. Different facts,
  and a consumer needs both kept apart.

One quirk worth recording: Part 14's Annex **A10** embeds
`part14-annexa9.gif`, and Annex A9 embeds `part14-annexa8.gif`. The filenames
are off by one against the annex numbers. That is the source's own numbering,
not a mis-parse — the `src` is recorded exactly as written, and anyone matching
images to annexes by filename will get it wrong.

### How a reader should render one (decided 0.5.0)

**A placeholder, not the image.** Naming the page, saying its content is a
figure this archive has not captured, and linking out to the live page. Not an
`<img>` pointed at `manuals.ipaustralia.gov.au`.

Two reasons, and the second is the one that matters. Hotlinking would make
every view of the archive a request to a Commonwealth agency's servers, which
§Courtesy to the source in `CLAUDE.md` rules out for the crawler and should
equally rule out for anything reading its output. And it would render as
though the archive held the content when it does not: the snapshot has the
`src` and nothing behind it, so a live-loading image shows a reader something
this repository cannot vouch for and will silently show them nothing at all
once the path moves.

The three states a reader must tell apart are already fully determined by the
record, and no field needs adding to say so — `SCHEMA.md` §What is deliberately
absent applies:

| `archived` | `chunks` | `images` | Render as |
|---|---|---|---|
| `true` | `[]` | `[]` | withdrawn by IP Australia; show `amendment_note` |
| `false` | `[]` | non-empty | a figure, uncaptured; placeholder + link out |
| `false` | `[]` | `[]` | a stub in the source (Part 39 Annex A1 alone) |

---

## 17. Tables are content, and flattening loses half of them

121 tables across 45 pages, and several pages — Part 10's Annex A1 and A2, the
Part 12 divisional examples — are essentially nothing but a table.

`flatten_text` renders one as a run of cell text:

```
Owner Name Address Description Individual Surname + Given name/s (not trading
style) Address and address for service in Australia or New Zealand not required
Corporate Body Full designation (not trading style) as above ACN, ABN or ARBN
```

Every word is there, in order, and which cell sat under which column is not.
That is the correct value for `chunk.text` — it is the verbatim reading, and
the only string SCHEMA.md permits quoting to an applicant — but on its own it
throws the grid away. `chunk.tables` carries the grid alongside it.

What the markup actually looks like, measured over all 121:

| | |
|---|---|
| Plain `<tr>`/`<td>`, no header markup | 119 |
| `<thead>` or an all-`<th>` first row | 2 |
| `colspan` | 4 |
| `rowspan` | 3 |
| Ragged rows | 7 |
| Containing an image | 11 |
| Containing a heading (`<h4>` inside a cell) | 2 |
| Nested tables | 0 |

**The header problem.** 119 of 121 tables have a first row that reads exactly
like a header — *"Owner | Name | Address | Description"* — and says so nowhere
in the markup. Deciding it is one on the strength of how the words look is an
inference about meaning, so `header_row` is null for all 119 and the row stays
in `cells` as data. A consumer that wants to treat row 0 as a header may; this
pipeline will not do it for them. Only `<thead>` and `<th>` count.

**Headings inside tables.** Part 29.4 puts two `<h4>PLATYPUS</h4>` inside table
cells. The chunker does not cut on them, because a `<table>` is one unit and
splitting inside one is forbidden — which is why that page is a single chunk
despite having headings. Correct, and worth knowing before someone "fixes" it.

**Spans are recorded, not expanded.** `colspan="2"` is stored on the cell.
Which grid positions the span covers is a rendering question, and answering it
means writing cells the Manual never wrote.

---

## 18. Heading numbering decides how stable a citation is

The Manual numbers most of its headings and not all of them, and that single
fact decides whether a `chunk_ref` survives the next amendment.

Measured over the 2151 chunks of the 28 July 2026 corpus, by *why* each got the
address it did:

| Cause | Chunks | Can an insertion move it? |
|---|---|---|
| Numbered heading — `15.4 Names of foreign towns…` | 784 (36%) | No |
| Unnumbered heading — `Adhesive`, `Disclaimer` | 777 (36%) | **Yes, before 0.4.0** |
| No heading at all — the page preamble | 590 (27%) | No |

**The middle row was the whole problem, and the bottom row never was.** A
section with no heading is by definition the prose above the *first* heading,
so it is the first section on the page and nothing can be inserted ahead of it.
All 590 sit at ordinal 1. A `#1` is as stable as a number; only `#N` with N > 1
could ever move, and every one of those had an unnumbered heading above it.

### It was one page

Of the 777 exposed chunks:

| Page | Chunks | Cumulative |
|---|---|---|
| Part 14 Annex A13 — *list of terms too broad for classification* | 627 | 81% |
| Part 5 — device constituents | 43 | 87% |
| Part 29 Annex A1 — table of INN stems | 23 | 90% |
| Part 5 — word constituents | 21 | 92% |
| 20 further pages | 63 | 100% |

24 pages carry the whole of it. A13 is an alphabetical glossary of vague
classification terms which the Manual's own opening line calls
*"non-exhaustive"* — a list IP Australia expects to add to. Under positional
addressing, inserting `Adhesive tape` between `Adhesive` and `Adhesives`
repointed every one of the ~600 addresses below it, and nothing in the output
said so: the diff showed a page rewritten, not a citation broken.

### What 0.4.0 does

An unnumbered heading is addressed by a slug of its own text —
`TMM/Part14/x-14.-annex-a13-…/adhesive` — falling back to position only for a
heading whose text is punctuation alone, which has never been seen.

Verified over all 24 affected pages before the change and again by the rebuild:
**no slug collides with another on its page**, and none slugs to an empty
string. Two that did would raise `ChunkRefCollision`, which is the existing
behaviour for two chunks deriving one address and the right one — an address
shared by two passages is a citation nobody can resolve.

Slugs are **not truncated**. The longest is 158 characters
(`TMM/Part26/x-annex-a1---citing-multiple-names/citations-when-one-mark-consists-of-a-given-name-and-the-other-the-name-of-a-person-incorporating-the-given-name`).
A length cap would collide headings differing only past the cut, and `page_ref`
already carries segments as long for the same reason.

No `x-` prefix, unlike the slug fallback on `page_ref`. There it marks a
segment that could otherwise be read as the Part-local number the Manual
prints; here a segment of words is self-evidently not a heading number.

### The trade, stated plainly

A slug breaks when IP Australia rewords the heading. A position broke when
anything above it moved. The first is rarer, and — this is the part that
matters — it is *visible*: rewording a heading changes `heading_path` and the
chunk text, so it appears in the diff as an amendment. A shifted ordinal
appeared as nothing at all.

Afterwards: 1561 of 2151 chunks (72%) carry a heading-derived address, up from
784 (36%), and every remaining positional address sits at `#1`.

### If you are tempted to number the headings yourself

Don't. Deriving `15.5` for an unnumbered heading that follows `15.4` is
inventing an address the Manual does not print, and the next crawl will invent
a different one when a heading is inserted between them. The slug says only
what the heading says.

---

## 19. A heading can be the whole section

Found in the 0.5.0 review, by counting headings in the cleaned bodies against
headings reaching a `heading_path`. Fourteen did not, across ten pages, and
the reason was the same in every case: the `<h2>`–`<h4>` had no content
element after it, so the chunker produced no chunk and the heading's words
went nowhere.

Three shapes, all real.

**The Manual states the proposition in the heading.** Part 61.3 has four
sections and two of them are written this way:

```html
<h3>3.2 Documents that are not made available for public inspection can be
    requested under the Freedom of Information Act.</h3>
<h3>3.3 A request can be made under the FOI Act for any of the documents
    listed at paragraph 3.1.</h3>
<p>To the extent that these documents contain sensitive business …</p>
```

3.3 survived because a paragraph follows it. 3.2 and 3.4 did not, so the
snapshot held half of a page about what the Registrar will and will not
disclose. Not a formatting quirk — those are statements of practice.

**Footnotes are set as headings.** Parts 49.2, 52.4 and 55.2 close with an
`<h4>` holding a numbered footnote. They carry citations, and the citations
went with them: Part 55.2's reference to *AKT Consultants Pty Ltd v Alfa Laval
Lund AB* (2006) 70 IPR 347 reached no case list at all, and Part 49.2's to
s 25C of the *Acts Interpretation Act 1901* reached no provision list.

**The heading is a label inside an example.** Part 29.9 sets the applicant of
each worked example as `<h4>XYZ Company</h4>` with the mark below it as an
`<h3>`. Nothing is lost in prose terms — but see below, because these are what
made the fix bite.

### What 0.5.0 does

A heading with no content under it is chunked as its own content. The words are
on the page and belong to no other section, so `text` is the heading and the
leaf of `heading_path` equals it. An *empty* heading — six pages have an `<h3>`
holding only a stripped image or a non-breaking space — is still skipped;
there is nothing in one to record.

### The collision this uncovered, and why a label is not a number

Emitting those sections immediately raised `ChunkRefCollision` on Part 29.9:
both examples are headed `XYZ Company`, both sections are heading-only, and both
derived `TMM/Part29/9/xyz-company`. Part 29.4 does the same with the specimen
mark `PLATYPUS`.

§18 says a repeated heading *number* raises, and that stays true — the Manual's
numbering is what a citation rests on, and two `8.1`s is a defect a human should
take up with its authors. A repeated *label* is different. The Manual never
promised that a label would identify a section, only that a number would, so
there is no defect to report and nobody to report it to; and raising would mean
this corpus could not be snapshotted at all.

So the page is read before it is addressed. `_repeated_labels` counts the
slug-derived addresses on a page, and a heading whose label the page prints more
than once falls back to the positional form. Four sections across two Part 29
pages take it. `ChunkRefCollision` still guards everything downstream.

---

## 20. A three-column table, flattened, reads as one sentence

Found in the 0.5.0 review by asking a question the schema cannot: does the
instrument in a provision id hold the kind of provision the id names?

Twenty did not. Every one had the shape `TMR1995/s224` — section 224 of the
*Regulations*, which does not exist; s 224 is in the Act. Every one was recorded
`certainty: "explicit"`, the confident end of the scale, the only regex tier
`SCHEMA.md` says may hydrate primary law into an answer.

The cause is §17 meeting §4. A Relevant Legislation page is a three-column
table:

| Section 224 | Extension of time | Trade Marks Regulations 1995 |

`chunk.text` renders it as a run of cell text, so those three cells become one
line, and the 60-character instrument lookahead that hangs off `Section 224`
reaches straight past two column boundaries into the instrument column of the
same row.

The fix is not a wider or narrower window — any window can cross a boundary the
flattened text no longer marks. It is that **an Act holds sections and
Regulations hold regulations, and neither ever holds the other's**. The
reference word and the instrument title are two independent readings of one
fact, so where they disagree the title is not this reference's instrument, and
it is discarded. The reference then falls through to the same treatment as an
unqualified one: `TMA1995/s224` at `default`.

Discarded rather than raised on, because the row is not malformed. It says
exactly what it means to a reader who still has the columns.

`validate.py` now asserts the invariant over the whole snapshot, so a future
extractor cannot reintroduce it quietly.

---

## 21. Naming the Act and the Regulations together is not an ambiguity

Also 0.5.0. 757 of 1939 regex provision edges — 39% — carried
`certainty: "ambiguous"`, a bucket `SCHEMA.md` says never to hydrate from. That
is not a corpus that is 39% doubtful; it is a rule firing on the wrong thing.

The rule was: more than one instrument named anywhere in the chunk makes a bare
reference ambiguous. But nearly every page of the Manual names both the Act and
the Regulations, because the Relevant Legislation preamble lists them together
at the top. So `section 41` on a page that also mentions reg 4.15 was called
ambiguous — when `section` already says, on its own, that the reference is to an
Act.

Only an instrument that could *hold* the reference competes for it. Filtering
the scope by the reference's own kind before counting leaves 134 ambiguous
edges, and they are the ones the flag exists for: 1955-vs-1995 Act passages,
the Raising the Bar annexes, the Acts Interpretation Act overlaps.

The Part 22.1 anaphora case of §4 — `section 26 of the Act`, in a paragraph
about the 1955 Act — has two *Acts* in scope and still comes out ambiguous.
That is the test that pins this, and it must not be allowed to pass by
accident.

---

## 22. An internal link can name a heading, not just a page

Also 0.5.0. Of the Manual's 524 internal hyperlinks, 137 carry a `#fragment`:

```
/trademark/4.-classification-procedures-in-examination#4.5-goods-or-services-to-be-grouped-together-by-class-number
```

The fragment is the Drupal slug of the target heading, and 47 of them open with
the number the Manual prints. That number is exactly what the chunker builds
the target's `chunk_ref` from, so `TMM/Part14/4/4/5` is determined, not guessed.
The other 90 anchor on a single letter — the Part 5 glossary and the Part 14
A13 index — and address no heading, so they stay page-level.

All 399 `internal_refs` in the 0.4.0 snapshot were page-level, because a single
pass cannot check a heading on a page it has not read. `ARCHITECTURE.md` §Two
phases is what changed to make it checkable.

Two things to know when reading the result:

- **A section long enough to split owns no bare address.** `TMM/Part14/4/4/8`
  is held by `…~1` through `…~4`, and a link to the heading is aimed at where
  the section starts, which is `~1` by construction. 27 of the 47 land here.
- **A heading that has gone coarsens, it does not vanish.** The page half of
  the reference was established by URL and is still true. Two of the 47 are
  this, on Parts 9.4 and 27.3, where the Manual has renumbered since the link
  was written.

32 references now address a chunk. It is a small number and it is the honest
one: it is every anchor whose target this snapshot can actually confirm.

---

## 23. Every table the Manual writes is wrapped in a `<figure>`

Found in the 0.6.0 review. The CMS's editor emits this:

```html
<figure class="table canvasRteResponsiveTable"><table class="ck-table-resized">
  <colgroup>…</colgroup><tbody><tr><td>Argentina</td>…</tr></tbody>
</table></figure>
```

106 of the corpus's 121 tables sit inside one. `figure` was in neither
`blocks._TRANSPARENT` nor `blocks._KINDS`, so `extract_blocks` fell through to
its catch-all and recorded the whole grid as a single `text` block: a 29-row
table arrived as one run-on line. Only 18 of 121 tables produced a `table`
block, and of the 104 chunks holding a table only 17 said so.

`chunk.tables` was unaffected throughout — `tables.py` finds the `<table>`
wherever it sits — so this was never a loss of the grid. It was a loss of
*where the grid goes*: a consumer reading `blocks` to lay a chunk out had the
table's words in the running order and the table's structure in a separate
array, with nothing to join them by.

`figure` is now transparent to `blocks.py` and still opaque to
`chunker._CONTAINER_TAGS`, and the asymmetry is deliberate. To the chunker the
figure is one unit, which is what stops a table being split across a fragment
boundary. To the block reader it is scaffolding. All 121 tables now record as
`table` blocks, and the count matches `chunk.tables` exactly.

---

## 24. An image has a place in the prose, and had nowhere to say so

`PageRecord.images` (§16) records that a page has images. It cannot record
*where* — and the Manual uses images inline, mid-argument, as the worked
examples of Parts 13, 19A and 26.

Two things were dropping them. `extract_blocks` recorded a block only when the
element flattened to some text, and an `<img>` flattens to none. Before that,
`chunker._group` measured every unit by its text length and discarded the
empty ones, so a loose `<img>` never reached the fragment at all.

Both now keep it, and an `image` block carries `src`, and `alt` where the
Manual wrote one — which across all 169 images it never has. **It is the only
block with no `text`.** That is not an oversight: `blocks` must join back to
`chunk.text` exactly, and a block carrying `""` would put a stray space into
the join. Its absence is what the join steps over, in `validate.py` and in
`tests/test_blocks.py` alike.

93 of the 169 images now have a position. The other 76 are in sections with no
words at all — 8 pages *are* an image and nothing else (§16) — and a chunk
needs text to exist, so those stay recorded at page level only. The image
bytes are still not in the snapshot, and no alt text is invented for them.

---

## 25. The Manual sets most of its subsections in bold, not in headings

The largest finding of the 0.6.0 review, and the only one that required
reading something the markup does not declare.

**456 numbered subsections across 88 pages are `<p><strong>3.1 …</strong></p>`
rather than `<h2>`–`<h4>`.** The chunker cuts on headings and nothing else, so
none of them was a boundary and none reached a `heading_path`. The effect was
not marginal: 39% of the corpus text sat under an empty heading path, 311
pages had no heading at all, and Part 10.3 — which prints 36 numbered
subsections — arrived as nine addressless chunks. Part 47.1 printed 19 across
27,599 characters.

Typography alone cannot decide this. The corpus has **898 wholly bold
paragraphs and only 471 are headings**; the rest are labels, callouts and
emphasised sentences. What makes it decidable is that the Manual numbers its
subsections against the page's own number, so the test is not "does this look
like a heading" but "does this continue this page's numbering":

1. the unit's entire content is one `<strong>` or `<b>` — a `<p>` wrapping
   one, or a bare one loose in a layout div (Part 35.1 does that);
2. it opens with a dotted number of at least two components, bounded by
   whitespace, a colon or end of string; and
3. that number extends **this page's** number by at least one component —
   `3.1` and `3.1.1` on page 3, `2.4.1` on page 2.4.

Rule 3 is the whole control, and it is nearly total: across the corpus it
admits 471 candidates and rejects **exactly one** dotted bold paragraph —
Part 60.4.25's `4.24.5 No Request for Transformation`, whose number belongs to
a different page. That one stays in the prose, because a heading whose number
contradicts its page is precisely what rule 3 of `CLAUDE.md` says not to
resolve.

Three further things worth knowing:

- **The level comes from the number, not the typography.** `3.1` is two
  components and sits where an `<h3>` sits; `3.1.1` where an `<h4>` does. A
  paragraph letter is one level deeper again, which the corpus confirms:
  Part 32A sets `2.1.2(a)` directly under a real `<h3>2.1.2</h3>`.
- **A subsection number with no title is still a heading.** Part 33.1 prints
  `1.1`, `1.2`, `1.3` and then `1.4 Definition of an association`. Twelve
  candidates are a bare number, and they are the Manual's own addresses.
- **Every chunk cut this way is marked `heading_source: "emphasis"`.** This is
  the one inference in the pipeline, and that field is what keeps it honest.
  A consumer wanting strictly the Manual's own structure filters to `markup`
  and knows exactly what it gave up.

491 chunks across 89 pages are now cut on an inferred heading. Text with no
heading fell from 39% to 29%, and pages with no heading at all from 311 to 264.

---

## 26. A footnote marker is not a heading number

Parts 49, 52 and 55 set their footnotes as an `<h4>`, with the marker in a
`<sup>`:

```html
<h4><span class="fontSizeMedium"><sup>2</sup> See&nbsp;AKT Consultants Pty Ltd
    v Alfa Laval Lund AB&nbsp;(2006) 70 IPR 347.</span></h4>
```

`_heading_address` reads the heading through `flatten_text` (§7), which gives
`2 See AKT Consultants…`, and `_LEADING_ADDRESS` matched the `2`. So footnote 2
took the address `TMM/Part55/2/2` — which reads as *heading 2 of page 55.2*,
and is the parent of that page's real sections `TMM/Part55/2/2/1` through
`/2/2/5`. A citation to the section resolved to a footnote. Part 49.2's
footnote held `TMM/Part49/2/1` and Part 52.4's held `TMM/Part52/4/5` the same
way.

This is a wrong address rather than a weak one, which is the failure
`SCHEMA.md`'s "a serial number is a citation that breaks silently" argument
exists to prevent — and the markup already draws the distinction needed to
avoid it. **`<sup>` appears in exactly three headings in the corpus and is a
footnote marker in all three; no heading number the Manual prints is
superscript.** A leading number that came out of a `<sup>` is therefore not
read as an address, and the heading falls through to the slug form like any
other heading the Manual did not number.

`TMM/Part55/2/2` now addresses section 2.2, as it always read.

The footnotes still inherit the ancestry the markup gives them — they are
`<h4>`s following the last `<h3>`, so they hang under the section above them.
That is faithful to the source and visibly odd in a tree; it is recorded here
rather than corrected, because moving them would be inventing a structure the
Manual has not written.

---

## 27. A heading that only names the sections below it

The heading-as-content branch (§19) exists for the heading that *is* the
proposition — Part 61.3 states two of its four sections entirely in their own
heading. It was firing on a second, different case: a heading whose content
lives in the subsections beneath it.

The Part 14 A13 glossary sets `A`, `B`, `C` … over the terms filed under each,
and produced 22 chunks whose entire text was one letter. Part 5's device
constituents added three; Part 28 one. Promoting the bold subsections of §25
made it much worse, since a heading immediately followed by its own first
subsection has no content of its own — the count went to 52.

Such a heading did not hold its section's content, so the branch's own reason
does not reach it, and every one of its children already carries the words in
`heading_path`. It is therefore not chunked, and **nothing is announced**,
because nothing leaves the corpus.

That leaves the case where a heading holds only a marker and has no
subsections to carry it: Part 23.2 prints a bare `<h3>2.2</h3>` whose `2.2.1`
and `2.2.2` are `<h3>` siblings in the markup (§28), so they are not its
children and the words really would vanish. Headings shorter than
`MIN_HEADING_CHUNK_CHARS` are dropped **loudly**, as a `SuppressedHeading`
warning naming the page and the text. Five characters sits above every marker
in the corpus and below every real proposition — the shortest of those is
Part 32A's `Divisions I: Principles`.

Exactly one heading in the corpus is dropped this way, and it is the only
place in 500 pages where a word of body text is not in the snapshot.

---

## 28. Numbering and markup disagree about nesting on three pages

Nine numbered parent/child pairs, out of 33 in the corpus, where the Manual's
own numbering says one heading is under another and the markup makes them
siblings — both are `<h3>`.

| Page | The Manual's numbering | The markup |
|---|---|---|
| Part 2.3 | 2.3.2.1 under 2.3.2 | both `<h3>` |
| Part 23.2 | 2.2.1 under 2.2 | both `<h3>` |
| Part 55.2 | the footnote of §26 | `<h4>` after the last `<h3>` |

`heading_path` follows the markup, because the markup is what the pipeline is
allowed to read. The disagreement is the Manual's, and it is recorded rather
than reconciled.

**For a reader building a tree, `snapshot/sitemap.json` is authoritative.** It
is the Manual's own navigation, it is the only reliable source of Part
membership (§2), and it settles the page hierarchy — including the three-level
pages like `TMM/Part60/4/7`. Within a page, `heading_path` gives the structure
the markup asserts and `chunk_ref` gives the number the Manual prints; where
those two disagree they disagree because the source does, and the three pages
above are the whole of it.

---

## 29. The Manual's hyperlinks were not in the snapshot

Found on 28 July 2026, by a reader looking at the reassembled Part 61.2 in the
viewer and noticing that the Manual's link on *section 217A* was gone.

It was, and so were 2,217 others. `chunk.text` is the words with the markup
gone, and until `ingest/0.7.0` the markup that went included every `<a>` on the
page. Two fields kept part of what the anchors said, and only the part each was
about:

- `provisions` records an AustLII provision href as `extraction: "href"` — the
  strongest citation edge the pipeline produces — but records the *provision*,
  deduplicated per chunk, with the URL and the position discarded.
- `internal_refs` records an href naming a page in the nav, resolved to a
  `page_ref` or `chunk_ref`, sorted, deduplicated, and again positionless.

Everything else was dropped where it was found. The corpus:

| Where the link points | Anchors |
|---|---|
| AustLII | 966 |
| The Manual itself | 527 |
| Federal Register of Legislation | 475 |
| TimeBase | 101 |
| WIPO | 86 |
| jade.io | 24 |
| Everything else — IP Australia, APRA, PM&C, WHO, WTO, UPOV, ACCC, Wikipedia | 39 |

**792 of the 2,218 reached the snapshot in no form whatever.** Every
legislation.gov.au and TimeBase link is in that number, and so is every jade.io
link to a decision the Manual is discussing.

### Part 61.2 is the case worth reading

The page cites section 217A of the Act three times and hyperlinks it twice —
to `timebase.com.au/IPAust/index.cfm?id=tmact:217a`, not to AustLII. So
`_href_edges` never saw it, and the three references were left to the regex
path, which recorded:

```json
{ "id": "TMA1995/s217A", "extraction": "regex", "certainty": "default",
  "mention": "section 217A" }
```

`default` means *a bare "section N", assumed to be the Trade Marks Act*. The
assumption is right, and the page was carrying the authors' own statement of it
in an href the snapshot was throwing away.

### What 0.7.0 does

`links.py` records every anchor in the chunk, in document order, with its href
verbatim and the offsets into `chunk.text` at which the Manual set it:

```json
{ "href": "http://www.timebase.com.au/IPAust/index.cfm?id=tmact:217a",
  "text": "section 217A", "start": 260, "end": 272 }
```

`text[start:end] == link.text` is the contract, and `validate.py` checks it
over every link in the snapshot rather than in a test alone. Offsets rather
than words, because 91 anchors share their words with another anchor in the
same chunk and matching them up afterwards would be a guess between the two.
Not deduplicated, because two links to one target are two links — the
difference from `internal_refs`, which answers a different question.

The field says what the Manual linked and where. It does not say what the link
*means*: `TMA1995/s217A` is still a `default` regex edge, because promoting it
would mean teaching the citation layer to read TimeBase and Federal Register
URLs, which is a change to what `extraction: "href"` asserts and belongs in its
own change. The href is now in the record for that work to be done from.

### The five anchors this does not reach

An `<a>` inside an `<h2>`–`<h4>` that opens subsections is inside a heading,
and a heading's words reach the snapshot as a `heading_path` string with no
structure to hang an offset on. Two on Part 2.1, three on Part 31.4:

| Page | Heading | Links to |
|---|---|---|
| Part 2.1 | `Trade Marks Act 1995` | legislation.gov.au |
| Part 2.1 | `Trade Mark Regulations 1995` | legislation.gov.au |
| Part 31.4 | `Subregs 4.15(a) and (b)`, `Subreg 4.15(d)`, `Subreg 4.15(da) and (e)` | AustLII r4.15 |

2,218 of 2,223 are recorded. The five are named here rather than made to
disappear, and a heading that is *itself* a chunk — the Part 5 glossary's A–Z
index heading, which is one `<h3>` holding 26 anchors — is not affected: its
text is a chunk's text and its links are recorded like any other.

### What it makes visible

47 of the 527 internal links name a Manual URL that is not in the nav
inventory. `internal_refs` drops those, correctly — an unresolvable reference
is worse than an absent one — and so, until now, a link the Manual had broken
looked exactly like no link at all. 26 are the glossary's A–Z anchors, which
point at `/trademark/a` … `/trademark/z` and never resolved; the other 21 are
ordinary cross references to pages that have moved, four of them to
`4.-factors-to-consider-when-assessing-section-43` from three pages in two
Parts. That is a defect in the Manual, it is now in the data, and a crawl will
show it being fixed.
