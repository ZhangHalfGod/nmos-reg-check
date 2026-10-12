"""Query API discovery and collection reads, using recorded JSON fixtures."""

from __future__ import annotations

import httpx
import pytest

from nmos_reg_check.client import RegistryError, load_snapshot
from tests.conftest import REGISTRY, healthy_routes, load_json, scripted_transport


def test_discovers_highest_v1_and_loads_four_collections():
    seen: list[tuple[str, str]] = []
    snapshot = load_snapshot(REGISTRY, transport=scripted_transport(healthy_routes(), seen))

    assert snapshot.version == "v1.3"
    assert snapshot.query_url == f"{REGISTRY}/x-nmos/query/v1.3/"
    assert snapshot.counts() == {"nodes": 2, "devices": 2, "senders": 1, "receivers": 1}
    assert snapshot.resources["nodes"][0].id == "c8ba20e9-e197-4ec5-8764-4da672128589"
    assert snapshot.resources["nodes"][0].label == "host1"
    methods = {method for method, _path in seen}
    assert methods == {"GET"}
    assert "/x-nmos/query/v1.3/nodes" in {path for _method, path in seen}
    assert not any("/registration/" in path for _method, path in seen)


def test_explicit_version_url_skips_the_api_index():
    seen: list[tuple[str, str]] = []
    routes = {
        "/x-nmos/query/v1.2/": load_json("query-root.json"),
        "/x-nmos/query/v1.2/nodes": load_json("nodes.json"),
        "/x-nmos/query/v1.2/devices": [],
        "/x-nmos/query/v1.2/senders": [],
        "/x-nmos/query/v1.2/receivers": [],
    }
    snapshot = load_snapshot(
        f"{REGISTRY}/x-nmos/query/v1.2/nodes",
        transport=scripted_transport(routes, seen),
    )
    assert snapshot.version == "v1.2"
    assert snapshot.counts()["nodes"] == 2
    requested = [path for _method, path in seen]
    assert "/x-nmos/" not in requested
    assert "/x-nmos/query/" not in requested


def test_negotiates_v1_0_when_that_is_all_the_registry_offers():
    routes = healthy_routes()
    routes["/x-nmos/query/"] = load_json("query-v1.0-only.json")
    routes["/x-nmos/query/v1.0/"] = load_json("query-root.json")
    for name in ("nodes", "devices", "senders", "receivers"):
        routes[f"/x-nmos/query/v1.0/{name}"] = []
    snapshot = load_snapshot(REGISTRY, transport=scripted_transport(routes))
    assert snapshot.version == "v1.0"
    assert snapshot.counts()["nodes"] == 0


def test_v2_only_is_not_a_supported_query_api():
    routes = healthy_routes()
    routes["/x-nmos/query/"] = load_json("query-v2-only.json")
    with pytest.raises(RegistryError) as exc:
        load_snapshot(REGISTRY, transport=scripted_transport(routes))
    assert exc.value.kind == "api"
    assert "v1.x" in str(exc.value)


def test_missing_query_advertisement_is_an_api_error():
    routes = healthy_routes()
    routes["/x-nmos/"] = load_json("x-nmos-no-query.json")
    with pytest.raises(RegistryError) as exc:
        load_snapshot(REGISTRY, transport=scripted_transport(routes))
    assert exc.value.kind == "api"
    assert "Query API" in str(exc.value)


def test_http_error_body_is_included_in_the_api_error():
    routes = healthy_routes()
    routes["/x-nmos/query/v1.3/devices"] = (500, load_json("error-500.json"))
    with pytest.raises(RegistryError) as exc:
        load_snapshot(REGISTRY, transport=scripted_transport(routes))
    assert exc.value.kind == "api"
    assert "500" in str(exc.value)
    assert "registry backend unavailable" in str(exc.value)


def test_non_json_body_is_an_api_error():
    routes = healthy_routes(**{"/x-nmos/": (200, b"<html>dashboard</html>")})
    with pytest.raises(RegistryError) as exc:
        load_snapshot(REGISTRY, transport=scripted_transport(routes))
    assert exc.value.kind == "api"
    assert "not JSON" in str(exc.value)


def test_connection_failure_is_not_an_api_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(RegistryError) as exc:
        load_snapshot(REGISTRY, transport=httpx.MockTransport(handler))
    assert exc.value.kind == "connection"
    assert "connection refused" in str(exc.value)


