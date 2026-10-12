"""Fixture loading and an in-process Query API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

FIXTURES = Path(__file__).parent / "fixtures"
REGISTRY = "http://registry.test:8080"


def load_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def route_key(url: httpx.URL) -> str:
    path = url.path
    query = url.query.decode() if isinstance(url.query, bytes) else str(url.query or "")
    if query:
        return f"{path}?{query}"
    return path


def scripted_transport(
    routes: dict[str, Any],
    recorder: list[tuple[str, str]] | None = None,
) -> httpx.MockTransport:
    """Map request paths to JSON bodies, ``(status, body)``, or ``(status, body, headers)``."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = route_key(request.url)
        if recorder is not None:
            recorder.append((request.method, key))
        if request.method != "GET":
            return httpx.Response(
                405,
                json={"code": 405, "error": "method not allowed", "debug": None},
            )
        if key not in routes:
            return httpx.Response(
                404,
                json={"code": 404, "error": f"no route {key}", "debug": None},
            )
        spec = routes[key]
        headers: dict[str, str] = {}
        if isinstance(spec, tuple):
            status, body = spec[0], spec[1]
            if len(spec) > 2:
                headers = spec[2]
        else:
            status, body = 200, spec
        if isinstance(body, (dict, list)):
            return httpx.Response(status, json=body, headers=headers)
        if isinstance(body, bytes):
            return httpx.Response(status, content=body, headers=headers)
        return httpx.Response(status, content=str(body).encode(), headers=headers)

    return httpx.MockTransport(handler)


def healthy_routes(**overrides: Any) -> dict[str, Any]:
    routes: dict[str, Any] = {
        "/x-nmos/": load_json("x-nmos-query-only.json"),
        "/x-nmos/query/": load_json("query-versions.json"),
        "/x-nmos/query/v1.3/": load_json("query-root.json"),
        "/x-nmos/query/v1.3/nodes": load_json("nodes.json"),
        "/x-nmos/query/v1.3/devices": load_json("devices.json"),
        "/x-nmos/query/v1.3/senders": load_json("senders.json"),
        "/x-nmos/query/v1.3/receivers": load_json("receivers.json"),
    }
    routes.update(overrides)
    return routes
