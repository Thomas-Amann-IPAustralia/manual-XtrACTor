"""The Federal Register of Legislation's OData API, and only what we need of it.

Two calls carry the whole pipeline:

    Versions/Find(titleId=…, asAtSpecification='Latest')   -> the amendment signal
    documents/find(titleid=…, …, format='Word')            -> the document itself

Everything in this module that looks like superstition is load-bearing. The
API's spelling and defaults are documented in LEGISLATION_NOTES.md §3; the
short version is below, at each place it bites.
"""

from __future__ import annotations

import json
import time
import urllib.robotparser
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Final

import httpx

from frl_snapshot import config


class ApiError(Exception):
    """The Register did not answer, or answered with something unusable."""


class RobotsDisallowed(Exception):
    """robots.txt forbids a URL this pipeline wanted."""


#: `documents/find()` declares these three as optional with a default of 0.
#: They are not optional. Omitted, the call returns a bare 404 with an empty
#: body — indistinguishable from the response for a document that genuinely
#: does not exist, which is what makes the mistake expensive: it looks like
#: missing data rather than a malformed call. LEGISLATION_NOTES.md §3.2.
_REQUIRED_DEFAULTS: Final[str] = (
    "uniqueTypeNumber=0,volumeNumber=0,rectificationVersionNumber=0"
)


@dataclass(frozen=True)
class Version:
    """One compiled version of one law, as the Register describes it.

    `register_id` is the amendment signal and the reason this pipeline needs no
    content hashing at the fetch stage: it changes if and only if a new
    compilation was registered. `has_unincorporated_amendments` is the case
    that signal does *not* cover — amendments made and commenced but not yet
    compiled, so the document is legally out of date and `register_id` has not
    moved. Both are recorded. LEGISLATION_NOTES.md §4.
    """

    title_id: str
    register_id: str
    compilation_number: str | None
    name: str | None
    start: str | None
    end: str | None
    status: str | None
    is_latest: bool | None
    has_unincorporated_amendments: bool | None
    registered_at: str | None
    reasons: tuple[dict[str, Any], ...] = field(default=())

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Version:
        register_id = payload.get("registerId")
        title_id = payload.get("titleId")
        if not register_id or not title_id:
            raise ApiError(
                f"Versions/Find returned no registerId for {title_id!r}: "
                f"{sorted(payload)!r}. Without it there is no amendment signal, "
                "and treating that as 'unchanged' would freeze the snapshot "
                "silently."
            )
        reasons = payload.get("reasons") or []
        return cls(
            title_id=str(title_id),
            register_id=str(register_id),
            compilation_number=_opt_str(payload.get("compilationNumber")),
            name=_opt_str(payload.get("name")),
            start=_opt_str(payload.get("start")),
            end=_opt_str(payload.get("end")),
            status=_opt_str(payload.get("status")),
            is_latest=payload.get("isLatest"),
            has_unincorporated_amendments=payload.get("hasUnincorporatedAmendments"),
            registered_at=_opt_str(payload.get("registeredAt")),
            reasons=tuple(reasons),
        )

    @property
    def start_date(self) -> str | None:
        """'2024-10-14T00:00:00' -> '2024-10-14'."""
        return self.start[:10] if self.start else None


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


