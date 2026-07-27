"""Deterministic offline snapshot of the IP Australia Trade Marks Manual.

The pipeline is a pure function of (live site, previous snapshot) -> new
snapshot. Nothing in this package may call a language model, and every field in
the output must be derivable from source HTML by regex, href parsing or
structural traversal. See CLAUDE.md.
"""

from __future__ import annotations

from tmm_snapshot.config import EXTRACTOR_VERSION

__all__ = ["EXTRACTOR_VERSION", "__version__"]

__version__ = "0.1.0"
