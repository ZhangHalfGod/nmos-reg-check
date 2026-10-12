"""Registry URL parsing and version selection."""

import pytest

from nmos_reg_check.client import UsageError, choose_version, parse_registry_url


def test_origin_discovers_query_api():
    parsed = parse_registry_url("http://10.1.1.8:8080")
    assert parsed.prefix == "http://10.1.1.8:8080"
    assert parsed.mode == "discover"
    assert parsed.version is None


def test_trailing_slash_and_fragment_are_not_part_of_the_api_path():
    parsed = parse_registry_url("HTTP://registry.example:8443/#overview")
    assert parsed.prefix == "http://registry.example:8443"
    assert parsed.mode == "discover"
    assert parsed.source_url == "http://registry.example:8443/"


def test_mount_prefix_is_preserved():
    parsed = parse_registry_url("https://reg.example/nms")
    assert parsed.prefix == "https://reg.example/nms"
    assert parsed.mode == "discover"


def test_explicit_query_version():
    parsed = parse_registry_url("http://10.1.1.8:8080/x-nmos/query/v1.2/")
    assert parsed.prefix == "http://10.1.1.8:8080"
    assert parsed.mode == "version"
    assert parsed.version == "v1.2"


def test_explicit_version_with_collection_suffix():
    parsed = parse_registry_url("http://10.1.1.8:8080/x-nmos/query/V1.3/nodes/")
    assert parsed.mode == "version"
    assert parsed.version == "v1.3"
    assert parsed.prefix == "http://10.1.1.8:8080"


def test_query_root_negotiates_a_version():
    parsed = parse_registry_url("https://reg.example/proxy/x-nmos/query")
    assert parsed.prefix == "https://reg.example/proxy"
    assert parsed.mode == "query_root"
    assert parsed.version is None


def test_ipv6_origin():
    parsed = parse_registry_url("http://[2001:db8::20]:8080/x-nmos/")
    assert parsed.prefix == "http://[2001:db8::20]:8080"
    assert parsed.mode == "discover"


def test_rejects_non_http_urls():
    with pytest.raises(UsageError) as exc:
        parse_registry_url("ftp://registry.example")
    assert exc.value.message_key == "registry_url_invalid"


def test_rejects_unknown_x_nmos_shape():
    with pytest.raises(UsageError) as exc:
        parse_registry_url("http://registry.example/x-nmos/query/v1.3.1")
    assert exc.value.message_key == "registry_url_unrecognized"


def test_choose_highest_v1_minor():
    assert choose_version(["v1.0/", "v1.2/", "v1.3/"]) == "v1.3"
    assert choose_version(["V1.0"]) == "v1.0"
    assert choose_version(["v2.0/", "v1.1/"]) == "v1.1"
    assert choose_version(["v2.0/"]) is None
    assert choose_version([]) is None
