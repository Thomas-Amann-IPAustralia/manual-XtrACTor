"""Orchestration and CLI entry point.

Owned by T7. Wires robots check -> fetch -> sitemap -> per page (fetch, parse,
chunk, extract, write), applying the three skip gates from ARCHITECTURE.md.

The argument parser is settled and is what `--help` documents; `run` is the
part T7 fills in.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from tmm_snapshot import config

#: Matches the part_id form the schema requires: Part22, Part19A, Part32B.
_PART_ID = re.compile(r"^Part[0-9]{1,3}[A-Z]?$")


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


def run(args: argparse.Namespace) -> int:
    raise NotImplementedError("T7")


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
