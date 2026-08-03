"""Constants for the whole pipeline. No logic, no I/O, no side effects.

Everything that another module would otherwise hard-code lives here, so that a
change of rate limit, contact address or snapshot location is a one-line edit
rather than a search-and-replace across the package.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

# --------------------------------------------------------------------------
# The source
# --------------------------------------------------------------------------

BASE_URL: Final[str] = "https://manuals.ipaustralia.gov.au"
MANUAL_ROOT: Final[str] = f"{BASE_URL}/trademark"
ROBOTS_URL: Final[str] = f"{BASE_URL}/robots.txt"

#: Any page renders the complete sidebar nav, so one fetch yields the whole
#: inventory. See SOURCE_NOTES.md §2 — the nav is the *only* reliable source of
#: Part membership, because URL slugs collide across Parts.
SITEMAP_SEED_URL: Final[str] = MANUAL_ROOT


# --------------------------------------------------------------------------
# Courtesy to the source
# --------------------------------------------------------------------------

PROJECT_URL: Final[str] = (
    "https://github.com/Thomas-Amann-IPAustralia/manual-XtrACTor"
)

#: A human-reachable address for whoever runs the crawl, surfaced in the
#: User-Agent so the site operator can complain to a person rather than to a
#: log file. Defaults to the project's issue tracker; override with an email
#: address when running outside CI.
CONTACT: Final[str] = os.environ.get("TMM_CONTACT", f"{PROJECT_URL}/issues")

USER_AGENT: Final[str] = f"tmm-snapshot/0.1.0 (+{PROJECT_URL}; contact: {CONTACT})"

#: Minimum seconds between requests. Serial requests only — never widen this
#: into a connection pool. This is a Commonwealth agency site and we pull all
#: of it.
REQUEST_DELAY_S: Final[float] = 1.0

#: Transient-failure retries (429, 5xx, connection errors) before giving up and
#: raising with the URL in the message.
MAX_RETRIES: Final[int] = 3

#: Exponential backoff: BACKOFF_BASE_S * 2**attempt, capped.
BACKOFF_BASE_S: Final[float] = 2.0
BACKOFF_CAP_S: Final[float] = 60.0

#: Per-request timeout, seconds.
REQUEST_TIMEOUT_S: Final[float] = 30.0


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

#: Repository root. The snapshot lives in the checkout — it *is* the
#: deliverable — so the pipeline is always run from one. Override with
#: TMM_REPO_ROOT if you need to write a snapshot elsewhere (tests do).
REPO_ROOT: Final[Path] = Path(
    os.environ.get("TMM_REPO_ROOT", Path(__file__).resolve().parents[2])
)

SCHEMA_DIR: Final[Path] = REPO_ROOT / "schema"
PAGE_SCHEMA_PATH: Final[Path] = SCHEMA_DIR / "page.schema.json"
CHUNK_SCHEMA_PATH: Final[Path] = SCHEMA_DIR / "chunk.schema.json"

SNAPSHOT_DIR: Final[Path] = REPO_ROOT / "snapshot"
MANIFEST_PATH: Final[Path] = SNAPSHOT_DIR / "manifest.json"
SITEMAP_PATH: Final[Path] = SNAPSHOT_DIR / "sitemap.json"
PAGES_DIR: Final[Path] = SNAPSHOT_DIR / "pages"
RAW_DIR: Final[Path] = SNAPSHOT_DIR / "raw"

#: Pages that vanished from the nav are moved here, never deleted. Old
#: citations must stay resolvable. See ARCHITECTURE.md §Retirement.
RETIRED_DIR: Final[Path] = PAGES_DIR / "_retired"

#: Conditional-request metadata (ETag / Last-Modified). Gitignored: it is
#: cache, not deliverable.
CACHE_DIR: Final[Path] = REPO_ROOT / ".cache"

TESTS_DIR: Final[Path] = REPO_ROOT / "tests"
FIXTURES_DIR: Final[Path] = TESTS_DIR / "fixtures"


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

#: Stamped onto every page record. Bump it when a change to this pipeline
#: alters the output for unchanged input — that is the signal telling you which
#: snapshots need rebuilding from snapshot/raw/ with `crawl --from-raw`.
#:
#: Deliberately not tied to the package version: a packaging bump does not
#: invalidate a snapshot, and a parser fix does.
EXTRACTOR_VERSION: Final[str] = "ingest/0.11.0"

#: Reference prefix for every page_ref and chunk_ref: 'TMM/Part22/1'.
REF_PREFIX: Final[str] = "TMM"

#: BeautifulSoup parser, everywhere. Not a preference — the sidebar nav puts a
#: child <ul> *after* its parent <li> rather than inside it (SOURCE_NOTES.md
#: §2), which is invalid HTML. 'html.parser' preserves that shape as written;
#: lxml and html5lib "correct" it into a different tree and the Part ancestry
#: comes out wrong. Change this and the sitemap silently misattributes pages.
HTML_PARSER: Final[str] = "html.parser"

#: Serialisation settings for every JSON file this pipeline writes. Rule 2 —
#: byte-stability — depends on these being applied uniformly, so pass them
#: rather than restating them.
JSON_DUMP_KWARGS: Final[dict[str, object]] = {
    "sort_keys": True,
    "indent": 2,
    "ensure_ascii": False,
}
