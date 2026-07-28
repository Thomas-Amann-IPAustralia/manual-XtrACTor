"""Chunk markup -> the blocks it was written as.

`chunk.text` is the chunk's words, whitespace-normalised, and joining a
section's paragraphs and list items with single spaces is the correct verbatim
reading of them. It is also unreadable at the length the Manual writes: 18,735
`<p>` and `<li>` elements flatten into 2,151 chunks, 8.7 blocks each, with
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
`p`, `li` nested up to three deep, `ol`, `ul`, `table`, and loose inline
content that Drupal leaves sitting directly in a layout `div`.

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
_TRANSPARENT = frozenset({"div", "section", "article", "aside", "main"})

#: Lists are containers of blocks, not blocks. The list item is the unit a
#: reader sees, and the list is how deep it sits.
_LIST_TAGS = frozenset({"ul", "ol"})

#: Element name to block kind. Anything absent is inline content and is
#: gathered into a 'text' block — that is where a stray `<a>` or `<strong>`
#: left loose in a container ends up, of which the corpus has 1,454.
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
