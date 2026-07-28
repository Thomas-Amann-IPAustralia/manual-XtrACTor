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

Measured 27 July 2026 (T2). Re-measure when a crawl reports a materially
different count — a moved page count is usually a restructure, not an edit.

| | |
|---|---|
| Parts | 54 |
| Pages | 502 |
| Non-page nav links | 1 (see §13) |
| Nav links that 404 | 1 (see §14) |
| Mean page size | 88.4 KB (n=20, median 84.6 KB, range 81–109 KB) |
| Extrapolated `snapshot/raw/` | ~44 MB |

Well inside the gigabyte at which `ARCHITECTURE.md` says to stop and reconsider,
and it only grows by the pages that actually change.

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

## 14. The nav links to a page that is not there

Part 1 links *"Part 1.3. Practice Change Procedure"* to a URL that 404s:

```
/trademark/1.5   ->   404
```

Not a redirect, not a moved page — the Manual's own sidebar pointing at nothing.
Found on the first live run of the orchestration (T7, 27 July 2026), where it
aborted the crawl on the third page of the first Part.

This is distinct from §13. There the nav points at something real that is not a
page, and the target is excluded by path before anything is fetched. Here the
nav points at a page-shaped URL that the site will not serve, and there is no
way to know that without asking.

So the crawler records it and carries on. A 404 hands us nothing, which means
nothing can be silently wrong — rule 3's failure mode is not available — while
abandoning 501 good pages to protect against it is simply losing the snapshot.
The run names the page in its report and in `manifest.json` under
`run.unreachable`, no record is written for it, and any record already held is
left exactly as it was. The page stays in the nav, so it is *not* retired:
retirement means gone from the inventory, and this is present but unserved.

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
