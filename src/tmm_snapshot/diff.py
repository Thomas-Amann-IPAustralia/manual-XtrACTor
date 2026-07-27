"""Compare two snapshot states, emit a change report.

Owned by T8. Output is the body of the pull request a scheduled crawl opens,
and that pull request is the audit trail: it is where a human decides whether
an amendment was substantive practice change or a hyperlink tidy-up, using the
Manual's own amendment_note as the clue.

Structural changes are called out loudly. A Part's page count moving usually
means a restructure, not an edit. See SOURCE_NOTES.md §10.

The report is a pure function of the two directories it is given — no clock, no
network, no git. Run it twice on the same pair and you get the same bytes, for
the same reason page files are byte-stable: a report that moves on its own is a
report nobody reads twice.

ARCHITECTURE.md does not fix a signature for this module. `render_report`
keeps the one the skeleton suggested; everything else here is T8's.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tmm_snapshot import config, writer

# Part ordering has one home, and it is the orchestrator that also uses it to
# decide what `--limit 5` means. Restating the rule here would give the report
# and the crawl two chances to disagree about what 'Part 32A' comes after.
from tmm_snapshot.crawl import part_sort_key

#: Longest list this report will print before summarising the tail. A restructure
#: can move hundreds of pages at once, and GitHub truncates a pull request body
#: at 65 536 characters — silently, in the middle of a sentence. Better to cut
#: where we can say how much was cut.
MAX_LISTED = 40

#: What a table cell says when the Manual said nothing.
NOTHING = "—"


# --------------------------------------------------------------------------
# Reading a snapshot state
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PageState:
    """One page record, reduced to what a change report needs of it."""

    page_ref: str
    part_id: str
    url: str
    nav_title: str
    h1: str | None
    content_hash: str
    date_published: str | None
    last_amended: str | None
    amendment_note: str | None
    extractor_version: str
    #: chunk_ref -> content_hash. The chunk text itself is not read: this
    #: module counts what moved, and the diff of the file says what it says.
    chunks: dict[str, str] = field(default_factory=dict)

    @property
    def metadata(self) -> dict[str, Any]:
        """Everything the record asserts except the body hash and the chunks.

        `crawled_at` is deliberately absent. It records when this version of
        the page was first seen (SCHEMA.md), so it moves exactly when something
        else here moves, and reporting it would be reporting the same fact
        twice.
        """
        return {
            "amendment_note": self.amendment_note,
            "date_published": self.date_published,
            "extractor_version": self.extractor_version,
            "h1": self.h1,
            "last_amended": self.last_amended,
            "nav_title": self.nav_title,
            "part_id": self.part_id,
            "url": self.url,
        }


@dataclass(frozen=True)
class Part:
    part_id: str
    part_title: str
    page_count: int


@dataclass(frozen=True)
class Snapshot:
    """A snapshot directory, read for comparison. Absent files read as empty."""

    root: Path
    pages: dict[str, PageState]
    retired: dict[str, PageState]
    parts: dict[str, Part]
    #: url -> page_ref, straight from the inventory. The same URL under a new
    #: address is the cleanest evidence of a renumbering there is.
    addresses: dict[str, str]
    manifest: dict[str, Any]

    @property
    def populated(self) -> bool:
        return bool(self.pages or self.retired or self.parts)


def _read_json(path: Path) -> dict[str, Any]:
    """A JSON object from disk, or an empty one. Absent and corrupt read alike.

    Reading a corrupt file as empty is safe *here* and nowhere else in this
    package: the validator is what fails on a malformed record, and a report
    that crashed rather than printing would hide every other change in the run.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return document if isinstance(document, dict) else {}


def _page_state(document: dict[str, Any]) -> PageState | None:
    page = document.get("page")
    if not isinstance(page, dict) or not isinstance(page.get("page_ref"), str):
        return None
    chunks = {
        chunk["chunk_ref"]: str(chunk.get("content_hash", ""))
        for chunk in document.get("chunks", [])
        if isinstance(chunk, dict) and isinstance(chunk.get("chunk_ref"), str)
    }
    return PageState(
        page_ref=page["page_ref"],
        part_id=str(page.get("part_id", "")),
        url=str(page.get("url", "")),
        nav_title=str(page.get("nav_title", "")),
        h1=page.get("h1"),
        content_hash=str(page.get("content_hash", "")),
        date_published=page.get("date_published"),
        last_amended=page.get("last_amended"),
        amendment_note=page.get("amendment_note"),
        extractor_version=str(page.get("extractor_version", "")),
        chunks=chunks,
    )


