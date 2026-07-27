"""HTTP with caching, politeness and retries.

Owned by T2. The signatures below are the contract other modules build
against — see ARCHITECTURE.md §Module boundaries — and are fixed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tmm_snapshot import config


@dataclass(frozen=True)
class FetchResult:
    """One HTTP response, reduced to what the pipeline needs.

    `html` is None on 304 and on error; a 304 means the stored raw file is
    still current and gate 1 of the skip logic applies.
    """

    url: str
    status: int
    html: str | None
    etag: str | None
    last_modified: str | None


class Fetcher:
    """Serial, rate-limited, conditional-request HTTP client.

    One request at a time, never fewer than `delay_s` seconds apart, backing
    off on 429 and 5xx. See CLAUDE.md §Courtesy to the source.
    """

    def __init__(
        self,
        cache_dir: Path,
        delay_s: float = config.REQUEST_DELAY_S,
        ua: str = config.USER_AGENT,
    ) -> None:
        raise NotImplementedError("T2")

    def check_robots(self) -> None:
        """Fetch and evaluate robots.txt. Raises if the Manual is disallowed.

        Called on every run. The verdict is never cached across runs.
        """
        raise NotImplementedError("T2")

    def get(self, url: str) -> FetchResult:
        """GET `url`, sending If-None-Match / If-Modified-Since when known."""
        raise NotImplementedError("T2")
