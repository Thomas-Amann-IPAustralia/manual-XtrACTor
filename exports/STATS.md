# The Trade Marks Manual, counted

Every number here is counted off `snapshot/pages/` and `snapshot/legislation/` by `exports/build_stats.py`. Nothing is estimated except where it says so.

Snapshot crawled `2026-08-03T09:25:26Z`, extractor `ingest/0.11.0`.

## 1. Size

|  |  |
|---|---|
| Parts | **54** |
| Pages | **500** |
| Chunks (addressable passages) | **2,460** |
| Words | **306,619** |
| Characters | **1,866,810** |
| Distinct word forms | **13,998** |
| Source HTML crawled | **44.3 MB** |
| Extracted text | **1.87 MB** |

The Manual is **306,619 words** — about 3.1 times the length of a 100,000-word book, or an estimated 25 hours 33 minutes of reading at 200 words per minute.

The pipeline reads 44 MB of rendered HTML and keeps 1.87 MB of text: **4.2%** of what the site sends is the Manual's own words. The rest is site chrome — and a large part of it is the navigation tree, which the CMS renders in full on every one of the 500 pages.

Tokens, by tokeniser:

| Encoding | Tokens | Tokens per word |
|---|---|---|
| `cl100k_base` | 389,655 | 1.27 |
| `o200k_base` | 385,987 | 1.26 |

There is no single token count of a corpus — a token is whatever a tokeniser says it is, and these two disagree by about 1%.

Average page: **632 words**. Average chunk: **125 words** (median 76).

**The ten longest Parts**

| Part | Words | Pages |
|---|---|---|
| Part 14 Classification of Goods and Services | 33,613 | 22 |
| Part 22 Section 41 - Capable of Distinguishing | 24,277 | 31 |
| Part 60 The Madrid Protocol | 19,211 | 37 |
| Part 26 Section 44 and Regulation 4.15A - Conflict with Other Signs | 14,646 | 11 |
| Part 21 Non-traditional Signs | 11,769 | 11 |
| Part 32A Examination of Trade Marks for Plants (in Class 31) | 11,692 | 14 |
| Part 5 Data Capture and Indexing | 11,336 | 9 |
| Part 19A Use of a Trade Mark | 11,327 | 9 |
| Part 23 Overcoming Grounds for Rejection under Section 41 - including Evidence of Use | 10,915 | 14 |
| Part 29 Section 43 - Trade Marks likely to Deceive or Cause Confusion | 9,894 | 13 |

**The five longest pages**

| Page | Words | Title |
|---|---|---|
| `TMM/Part14/x-14.-annex-a13-list-of-terms-too-broad-for-classification` | 18,166 | 14. Annex A13 List of terms too broad for classification |
| `TMM/Part26/6` | 6,863 | 26.6. Factors to consider when comparing trade marks |
| `TMM/Part30/3` | 5,902 | 30.3. Use contrary to law |
| `TMM/Part5/x-device-constituents` | 5,863 | Device Constituents |
| `TMM/Part19A/2` | 5,706 | 19A.2. Use 'as a trade mark' |

Longest single passage: `TMM/Part28/x-annex-a1---information-sheet-for-trade-mark-applicants#1~2`, 1,454 words. Shortest: `TMM/Part29/9#7`, 2 words — “XYZ Company”.


## 2. Shape

|  |  |
|---|---|
| Blocks (paragraphs, list items, tables, images) | **12,521** |
| Paragraphs | **7,632** |
| List items | **4,659** |
| Tables | **121** |
| Table rows | **845** |
| Table cells | **2,336** |
| Images | **169** |

Lists nest three deep at most: 4,568 top-level items, 87 at depth 2, 4 at depth 3. 37% of the Manual's blocks are list items — this is a procedures manual, and it reads like one.

Of 121 tables, **2** mark a header row in the markup. The rest give a consumer no way to know which row is the header, and the extractor does not guess. Largest table: 92 rows × 4 columns.