def _pages(root: Path, *, retired: bool) -> dict[str, PageState]:
    states: dict[str, PageState] = {}
    for path in writer.iter_page_files(root, retired=retired):
        document = writer.read_page_file(path)
        state = _page_state(document) if document else None
        if state is not None:
            states[state.page_ref] = state
    return states


def read_snapshot(root: Path) -> Snapshot:
    """Load a snapshot directory. A directory that is not there reads as empty.

    An empty read is not an error: the first crawl compares against exactly
    that, and `snapshot/` holds nothing but a `.gitkeep` in a fresh checkout.
    """
    root = Path(root)
    sitemap = _read_json(root / "sitemap.json")

    parts = {
        part["part_id"]: Part(
            part_id=part["part_id"],
            part_title=str(part.get("part_title", "")),
            page_count=int(part.get("page_count", 0)),
        )
        for part in sitemap.get("parts", [])
        if isinstance(part, dict) and isinstance(part.get("part_id"), str)
    }
    addresses = {
        page["url"]: page["page_ref"]
        for page in sitemap.get("pages", [])
        if isinstance(page, dict)
        and isinstance(page.get("url"), str)
        and isinstance(page.get("page_ref"), str)
    }

    return Snapshot(
        root=root,
        pages=_pages(root, retired=False),
        retired=_pages(root, retired=True),
        parts=parts,
        addresses=addresses,
        manifest=_read_json(root / "manifest.json"),
    )


# --------------------------------------------------------------------------
# Comparing them
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Amendment:
    """One page that is in both snapshots and does not say the same thing."""

    before: PageState
    after: PageState
    edited: int
    added: int
    removed: int

    @property
    def total(self) -> int:
        return len(self.after.chunks)

    @property
    def changed(self) -> int:
        """Chunks a reader would find different: edited, plus brand new ones."""
        return self.edited + self.added

    @property
    def text_moved(self) -> bool:
        return bool(self.changed or self.removed)

    @property
    def body_moved(self) -> bool:
        return self.before.content_hash != self.after.content_hash

    @property
    def fields(self) -> list[tuple[str, Any, Any]]:
        """(name, before, after) for every page field that moved."""
        was, now = self.before.metadata, self.after.metadata
        return [(name, was[name], now[name]) for name in sorted(was) if was[name] != now[name]]

    @property
    def silent(self) -> bool:
        """Body moved, but the Manual's own amendment log did not.

        Worth a reviewer's attention. The Amended Reasons table is as close to
        a change feed as the Manual has (SOURCE_NOTES.md §5), and an edit that
        does not appear in it is one nobody downstream will hear about.
        """
        return (
            self.body_moved
            and self.before.last_amended == self.after.last_amended
            and self.before.amendment_note == self.after.amendment_note
        )


@dataclass(frozen=True)
class PartChange:
    part_id: str
    part_title: str
    before: int
    after: int


@dataclass
class Changes:
    """Everything that moved between two snapshots."""

    added: list[PageState] = field(default_factory=list)
    retired: list[PageState] = field(default_factory=list)
    restored: list[PageState] = field(default_factory=list)
    #: Gone from pages/ and not filed under _retired/. Never produced by a
    #: complete crawl — `writer.retire` moves pages, it does not delete them —
    #: so this is either a hand edit or a bug, and is reported as such.
    vanished: list[PageState] = field(default_factory=list)
    amended: list[Amendment] = field(default_factory=list)
    #: Same body, different record. A Part renamed in the nav does this.
    reworded: list[Amendment] = field(default_factory=list)
    parts_added: list[Part] = field(default_factory=list)
    parts_removed: list[Part] = field(default_factory=list)
    parts_resized: list[PartChange] = field(default_factory=list)
    parts_renamed: list[tuple[Part, Part]] = field(default_factory=list)
    #: (url, old page_ref, new page_ref) — the same page at a new address.
    readdressed: list[tuple[str, str, str]] = field(default_factory=list)
    unchanged: int = 0

    @property
    def structural(self) -> bool:
        return bool(
            self.parts_added
            or self.parts_removed
            or self.parts_resized
            or self.parts_renamed
            or self.readdressed
        )

    @property
    def any(self) -> bool:
        return bool(
            self.added
            or self.retired
            or self.restored
            or self.vanished
            or self.amended
            or self.reworded
            or self.structural
        )


