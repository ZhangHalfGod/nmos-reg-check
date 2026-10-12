"""mDNS selection and TXT decoding. The network is never opened."""

from __future__ import annotations

import socket

import pytest
from zeroconf import ServiceInfo

from nmos_reg_check.discovery import (
    BROWSE_TYPES,
    DiscoveryError,
    RawAdvertisement,
    browse_nmos_services,
    choose_host,
    interpret_advertisements,
    select_service,
    service_from_zeroconf,
)
from nmos_reg_check.discovery import DiscoveredService as Service
from nmos_reg_check.report import STRINGS, text


def _service(**overrides: object) -> Service:
    fields: dict[str, object] = {
        "name": "lab",
        "service_type": "_nmos-query._tcp",
        "host": "192.168.1.20",
        "port": 8080,
        "protocol": "http",
        "priority": 0,
    }
    fields.update(overrides)
    return Service(**fields)  # type: ignore[arg-type]


def _record(**overrides: object) -> RawAdvertisement:
    fields: dict[str, object] = {
        "name": "lab",
        "service_type": "_nmos-query._tcp",
        "host": "192.168.1.20",
        "port": 8080,
        "protocol": "http",
        "priority": 0,
        "api_versions": ("v1.3",),
        "requires_auth": False,
    }
    fields.update(overrides)
    return RawAdvertisement(**fields)  # type: ignore[arg-type]


class _Info:
    def __init__(self, **kwargs: object) -> None:
        self.type = "_nmos-query._tcp.local."
        self.name = "Lab._nmos-query._tcp.local."
        self.instance = "Lab"
        self.server = "lab.local."
        self.port = 8080
        self.addresses: list[str] = ["192.168.1.20"]
        self.decoded_properties = {
            "api_proto": "http",
            "api_ver": "v1.0,v1.1,v1.2,v1.3",
            "api_auth": "false",
            "pri": "0",
        }
        for key, value in kwargs.items():
            setattr(self, key, value)

    def parsed_addresses(self) -> list[str]:
        return list(self.addresses)

    def get_name(self) -> str:
        return str(self.instance)


def test_query_beats_a_higher_priority_registration_service():
    chosen = select_service(
        [
            _service(name="reg", service_type="_nmos-register._tcp", host="10.0.0.1", priority=0),
            _service(name="query", priority=40),
            _service(name="legacy", service_type="_nmos-registration._tcp", host="10.0.0.2", priority=0),
        ]
    )
    assert chosen is not None
    assert chosen.name == "query"
    assert chosen.url == "http://192.168.1.20:8080"


def test_lower_pri_then_https_then_name_are_stable():
    services = [
        _service(name="zeta", host="10.2.2.2", priority=5),
        _service(name="alpha", host="10.1.1.1", priority=5, protocol="http"),
        _service(name="alpha", host="10.1.1.1", priority=5, protocol="https"),
        _service(name="early-name", host="10.0.0.1", priority=9),
    ]
    chosen = select_service(services)
    assert chosen is not None
    assert chosen.protocol == "https"
    assert chosen.name == "alpha"
    # Same inputs, same winner.
    assert select_service(list(reversed(services))) == chosen


def test_missing_priority_sorts_as_development():
    chosen = select_service(
        [
            _service(name="dev", priority=100),
            _service(name="live", priority=0),
        ]
    )
    assert chosen is not None and chosen.name == "live"


def test_interpret_skips_auth_and_non_v1_and_keeps_a_missing_version():
    result = interpret_advertisements(
        [
            _record(name="open"),
            _record(name="locked", requires_auth=True),
            _record(name="v2", api_versions=("v2.0",), host="10.0.0.8"),
            _record(name="unspecified", api_versions=None, host="10.0.0.7"),
            _record(name="no-address", host=None),
        ]
    )
    assert [service.name for service in result.services] == ["open", "unspecified"]
    assert result.skipped_auth == 1
    assert result.skipped_version == 1
    assert result.skipped_address == 1
    assert result.chosen is not None and result.chosen.name == "open"


def test_choose_host_prefers_unicast_ipv4_and_brackets_ipv6():
    assert choose_host(["2001:db8::2", "192.168.1.20", "169.254.1.1", "127.0.0.1"], "lab.local.") == "192.168.1.20"
    assert choose_host(["fe80::1%eth0", "2001:db8::9"], None) == "2001:db8::9"
    assert choose_host([], "lab-registry.local.") == "lab-registry.local"
    service = _service(host="2001:db8::9", protocol="https", port=443)
    assert service.url == "https://[2001:db8::9]:443"


