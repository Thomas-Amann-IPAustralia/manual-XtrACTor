"""Chunk markup -> the blocks it was written as.

`chunk.text` is the chunk's words, whitespace-normalised, and joining a
section's paragraphs and list items with single spaces is the correct verbatim
reading of them. It is also unreadable at the length the Manual writes: 12,291
`<p>` and `<li>` elements flatten into 2,460 chunks, five blocks each, with
nothing left to say where one ended. Part 61.3's ten-item list of documents
exempt from public inspection arrives as a single run-on line, and the source's
own semicolons give out halfway down it, so not even a reader can recover the
item boundaries.

This module records the boundaries the markup already asserts. It is the same
argument as `tables.py`: the flattened text is right and useless, so keep it and
record the grid beside it.

Every field here comes from a tag name or the shape of the tree — no pattern
matching over the words, nothing inferred about meaning. The kinds are the
element types the corpus actually contains, counted rather than anticipated:
`p`, `li` nested up to three deep, `ol`, `ul`, `table`, `img`, and the loose
inline content Drupal leaves sitting directly in a layout `div`. Measured at
`ingest/0.8.0`: 7,632 paragraphs, 4,659 list items, 121 tables, 93 images, 12
headings and 4 loose runs, over 2,460 chunks.

`text` is unchanged and remains the thing that gets quoted. Joining the blocks'
text reproduces it exactly, which `tests/test_blocks.py` asserts over the whole
fixture set — a block list that does not add back up to the chunk is a block
list that has dropped a sentence.
"""

from __future__ import annotations

import copy

from bs4 import BeautifulSoup, NavigableString, Tag

from tmm_snapshot import config
from tmm_snapshot.page import flatten_text, normalise_text

#: Walked through rather than recorded. The same set `chunker._units` walks,
#: for the same reason: Drupal's `div.zone > div.section12 > div` scaffolding
#: is layout, and a layout div is not a block a reader sees.
#:
#: `figure` is here and deliberately *not* in `chunker._CONTAINER_TAGS`, and the
#: asymmetry is the point. The CMS wraps every table it writes in
#: `<figure class="table canvasRteResponsiveTable">`. To the chunker that
#: figure is one unit, which is what stops a table being split across a
#: fragment boundary. To this module it is scaffolding: leaving it opaque made
#: `flatten_text` swallow the whole grid into a single `text` block, so 106 of
#: the corpus's 121 tables were recorded as run-on prose and only 18 as tables.
#: See SOURCE_NOTES.md §23.
_TRANSPARENT = frozenset({"div", "section", "article", "aside", "main", "figure"})

#: Lists are containers of blocks, not blocks. The list item is the unit a
#: reader sees, and the list is how deep it sits.
_LIST_TAGS = frozenset({"ul", "ol"})

#: Element name to block kind. Anything absent is inline content and is
#: gathered into a 'text' block — that is where a stray `<a>` or `<strong>`
#: left loose in a container ends up. The corpus has four, and the number is
#: worth keeping current: it was 1,454 before §23 made `figure` transparent,
#: and nearly all of those were tables being recorded as run-on prose.
_KINDS: dict[str, str] = {
    "p": "paragraph",
    "li": "list_item",
    "table": "table",
    "h1": "heading",
    "h2": "heading",
    "h3": "heading",
    "h4": "heading",
    "h5": "heading",
    "h6": "heading",
}


def _own_text(item: Tag) -> str:
    """A list item's own words, without the nested list hanging off it.

    Part 61.3 writes 'a document:' with two sub-items under it. Reading the
    whole `<li>` would put the sub-items' words in the parent as well as in
    themselves, and the blocks would then add up to more than the chunk.
    """
    holder = BeautifulSoup("<li></li>", config.HTML_PARSER).li
    assert holder is not None
    for child in item.children:
        if isinstance(child, Tag) and child.name in _LIST_TAGS:
            continue
        holder.append(copy.copy(child))
    return flatten_text(holder)


def _image(child: Tag) -> dict:
    """An image, recorded where it sits and nowhere near the words.

    The only block with no `text`, because an `<img>` contributes no words and
    a block carrying `""` would put a stray space into the join that
    reconstructs the chunk. Its absence is what the join skips over, so the
    contract in `validate._block_failures` still holds exactly.

    The bytes are not in the snapshot and the Manual writes no `alt`, so this
    says *an image sat here* and no more. That is strictly more than the page
    record can say: `PageRecord.images` establishes that a page has images,
    and only this establishes where in the prose they fell. See
    SOURCE_NOTES.md §24.
    """
    block: dict = {"kind": "image"}
    src = child.get("src")
    if isinstance(src, str) and src.strip():
        block["src"] = src.strip()
    alt = child.get("alt")
    if isinstance(alt, str) and alt.strip():
        block["alt"] = alt.strip()
    return block


def extract_blocks(fragment: Tag) -> list[dict]:
    """The blocks of one chunk, in document order.

    `depth` rides on a list item and says how many lists enclose it, starting
    at 1. It is the only nesting the corpus has — 4,569 items at depth 1, 87 at
    2, four at 3 — and without it a sub-item reads as a sibling of the item it
    qualifies.
    """
    found: list[dict] = []

    def visit(node: Tag, depth: int) -> None:
        for child in node.children:
            if isinstance(child, NavigableString):
                if text := normalise_text(str(child)):
                    found.append({"kind": "text", "text": text})
                continue
            if not isinstance(child, Tag):
                continue

            if child.name == "img":
                found.append(_image(child))
                continue
            if child.name in _LIST_TAGS:
                visit(child, depth + 1)
                continue
            if child.name in _TRANSPARENT:
                visit(child, depth)
                continue

            kind = _KINDS.get(child.name, "text")
            if kind == "list_item":
                # The item's own words first, then any list hanging off it —
                # never the item's other children, whose words `_own_text` has
                # already taken. Walking them again would put the same sentence
                # in two blocks.
                if text := _own_text(child):
                    found.append(
                        {"kind": kind, "text": text, "depth": max(depth, 1)}
                    )
                for nested in child.children:
                    if isinstance(nested, Tag) and nested.name in _LIST_TAGS:
                        visit(nested, depth + 1)
                continue

            if text := flatten_text(child):
                found.append({"kind": kind, "text": text})

    visit(fragment, 0)
    return found
