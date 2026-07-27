"""T2 — politeness, conditional requests and retries.

Every request here is served by a mock transport and every sleep is recorded
rather than taken, so the suite is both offline and instant.
"""

from __future__ import annotations

import json

import httpx
import pytest

from tmm_snapshot import config, fetch
from tmm_snapshot.fetch import FetchError, Fetcher, RobotsDisallowed, normalise_url

URL = "https://manuals.ipaustralia.gov.au/trademark/22.-numerals"

ROBOTS_ALLOWING = "User-agent: *\nDisallow: /admin/\nDisallow: /user/login\n"
ROBOTS_DISALLOWING = "User-agent: *\nDisallow: /trademark\n"


class FakeClock:
    """Stands in for the `time` module inside fetch.py.

    Sleeping advances the clock instead of the wall, which lets the rate limit
    and the backoff be asserted on exactly.
    """

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(fetch, "time", fake)
    return fake


class Site:
    """A scripted mock origin. Records every request it is sent."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = (
            self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        )
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=response.content,
        )


def ok(body: str = "<html>page</html>", **headers: str) -> httpx.Response:
    return httpx.Response(200, headers=headers, text=body)


def build(tmp_path, site: Site, **kwargs) -> Fetcher:
    return Fetcher(
        tmp_path / ".cache", transport=httpx.MockTransport(site), **kwargs
    )


# -- conditional requests -------------------------------------------------


def test_a_200_returns_the_html_and_stores_the_validators(tmp_path, clock):
    site = Site(ok(ETag='"1785131438"', **{"Last-Modified": "Mon, 27 Jul 2026 05:50:38 GMT"}))
    with build(tmp_path, site) as fetcher:
        result = fetcher.get(URL)

    assert (result.status, result.html) == (200, "<html>page</html>")
    assert result.etag == '"1785131438"'
    assert result.last_modified == "Mon, 27 Jul 2026 05:50:38 GMT"

    (cached,) = list((tmp_path / ".cache").glob("*.json"))
    stored = json.loads(cached.read_text(encoding="utf-8"))
    assert stored == {
        "url": URL,
        "etag": '"1785131438"',
        "last_modified": "Mon, 27 Jul 2026 05:50:38 GMT",
    }


def test_the_second_request_is_conditional(tmp_path, clock):
    """Gate 1 of the skip logic."""
    site = Site(ok(ETag='"abc"', **{"Last-Modified": "Mon, 27 Jul 2026 05:50:38 GMT"}))
    with build(tmp_path, site) as fetcher:
        fetcher.get(URL)
        fetcher.get(URL)

    first, second = site.requests
    assert "If-Modified-Since" not in first.headers
    assert second.headers["If-Modified-Since"] == "Mon, 27 Jul 2026 05:50:38 GMT"


def test_only_one_validator_is_sent_and_the_date_wins(tmp_path, clock):
    """Both together is not belt and braces — it is a 200 every time.

    The Manual is served by Apache with mod_deflate, whose `-gzip` ETag suffix
    never matches an incoming If-None-Match, and RFC 9110 has If-None-Match
    suppress the date check when both are present. Measured against the live
    site on 27 July 2026; see fetch._cached_validators and SOURCE_NOTES.md §12.
    """
    site = Site(
        ok(
            ETag='"1785133603-gzip"',
            **{"Last-Modified": "Mon, 27 Jul 2026 06:26:43 GMT"},
        )
    )
    with build(tmp_path, site) as fetcher:
        fetcher.get(URL)
        fetcher.get(URL)

    assert "If-None-Match" not in site.requests[1].headers


def test_an_etag_is_the_fallback_when_there_is_no_date(tmp_path, clock):
    site = Site(ok(ETag='"abc"'))
    with build(tmp_path, site) as fetcher:
        fetcher.get(URL)
        fetcher.get(URL)

    assert site.requests[1].headers["If-None-Match"] == '"abc"'
    assert "If-Modified-Since" not in site.requests[1].headers


def test_a_304_carries_no_html(tmp_path, clock):
    site = Site(ok(ETag='"abc"'), httpx.Response(304, headers={"ETag": '"abc"'}))
    with build(tmp_path, site) as fetcher:
        fetcher.get(URL)
        result = fetcher.get(URL)

    assert result.status == 304
    assert result.html is None


def test_a_304_does_not_discard_the_stored_validators(tmp_path, clock):
    site = Site(ok(ETag='"abc"'), httpx.Response(304))
    with build(tmp_path, site) as fetcher:
        fetcher.get(URL)
        fetcher.get(URL)
        fetcher.get(URL)

    assert site.requests[-1].headers["If-None-Match"] == '"abc"'


def test_a_response_with_no_validators_writes_no_cache_entry(tmp_path, clock):
    with build(tmp_path, Site(ok())) as fetcher:
        fetcher.get(URL)
    assert not list((tmp_path / ".cache").glob("*.json"))


def test_validators_are_per_url(tmp_path, clock):
    other = "https://manuals.ipaustralia.gov.au/trademark/9.-words"
    site = Site(ok(ETag='"abc"'))
    with build(tmp_path, site) as fetcher:
        fetcher.get(URL)
        fetcher.get(other)

    assert "If-None-Match" not in site.requests[1].headers
    assert len(list((tmp_path / ".cache").glob("*.json"))) == 2


# -- politeness -----------------------------------------------------------


def test_requests_are_spaced_by_the_delay(tmp_path, clock):
    with build(tmp_path, Site(ok()), delay_s=1.5) as fetcher:
        fetcher.get(URL)
        assert clock.sleeps == []  # nothing to wait for on the first request
        fetcher.get(URL)

    assert clock.sleeps == [1.5]


def test_the_user_agent_identifies_the_crawler_and_a_contact(tmp_path, clock):
    site = Site(ok())
    with build(tmp_path, site) as fetcher:
        fetcher.get(URL)

    agent = site.requests[0].headers["User-Agent"]
    assert agent == config.USER_AGENT
    assert "tmm-snapshot" in agent
    assert config.CONTACT in agent


def test_a_429_backs_off_and_then_succeeds(tmp_path, clock):
    site = Site(httpx.Response(429), ok())
    with build(tmp_path, site) as fetcher:
        assert fetcher.get(URL).status == 200

    assert len(site.requests) == 2
    assert clock.sleeps == [config.BACKOFF_BASE_S]


def test_backoff_is_exponential_and_then_gives_up(tmp_path, clock):
    site = Site(httpx.Response(503))
    with build(tmp_path, site) as fetcher:
        with pytest.raises(FetchError, match=URL):
            fetcher.get(URL)

    assert len(site.requests) == config.MAX_RETRIES + 1
    assert clock.sleeps == [2.0, 4.0, 8.0]


def test_backoff_is_capped(tmp_path, clock, monkeypatch):
    monkeypatch.setattr(config, "BACKOFF_CAP_S", 5.0)
    with build(tmp_path, Site(httpx.Response(500))) as fetcher:
        with pytest.raises(FetchError):
            fetcher.get(URL)

    assert max(clock.sleeps) <= 5.0


def test_retry_after_widens_the_backoff(tmp_path, clock):
    site = Site(httpx.Response(429, headers={"Retry-After": "30"}), ok())
    with build(tmp_path, site) as fetcher:
        fetcher.get(URL)

    assert clock.sleeps == [30.0]


def test_an_unparseable_retry_after_falls_back_to_our_own_backoff(tmp_path, clock):
    site = Site(
        httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
        ok(),
    )
    with build(tmp_path, site) as fetcher:
        fetcher.get(URL)

    assert clock.sleeps == [config.BACKOFF_BASE_S]


def test_a_connection_error_is_retried_and_then_raises_with_the_url(tmp_path, clock):
    attempts = []

    def refuse(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        raise httpx.ConnectError("connection refused", request=request)

    fetcher = Fetcher(tmp_path / ".cache", transport=httpx.MockTransport(refuse))
    with pytest.raises(FetchError, match=URL):
        fetcher.get(URL)

    assert len(attempts) == config.MAX_RETRIES + 1


def test_a_404_is_reported_rather_than_retried(tmp_path, clock):
    """A page that is gone is a fact the crawler needs — it drives retirement
    — not a failure to retry at the site."""
    site = Site(httpx.Response(404))
    with build(tmp_path, site) as fetcher:
        result = fetcher.get(URL)

    assert (result.status, result.html) == (404, None)
    assert len(site.requests) == 1


# -- robots ---------------------------------------------------------------


def test_robots_allowing_the_manual_passes(tmp_path, clock):
    site = Site(ok(ROBOTS_ALLOWING))
    with build(tmp_path, site) as fetcher:
        fetcher.check_robots()

    assert str(site.requests[0].url) == config.ROBOTS_URL


def test_robots_disallowing_the_manual_stops_the_run(tmp_path, clock):
    with build(tmp_path, Site(ok(ROBOTS_DISALLOWING))) as fetcher:
        with pytest.raises(RobotsDisallowed):
            fetcher.check_robots()


def test_the_robots_verdict_is_never_cached_across_runs(tmp_path, clock):
    """A site that starts disallowing us must be able to stop us on the next
    run, not on our next release."""
    site = Site(ok(ROBOTS_ALLOWING))
    with build(tmp_path, site) as fetcher:
        fetcher.check_robots()
        fetcher.check_robots()

    assert len(site.requests) == 2
    assert not list((tmp_path / ".cache").glob("*.json"))


def test_an_unreadable_robots_stops_the_run(tmp_path, clock):
    """Not being able to read the rules is not permission to ignore them."""
    with build(tmp_path, Site(httpx.Response(404))) as fetcher:
        with pytest.raises(FetchError, match="robots.txt"):
            fetcher.check_robots()


def test_a_crawl_delay_widens_our_own(tmp_path, clock):
    site = Site(ok("User-agent: *\nCrawl-delay: 10\n"))
    with build(tmp_path, site, delay_s=1.0) as fetcher:
        fetcher.check_robots()
        assert fetcher.delay_s == 10.0


def test_a_crawl_delay_never_narrows_our_own(tmp_path, clock):
    site = Site(ok("User-agent: *\nCrawl-delay: 0.1\n"))
    with build(tmp_path, site, delay_s=1.0) as fetcher:
        fetcher.check_robots()
        assert fetcher.delay_s == 1.0


# -- url normalisation ----------------------------------------------------


@pytest.mark.parametrize(
    "variant",
    [
        "https://manuals.ipaustralia.gov.au/trademark/22.-numerals",
        "http://manuals.ipaustralia.gov.au/trademark/22.-numerals",
        "https://MANUALS.ipaustralia.gov.au/trademark/22.-numerals",
        "/trademark/22.-numerals",
        "https://manuals.ipaustralia.gov.au/trademark/22.-numerals/",
        "https://manuals.ipaustralia.gov.au/trademark/22.-numerals#heading",
        "  https://manuals.ipaustralia.gov.au/trademark/22.-numerals  ",
    ],
)
def test_normalise_url_collapses_the_forms_the_manual_links_with(variant):
    assert normalise_url(variant) == URL


def test_normalise_url_leaves_other_hosts_alone():
    austlii = "http://austlii.edu.au/cgi-bin/viewdb/au/legis/cth/consol_act/tma1995121/s41.html"
    assert normalise_url(austlii) == austlii
