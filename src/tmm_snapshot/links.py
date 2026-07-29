"""Chunk markup -> the hyperlinks in it, and where they sit in the words.

The Manual links constantly: 2,223 anchors across 424 of its 502 pages, to
AustLII, to the Federal Register of Legislation, to TimeBase, to WIPO, and to
527 places inside the Manual itself. Until this module they reached the
snapshot only where something else happened to want them. Of the 2,218 that
sit inside a chunk, 946 became a `provisions` edge because their href is an
AustLII provision and 480 became an `internal_ref` because their href is a page
in the nav — and both of those record what the link *means*, deduplicated,
sorted, with the href and the position thrown away. **The remaining 792 left no
trace at all.**

Part 61.2's link on *section 217A* is one of the 792: it points at TimeBase
rather than AustLII, so the provision layer never read it, and the passage
records that citation as `certainty: "default"` — a guess from the prose that
happens to agree with a hyperlink the snapshot was not keeping.

Five anchors reach no chunk, and they are the field's one gap: an `<a>` inside
an `<h2>`–`<h4>` that opens subsections is inside a heading, and a heading's
words reach the snapshot as a `heading_path` string with no structure to hang
an offset on. Two on Part 2.1 and three on Part 31.4. See SOURCE_NOTES.md §29.

The same argument as `tables.py` and `blocks.py`, then, applied to the anchors:
the flattened text is the correct reading of the words and destroys everything
the markup asserted around them. So keep the words and record the assertions
beside them.

`href` is verbatim. `start` and `end` are offsets into `chunk.text`, so
`text[start:end]` is the anchor's own words — which is the whole point, and
what lets a reader put the link back where the Manual had it. Nothing here
interprets a target: resolving an href to a page is `citations.py`'s job and it
does it with the sitemap, which this module deliberately does not take.
"""

from __future__ import annotations

from bs4 import Tag

from tmm_snapshot.page import flatten_spans

#: `<a>` and nothing else. An `<a>` with no `href` is an anchor point rather
#: than a link — the same test `citations.extract_internal_refs` applies — and
#: `<area>` never appears in the corpus.
_ANCHORS = frozenset({"a"})


def extract_links(fragment: Tag) -> list[dict]:
    """The hyperlinks of one chunk, in document order.

    Not deduplicated, unlike `internal_refs`: two links to one target are two
    links. That field answers *what does this passage point at*, and a set is
    the right shape for it; this one answers *where in the passage*, and 91 of
    the corpus's anchors set the same words as another anchor in the same
    chunk, so a set would lose the second of every pair — and matching a link
    to its words later, rather than storing where they are, would be a guess
    between the two.

    Document order is the stable order here — the order the Manual set them in
    — so unlike `provisions` this is not re-sorted on the way out. Inserting a
    paragraph moves the offsets of everything after it, but that paragraph has
    already changed the chunk's text and its hash, so nothing is destabilised
    that was not already rewritten.
    """
    text, spans = flatten_spans(fragment, _ANCHORS)

    found: list[dict] = []
    for anchor, start, end in spans:
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        found.append(
            {
                "href": href,
                "text": text[start:end],
                "start": start,
                "end": end,
            }
        )
    return found
