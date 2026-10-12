"""Text and JSON reports for registry checks."""

from __future__ import annotations

import json
import unicodedata
from typing import Any

from nmos_reg_check import __version__
from nmos_reg_check.checks import Finding

TYPE_NAMES = {
    "en": {
        "node": "node",
        "device": "device",
        "sender": "sender",
        "receiver": "receiver",
    },
    "zh": {
        "node": "节点",
        "device": "设备",
        "sender": "发送器",
        "receiver": "接收器",
    },
}

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "header_registry": "Registry: {url}",
        "header_query": "Query API: {version} {url}",
        "header_counts": "Resources: nodes={nodes}, devices={devices}, senders={senders}, receivers={receivers}",
        "col_check": "Check",
        "col_severity": "Severity",
        "col_resource": "Resource",
        "col_message": "Message",
        "severity_ok": "ok",
        "severity_info": "info",
        "severity_error": "error",
        "summary": "{errors}, {info}, {ok}",
        "error_word": "error",
        "errors_word": "errors",
        "info_word": "info",
        "ok_word": "ok",
        "r01_ok": "Query API {version} is reachable",
        "r01_connection": "Cannot connect to the registry: {detail}",
        "r01_api": "Query API is not usable: {detail}",
        "registry_url_invalid": "Registry URL must start with http:// or https:// and include a host.",
        "registry_url_unrecognized": "Cannot find an IS-04 Query API in '{url}'. Pass an origin, a /x-nmos/query/ URL, or a /x-nmos/query/v1.x/ URL.",
        "r02_no_nodes": "No nodes are registered; heartbeat check skipped",
        "r02_absent": "Nodes have no health or heartbeat field; heartbeat check skipped",
        "r02_unparsed": "Health field is present but is not a recognized timestamp",
        "r02_stale": "Heartbeat is stale ({age}s old; limit {threshold}s)",
        "mdns_only": "mDNS discovery is not implemented in W1. Pass --registry with an http or https IS-04 Query API URL.",
        "mdns_ignored": "mDNS discovery is not implemented in W1; continuing with --registry.",
        "registry_required": "Pass --registry with an http or https IS-04 Query API URL.",
        "r05_ok": "No duplicate UUIDs in nodes, devices, senders, or receivers",
        "r05_duplicate": "UUID {uuid} is used by {count} resources: {places}",
    },
    "zh": {
        "header_registry": "注册中心: {url}",
        "header_query": "Query API: {version} {url}",
        "header_counts": "资源: 节点={nodes}，设备={devices}，发送器={senders}，接收器={receivers}",
        "col_check": "检查项",
        "col_severity": "级别",
        "col_resource": "资源",
        "col_message": "说明",
        "severity_ok": "正常",
        "severity_info": "信息",
        "severity_error": "错误",
        "summary": "{errors}，{info}，{ok}",
        "error_word": "个错误",
        "errors_word": "个错误",
        "info_word": "条信息",
        "ok_word": "个正常",
        "r01_ok": "Query API {version} 可达，版本协商成功",
        "r01_connection": "无法连接注册中心：{detail}",
        "r01_api": "Query API 不可用：{detail}",
        "registry_url_invalid": "注册中心地址必须以 http:// 或 https:// 开头，并包含主机名。",
        "registry_url_unrecognized": "无法从“{url}”识别 IS-04 Query API。请传入主机根地址、/x-nmos/query/ 或 /x-nmos/query/v1.x/。",
        "r02_no_nodes": "注册中心没有节点，已跳过心跳检查",
        "r02_absent": "节点没有 health/heartbeat 字段，已跳过心跳检查",
        "r02_unparsed": "存在 health 字段，但不是可识别的时间戳",
        "r02_stale": "心跳已过期（已过去 {age} 秒，上限 {threshold} 秒）",
        "mdns_only": "W1 尚未实现 mDNS 发现。请使用 --registry 传入 http 或 https 的 IS-04 Query API 地址。",
        "mdns_ignored": "W1 尚未实现 mDNS 发现；将继续使用 --registry。",
        "registry_required": "请使用 --registry 传入 http 或 https 的 IS-04 Query API 地址。",
        "r05_ok": "节点、设备、发送器、接收器中没有重复 UUID",
        "r05_duplicate": "UUID {uuid} 被 {count} 个资源使用：{places}",
    },
}


def text(lang: str, key: str, **params: Any) -> str:
    return STRINGS[lang][key].format(**params)


def make_report(
    *,
    registry_url: str | None,
    query_url: str | None,
    query_version: str | None,
    counts: dict[str, int],
    findings: list[Finding],
    lang: str,
    exit_code: int,
) -> dict[str, Any]:
    summary = {
        "error": sum(1 for finding in findings if finding.severity == "error"),
        "info": sum(1 for finding in findings if finding.severity == "info"),
        "ok": sum(1 for finding in findings if finding.severity == "ok"),
    }
    return {
        "tool": "nmos-reg-check",
        "version": __version__,
        "lang": lang,
        "registry_url": registry_url,
        "query_url": query_url,
        "query_version": query_version,
        "ok": exit_code == 0,
        "exit_code": exit_code,
        "counts": {
            "nodes": counts.get("nodes", 0),
            "devices": counts.get("devices", 0),
            "senders": counts.get("senders", 0),
            "receivers": counts.get("receivers", 0),
        },
        "summary": summary,
        "findings": [_finding_json(finding, lang) for finding in findings],
    }


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"