def test_timeout_is_a_connection_failure():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out")

    with pytest.raises(RegistryError) as exc:
        load_snapshot(REGISTRY, transport=httpx.MockTransport(handler))
    assert exc.value.kind == "connection"
    assert "timed out" in str(exc.value)


def test_wrapped_single_and_data_collections():
    wrapped = healthy_routes(
        **{"/x-nmos/query/v1.3/nodes": load_json("nodes-wrapped.json")}
    )
    assert load_snapshot(REGISTRY, transport=scripted_transport(wrapped)).counts()["nodes"] == 1

    single = healthy_routes(
        **{"/x-nmos/query/v1.3/nodes": load_json("node-single.json")}
    )
    snapshot = load_snapshot(REGISTRY, transport=scripted_transport(single))
    assert snapshot.resources["nodes"][0].label == "host1"

    data = healthy_routes(
        **{"/x-nmos/query/v1.3/nodes": load_json("nodes-data-wrapper.json")}
    )
    assert load_snapshot(REGISTRY, transport=scripted_transport(data)).counts()["nodes"] == 1


def test_link_next_pages_and_drops_identical_overlap():
    link = (
        f'<{REGISTRY}/x-nmos/query/v1.3/nodes?paging.since=2>; rel="next"'
    )
    routes = healthy_routes(
        **{
            "/x-nmos/query/v1.3/nodes": (
                200,
                load_json("nodes-page-1.json"),
                {"Link": link},
            ),
            "/x-nmos/query/v1.3/nodes?paging.since=2": load_json("nodes-page-2.json"),
        }
    )
    snapshot = load_snapshot(REGISTRY, transport=scripted_transport(routes))
    ids = [node.id for node in snapshot.resources["nodes"]]
    assert ids == [
        "c8ba20e9-e197-4ec5-8764-4da672128589",
        "cebc6305-e8db-4026-aeb5-eb7a5620839e",
    ]


def test_self_referential_next_link_does_not_loop():
    link = f'<{REGISTRY}/x-nmos/query/v1.3/nodes>; rel="next"'
    seen: list[tuple[str, str]] = []
    routes = healthy_routes(
        **{
            "/x-nmos/query/v1.3/nodes": (
                200,
                load_json("nodes-page-1.json"),
                {"Link": link},
            )
        }
    )
    snapshot = load_snapshot(REGISTRY, transport=scripted_transport(routes, seen))
    assert snapshot.counts()["nodes"] == 1
    node_gets = [path for method, path in seen if method == "GET" and path.endswith("/nodes")]
    assert node_gets == ["/x-nmos/query/v1.3/nodes"]


def test_directory_urls_without_a_trailing_slash_still_resolve():
    routes = {
        "/x-nmos": load_json("x-nmos-query-only.json"),
        "/x-nmos/query": load_json("query-versions.json"),
        "/x-nmos/query/v1.3": load_json("query-root.json"),
        "/x-nmos/query/v1.3/nodes": [],
        "/x-nmos/query/v1.3/devices": [],
        "/x-nmos/query/v1.3/senders": [],
        "/x-nmos/query/v1.3/receivers": [],
    }
    snapshot = load_snapshot(REGISTRY, transport=scripted_transport(routes))
    assert snapshot.version == "v1.3"


def test_mount_prefix_is_sent_on_the_wire():
    seen: list[tuple[str, str]] = []
    routes = {
        "/nms/x-nmos/": load_json("x-nmos-query-only.json"),
        "/nms/x-nmos/query/": load_json("query-versions.json"),
        "/nms/x-nmos/query/v1.3/": load_json("query-root.json"),
        "/nms/x-nmos/query/v1.3/nodes": [],
        "/nms/x-nmos/query/v1.3/devices": [],
        "/nms/x-nmos/query/v1.3/senders": [],
        "/nms/x-nmos/query/v1.3/receivers": [],
    }
    snapshot = load_snapshot(f"{REGISTRY}/nms", transport=scripted_transport(routes, seen))
    assert snapshot.version == "v1.3"
    assert any(path == "/nms/x-nmos/query/v1.3/nodes" for _method, path in seen)


def test_label_falls_back_to_hostname():
    node = {
        "id": "c8ba20e9-e197-4ec5-8764-4da672128589",
        "version": "1441716120:1",
        "hostname": "encoder-a",
        "description": "no label",
        "tags": {},
        "caps": {},
    }
    routes = healthy_routes(**{"/x-nmos/query/v1.3/nodes": [node]})
    snapshot = load_snapshot(REGISTRY, transport=scripted_transport(routes))
    assert snapshot.resources["nodes"][0].label == "encoder-a"
