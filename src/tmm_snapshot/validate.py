"""Validate snapshot/ against schema/.

Owned by T10. Independent of the rest of the pipeline: implementable from
schema/ and a fixture snapshot alone.

Beyond schema validation this module asserts the invariants a schema cannot
express — every chunk.page_ref resolving to the page in its own file, globally
unique chunk_refs, internal_refs targets existing in the snapshot, ordinals
contiguous from 1.

Reports every failure with file and JSON path rather than stopping at the
first, and exits non-zero if there were any.

ARCHITECTURE.md does not fix signatures for this module beyond the CLI entry
point, so the placeholders below are suggestions and T10 may replace them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tmm_snapshot import config


def validate_snapshot(root: Path) -> list[str]:
    """Return a list of human-readable failures. Empty means valid."""
    raise NotImplementedError("T10")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tmm_snapshot.validate",
        description=(
            "Validate the snapshot against schema/ and the invariants a "
            "schema cannot express. Exits non-zero on any failure."
        ),
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=config.SNAPSHOT_DIR,
        metavar="DIR",
        help="snapshot directory to validate (default: %(default)s)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    failures = validate_snapshot(args.snapshot)
    for failure in failures:
        print(failure, file=sys.stderr)
    if failures:
        print(f"{len(failures)} validation failure(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