**Not one of the Manual's 169 images carries alt text.** All 169 of them have no `alt` attribute at all — not even the empty one that HTML uses to mean “decorative”. “Accessibility fix – alternative text for images” is nonetheless one of the Manual's own amendment reasons, on 43 page-amendments.

**Where the Manual's structure comes from**

| Heading of a passage | Chunks | Share |
|---|---|---|
| `markup` — an h2–h4, the Manual asserting the boundary | 1,473 | 60% |
| `emphasis` — a bold numbered paragraph, promoted by the chunker | 491 | 20% |
| `null` — prose above the page's first heading | 496 | 20% |

**20% of the Manual's passages sit under a heading the Manual never marked up as one.** They are bold paragraphs opening with a number that extends the page's own — the only inference in the whole pipeline, and it is recorded in the data rather than hidden. Across every ancestor rather than the leaf alone, 583 of 3,028 heading ancestries are inferred this way.

333 chunks are fragments of 143 sections too long to keep whole; the most-split section is in 10 pieces.

**15 pages yield no text at all**: 6 carry the Manual's archive banner, and 8 are a single image — a flowchart, a cross-search class table, the format of a summons. 1 is neither: it has no prose, no image and no banner.


## 3. How often the Manual links to itself

|  |  |
|---|---|
| Hyperlinks inside the Manual's text | **2,218** |
| …of those, pointing at another Manual page | **525** |
| …as a share of all links | **24%** |
| Cross-references resolved to a page or passage | **418** |
| …found as a hyperlink (`href`) | **378** |
| …read out of the prose (`regex`, e.g. “see part 22.15.7”) | **40** |
| Distinct pages or passages pointed at | **222** |
| Passages carrying at least one cross-reference | **307** |

The Manual links to itself **525 times** — roughly once every 584 words, and about one link in four. Those anchors reduce to 378 cross-reference edges: the difference is anchors naming a Manual page that is not in the navigation tree, whose target cannot be established and is dropped rather than guessed, and anchors repeating a target the same passage already points at, since a cross-reference is stored once per target. A further 40 edges have no hyperlink at all and were read out of the prose.

**280 of 418 cross-references leave their own Part**; 138 stay inside it, and 17 point somewhere else on the same page.

**The Parts that point outward most, and the ones pointed at**

| Part | References out | Part | References in |
|---|---|---|---|
| Part 60 The Madrid Protocol | 58 | Part 14 Classification of Goods and Services | 27 |
| Part 14 Classification of Goods and Services | 30 | Part 60 The Madrid Protocol | 25 |
| Part 22 Section 41 - Capable of Distinguishing | 19 | Part 22 Section 41 - Capable of Distinguishing | 22 |
| Part 27 Overcoming Grounds for Rejection under Section 44 | 17 | Part 19A Use of a Trade Mark | 18 |
| Part 32A Examination of Trade Marks for Plants (in Class 31) | 17 | Part 26 Section 44 and Regulation 4.15A - Conflict with Other Signs | 18 |
| Part 43 Assignment and Transmission | 14 | Part 21 Non-traditional Signs | 17 |

**321 of the Manual's 500 pages are never linked to from anywhere else in the Manual.** They are reachable only through the navigation tree — which is also the only reliable source of which Part a page belongs to.

**The most cross-referenced destinations**

| Target | Times referenced | Title |
|---|---|---|
| `TMM/Part49/1` | 8 | Part 49.1 Application for removal or cessation of protection |
| `TMM/Part51/1` | 8 | Part 51.1. Evidence |
| `TMM/Part43/1` | 7 | 43.1. What is assignment and transmission? |
| `TMM/Part52/1` | 7 | Part 52.1. What is a decision? |
| `TMM/Part14/5` | 6 | 14.5. Principles of classification and finding the correct c |
| `TMM/Part4/1` | 6 | Part 4.1. Fees - general |
| `TMM/Part44/1` | 6 | Part 44.1. Background |
| `TMM/Part47/1` | 6 | Part 47.1. Filing a notice of opposition |


