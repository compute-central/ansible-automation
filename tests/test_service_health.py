"""Unit tests for the custom module's probe logic.

The module's `probe()` function takes `module` and `params` explicitly and
returns a tuple, specifically so it can be tested without an Ansible run. A
module whose logic only exists inside `main()` cannot be unit tested at all,
which is the most common reason custom modules go untested.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "modules"))

import service_health  # noqa: E402


class FakeResponse:
    def __init__(self, body=""):
        self._body = body.encode("utf-8")

    def read(self):
        return self._body


def params(**overrides):
    base = {
        "url": "http://host/healthz",
        "expect_status": 200,
        "expect_body": None,
        "timeout": 5.0,
        "retries": 3,
        "backoff": 0.0,  # no real sleeping in tests
        "validate_certs": True,
        "headers": {},
    }
    base.update(overrides)
    return base


def patch_fetch(monkeypatch, responses):
    """Queue a list of (response, info) pairs for successive fetch_url calls."""
    queue = list(responses)
    calls = []

    def fake_fetch_url(module, url, **kwargs):
        calls.append(url)
        return queue.pop(0) if queue else (None, {"status": -1, "msg": "exhausted"})

    monkeypatch.setattr(service_health, "fetch_url", fake_fetch_url)
    monkeypatch.setattr(service_health.time, "sleep", lambda _s: None)
    return calls


def test_healthy_on_the_first_attempt(monkeypatch):
    calls = patch_fetch(monkeypatch, [(FakeResponse("ok"), {"status": 200})])
    healthy, status, _elapsed, attempts, reason = service_health.probe(None, params())

    assert healthy is True
    assert status == 200
    assert attempts == 1
    assert len(calls) == 1
    assert "200 in" in reason


def test_retries_a_503_then_succeeds(monkeypatch):
    calls = patch_fetch(
        monkeypatch,
        [
            (None, {"status": 503}),
            (None, {"status": 503}),
            (FakeResponse("ok"), {"status": 200}),
        ],
    )
    healthy, status, _elapsed, attempts, _reason = service_health.probe(None, params())

    assert healthy is True
    assert status == 200
    assert attempts == 3
    assert len(calls) == 3


def test_gives_up_after_the_retry_budget(monkeypatch):
    patch_fetch(monkeypatch, [(None, {"status": 503})] * 3)
    healthy, status, _elapsed, attempts, reason = service_health.probe(None, params())

    assert healthy is False
    assert status == 503
    assert attempts == 3
    assert reason == "expected 200, got 503"


def test_does_not_retry_a_401(monkeypatch):
    """A 401 will still be a 401 in two seconds."""
    calls = patch_fetch(monkeypatch, [(None, {"status": 401})])
    healthy, status, _elapsed, attempts, _reason = service_health.probe(None, params())

    assert healthy is False
    assert status == 401
    assert attempts == 1
    assert len(calls) == 1


def test_connection_failure_reports_the_transport_error(monkeypatch):
    patch_fetch(
        monkeypatch,
        [(None, {"status": -1, "msg": "Connection refused"})] * 2,
    )
    healthy, status, _elapsed, attempts, reason = service_health.probe(
        None, params(retries=2)
    )

    assert healthy is False
    assert status is None
    assert attempts == 2
    assert "Connection refused" in reason


def test_body_assertion(monkeypatch):
    patch_fetch(monkeypatch, [(FakeResponse('{"status":"degraded"}'), {"status": 200})])
    healthy, _status, _elapsed, _attempts, reason = service_health.probe(
        None, params(expect_body="healthy")
    )

    assert healthy is False
    assert reason == "body did not match"


def test_body_assertion_passes_when_present(monkeypatch):
    patch_fetch(monkeypatch, [(FakeResponse('{"status":"ok"}'), {"status": 200})])
    healthy, _status, _elapsed, _attempts, _reason = service_health.probe(
        None, params(expect_body='"status":"ok"')
    )

    assert healthy is True


def test_a_non_default_expected_status(monkeypatch):
    patch_fetch(monkeypatch, [(None, {"status": 204})])
    healthy, _status, _elapsed, _attempts, _reason = service_health.probe(
        None, params(expect_status=204)
    )

    assert healthy is True


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_the_retryable_set(status):
    assert status in service_health.RETRYABLE_STATUSES


@pytest.mark.parametrize("status", [400, 401, 403, 404, 200])
def test_what_is_not_retryable(status):
    assert status not in service_health.RETRYABLE_STATUSES
