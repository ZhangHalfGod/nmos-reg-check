"""mDNS discovery of an IS-04 registry.

IS-04 v1.3 discovery (DNS-SD, RFC 6763) defines these registry service types:

* ``_nmos-query._tcp`` — Query API (preferred; this is what the checks call)
* ``_nmos-register._tcp`` — Registration API
* ``_nmos-registration._tcp`` — legacy Registration API required for v1.2 and earlier

``_nmos-node._tcp`` is a Node API, not a registry, and is not browsed.

The advertisement carries the host and port. The HTTP path is the standard
NMOS path, so a chosen service becomes an origin such as
``http://192.168.1.20:8080``. The Query API client then resolves
``/x-nmos/query/`` the same way ``--registry`` does.

This module browses multicast DNS only. Unicast DNS-SD is not implemented.
"""

from __future__ import annotations

import ipaddress
import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Sequence

# Fully qualified mDNS types. The spec writes them without ``.local``.
BROWSE_TYPES: tuple[str, ...] = (
    "_nmos-query._tcp.local.",
    "_nmos-register._tcp.local.",
    "_nmos-registration._tcp.local.",
)

QUERY_TYPE = "_nmos-query._tcp"
REGISTER_TYPE = "_nmos-register._tcp"
LEGACY_REGISTER_TYPE = "_nmos-registration._tcp"

_KNOWN_TYPES = frozenset({QUERY_TYPE, REGISTER_TYPE, LEGACY_REGISTER_TYPE})
_TYPE_RANK = {QUERY_TYPE: 0, REGISTER_TYPE: 1, LEGACY_REGISTER_TYPE: 2}

# IS-04: pri 0 is the highest priority. 100 and above are for development
# registries. A missing or unreadable pri is treated as 100 so a live
# registry (0–99) is preferred.
ABSENT_PRIORITY = 100
DEFAULT_MDNS_TIMEOUT = 3.0
_RESOLVE_TIMEOUT_MS = 1000
_VERSION = re.compile(r"v(\d+)\.(\d+)", re.IGNORECASE)


class DiscoveryError(Exception):
    """mDNS could not be performed (sockets, permissions, or the library)."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class RawAdvertisement:
    """One decoded DNS-SD record, before it is accepted as a candidate."""

    name: str
    service_type: str
    host: str | None
    port: int | None
    protocol: str | None
    priority: int
    api_versions: tuple[str, ...] | None
    requires_auth: bool
    server: str | None = None


@dataclass(frozen=True)
class DiscoveredService:
    """A registry origin the Query API client can be pointed at."""

    name: str
    service_type: str
    host: str
    port: int
    protocol: str
    priority: int
    api_versions: tuple[str, ...] | None = None
    server: str | None = None

    @property
    def url(self) -> str:
        return format_origin(self.protocol, self.host, self.port)

    @property
    def is_query(self) -> bool:
        return self.service_type == QUERY_TYPE


@dataclass(frozen=True)
class DiscoveryResult:
    """Usable services plus why other advertisements were set aside."""

    services: tuple[DiscoveredService, ...] = ()
    skipped_auth: int = 0
    skipped_version: int = 0
    skipped_address: int = 0

    @property
    def chosen(self) -> DiscoveredService | None:
        return select_service(self.services)


def format_origin(protocol: str, host: str, port: int) -> str:
    """Build ``scheme://host:port`` with brackets around an IPv6 address."""

    literal = host
    if ":" in host and not (host.startswith("[") and host.endswith("]")):
        literal = f"[{host}]"
    return f"{protocol}://{literal}:{port}"


def format_timeout(seconds: float) -> str:
    text = f"{seconds:.3f}".rstrip("0").rstrip(".")
    return text or "0"


def parse_timeout(value: str) -> float:
    """Return a positive finite timeout, or raise ``ValueError``."""

    try:
        number = float(value.strip())
    except ValueError as exc:
        raise ValueError("not a number") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError("not a positive number")
    return number


