"""CLI exit codes, languages, and the mDNS stub."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlsplit

import httpx
import pytest

from nmos_reg_check.cli import main
from nmos_reg_check.client import create_client
from tests.conftest import REGISTRY, healthy_routes, load_json, scripted_transport

HEALTH = 1441974485


def _run(argv: list[str], **kwargs) -> tuple[int, str, str]:
    capsys = kwargs.pop("capsys")
    code = main(argv, **kwargs)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_help_and_version(capsys: pytest.CaptureFixture[str]):
    assert main(["--help"]) == 0
    help_text = capsys.readouterr().out
    assert "--registry" in help_text
    assert "--json" in help_text
    assert "--lang" in help_text
    assert "--insecure" in help_text
    assert "--mdns" in help_text

    assert main(["--version"]) == 0
    assert "nmos-reg-check" in capsys.readouterr().out


def test_healthy_registry_exits_zero_and_json_report(capsys: pytest.CaptureFixture[str]):
    code = main(
        ["--registry", REGISTRY, "--json"],
        transport=scripted_transport(healthy_routes()),
    )
    captured = capsys.readouterr()
    assert code == 0
    report = json.loads(captured.out)
    assert report["ok"] is True
    assert report["exit_code"] == 0
    assert report["query_version"] == "v1.3"
    assert report["counts"] == {"nodes": 2, "devices": 2, "senders": 1, "receivers": 1}
    codes = [(item["id"], item["code"], item["severity"]) for item in report["findings"]]
    assert ("R01", "query_api_reachable", "ok") in codes
    assert ("R02", "heartbeat_absent", "info") in codes
    assert ("R05", "no_duplicate_ids", "ok") in codes
    assert report["summary"] == {"error": 0, "info": 1, "ok": 2}


def test_text_report_names_the_query_version(capsys: pytest.CaptureFixture[str]):
    code = main(["--registry", REGISTRY], transport=scripted_transport(healthy_routes()))
    captured = capsys.readouterr()
    assert code == 0
    assert "Query API v1.3 is reachable" in captured.out
    assert "heartbeat check skipped" in captured.out
    assert "No duplicate UUIDs" in captured.out
    assert captured.out.endswith("0 errors, 1 info, 2 ok\n")


def test_chinese_report(capsys: pytest.CaptureFixture[str]):
    code = main(
        ["--registry", REGISTRY, "--lang", "zh", "--json"],
        transport=scripted_transport(healthy_routes()),
    )
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    messages = " ".join(item["message"] for item in report["findings"])
    assert "版本协商成功" in messages
    assert "心跳" in messages
    assert "重复 UUID" in messages


def test_stale_heartbeat_exits_one(capsys: pytest.CaptureFixture[str]):
    routes = healthy_routes(
        **{"/x-nmos/query/v1.3/nodes": load_json("nodes-with-health.json")}
    )
    now = HEALTH + 40 - 37
    code = main(
        ["--registry", REGISTRY, "--json"],
        transport=scripted_transport(routes),
        now_utc=now,
    )
    report = json.loads(capsys.readouterr().out)
    assert code == 1
    assert report["exit_code"] == 1
    assert report["ok"] is False
    stale = next(item for item in report["findings"] if item["code"] == "heartbeat_stale")
    assert stale["severity"] == "error"
    assert "host1" in stale["message"] or stale["resource_label"] == "host1"


def test_duplicate_uuid_exits_one(capsys: pytest.CaptureFixture[str]):
    routes = healthy_routes(
        **{"/x-nmos/query/v1.3/nodes": load_json("nodes-duplicate.json")}
    )
    code = main(
        ["--registry", REGISTRY, "--json"],
        transport=scripted_transport(routes),
    )
    report = json.loads(capsys.readouterr().out)
    assert code == 1
    duplicate = next(item for item in report["findings"] if item["code"] == "duplicate_id")
    assert "c8ba20e9-e197-4ec5-8764-4da672128589" in duplicate["message"]
    assert "host1" in duplicate["message"]


def test_connect_failure_exits_two(capsys: pytest.CaptureFixture[str]):
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    code = main(
        ["--registry", REGISTRY, "--json"],
        transport=httpx.MockTransport(handler),
    )
    report = json.loads(capsys.readouterr().out)
    assert code == 2
    assert report["exit_code"] == 2
    assert report["findings"][0]["id"] == "R01"
    assert report["findings"][0]["code"] == "registry_unreachable"
    assert report["findings"][0]["severity"] == "error"


def test_unusable_api_exits_one(capsys: pytest.CaptureFixture[str]):
    routes = healthy_routes()
    routes["/x-nmos/query/"] = load_json("query-v2-only.json")
    code = main(["--registry", REGISTRY, "--json"], transport=scripted_transport(routes))
    report = json.loads(capsys.readouterr().out)
    assert code == 1
    assert report["findings"][0]["code"] == "query_api_unusable"
    assert len(report["findings"]) == 1


def test_bad_url_exits_two(capsys: pytest.CaptureFixture[str]):
    code = main(["--registry", "ftp://registry.example", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert code == 2
    assert report["findings"][0]["code"] == "registry_url_invalid"


def test_missing_registry_exits_two(capsys: pytest.CaptureFixture[str]):
    code = main(["--lang", "en"])
    captured = capsys.readouterr()
    assert code == 2
    assert "Pass --registry" in captured.out


def test_mdns_alone_is_not_implemented(capsys: pytest.CaptureFixture[str]):
    code = main(["--mdns", "--lang", "zh", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert code == 2
    assert report["exit_code"] == 2
    assert report["findings"][0]["code"] == "mdns_not_implemented"
    assert "尚未实现" in report["findings"][0]["message"]


def test_mdns_with_registry_warns_and_uses_the_url(capsys: pytest.CaptureFixture[str]):
    code = main(
        ["--mdns", "--registry", REGISTRY],
        transport=scripted_transport(healthy_routes()),
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "not implemented in W1" in captured.err
    assert "Query API v1.3 is reachable" in captured.out


def test_insecure_flag_disables_tls_verification(monkeypatch: pytest.MonkeyPatch):
    seen: dict[str, object] = {}
    real = create_client

    def spy(**kwargs: object) -> httpx.Client:
        seen["insecure"] = kwargs["insecure"]
        kwargs["transport"] = scripted_transport(healthy_routes())
        return real(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("nmos_reg_check.client.create_client", spy)
    code = main(["--registry", "https://registry.example", "--insecure"])
    assert code == 0
    assert seen["insecure"] is True


def test_invalid_language_exits_two(capsys: pytest.CaptureFixture[str]):
    assert main(["--registry", REGISTRY, "--lang", "fr"]) == 2
    assert "invalid choice" in capsys.readouterr().err


def test_loopback_registry_matches_the_fixture_report():
    routes = {
        "/x-nmos/": load_json("x-nmos-query-only.json"),
        "/x-nmos": load_json("x-nmos-query-only.json"),
        "/x-nmos/query/": load_json("query-versions.json"),
        "/x-nmos/query": load_json("query-versions.json"),
        "/x-nmos/query/v1.3/": load_json("query-root.json"),
        "/x-nmos/query/v1.3": load_json("query-root.json"),
        "/x-nmos/query/v1.3/nodes": load_json("nodes.json"),
        "/x-nmos/query/v1.3/devices": load_json("devices.json"),
        "/x-nmos/query/v1.3/senders": load_json("senders.json"),
        "/x-nmos/query/v1.3/receivers": load_json("receivers.json"),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            body = routes.get(path)
            if body is None:
                payload = json.dumps(
                    {"code": 404, "error": f"no route {path}", "debug": None}
                ).encode()
                self.send_response(404)
            else:
                payload = json.dumps(body).encode()
                self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        code = main(["--registry", f"http://127.0.0.1:{port}", "--json"])
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert code == 0