## 4. Where the Manual points outward

|  |  |
|---|---|
| Distinct hosts linked to | **24** |
| Links to AustLII | **966** |
| Links to the Federal Register of Legislation | **475** |
| Links to TimeBase | **101** |
| Distinct URLs | **765** |
| Anchors with no words at all | **5** |

| Host | Links |
|---|---|
| austlii.edu.au | 583 |
| www.legislation.gov.au | 470 |
| www.austlii.edu.au | 346 |
| www.timebase.com.au | 99 |
| www.wipo.int | 86 |
| www8.austlii.edu.au | 36 |
| jade.io | 24 |
| www.ipaustralia.gov.au | 13 |
| www.pmc.gov.au | 5 |
| www.prod.legislation.gov.au | 5 |
| docstore.aipo.gov.au | 3 |
| tmgns.search.ipaustralia.gov.au | 3 |

**The Manual cites primary law through three different publishers.** AustLII carries the provision in the URL path, TimeBase in a query string, and the Federal Register names only the instrument — which is why 232 separate anchors resolve to one Register URL for the Act, and the citation layer deliberately does not read them as provision edges.

**The most-linked external URLs**

| Links | URL |
|---|---|
| 232 | `https://www.legislation.gov.au/C2004A04969/latest/versions` |
| 215 | `https://www.legislation.gov.au/F1996B00084/latest/versions` |
| 72 | `https://austlii.edu.au/cgi-bin/viewdb/au/legis/cth/consol_act/tma1995121/s44.html` |
| 51 | `https://austlii.edu.au/cgi-bin/viewdb/au/legis/cth/consol_act/tma1995121/s43.html` |
| 45 | `https://austlii.edu.au/cgi-bin/viewdb/au/legis/cth/consol_act/tma1995121/s41.html` |
| 27 | `https://austlii.edu.au/cgi-bin/viewdb/au/legis/cth/consol_act/tma1995121/s39.html` |
| 22 | `https://austlii.edu.au/cgi-bin/viewdb/au/legis/cth/consol_act/tma1995121/s42.html` |
| 21 | `http://www.austlii.edu.au/cgi-bin/viewdb/au/legis/cth/consol_reg/tmr1995230/s4.13.html` |

**The most-repeated anchor text**

| Times | Anchor |
|---|---|
| 188 | “Trade Marks Act 1995” |
| 115 | “Trade Mark Regulations 1995” |
| 74 | “Trade Marks Regulations 1995” |
| 32 | “Federal Register of Legislation - Trade Marks Act 1995” |
| 32 | “Federal Register of Legislation - Trade Marks Regulations 1995” |
| 32 | “section 43” |
| 31 | “section 41” |
| 16 | “Annex A1” |


## 5. How often the Manual cites the Act and the Regulations

|  |  |
|---|---|
| Provision citations | **2,717** |
| …hyperlinked by the Manual's authors (`href`) | **930** |
| …read out of the prose (`regex`) | **1,787** |
| Distinct provisions cited (to subsection level) | **963** |
| Distinct sections or regulations cited | **491** |
| Passages citing at least one provision | **909** |
| Pages citing at least one provision | **406** |

That is one statutory citation every 112 words, and 37% of the Manual's passages carry at least one.

| Instrument | Citations |
|---|---|
| `TMA1995` | 1,799 |
| `TMR1995` | 892 |
| `TMA1955` | 13 |
| `PBRA1994` | 9 |
| `AIA1901` | 2 |
| `DR2016` | 1 |
| `TMA1905` | 1 |

`TMA1995` is the Trade Marks Act 1995 and `TMR1995` the Regulations. The rest are the Manual reaching outside its own corpus: the repealed 1955 Act, the Plant Breeder's Rights Act, the Acts Interpretation Act, the 1905 Act, and the Designs Regulations.

