"""Constants for the legislation pipeline. No logic, no I/O, no side effects.

Mirrors `tmm_snapshot.config` in intent: everything another module would
otherwise hard-code lives here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from tmm_snapshot import config as tmm_config

# --------------------------------------------------------------------------
# The source
# --------------------------------------------------------------------------

#: The Federal Register of Legislation's public OData API. No auth for reads.
API_BASE: Final[str] = "https://api.prod.legislation.gov.au"

#: The public site. Used only for the document fallback in `api.download` —
#: never for document *text*, which the site renders client-side and which a
#: scrape therefore reduces to about 5% nav chrome. LEGISLATION_NOTES.md §1.
SITE_BASE: Final[str] = "https://www.legislation.gov.au"

#: `www.legislation.gov.au/robots.txt` asks for `Crawl-delay: 10`. The API host
#: serves no robots.txt at all (404), so nothing is asserted about it and the
#: general courtesy delay applies. We honour the stricter number on the host
#: that asked for it rather than averaging the two.
SITE_REQUEST_DELAY_S: Final[float] = 10.0
API_REQUEST_DELAY_S: Final[float] = 1.0

#: Paths robots.txt disallows on the public site. Checked on every run, never
#: cached across runs — same rule as the Manual crawler.
SITE_ROBOTS_URL: Final[str] = f"{SITE_BASE}/robots.txt"


# --------------------------------------------------------------------------
# The instruments
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Instrument:
    """One law this pipeline snapshots.

    `code` is the identifier the *Manual's* citation layer already emits:
    `tmm_snapshot.citations` writes `TMA1995/s41` and `TMR1995/r3A.3` today,
    and those strings are chosen here to be the same strings, so that a
    provision edge on a Manual chunk is a foreign key into this snapshot with
    no transformation in between. Changing a code breaks that join silently —
    it is a decision to raise, not to make.

    `title_id` is the Federal Register's permanent identifier for the law, as
    distinct from `registerId`, which identifies one compiled version of it and
    is the amendment signal. LEGISLATION_NOTES.md §2.

    `symbol` is 's' for a law divided into sections and 'r' for one divided
    into regulations. It decides the reference grammar and must agree with
    `tmm_snapshot.citations.instrument_kind`, which is asserted in the tests.
    """

    code: str
    title_id: str
    name: str
    symbol: str


#: The instruments in scope, keyed by code.
#:
#: Seeded with the two principal trade marks instruments. Adding another is one
#: entry here plus a fixture — the pipeline has nothing else keyed on which law
#: it is reading. The obvious candidates, none of which is in scope today: the
#: Trade Marks Act 1955 (which the Manual's Part 22.1 anaphora case turns on,
#: SOURCE_NOTES.md §4), the Acts Interpretation Act 1901, and the Trade Marks
#: Amendment Acts. Each is a scope decision, so each is a raise.
INSTRUMENTS: Final[dict[str, Instrument]] = {
    "TMA1995": Instrument(
        code="TMA1995",
        title_id="C2004A04969",
        name="Trade Marks Act 1995",
        symbol="s",
    ),
    "TMR1995": Instrument(
        code="TMR1995",
        title_id="F1996B00084",
        name="Trade Marks Regulations 1995",
        symbol="r",
    ),
}


# --------------------------------------------------------------------------
# Courtesy to the source
# --------------------------------------------------------------------------

#: Reuses the Manual crawler's contact address: same operator, same obligation
#: to be reachable. The token differs so the two pipelines are separable in the
#: Register's logs.
USER_AGENT: Final[str] = (
    f"tmm-legislation-snapshot/{'0.1.0'} "
    f"(+{tmm_config.PROJECT_URL}; contact: {tmm_config.CONTACT})"
)

MAX_RETRIES: Final[int] = 3
BACKOFF_BASE_S: Final[float] = 2.0
BACKOFF_CAP_S: Final[float] = 60.0

#: Documents run to hundreds of kilobytes and the Register is not fast.
REQUEST_TIMEOUT_S: Final[float] = 30.0
DOCUMENT_TIMEOUT_S: Final[float] = 180.0


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

REPO_ROOT: Final[Path] = tmm_config.REPO_ROOT

#: A sibling of `snapshot/pages/`, not a child of it. `tmm_snapshot.validate`
#: walks `snapshot/pages/` and would otherwise try to read these files against
#: the Manual's schema.
LEGISLATION_DIR: Final[Path] = tmm_config.SNAPSHOT_DIR / "legislation"

MANIFEST_PATH: Final[Path] = LEGISLATION_DIR / "manifest.json"

INSTRUMENT_SCHEMA_PATH: Final[Path] = tmm_config.SCHEMA_DIR / "instrument.schema.json"
PROVISION_SCHEMA_PATH: Final[Path] = tmm_config.SCHEMA_DIR / "provision.schema.json"

FIXTURES_DIR: Final[Path] = tmm_config.FIXTURES_DIR / "legislation"


def instrument_dir(code: str, root: Path | None = None) -> Path:
    return (root or LEGISLATION_DIR) / code


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

#: Stamped onto every provision record. Bump it when a change here alters the
#: output for unchanged input — that is the signal saying which snapshots need
#: rebuilding with `crawl --from-raw --force`.
#:
#: Separate from `tmm_snapshot`'s version on purpose: a chunker fix does not
#: invalidate a compiled Act, and a unit-parser fix does not invalidate the
#: Manual.
EXTRACTOR_VERSION: Final[str] = "legislation/0.2.0"

#: Serialisation settings, taken from the Manual pipeline rather than restated,
#: because rule 2 depends on every file this repository writes being written
#: the same way.
JSON_DUMP_KWARGS: Final[dict[str, object]] = tmm_config.JSON_DUMP_KWARGS

#: Override to write a snapshot somewhere else. Tests do.
def snapshot_root() -> Path:
    override = os.environ.get("FRL_SNAPSHOT_ROOT")
    return Path(override) if override else LEGISLATION_DIR