def _page_sort_key(page_ref: str) -> tuple:
    """Reading order: Part first, then the dotted address numerically.

    Lexically, `TMM/Part22/10` sorts before `TMM/Part22/2`, which reads as a
    mistake in a report a human is scanning for the page they know changed.
    """
    components = page_ref.split("/")
    part = part_sort_key(components[1]) if len(components) > 1 else (10**6, page_ref)
    tail: list[tuple[int, int, str]] = []
    for component in components[2:]:
        tail.append((0, int(component), "") if component.isdigit() else (1, 0, component))
    return (part, tail, page_ref)


def _amendment(before: PageState, after: PageState) -> Amendment:
    edited = sum(
        1
        for ref, digest in after.chunks.items()
        if ref in before.chunks and before.chunks[ref] != digest
    )
    return Amendment(
        before=before,
        after=after,
        edited=edited,
        added=sum(1 for ref in after.chunks if ref not in before.chunks),
        removed=sum(1 for ref in before.chunks if ref not in after.chunks),
    )


def compare(before: Snapshot, after: Snapshot) -> Changes:
    """What moved from `before` to `after`. Reads nothing; decides nothing."""
    changes = Changes()

    for ref in sorted(set(before.pages) | set(after.pages), key=_page_sort_key):
        was, now = before.pages.get(ref), after.pages.get(ref)

        if now is not None and was is None:
            (changes.restored if ref in before.retired else changes.added).append(now)
        elif was is not None and now is None:
            (changes.retired if ref in after.retired else changes.vanished).append(was)
        elif was is not None and now is not None:
            if was == now:
                changes.unchanged += 1
                continue
            amendment = _amendment(was, now)
            target = changes.amended if amendment.body_moved or amendment.text_moved else changes.reworded
            target.append(amendment)

    for part_id in sorted(set(before.parts) | set(after.parts), key=part_sort_key):
        was_part, now_part = before.parts.get(part_id), after.parts.get(part_id)
        if now_part is not None and was_part is None:
            changes.parts_added.append(now_part)
            continue
        if was_part is not None and now_part is None:
            changes.parts_removed.append(was_part)
            continue
        assert was_part is not None and now_part is not None
        if was_part.page_count != now_part.page_count:
            changes.parts_resized.append(
                PartChange(part_id, now_part.part_title, was_part.page_count, now_part.page_count)
            )
        if was_part.part_title != now_part.part_title:
            changes.parts_renamed.append((was_part, now_part))

    for url in sorted(set(before.addresses) & set(after.addresses)):
        if before.addresses[url] != after.addresses[url]:
            changes.readdressed.append((url, before.addresses[url], after.addresses[url]))

    return changes


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def human_ref(page_ref: str) -> str:
    """'TMM/Part22/1' -> 'Part 22.1'. How the Manual addresses itself.

    Unnumbered pages carry a slug-derived ref (SOURCE_NOTES.md §7) and come out
    of here looking like one. That is honest — there is no dotted address to
    print — and the nav title sits beside it in every list that uses this.
    """
    components = page_ref.split("/")
    if len(components) < 2 or not components[1].startswith("Part"):
        return page_ref
    number = components[1][len("Part") :]
    tail = ".".join(components[2:])
    return f"Part {number}.{tail}" if tail else f"Part {number}"


def _cell(value: Any) -> str:
    """One table cell. A pipe or a newline in a title would break the table."""
    if value is None or value == "":
        return NOTHING
    return " ".join(str(value).split()).replace("|", "\\|")


def _count(number: int, noun: str, plural: str | None = None) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {plural or noun + 's'}"