def render_text(report: dict[str, Any]) -> str:
    lang = report["lang"]
    strings = STRINGS[lang]
    counts = report["counts"]
    lines = [
        strings["header_registry"].format(url=report["registry_url"] or "-"),
        strings["header_query"].format(
            version=report["query_version"] or "-",
            url=report["query_url"] or "-",
        ),
        strings["header_counts"].format(
            nodes=counts["nodes"],
            devices=counts["devices"],
            senders=counts["senders"],
            receivers=counts["receivers"],
        ),
        "",
    ]
    header = [
        strings["col_check"],
        strings["col_severity"],
        strings["col_resource"],
        strings["col_message"],
    ]
    rows = [header]
    for finding in report["findings"]:
        rows.append(
            [
                finding["id"],
                strings[f"severity_{finding['severity']}"],
                _resource_cell(finding, lang),
                finding["message"],
            ]
        )
    widths = [
        max(_display_width(row[index]) for row in rows)
        for index in range(4)
    ]
    lines.append(_format_row(rows[0], widths))
    lines.append("  ".join("-" * width for width in widths))
    for row in rows[1:]:
        lines.append(_format_row(row, widths))
    lines.append("")
    lines.append(_summary_line(report, lang))
    lines.append("")
    return "\n".join(lines)


def localize(finding: Finding, lang: str) -> str:
    params = dict(finding.message_params)
    key = finding.message_key
    if key == "r05_duplicate":
        params["places"] = ", ".join(
            _describe(item, lang) for item in finding.details.get("resources", [])
        )
        return STRINGS[lang][key].format(**params)
    if key == "r02_partial":
        count = int(finding.message_params["count"])
        if lang == "zh":
            return f"{count} 个节点没有 health/heartbeat 字段，已跳过这些节点"
        noun = "node" if count == 1 else "nodes"
        return f"{count} {noun} have no health or heartbeat field; those nodes were skipped"
    if key == "r02_ok":
        count = int(finding.message_params["count"])
        threshold = finding.message_params["threshold"]
        if lang == "zh":
            return f"{count} 个节点的心跳未超过 {threshold} 秒"
        noun = "node" if count == 1 else "nodes"
        return f"Heartbeats for {count} {noun} are within {threshold}s"
    return STRINGS[lang][key].format(**params)


def _finding_json(finding: Finding, lang: str) -> dict[str, Any]:
    return {
        "id": finding.check_id,
        "severity": finding.severity,
        "code": finding.code,
        "resource_type": finding.resource_type,
        "resource_id": finding.resource_id,
        "resource_label": finding.resource_label,
        "message": localize(finding, lang),
        "details": finding.details,
    }


def _describe(item: dict[str, Any], lang: str) -> str:
    type_name = TYPE_NAMES[lang].get(str(item.get("type")), str(item.get("type")))
    label = item.get("label")
    ident = item.get("id")
    if label and ident:
        return f"{type_name} {label} ({ident})"
    if label:
        return f"{type_name} {label}"
    return f"{type_name} {ident}"


def _resource_cell(finding: dict[str, Any], lang: str) -> str:
    resource_type = finding.get("resource_type")
    resource_id = finding.get("resource_id")
    if not resource_type and not resource_id:
        return "-"
    type_name = TYPE_NAMES[lang].get(resource_type or "", resource_type or "")
    label = finding.get("resource_label")
    if resource_id and label:
        return f"{type_name} {resource_id} ({label})"
    if resource_id:
        return f"{type_name} {resource_id}"
    return type_name or "-"


def _summary_line(report: dict[str, Any], lang: str) -> str:
    summary = report["summary"]
    strings = STRINGS[lang]
    errors = summary["error"]
    error_word = strings["error_word"] if errors == 1 else strings["errors_word"]
    if lang == "zh":
        rendered = {
            "errors": f"{errors} {strings['errors_word']}",
            "info": f"{summary['info']} {strings['info_word']}",
            "ok": f"{summary['ok']} {strings['ok_word']}",
        }
    else:
        rendered = {
            "errors": f"{errors} {error_word}",
            "info": f"{summary['info']} {strings['info_word']}",
            "ok": f"{summary['ok']} {strings['ok_word']}",
        }
    return strings["summary"].format(**rendered)


def _format_row(columns: list[str], widths: list[int]) -> str:
    padded = [_pad(columns[index], widths[index]) for index in range(3)]
    return "  ".join(padded + [columns[3]])


def _pad(text: str, width: int) -> str:
    gap = width - _display_width(text)
    if gap <= 0:
        return text
    return text + (" " * gap)


def _display_width(text: str) -> int:
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in ("F", "W") else 1
    return width
