"""The shape `chunk.text` was flattened from.

`blocks` exists because the flattened reading is correct and unreadable: a
ten-item list of statutory exceptions and a single paragraph are the same
string once the markup is gone. The tests that matter most here are not the
ones about kinds — they are the two that say the blocks add back up to the
text, because a block list that has quietly dropped a sentence is worse than
no block list at all.
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from tmm_snapshot import config
from tmm_snapshot.blocks import extract_blocks
from tmm_snapshot.chunker import chunk_body
from tmm_snapshot.page import flatten_text, parse_page, resolve_nav

from conftest import PAGE_SLUGS, page_html, page_url


def fragment(html: str):
    return BeautifulSoup(f"<div>{html}</div>", config.HTML_PARSER).div


def blocks(html: str) -> list[dict]:
    return extract_blocks(fragment(html))


# -- the invariant --------------------------------------------------------


def test_joining_the_blocks_reproduces_the_text():
    body = fragment(
        "<p>An opening paragraph.</p><ul><li>First item.</li>"
        "<li>Second item.</li></ul><p>A closing paragraph.</p>"
    )
    found = extract_blocks(body)

    assert " ".join(block["text"] for block in found) == flatten_text(body)


@pytest.mark.parametrize("name", sorted(PAGE_SLUGS))
def test_every_chunk_of_every_real_page_adds_back_up(name, sitemap):
    """Over every saved page, not a sample. This is the check that a parser
    change cannot quietly lose a paragraph."""
    nav = resolve_nav(page_url(name), sitemap)
    record, body = parse_page(page_html(name), nav)

    for chunk in chunk_body(body, record, nav, sitemap):
        # An image block carries no `text` and contributes no words — the same
        # blocks the join in `validate._block_failures` steps over.
        joined = " ".join(block["text"] for block in chunk.blocks if "text" in block)
        assert joined == chunk.text, chunk.chunk_ref


# -- kinds ----------------------------------------------------------------


def test_a_paragraph_and_a_list_item_are_told_apart():
    found = blocks("<p>Prose.</p><ul><li>An item.</li></ul>")

    assert [block["kind"] for block in found] == ["paragraph", "list_item"]


def test_a_layout_div_is_walked_through_not_recorded():
    """Drupal wraps the prose several `div.zone` deep. A layout div is not a
    block a reader sees — the same rule `chunker._units` applies."""
    found = blocks('<div class="zone"><div class="section12"><p>Prose.</p></div></div>')

    assert found == [{"kind": "paragraph", "text": "Prose."}]


def test_loose_inline_content_becomes_a_text_block():
    """The CMS leaves a stray `<a>` or `<strong>` sitting directly in a
    container. 108 blocks in the corpus are this."""
    found = blocks('<a href="/trademark/22.1">A loose link.</a>')

    assert found == [{"kind": "text", "text": "A loose link."}]


def test_a_table_is_one_block():
    """Its grid is `chunk.tables`; here it is one thing in the running order."""
    found = blocks("<table><tr><td>Cell one</td><td>Cell two</td></tr></table>")

    assert [block["kind"] for block in found] == ["table"]


def test_an_h5_inside_a_chunk_is_a_heading_block():
    """`<h2>`-`<h4>` are chunk boundaries and never reach here; `<h5>` and
    `<h6>` fall inside the chunk they sit in."""
    found = blocks("<h5>A sub-sub-heading</h5><p>Prose.</p>")

    assert [block["kind"] for block in found] == ["heading", "paragraph"]


# -- nesting --------------------------------------------------------------


def test_a_list_item_carries_its_depth():
    found = blocks("<ul><li>An item.</li></ul>")

    assert found == [{"kind": "list_item", "text": "An item.", "depth": 1}]


def test_a_nested_item_is_deeper_than_its_parent():
    """Part 61.3 writes 'a document:' with two sub-items under it. Without the
    depth a sub-item reads as a sibling of the item it qualifies."""
    found = blocks(
        "<ul><li>a document:<ul><li>whose production the Registrar has "
        "required; and</li><li>that the Registrar is satisfied should not be "
        "made available</li></ul></li></ul>"
    )

    assert [(block["text"][:11], block["depth"]) for block in found] == [
        ("a document:", 1),
        ("whose produ", 2),
        ("that the Re", 2),
    ]


def test_a_parent_item_does_not_repeat_its_children():
    """Reading the whole `<li>` would put the sub-items' words in the parent as
    well as in themselves, and the blocks would add up to more than the text."""
    found = blocks("<ul><li>Parent.<ul><li>Child.</li></ul></li></ul>")

    assert found[0]["text"] == "Parent."


def test_an_empty_element_contributes_no_block():
    assert blocks("<p></p><p>   </p><p>Prose.</p>") == [
        {"kind": "paragraph", "text": "Prose."}
    ]


# -- the CMS's own wrappers ------------------------------------------------


def test_a_table_inside_a_figure_is_a_table_block():
    """CKEditor wraps every table the Manual writes in
    `<figure class="table canvasRteResponsiveTable">`. While that figure was
    opaque, `flatten_text` swallowed the whole grid into one 'text' block:
    106 of the corpus's 121 tables were recorded as run-on prose."""
    found = blocks(
        '<figure class="table canvasRteResponsiveTable">'
        "<table><tbody><tr><td>Owner</td><td>Name</td></tr></tbody></table>"
        "</figure>"
    )

    assert [block["kind"] for block in found] == ["table"]


def test_a_figure_is_transparent_but_a_table_is_still_one_unit():
    """The asymmetry with `chunker._CONTAINER_TAGS` is deliberate: to the
    chunker the figure is one unit, which is what stops a table being split
    across a fragment boundary."""
    found = blocks(
        '<p>Before.</p><figure class="table"><table><tbody>'
        "<tr><td>A cell.</td></tr></tbody></table></figure><p>After.</p>"
    )

    assert [block["kind"] for block in found] == [
        "paragraph",
        "table",
        "paragraph",
    ]


# -- an image ---------------------------------------------------------------


def test_an_image_is_recorded_where_it_sits():
    """169 images sit loose in layout divs. `PageRecord.images` says a page
    has them; only this says where in the prose they fell."""
    found = blocks(
        '<p>Before.</p><img src="/sites/default/files/flowchart.png"><p>After.</p>'
    )

    assert [block["kind"] for block in found] == ["paragraph", "image", "paragraph"]
    assert found[1]["src"] == "/sites/default/files/flowchart.png"


def test_an_image_block_carries_no_text():
    """The only block without one. A block carrying '' would put a stray
    space into the join that reconstructs the chunk."""
    found = blocks('<img src="/sites/default/files/flowchart.png">')

    assert "text" not in found[0]


def test_an_image_does_not_disturb_the_join():
    body = fragment('<p>Before.</p><img src="/a.png"><p>After.</p>')
    found = extract_blocks(body)

    joined = " ".join(block["text"] for block in found if "text" in block)
    assert joined == flatten_text(body) == "Before. After."


def test_alt_text_is_recorded_only_where_the_manual_wrote_one():
    """Across 169 images it never has, and nothing here invents one."""
    with_alt = blocks('<img src="/a.png" alt="A flowchart.">')
    without = blocks('<img src="/a.png">')

    assert with_alt[0]["alt"] == "A flowchart."
    assert "alt" not in without[0]
