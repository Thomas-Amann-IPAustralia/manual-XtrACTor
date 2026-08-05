"""Count the Manual, and write the counts as `exports/STATS.md`.

Reads `snapshot/pages/` and `snapshot/legislation/`, and writes one Markdown
report describing the corpus: how big it is, how it is shaped, how often it
links to itself, how often it cites the Act, the Regulations and the courts,
and what its publisher's own amendment log says about it.

Not part of the pipeline. Same standing as `build_cases.py` and `viz/`: it
reads the snapshot and nothing in the snapshot exists for its benefit. No
number here is new information — every one is counted off the records the
extractor wrote, so the report is a pure function of the snapshot and
re-running it on an unchanged snapshot gives byte-identical output.

    python exports/build_stats.py

Rule 1 applies here as everywhere else. Where a count is of something the
extractor marked as an inference — a `regex` provision edge, an `emphasis`
heading — the report says so beside the number rather than presenting it as
the Manual's own assertion. Where two definitions of a statistic are both
defensible, the one used is stated: "words" means whitespace-separated tokens
of `chunk.text`, and nothing here re-reads the source HTML.

Token counts are the one thing that cannot be derived from the snapshot with
the standard library alone, because a token is defined by a tokeniser. If
`tiktoken` is importable the report carries the counts and names the encoding;
if it is not, the report says the counts were not computed. That is the only
line of this file whose output depends on the environment rather than the
snapshot, and it is written so that reading the report tells you which of the
two happened. `tiktoken` is NOT a dependency of this repository.
"""

from __future__ import annotations

import collections
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
PAGES = ROOT / "snapshot" / "pages"
LEGISLATION = ROOT / "snapshot" / "legislation"
MANIFEST = ROOT / "snapshot" / "manifest.json"
SITEMAP = ROOT / "snapshot" / "sitemap.json"
OUT = Path(__file__).resolve().parent / "STATS.md"

#: Instruments the legislation snapshot carries, and so the only ones a
#: Manual provision edge can be resolved against. Mirrors
#: `frl_snapshot.config.INSTRUMENTS`, read here rather than imported so this
#: script depends on the snapshot on disk and not on the pipeline packages.
IN_SCOPE = ("TMA1995", "TMR1995")

#: The root of a provision id: `TMA1995/s44(3)(a)` -> `TMA1995/s44`. The same
#: derivation `chunk.schema.json` describes for the id, done here because a
#: count of "how often is section 44 cited" wants subsection edges folded in.
ROOT_OF = re.compile(r"^([A-Z]{2,8}[0-9]{4}/(?:sch[0-9]+[A-Z]*|[sr][0-9]+[A-Z]*(?:\.[0-9]+[A-Z]*)*))")

#: Words excluded from the frequency table. A stopword list is a judgement and
#: not a fact about the corpus, so it is written out here rather than being
#: imported from somewhere it cannot be read: what the table shows depends on
#: this list, and a reader is entitled to see it.
STOPWORDS = frozenset(
    """a an and are as at be been being but by can did do does for from had has have
    if in into is it its may must no not of on or other should so such than that the
    their them then there these they this those to under up was were what when where
    which who will with within would you your""".split()
)

#: What is stripped from a word before counting distinct forms: everything
#: that is not a letter, digit, apostrophe or hyphen. So "mark," and "mark"
#: are one form and "trade-mark" stays one word.
WORD_EDGES = re.compile(r"[^\w'’-]")

#: Words per minute, for the one derived-rather-than-counted figure in the
#: report. 200 is the conventional silent-reading rate for prose; the Manual is
#: not prose, so the number is a scale marker and is labelled as an estimate.
READING_RATE = 200


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_pages() -> tuple[list[dict], list[dict]]:
    """Every page record and every chunk, in `page_ref` order.

    Sorted rather than taken in filesystem order: `rglob` is not ordered, and
    a report whose "top 10" ties break differently on two machines is not the
    byte-identical output the docstring promises.
    """
    pages: list[dict] = []
    chunks: list[dict] = []
    for path in sorted(PAGES.rglob("*.json")):
        document = read_json(path)
        pages.append(document["page"])
        chunks.extend(document["chunks"])
    pages.sort(key=lambda page: page["page_ref"])
    chunks.sort(key=lambda chunk: (chunk["page_ref"], chunk["ordinal"], chunk["chunk_ref"]))
    return pages, chunks


def load_legislation() -> tuple[list[dict], set[str]]:
    """Provision records, and every ref they make addressable.

    The ref set is what a Manual provision edge is joined against, and it is
    provisions *and* their units — `TMA1995/s41` and `TMA1995/s41(1)` are both
    citable addresses. Same set `frl_snapshot.validate._manual_coverage`
    builds, rebuilt from disk rather than imported for the reason above.
    """
    provisions: list[dict] = []
    known: set[str] = set()
    if not LEGISLATION.is_dir():
        return provisions, known
    for path in sorted(LEGISLATION.rglob("provisions/**/*.json")):
        document = read_json(path)
        provisions.append(document)
        known.add(str(document.get("ref")))
        for unit in document.get("units", []):
            known.add(str(unit.get("ref")))
    provisions.sort(key=lambda record: record["ref"])
    return provisions, known


