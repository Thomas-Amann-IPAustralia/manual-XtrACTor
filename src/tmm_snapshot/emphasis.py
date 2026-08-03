"""Chunk markup -> the emphasis in it, and where it sits in the words.

The Manual sets 5,670 stretches of its prose in italic, bold, underline or
superscript, across 428 of its 500 pages, and until this module every one of
them reached the snapshot as undifferentiated text. This is the same gap
`links.py` closed for anchors, and the argument is the same one: flattening to
`chunk.text` is the correct verbatim reading of the words and destroys
everything the markup asserted around them, so keep the words and record the
assertions beside them.

The legislation half has recorded exactly this since `legislation/0.1.0` —
`provision.units[].emphasis`, with `SCHEMA.md` arguing for it on the grounds
that the leading bold-italic run of a `Definition` is the defined term and that
legislation italicises the names of other instruments. Both facts have Manual
equivalents, and one of them is load-bearing:

- **The Manual italicises case names.** 437 of the corpus's 522 case-citation
  positions are immediately preceded by an italic run, against the 18 that
  `exports/cases.csv` can currently name from a jade.io anchor. Reading `<i>`
  is not a different kind of act from reading `<a href>` — both are the
  authors marking a span, and neither is an inference about what it means.
- **It italicises instrument titles**, 695 times, which is where the
  `certainty: "explicit"` evidence in `citations.py` is written down in markup
  rather than in prose.

Nothing here interprets a span. That a name sits beside a citation is an
adjacency a consumer can walk; asserting the two belong to each other is a
merge, and `SCHEMA.md` puts merges downstream. This module records what the
Manual set and where.

`start` and `end` are offsets into `chunk.text`, so `text[start:end]` is the
element's own words — the same contract `links` carries, checked over the whole
snapshot by `validate._emphasis_failures` rather than in a test alone, because
an offset drifted by one emphasises the wrong words while staying well-formed.
"""

from __future__ import annotations

from bs4 import Tag

from tmm_snapshot.page import flatten_spans

#: The elements the Manual actually uses, counted rather than anticipated:
#: `<i>` 2,670, `<strong>` 2,288, `<u>` 533, `<em>` 130, `<sup>` 26, `<b>` 23.
#:
#: `<sup>` earns its place twice over. `SOURCE_NOTES.md` §26 establishes that a
#: superscript in a heading is a footnote marker and never a heading number,
#: and the chunker acts on that — but only in its control flow, so the fact was
#: nowhere in the output. The 26 body-side markers are now visible to a reader.
#:
#: `<u>` is here because the Manual uses it, not because underlining means
#: anything in particular: it is usually laid over an italic instrument title,
#: and on Part 10.4 it marks the placeholder slots of a form template
#: (`<language>`, `<TRANSLATION>`). Recording it and declining to say which is
#: exactly the split this module is for.
EMPHASIS_TAGS = frozenset({"b", "em", "i", "strong", "sup", "u"})


def extract_emphasis(fragment: Tag) -> list[dict]:
    """The emphasised stretches of one chunk, in document order.

    Not deduplicated and not sorted, for the reasons `links` is neither:
    document order is the Manual's own order and is already stable, and two
    spans of the same words are two spans.

    **One record per element, never a merged weight.** 1,271 of the corpus's
    spans are co-extensive with another because HTML nests where Word does not:
    `<u><i>Trade Marks Act 1995</i></u>` is one stretch of words carrying two
    assertions, and the legislation side's `weight: "bold-italic"` spelling
    exists only because a Word run carries both properties on the one element.
    Collapsing nested elements into a synthetic weight here would be inventing
    a thing the source does not have; a consumer wanting the intersection can
    take it, and cannot un-take it if this module decides first.

    Nor is a nested identical element collapsed. The CMS emits
    `<i><i>ordinary signification</i></i>` (SOURCE_NOTES.md §4), which is 193 of
    the corpus's spans arriving as two records sharing a kind and their offsets.
    Collapsing them asserts that `<i><i>x</i></i>` and `<i>x</i>` are one
    assertion — true of how they render, and still a normalisation. A consumer
    counting spans deduplicates on `(kind, start, end)`; this module cannot
    un-collapse what it collapsed.

    Empty spans are dropped, which is the one place this differs from `links`.
    An anchor with no words still records a place the Manual put a link — the
    empty `<a>` that `TMA1995/s42` on Part 32A.1 comes from is the reason that
    field keeps them. An `<i>` around nothing asserts nothing about any words,
    and the corpus's 128 of them are CMS residue.
    """
    text, spans = flatten_spans(fragment, EMPHASIS_TAGS)

    return [
        {
            "kind": tag.name,
            "text": text[start:end],
            "start": start,
            "end": end,
        }
        for tag, start, end in spans
        if end > start
    ]