def select_service(services: Sequence[DiscoveredService]) -> DiscoveredService | None:
    """Pick one registry.

    Order, first match wins:

    1. Query (``_nmos-query._tcp``), then Registration (``_nmos-register._tcp``),
       then the legacy Registration type.
    2. Lower TXT ``pri`` (0 is highest).
    3. ``https`` before ``http``.
    4. Instance name, then host, then port, all compared case-insensitively
       for the name and host.

    IS-04 allows a random choice among equal priorities. This ordering is
    stable so the same LAN answers the same way on the next run.
    """

    if not services:
        return None
    return min(services, key=sort_key)


def sort_key(service: DiscoveredService) -> tuple[Any, ...]:
    return (
        _TYPE_RANK.get(service.service_type, 9),
        service.priority,
        0 if service.protocol == "https" else 1,
        service.name.casefold(),
        service.host.casefold(),
        service.port,
    )


def empty_discovery_reason(result: DiscoveryResult) -> tuple[str, dict[str, int]]:
    """Message key and counts when nothing usable was found."""

    auth = result.skipped_auth
    version = result.skipped_version
    address = result.skipped_address
    present = [count for count in (auth, version, address) if count]
    if not present:
        return "mdns_none", {}
    if len(present) == 1 and auth:
        return "mdns_auth_only", {"count": auth}
    if len(present) == 1 and version:
        return "mdns_no_v1", {"count": version}
    if len(present) == 1 and address:
        return "mdns_unresolved", {"count": address}
    return "mdns_none_usable", {"auth": auth, "version": version, "address": address}


def interpret_advertisements(records: Sequence[RawAdvertisement]) -> DiscoveryResult:
    """Keep v1 registries this tool can call without credentials."""

    usable: list[DiscoveredService] = []
    skipped_auth = 0
    skipped_version = 0
    skipped_address = 0
    for record in records:
        if record.service_type not in _KNOWN_TYPES:
            continue
        if record.requires_auth:
            skipped_auth += 1
            continue
        if not _supports_v1(record.api_versions):
            skipped_version += 1
            continue
        if record.host is None or record.port is None or record.protocol not in ("http", "https"):
            skipped_address += 1
            continue
        usable.append(
            DiscoveredService(
                name=record.name,
                service_type=record.service_type,
                host=record.host,
                port=record.port,
                protocol=record.protocol,
                priority=record.priority,
                api_versions=record.api_versions,
                server=record.server,
            )
        )
    ordered = tuple(sorted(usable, key=sort_key))
    return DiscoveryResult(
        services=ordered,
        skipped_auth=skipped_auth,
        skipped_version=skipped_version,
        skipped_address=skipped_address,
    )


def discovery_payload(result: DiscoveryResult) -> dict[str, Any]:
    """JSON-ready description of a successful browse. ``chosen`` is required."""

    chosen = result.chosen
    if chosen is None:
        raise ValueError("no service to describe")
    return {
        "method": "mdns",
        "found": len(result.services),
        "skipped_auth": result.skipped_auth,
        "skipped_version": result.skipped_version,
        "skipped_address": result.skipped_address,
        "chosen": service_payload(chosen),
        "services": [service_payload(service) for service in sorted(result.services, key=sort_key)],
    }


def service_payload(service: DiscoveredService) -> dict[str, Any]:
    versions = None if service.api_versions is None else list(service.api_versions)
    return {
        "name": service.name,
        "type": service.service_type,
        "role": "query" if service.is_query else "registration",
        "host": service.host,
        "port": service.port,
        "protocol": service.protocol,
        "priority": service.priority,
        "url": service.url,
        "api_versions": versions,
    }