def _listing(page: PageState) -> str:
    return f"- **{human_ref(page.page_ref)}** — {_cell(page.nav_title)} ([source]({page.url}))"


def _capped(lines: list[str], *, row: bool = False) -> list[str]:
    """The first MAX_LISTED lines, and how many were left out.

    `row=True` spells the tail as a table row, because a bullet in the middle
    of a table stops it being a table.
    """
    if len(lines) <= MAX_LISTED:
        return lines
    rest = len(lines) - MAX_LISTED
    tail = f"| … and {rest} more |" if row else f"- … and {rest} more."
    return [*lines[:MAX_LISTED], tail]


def _section(title: str, lines: list[str], *, preamble: str | None = None) -> list[str]:
    if not lines:
        return []
    out = ["", f"## {title}", ""]
    if preamble:
        out.extend([preamble, ""])
    out.extend(_capped(lines))
    return out


def _headline(changes: Changes) -> str:
    bits: list[str] = []
    if changes.amended:
        bits.append(_count(len(changes.amended), "page") + " amended")
    if changes.added:
        bits.append(f"{len(changes.added)} added")
    if changes.retired:
        bits.append(f"{len(changes.retired)} retired")
    if changes.restored:
        bits.append(f"{len(changes.restored)} restored")
    if changes.vanished:
        bits.append(f"{len(changes.vanished)} GONE")
    if changes.reworded and not bits:
        bits.append(_count(len(changes.reworded), "page") + " retitled")
    if changes.structural and not bits:
        bits.append("structure moved")
    return ", ".join(bits) if bits else "no changes"


def _context(after: Snapshot) -> list[str]:
    """One line of run metadata, from the manifest the crawl just wrote."""
    manifest = after.manifest
    if not manifest:
        return []

    run = manifest.get("run", {}) if isinstance(manifest.get("run"), dict) else {}
    corpus = manifest.get("corpus", {}) if isinstance(manifest.get("corpus"), dict) else {}

    facts = [f"Crawled `{manifest.get('crawled_at', 'unknown')}`"]
    if corpus.get("pages"):
        facts.append(f"{_count(int(corpus['pages']), 'page')} in the inventory")
    if corpus.get("parts"):
        facts.append(f"{_count(int(corpus['parts']), 'Part')}")
    if run.get("pages_written") is not None:
        facts.append(f"{_count(int(run['pages_written']), 'page file')} written")
    facts.append(f"extractor `{manifest.get('extractor_version', 'unknown')}`")

    lines = ["", ". ".join(facts) + "."]

    if run and not run.get("complete", True):
        scope = f"`--part {run['part']}`" if run.get("part") else f"`--limit {run.get('limit')}`"
        lines.extend(
            [
                "",
                f"> **Partial run** ({scope}). It did not see the whole inventory, "
                "so a page missing from it is not evidence that the page is gone, "
                "and nothing was retired.",
            ]
        )
    return lines


def _structure(changes: Changes) -> list[str]:
    if not changes.structural:
        return []

    lines = [
        "",
        "## Structure",
        "",
        "**Read this before the amendments.** The Manual is overhauled Part by "
        "Part, not only edited (SOURCE_NOTES.md §10), so a Part's page count "
        "moving usually means pages were renamed, split, merged or renumbered.",
        "",
    ]
    lines.extend(
        f"- **New Part {part.part_id[4:]}** — {_cell(part.part_title)} "
        f"({_count(part.page_count, 'page')})"
        for part in changes.parts_added
    )
    lines.extend(
        f"- **Part {part.part_id[4:]} is gone from the nav** — {_cell(part.part_title)} "
        f"(held {_count(part.page_count, 'page')})"
        for part in changes.parts_removed
    )
    lines.extend(
        f"- **Part {change.part_id[4:]}: {change.before} → {change.after} pages** — "
        f"{_cell(change.part_title)}"
        for change in changes.parts_resized
    )
    lines.extend(
        f"- Part {was.part_id[4:]} renamed: {_cell(was.part_title)} → "
        f"{_cell(now.part_title)}"
        for was, now in changes.parts_renamed
    )
    if changes.readdressed:
        lines.extend(
            [
                "",
                "Same URL, new address — the page did not go anywhere, its "
                "number did. Citations to the old ref will not resolve:",
                "",
            ]
        )
        lines.extend(
            _capped(
                [
                    f"- `{was}` → `{now}` ([source]({url}))"
                    for url, was, now in changes.readdressed
                ]
            )
        )
    return lines


