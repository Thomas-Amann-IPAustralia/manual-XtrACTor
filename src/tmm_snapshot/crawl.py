"""Orchestration and CLI entry point.

Owned by T7. Wires robots check -> fetch -> sitemap -> per page (fetch, parse,
chunk, extract, write), applying the three skip gates from ARCHITECTURE.md.

The argument parser is settled and is what `--help` documents; `run` is the
part T7 fills in.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from tmm_snapshot import config, writer
from tmm_snapshot.chunker import chunk_body
from tmm_snapshot.fetch import Fetcher
from tmm_snapshot.page import parse_page
from tmm_snapshot.sitemap import NavPage, build_sitemap, write_sitemap

#: Matches the part_id form the schema requires: Part22, Part19A, Part32B.
_PART_ID = re.compile(r"^Part[0-9]{1,3}[A-Z]?$")

#: Splits a part_id into its number and its alpha suffix, for ordering: the
#: Manual reads Part 5, Part 22, Part 32A, Part 32B, and a lexical sort of the
#: ids reads Part 1, Part 10, Part 2. Only ordering depends on this — Part
#: membership never does.
_PART_NUMBER = re.compile(r"^Part(?P<number>[0-9]{1,3})(?P<suffix>[A-Z]?)$")


class CrawlError(Exception):
    """The run cannot continue and must not produce a partial snapshot.

    Raised where carrying on would write something confidently wrong: a nav
    page the site will not serve, a conditional cache out of step with the
    stored source. A missing record is recoverable; a silently wrong one is
    not.
    """


def part_id(value: str) -> str:
    """argparse type for --part. Rejects anything the schema would reject."""
    if not _PART_ID.match(value):
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a Part id (expected e.g. Part22, Part19A, Part32B)"
        )
    return value


def positive_int(value: str) -> int:
    """argparse type for --limit."""
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer") from None
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"{value!r} must be 1 or greater")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tmm_snapshot.crawl",
        description=(
            "Crawl the IP Australia Trade Marks Manual and write a "
            "deterministic snapshot to snapshot/."
        ),
        epilog=(
            "Requests are serial and rate limited, and robots.txt is checked "
            "on every run. Do not run a full crawl on a whim: use --limit, or "
            "let scheduled CI do it."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and parse, report what would change, write nothing",
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        metavar="N",
        help="stop after N pages",
    )
    parser.add_argument(
        "--part",
        type=part_id,
        metavar="PartNN",
        help="restrict the crawl to one Part, e.g. Part22",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="ignore the skip gates and reprocess every page",
    )
    parser.add_argument(
        "--from-raw",
        action="store_true",
        help=(
            "re-parse snapshot/raw/ without touching the network; what you "
            "run after every parser fix"
        ),
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=config.SNAPSHOT_DIR,
        metavar="DIR",
        help="snapshot directory to write",
    )
    return parser


# --------------------------------------------------------------------------
# Ordering
# --------------------------------------------------------------------------


def part_sort_key(value: str) -> tuple[int, str]:
    """Order Parts the way the Manual does: 5, 22, 32A, 32B."""
    match = _PART_NUMBER.match(value)
    if match is None:
        return (10**6, value)
    return (int(match.group("number")), match.group("suffix"))


def page_order(sitemap: dict[str, NavPage]) -> list[NavPage]:
    """The inventory in reading order — Part, then position within the Part.

    `--limit 5` must mean the same five pages on every run, or a limited crawl
    is not comparable with the one before it.
    """
    return sorted(
        sitemap.values(),
        key=lambda nav: (part_sort_key(nav.part_id), nav.nav_ordinal, nav.page_ref),
    )


# --------------------------------------------------------------------------
# Getting an inventory
# --------------------------------------------------------------------------


def _stored_nav_html(root: Path) -> str | None:
    """Any stored page, for its nav. Every Manual page renders the whole tree.

    Lexically first, so that two runs over the same snapshot build the
    inventory from the same bytes.
    """
    raw = Path(root) / "raw"
    if not raw.is_dir():
        return None
    for path in sorted(raw.rglob("*.html")):
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            continue
    return None


def _sitemap_from_raw(root: Path) -> dict[str, NavPage]:
    """Rebuild the inventory from stored HTML, without the network.

    Rebuilt rather than read back from sitemap.json, because `--from-raw` is
    what you run after a parser fix and the sitemap parser is one of the
    parsers that gets fixed.
    """
    html = _stored_nav_html(root)
    if html is None:
        raise CrawlError(
            f"--from-raw needs stored source and {Path(root) / 'raw'} holds "
            "none; run a crawl first"
        )
    return build_sitemap(html)


def _sitemap_from_site(fetcher: Fetcher, root: Path) -> dict[str, NavPage]:
    result = fetcher.get(config.SITEMAP_SEED_URL)
    if result.status == 200 and result.html is not None:
        return build_sitemap(result.html)
    if result.status == 304:
        # The seed is unchanged, so any stored page carries the same nav.
        html = _stored_nav_html(root)
        if html is None:
            raise CrawlError(
                f"{config.SITEMAP_SEED_URL} returned 304 but no stored source "
                f"was found under {Path(root) / 'raw'}; {config.CACHE_DIR} is "
                "out of step with the snapshot — delete it and re-run"
            )
        return build_sitemap(html)
    raise CrawlError(
        f"{config.SITEMAP_SEED_URL} returned {result.status}; without the nav "
        "no page's Part is knowable and nothing downstream may be written"
    )


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------


@dataclass
class Stats:
    """What one run did. Reported to stdout and written to manifest.json."""

    in_scope: int = 0
    fetched: int = 0
    not_modified: int = 0
    skipped_304: int = 0
    unchanged: int = 0
    parsed: int = 0
    pages_written: int = 0
    raw_written: int = 0
    chunks: int = 0
    chunks_changed: int = 0
    missing_raw: list[str] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)
    #: (page_ref, url, status) for nav entries the site would not serve.
    unreachable: list[tuple[str, str, int]] = field(default_factory=list)
    #: (page_ref, changed chunks, total chunks) for every page that moved.
    amended: list[tuple[str, int, int]] = field(default_factory=list)


def _html_for(
    nav: NavPage,
    root: Path,
    fetcher: Fetcher | None,
    stats: Stats,
    *,
    from_raw: bool,
    force: bool,
    have_stored_record: bool,
) -> str | None:
    """The source for one page, or None when a gate says to skip it.

    Gate 1 lives here: a conditional request answered 304 means the stored raw
    file is still current, and if a parsed record for it is already on disk
    there is nothing left to do. `--force` still reprocesses, from the stored
    source — forcing does not mean asking the site for bytes it has just told
    us we already hold.
    """
    if from_raw:
        html = writer.read_raw(nav.page_ref, root)
        if html is None:
            stats.missing_raw.append(nav.page_ref)
        return html

    assert fetcher is not None
    result = fetcher.get(nav.url)

    if result.status == 200 and result.html is not None:
        stats.fetched += 1
        return result.html

    if result.status == 304:
        stats.not_modified += 1
        if have_stored_record and not force:
            stats.skipped_304 += 1
            return None
        html = writer.read_raw(nav.page_ref, root)
        if html is None:
            raise CrawlError(
                f"{nav.url} returned 304 but no stored source was found at "
                f"{writer.raw_path(nav.page_ref, root)}; {config.CACHE_DIR} is "
                "out of step with the snapshot — delete it and re-run"
            )
        return html

    # The nav and the site disagree. Recorded by name and skipped rather than
    # raised on: the Manual's own nav links 'Part 1.3. Practice Change
    # Procedure' to a URL that 404s (SOURCE_NOTES.md §14), and abandoning 501
    # good pages over one rotted link is not caution, it is losing the
    # snapshot. Nothing is guessed — no record is written for the page, any
    # record already held is left untouched, and the run names it in both the
    # report and the manifest.
    stats.unreachable.append((nav.page_ref, nav.url, result.status))
    return None


def _process(
    nav: NavPage,
    sitemap: dict[str, NavPage],
    root: Path,
    fetcher: Fetcher | None,
    args: argparse.Namespace,
    stats: Stats,
) -> None:
    """One page, through all three gates."""
    stored = writer.read_page_file(writer.page_path(nav.page_ref, nav.part_id, root))

    html = _html_for(
        nav,
        root,
        fetcher,
        stats,
        from_raw=bool(args.from_raw),
        force=bool(args.force),
        have_stored_record=stored is not None,
    )
    if html is None:
        return

    record, body = parse_page(html, nav)
    stats.parsed += 1

    if args.dry_run:
        if writer.read_raw(nav.page_ref, root) != html:
            stats.raw_written += 1
    elif writer.write_raw(nav.page_ref, html, root):
        stats.raw_written += 1

    # Gate 2. The stored record already says everything this parse says, so
    # chunking and extracting again would produce the same bytes at the cost of
    # the most expensive stage in the pipeline.
    stored_page = stored.get("page") if stored else None
    if not args.force and writer.page_fields_unchanged(stored_page, record):
        stats.unchanged += 1
        return

    chunks = chunk_body(body, record, nav, sitemap)
    stats.chunks += len(chunks)

    # Gate 3. The page moved, but most of it may not have. Every chunk is
    # rewritten regardless — they share a file — so this only feeds the report,
    # which is what tells a reviewer whether an amendment touched one paragraph
    # or the whole Part.
    was = {
        chunk.get("chunk_ref"): chunk.get("content_hash")
        for chunk in (stored.get("chunks", []) if stored else [])
        if isinstance(chunk, dict)
    }
    changed_chunks = sum(
        1 for chunk in chunks if was.get(chunk.chunk_ref) != chunk.content_hash
    )
    stats.chunks_changed += changed_chunks

    if args.dry_run:
        _, _, changed = writer.render_page(record, chunks, root)
    else:
        writer.unretire(root, nav.page_ref, nav.part_id)
        changed = writer.write_page(record, chunks, root)

    if changed:
        stats.pages_written += 1
        if stored is not None:
            stats.amended.append((nav.page_ref, changed_chunks, len(chunks)))


def _corpus(root: Path, sitemap: dict[str, NavPage]) -> dict[str, object]:
    """The numbers SOURCE_NOTES.md §12 measured by hand, measured by the run.

    They live in that file because `write_manifest` did not exist yet. It does
    now, and this is where they belong.
    """
    sizes = [path.stat().st_size for path in (Path(root) / "raw").rglob("*.html")]
    return {
        "mean_raw_bytes": round(sum(sizes) / len(sizes)) if sizes else 0,
        "pages": len(sitemap),
        "parts": len({nav.part_id for nav in sitemap.values()}),
        "raw_bytes": sum(sizes),
        "raw_files": len(sizes),
    }


def _manifest(
    args: argparse.Namespace, stats: Stats, started_at: str, corpus: dict[str, object]
) -> dict[str, object]:
    return {
        "corpus": corpus,
        "crawled_at": started_at,
        "extractor_version": config.EXTRACTOR_VERSION,
        "finished_at": writer.utcnow(),
        "run": {
            "chunks": stats.chunks,
            "chunks_changed": stats.chunks_changed,
            # Only a complete run is evidence about the pages it did not
            # write. The diff tooling needs to know which kind this was before
            # it reads an absent page as a removed one.
            "complete": args.part is None and args.limit is None,
            "force": bool(args.force),
            "from_raw": bool(args.from_raw),
            "limit": args.limit,
            "not_modified": stats.not_modified,
            "pages_fetched": stats.fetched,
            "pages_in_scope": stats.in_scope,
            "pages_parsed": stats.parsed,
            "pages_written": stats.pages_written,
            "part": args.part,
            "raw_written": stats.raw_written,
            "retired": stats.retired,
            "skipped_not_modified": stats.skipped_304,
            "unchanged": stats.unchanged,
            "unreachable": [
                {"page_ref": page_ref, "status": status, "url": url}
                for page_ref, url, status in sorted(stats.unreachable)
            ],
        },
        "source": {
            "manual_root": config.MANUAL_ROOT,
            "seed": config.SITEMAP_SEED_URL,
        },
    }


def _report(args: argparse.Namespace, stats: Stats) -> list[str]:
    mode = "from-raw" if args.from_raw else "crawl"
    if args.dry_run:
        mode += " (dry run, nothing written)"

    lines = [
        f"{mode}: {stats.in_scope} pages in scope",
        f"  fetched          {stats.fetched}",
        f"  not modified     {stats.not_modified} "
        f"({stats.skipped_304} skipped at gate 1)",
        f"  unchanged        {stats.unchanged} (gate 2)",
        f"  parsed           {stats.parsed}",
        f"  pages written    {stats.pages_written}",
        f"  raw written      {stats.raw_written}",
        f"  chunks           {stats.chunks} ({stats.chunks_changed} new or amended)",
    ]
    lines.extend(
        f"    {page_ref}: {changed} of {total} paragraphs amended"
        for page_ref, changed, total in stats.amended
    )
    if stats.unreachable:
        lines.append(f"  UNREACHABLE      {len(stats.unreachable)}")
        lines.extend(
            f"    {page_ref}: {url} returned {status}"
            for page_ref, url, status in sorted(stats.unreachable)
        )
    if stats.retired:
        lines.append(f"  RETIRED          {len(stats.retired)}")
        lines.extend(f"    {ref}" for ref in stats.retired)
    if stats.missing_raw:
        lines.append(f"  no stored source {len(stats.missing_raw)}")
        lines.extend(f"    {ref}" for ref in stats.missing_raw)
    return lines


def run(args: argparse.Namespace, fetcher: Fetcher | None = None) -> int:
    """Crawl, parse, chunk and write. Returns a process exit code.

    `fetcher` is an injection point for tests, which may never touch the
    network; a real run leaves it unset and gets a polite one.
    """
    root = Path(args.snapshot)
    started_at = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    stats = Stats()

    owned: Fetcher | None = None
    try:
        if args.from_raw:
            sitemap = _sitemap_from_raw(root)
        else:
            if fetcher is None:
                fetcher = owned = Fetcher(
                    config.CACHE_DIR, store_validators=not args.dry_run
                )
            fetcher.check_robots()
            sitemap = _sitemap_from_site(fetcher, root)

        scope = page_order(sitemap)
        if args.part is not None:
            scope = [nav for nav in scope if nav.part_id == args.part]
            if not scope:
                known = sorted(
                    {nav.part_id for nav in sitemap.values()}, key=part_sort_key
                )
                raise CrawlError(
                    f"--part {args.part} matched no pages; the inventory holds "
                    f"{', '.join(known)}"
                )
        if args.limit is not None:
            scope = scope[: args.limit]
        stats.in_scope = len(scope)

        for nav in scope:
            _process(nav, sitemap, root, fetcher, args, stats)

        # One rotted nav link is the Manual's business. Every page failing is
        # ours: the site is down, or it has stopped serving us, and writing a
        # manifest that reports a successful run of nothing would be a lie.
        if stats.unreachable and not (stats.parsed or stats.skipped_304):
            raise CrawlError(
                f"none of the {stats.in_scope} pages in scope could be "
                f"fetched (first: {stats.unreachable[0][1]} returned "
                f"{stats.unreachable[0][2]}); the site is not serving us and "
                "no snapshot may be written from that"
            )

        # A filtered or dry run has not seen the whole inventory, and must draw
        # no conclusions about the pages it did not visit.
        complete = args.part is None and args.limit is None and not args.dry_run

        if not args.dry_run:
            write_sitemap(sitemap, Path(root) / "sitemap.json")
            if complete:
                stats.retired = writer.retire(
                    root, {nav.page_ref for nav in scope}, started_at
                )
            writer.write_manifest(
                root, _manifest(args, stats, started_at, _corpus(root, sitemap))
            )
    finally:
        if owned is not None:
            owned.close()

    print("\n".join(_report(args, stats)))
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(build_parser().parse_args(argv))
    except CrawlError as exc:
        print(f"crawl failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
