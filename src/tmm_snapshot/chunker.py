"""Cleaned body -> chunks.

Owned by T5. The signatures below are fixed — see ARCHITECTURE.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from bs4 import Tag

from tmm_snapshot.page import PageRecord
from tmm_snapshot.sitemap import NavPage


@dataclass
class Chunk:
    """One retrievable passage — normally the prose under a single heading.

    `chunk_ref` is the address *and* the id. Do not add a sequential id: a
    counter is a citation that breaks silently when a paragraph is inserted
    upstream. See SCHEMA.md §The chunk record.
    """

    chunk_ref: str
    page_ref: str
    text: str
    heading_path: list[str]
    ordinal: int
    content_hash: str
    kind: str
    fragment: dict | None
    provisions: list[dict]
    cases: list[dict]
    internal_refs: list[str]


def chunk_body(body: Tag, page: PageRecord, nav: NavPage) -> list[Chunk]:
    """Cut the cleaned body on h2-h4, never merging across headings.

    Citations are extracted per chunk from the DOM fragment *before* the text
    is flattened — the AustLII hrefs are the high-confidence citation layer and
    text extraction discards them. See SOURCE_NOTES.md §3.
    """
    raise NotImplementedError("T5")
