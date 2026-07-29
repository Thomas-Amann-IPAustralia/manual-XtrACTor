"""Deterministic offline snapshot of the Trade Marks Act and Regulations.

A sibling pipeline to `tmm_snapshot`, not an extension of it. The Manual is
practice and comes off a web CMS; the Act and the Regulations are law and come
off the Federal Register of Legislation as compiled Word documents. Different
source, different fetch, different parse — but the same three rules, the same
byte-stability discipline, and, deliberately, the same reference grammar, so
that a provision the Manual cites is a provision this snapshot holds.

See LEGISLATION_NOTES.md before writing any parser here.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