class FrlClient:
    """Serial, polite, retrying access to the Register.

    Deliberately not a subclass of `tmm_snapshot.fetch.Fetcher`, which is built
    around conditional HTML GETs with an ETag cache. Here the conditional
    request *is* the version probe, and it is cheaper than any HTTP validator:
    one small JSON body that says whether the law changed, rather than a
    round-trip that says whether the bytes did.
    """

    def __init__(
        self,
        *,
        delay_s: float = config.API_REQUEST_DELAY_S,
        site_delay_s: float = config.SITE_REQUEST_DELAY_S,
        user_agent: str = config.USER_AGENT,
        client: httpx.Client | None = None,
    ) -> None:
        self._delay_s = delay_s
        self._site_delay_s = site_delay_s
        self._last_request_at: float | None = None
        self._last_host: str | None = None
        self._client = client or httpx.Client(
            headers={"User-Agent": user_agent},
            follow_redirects=True,
            timeout=config.REQUEST_TIMEOUT_S,
        )
        self._robots: urllib.robotparser.RobotFileParser | None = None
        self._user_agent = user_agent

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> FrlClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- courtesy ----------------------------------------------------------

    def check_robots(self) -> None:
        """Fetch and honour `www.legislation.gov.au/robots.txt`.

        Checked on every run, never cached across runs — the Manual crawler's
        rule, for the same reason: a site that starts disallowing us must be
        able to say so and be heard on the next crawl, not the next release.

        The API host serves no robots.txt (404), so nothing is asserted about
        it and nothing is enforced. The public site asks for `Crawl-delay: 10`
        and that is what `config.SITE_REQUEST_DELAY_S` is.
        """
        parser = urllib.robotparser.RobotFileParser()
        try:
            response = self._client.get(
                config.SITE_ROBOTS_URL, timeout=config.REQUEST_TIMEOUT_S
            )
        except httpx.HTTPError as error:  # pragma: no cover - network only
            raise ApiError(f"could not read {config.SITE_ROBOTS_URL}: {error}") from error

        if response.status_code == 404:
            parser.parse([])
        else:
            parser.parse(response.text.splitlines())
        self._robots = parser

    def _allowed(self, url: str) -> bool:
        if self._robots is None or not url.startswith(config.SITE_BASE):
            return True
        return self._robots.can_fetch(self._user_agent, url)

    def _wait_turn(self, host_key: str) -> None:
        """One request at a time, with the delay the host asked for."""
        delay = self._site_delay_s if host_key == "site" else self._delay_s
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < delay:
                time.sleep(delay - elapsed)
        self._last_request_at = time.monotonic()
        self._last_host = host_key

    def _backoff(self, attempt: int, retry_after: str | None = None) -> None:
        if retry_after:
            try:
                time.sleep(min(float(retry_after), config.BACKOFF_CAP_S))
                return
            except ValueError:
                pass
        time.sleep(min(config.BACKOFF_BASE_S * (2**attempt), config.BACKOFF_CAP_S))

    # -- requests ----------------------------------------------------------

    def _get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = config.REQUEST_TIMEOUT_S,
        host_key: str = "api",
        allow_404: bool = False,
    ) -> httpx.Response | None:
        if not self._allowed(url):
            raise RobotsDisallowed(url)

        last_error: str = ""
        for attempt in range(config.MAX_RETRIES + 1):
            self._wait_turn(host_key)
            try:
                response = self._client.get(url, headers=headers, timeout=timeout)
            except httpx.HTTPError as error:
                last_error = f"{type(error).__name__}: {error}"
                if attempt == config.MAX_RETRIES:
                    break
                self._backoff(attempt)
                continue

            if response.status_code == 404 and allow_404:
                return None
            if response.status_code == 429 or response.status_code >= 500:
                last_error = f"HTTP {response.status_code}"
                if attempt == config.MAX_RETRIES:
                    break
                self._backoff(attempt, response.headers.get("Retry-After"))
                continue
            if response.status_code >= 400:
                raise ApiError(f"HTTP {response.status_code} for {url}")
            return response

        raise ApiError(f"giving up on {url} after {config.MAX_RETRIES} retries: {last_error}")

    # -- the two calls that matter ----------------------------------------

    def version(self, title_id: str, as_at: str = "Latest") -> Version:
        """The current compiled version of a law.

        `Find()` returns a single object, not an OData `{"value": [...]}`
        envelope. Indexing into `["value"]` is the reflex to resist.

        Note the casing: this endpoint is camelCase and `documents/find` below
        is all lowercase. That is the live API, not a typo here.
        """
        url = (
            f"{config.API_BASE}/v1/Versions/Find("
            f"titleId='{title_id}',asAtSpecification='{as_at}')"
        )
        response = self._get(url, headers={"Accept": "application/json"})
        assert response is not None
        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise ApiError(f"{url} did not return JSON: {error}") from error
        if not isinstance(payload, dict) or not payload:
            raise ApiError(f"{url} returned {type(payload).__name__}, expected an object")
        return Version.from_payload(payload)

    def documents(self, register_id: str) -> list[dict[str, Any]]:
        """Every rendition of one compilation: type, format, size, authority.

        Used to check a download arrived whole. `sizeInBytes` is the Register's
        own count and a truncated body is otherwise a perfectly well-formed
        zip that parses to a shorter Act.
        """
        url = (
            f"{config.API_BASE}/v1/Documents"
            f"?$filter=registerId eq '{register_id}'"
        )
        response = self._get(url, headers={"Accept": "application/json"})
        assert response is not None
        payload = response.json()
        value = payload.get("value") if isinstance(payload, dict) else payload
        return list(value or [])

    def download(
        self,
        title_id: str,
        *,
        doc_type: str = "Primary",
        fmt: str = "Word",
        as_at: str = "Latest",
        start_date: str | None = None,
    ) -> bytes | None:
        """The document itself, as bytes. None if the Register has no such file.

        Two things about this call.

        **No `Accept: application/json`.** The same URL serves the file by
        default and *metadata about* the file when JSON is asked for, so a
        session-level Accept header silently returns a description of the Act
        where the Act was wanted. That is why this method builds its headers
        rather than inheriting them, and why a 200 carrying JSON is treated as
        a miss rather than as content.

        **The three zero-valued parameters are required**, despite the spec
        calling them optional. See `_REQUIRED_DEFAULTS`.

        On a miss, falls back to the public site's predictable path, which
        serves documents the API's index does not carry. Verified byte-for-byte
        identical to the API's own response for the Trade Marks Act.
        """
        url = (
            f"{config.API_BASE}/v1/documents/find("
            f"titleid='{title_id}',"
            f"asatspecification='{as_at}',"
            f"type='{doc_type}',"
            f"format='{fmt}',"
            f"{_REQUIRED_DEFAULTS})"
        )
        response = self._get(
            url, timeout=config.DOCUMENT_TIMEOUT_S, allow_404=True
        )
        if response is not None:
            content = _document_bytes(response)
            if content is not None:
                return content

        if start_date is None:
            return None
        return self._download_from_site(title_id, start_date, as_at=as_at, fmt=fmt)

    def _download_from_site(
        self, title_id: str, start_date: str, *, as_at: str, fmt: str
    ) -> bytes | None:
        """The §3.4 fallback: `/{titleId}/latest/{startDate}/text/original/word`."""
        stage = "asmade" if as_at.lower() == "asmade" else "latest"
        url = (
            f"{config.SITE_BASE}/{title_id}/{stage}/{start_date}"
            f"/text/original/{fmt.lower()}"
        )
        response = self._get(
            url,
            timeout=config.DOCUMENT_TIMEOUT_S,
            host_key="site",
            allow_404=True,
        )
        if response is None:
            return None
        return _document_bytes(response)


def _document_bytes(response: httpx.Response) -> bytes | None:
    """The response body, if it is actually a document.

    Guards the two ways this endpoint returns success without returning a file:
    JSON metadata, and an HTML error page served as 200. The size floor is
    what separates the second from a genuinely tiny instrument — no compiled
    trade marks document is under 50 KB, and one that were would fail the
    `sizeInBytes` check in `crawl` rather than being parsed as an error page.
    """
    content_type = (response.headers.get("Content-Type") or "").lower()
    if "json" in content_type:
        return None
    if "html" in content_type and len(response.content) < 50_000:
        return None
    return response.content or None
