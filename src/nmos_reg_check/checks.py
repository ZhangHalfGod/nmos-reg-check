"""R01, R02, and R05 against a Query API snapshot.

R02 reads heartbeat fields when a node carries them. The IS-04 node ``version``
value is the last time an attribute changed (TAI ``seconds:nanoseconds``), not
a registration heartbeat, so it is intentionally ignored. Stock Query API node
documents do not include ``health``; the Registration API debug read
``GET /health/nodes/{nodeId}`` is outside this Query-only client. Missing
heartbeat fields produce an info result rather than an error.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from nmos_reg_check.client import COLLECTIONS, Snapshot

# IS-04 default registration garbage-collection interval. A heartbeat is stale
# only when it is older than this interval ("greater than", not "greater or equal").
HEARTBEAT_EXPIRY_SECONDS = 12
# TAI - UTC, unchanged since 2017-01-01. nmos-cpp records heartbeat `health`
# seconds on the TAI clock, the same epoch as resource `version`.
TAI_UTC_OFFSET_SECONDS = 37

HEALTH_FIELDS = ("health", "heartbeat", "last_heartbeat", "heartbeat_timestamp", "last_seen")
_OBJECT_TIME_FIELDS = (
    "health",
    "timestamp",
    "seconds",
    "tai",
    "last_heartbeat",
    "heartbeat",
    "last_seen",
    "time",
    "updated",
)
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

Severity = Literal["ok", "info", "error"]


@dataclass(frozen=True)
class Finding:
    check_id: str
    severity: Severity
    code: str
    message_key: str
    message_params: dict[str, Any] = field(default_factory=dict)
    resource_type: str | None = None
    resource_id: str | None = None
    resource_label: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HealthValue:
    seconds: float
    timescale: str


def evaluate(snapshot: Snapshot, *, now_utc: float | None = None) -> list[Finding]:
    """Run R01 (already reachable), R02, and R05."""

    clock = time.time() if now_utc is None else now_utc
    findings = [
        Finding(
            check_id="R01",
            severity="ok",
            code="query_api_reachable",
            message_key="r01_ok",
            message_params={"version": snapshot.version},
            details={"version": snapshot.version, "query_url": snapshot.query_url},
        )
    ]
    findings.extend(_heartbeats(snapshot, clock))
    findings.extend(_duplicates(snapshot))
    return findings


def connection_finding(detail: str) -> Finding:
    return Finding(
        check_id="R01",
        severity="error",
        code="registry_unreachable",
        message_key="r01_connection",
        message_params={"detail": detail},
        details={"detail": detail},
    )


def api_finding(detail: str) -> Finding:
    return Finding(
        check_id="R01",
        severity="error",
        code="query_api_unusable",
        message_key="r01_api",
        message_params={"detail": detail},
        details={"detail": detail},
    )


def usage_finding(message_key: str, **params: str) -> Finding:
    return Finding(
        check_id="R01",
        severity="error",
        code=message_key,
        message_key=message_key,
        message_params=dict(params),
        details=dict(params),
    )


def discovery_finding(message_key: str, **params: Any) -> Finding:
    return Finding(
        check_id="MDNS",
        severity="error",
        code=message_key,
        message_key=message_key,
        message_params=dict(params),
        details=dict(params),
    )


def registry_required_finding() -> Finding:
    return Finding(
        check_id="CLI",
        severity="error",
        code="registry_required",
        message_key="registry_required",
    )


def _heartbeats(snapshot: Snapshot, now_utc: float) -> list[Finding]:
    nodes = snapshot.resources.get("nodes", [])
    if not nodes:
        return [
            Finding(
                check_id="R02",
                severity="info",
                code="no_nodes",
                message_key="r02_no_nodes",
            )
        ]

    stale: list[Finding] = []
    unrecognized: list[Finding] = []
    fresh = 0
    absent = 0
    for node in nodes:
        extracted = extract_health(node.raw)
        if extracted is None:
            absent += 1
            continue
        if extracted == "unrecognized":
            unrecognized.append(
                Finding(
                    check_id="R02",
                    severity="info",
                    code="heartbeat_unrecognized",
                    message_key="r02_unparsed",
                    resource_type="node",
                    resource_id=node.id,
                    resource_label=node.label,
                )
            )
            continue
        age = age_seconds(extracted, now_utc)
        if age > HEARTBEAT_EXPIRY_SECONDS:
            stale.append(
                Finding(
                    check_id="R02",
                    severity="error",
                    code="heartbeat_stale",
                    message_key="r02_stale",
                    message_params={
                        "age": format_seconds(age),
                        "threshold": str(HEARTBEAT_EXPIRY_SECONDS),
                    },
                    resource_type="node",
                    resource_id=node.id,
                    resource_label=node.label,
                    details={
                        "age_seconds": round(age, 3),
                        "threshold_seconds": HEARTBEAT_EXPIRY_SECONDS,
                        "timescale": extracted.timescale,
                    },
                )
            )
        else:
            fresh += 1

    findings: list[Finding] = list(stale)
    findings.extend(unrecognized)
    if absent and absent == len(nodes):
        findings.append(
            Finding(
                check_id="R02",
                severity="info",
                code="heartbeat_absent",
                message_key="r02_absent",
                details={"nodes": absent},
            )
        )
    elif absent:
        findings.append(
            Finding(
                check_id="R02",
                severity="info",
                code="heartbeat_missing_on_some",
                message_key="r02_partial",
                message_params={"count": absent},
                details={"count": absent},
            )
        )

    if fresh:
        findings.append(
            Finding(
                check_id="R02",
                severity="ok",
                code="heartbeat_ok",
                message_key="r02_ok",
                message_params={"count": fresh, "threshold": str(HEARTBEAT_EXPIRY_SECONDS)},
                details={"count": fresh, "threshold_seconds": HEARTBEAT_EXPIRY_SECONDS},
            )
        )
    return findings


def extract_health(raw: dict[str, Any]) -> HealthValue | Literal["unrecognized"] | None:
    """Return a timestamp from known heartbeat fields, if the node has one."""

    present = False
    for key in HEALTH_FIELDS:
        if key not in raw:
            continue
        value = raw[key]
        if value is None or value == "":
            continue
        present = True
        parsed = parse_timestamp(value)
        if parsed is not None:
            return parsed
    if present:
        return "unrecognized"
    return None


def parse_timestamp(value: Any) -> HealthValue | None:
    if isinstance(value, dict):
        for key in _OBJECT_TIME_FIELDS:
            if key in value and value[key] not in (None, ""):
                parsed = parse_timestamp(value[key])
                if parsed is not None:
                    return parsed
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    if isinstance(value, (int, float)):
        return _from_number(float(value))
    text = value.strip()
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", text):
        return _from_number(float(text))
    version_match = re.fullmatch(r"([0-9]+):([0-9]+)", text)
    if version_match:
        return _from_number(float(version_match.group(1)))
    iso = _parse_iso(text)
    if iso is None:
        return None
    return HealthValue(seconds=iso, timescale="utc")


def age_seconds(health: HealthValue, now_utc: float) -> float:
    now = now_utc + TAI_UTC_OFFSET_SECONDS if health.timescale == "tai" else now_utc
    return now - health.seconds


def format_seconds(value: float) -> str:
    rounded = round(value)
    if abs(value - rounded) < 0.05:
        return str(int(rounded))
    return f"{value:.1f}"


def _from_number(number: float) -> HealthValue | None:
    if number < 0:
        return None
    if number >= 1e14:
        number /= 1_000_000
    elif number >= 1e11:
        number /= 1_000
    return HealthValue(seconds=number, timescale="tai")


def _parse_iso(text: str) -> float | None:
    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _duplicates(snapshot: Snapshot) -> list[Finding]:
    groups: dict[str, list[dict[str, str | None]]] = {}
    order: list[str] = []
    for collection in COLLECTIONS:
        for resource in snapshot.resources.get(collection, []):
            canonical = _canonical_uuid(resource.id)
            if canonical is None:
                continue
            if canonical not in groups:
                groups[canonical] = []
                order.append(canonical)
            groups[canonical].append(
                {
                    "type": resource.type,
                    "id": resource.id,
                    "label": resource.label,
                }
            )

    findings: list[Finding] = []
    for canonical in order:
        members = groups[canonical]
        if len(members) < 2:
            continue
        findings.append(
            Finding(
                check_id="R05",
                severity="error",
                code="duplicate_id",
                message_key="r05_duplicate",
                message_params={"uuid": canonical, "count": len(members)},
                details={"uuid": canonical, "count": len(members), "resources": members},
            )
        )
    if findings:
        return findings
    return [
        Finding(
            check_id="R05",
            severity="ok",
            code="no_duplicate_ids",
            message_key="r05_ok",
        )
    ]


def _canonical_uuid(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip().lower()
    if _UUID.fullmatch(text):
        return text
    return None