def _amended_table(changes: Changes) -> list[str]:
    if not changes.amended:
        return []

    rows: list[str] = []
    for amendment in changes.amended:
        page = amendment.after
        moved = f"{amendment.changed} of {amendment.total}"
        extra = []
        if amendment.added:
            extra.append(f"+{amendment.added} new")
        if amendment.removed:
            extra.append(f"-{amendment.removed} gone")
        if extra:
            moved += f" ({', '.join(extra)})"
        rows.append(
            f"| **{human_ref(page.page_ref)}** ([source]({page.url})) | {moved} | "
            f"{_cell(page.last_amended)} | {_cell(page.amendment_note)} |"
        )

    lines = [
        "",
        f"## Pages amended ({len(changes.amended)})",
        "",
        "| Page | Paragraphs | Amended | IP Australia's reason |",
        "|---|---|---|---|",
        *_capped(rows, row=True),
    ]

    if any(amendment.changed == 0 for amendment in changes.amended):
        lines.extend(
            [
                "",
                "`0 of N` is not a mistake: a chunk hash covers the text, and "
                "*Update hyperlinks* — one of the Manual's own reasons — moves "
                "the markup around it without changing a word.",
            ]
        )

    silent = [amendment for amendment in changes.amended if amendment.silent]
    if silent:
        lines.extend(
            [
                "",
                "**Changed without saying so.** These pages moved, but their "
                "Amended Reasons table did not — so the Manual's own change "
                "feed does not mention the edit:",
                "",
            ]
        )
        lines.extend(
            _capped([f"- **{human_ref(a.after.page_ref)}**" for a in silent])
        )
    return lines


def _reworded(changes: Changes) -> list[str]:
    """Records that moved without the body moving. Usually a nav retitle."""
    if not changes.reworded:
        return []

    def version_bump_only(amendment: Amendment) -> bool:
        return [name for name, _, _ in amendment.fields] == ["extractor_version"]

    version_only = [a for a in changes.reworded if version_bump_only(a)]
    rest = [a for a in changes.reworded if not version_bump_only(a)]

    lines: list[str] = []
    if rest:
        lines.extend(
            [
                "",
                f"## Changed around the text ({len(rest)})",
                "",
                "The body is byte-identical; the record around it is not. A Part "
                "renamed in the nav does this, and it is why the skip gate "
                "compares every field and not just the hash "
                "(ARCHITECTURE.md §Skip logic).",
                "",
            ]
        )
        lines.extend(
            _capped(
                [
                    f"- **{human_ref(amendment.after.page_ref)}** — "
                    + "; ".join(
                        f"`{name}`: {_cell(was)} → {_cell(now)}"
                        for name, was, now in amendment.fields
                    )
                    for amendment in rest
                ]
            )
        )

    if version_only:
        was = version_only[0].before.extractor_version
        now = version_only[0].after.extractor_version
        lines.extend(
            [
                "",
                "## Rebuilt by a new extractor",
                "",
                f"{_count(len(version_only), 'page')} carry `{now}` in place of "
                f"`{was}` and are otherwise unchanged. The corpus was rebuilt; "
                "the Manual did not move (SCHEMA.md §extractor_version).",
            ]
        )
    return lines


def _unreachable(after: Snapshot) -> list[str]:
    run = after.manifest.get("run", {})
    entries = run.get("unreachable", []) if isinstance(run, dict) else []
    if not entries:
        return []
    return [
        "",
        f"## Unreachable ({len(entries)})",
        "",
        "The nav links these; the site would not serve them. No record was "
        "written and any record already held is untouched — this is not "
        "retirement, which means gone from the nav (SOURCE_NOTES.md §14).",
        "",
        *_capped(
            [
                f"- `{entry.get('page_ref')}` — {entry.get('url')} returned "
                f"{entry.get('status')}"
                for entry in entries
                if isinstance(entry, dict)
            ]
        ),
    ]


