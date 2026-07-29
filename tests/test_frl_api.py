"""The Register's API, against a mocked transport. Never the network.

Most of what is asserted here is a way the live API returns success without
returning what was asked for. Each was verified against production before it
was encoded, and each is silent when it goes wrong — which is why it is a test
rather than a comment.
"""

from __future__ import annotations

import httpx
import pytest

from frl_snapshot import config
from frl_snapshot.api import ApiError, FrlClient, Version

_VERSION_PAYLOAD = {
    "titleId": "C2004A04969",
    "registerId": "C2024C00545",
    "compilationNumber": "47",
    "name": "Trade Marks Act 1995",
    "start": "2024-10-14T00:00:00",
    "end": None,
    "status": "InForce",
    "isLatest": True,
    "hasUnincorporatedAmendments": False,
    "registeredAt": "2024-10-14T13:40:38.9539588",
    "reasons": [{"affect": "Amend", "markdown": "sch 11 of the [ART Act](/C2024A00039)"}],
}


def _client(handler) -> FrlClient:
    transport = httpx.MockTransport(handler)
    return FrlClient(
        delay_s=0.0,
        site_delay_s=0.0,
        client=httpx.Client(transport=transport, follow_redirects=True),
    )


def test_version_reads_the_bare_object():
    """`Find()` returns a single object, not an OData {"value": [...]} envelope."""
    with _client(lambda request: httpx.Response(200, json=_VERSION_PAYLOAD)) as client:
        version = client.version("C2004A04969")
    assert version.register_id == "C2024C00545"
    assert version.compilation_number == "47"
    assert version.start_date == "2024-10-14"
    assert version.has_unincorporated_amendments is False


def test_version_without_a_register_id_raises():
    """No amendment signal is not the same as 'unchanged'."""
    with _client(lambda request: httpx.Response(200, json={"titleId": "X"})) as client:
        with pytest.raises(ApiError, match="no registerId"):
            client.version("X")


def test_download_sends_the_three_parameters_the_spec_calls_optional():
    """Omitted, they produce a bare 404 that looks exactly like a missing
    document rather than a malformed call."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            200,
            content=b"PK\x03\x04" + b"x" * 60_000,
            headers={"Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        )

    with _client(handler) as client:
        assert client.download("C2004A04969") is not None

    url = seen[0]
    assert "uniqueTypeNumber=0" in url
    assert "volumeNumber=0" in url
    assert "rectificationVersionNumber=0" in url
    assert "documents/find(" in url


def test_download_does_not_ask_for_json():
    """The same URL serves the file by default and metadata *about* the file
    when JSON is requested. An Accept header here silently returns a
    description of the Act where the Act was wanted."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"x" * 60_000)

    with _client(handler) as client:
        client.download("C2004A04969")

    assert "json" not in (seen[0].headers.get("accept") or "").lower()


def test_a_200_carrying_json_is_a_miss_not_a_document():
    with _client(lambda r: httpx.Response(200, json={"type": "Primary"})) as client:
        assert client.download("C2004A04969") is None


def test_an_html_error_page_served_as_200_is_a_miss():
    with _client(
        lambda r: httpx.Response(
            200, content=b"<html>error</html>", headers={"Content-Type": "text/html"}
        )
    ) as client:
        assert client.download("C2004A04969") is None


def test_a_404_falls_back_to_the_public_site():
    """Some instruments' documents are lodged as direct files that never reach
    the API's document index."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "api.prod" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(
            200,
            content=b"x" * 60_000,
            headers={"Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        )

    with _client(handler) as client:
        assert client.download("F2025L01380", start_date="2025-11-01") is not None

    assert seen[1].startswith(config.SITE_BASE)
    assert seen[1].endswith("/F2025L01380/latest/2025-11-01/text/original/word")


def test_a_404_with_no_start_date_is_simply_a_miss():
    with _client(lambda r: httpx.Response(404)) as client:
        assert client.download("F2025L01380") is None


def test_retries_then_gives_up_with_the_url():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    with _client(handler) as client:
        client._backoff = lambda *args, **kwargs: None  # type: ignore[method-assign]
        with pytest.raises(ApiError, match="giving up"):
            client.version("C2004A04969")

    assert calls["n"] == config.MAX_RETRIES + 1


def test_a_429_is_retried_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json=_VERSION_PAYLOAD)

    with _client(handler) as client:
        client._backoff = lambda *args, **kwargs: None  # type: ignore[method-assign]
        assert client.version("C2004A04969").register_id == "C2024C00545"
    assert calls["n"] == 2


def test_robots_is_honoured_on_the_public_site():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        return httpx.Response(200, content=b"x" * 60_000)

    from frl_snapshot.api import RobotsDisallowed

    with _client(handler) as client:
        client.check_robots()
        with pytest.raises(RobotsDisallowed):
            client._download_from_site(
                "F2025L01380", "2025-11-01", as_at="Latest", fmt="Word"
            )


def test_a_missing_robots_file_allows_everything():
    """The API host serves no robots.txt at all — a 404 asserts nothing."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, json=_VERSION_PAYLOAD)

    with _client(handler) as client:
        client.check_robots()
        assert client.version("C2004A04969").register_id == "C2024C00545"


def test_version_payload_keeps_the_reasons_array():
    version = Version.from_payload(_VERSION_PAYLOAD)
    assert version.reasons
    assert version.reasons[0]["affect"] == "Amend"
