# nmos-reg-check

Command-line health check for an [NMOS IS-04](https://specs.amwa.tv/is-04/) registry. Point it at a registry with `--registry URL`, or pass `--mdns` and let it find one on the local network the way Riedel Explorer's **Auto Discover** fills in a registry before you type a URL. Both paths send **HTTP GET only** to the Query API, then report:

| Check | What it means |
| --- | --- |
| **R01** | The registry answers and an IS-04 **v1.x** Query API version can be negotiated. |
| **R02** | A node heartbeat is older than the IS-04 garbage-collection interval (**12 seconds**), when a heartbeat field is present. |
| **R05** | The same UUID is used by more than one of `nodes`, `devices`, `senders`, or `receivers`. |

## Install

Python 3.10 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The install adds the `nmos-reg-check` command. `python -m nmos_reg_check` runs the same entry point.

## Usage

```bash
nmos-reg-check --registry http://192.168.1.20:8080
nmos-reg-check --mdns
nmos-reg-check --mdns --mdns-timeout 5 --lang zh
nmos-reg-check --registry https://registry.example/x-nmos/query/v1.3/ --json
nmos-reg-check --registry https://registry.example:8443 --insecure --lang zh
```

`--registry` is the static URL. `--mdns` is auto-discovery. They are two ways to obtain the same registry address. If both are set, the explicit URL is used and mDNS is not browsed; a warning says so.

## Discovery (`--mdns`)

`--mdns` browses multicast DNS for the IS-04 DNS-SD types in `.local`:

| Service type | What it is |
| --- | --- |
| `_nmos-query._tcp` | Query API. Preferred, because the checks call Query. |
| `_nmos-register._tcp` | Registration API. Used only when no Query service is found. |
| `_nmos-registration._tcp` | Legacy Registration API (IS-04 v1.2 and earlier). Used only when neither of the types above is usable. |

`_nmos-node._tcp` is a Node API, not a registry, and is not browsed. Unicast DNS-SD (the spec's other browse path, used when a search domain is configured) is not implemented. On a LAN, Auto Discover is the multicast browse.

Each advertisement contributes an origin, `http://address:port` or `https://address:port`. The address is taken from the mDNS A/AAAA record so the later HTTP request does not depend on resolving a `.local` name. A unicast IPv4 address is preferred, then unicast IPv6, then a link-local address, then loopback. The port is the SRV port. The HTTP path is not in the advertisement; the same client that handles `--registry` then requests `/x-nmos/query/`.

TXT records follow IS-04:

- `api_proto` — `http` or `https`. A missing value is treated as `http`. If an older stack lists both, `https` is used.
- `api_ver` — comma-separated versions. A service with no v1.x version is skipped. A missing `api_ver` is kept, and the Query client negotiates v1 as usual.
- `api_auth` — `true` means the API requires authorization. Those services are skipped; this tool does not send credentials.
- `pri` — lower is higher priority (`0` is highest). A missing or non-integer value is treated as `100`, which IS-04 reserves for development registries, so any live registry (`0`–`99`) wins.

When more than one service is usable, the choice is stable (it is not random):

1. Query, then current Registration, then legacy Registration.
2. Lower `pri`.
3. `https` before `http`.
4. Instance name, then host, then port.

The text report and stderr name the service that was chosen, its type, priority, and how many services were found. `--json` adds a `discovery` object with the same choice and the full candidate list. A Registration advertisement is still checked through the Query API on that host and port, which is how a co-located registry is usually deployed. There is no automatic failover to the next candidate if that host does not answer.

Nothing usable exits 2. That includes an empty browse, a browse where every advertisement required authorization or had no v1 API, and an mDNS failure (no multicast permission, for example). `--mdns-timeout` is how long to listen, in seconds. The default is 3. Resolving each answer can take up to another second when the address was not already in the response.

### Limitations

- Multicast does not cross a typical Docker bridge. A registry on the LAN is invisible to a container unless the container uses host networking (`docker run --network host` on Linux) or you pass `--registry`. The same applies to many VMs and WSL2 setups.
- Linux needs UDP port 5353 and a route for 224.0.0.251 (and IPv6 multicast when the host has IPv6). macOS and Windows receive mDNS on the host in the usual way; the library is [python-zeroconf](https://github.com/python-zeroconf/python-zeroconf) (`zeroconf` on PyPI), which supports all three.
- Link-local addresses are used only when the advertisement has no other address. An IPv6 link-local address is used without a zone index, so it may be unreachable.
- This tool does not browse unicast DNS-SD and does not retry a different discovered registry in the same run.

### Registry URL

`--registry` accepts any of:

- an origin: `http://host:port`
- a path prefix in front of `/x-nmos/`: `http://host:port/nms`
- the Query API root: `http://host:port/x-nmos/query/`
- a pinned version: `http://host:port/x-nmos/query/v1.3/` (a trailing `/nodes` is ignored)

From an origin or a Query API root, the highest advertised **v1** minor version is used. v1.0 through whatever v1 minor the registry lists are accepted. A later major version is not used. A pinned version is requested as given.

The client reads:

- `GET /x-nmos/`
- `GET /x-nmos/query/`
- `GET /x-nmos/query/{version}/`
- `GET /x-nmos/query/{version}/nodes`
- `GET /x-nmos/query/{version}/devices`
- `GET /x-nmos/query/{version}/senders`
- `GET /x-nmos/query/{version}/receivers`

Those collection URLs are what IS-04 v1.3 specifies. Each response is a JSON array of resources. `Link: rel="next"` is followed when a registry pages with `paging.since` / `paging.until`. A single resource object is accepted, as are wrappers `{"nodes": [...]}` and `{"data": [...]}` (also `items`, `resources`, `results`, `result`).

### Options

| Option | Meaning |
| --- | --- |
| `--registry URL` | Registry origin or Query API URL. Wins over `--mdns` when both are set. |
| `--mdns` | Discover a registry with mDNS, then run the same checks. |
| `--mdns-timeout SECONDS` | How long to listen for mDNS (default 3). Must be greater than 0. |
| `--json` | Write the report as JSON to stdout. |
| `--lang en\|zh` | Report language. Default `en`. |
| `--insecure` | Do not verify TLS certificates. |

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | No finding has severity `error`. Info results, including a skipped heartbeat check, still exit 0. |
| 1 | The registry responded, and at least one check reported an error. |
| 2 | No HTTP response (DNS, connection, timeout, TLS), or the command line cannot be run (bad URL, missing `--registry` / `--mdns`, invalid `--mdns-timeout`, mDNS found nothing, mDNS itself failed). |

### Example

Against a registry whose Query API returns the usual node, device, sender, and receiver arrays (no heartbeat field on the nodes):

```text
Registry: http://192.168.1.20:8080
Query API: v1.3 http://192.168.1.20:8080/x-nmos/query/v1.3/
Resources: nodes=2, devices=2, senders=1, receivers=1

Check  Severity  Resource  Message
-----  --------  --------  ----------------------------------------------------------------
R01    ok        -         Query API v1.3 is reachable
R02    info      -         Nodes have no health or heartbeat field; heartbeat check skipped
R05    ok        -         No duplicate UUIDs in nodes, devices, senders, or receivers

0 errors, 1 info, 2 ok
```

The same run with `--json` (messages follow `--lang`):

```json
{
  "tool": "nmos-reg-check",
  "version": "0.1.0",
  "lang": "en",
  "registry_url": "http://192.168.1.20:8080",
  "query_url": "http://192.168.1.20:8080/x-nmos/query/v1.3/",
  "query_version": "v1.3",
  "ok": true,
  "exit_code": 0,
  "counts": {
    "nodes": 2,
    "devices": 2,
    "senders": 1,
    "receivers": 1
  },
  "summary": {
    "error": 0,
    "info": 1,
    "ok": 2
  },
  "findings": [
    {
      "id": "R01",
      "severity": "ok",
      "code": "query_api_reachable",
      "resource_type": null,
      "resource_id": null,
      "resource_label": null,
      "message": "Query API v1.3 is reachable",
      "details": {
        "version": "v1.3",
        "query_url": "http://192.168.1.20:8080/x-nmos/query/v1.3/"
      }
    },
    {
      "id": "R02",
      "severity": "info",
      "code": "heartbeat_absent",
      "resource_type": null,
      "resource_id": null,
      "resource_label": null,
      "message": "Nodes have no health or heartbeat field; heartbeat check skipped",
      "details": {
        "nodes": 2
      }
    },
    {
      "id": "R05",
      "severity": "ok",
      "code": "no_duplicate_ids",
      "resource_type": null,
      "resource_id": null,
      "resource_label": null,
      "message": "No duplicate UUIDs in nodes, devices, senders, or receivers",
      "details": {}
    }
  ]
}
```

## Checks

### R01 — reachable, version negotiated

R01 passes when the Query API root for the chosen version can be read and the four collections return HTTP 200 and JSON. A connection failure is still reported as R01, with exit code 2. An HTTP error, a non-JSON body, a server that does not advertise `query/`, or a version list with no v1.x release is R01 with exit code 1.

IS-04 error bodies `{"code", "error", "debug"}` contribute the `error` string to the R01 message.

### R02 — stale heartbeat when a timestamp is present

IS-04 Query API **node** documents do not include a heartbeat. Confirmed against the v1.3.3 node schema and the Query API examples: a node has `id`, `version`, `label`, `href`, `api`, and so on. `version` is a TAI timestamp `<seconds>:<nanoseconds>` of the last attribute change. Heartbeats do not update it, so this tool does not treat `version` as a heartbeat. Doing so would flag every stable node.

The heartbeat timestamp is defined on the Registration API. `GET /x-nmos/registration/{version}/health/nodes/{nodeId}` (debug read) and the heartbeat `POST` response use:

```json
{"health": "1441974485"}
```

`health` is a string of integer seconds. nmos-cpp stores that value on the TAI clock (leap seconds are not applied). This program does not call the Registration API, so it does not see that field on a stock registry.

R02 instead reads these fields when a node object already carries them: `health`, `heartbeat`, `last_heartbeat`, `heartbeat_timestamp`, `last_seen`. A number, a digit string, or `seconds:nanoseconds` is TAI. A value with 13 or more digits is milliseconds; 15 or more is microseconds. An object may nest the timestamp under `health`, `timestamp`, `seconds`, or `tai`. An ISO-8601 value (a trailing `Z` is accepted) is UTC. The TAI offset used here is 37 seconds, the value in force since 2017-01-01.

If none of those fields exist, R02 is **info** and the process can still exit 0. A present value that is not a timestamp is info for that node. A timestamp older than 12 seconds is an error. A timestamp exactly 12 seconds old is not an error: the specification removes a node only after heartbeats have been missing for longer than the garbage-collection interval. The default interval is 12 seconds (two missed 5-second heartbeats).

### R05 — duplicate UUIDs

Ids are compared case-insensitively with the IS-04 pattern (`8-4-4-4-12` lowercase hex, version nibble 1–5, variant nibble 8, 9, a, or b). The same id on two resource types is a duplicate: registration rejects an id that another resource type already uses. Ids that are not UUIDs are ignored. Sources and flows are not loaded in this version, so a clash that involves only those types is not visible.

An identical copy of a resource repeated on a later `Link: rel="next"` page is treated as page overlap, not as a second registration. Two copies in the same response are a duplicate.

## Tests

```bash
pytest
```

Tests load JSON fixtures from `tests/fixtures/` and answer them with an in-process HTTP mock. No live registry is required. mDNS is replaced with a fake browse, so CI does not need multicast. The fixtures follow the IS-04 v1.3 Query API examples: version lists use a trailing slash (`"v1.3/"`), the API root lists `nodes/`, `devices/`, `senders/`, and `receivers/`, and resource bodies are JSON arrays.

## License

MIT. See [LICENSE](LICENSE).