def _first_snapshot(after: Snapshot) -> str:
    """The report for a snapshot with nothing to compare against."""
    lines = [
        "# Manual snapshot: first crawl",
        "",
        f"Nothing to compare against — this is the whole Manual as it stands, "
        f"{_count(len(after.pages), 'page')} across "
        f"{_count(len(after.parts), 'Part')}. Every later report is a diff "
        "against it.",
        *_context(after),
    ]
    if after.parts:
        # Uncapped, unlike every other list here. This table is the inventory,
        # it is bounded by the number of Parts in the Manual, and a reader who
        # has never seen the corpus before wants all of it.
        lines.extend(["", "| Part | Pages | Title |", "|---|---|---|"])
        lines.extend(
            f"| Part {part.part_id[4:]} | {part.page_count} | {_cell(part.part_title)} |"
            for part in sorted(after.parts.values(), key=lambda p: part_sort_key(p.part_id))
        )
    lines.extend(_unreachable(after))
    lines.extend(["", "---", "", "Never auto-merged. The human read is the audit trail."])
    return "\n".join(lines).rstrip() + "\n"


def render(before: Snapshot, after: Snapshot) -> str:
    """The markdown report between two loaded snapshots."""
    if not before.populated:
        return _first_snapshot(after)

    changes = compare(before, after)

    lines = [f"# Manual snapshot: {_headline(changes)}", *_context(after)]

    if not changes.any:
        lines.extend(
            [
                "",
                f"{_count(changes.unchanged, 'page')} compared, none moved. The "
                "Manual says today what it said last time we looked.",
            ]
        )

    lines.extend(_structure(changes))
    lines.extend(_amended_table(changes))
    lines.extend(
        _section(
            f"Pages added ({len(changes.added)})",
            [_listing(page) for page in changes.added],
        )
    )
    lines.extend(
        _section(
            f"Pages retired ({len(changes.retired)})",
            [_listing(page) for page in changes.retired],
            preamble=(
                "Gone from the nav, not deleted: the record moves to "
                "`pages/_retired/` so old citations still resolve, and its raw "
                "HTML stays where it is (ARCHITECTURE.md §Retirement)."
            ),
        )
    )
    lines.extend(
        _section(
            f"Pages restored ({len(changes.restored)})",
            [_listing(page) for page in changes.restored],
            preamble="Retired in an earlier run, back in the nav now.",
        )
    )
    lines.extend(
        _section(
            f"Pages gone without being retired ({len(changes.vanished)})",
            [_listing(page) for page in changes.vanished],
            preamble=(
                "**A complete crawl cannot produce this.** Retirement moves a "
                "page file, it never deletes one — so these went by a hand "
                "edit or by a bug, and the citations that pointed at them now "
                "resolve to nothing. Do not merge without finding out which."
            ),
        )
    )
    lines.extend(_reworded(changes))
    lines.extend(_unreachable(after))

    if changes.any:
        lines.extend(["", f"{_count(changes.unchanged, 'page')} unchanged."])
    lines.extend(["", "---", "", "Never auto-merged. The human read is the audit trail."])

    return "\n".join(lines).rstrip() + "\n"


def render_report(before: Path, after: Path) -> str:
    """Markdown change report between two snapshot states."""
    return render(read_snapshot(before), read_snapshot(after))


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tmm_snapshot.diff",
        description=(
            "Compare two snapshot states and write the change report that "
            "becomes the body of a crawl's pull request."
        ),
        epilog=(
            "The 'before' state is a copy of snapshot/ taken before the crawl "
            "ran — scheduled CI copies it aside for exactly this."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--before",
        type=Path,
        required=True,
        metavar="DIR",
        help="the snapshot as it was; an absent directory reads as a first crawl",
    )
    parser.add_argument(
        "--after",
        type=Path,
        default=config.SNAPSHOT_DIR,
        metavar="DIR",
        help="the snapshot as it is now",
    )
    parser.add_argument(
        "--out",
        type=Path,
        metavar="FILE",
        help="write the report here instead of to stdout",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = render_report(args.before, args.after)
    if args.out is None:
        sys.stdout.write(report)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
