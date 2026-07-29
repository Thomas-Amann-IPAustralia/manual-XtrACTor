"""End to end over the fixtures: write, validate, and write again.

The idempotence test here is the enforcement mechanism for rule 2 and should be
treated as a blocker rather than a nuisance if it fails. Everything else in the
repository — the readable amendment diff, the ability to tell a substantive
change from a re-render — rests on a second run over unchanged input touching
nothing.
"""

from __future__ import annotations

import json
from urllib.parse import unquote

import httpx
import pytest
from legislation_fixtures import fixture_docx

from frl_snapshot import config, crawl, validate, writer
from frl_snapshot.api import FrlClient

_VERSIONS = {
    "C2004A04969": {
        "titleId": "C2004A04969",
        "registerId": "C2024C00545",
        "compilationNumber": "47",
        "name": "Trade Marks Act 1995",
        "start": "2024-10-14T00:00:00",
        "status": "InForce",
        "isLatest": True,
        "hasUnincorporatedAmendments": False,
        "registeredAt": "2024-10-14T13:40:38.9539588",
        "reasons": [
            {
                "affect": "Amend",
                "markdown": "sch 11 (items 80-88) of the ART Act 2024",
                "affectedByTitle": {
                    "titleId": "C2024A00039",
                    "name": "Administrative Review Tribunal Act 2024",
                    "provisions": "sch 11 (items 80-88)",
                    "seriesType": "Act",
                    "year": 2024,
                    "number": 39,
                },
                "amendedByTitle": None,
            }
        ],
    },
    "F1996B00084": {
        "titleId": "F1996B00084",
        "registerId": "F2026C00009",
        "compilationNumber": "53",
        "name": "Trade Marks Regulations 1995",
        "start": "2025-12-18T00:00:00",
        "status": "InForce",
        "isLatest": True,
        "hasUnincorporatedAmendments": False,
        "registeredAt": "2025-12-18T00:00:00",
        "reasons": [],
    },
}

_DOCUMENTS = {
    "C2004A04969": "tma1995-slice",
    "F1996B00084": "tmr1995-slice",
}


def _handler(request: httpx.Request) -> httpx.Response:
    # httpx percent-encodes the OData filter, so match against the decoded URL.
    url = unquote(str(request.url))
    if request.url.path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nCrawl-delay: 10\n")
    for title_id, payload in _VERSIONS.items():
        if f"titleId='{title_id}'" in url:
            return httpx.Response(200, json=payload)
    for title_id, fixture in _DOCUMENTS.items():
        if f"titleid='{title_id}'" in url:
            data = fixture_docx(fixture)
            return httpx.Response(
                200,
                content=data,
                headers={
                    "Content-Type": "application/vnd.openxmlformats-officedocument"
                    ".wordprocessingml.document"
                },
            )
    if "/v1/Documents" in url:
        register = url.split("registerId eq '")[1].split("'")[0]
        fixture = "tmr1995-slice" if register.startswith("F") else "tma1995-slice"
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "type": "Primary",
                        "format": "Word",
                        "sizeInBytes": len(fixture_docx(fixture)),
                    }
                ]
            },
        )
    return httpx.Response(404)


def _client() -> FrlClient:
    return FrlClient(
        delay_s=0.0,
        site_delay_s=0.0,
        client=httpx.Client(transport=httpx.MockTransport(_handler)),
    )


def _run(root, **kwargs):
    defaults = dict(from_raw=False, force=False, dry_run=False, now=writer.utcnow())
    defaults.update(kwargs)
    with _client() as client:
        return [
            crawl.process(
                config.INSTRUMENTS[code], root=root, client=client, **defaults
            )
            for code in sorted(config.INSTRUMENTS)
        ]


