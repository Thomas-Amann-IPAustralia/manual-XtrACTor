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

Top-level `<li>` items are Parts, labelled `Part 22 Section 41 - Capable of
Distinguishing`. Their `href` is a placeholder (`<>` or `#`), not a real link.
Children are pages. Nesting can go three deep (Part 32B → `Part 32B.2.
Examination of Wine Trade Marks` → `Part 32B.2.3 Section 41: ...`), so walk
recursively and carry the Part down.

Part numbers take alpha suffixes: `19A`, `19B`, `32A`, `32B`. Do not parse as int.

---

## 3. Act sections are already hyperlinked to AustLII

Statutory references in the prose carry real links:

```html
<a href="https://austlii.edu.au/cgi-bin/viewdb/au/legis/cth/consol_act/tma1995121/s41.html">section 41</a>
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
third row above — reason can be blank. Handle it.

Separately, pages carry a `Date Published` field. Different thing; capture both.

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

Scope to `<main>` / `#main-content`, then to `.node__content` where it exists,
then strip the known boilerplate strings.

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

## 12. Things not yet verified

Stated plainly so nobody treats them as settled:

- **Total page count.** Unmeasured. Establish in Task 2 and record in the manifest.
- **`robots.txt` contents.** Must be checked on every run; do not assume.
- **ETag / Last-Modified support.** Drupal usually sends them. Verify before
  relying on 304s as the primary skip gate; fall back to hash comparison if not.
- **Whether Part numbering is globally unique.** Assumed yes. If two Parts ever
  share a number, `page_ref` collides — assert uniqueness when building the
  sitemap so this surfaces immediately rather than silently.
- **Real amendment cadence.** Unknown. The weekly CI schedule is a guess. Measure
  it over the first two months and tune.