| Evidence for the citation | Count | Share |
|---|---|---|
| Hyperlink — the authors said so | 930 | 34% |
| `explicit` — prose naming the instrument alongside | 60 | 2% |
| `default` — bare “section N”, assumed to be the Act | 1,608 | 59% |
| `ambiguous` — several instruments in scope, unresolved | 119 | 4% |

**59% of statutory citations rest on a convention** — the Manual writes “section 41” without naming an instrument, and the extractor reads a bare section number as the Trade Marks Act. The convention is recorded on every edge that relies on it, and the 119 places where another instrument is genuinely in scope are flagged `ambiguous` rather than resolved.

**The twenty most-cited provisions**

| Provision | Citations | Distinct passages |
|---|---|---|
| `TMA1995/s41` | 153 | 125 |
| `TMA1995/s44` | 135 | 107 |
| `TMA1995/s43` | 67 | 67 |
| `TMA1995/s42` | 61 | 55 |
| `TMA1995/s6` | 52 | 52 |
| `TMA1995/s224` | 46 | 37 |
| `TMA1995/s65` | 43 | 39 |
| `TMA1995/s39` | 40 | 33 |
| `TMA1995/s33` | 33 | 30 |
| `TMA1995/s92` | 26 | 21 |
| `TMA1995/s27` | 24 | 22 |
| `TMA1995/s8` | 23 | 16 |
| `TMR1995/r4.13` | 23 | 13 |
| `TMR1995/r4.15A` | 23 | 15 |
| `TMA1995/s51` | 22 | 14 |
| `TMR1995/r4.4` | 22 | 16 |
| `TMA1995/s15` | 19 | 12 |
| `TMA1995/s17` | 19 | 18 |
| `TMA1995/s7` | 19 | 19 |
| `TMA1995/s65A` | 18 | 18 |

**The Parts that cite the law hardest**

| Part | Provision citations | Words | Citations per 1,000 words |
|---|---|---|---|
| Part 51 General Opposition Proceedings | 150 | 8,054 | 18.6 |
| Part 60 The Madrid Protocol | 145 | 19,211 | 7.5 |
| Part 47 Procedures for Opposing Registration or Protection | 135 | 6,882 | 19.6 |
| Part 35 Certification Trade Marks | 117 | 4,353 | 26.9 |
| Part 52 Hearings, Decisions, Reasons and Appeals | 104 | 5,689 | 18.3 |
| Part 49 Non-use Procedures | 99 | 3,984 | 24.8 |
| Part 22 Section 41 - Capable of Distinguishing | 96 | 24,277 | 4.0 |
| Part 30 Signs that are Scandalous and Use Contrary to Law | 96 | 9,593 | 10.0 |


## 6. How much case law the Manual carries

|  |  |
|---|---|
| Case citations | **519** |
| Distinct decisions | **411** |
| Passages citing a decision | **221** |
| Pages citing a decision | **83** |
| Earliest decision cited | **1894** |
| Most recent decision cited | **2026** |

**Case law is concentrated.** Only 17% of pages cite a decision at all, and 9% of passages. The Manual is a procedures document that reaches for authority in a few places, not a case book.

| Court or report series | Citations |
|---|---|
| FCA | 144 |
| ATMO | 117 |
| RPC | 65 |
| IPR | 44 |
| FCAFC | 43 |
| HCA | 41 |
| CLR | 29 |
| AOJP | 12 |
| ALR | 5 |
| FCR | 5 |
| APO | 3 |
| AIPC | 2 |

| Decade | Citations |
|---|---|
| 1890s | 4 |
| 1900s | 2 |
| 1910s | 4 |
| 1920s | 9 |
| 1930s | 14 |
| 1940s | 21 |
| 1950s | 23 |
| 1960s | 31 |
| 1970s | 20 |
| 1980s | 38 |
| 1990s | 76 |
| 2000s | 111 |
| 2010s | 117 |
| 2020s | 49 |

**68% of the Manual's case citations are to decisions from 1990 onwards**, but it still reaches back to 1894.