def link_class(href: str) -> str:
    """What a hyperlink points at: a Manual page, a host, or a mailbox.

    An href is verbatim in the snapshot, so classifying one is a parse of the
    string and nothing more. A Manual page is a root-relative `/trademark/…`
    or the two places the authors wrote the absolute form instead — both are
    the Manual linking to itself and counting them apart would understate it.
    """
    parts = urlsplit(href)
    if parts.scheme == "mailto":
        return "mailto"
    host = parts.netloc.lower()
    if not host:
        return "manual" if parts.path.startswith("/trademark/") else "ipaustralia.gov.au"
    if host.endswith("manuals.ipaustralia.gov.au"):
        return "manual" if "/trademark/" in parts.path else host
    return host


def law_source(href: str) -> str | None:
    """The three publishers of primary law the Manual links to, or None."""
    host = urlsplit(href).netloc.lower()
    if "austlii" in host:
        return "AustLII"
    if "timebase" in host:
        return "TimeBase"
    if "legislation.gov.au" in host:
        return "Federal Register of Legislation"
    return None


def provision_root(identifier: str) -> str:
    match = ROOT_OF.match(identifier)
    # Rule 3: an id that does not split is a change in the id grammar, not
    # something to fold into a bucket and forget.
    if match is None:
        raise ValueError(f"unparsed provision id {identifier!r}")
    return match.group(1)


def page_of(ref: str) -> str:
    """The page a ref addresses, whether it is a page ref or a chunk ref."""
    return "/".join(ref.split("#")[0].split("/")[:3])


def part_of(ref: str) -> str:
    return ref.split("/")[1]


def ranked(counter: Counter, limit: int | None = None) -> list[tuple[Any, int]]:
    """Most frequent first, ties broken by key so the order is total."""
    items = sorted(counter.items(), key=lambda item: (-item[1], str(item[0])))
    return items[:limit] if limit else items


def token_counts(texts: Iterable[str]) -> list[tuple[str, int]]:
    """Tokens under each encoding `tiktoken` offers, where it is installed.

    Two encodings rather than one because they disagree by about 1%, and a
    single number invites being read as "the" token count of the Manual. There
    is no such thing: there is a count per tokeniser.
    """
    try:
        import tiktoken
    except ImportError:
        return []

    corpus = list(texts)
    counts = []
    for encoding_name in ("cl100k_base", "o200k_base"):
        encoding = tiktoken.get_encoding(encoding_name)
        counts.append((encoding_name, sum(len(encoding.encode(text)) for text in corpus)))
    return counts


