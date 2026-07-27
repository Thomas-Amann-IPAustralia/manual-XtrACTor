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
| `aia1901230` | Acts Interpretation Act 1901 |

These give near-certain Manual→provision edges straight from the markup, with no
inference. Record them with `extraction: "href"`.

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

---

## 8. Cross references come in two forms

Hyperlinked:

```html
<a href="http://manuals.ipaustralia.gov.au/trademark/annex-a1-...">Annex A1</a>
```

And bare text: `see part 22.15.7`, lowercase, no link. Both are worth capturing.
Resolve hyperlinked ones through the sitemap. For bare textual ones, resolve the
dotted address to a `page_ref` if one exists; if it does not resolve, **drop it**
rather than storing an unresolvable string.

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
| Mean page size | 88.4 KB (n=20, median 84.6 KB, range 81–109 KB) |
| Extrapolated `snapshot/raw/` | ~44 MB |

Well inside the gigabyte at which `ARCHITECTURE.md` says to stop and reconsider,
and it only grows by the pages that actually change.

**T7 owes the manifest these numbers.** `write_manifest` does not exist yet, so
they live here for now; they belong in `snapshot/manifest.json` once it does.

### Settled since

- **`robots.txt`.** Stock Drupal. Disallows `/core/`, `/admin/`, `/user/login`
  and friends; says nothing about `/trademark`, and sets no `Crawl-delay`. Still
  check it on every run — this is a snapshot of one day, not a licence.
- **ETag / Last-Modified.** Both sent on every response, and both honoured:
  `If-None-Match` and `If-Modified-Since` each return `304` on their own. Gate 1
  of the skip logic works, and a re-crawl costs the site almost nothing.
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
