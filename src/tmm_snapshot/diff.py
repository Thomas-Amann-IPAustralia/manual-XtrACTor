"""Compare two snapshot states, emit a change report.

Owned by T8. Output is the body of the pull request a scheduled crawl opens,
and that pull request is the audit trail: it is where a human decides whether
an amendment was substantive practice change or a hyperlink tidy-up, using the
Manual's own amendment_note as the clue.

Structural changes are called out loudly. A Part's page count moving usually
means a restructure, not an edit. See SOURCE_NOTES.md §10.

ARCHITECTURE.md does not fix a signature for this module, so the placeholder
below is a suggestion and T8 may replace it.
"""

from __future__ import annotations

from pathlib import Path


def render_report(before: Path, after: Path) -> str:
    """Markdown change report between two snapshot states."""
    raise NotImplementedError("T8")
