# Manual snapshot: 2 pages amended, 3 added, 2 retired, 1 restored

Crawled `2026-07-27T18:03:07Z`. 8 pages in the inventory. 3 Parts. 6 page files written. extractor `ingest/0.1.0`.

## Structure

**Read this before the amendments.** The Manual is overhauled Part by Part, not only edited (SOURCE_NOTES.md §10), so a Part's page count moving usually means pages were renamed, split, merged or renumbered.

- **New Part 32B** — Examination of Trade Marks for Wines (in Class 33) (1 page)
- **Part 22: 4 → 5 pages** — Section 41 - Capable of Distinguishing
- Part 5 renamed: Fees → Fees and Payments

Same URL, new address — the page did not go anywhere, its number did. Citations to the old ref will not resolve:

- `TMM/Part5/2` → `TMM/Part5/3` ([source](https://manuals.ipaustralia.gov.au/trademark/2.-payment-of-fees))

## Pages amended (2)

| Page | Paragraphs | Amended | IP Australia's reason |
|---|---|---|---|
| **Part 22.1** ([source](https://manuals.ipaustralia.gov.au/trademark/1.-registrability-under-section-41)) | 2 of 3 (+1 new, -1 gone) | 2026-07-20 | Amended following the Raising the Bar review. |
| **Part 22.2** ([source](https://manuals.ipaustralia.gov.au/trademark/2.-capable-of-distinguishing)) | 0 of 2 | 2026-07-20 | Update hyperlinks |

`0 of N` is not a mistake: a chunk hash covers the text, and *Update hyperlinks* — one of the Manual's own reasons — moves the markup around it without changing a word.

## Pages added (3)

- **Part 5.3** — 3. Payment of fees ([source](https://manuals.ipaustralia.gov.au/trademark/2.-payment-of-fees))
- **Part 22.4** — 4. Evidence of use ([source](https://manuals.ipaustralia.gov.au/trademark/4.-evidence-of-use))
- **Part 32B.2.3** — Part 32B.2.3 Section 41: Capacity to Distinguish ([source](https://manuals.ipaustralia.gov.au/trademark/2.3-section-41--capacity-to-distinguish1))

## Pages retired (2)

Gone from the nav, not deleted: the record moves to `pages/_retired/` so old citations still resolve, and its raw HTML stays where it is (ARCHITECTURE.md §Retirement).

- **Part 5.2** — 2. Payment of fees ([source](https://manuals.ipaustralia.gov.au/trademark/2.-payment-of-fees))
- **Part 22.3** — 3. Withdrawn guidance ([source](https://manuals.ipaustralia.gov.au/trademark/3.-withdrawn-guidance))

## Pages restored (1)

Retired in an earlier run, back in the nav now.

- **Part 22.5** — 5. Divisional applications ([source](https://manuals.ipaustralia.gov.au/trademark/5.-divisional-applications))

## Changed around the text (1)

The body is byte-identical; the record around it is not. A Part renamed in the nav does this, and it is why the skip gate compares every field and not just the hash (ARCHITECTURE.md §Skip logic).

- **Part 5.1** — `nav_title`: 1. Fees - general → 1. Fees and charges - general

## Unreachable (1)

The nav links these; the site would not serve them. No record was written and any record already held is untouched — this is not retirement, which means gone from the nav (SOURCE_NOTES.md §14).

- `TMM/Part1/3` — https://manuals.ipaustralia.gov.au/trademark/1.5 returned 404

1 page unchanged.

---

Never auto-merged. The human read is the audit trail.
