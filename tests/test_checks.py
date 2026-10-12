"""R02 and R05 against fixture documents and in-memory resources."""

from __future__ import annotations

from datetime import datetime, timezone

from nmos_reg_check.checks import (
    HEARTBEAT_EXPIRY_SECONDS,
    TAI_UTC_OFFSET_SECONDS,
    evaluate,
    extract_health,
)
from nmos_reg_check.client import Resource, Snapshot
from tests.conftest import load_json

HEALTH = 1441974485  # IS-04 heartbeat example, TAI seconds


def _resource(resource_type: str, raw: dict) -> Resource:
    label = raw.get("label") or raw.get("hostname")
    return Resource(
        type=resource_type,
        id=raw.get("id"),
        label=label if isinstance(label, str) else None,
        raw=raw,
    )


def _snapshot(
    nodes: list[dict],
    devices: list[dict] | None = None,
    senders: list[dict] | None = None,
    receivers: list[dict] | None = None,
) -> Snapshot:
    return Snapshot(
        registry_url="http://registry.test:8080",
        query_url="http://registry.test:8080/x-nmos/query/v1.3/",
        version="v1.3",
        resources={
            "nodes": [_resource("node", item) for item in nodes],
            "devices": [_resource("device", item) for item in devices or []],
            "senders": [_resource("sender", item) for item in senders or []],
            "receivers": [_resource("receiver", item) for item in receivers or []],
        },
    )


def _codes(findings: list) -> list[tuple[str, str]]:
    return [(finding.check_id, finding.code) for finding in findings]


def _tai_now(health_tai: float, age: float) -> float:
    return health_tai + age - TAI_UTC_OFFSET_SECONDS


def test_spec_nodes_skip_r02_because_version_is_not_a_heartbeat():
    nodes = load_json("nodes.json")
    assert all("health" not in node for node in nodes)
    findings = evaluate(
        _snapshot(nodes, load_json("devices.json"), load_json("senders.json"), load_json("receivers.json")),
        now_utc=_tai_now(HEALTH, 10_000),
    )
    assert ("R01", "query_api_reachable") in _codes(findings)
    assert ("R02", "heartbeat_absent") in _codes(findings)
    assert ("R05", "no_duplicate_ids") in _codes(findings)
    assert "heartbeat_stale" not in {code for _check, code in _codes(findings)}


def test_fresh_inline_health_is_ok_and_nodes_without_it_are_skipped():
    findings = evaluate(
        _snapshot(load_json("nodes-with-health.json")),
        now_utc=_tai_now(HEALTH, 5),
    )
    assert ("R02", "heartbeat_ok") in _codes(findings)
    assert ("R02", "heartbeat_missing_on_some") in _codes(findings)
    assert "heartbeat_stale" not in {code for _check, code in _codes(findings)}
    ok = next(finding for finding in findings if finding.code == "heartbeat_ok")
    assert ok.details["count"] == 1
    assert ok.details["threshold_seconds"] == HEARTBEAT_EXPIRY_SECONDS


def test_stale_health_uses_tai_and_the_twelve_second_limit():
    stale = evaluate(_snapshot(load_json("nodes-with-health.json")), now_utc=_tai_now(HEALTH, 30))
    finding = next(item for item in stale if item.code == "heartbeat_stale")
    assert finding.severity == "error"
    assert finding.resource_id == "c8ba20e9-e197-4ec5-8764-4da672128589"
    assert finding.details["age_seconds"] == 30
    assert finding.details["timescale"] == "tai"
    assert finding.message_params["age"] == "30"

    # Exactly the garbage-collection interval is not stale yet.
    at_limit = evaluate(
        _snapshot(load_json("nodes-with-health.json")),
        now_utc=_tai_now(HEALTH, HEARTBEAT_EXPIRY_SECONDS),
    )
    assert "heartbeat_stale" not in {code for _check, code in _codes(at_limit)}

    just_over = evaluate(
        _snapshot(load_json("nodes-with-health.json")),
        now_utc=_tai_now(HEALTH, HEARTBEAT_EXPIRY_SECONDS + 0.2),
    )
    assert "heartbeat_stale" in {code for _check, code in _codes(just_over)}


