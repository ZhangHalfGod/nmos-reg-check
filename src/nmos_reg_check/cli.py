"""Command-line entry point for nmos-reg-check."""

from __future__ import annotations

import argparse
import sys
from typing import Any, Sequence

import httpx

from nmos_reg_check import __version__
from nmos_reg_check.checks import (
    Finding,
    api_finding,
    connection_finding,
    evaluate,
    mdns_finding,
    registry_required_finding,
    usage_finding,
)
from nmos_reg_check.client import RegistryError, UsageError, load_snapshot
from nmos_reg_check.report import make_report, render_json, render_text, text

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
            "  nmos-reg-check --registry https://registry.example/x-nmos/query/v1.3/ --json\n"
            "  nmos-reg-check --registry https://registry.example:8443 --insecure --lang zh\n"
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
        help="Discover a registry with mDNS (not implemented in W1)",
    )
    parser.add_argument("--version", action="version", version=f"nmos-reg-check {__version__}")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    now_utc: float | None = None,
) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        code = exc.code
        return 0 if code is None else int(code)

    if args.mdns and not args.registry:
        report = _report_for(
            registry_url=None,
            query_url=None,
            query_version=None,
            counts=_EMPTY_COUNTS,
            findings=[mdns_finding()],
            lang=args.lang,
            exit_code=2,
        )
        _emit(report, as_json=args.json)
        return 2

    if args.mdns and args.registry:
        print(text(args.lang, "mdns_ignored"), file=sys.stderr)

    if not args.registry:
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

    try:
        snapshot = load_snapshot(
            args.registry,
            insecure=args.insecure,
            transport=transport,
        )
    except UsageError as exc:
        report = _report_for(
            registry_url=args.registry,
            query_url=None,
            query_version=None,
            counts=_EMPTY_COUNTS,
            findings=[usage_finding(exc.message_key, **exc.params)],
            lang=args.lang,
            exit_code=2,
        )
        _emit(report, as_json=args.json)
        return 2
    except RegistryError as exc:
        finding = connection_finding(str(exc)) if exc.kind == "connection" else api_finding(str(exc))
        exit_code = 2 if exc.kind == "connection" else 1
        report = _report_for(
            registry_url=args.registry.strip(),
            query_url=None,
            query_version=None,
            counts=_EMPTY_COUNTS,
            findings=[finding],
            lang=args.lang,
            exit_code=exit_code,
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
    )
    _emit(report, as_json=args.json)
    return exit_code


def console_main() -> None:
    sys.exit(main())


def _report_for(
    *,
    registry_url: str | None,
    query_url: str | None,
    query_version: str | None,
    counts: dict[str, int],
    findings: list[Finding],
    lang: str,
    exit_code: int,
) -> dict[str, Any]:
    return make_report(
        registry_url=registry_url,
        query_url=query_url,
        query_version=query_version,
        counts=counts,
        findings=findings,
        lang=lang,
        exit_code=exit_code,
    )


def _emit(report: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        sys.stdout.write(render_json(report))
    else:
        sys.stdout.write(render_text(report))