**The most-cited decisions**

| Citation | Times cited | Pages |
|---|---|---|
| `[1999] FCA 1020` | 8 | 7 |
| `[2017] FCAFC 174` | 5 | 4 |
| `[1954] HCA 82` | 4 | 3 |
| `[2000] FCA 1335` | 4 | 4 |
| `[2001] FCA 261` | 4 | 3 |
| `[2002] FCA 1551` | 4 | 4 |
| `[2010] FCA 664` | 4 | 4 |
| `[2021] FCAFC 31` | 4 | 4 |
| `[2023] FCAFC 44` | 4 | 4 |
| `(1949) 66 RPC 110` | 3 | 3 |

**Where the case law is**

| Part | Case citations |
|---|---|
| Part 26 Section 44 and Regulation 4.15A - Conflict with Other Signs | 110 |
| Part 22 Section 41 - Capable of Distinguishing | 86 |
| Part 19A Use of a Trade Mark | 79 |
| Part 29 Section 43 - Trade Marks likely to Deceive or Cause Confusion | 42 |
| Part 28 Honest Concurrent Use, Prior Use or Other Circumstances | 27 |
| Part 46 Grounds for Opposition to Registration or Protection | 27 |
| Part 55 Costs | 22 |
| Part 23 Overcoming Grounds for Rejection under Section 41 - including Evidence of Use | 21 |


## 7. What the Manual says about its own changes

|  |  |
|---|---|
| Amendment rows the Manual publishes | **2,039** |
| Pages amended more than once | **493 of 500** |
| Most amendments on one page | **13 (`TMM/Part19A/2`)** |
| Distinct reasons given | **273** |
| Earliest amendment recorded | **2021-01-29** |
| Most recent | **2026-07-27** |

| Year | Amendments |
|---|---|
| 2021 | 555 |
| 2022 | 784 |
| 2023 | 80 |
| 2024 | 161 |
| 2025 | 346 |
| 2026 | 113 |

**The reasons IP Australia gives**

| Times | Reason |
|---|---|
| 741 | Update hyperlinks |
| 467 | (no reason recorded) |
| 128 | Page renamed. Links updated. |
| 50 | Hyperlinks updated |
| 45 | Terminology updated to reflect legislative changes. |
| 43 | Accessibility fix – alternative text for images |
| 37 | Part reviewed: Minor content updates, links to legislation updated, minor typo |
| 31 | Content updated. |
| 20 | Minor update. |
| 20 | Turn off publish date, add Act/Reg links. |
| 15 | Updated to reflect new legislation - Administrative Review Tribunal Act 2024:  |
| 12 | Links to legislation added. Content reviewed - minor updates. |

**1,077 of 2,039 recorded amendments (53%) mention links or hyperlinks** — the Manual spends much of its published change history maintaining its own citations. A further 467 rows give no reason at all.


## 8. Typography, and what it is doing

|  |  |
|---|---|
| Emphasised spans | **5,146** |
| Italic (`i` + `em`) | **2,761** |
| Bold (`strong` + `b`) | **1,827** |
| Underlined (`u`) | **532** |
| Superscript (`sup`, footnote markers) | **26** |

The Manual writes the same weight two ways and the snapshot does not normalise it: `i` appears 2,631 times against `em` 130, and `strong` 1,808 times against `b` 19. That is a fact about the markup, and there is nowhere in the record to put the claim that the two mean the same thing.

| Times emphasised | Text |
|---|---|
| 660 | “Trade Marks Act 1995” |
| 342 | “Trade Mark Regulations 1995” |
| 289 | “Trade Marks Regulations 1995” |
| 50 | “Note:” |
| 43 | “Madrid Protocol” |
| 43 | “Madrid Protocol Regulations” |
| 42 | “not” |
| 27 | “Note” |
| 26 | “PLEASE NOTE:” |
| 25 | “v” |

