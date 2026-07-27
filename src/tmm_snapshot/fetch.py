"""HTTP with caching, politeness and retries.

Owned by T2. The signatures below are the contract other modules build
against — see ARCHITECTURE.md §Module boundaries — and are fixed.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from urllib.parse import urlsplit

import httpx

from tmm_snapshot import config


class FetchError(Exception):
    """A request failed and retrying did not help. Carries the URL."""


class RobotsDisallowed(Exception):
    """robots.txt forbids the Manual to our User-Agent. Stop the run."""


#: Statuses worth retrying: rate limiting and server-side faults. Everything
#: else is the site telling us something true — a 404 means the page is gone,
#: which is a fact the caller needs — and retrying it would only be rude.
_TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})


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

    The delay is measured from the *end* of one request to the start of the
    next, so a slow response lengthens the gap rather than being absorbed by
    it.
    """

    def __init__(
        self,
        cache_dir: Path,
        delay_s: float = config.REQUEST_DELAY_S,
        ua: str = config.USER_AGENT,
        *,
        transport: httpx.BaseTransport | None = None,
        store_validators: bool = True,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.delay_s = delay_s
        self.ua = ua
        #: Whether a 200 records its validators for the next run. False for a
        #: dry run, which must leave the cache exactly as it found it — see
        #: `_store_validators`.
        self.store_validators = store_validators
        self._last_request_ended: float | None = None
        self._client = httpx.Client(
            headers={"User-Agent": ua},
            timeout=config.REQUEST_TIMEOUT_S,
            follow_redirects=True,
            transport=transport,
        )

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- politeness --------------------------------------------------------

    def _wait_turn(self) -> None:
        """Block until `delay_s` has elapsed since the last request ended."""
        if self._last_request_ended is None:
            return
        remaining = self.delay_s - (time.monotonic() - self._last_request_ended)
        if remaining > 0:
            time.sleep(remaining)

    def _backoff(self, attempt: int, retry_after: str | None = None) -> None:
        """Sleep before retry number `attempt` (0-based). Honours Retry-After."""
        wait = min(config.BACKOFF_BASE_S * (2**attempt), config.BACKOFF_CAP_S)
        if retry_after is not None:
            try:
                # Only the delta-seconds form. An HTTP-date would need us to
                # trust the server's clock against ours, and our own backoff
                # is already a safe answer.
                wait = max(wait, min(float(retry_after), config.BACKOFF_CAP_S))
            except ValueError:
                pass
        time.sleep(wait)

    def check_robots(self) -> None:
        """Fetch and evaluate robots.txt. Raises if the Manual is disallowed.

        Called on every run. The verdict is never cached across runs: a site
        that starts disallowing us must be able to stop us on the next run,
        not on our next release.
        """
        response = self._request(config.ROBOTS_URL)
        if response.status_code != 200:
            raise FetchError(
                f"could not read robots.txt "
                f"({response.status_code}): {config.ROBOTS_URL}"
            )

        parser = urllib.robotparser.RobotFileParser()
        parser.parse(response.text.splitlines())

        if not parser.can_fetch(self.ua, config.MANUAL_ROOT):
            raise RobotsDisallowed(
                f"robots.txt disallows {config.MANUAL_ROOT} for {self.ua!r}"
            )

        # If the site asks for a wider gap than ours, it gets it.
        crawl_delay = parser.crawl_delay(self.ua)
        if crawl_delay is not None and float(crawl_delay) > self.delay_s:
            self.delay_s = float(crawl_delay)

    # -- conditional-request cache ----------------------------------------

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def _cached_validators(self, url: str) -> dict[str, str]:
        """Stored validators for `url`, as one conditional header.

        **One, not both, and Last-Modified for preference.** The Manual is
        served by Apache with mod_deflate, which appends `-gzip` to the ETag it
        sends but compares incoming `If-None-Match` against the *unsuffixed*
        value. Echoing back the ETag the server itself gave us therefore never
        matches, and always answers 200. Measured 27 July 2026:

            If-None-Match: "1785133603-gzip"              -> 200
            If-None-Match: "1785133603"                   -> 304
            If-Modified-Since: <date>                     -> 304
            If-Modified-Since: <date> + If-None-Match     -> 200

        That last line is the trap, and it is why this sends one header rather
        than two: RFC 9110 gives If-None-Match precedence and has the server
        ignore the date entirely when both are present. Sending both is not
        belt and braces — the broken ETag silently disables the validator that
        works, and with it gate 1 for the whole corpus.

        The ETag is kept as the fallback for a URL that carries no
        Last-Modified, and is sent verbatim. Stripping `-gzip` to make it match
        would be guessing at the server's bug from the outside, and would break
        the day the server stopped having it.
        """
        try:
            stored = json.loads(self._cache_path(url).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

        if last_modified := stored.get("last_modified"):
            return {"If-Modified-Since": last_modified}
        if etag := stored.get("etag"):
            return {"If-None-Match": etag}
        return {}

    def _store_validators(
        self, url: str, etag: str | None, last_modified: str | None
    ) -> None:
        """Record this URL's validators so the next run can send them.

        Skipped entirely on a dry run. The cache and the snapshot are one
        state, not two: a stored validator is a claim that `snapshot/raw/`
        holds the body that goes with it. A dry run fetches but writes no raw,
        so persisting validators here would leave the cache asserting bodies
        that were never saved — and the next real crawl gets a 304 with
        nothing to fall back on and dies. CLAUDE.md's own pre-commit checklist
        ends with a dry run, so this is the ordinary path, not a corner case.
        """
        if not self.store_validators:
            return
        if etag is None and last_modified is None:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path(url).write_text(
            json.dumps(
                {"url": url, "etag": etag, "last_modified": last_modified},
                **config.JSON_DUMP_KWARGS,  # type: ignore[arg-type]
            )
            + "\n",
            encoding="utf-8",
        )

    # -- requests ----------------------------------------------------------

    def _request(
        self, url: str, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        """One rate-limited request, retried on transient failure.

        Raises FetchError with the URL in the message once the retries are
        spent. Returns the response for every non-transient status.
        """
        retry_after: str | None = None
        response: httpx.Response | None = None

        for attempt in range(config.MAX_RETRIES + 1):
            if attempt:
                self._backoff(attempt - 1, retry_after)
            self._wait_turn()
            try:
                response = self._client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                self._last_request_ended = time.monotonic()
                retry_after = None
                if attempt == config.MAX_RETRIES:
                    raise FetchError(
                        f"{type(exc).__name__} fetching {url}: {exc}"
                    ) from exc
                continue

            self._last_request_ended = time.monotonic()
            if response.status_code not in _TRANSIENT_STATUSES:
                return response
            retry_after = response.headers.get("Retry-After")

        assert response is not None  # the loop either returns or sets this
        raise FetchError(
            f"giving up on {url} after {config.MAX_RETRIES + 1} attempts "
            f"(last status {response.status_code})"
        )

    def get(self, url: str) -> FetchResult:
        """GET `url`, sending If-None-Match / If-Modified-Since when known."""
        response = self._request(url, headers=self._cached_validators(url))

        etag = response.headers.get("ETag")
        last_modified = response.headers.get("Last-Modified")

        if response.status_code == 304:
            # Nothing to store: a 304 need not repeat the validators, and the
            # ones we already hold are by definition still current.
            return FetchResult(url, 304, None, etag, last_modified)

        if response.status_code != 200:
            return FetchResult(url, response.status_code, None, etag, last_modified)

        self._store_validators(url, etag, last_modified)
        return FetchResult(url, 200, response.text, etag, last_modified)


def normalise_url(url: str, base: str = config.BASE_URL) -> str:
    """Canonical form of a Manual URL, for use as an inventory key.

    Absolutises against `base`, drops the query and fragment, lowercases the
    host and strips a trailing slash. The Manual links to itself with a
    mixture of relative paths, `http://` and `https://` (SOURCE_NOTES.md §8),
    so on the Manual's own host the scheme is forced to the canonical one —
    otherwise the same page keys three ways and every lookup of an internal
    cross reference misses. Other hosts keep the scheme they were given.
    """
    parts = urlsplit(url.strip())
    base_parts = urlsplit(base)

    scheme = (parts.scheme or base_parts.scheme).lower()
    netloc = (parts.netloc or base_parts.netloc).lower()
    if netloc == base_parts.netloc.lower():
        scheme = base_parts.scheme.lower()
    path = parts.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    if len(path) > 1:
        path = path.rstrip("/")

    return f"{scheme}://{netloc}{path}"
