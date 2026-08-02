"""Export the Manual's case citations as a flat CSV.

Reads `snapshot/pages/` and writes `exports/cases.csv`: one row per citation
position — 519 of them, carrying the 411 distinct decisions the Manual cites.

Not part of the pipeline. Same standing as `viz/`: it reads the snapshot and
nothing in the snapshot exists for its benefit. No field here is new
information — every column is either copied from a chunk record or derived
from one by parsing, so the CSV is a pure function of `snapshot/pages/` and
re-running this on an unchanged snapshot gives byte-identical output.

Written for one job: joining the corpus to an external register of decisions.
The join key is `citation` (or `case_id`, which is the same fact addressed).

    python exports/build_cases.py

Rule 1 applies here as it does everywhere else. Where the Manual's own
citation is malformed — `(1904) 21 ROC 617`, which is a mis-set `RPC` — it is
exported as written. Correcting it here would put a decision in the CSV that
the Manual does not cite.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent.parent
PAGES = ROOT / "snapshot" / "pages"
OUT = Path(__file__).resolve().parent / "cases.csv"

#: Characters of surrounding prose kept either side of the citation, so a
#: reviewer deciding whether two citation strings name one decision can do it
#: from the CSV instead of opening the Manual.
CONTEXT = 140

#: `[2018] FCAFC 109` — SCHEMA.md calls this the neutral style. The token is
#: usually a court and occasionally a report series cited the same way (`AC`),
#: which is why the column is named for both.
NEUTRAL = re.compile(r"^\[(\d{4})\]\s+([A-Za-z]+)\s+(\d+)$")

#: `(1963) 109 CLR 407` — the reported style: year, volume, series, first page.
REPORTED = re.compile(r"^\((\d{4})\)\s+(\d+)\s+([A-Za-z]+)\s+(\d+)$")

#: A citation printed immediately after another and separated only by `;` or
#: `,` is the same decision cited a second way — `[1963] HCA 66; (1963) 109
#: CLR 407`. 16 pairs in the corpus. Adjacency is the drafter's own convention
#: for a parallel citation and reading it is a traversal, not an inference,
#: but it is still *evidence* of an alias rather than an assertion of one: the
#: CSV records the neighbour and leaves the merge to a human. The third
#: alternative matches the volume-series-page form with the year left off,
#: which is how a parallel citation is usually written once the year is
#: already stated by the citation in front of it.
ADJACENT = re.compile(
    r"(?P<first>\[\d{4}\]\s+[A-Za-z]+\s+\d+|\(\d{4}\)\s+\d+\s+[A-Za-z]+\s+\d+)"
    r"\s*[;,]\s*"
    r"(?P<second>\[\d{4}\]\s+[A-Za-z]+\s+\d+"
    r"|\(\d{4}\)\s+\d+\s+[A-Za-z]+\s+\d+"
    r"|\d+\s+[A-Za-z]+\s+\d+)"
)

FIELDS = [
    "case_id",
    "citation",
    "citation_style",
    "year",
    "court_or_series",
    "number",
    "volume",
    "first_page",
    "corpus_citation_count",
    "parties",
    "jade_href",
    "parallel_citation",
    "parallel_case_id",
    "chunk_ref",
    "page_ref",
    "part_id",
    "part_title",
    "page_title",
    "heading_path",
    "chunk_ordinal",
    "char_offset",
    "occurrences_in_chunk",
    "url",
    "context",
]


def parse_citation(case_id: str, citation: str) -> dict[str, str]:
    """Split a citation into its parts, from the string the Manual printed.

    The id carries the same fact — `CASE/1963/CLR/109/407` — but it is the
    citation that a register is keyed on, so the citation is what is parsed
    and the id is left as the opaque address it is meant to be.
    """
    match = NEUTRAL.match(citation)
    if match is not None:
        year, token, number = match.groups()
        return {
            "citation_style": "neutral",
            "year": year,
            "court_or_series": token,
            "number": number,
            "volume": "",
            "first_page": "",
        }

    match = REPORTED.match(citation)
    if match is not None:
        year, volume, token, page = match.groups()
        return {
            "citation_style": "reported",
            "year": year,
            "court_or_series": token,
            "number": "",
            "volume": volume,
            "first_page": page,
        }

    # Rule 3: a citation shape this does not recognise is a change in the
    # corpus, not something to paper over with empty columns.
    raise ValueError(f"unparsed citation {citation!r} on {case_id}")


def anchor_evidence(chunk: dict[str, Any], citation: str) -> tuple[str, str]:
    """Party names and a jade link, where the Manual hyperlinked the decision.

    Only from an anchor whose own words contain the citation — those are the
    Manual's authors naming the case, not our reading of the prose. 19 of the
    519 positions have one. Everything else gets empty strings, because
    SCHEMA.md is right that party names lifted out of running prose are not
    reliable, and a guess in a column meant for joining is worse than a blank.
    """
    for link in chunk["links"]:
        if citation not in link["text"]:
            continue
        # Everything before the citation, not everything except it: the words
        # after it are a parallel citation, not a party — `Qantas Airways
        # Limited v Edwards [2016] FCA 729; 338 ALR 134`. Party names precede
        # the citation in all 18 of these anchors.
        parties = link["text"].split(citation)[0].strip(" .,;:-")
        href = link["href"] if "jade.io" in link["href"].lower() else ""
        return parties, href
    return "", ""


def parallel(chunk: dict[str, Any], citation: str) -> tuple[str, str]:
    """The citation printed beside this one, and its id where it has one.

    Returns the neighbour as the Manual set it, plus its `case_id` when the
    neighbour is itself a case edge on this chunk — which is the useful pair,
    because it says two of this corpus's own decision ids are one decision.
    Where the neighbour is written without its year (`51 IPR 149`) there is no
    edge for it and the id is empty; the string is still worth carrying,
    because an external register can resolve it and this pipeline cannot.
    """
    ids = {case["citation"]: case["id"] for case in chunk["cases"]}

    for match in ADJACENT.finditer(chunk["text"]):
        first, second = match.group("first"), match.group("second")
        if first == citation:
            return second, ids.get(second, "")
        if second == citation:
            return first, ids.get(first, "")
    return "", ""


def rows() -> Iterator[dict[str, str]]:
    """Every (decision, chunk) pair in the corpus, unsorted."""
    counts: Counter[str] = Counter()
    found: list[dict[str, str]] = []

    for path in sorted(PAGES.rglob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        page = record["page"]

        for chunk in record["chunks"]:
            for case in chunk["cases"]:
                citation = case["citation"]
                text = chunk["text"]
                offset = text.find(citation)
                if offset < 0:
                    # The edge was extracted from this text, so it is in it.
                    raise ValueError(
                        f"{citation!r} not in {chunk['chunk_ref']}"
                    )

                counts[case["id"]] += 1
                parties, jade = anchor_evidence(chunk, citation)
                neighbour, neighbour_id = parallel(chunk, citation)
                start = max(0, offset - CONTEXT)
                end = min(len(text), offset + len(citation) + CONTEXT)

                found.append(
                    {
                        "case_id": case["id"],
                        "citation": citation,
                        **parse_citation(case["id"], citation),
                        "parties": parties,
                        "jade_href": jade,
                        "parallel_citation": neighbour,
                        "parallel_case_id": neighbour_id,
                        "chunk_ref": chunk["chunk_ref"],
                        "page_ref": chunk["page_ref"],
                        "part_id": page["part_id"],
                        "part_title": chunk["heading_path"][0],
                        "page_title": page["h1"] or page["nav_title"],
                        "heading_path": " > ".join(chunk["heading_path"]),
                        "chunk_ordinal": str(chunk["ordinal"]),
                        "char_offset": str(offset),
                        "occurrences_in_chunk": str(text.count(citation)),
                        "url": page["url"],
                        "context": text[start:end],
                    }
                )

    for row in found:
        row["corpus_citation_count"] = str(counts[row["case_id"]])
        yield row


def sort_key(row: dict[str, str]) -> tuple[Any, ...]:
    """Stable order: decision, then where it is cited.

    By year and citation rather than by `case_id`, so the file reads
    chronologically and a decision's positions sit together. `chunk_ref` is
    the tiebreak and is unique within a decision.
    """
    return (int(row["year"]), row["citation"], row["chunk_ref"])


def main() -> None:
    ordered = sorted(rows(), key=sort_key)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(ordered)

    decisions = len({row["case_id"] for row in ordered})
    named = sum(1 for row in ordered if row["parties"])
    print(
        f"{OUT.relative_to(ROOT)}: {len(ordered)} citation positions, "
        f"{decisions} distinct decisions, {named} with party names"
    )


if __name__ == "__main__":
    main()
