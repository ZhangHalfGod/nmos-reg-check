"""Command-line entry point for nmos-reg-check."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any, Sequence

import httpx

from nmos_reg_check import __version__
from nmos_reg_check.checks import (
    Finding,
    api_finding,
    connection_finding,
    discovery_finding,
    evaluate,
    registry_required_finding,
    usage_finding,
)
from nmos_reg_check.client import RegistryError, UsageError, load_snapshot
from nmos_reg_check.discovery import (
    DEFAULT_MDNS_TIMEOUT,
    DiscoveryError,
    DiscoveryResult,
    browse_nmos_services,
    discovery_payload,
    empty_discovery_reason,
    format_timeout,
    parse_timeout,
)
from nmos_reg_check.report import discovery_notice, make_report, render_json, render_text, text

_EMPTY_COUNTS = {"nodes": 0, "devices": 0, "senders": 0, "receivers": 0}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nmos-reg-check",
        description=(
            "Check an NMOS IS-04 registry through the read-only Query API "
            "(reachability, stale heartbeats, duplicate UUIDs)."
        ),
        epilog=(
            "examples:\n"
            "  nmos-reg-check --registry http://192.168.1.20:8080\n"
            "  nmos-reg-check --mdns\n"
            "  nmos-reg-check --mdns --mdns-timeout 5 --lang zh\n"
            "  nmos-reg-check --registry https://registry.example/x-nmos/query/v1.3/ --json\n"
            "\n"
            "When both --registry and --mdns are set, the explicit URL is used\n"
            "and mDNS is not browsed.\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--registry",
        metavar="URL",
        help="Registry origin or IS-04 Query API URL (http or https)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the report as JSON on stdout",
    )
    parser.add_argument(
        "--lang",
        choices=("en", "zh"),
        default="en",
        help="Report language (default: en)",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Do not verify TLS certificates",
    )
    parser.add_argument(
        "--mdns",
        action="store_true",
        help=(
            "Discover an IS-04 registry with mDNS (DNS-SD) and check its Query API. "
            "Ignored when --registry is set"
        ),
    )
    parser.add_argument(
        "--mdns-timeout",
        metavar="SECONDS",
        help=(
            "Seconds to wait for mDNS responses "
            f"(default: {format_timeout(DEFAULT_MDNS_TIMEOUT)}). "
            "Used when --mdns browses the network"
        ),
    )
    parser.add_argument("--version", action="version", version=f"nmos-reg-check {__version__}")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    now_utc: float | None = None,
    discover: Any | None = None,
) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        code = exc.code
        return 0 if code is None else int(code)

    timeout = DEFAULT_MDNS_TIMEOUT
    if args.mdns_timeout is not None:
        try:
            timeout = parse_timeout(args.mdns_timeout)
        except ValueError:
            report = _report_for(
                registry_url=None,
                query_url=None,
                query_version=None,
                counts=_EMPTY_COUNTS,
                findings=[discovery_finding("mdns_timeout_invalid")],
                lang=args.lang,
                exit_code=2,
            )
            _emit(report, as_json=args.json)
            return 2

    if args.mdns and args.registry:
        print(text(args.lang, "mdns_ignored"), file=sys.stderr)

    discovery: dict[str, Any] | None = None
    registry_url = args.registry
    if not registry_url:
        if not args.mdns:
            report = _report_for(
                registry_url=None,
                query_url=None,
                query_version=None,
                counts=_EMPTY_COUNTS,
                findings=[registry_required_finding()],
                lang=args.lang,
                exit_code=2,
            )
            _emit(report, as_json=args.json)
            return 2
        found = _discover(timeout=timeout, lang=args.lang, discover=discover)
        if found.finding is not None:
            report = _report_for(
                registry_url=None,
                query_url=None,
                query_version=None,
                counts=_EMPTY_COUNTS,
                findings=[found.finding],
                lang=args.lang,
                exit_code=2,
            )
            _emit(report, as_json=args.json)
            return 2
        registry_url = found.url
        discovery = found.meta

    assert registry_url is not None
    try:
        snapshot = load_snapshot(
            registry_url,
            insecure=args.insecure,
            transport=transport,
        )
    except UsageError as exc:
        report = _report_for(
            registry_url=registry_url,
            query_url=None,
            query_version=None,
            counts=_EMPTY_COUNTS,
            findings=[usage_finding(exc.message_key, **exc.params)],
            lang=args.lang,
            exit_code=2,
            discovery=discovery,
        )
        _emit(report, as_json=args.json)
        return 2
    except RegistryError as exc:
        finding = connection_finding(str(exc)) if exc.kind == "connection" else api_finding(str(exc))
        exit_code = 2 if exc.kind == "connection" else 1
        report = _report_for(
            registry_url=registry_url.strip(),
            query_url=None,
            query_version=None,
            counts=_EMPTY_COUNTS,
            findings=[finding],
            lang=args.lang,
            exit_code=exit_code,
            discovery=discovery,
        )
        _emit(report, as_json=args.json)
        return exit_code

    findings = evaluate(snapshot, now_utc=now_utc)
    exit_code = 1 if any(finding.severity == "error" for finding in findings) else 0
    report = _report_for(
        registry_url=snapshot.registry_url,
        query_url=snapshot.query_url,
        query_version=snapshot.version,
        counts=snapshot.counts(),
        findings=findings,
        lang=args.lang,
        exit_code=exit_code,
        discovery=discovery,
    )
    _emit(report, as_json=args.json)
    return exit_code


def console_main() -> None:
    sys.exit(main())


@dataclass(frozen=True)
class _FoundRegistry:
    url: str | None = None
    meta: dict[str, Any] | None = None
    finding: Finding | None = None


def _discover(
    *,
    timeout: float,
    lang: str,
    discover: Any | None,
) -> _FoundRegistry:
    browse = discover or browse_nmos_services
    try:
        result = browse(timeout=timeout)
    except DiscoveryError as exc:
        detail = exc.detail.strip() or "mDNS error"
        return _FoundRegistry(finding=discovery_finding("mdns_failed", detail=detail))
    if not isinstance(result, DiscoveryResult):
        raise TypeError("discover() must return a DiscoveryResult")
    chosen = result.chosen
    if chosen is None:
        key, params = empty_discovery_reason(result)
        if key == "mdns_none":
            params = {"timeout": format_timeout(timeout)}
        return _FoundRegistry(finding=discovery_finding(key, **params))
    meta = discovery_payload(result)
    print(discovery_notice(lang, meta), file=sys.stderr)
    return _FoundRegistry(url=chosen.url, meta=meta)


def _report_for(
    *,
    registry_url: str | None,
    query_url: str | None,
    query_version: str | None,
    counts: dict[str, int],
    findings: list[Finding],
    lang: str,
    exit_code: int,
    discovery: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return make_report(
        registry_url=registry_url,
        query_url=query_url,
        query_version=query_version,
        counts=counts,
        findings=findings,
        lang=lang,
        exit_code=exit_code,
        discovery=discovery,
    )


def _emit(report: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        sys.stdout.write(render_json(report))
    else:
        sys.stdout.write(render_text(report))