def test_service_info_txt_records_decode_without_the_network():
    info = ServiceInfo(
        type_="_nmos-query._tcp.local.",
        name="Lab Registry._nmos-query._tcp.local.",
        addresses=[socket.inet_aton("192.168.1.20"), socket.inet_pton(socket.AF_INET6, "2001:db8::5")],
        port=8080,
        properties={
            b"api_proto": b"http,https",
            b"api_ver": b"v1.2,v1.3",
            b"api_auth": b"false",
            b"pri": b"2",
        },
        server="lab-registry.local.",
    )
    record = service_from_zeroconf(info)
    assert record is not None
    assert record.name == "Lab Registry"
    assert record.service_type == "_nmos-query._tcp"
    assert record.host == "192.168.1.20"
    assert record.protocol == "https"
    assert record.priority == 2
    assert record.api_versions == ("v1.2", "v1.3")
    assert record.requires_auth is False


def test_missing_txt_defaults_and_auth_true_is_recorded():
    info = _Info(decoded_properties={"api_auth": "true"}, addresses=["10.0.0.4"])
    record = service_from_zeroconf(info)
    assert record is not None
    assert record.protocol == "http"
    assert record.priority == 100
    assert record.api_versions is None
    assert record.requires_auth is True

    unknown = _Info(decoded_properties={"api_proto": "ftp", "pri": "nope"})
    record = service_from_zeroconf(unknown)
    assert record is not None
    assert record.protocol is None
    assert record.priority == 100


def test_browse_maps_mocked_service_info_and_does_not_open_sockets():
    query = ServiceInfo(
        type_="_nmos-query._tcp.local.",
        name="Zebra._nmos-query._tcp.local.",
        addresses=[socket.inet_aton("192.168.1.20")],
        port=8080,
        properties={b"api_proto": b"http", b"api_ver": b"v1.3", b"api_auth": b"false", b"pri": b"7"},
        server="zebra.local.",
    )
    register = ServiceInfo(
        type_="_nmos-register._tcp.local.",
        name="Alpha._nmos-register._tcp.local.",
        addresses=[socket.inet_aton("10.0.0.5")],
        port=8081,
        properties={b"api_proto": b"http", b"api_ver": b"v1.3", b"pri": b"0"},
        server="alpha.local.",
    )
    infos = {query.name: query, register.name: register}
    seen: dict[str, object] = {}

    class FakeZeroconf:
        def get_service_info(self, type_: str, name: str, timeout: int = 3000) -> ServiceInfo:
            seen["timeout"] = timeout
            assert (type_, name) in {(query.type, query.name), (register.type, register.name)}
            return infos[name]

        def close(self) -> None:
            seen["closed"] = True

    class FakeBrowser:
        def __init__(self, zc: FakeZeroconf, types: list[str], listener: _Info) -> None:
            seen["types"] = list(types)
            listener.add_service(zc, query.type, query.name)
            listener.add_service(zc, register.type, register.name)
            listener.remove_service(zc, query.type, "gone._nmos-query._tcp.local.")

        def cancel(self) -> None:
            seen["cancelled"] = True

    result = browse_nmos_services(
        timeout=0.2,
        zeroconf_factory=FakeZeroconf,
        browser_factory=FakeBrowser,
        sleeper=lambda seconds: seen.__setitem__("slept", seconds),
    )
    assert seen["types"] == list(BROWSE_TYPES)
    assert seen["slept"] == 0.2
    assert seen["cancelled"] is True
    assert seen["closed"] is True
    assert result.chosen is not None
    assert result.chosen.service_type == "_nmos-query._tcp"
    assert result.chosen.name == "Zebra"
    assert result.chosen.url == "http://192.168.1.20:8080"
    assert [service.name for service in result.services] == ["Zebra", "Alpha"]


def test_discovery_messages_format_in_english_and_chinese():
    assert set(STRINGS["en"]) == set(STRINGS["zh"])
    samples = {
        "header_discovery_query": {
            "name": "Lab",
            "service_type": "_nmos-query._tcp",
            "url": "http://10.0.0.1:80",
            "priority": 0,
            "found": 2,
        },
        "header_discovery_registration": {
            "name": "Lab",
            "service_type": "_nmos-register._tcp",
            "url": "http://10.0.0.1:80",
            "priority": 1,
            "found": 1,
        },
        "mdns_none": {"timeout": "3"},
        "mdns_auth_only": {"count": 2},
        "mdns_no_v1": {"count": 1},
        "mdns_unresolved": {"count": 1},
        "mdns_none_usable": {"auth": 1, "version": 0, "address": 1},
        "mdns_failed": {"detail": "Permission denied"},
    }
    for key, params in samples.items():
        english = text("en", key, **params)
        chinese = text("zh", key, **params)
        assert english
        assert chinese
        assert english != chinese


def test_browse_turns_a_socket_error_into_discovery_error():
    def opener() -> object:
        raise OSError("Permission denied")

    with pytest.raises(DiscoveryError) as exc:
        browse_nmos_services(timeout=0.1, zeroconf_factory=opener, sleeper=lambda _seconds: None)
    assert "Permission denied" in exc.value.detail