Italics are how the Manual names things: instrument titles and the party names of decisions. It is the italic run beside a citation, not a hyperlink, that supplies most of the case names in `exports/cases.csv`.


## 9. The join to the legislation snapshot

|  |  |
|---|---|
| Provisions in the legislation snapshot | **763** |
| Addressable refs (provisions and their units) | **6,576** |
| Manual citations to `TMA1995` or `TMR1995` | **2,691** |
| …that resolve to a provision the snapshot holds | **2,615 (97.2%)** |
| …that do not | **76** |

**The two halves of this repository join without a lookup table.** A Manual passage citing section 41 carries `provisions[].id == "TMA1995/s41"`, and that is the ref of a provision record in the legislation snapshot.

- **Trade Marks Act 1995**: the compilation carries 315 sections. The Manual cites 219 of them (70%) and never mentions the other 96. A further 20 numbers it cites have no counterpart anywhere in the current compilation.
- **Trade Marks Regulations 1995**: the compilation carries 401 regulations. The Manual cites 226 of them (56%) and never mentions the other 175. A further 4 numbers it cites have no counterpart anywhere in the current compilation.

Those last numbers are worth reading carefully. They are not all errors: some are provisions repealed since the passage was written, some are references to another Act that the `default` convention reads as the Trade Marks Act. Some are neither — `TMA1995/s5T` comes from the words “Beethoven's 5th Symphony”.


## 10. Vocabulary

| Word | Occurrences |
|---|---|
| trade | 5,346 |
| mark | 3,869 |
| class | 3,557 |
| goods | 1,944 |
| application | 1,911 |
| services | 1,844 |
| marks | 1,730 |
| use | 1,550 |
| section | 1,324 |
| registration | 1,034 |
| act | 1,006 |
| registrar | 987 |
| applicant | 980 |
| any | 785 |
| part | 755 |
| australia | 654 |
| suggested | 646 |
| made | 635 |
| alternatives | 630 |
| name | 603 |

Stopwords are excluded — the list is in `build_stats.py` and is a judgement, not a fact about the corpus. `class`, `suggested` and `alternatives` are inflated by one page: Part 14's Annex A13, a 18,166-word list of terms too broad for classification, which is 6% of the whole Manual by itself.

**Phrases**

| Phrase | Occurrences |
|---|---|
| “trade mark” | 3,526 |
| “trade marks” | 1,564 |
| “the registrar” | 957 |
| “goods and/or services” | 311 |
| “the applicant” | 930 |
| “capable of distinguishing” | 174 |
| “evidence of use” | 80 |
| “deceptively similar” | 80 |
| “substantially identical” | 48 |
| “honest concurrent use” | 36 |
| “prima facie” | 97 |
| “madrid protocol” | 109 |
| “hearing officer” | 45 |


## 11. Quirks the snapshot records rather than fixes

- **2 pages print a number that is not their address.** `TMM/Part20/3` prints “Part 20.2. Definition of sign” while `TMM/Part20/2` prints “20.2. Background to definition of a trade mark”, so two pages claim 20.2. The nav decides the address and the record says the page disagrees.
- **2 pages are in the navigation tree but return 404.** They are listed in `snapshot/manifest.json`, not silently dropped.
- **119 provision citations are flagged `ambiguous`** — several instruments are genuinely in scope and nothing in the source chooses between them, so the record carries the ambiguity instead of resolving it. No cross-reference is (0 of 418).
- **5 anchors contain no words at all** — an `<a>` wrapped around nothing. They are kept, with `start == end`, because the point in the text where the Manual put a link is a fact about the passage even when the link has no words to show for it.
- **91 anchors repeat words another anchor in the same passage already used**, which is why links carry character offsets instead of being matched by their text.
- **The Manual mis-sets its own citations.** `(1904) 21 ROC 617` is a mistyped `RPC`, and it is exported as written: correcting it would put a decision in the data that the Manual does not cite.

---

_Generated by `exports/build_stats.py` from `snapshot/` at extractor `ingest/0.11.0`._