def browse_nmos_services(
    *,
    timeout: float,
    zeroconf_factory: Callable[[], Any] | None = None,
    browser_factory: Callable[..., Any] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> DiscoveryResult:
    """Browse the LAN and return the services this tool can check.

    ``zeroconf_factory``, ``browser_factory``, and ``sleeper`` exist so tests
    can supply the browse results without sending multicast.
    """

    records = collect_advertisements(
        timeout=timeout,
        zeroconf_factory=zeroconf_factory,
        browser_factory=browser_factory,
        sleeper=sleeper,
    )
    return interpret_advertisements(records)


def collect_advertisements(
    *,
    timeout: float,
    zeroconf_factory: Callable[[], Any] | None = None,
    browser_factory: Callable[..., Any] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> list[RawAdvertisement]:
    """Listen for NMOS registry PTR records, then resolve each one.

    Service info is requested after the browse window, on this thread.
    Resolving inside the zeroconf callback can deadlock the browser.
    """

    try:
        from zeroconf import Error as ZeroconfError
        from zeroconf import ServiceBrowser
    except ImportError as exc:
        raise DiscoveryError("zeroconf is not installed") from exc

    opener = zeroconf_factory or _open_zeroconf
    browser_cls = browser_factory or ServiceBrowser
    wait = sleeper or _wait

    listener = _Listener()
    try:
        zc = opener()
    except (OSError, RuntimeError, ZeroconfError) as exc:
        raise DiscoveryError(_error_detail(exc)) from exc

    browser: Any = None
    try:
        browser = browser_cls(zc, list(BROWSE_TYPES), listener)
        wait(timeout)
        found = listener.snapshot()
        records: list[RawAdvertisement] = []
        for name, service_type in found:
            try:
                info = zc.get_service_info(service_type, name, timeout=_RESOLVE_TIMEOUT_MS)
            except (OSError, RuntimeError, ZeroconfError) as exc:
                raise DiscoveryError(_error_detail(exc)) from exc
            record = service_from_zeroconf(info)
            if record is not None:
                records.append(record)
        return records
    except DiscoveryError:
        raise
    except (OSError, RuntimeError, ZeroconfError) as exc:
        raise DiscoveryError(_error_detail(exc)) from exc
    finally:
        try:
            if browser is not None:
                cancel = getattr(browser, "cancel", None)
                if callable(cancel):
                    cancel()
        finally:
            close = getattr(zc, "close", None)
            if callable(close):
                close()


def service_from_zeroconf(info: Any) -> RawAdvertisement | None:
    """Map a resolved zeroconf ``ServiceInfo`` (or a lookalike) to a record."""

    if info is None:
        return None
    service_type = normalize_service_type(str(getattr(info, "type", "") or ""))
    if service_type not in _KNOWN_TYPES:
        return None
    txt = _txt_map(info)
    versions = parse_api_versions(txt["api_ver"]) if "api_ver" in txt else None
    port = getattr(info, "port", None)
    usable_port = port if isinstance(port, int) and 1 <= port <= 65535 else None
    addresses: list[str] = []
    parsed = getattr(info, "parsed_addresses", None)
    if callable(parsed):
        try:
            addresses = [str(item) for item in parsed()]
        except (TypeError, ValueError):
            addresses = []
    server = getattr(info, "server", None)
    server_text = server if isinstance(server, str) else None
    return RawAdvertisement(
        name=instance_name(info),
        service_type=service_type,
        host=choose_host(addresses, server_text),
        port=usable_port,
        protocol=choose_protocol(txt.get("api_proto")),
        priority=parse_priority(txt.get("pri")),
        api_versions=versions,
        requires_auth=requires_auth(txt.get("api_auth")),
        server=server_text.strip().rstrip(".") if isinstance(server_text, str) else None,
    )


def normalize_service_type(type_name: str) -> str:
    text = type_name.strip().rstrip(".").lower()
    if text.endswith(".local"):
        text = text[: -len(".local")].rstrip(".")
    return text


def instance_name(info: Any) -> str:
    getter = getattr(info, "get_name", None)
    raw = getter() if callable(getter) else getattr(info, "name", "")
    name = str(raw or "").strip().rstrip(".")
    service_type = normalize_service_type(str(getattr(info, "type", "") or ""))
    lowered = name.casefold()
    if service_type:
        for suffix in (f".{service_type}.local", f".{service_type}"):
            if lowered.endswith(suffix):
                name = name[: -len(suffix)]
                break
    name = name.strip()
    return name or "(unnamed)"


def choose_host(addresses: Sequence[str], server: str | None) -> str | None:
    """Prefer a unicast IPv4 address from the mDNS response.

    Later HTTP uses the system resolver, which often cannot resolve
    ``.local`` names. The address carried by the advertisement is used
    instead. Order: unicast IPv4, unicast IPv6, link-local, loopback.
    The SRV host name is only used when no address was resolved.
    """

    parsed: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for raw in addresses:
        text = raw.strip()
        if not text:
            continue
        if "%" in text:
            text = text.split("%", 1)[0]
        try:
            parsed.append(ipaddress.ip_address(text))
        except ValueError:
            continue
    if parsed:
        best = min(parsed, key=_addr_rank)
        if isinstance(best, ipaddress.IPv6Address):
            return best.compressed
        return str(best)
    if not server:
        return None
    host = server.strip().rstrip(".")
    return host or None


def choose_protocol(value: str | None) -> str | None:
    """Pick http or https.

    Current IS-04 advertisements use a single ``api_proto`` value. Some
    earlier stacks sent a comma-separated list; ``https`` wins when both
    are present because this client can speak TLS. A missing value is
    ``http``.
    """

    if value is None or not value.strip():
        return "http"
    tokens = [part.strip().lower() for part in value.split(",") if part.strip()]
    if "https" in tokens:
        return "https"
    if "http" in tokens:
        return "http"
    return None


def parse_api_versions(value: str) -> tuple[str, ...]:
    found: list[str] = []
    for part in value.split(","):
        match = _VERSION.fullmatch(part.strip().strip("/"))
        if match:
            found.append(f"v{int(match.group(1))}.{int(match.group(2))}")
    return tuple(found)


def parse_priority(value: str | None) -> int:
    if value is None or not value.strip():
        return ABSENT_PRIORITY
    try:
        return int(value.strip(), 10)
    except ValueError:
        return ABSENT_PRIORITY


def requires_auth(value: str | None) -> bool:
    return value is not None and value.strip().lower() == "true"


def _supports_v1(versions: tuple[str, ...] | None) -> bool:
    if versions is None:
        return True
    for token in versions:
        match = _VERSION.fullmatch(token)
        if match is not None and int(match.group(1)) == 1:
            return True
    return False


def _addr_rank(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> tuple[int, int, str]:
    if addr.is_loopback:
        scope = 2
    elif addr.is_link_local:
        scope = 1
    else:
        scope = 0
    family = 0 if isinstance(addr, ipaddress.IPv4Address) else 1
    return (scope, family, str(addr))


def _txt_map(info: Any) -> dict[str, str]:
    decoded = getattr(info, "decoded_properties", None)
    source = decoded if isinstance(decoded, dict) else getattr(info, "properties", None) or {}
    mapped: dict[str, str] = {}
    for key, value in source.items():
        name = _as_text(key)
        if not name:
            continue
        if value is None:
            mapped[name.lower()] = ""
            continue
        text = _as_text(value)
        if text is not None:
            mapped[name.lower()] = text
    return mapped


def _as_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return None


def _open_zeroconf() -> Any:
    from zeroconf import IPVersion, Zeroconf

    try:
        return Zeroconf(ip_version=IPVersion.All)
    except (OSError, RuntimeError):
        return Zeroconf(ip_version=IPVersion.V4Only)


def _wait(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.05, remaining))


def _error_detail(exc: BaseException) -> str:
    detail = str(exc).strip()
    return detail or exc.__class__.__name__


class _Listener:
    """Collect service names without resolving them on the callback thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._names: dict[str, str] = {}

    def add_service(self, _zc: Any, type_: str, name: str) -> None:
        with self._lock:
            self._names[name] = type_

    def update_service(self, _zc: Any, type_: str, name: str) -> None:
        with self._lock:
            self._names[name] = type_

    def remove_service(self, _zc: Any, _type: str, name: str) -> None:
        with self._lock:
            self._names.pop(name, None)

    def snapshot(self) -> list[tuple[str, str]]:
        with self._lock:
            return list(self._names.items())
