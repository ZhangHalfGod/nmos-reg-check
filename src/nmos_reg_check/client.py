"""Read-only IS-04 Query API client.

The client negotiates ``/x-nmos/query/v1.x/`` and loads ``nodes``, ``devices``,
``senders``, and ``receivers``. It never calls the Registration API.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from nmos_reg_check import __version__

COLLECTIONS: tuple[str, ...] = ("nodes", "devices", "senders", "receivers")
_COLLECTION_SUFFIX = re.compile(
    r"/(nodes|devices|senders|receivers|sources|flows|subscriptions)/?$",
    re.IGNORECASE,
)
_VERSION_IN_PATH = re.compile(
    r"(?P<mount>.*?)/x-nmos/query/(?P<ver>v\d+\.\d+)/?$",
    re.IGNORECASE,
)
_QUERY_ROOT_IN_PATH = re.compile(r"(?P<mount>.*?)/x-nmos/query/?$", re.IGNORECASE)
_XNMOS_IN_PATH = re.compile(r"(?P<mount>.*?)/x-nmos/?$", re.IGNORECASE)
_API_VERSION = re.compile(r"v(\d+)\.(\d+)", re.IGNORECASE)

DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_PAGES = 100
USER_AGENT = f"nmos-reg-check/{__version__}"

_WRAPPER_KEYS = ("data", "items", "resources", "results", "result")


class RegistryError(Exception):
    """Query API discovery or fetch failed.

    ``kind`` is ``connection`` when no HTTP response was obtained (DNS, TCP,
    TLS, timeout) and ``api`` when the server responded but is not a usable
    IS-04 Query API.
    """

    def __init__(self, message: str, *, kind: str) -> None:
        super().__init__(message)
        self.kind = kind


class UsageError(Exception):
    """The registry URL cannot be interpreted."""

    def __init__(self, message_key: str, **params: str) -> None:
        super().__init__(message_key)
        self.message_key = message_key
        self.params = params


@dataclass(frozen=True)
class ParsedRegistry:
    """How ``--registry`` maps onto the Query API."""

    prefix: str
    mode: str
    version: str | None
    source_url: str


@dataclass(frozen=True)
class Resource:
    """One Query API resource."""

    type: str
    id: str | None
    label: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class Snapshot:
    """Resources read from one registry."""

    registry_url: str
    query_url: str
    version: str
    resources: dict[str, list[Resource]] = field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        return {name: len(self.resources.get(name, [])) for name in COLLECTIONS}


def parse_registry_url(url: str) -> ParsedRegistry:
    """Accept an origin, a mount prefix, or a Query API root."""

    raw = url.strip()
    parsed = urlsplit(raw)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https") or not parsed.netloc:
        raise UsageError("registry_url_invalid")

    path = parsed.path or "/"
    path = re.sub(r"/{2,}", "/", path)
    path = _COLLECTION_SUFFIX.sub("", path) or "/"
    # Query and fragment are not forwarded. Version selection uses the path.
    source_url = f"{scheme}://{parsed.netloc}{parsed.path or ''}"

    version_match = _VERSION_IN_PATH.fullmatch(path)
    if version_match:
        version = _canonical_version(version_match.group("ver"))
        return ParsedRegistry(
            prefix=_prefix(scheme, parsed.netloc, version_match.group("mount")),
            mode="version",
            version=version,
            source_url=source_url,
        )

    query_match = _QUERY_ROOT_IN_PATH.fullmatch(path)
    if query_match:
        return ParsedRegistry(
            prefix=_prefix(scheme, parsed.netloc, query_match.group("mount")),
            mode="query_root",
            version=None,
            source_url=source_url,
        )

    xnmos_match = _XNMOS_IN_PATH.fullmatch(path)
    if xnmos_match:
        return ParsedRegistry(
            prefix=_prefix(scheme, parsed.netloc, xnmos_match.group("mount")),
            mode="discover",
            version=None,
            source_url=source_url,
        )

    if re.search(r"/x-nmos(/|$)", path, flags=re.IGNORECASE):
        raise UsageError("registry_url_unrecognized", url=raw)

    return ParsedRegistry(
        prefix=_prefix(scheme, parsed.netloc, path if path != "/" else ""),
        mode="discover",
        version=None,
        source_url=source_url,
    )


def choose_version(advertised: list[str]) -> str | None:
    """Pick the highest IS-04 v1 minor version."""

    found: list[tuple[int, int]] = []
    for item in advertised:
        parsed = _parse_version_token(item)
        if parsed is not None and parsed[0] == 1:
            found.append(parsed)
    if not found:
        return None
    major, minor = max(found)
    return f"v{major}.{minor}"


def unwrap_collection(payload: Any, collection: str) -> list[dict[str, Any]]:
    """Accept a JSON array, a single resource, or a wrapped collection."""

    if isinstance(payload, list):
        return _objects(payload, collection)
    if isinstance(payload, dict):
        for key in (collection, f"{collection}/"):
            value = payload.get(key)
            if isinstance(value, list):
                return _objects(value, collection)
        for key in _WRAPPER_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                return _objects(value, collection)
        if "id" in payload:
            return [payload]
    raise RegistryError(f"Unrecognized {collection} response shape", kind="api")


def create_client(
    *,
    insecure: bool,
    transport: httpx.BaseTransport | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> httpx.Client:
    return httpx.Client(
        transport=transport,
        verify=not insecure,
        timeout=timeout,
        follow_redirects=True,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )


def load_snapshot(
    registry_url: str,
    *,
    insecure: bool = False,
    transport: httpx.BaseTransport | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Snapshot:
    """Discover the Query API and load the four W1 collections."""

    parsed = parse_registry_url(registry_url)
    with create_client(insecure=insecure, transport=transport, timeout=timeout) as client:
        version, query_url = _negotiate(client, parsed)
        resources: dict[str, list[Resource]] = {}
        for collection in COLLECTIONS:
            url = _url(parsed.prefix, "x-nmos", "query", version, collection)
            raw_items = _fetch_all(client, url, collection)
            resource_type = collection[:-1]
            resources[collection] = [_to_resource(resource_type, item) for item in raw_items]
    return Snapshot(
        registry_url=parsed.source_url,
        query_url=query_url,
        version=version,
        resources=resources,
    )


def _negotiate(client: httpx.Client, parsed: ParsedRegistry) -> tuple[str, str]:
    if parsed.mode == "discover":
        index_url = _url(parsed.prefix, "x-nmos", slash=True)
        advertised = _string_list(_get_index(client, index_url), index_url)
        if not _has_child(advertised, "query"):
            raise RegistryError(
                "Server does not advertise the IS-04 Query API at /x-nmos/",
                kind="api",
            )

    if parsed.mode == "version":
        version = parsed.version or ""
    else:
        versions_url = _url(parsed.prefix, "x-nmos", "query", slash=True)
        advertised = _string_list(_get_index(client, versions_url), versions_url)
        chosen = choose_version(advertised)
        if chosen is None:
            shown = ", ".join(advertised) if advertised else "(none)"
            raise RegistryError(
                f"No supported IS-04 v1.x Query API version (advertised: {shown})",
                kind="api",
            )
        version = chosen

    root = _url(parsed.prefix, "x-nmos", "query", version, slash=True)
    payload = _get_index(client, root)
    if isinstance(payload, list) and payload and all(isinstance(item, str) for item in payload):
        missing = [name for name in COLLECTIONS if not _has_child(payload, name)]
        if missing:
            raise RegistryError(
                f"Query API {version} does not advertise {', '.join(missing)}",
                kind="api",
            )
    return version, root


def _fetch_all(client: httpx.Client, url: str, collection: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_pages: set[str] = set()
    seen_exact: set[tuple[str, str]] = set()
    next_url: str | None = url
    page = 0
    while next_url is not None:
        if next_url in seen_pages:
            break
        seen_pages.add(next_url)
        page += 1
        if page > MAX_PAGES:
            raise RegistryError(
                f"Stopped after {MAX_PAGES} pages while reading {collection}",
                kind="api",
            )
        response = _request(client, next_url)
        payload = _decode(response, next_url)
        batch = unwrap_collection(payload, collection)
        if page == 1:
            items.extend(batch)
        else:
            batch = _drop_page_overlap(batch, seen_exact)
            items.extend(batch)
        for obj in batch:
            ident = _exact_key(obj)
            if ident is not None:
                seen_exact.add(ident)
        next_url = _link_next(response)
    return items


def _drop_page_overlap(
    batch: list[dict[str, Any]],
    seen_exact: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    fresh: list[dict[str, Any]] = []
    for obj in batch:
        ident = _exact_key(obj)
        if ident is not None and ident in seen_exact:
            continue
        fresh.append(obj)
    return fresh


def _exact_key(obj: dict[str, Any]) -> tuple[str, str] | None:
    rid = obj.get("id")
    if not isinstance(rid, str) or not rid.strip():
        return None
    canonical = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return (rid.strip().lower(), canonical)


def _link_next(response: httpx.Response) -> str | None:
    link = response.links.get("next")
    if not link:
        return None
    href = link.get("url")
    if not href:
        return None
    joined = str(response.url.join(href))
    if urlsplit(joined).scheme not in ("http", "https"):
        return None
    return joined


def _get_index(client: httpx.Client, url: str) -> Any:
    response = _request(client, url)
    if response.status_code == 404 and url.endswith("/"):
        response = _request(client, url[:-1])
    return _decode(response, url)


def _request(client: httpx.Client, url: str) -> httpx.Response:
    try:
        return client.get(url)
    except httpx.TimeoutException as exc:
        raise RegistryError(f"timed out contacting {url}", kind="connection") from exc
    except httpx.NetworkError as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        raise RegistryError(detail, kind="connection") from exc
    except httpx.RemoteProtocolError as exc:
        detail = str(exc).strip() or "HTTP protocol error"
        raise RegistryError(detail, kind="connection") from exc


def _decode(response: httpx.Response, url: str) -> Any:
    if response.status_code != 200:
        raise RegistryError(
            f"HTTP {response.status_code} from {url}: {_error_detail(response)}",
            kind="api",
        )
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise RegistryError(f"Response from {url} is not JSON", kind="api") from exc


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        text = " ".join(response.text.split())
        return (text[:180] or response.reason_phrase or "error")
    if isinstance(body, dict) and isinstance(body.get("error"), str) and body["error"].strip():
        return body["error"].strip()[:180]
    return response.reason_phrase or "error"


def _string_list(payload: Any, url: str) -> list[str]:
    if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
        raise RegistryError(f"Expected a JSON array of strings from {url}", kind="api")
    return payload


def _has_child(items: list[str], name: str) -> bool:
    want = name.strip("/").lower()
    return any(item.strip("/").lower() == want for item in items)


def _objects(items: list[Any], collection: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise RegistryError(f"{collection} entry is not a JSON object", kind="api")
        objects.append(item)
    return objects


def _to_resource(resource_type: str, raw: dict[str, Any]) -> Resource:
    rid = raw.get("id")
    if isinstance(rid, str) and rid.strip():
        resource_id: str | None = rid.strip()
    else:
        resource_id = None
    label = raw.get("label")
    if not isinstance(label, str) or not label.strip():
        label = raw.get("hostname") if resource_type == "node" else None
    if isinstance(label, str) and label.strip():
        resource_label: str | None = label.strip()
    else:
        resource_label = None
    return Resource(type=resource_type, id=resource_id, label=resource_label, raw=raw)


def _prefix(scheme: str, netloc: str, mount: str) -> str:
    mount = (mount or "").rstrip("/")
    if mount and not mount.startswith("/"):
        mount = "/" + mount
    return f"{scheme}://{netloc}{mount}"


def _url(prefix: str, *parts: str, slash: bool = False) -> str:
    bits = [part.strip("/") for part in parts if part.strip("/")]
    url = prefix.rstrip("/") + "/" + "/".join(bits)
    if slash:
        url += "/"
    return url


def _canonical_version(token: str) -> str:
    parsed = _parse_version_token(token)
    if parsed is None:
        raise UsageError("registry_url_unrecognized", url=token)
    return f"v{parsed[0]}.{parsed[1]}"


def _parse_version_token(token: str) -> tuple[int, int] | None:
    match = _API_VERSION.fullmatch(token.strip().strip("/"))
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))