def _snapshot_bytes(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture()
def snapshot(tmp_path):
    root = tmp_path / "legislation"
    _run(root)
    return root


def test_a_first_run_writes_both_instruments(snapshot):
    assert (snapshot / "TMA1995" / "instrument.json").is_file()
    assert (snapshot / "TMR1995" / "contents.json").is_file()
    assert (snapshot / "TMA1995" / "provisions" / "pt4" / "TMA1995-s41.json").is_file()
    assert (snapshot / "TMA1995" / "raw" / "TMA1995-C2024C00545.docx").is_file()


def test_a_second_run_over_unchanged_input_changes_nothing(snapshot):
    """Rule 2. A failure here is a blocker, not a nuisance."""
    before = _snapshot_bytes(snapshot)
    results = _run(snapshot, force=True)
    after = _snapshot_bytes(snapshot)

    assert before == after
    assert all(result.files_written == 0 for result in results)


def test_re_parsing_from_raw_needs_no_network(snapshot):
    """`--from-raw` is the check that a parser change did not move the corpus."""
    before = _snapshot_bytes(snapshot)
    results = [
        crawl.process(
            config.INSTRUMENTS[code],
            root=snapshot,
            client=None,
            from_raw=True,
            force=True,
            dry_run=False,
            now=writer.utcnow(),
        )
        for code in sorted(config.INSTRUMENTS)
    ]
    assert _snapshot_bytes(snapshot) == before
    assert all(result.status == "reparsed" for result in results)


def test_the_register_id_gate_skips_an_unchanged_instrument(snapshot):
    results = _run(snapshot)
    assert [result.status for result in results] == ["unchanged", "unchanged"]
    assert all(result.files_written == 0 for result in results)


def test_a_new_compilation_is_detected_and_re_read(snapshot):
    stored = json.loads(
        (snapshot / "TMA1995" / "instrument.json").read_text(encoding="utf-8")
    )
    assert stored["register_id"] == "C2024C00545"

    _VERSIONS["C2004A04969"]["registerId"] = "C2025C00600"
    _VERSIONS["C2004A04969"]["compilationNumber"] = "48"
    try:
        results = _run(snapshot)
    finally:
        _VERSIONS["C2004A04969"]["registerId"] = "C2024C00545"
        _VERSIONS["C2004A04969"]["compilationNumber"] = "47"

    act = next(result for result in results if result.code == "TMA1995")
    assert act.status == "amended"
    assert (snapshot / "TMA1995" / "raw" / "TMA1995-C2025C00600.docx").is_file()


def test_a_provision_file_carries_no_compilation_identity(snapshot):
    """Otherwise every file in the corpus moves on every amendment and the
    readable diff — the point of the repository — is gone."""
    document = json.loads(
        (snapshot / "TMA1995" / "provisions" / "pt4" / "TMA1995-s41.json").read_text(
            encoding="utf-8"
        )
    )
    assert "register_id" not in document
    assert "compilation_number" not in document
    assert document["ref"] == "TMA1995/s41"


def test_captured_at_is_carried_forward_while_content_matches(snapshot):
    path = snapshot / "TMA1995" / "provisions" / "pt4" / "TMA1995-s41.json"
    first = json.loads(path.read_text(encoding="utf-8"))["captured_at"]
    _run(snapshot, force=True)
    assert json.loads(path.read_text(encoding="utf-8"))["captured_at"] == first


def test_a_repealed_provision_is_removed_from_disk(snapshot):
    stray = snapshot / "TMA1995" / "provisions" / "pt4" / "TMA1995-s999.json"
    stray.write_text(json.dumps({"ref": "TMA1995/s999"}), encoding="utf-8")

    results = _run(snapshot, force=True)
    act = next(result for result in results if result.code == "TMA1995")
    assert act.removed == ["TMA1995/s999"]
    assert not stray.exists()


def test_dry_run_writes_nothing(tmp_path):
    root = tmp_path / "legislation"
    results = _run(root, dry_run=True)
    assert all(result.provisions > 0 for result in results)
    assert not root.exists() or not any(root.rglob("*.json"))


def test_a_truncated_download_is_refused(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        response = _handler(request)
        if "/v1/Documents" in str(request.url):
            payload = response.json()
            payload["value"][0]["sizeInBytes"] = 999_999
            return httpx.Response(200, json=payload)
        return response

    client = FrlClient(
        delay_s=0.0,
        site_delay_s=0.0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with client:
        with pytest.raises(crawl.CrawlError, match="partial download"):
            crawl.process(
                config.INSTRUMENTS["TMA1995"],
                root=tmp_path / "legislation",
                client=client,
                from_raw=False,
                force=False,
                dry_run=False,
                now=writer.utcnow(),
            )


def test_from_raw_without_a_snapshot_raises(tmp_path):
    with pytest.raises(crawl.CrawlError, match="--from-raw"):
        crawl.process(
            config.INSTRUMENTS["TMA1995"],
            root=tmp_path / "legislation",
            client=None,
            from_raw=True,
            force=False,
            dry_run=False,
            now=writer.utcnow(),
        )


def test_the_snapshot_validates(snapshot):
    failures, summary = validate.validate(snapshot)
    assert failures == []
    assert summary["provisions"] > 0
    assert summary["units"] > 0


def test_the_validator_catches_a_broken_join(snapshot):
    path = snapshot / "TMA1995" / "provisions" / "pt4" / "TMA1995-s41.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["units"][0]["text"] = "something else entirely"
    path.write_text(json.dumps(document), encoding="utf-8")

    failures, _ = validate.validate(snapshot)
    assert any("join back to text" in failure for failure in failures)


def test_the_validator_catches_a_drifted_emphasis_offset(snapshot):
    path = snapshot / "TMA1995" / "provisions" / "_front" / "TMA1995-front.json"
    if not path.is_file():
        pytest.skip("fixture front matter carries no emphasis")
    document = json.loads(path.read_text(encoding="utf-8"))
    for unit in document["units"]:
        if unit.get("emphasis"):
            unit["emphasis"][0]["start"] += 1
            break
    else:
        pytest.skip("no emphasis span in the front matter")
    path.write_text(json.dumps(document), encoding="utf-8")

    failures, _ = validate.validate(snapshot)
    assert any("emphasis" in failure for failure in failures)


def test_the_validator_catches_an_inventory_disagreement(snapshot):
    path = snapshot / "TMA1995" / "provisions" / "pt4" / "TMA1995-s41.json"
    path.unlink()
    failures, _ = validate.validate(snapshot)
    assert any("no file on disk" in failure for failure in failures)


def test_the_report_names_unincorporated_amendments(snapshot):
    _VERSIONS["F1996B00084"]["hasUnincorporatedAmendments"] = True
    try:
        results = _run(snapshot, force=True)
        report = crawl.render_report(results)
    finally:
        _VERSIONS["F1996B00084"]["hasUnincorporatedAmendments"] = False
    assert "unincorporated amendments" in report
