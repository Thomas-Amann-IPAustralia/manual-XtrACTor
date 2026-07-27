"""Deterministic serialisation to snapshot/.

Owned by T7. The signatures below are fixed — see ARCHITECTURE.md.

This module is where rule 2 is enforced. Every writer here must compare against
the bytes already on disk and skip the write when they are identical: do not
rely on git to notice a no-op change, rely on git to notice *nothing*, because
the file was never touched.
"""

from __future__ import annotations

from pathlib import Path

from tmm_snapshot.chunker import Chunk
from tmm_snapshot.page import PageRecord


def write_page(page: PageRecord, chunks: list[Chunk], root: Path) -> bool:
    """Write snapshot/pages/<Part>/<page_ref>.json. True if bytes changed."""
    raise NotImplementedError("T7")


def write_raw(page_ref: str, html: str, root: Path) -> bool:
    """Write snapshot/raw/<Part>/<page_ref>.html verbatim. True if changed.

    Unmodified and uncompressed: this is the audit artefact and the input to
    every re-parse. A gzipped file diffs as a binary blob.
    """
    raise NotImplementedError("T7")


def write_manifest(root: Path, stats: dict) -> None:
    """Write snapshot/manifest.json — the only file that changes every run."""
    raise NotImplementedError("T7")