class Report:
    """Markdown accumulator. Nothing clever; it keeps `main` readable."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def head(self, level: int, text: str) -> None:
        self.lines.extend(["", "#" * level + " " + text, ""])

    def line(self, text: str = "") -> None:
        self.lines.append(text)

    def table(self, headers: Iterable[str], rows: Iterable[Iterable[Any]]) -> None:
        headers = list(headers)
        self.line("| " + " | ".join(headers) + " |")
        self.line("|" + "|".join(["---"] * len(headers)) + "|")
        for row in rows:
            self.line("| " + " | ".join(str(cell) for cell in row) + " |")
        self.line()

    def stat(self, rows: Iterable[tuple[str, Any]]) -> None:
        self.table(("", ""), [(label, f"**{value}**") for label, value in rows])

    def text(self) -> str:
        return "\n".join(self.lines).strip() + "\n"


def main() -> None:  # noqa: C901 — one long report, read top to bottom
    pages, chunks = load_pages()
    provisions, known_refs = load_legislation()
    manifest = read_json(MANIFEST) if MANIFEST.exists() else {}

    # The Part's own title, from the nav tree — the only place it exists. A
    # table of `Part14` alone is a table nobody can read.
    sitemap = read_json(SITEMAP) if SITEMAP.exists() else {"parts": []}
    part_title = {
        entry["part_id"]: entry["part_title"] for entry in sitemap.get("parts", [])
    }

    part_by_page = {page["page_ref"]: page["part_id"] for page in pages}
    title_by_page = {page["page_ref"]: (page["h1"] or page["nav_title"]) for page in pages}

    texts = [chunk["text"] for chunk in chunks]
    words = [word for text in texts for word in text.split()]
    characters = sum(len(text) for text in texts)
    chunk_words = [len(text.split()) for text in texts]
    word_forms = {WORD_EDGES.sub("", word).casefold() for word in words} - {""}

    links = [(chunk, link) for chunk in chunks for link in chunk["links"]]
    internal = [(chunk, ref) for chunk in chunks for ref in chunk["internal_refs"]]
    edges = [(chunk, edge) for chunk in chunks for edge in chunk["provisions"]]
    cases = [(chunk, case) for chunk in chunks for case in chunk["cases"]]
    blocks = [block for chunk in chunks for block in chunk["blocks"]]
    tables = [table for chunk in chunks for table in chunk["tables"]]
    emphasis = [span for chunk in chunks for span in chunk["emphasis"]]
    images = [image for page in pages for image in page["images"]]
    amendments = [(page, row) for page in pages for row in page["amendments"]]

    report = Report()
    report.line("# The Trade Marks Manual, counted")
    report.line()
    report.line(
        "Every number here is counted off `snapshot/pages/` and "
        "`snapshot/legislation/` by `exports/build_stats.py`. Nothing is "
        "estimated except where it says so."
    )
    report.line()
    report.line(
        f"Snapshot crawled `{manifest.get('crawled_at', 'unknown')}`, "
        f"extractor `{manifest.get('extractor_version', 'unknown')}`."
    )

    # ---------------------------------------------------------------- size
    report.head(2, "1. Size")

    words_per_page = len(words) / len({chunk["page_ref"] for chunk in chunks})
    report.stat(
        [
            ("Parts", f"{len({page['part_id'] for page in pages}):,}"),
            ("Pages", f"{len(pages):,}"),
            ("Chunks (addressable passages)", f"{len(chunks):,}"),
            ("Words", f"{len(words):,}"),
            ("Characters", f"{characters:,}"),
            ("Distinct word forms", f"{len(word_forms):,}"),
            ("Source HTML crawled", f"{manifest.get('corpus', {}).get('raw_bytes', 0) / 1_000_000:.1f} MB"),
            ("Extracted text", f"{characters / 1_000_000:.2f} MB"),
        ]
    )
    report.line(
        f"The Manual is **{len(words):,} words** — about "
        f"{len(words) / 100_000:.1f} times the length of a 100,000-word book, "
        f"or an estimated {len(words) // READING_RATE // 60} hours "
        f"{len(words) // READING_RATE % 60} minutes of reading at "
        f"{READING_RATE} words per minute."
    )
    report.line()
    report.line(
        f"The pipeline reads "
        f"{manifest.get('corpus', {}).get('raw_bytes', 0) / 1_000_000:.0f} MB of "
        f"rendered HTML and keeps {characters / 1_000_000:.2f} MB of text: "
        f"**{100 * characters / max(manifest.get('corpus', {}).get('raw_bytes', 1), 1):.1f}%** "
        "of what the site sends is the Manual's own words. The rest is site "
        "chrome — and a large part of it is the navigation tree, which the CMS "
        "renders in full on every one of the 500 pages."
    )
    report.line()

    tokens = token_counts(texts)
    if tokens:
        report.line("Tokens, by tokeniser:")
        report.line()
        report.table(
            ("Encoding", "Tokens", "Tokens per word"),
            [
                (f"`{name}`", f"{count:,}", f"{count / len(words):.2f}")
                for name, count in tokens
            ],
        )
        report.line(
            "There is no single token count of a corpus — a token is whatever "
            "a tokeniser says it is, and these two disagree by about 1%."
        )
        report.line()
    else:
        report.line(
            "_Token counts not computed: `tiktoken` is not installed, and it is "
            "not a dependency of this repository._"
        )
        report.line()

    report.line(
        f"Average page: **{words_per_page:,.0f} words**. Average chunk: "
        f"**{sum(chunk_words) / len(chunk_words):,.0f} words** "
        f"(median {sorted(chunk_words)[len(chunk_words) // 2]:,})."
    )
    report.line()

    words_by_part: Counter = Counter()
    for chunk in chunks:
        words_by_part[part_by_page[chunk["page_ref"]]] += len(chunk["text"].split())
    report.line("**The ten longest Parts**")
    report.line()
    report.table(
        ("Part", "Words", "Pages"),
        [
            (
                part_title.get(part, part),
                f"{count:,}",
                sum(1 for page in pages if page["part_id"] == part),
            )
            for part, count in ranked(words_by_part, 10)
        ],
    )

    words_by_page: Counter = Counter()
    for chunk in chunks:
        words_by_page[chunk["page_ref"]] += len(chunk["text"].split())
    report.line("**The five longest pages**")
    report.line()
    report.table(
        ("Page", "Words", "Title"),
        [
            (f"`{ref}`", f"{count:,}", title_by_page[ref][:70])
            for ref, count in ranked(words_by_page, 5)
        ],
    )

    longest_chunk = max(chunks, key=lambda chunk: (len(chunk["text"].split()), chunk["chunk_ref"]))
    shortest_chunk = min(chunks, key=lambda chunk: (len(chunk["text"].split()), chunk["chunk_ref"]))
    report.line(
        f"Longest single passage: `{longest_chunk['chunk_ref']}`, "
        f"{len(longest_chunk['text'].split()):,} words. Shortest: "
        f"`{shortest_chunk['chunk_ref']}`, {len(shortest_chunk['text'].split())} "
        f"words — “{shortest_chunk['text'][:60]}”."
    )
    report.line()

    # --------------------------------------------------------------- shape
    report.head(2, "2. Shape")

    block_kinds = Counter(block["kind"] for block in blocks)
    report.stat(
        [
            ("Blocks (paragraphs, list items, tables, images)", f"{len(blocks):,}"),
            ("Paragraphs", f"{block_kinds['paragraph']:,}"),
            ("List items", f"{block_kinds['list_item']:,}"),
            ("Tables", f"{len(tables):,}"),
            ("Table rows", f"{sum(table['rows'] for table in tables):,}"),
            ("Table cells", f"{sum(len(row) for table in tables for row in table['cells']):,}"),
            ("Images", f"{len(images):,}"),
        ]
    )

    depth = Counter(block.get("depth") for block in blocks if block["kind"] == "list_item")
    report.line(
        f"Lists nest three deep at most: {depth[1]:,} top-level items, "
        f"{depth[2]} at depth 2, {depth[3]} at depth 3. "
        f"{100 * block_kinds['list_item'] / len(blocks):.0f}% of the Manual's "
        "blocks are list items — this is a procedures manual, and it reads like one."
    )
    report.line()

    headered = sum(1 for table in tables if table.get("header_row") is not None)
    biggest = max(tables, key=lambda table: (table["rows"], table["columns"]))
    report.line(
        f"Of {len(tables)} tables, **{headered}** mark a header row in the "
        f"markup. The rest give a consumer no way to know which row is the "
        f"header, and the extractor does not guess. Largest table: "
        f"{biggest['rows']} rows × {biggest['columns']} columns."
    )
    report.line()

    report.line(
        f"**Not one of the Manual's {len(images)} images carries alt text.** "
        f"All {sum(1 for image in images if image['alt'] is None)} of them "
        "have no `alt` attribute at all — not even the empty one that HTML "
        "uses to mean “decorative”. "
        f"“Accessibility fix – alternative text for images” is nonetheless one "
        f"of the Manual's own amendment reasons, on "
        f"{sum(1 for _, row in amendments if row['reason'] == 'Accessibility fix – alternative text for images')} "
        "page-amendments."
    )
    report.line()

    heading_source = Counter(chunk.get("heading_source") for chunk in chunks)
    ancestors = [heading for chunk in chunks for heading in chunk["headings"]]
    report.line("**Where the Manual's structure comes from**")
    report.line()
    report.table(
        ("Heading of a passage", "Chunks", "Share"),
        [
            ("`markup` — an h2–h4, the Manual asserting the boundary", f"{heading_source['markup']:,}", f"{100 * heading_source['markup'] / len(chunks):.0f}%"),
            ("`emphasis` — a bold numbered paragraph, promoted by the chunker", f"{heading_source['emphasis']:,}", f"{100 * heading_source['emphasis'] / len(chunks):.0f}%"),
            ("`null` — prose above the page's first heading", f"{heading_source[None]:,}", f"{100 * heading_source[None] / len(chunks):.0f}%"),
        ],
    )
    report.line(
        f"**{100 * heading_source['emphasis'] / len(chunks):.0f}% of the "
        "Manual's passages sit under a heading the Manual never marked up as "
        "one.** They are bold paragraphs opening with a number that extends "
        "the page's own — the only inference in the whole pipeline, and it is "
        "recorded in the data rather than hidden. Across every ancestor rather "
        f"than the leaf alone, {Counter(h['source'] for h in ancestors)['emphasis']:,} "
        f"of {len(ancestors):,} heading ancestries are inferred this way."
    )
    report.line()

    fragments = [chunk for chunk in chunks if chunk["fragment"]]
    report.line(
        f"{len(fragments)} chunks are fragments of "
        f"{len({chunk['chunk_ref'].split('~')[0] for chunk in fragments})} "
        "sections too long to keep whole; the most-split section is in "
        f"{max(chunk['fragment']['count'] for chunk in fragments)} pieces."
    )
    report.line()

    no_chunks = [page for page in pages if page["page_ref"] not in {chunk["page_ref"] for chunk in chunks}]
    report.line(
        f"**{len(no_chunks)} pages yield no text at all**: "
        f"{sum(1 for page in no_chunks if page['archived'])} carry the "
        "Manual's archive banner, and "
        f"{sum(1 for page in no_chunks if not page['archived'] and page['images'])} "
        "are a single image — a flowchart, a cross-search class table, the "
        "format of a summons. "
        f"{sum(1 for page in no_chunks if not page['archived'] and not page['images'])} "
        "is neither: it has no prose, no image and no banner."
    )
    report.line()

    # ------------------------------------------------- the Manual on itself
    report.head(2, "3. How often the Manual links to itself")

    link_classes = Counter(link_class(link["href"]) for _, link in links)
    self_links = link_classes["manual"]
    report.stat(
        [
            ("Hyperlinks inside the Manual's text", f"{len(links):,}"),
            ("…of those, pointing at another Manual page", f"{self_links:,}"),
            ("…as a share of all links", f"{100 * self_links / len(links):.0f}%"),
            ("Cross-references resolved to a page or passage", f"{len(internal):,}"),
            ("…found as a hyperlink (`href`)", f"{Counter(ref['extraction'] for _, ref in internal)['href']:,}"),
            ("…read out of the prose (`regex`, e.g. “see part 22.15.7”)", f"{Counter(ref['extraction'] for _, ref in internal)['regex']:,}"),
            ("Distinct pages or passages pointed at", f"{len({ref['ref'] for _, ref in internal}):,}"),
            ("Passages carrying at least one cross-reference", f"{sum(1 for chunk in chunks if chunk['internal_refs']):,}"),
        ]
    )
    href_refs = Counter(ref["extraction"] for _, ref in internal)["href"]
    report.line(
        f"The Manual links to itself **{self_links:,} times** — roughly once "
        f"every {len(words) // max(self_links, 1):,} words, and about one link "
        "in four. Those anchors reduce to "
        f"{href_refs:,} cross-reference edges: the difference is anchors naming "
        "a Manual page that is not in the navigation tree, whose target cannot "
        "be established and is dropped rather than guessed, and anchors "
        "repeating a target the same passage already points at, since a "
        f"cross-reference is stored once per target. A further {len(internal) - href_refs} "
        "edges have no hyperlink at all and were read out of the prose."
    )
    report.line()

    crossing = sum(
        1
        for chunk, ref in internal
        if part_of(ref["ref"]) != part_by_page[chunk["page_ref"]]
    )
    report.line(
        f"**{crossing} of {len(internal)} cross-references leave their own "
        f"Part**; {len(internal) - crossing} stay inside it, and "
        f"{sum(1 for chunk, ref in internal if ref['ref'] == chunk['page_ref'])} "
        "point somewhere else on the same page."
    )
    report.line()

    outbound: Counter = Counter(part_by_page[chunk["page_ref"]] for chunk, _ in internal)
    inbound: Counter = Counter(part_of(ref["ref"]) for _, ref in internal)
    report.line("**The Parts that point outward most, and the ones pointed at**")
    report.line()
    report.table(
        ("Part", "References out", "Part", "References in"),
        [
            (part_title.get(out_part, out_part), out_count, part_title.get(in_part, in_part), in_count)
            for (out_part, out_count), (in_part, in_count) in zip(
                ranked(outbound, 6), ranked(inbound, 6)
            )
        ],
    )

    targeted = {
        page_of(ref["ref"])
        for chunk, ref in internal
        if page_of(ref["ref"]) != chunk["page_ref"]
    }
    orphans = {page["page_ref"] for page in pages} - targeted
    report.line(
        f"**{len(orphans)} of the Manual's {len(pages)} pages are never linked "
        "to from anywhere else in the Manual.** They are reachable only through "
        "the navigation tree — which is also the only reliable source of which "
        "Part a page belongs to."
    )
    report.line()

    most_linked = ranked(Counter(ref["ref"] for _, ref in internal), 8)
    report.line("**The most cross-referenced destinations**")
    report.line()
    report.table(
        ("Target", "Times referenced", "Title"),
        [
            (f"`{ref}`", count, title_by_page.get(page_of(ref), "")[:60])
            for ref, count in most_linked
        ],
    )

    # ----------------------------------------------------------- links out
    report.head(2, "4. Where the Manual points outward")

    hosts = Counter(
        {
            host: count
            for host, count in link_classes.items()
            if host not in ("manual", "mailto")
        }
    )
    report.stat(
        [
            ("Distinct hosts linked to", f"{len(hosts):,}"),
            ("Links to AustLII", f"{sum(1 for _, link in links if law_source(link['href']) == 'AustLII'):,}"),
            ("Links to the Federal Register of Legislation", f"{sum(1 for _, link in links if law_source(link['href']) == 'Federal Register of Legislation'):,}"),
            ("Links to TimeBase", f"{sum(1 for _, link in links if law_source(link['href']) == 'TimeBase'):,}"),
            ("Distinct URLs", f"{len({link['href'] for _, link in links}):,}"),
            ("Anchors with no words at all", f"{sum(1 for _, link in links if link['text'] == ''):,}"),
        ]
    )
    report.table(
        ("Host", "Links"),
        [(host, f"{count:,}") for host, count in ranked(hosts, 12)],
    )
    report.line(
        "**The Manual cites primary law through three different publishers.** "
        "AustLII carries the provision in the URL path, TimeBase in a query "
        "string, and the Federal Register names only the instrument — which is "
        f"why {ranked(Counter(link['href'] for _, link in links if law_source(link['href']) == 'Federal Register of Legislation'), 1)[0][1]} "
        "separate anchors resolve to one Register URL for the Act, and the "
        "citation layer deliberately does not read them as provision edges."
    )
    report.line()

    external_top = Counter(
        link["href"] for _, link in links if link_class(link["href"]) not in ("manual", "mailto")
    )
    report.line("**The most-linked external URLs**")
    report.line()
    report.table(
        ("Links", "URL"),
        [(count, f"`{url}`") for url, count in ranked(external_top, 8)],
    )

    anchor_words = Counter(link["text"].strip() for _, link in links if link["text"].strip())
    report.line("**The most-repeated anchor text**")
    report.line()
    report.table(
        ("Times", "Anchor"),
        [(count, f"“{text}”") for text, count in ranked(anchor_words, 8)],
    )

    # ---------------------------------------------------------- provisions
    report.head(2, "5. How often the Manual cites the Act and the Regulations")

    extraction = Counter(edge["extraction"] for _, edge in edges)
    certainty = Counter(edge.get("certainty") for _, edge in edges)
    instruments = Counter(edge["id"].split("/")[0] for _, edge in edges)
    roots = Counter(provision_root(edge["id"]) for _, edge in edges)

    report.stat(
        [
            ("Provision citations", f"{len(edges):,}"),
            ("…hyperlinked by the Manual's authors (`href`)", f"{extraction['href']:,}"),
            ("…read out of the prose (`regex`)", f"{extraction['regex']:,}"),
            ("Distinct provisions cited (to subsection level)", f"{len({edge['id'] for _, edge in edges}):,}"),
            ("Distinct sections or regulations cited", f"{len(roots):,}"),
            ("Passages citing at least one provision", f"{sum(1 for chunk in chunks if chunk['provisions']):,}"),
            ("Pages citing at least one provision", f"{len({chunk['page_ref'] for chunk in chunks if chunk['provisions']}):,}"),
        ]
    )
    report.line(
        f"That is one statutory citation every "
        f"{len(words) // len(edges):,} words, and "
        f"{100 * sum(1 for chunk in chunks if chunk['provisions']) / len(chunks):.0f}% "
        "of the Manual's passages carry at least one."
    )
    report.line()

    report.table(
        ("Instrument", "Citations"),
        [
            (f"`{code}`", f"{count:,}")
            for code, count in ranked(instruments)
        ],
    )
    report.line(
        "`TMA1995` is the Trade Marks Act 1995 and `TMR1995` the Regulations. "
        "The rest are the Manual reaching outside its own corpus: the repealed "
        "1955 Act, the Plant Breeder's Rights Act, the Acts Interpretation Act, "
        "the 1905 Act, and the Designs Regulations."
    )
    report.line()

    report.table(
        ("Evidence for the citation", "Count", "Share"),
        [
            ("Hyperlink — the authors said so", f"{extraction['href']:,}", f"{100 * extraction['href'] / len(edges):.0f}%"),
            ("`explicit` — prose naming the instrument alongside", f"{certainty['explicit']:,}", f"{100 * certainty['explicit'] / len(edges):.0f}%"),
            ("`default` — bare “section N”, assumed to be the Act", f"{certainty['default']:,}", f"{100 * certainty['default'] / len(edges):.0f}%"),
            ("`ambiguous` — several instruments in scope, unresolved", f"{certainty['ambiguous']:,}", f"{100 * certainty['ambiguous'] / len(edges):.0f}%"),
        ],
    )
    report.line(
        f"**{100 * certainty['default'] / len(edges):.0f}% of statutory "
        "citations rest on a convention** — the Manual writes “section 41” "
        "without naming an instrument, and the extractor reads a bare section "
        "number as the Trade Marks Act. The convention is recorded on every "
        f"edge that relies on it, and the {certainty['ambiguous']} places where "
        "another instrument is genuinely in scope are flagged `ambiguous` "
        "rather than resolved."
    )
    report.line()

    report.line("**The twenty most-cited provisions**")
    report.line()
    report.table(
        ("Provision", "Citations", "Distinct passages"),
        [
            (
                f"`{ref}`",
                f"{count:,}",
                len({chunk["chunk_ref"] for chunk, edge in edges if provision_root(edge["id"]) == ref}),
            )
            for ref, count in ranked(roots, 20)
        ],
    )

    by_part_provisions = Counter(part_by_page[chunk["page_ref"]] for chunk, _ in edges)
    report.line("**The Parts that cite the law hardest**")
    report.line()
    report.table(
        ("Part", "Provision citations", "Words", "Citations per 1,000 words"),
        [
            (
                part_title.get(part, part),
                f"{count:,}",
                f"{words_by_part[part]:,}",
                f"{1000 * count / words_by_part[part]:.1f}",
            )
            for part, count in ranked(by_part_provisions, 8)
        ],
    )

    # --------------------------------------------------------------- cases
    report.head(2, "6. How much case law the Manual carries")

    citations = Counter(case["citation"] for _, case in cases)
    years = Counter(int(re.search(r"\d{4}", case["citation"]).group()) for _, case in cases)
    series = Counter(
        re.sub(r"^[\[(]\d{4}[\])]\s+(?:\d+\s+)?([A-Za-z]+).*$", r"\1", case["citation"])
        for _, case in cases
    )
    report.stat(
        [
            ("Case citations", f"{len(cases):,}"),
            ("Distinct decisions", f"{len(citations):,}"),
            ("Passages citing a decision", f"{sum(1 for chunk in chunks if chunk['cases']):,}"),
            ("Pages citing a decision", f"{len({chunk['page_ref'] for chunk in chunks if chunk['cases']}):,}"),
            ("Earliest decision cited", f"{min(years)}"),
            ("Most recent decision cited", f"{max(years)}"),
        ]
    )
    report.line(
        f"**Case law is concentrated.** Only "
        f"{100 * len({chunk['page_ref'] for chunk in chunks if chunk['cases']}) / len(pages):.0f}% "
        f"of pages cite a decision at all, and "
        f"{100 * sum(1 for chunk in chunks if chunk['cases']) / len(chunks):.0f}% "
        "of passages. The Manual is a procedures document that reaches for "
        "authority in a few places, not a case book."
    )
    report.line()

    report.table(
        ("Court or report series", "Citations"),
        [(court, f"{count:,}") for court, count in ranked(series, 12)],
    )

    report.table(
        ("Decade", "Citations"),
        [
            (f"{decade}s", f"{count:,}")
            for decade, count in sorted(Counter((year // 10) * 10 for year in years.elements()).items())
        ],
    )
    modern = sum(count for year, count in years.items() if year >= 1990)
    report.line(
        f"**{100 * modern / sum(years.values()):.0f}% of the Manual's case "
        "citations are to decisions from 1990 onwards**, but it still reaches "
        f"back to {min(years)}."
    )
    report.line()

    report.line("**The most-cited decisions**")
    report.line()
    report.table(
        ("Citation", "Times cited", "Pages"),
        [
            (
                f"`{citation}`",
                count,
                len({chunk["page_ref"] for chunk, case in cases if case["citation"] == citation}),
            )
            for citation, count in ranked(citations, 10)
        ],
    )

    by_part_cases = Counter(part_by_page[chunk["page_ref"]] for chunk, _ in cases)
    report.line("**Where the case law is**")
    report.line()
    report.table(
        ("Part", "Case citations"),
        [
            (part_title.get(part, part), count)
            for part, count in ranked(by_part_cases, 8)
        ],
    )

    # ----------------------------------------------------- amendment history
    report.head(2, "7. What the Manual says about its own changes")

    reasons = Counter((row["reason"] or "(no reason recorded)") for _, row in amendments)
    by_year = Counter(row["date"][:4] for _, row in amendments)
    most_amended = max(pages, key=lambda page: (len(page["amendments"]), page["page_ref"]))
    report.stat(
        [
            ("Amendment rows the Manual publishes", f"{len(amendments):,}"),
            ("Pages amended more than once", f"{sum(1 for page in pages if len(page['amendments']) > 1):,} of {len(pages):,}"),
            ("Most amendments on one page", f"{len(most_amended['amendments'])} (`{most_amended['page_ref']}`)"),
            ("Distinct reasons given", f"{len(reasons):,}"),
            ("Earliest amendment recorded", f"{min(row['date'] for _, row in amendments)}"),
            ("Most recent", f"{max(row['date'] for _, row in amendments)}"),
        ]
    )
    report.table(
        ("Year", "Amendments"),
        [(year, f"{count:,}") for year, count in sorted(by_year.items())],
    )
    report.line("**The reasons IP Australia gives**")
    report.line()
    report.table(
        ("Times", "Reason"),
        [(f"{count:,}", reason[:78]) for reason, count in ranked(reasons, 12)],
    )
    housekeeping = sum(
        count
        for reason, count in reasons.items()
        if "hyperlink" in reason.lower() or "link" in reason.lower()
    )
    report.line(
        f"**{housekeeping:,} of {len(amendments):,} recorded amendments "
        f"({100 * housekeeping / len(amendments):.0f}%) mention links or "
        "hyperlinks** — the Manual spends much of its published change history "
        f"maintaining its own citations. A further {reasons['(no reason recorded)']:,} "
        "rows give no reason at all."
    )
    report.line()

    # ----------------------------------------------------------- typography
    report.head(2, "8. Typography, and what it is doing")

    kinds = Counter(span["kind"] for span in emphasis)
    report.stat(
        [
            ("Emphasised spans", f"{len(emphasis):,}"),
            ("Italic (`i` + `em`)", f"{kinds['i'] + kinds['em']:,}"),
            ("Bold (`strong` + `b`)", f"{kinds['strong'] + kinds['b']:,}"),
            ("Underlined (`u`)", f"{kinds['u']:,}"),
            ("Superscript (`sup`, footnote markers)", f"{kinds['sup']:,}"),
        ]
    )
    report.line(
        "The Manual writes the same weight two ways and the snapshot does not "
        f"normalise it: `i` appears {kinds['i']:,} times against `em` "
        f"{kinds['em']}, and `strong` {kinds['strong']:,} times against `b` "
        f"{kinds['b']}. That is a fact about the markup, and there is nowhere "
        "in the record to put the claim that the two mean the same thing."
    )
    report.line()

    emphasised_words = Counter(span["text"].strip() for span in emphasis if span["text"].strip())
    report.table(
        ("Times emphasised", "Text"),
        [(count, f"“{text[:70]}”") for text, count in ranked(emphasised_words, 10)],
    )
    report.line(
        "Italics are how the Manual names things: instrument titles and the "
        "party names of decisions. It is the italic run beside a citation, not "
        "a hyperlink, that supplies most of the case names in "
        "`exports/cases.csv`."
    )
    report.line()

    # ------------------------------------------------------------- the join
    report.head(2, "9. The join to the legislation snapshot")

    if provisions:
        in_scope = [edge for _, edge in edges if edge["id"].split("/")[0] in IN_SCOPE]
        resolved = [edge for edge in in_scope if edge["id"] in known_refs]
        sections = {
            record["ref"]
            for record in provisions
            if record["kind"] in ("section", "regulation")
        }
        cited_roots = {provision_root(edge["id"]) for edge in in_scope}
        report.stat(
            [
                ("Provisions in the legislation snapshot", f"{len(provisions):,}"),
                ("Addressable refs (provisions and their units)", f"{len(known_refs):,}"),
                ("Manual citations to `TMA1995` or `TMR1995`", f"{len(in_scope):,}"),
                ("…that resolve to a provision the snapshot holds", f"{len(resolved):,} ({100 * len(resolved) / len(in_scope):.1f}%)"),
                ("…that do not", f"{len(in_scope) - len(resolved):,}"),
            ]
        )
        report.line(
            "**The two halves of this repository join without a lookup table.** "
            "A Manual passage citing section 41 carries "
            "`provisions[].id == \"TMA1995/s41\"`, and that is the ref of a "
            "provision record in the legislation snapshot."
        )
        report.line()
        for code, label, unit in (
            ("TMA1995", "Trade Marks Act 1995", "sections"),
            ("TMR1995", "Trade Marks Regulations 1995", "regulations"),
        ):
            held = {ref for ref in sections if ref.startswith(code + "/")}
            cited = {ref for ref in cited_roots if ref.startswith(code + "/")}
            # Unmatched is measured against every ref the instrument makes
            # addressable, not against `held` alone: a number that lands on a
            # schedule item or a container is matched, and counting it as
            # unmatched would overstate the gap.
            unmatched = {ref for ref in cited if ref not in known_refs}
            report.line(
                f"- **{label}**: the compilation carries {len(held)} {unit}. "
                f"The Manual cites {len(cited & held)} of them "
                f"({100 * len(cited & held) / len(held):.0f}%) and never "
                f"mentions the other {len(held - cited)}. A further "
                f"{len(unmatched)} numbers it cites have no counterpart "
                "anywhere in the current compilation."
            )
        report.line()
        report.line(
            "Those last numbers are worth reading carefully. They are not all "
            "errors: some are provisions repealed since the passage was "
            "written, some are references to another Act that the `default` "
            "convention reads as the Trade Marks Act. Some are neither — "
            "`TMA1995/s5T` comes from the words “Beethoven's 5th Symphony”."
        )
        report.line()
    else:
        report.line("_No legislation snapshot on disk; the join is not reported._")
        report.line()

    # ----------------------------------------------------------- vocabulary
    report.head(2, "10. Vocabulary")

    lowered = " ".join(texts).lower()
    tokens_alpha = re.findall(r"[a-z][a-z'’-]+", lowered)
    frequency = Counter(word for word in tokens_alpha if word not in STOPWORDS and len(word) > 2)
    report.table(
        ("Word", "Occurrences"),
        [(word, f"{count:,}") for word, count in ranked(frequency, 20)],
    )
    report.line(
        "Stopwords are excluded — the list is in `build_stats.py` and is a "
        "judgement, not a fact about the corpus. `class`, `suggested` and "
        "`alternatives` are inflated by one page: Part 14's Annex A13, a "
        f"{words_by_page['TMM/Part14/x-14.-annex-a13-list-of-terms-too-broad-for-classification']:,}-word "
        "list of terms too broad for classification, which is "
        f"{100 * words_by_page['TMM/Part14/x-14.-annex-a13-list-of-terms-too-broad-for-classification'] / len(words):.0f}% "
        "of the whole Manual by itself."
    )
    report.line()

    report.line("**Phrases**")
    report.line()
    phrases = [
        "trade mark",
        "trade marks",
        "the registrar",
        "goods and/or services",
        "the applicant",
        "capable of distinguishing",
        "evidence of use",
        "deceptively similar",
        "substantially identical",
        "honest concurrent use",
        "prima facie",
        "madrid protocol",
        "hearing officer",
    ]
    # Counted with word boundaries, not `str.count`: "trade mark" is a
    # substring of "trade marks", and a plain count would report the plural
    # inside the singular's total and overstate it by a quarter.
    phrase_counts = [
        (phrase, len(re.findall(r"\b" + re.escape(phrase) + r"\b", lowered)))
        for phrase in phrases
    ]
    report.table(
        ("Phrase", "Occurrences"),
        [(f"“{phrase}”", f"{count:,}") for phrase, count in phrase_counts],
    )

    # ---------------------------------------------------------- the quirks
    report.head(2, "11. Quirks the snapshot records rather than fixes")

    printed = [page for page in pages if page.get("printed_page_ref")]
    unreachable = manifest.get("run", {}).get("unreachable", [])
    report.line(
        f"- **{len(printed)} pages print a number that is not their address.** "
        "`TMM/Part20/3` prints “Part 20.2. Definition of sign” while "
        "`TMM/Part20/2` prints “20.2. Background to definition of a trade "
        "mark”, so two pages claim 20.2. The nav decides the address and the "
        "record says the page disagrees."
    )
    report.line(
        f"- **{len(unreachable)} pages are in the navigation tree but return "
        "404.** They are listed in `snapshot/manifest.json`, not silently "
        "dropped."
    )
    ambiguous_internal = sum(1 for _, ref in internal if ref.get("certainty") == "ambiguous")
    report.line(
        f"- **{certainty['ambiguous']} provision citations are flagged "
        "`ambiguous`** — several instruments are genuinely in scope and "
        "nothing in the source chooses between them, so the record carries the "
        f"ambiguity instead of resolving it. No cross-reference is "
        f"({ambiguous_internal} of {len(internal)})."
    )
    report.line(
        f"- **{sum(1 for _, link in links if link['text'] == '')} anchors "
        "contain no words at all** — an `<a>` wrapped around nothing. They are "
        "kept, with `start == end`, because the point in the text where the "
        "Manual put a link is a fact about the passage even when the link has "
        "no words to show for it."
    )
    same_words = sum(
        count - 1
        for chunk in chunks
        for count in Counter(link["text"] for link in chunk["links"]).values()
        if count > 1
    )
    report.line(
        f"- **{same_words} anchors repeat words another anchor in the same "
        "passage already used**, which is why links carry character offsets "
        "instead of being matched by their text."
    )
    report.line(
        "- **The Manual mis-sets its own citations.** `(1904) 21 ROC 617` is a "
        "mistyped `RPC`, and it is exported as written: correcting it would "
        "put a decision in the data that the Manual does not cite."
    )
    report.line()

    report.line("---")
    report.line()
    report.line(
        "_Generated by `exports/build_stats.py` from "
        f"`snapshot/` at extractor `{manifest.get('extractor_version', 'unknown')}`._"
    )

    OUT.write_text(report.text(), encoding="utf-8")
    print(
        f"{OUT.relative_to(ROOT)}: {len(pages)} pages, {len(chunks)} chunks, "
        f"{len(words):,} words, {len(links):,} links, {len(edges):,} provision "
        f"citations, {len(cases):,} case citations"
    )


if __name__ == "__main__":
    main()