def test_tai_timestamp_ahead_of_utc_is_not_treated_as_future_utc():
    """A heartbeat 20s behind TAI now is only 17s ahead of UTC. It is still stale."""

    now_utc = 1_700_000_000
    health_tai = now_utc + TAI_UTC_OFFSET_SECONDS - 20
    nodes = [
        {
            "id": "c8ba20e9-e197-4ec5-8764-4da672128589",
            "label": "host1",
            "version": "1:0",
            "health": str(health_tai),
        }
    ]
    findings = evaluate(_snapshot(nodes), now_utc=now_utc)
    finding = next(item for item in findings if item.code == "heartbeat_stale")
    assert finding.details["age_seconds"] == 20


def test_health_field_shapes():
    node_id = "c8ba20e9-e197-4ec5-8764-4da672128589"
    base = {"id": node_id, "label": "host1", "version": "1441716120:1"}

    seconds_and_nanos = extract_health({**base, "heartbeat": f"{HEALTH}:250000000"})
    assert seconds_and_nanos is not None and seconds_and_nanos != "unrecognized"
    assert seconds_and_nanos.seconds == HEALTH
    assert seconds_and_nanos.timescale == "tai"

    millis = extract_health({**base, "last_heartbeat": HEALTH * 1000})
    assert millis is not None and millis != "unrecognized"
    assert millis.seconds == HEALTH

    nested = extract_health({**base, "health": {"timestamp": str(HEALTH)}})
    assert nested is not None and nested != "unrecognized"
    assert nested.seconds == HEALTH

    blank = extract_health({**base, "health": ""})
    assert blank is None
    assert extract_health({**base, "health": None}) is None

    bad = extract_health(load_json("nodes-bad-health.json")[0])
    assert bad == "unrecognized"

    findings = evaluate(_snapshot(load_json("nodes-bad-health.json")), now_utc=_tai_now(HEALTH, 5))
    assert ("R02", "heartbeat_unrecognized") in _codes(findings)
    assert all(finding.severity != "error" or finding.check_id != "R02" for finding in findings)


def test_iso8601_health_is_utc():
    stamp = datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)
    node = {
        "id": "c8ba20e9-e197-4ec5-8764-4da672128589",
        "label": "host1",
        "version": "1:0",
        "health": "2026-10-12T00:00:00Z",
    }
    fresh = evaluate(_snapshot([node]), now_utc=stamp.timestamp() + 5)
    assert "heartbeat_stale" not in {code for _check, code in _codes(fresh)}
    stale = evaluate(_snapshot([node]), now_utc=stamp.timestamp() + 30)
    finding = next(item for item in stale if item.code == "heartbeat_stale")
    assert finding.details["timescale"] == "utc"
    assert finding.details["age_seconds"] == 30


def test_empty_registry_skips_heartbeat_and_has_no_duplicates():
    findings = evaluate(_snapshot([]), now_utc=0)
    assert ("R02", "no_nodes") in _codes(findings)
    assert ("R05", "no_duplicate_ids") in _codes(findings)


def test_duplicate_uuid_is_case_insensitive_within_nodes():
    findings = evaluate(_snapshot(load_json("nodes-duplicate.json")))
    finding = next(item for item in findings if item.code == "duplicate_id")
    assert finding.severity == "error"
    assert finding.check_id == "R05"
    assert finding.details["uuid"] == "c8ba20e9-e197-4ec5-8764-4da672128589"
    assert finding.details["count"] == 2


def test_same_uuid_on_a_device_and_a_sender_is_a_duplicate():
    findings = evaluate(
        _snapshot(
            load_json("nodes.json"),
            load_json("devices.json"),
            load_json("senders-duplicate-device.json"),
            load_json("receivers.json"),
        )
    )
    finding = next(item for item in findings if item.code == "duplicate_id")
    types = {item["type"] for item in finding.details["resources"]}
    assert types == {"device", "sender"}


def test_identical_copies_in_one_response_are_still_duplicates():
    node = load_json("nodes.json")[0]
    findings = evaluate(_snapshot([node, dict(node)]))
    assert any(finding.code == "duplicate_id" for finding in findings)


def test_non_uuid_ids_are_not_r05():
    raw = {"id": "not-a-uuid", "label": "x", "version": "1:0"}
    findings = evaluate(_snapshot([raw, dict(raw)]))
    assert ("R05", "no_duplicate_ids") in _codes(findings)
