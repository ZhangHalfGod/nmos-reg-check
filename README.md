# nmos-reg-check — NMOS IS-04 Registry Health Check

**Language / 语言:** [English](README.md) | [中文](README.zh-CN.md)

> **Read-only NMOS IS-04 registry health check for the lab: verify the Query API by URL (W1), or discover the registry with mDNS and check it the same way (W2).**

[![GitHub](https://img.shields.io/badge/GitHub-ZhangHalfGod%2Fnmos--reg--check-blue?logo=github)](https://github.com/ZhangHalfGod/nmos-reg-check)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![NMOS IS-04](https://img.shields.io/badge/NMOS-IS--04-0A7EA4)](https://specs.amwa.tv/is-04/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> **What this repo is**: Python CLI that sends **HTTP GET only** to an [NMOS IS-04](https://specs.amwa.tv/is-04/) Query API and reports **R01** (the registry answers and a v1.x version is negotiated), **R02** (a node heartbeat is stale when that field exists), and **R05** (a UUID is reused across resources).  
> **Lab flow**: prep (Bonjour, Conan, native registry) → start the registry → point devices and Explorer-class tools → **W1** `--registry` → **W2** `--mdns` → success criteria. Windows process notes: [`docs/deploy-lab/README.md`](docs/deploy-lab/README.md) (Chinese).  
> **Lab addresses (2026-10-13)**: PC `192.168.1.15`, DUT `192.168.1.11`, Query `http://192.168.1.15:3211` (ports `3210`–`3213`).  
> **Report language**: `--lang en` (default) · `--lang zh`.

---

## Table of contents

- [Lab workflow](#lab-workflow)
- [1. Preparation](#1-preparation)
- [2. Start the registry](#2-start-the-registry)
  - [One-click start](#one-click-start)
- [3. Point devices and Explorer-class tools at the registry](#3-point-devices-and-explorer-class-tools-at-the-registry)
- [4. W1 typed Query API](#4-w1-typed-query-api)
- [5. W2 with mdns](#5-w2-with-mdns)
- [6. What counts as success](#6-what-counts-as-success)
- [7. FAQ](#7-faq)
- [Install the CLI](#install-the-cli)
- [Reference](#reference)
- [Checks](#checks)
- [Tests](#tests)
- [License](#license)
- [Lab deploy notes (Chinese)](docs/deploy-lab/README.md)

---

## Lab workflow

The steps below follow the lab machine: prepare first (Bonjour, Conan, the native registry), start the registry, point devices and Explorer-class tools at it, run W1, run W2, then decide what counts as a pass. The 2026-10-13 lab result is in this section. Build and troubleshooting notes are in the [deploy notes](docs/deploy-lab/README.md).

[`docs/deploy-lab/`](docs/deploy-lab/README.md) is the Windows 11 lab log: company-network NAT, Docker Desktop mDNS that never reached the host LAN, and the path that did work — a native Conan `nmos-cpp` registry plus Windows Bonjour. To repeat the path that passed, follow the order below.

Both paths run the same checks.

- **W1** passes the registry Query API by hand: `--registry http://192.168.1.15:3211`.
- **W2** lets the program find the registry on the LAN: `--mdns`. That is the same kind of action as **Auto Discover** in an Explorer-class tool.

Addresses that worked on 2026-10-13:

| Role | Address | Use |
| --- | --- | --- |
| Lab PC, native registry | `192.168.1.15` | `host_address` in `config.json`, and the LAN entry point |
| Query API | `http://192.168.1.15:3211` | W1, and the static query in an Explorer-class tool. Port `3211` |
| Node API | port `3212` | The registry's own Node port. The check command does not use this port |
| Device node (DUT) | `192.168.1.11` | The nmos-node that was already registered |

Registration is port `3210`. The Query WebSocket is `3213`. `nmos-reg-check` talks only to the Query API.

### 1. Preparation

Before step 2, the Windows 11 lab machine needs a running **Bonjour Service** and a built native registry. The repo and the Conan deployer working directory on that machine were `D:\trae_git\nmos-reg-check\`. The config used during the lab was `D:\zc_softwate\Docker\WorkSpace\nmos-registry\config.json`. Those settings are committed as `lab/config.json`; set `host_address` to the LAN IP of the machine that runs the registry. The longer write-up is in the [deploy notes](docs/deploy-lab/README.md#准备阶段).

#### Bonjour on Windows 11

The native registry's DNS-SD option is `with_dnssd=mdnsresponder`. The Conan `mdnsresponder` package may ship tools such as `dns-sd`, but the **operating-system Bonjour Service is a separate install** and must be Running. Without that service, `_nmos-query` is not visible on the LAN.

Install Apple **Bonjour Print Services for Windows** (support article [DL999](https://support.apple.com/kb/DL999); the page title is Bonjour Print Services for Windows v2.0.2). That package registers a Windows service named `Bonjour Service`. After install, set the service startup type to automatic and start it.

Confirm either of these:

- Open Services (`services.msc`). **Bonjour Service** status is **Running**.
- Or in PowerShell:

```powershell
Get-Service 'Bonjour Service'
```

`Status` should be `Running`. If the service is not found, it is not installed in the operating system. The Conan `mdnsresponder` package does not replace it.

#### Install Conan

The lab machine uses Conan 2.x. On Windows that already has Python, install with pip and check the version:

```bat
pip install conan
conan --version
```

Building from source needs the Visual Studio C++ workload: in Visual Studio Installer, select Desktop development with C++. The lab profile is `compiler=msvc` and `compiler.version=194` (Visual Studio 2022, MSVC 19.4x).

#### Deploy binaries with Conan

Run this from `D:\trae_git\nmos-reg-check\`. `--deployer=direct_deploy` writes into the current directory. Keep the working directory on that path so the output lands in `D:\trae_git\nmos-reg-check\direct_deploy\`.

When there is no prebuilt package for `compiler.version=194`, build `nmos-cpp` from source:

```bat
cd /d D:\trae_git\nmos-reg-check
conan install --requires=nmos-cpp/cci.20240223 --deployer=direct_deploy --build=nmos-cpp/cci.20240223
```

When linking cpprestsdk hits the `LNK2019` below, rebuild that dependency from source as well:

```bat
cd /d D:\trae_git\nmos-reg-check
conan install --requires=nmos-cpp/cci.20240223 --deployer=direct_deploy --build=nmos-cpp/cci.20240223 --build=cpprestsdk/*
```

DNS-SD must be `with_dnssd=mdnsresponder`, and the compiler is MSVC 194. The command that actually succeeded on the lab machine is below. Other profile fields stay on the MSVC settings this machine already had. A proxy is configured separately and is not written here.

```bat
cd /d D:\trae_git\nmos-reg-check
conan install --requires=nmos-cpp/cci.20240223 ^
  -o with_dnssd=mdnsresponder ^
  -s compiler=msvc -s compiler.version=194 ^
  --build=nmos-cpp/cci.20240223 --build=cpprestsdk/* ^
  --deployer=direct_deploy
```

Outputs are in `D:\trae_git\nmos-reg-check\direct_deploy\nmos-cpp\bin\Release\`. The same deploy also writes `conanrun*.bat` under `D:\trae_git\nmos-reg-check\`. Those are local build products, already listed in `.gitignore`. Do not commit them. The registry in this lab is:

```text
D:\trae_git\nmos-reg-check\direct_deploy\nmos-cpp\bin\Release\nmos-cpp-registry.exe
```

The same deploy also produces `D:\trae_git\nmos-reg-check\direct_deploy\nmos-cpp\bin\Release\nmos-cpp-node.exe`. The registry uses `nmos-cpp-registry.exe` above.

#### Build pitfalls

| What happened | What to do |
| --- | --- |
| No prebuilt package for `compiler.version=194` | Add `--build=nmos-cpp/cci.20240223` and build from source |
| Source fetch from GitHub times out. Conan retries the `github.com/sony/nmos-cpp` source archive | Set `HTTPS_PROXY` (or `https_proxy`) for the environment, or place the source where Conan can already read it. The proxy address is not written here |
| Link error `LNK2019: __std_find_first_of_trivial_pos_2` from cpprestsdk, ABI does not match the current MSVC | Rebuild with the same MSVC from source: `--build=cpprestsdk/*` |

Other lab conditions:

- For Auto Discover or `--mdns`, the PC and the device are on the same L2 segment. In this lab that is PC `192.168.1.15`, device node `192.168.1.11`, subnet `192.168.1.0/24`.
- While the PC was still behind the Netgear NAT (the PC was `10.0.0.4`, the WAN was `192.168.1.10`), only static Query worked. mDNS does not cross that NAT.
- `rhastie/nmos-cpp` under Docker Desktop was only a quick check of static Query. Auto/mDNS uses the native registry. If the container still holds `3210`–`3213`, stop it first. The Compose directory is `D:\zc_softwate\Docker\WorkSpace\nmos-registry\`.
- Install the CLI before steps 4 and 5. See [Install the CLI](#install-the-cli). Starting the registry does not need that install.

### 2. Start the registry

#### One-click start

On Windows, double-click `scripts/start-lab-registry.bat`, or run either script from any directory. Both resolve the repo root from their own path.

```bat
scripts\start-lab-registry.bat
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-lab-registry.ps1
```

`--check` runs the health check after the Query API answers:

```bat
scripts\start-lab-registry.bat --check
```

| Item | Path, relative to the repo root |
| --- | --- |
| Registry binary | `direct_deploy/nmos-cpp/bin/Release/nmos-cpp-registry.exe` |
| Config | `lab/config.json` |
| Logs | `logs/native-registry.log`, `logs/native-registry.err` |

The binary is not committed. Build it with Conan first; see [Deploy binaries with Conan](#deploy-binaries-with-conan). Edit `host_address` in `lab/config.json` to the LAN IP of the machine running the registry. The committed value `192.168.1.15` is the 2026-10-13 lab PC. The file is UTF-8 with no BOM. `NMOS_REGISTRY_CONFIG` may point at another config file; otherwise the script uses `lab/config.json`.

The script exits if the executable or the config is missing, if the Windows service **Bonjour Service** is missing or not Running (it prints the Bonjour Print Services for Windows / [DL999](https://support.apple.com/kb/DL999) hint and does not install Bonjour), or if TCP `3210`–`3213` are in use (it lists the owning process and does not stop Docker or any other process). It prints the resolved absolute paths and `host_address`, starts the registry in a new console with `Start-Process` (close that window to stop it; stdout and stderr go to `logs/`), waits about 3 seconds, and GETs `http://127.0.0.1:<query_port>/x-nmos/query/`.

With `--check`, a successful probe is followed by `nmos-reg-check --registry http://<host_address>:<query_port> --lang zh` when that command is on `PATH`. If it is not, the script tries `python -m nmos_reg_check` from the repo root, using `.venv` when that environment is present. If the checker is still missing, it warns and leaves the registry running.

The command used on the lab machine that day, with that machine's absolute paths:

```bat
D:\trae_git\nmos-reg-check\direct_deploy\nmos-cpp\bin\Release\nmos-cpp-registry.exe D:\zc_softwate\Docker\WorkSpace\nmos-registry\config.json
```

After it is up, Bonjour advertises `_nmos-query`, `_nmos-registration`, `_nmos-register`, and `_nmos-node`.

### 3. Point devices and Explorer-class tools at the registry

Static query and Auto Discover are two ways to use it.

**Static Query.** A person types the registry Query API:

```text
http://192.168.1.15:3211
```

`192.168.1.15` is the PC running the registry. `3211` is the Query API. On the device, RDS is the registry host the device can actually reach: `192.168.1.15` when it shares the PC's subnet. While the PC was still behind NAT, the device used the Netgear WAN `192.168.1.10`, with TCP `3210`–`3213` forwarded to the PC.

**Auto Discover.** Use Auto Discover in an Explorer-class tool. Keep the PC and the device on the same L2 segment. The registry is the native process from step 2, advertised by Bonjour.

### 4. W1 typed Query API

On the lab PC:

```bat
nmos-reg-check --registry http://192.168.1.15:3211 --lang zh
```

That URL is the registry Query API. The program then requests `/x-nmos/query/` and reads nodes, devices, senders, and receivers. Add `--lang zh` for a Chinese report, and `--json` for JSON.

W1 is the path when the registry address is already known. It is also how you check that W2 selected the LAN entry point.

### 5. W2 with mdns

When the registry is already advertising mDNS, and it is on this PC (or on the same L2 segment):

```bat
nmos-reg-check --mdns --lang zh
```

W2 checks that the registry can be found without typing a URL, which is what Auto Discover does in an Explorer-class tool. It browses `_nmos-query`, then `_nmos-register` if there is no Query service, then the legacy `_nmos-registration` if neither of those is usable. The browse target is the registry. A device `_nmos-node` is not browsed.

The default listen time is 3 seconds. To listen longer:

```bat
nmos-reg-check --mdns --mdns-timeout 5 --lang zh
```

If both `--registry` and `--mdns` are set, the written URL is used, mDNS is not browsed, and stderr says so.

The W2 report starts with a discovery line: the chosen service, its type, its priority, and how many services were found. When this PC also has WSL or VMware adapters, that line can show `172.18.32.1` or `169.254.x`. The LAN entry point is still `http://192.168.1.15:3211`. Check it again with step 4.

### 6. What counts as success

On 2026-10-13, with the addresses above, the lab showed:

- **Auto Discover** in an Explorer-class tool found the registry.
- The device node (`192.168.1.11`) was registered. Nodes, devices, and senders were visible.
- `nmos-reg-check --mdns` found the Query service. The resolved address can be a virtual NIC. See step 5.

A passing command exits 0, and the table has no error. Against this nmos-cpp registry, Query node documents usually have no heartbeat field, so R02 is info. That is still exit code 0. The block below is the report shape with `--lang zh`. The version and counts inside angle brackets change with that day's registry. This is not a saved raw transcript from 2026-10-13:

```text
注册中心: http://192.168.1.15:3211
Query API: <v1.x> http://192.168.1.15:3211/x-nmos/query/<v1.x>/
资源: 节点=<个数>，设备=<个数>，发送器=<个数>，接收器=<个数>

检查项  级别  资源  说明
R01     正常  -     Query API <v1.x> 可达，版本协商成功
R02     信息  -     节点没有 health/heartbeat 字段，已跳过心跳检查
R05     正常  -     节点、设备、发送器、接收器中没有重复 UUID

0 个错误，1 条信息，2 个正常
```

The resource line should match the device node, devices, and senders already visible in the Explorer-class tool. When a heartbeat field is present and older than 12 seconds, R02 becomes an error and the exit code is 1. When the registry cannot be reached, the exit code is 2. The rules for each check are under [Checks](#checks).

### 7. FAQ

| What you see | What to do |
| --- | --- |
| The device cannot reach the registry, and RDS says `127.0.0.1` | `127.0.0.1` points only at the machine that was given that address. On the device, use a registry host it can reach: `192.168.1.15` on the same subnet; during the NAT phase, `192.168.1.10` with TCP `3210`–`3213` forwarded. `10.0.0.4` is inside the NAT, and the device has no reverse path. |
| Static Query works, and Auto in the Explorer-class tool is empty | mDNS from Docker Desktop does not reach the host LAN. The device `_nmos-node` was visible on the LAN at the time. For Auto/mDNS, use the native registry and Bonjour from step 2, with the PC and the device on the same L2 segment. |
| Conan does not build: no prebuilt package for 194, a GitHub source timeout, or `LNK2019: __std_find_first_of_trivial_pos_2` | See [Build pitfalls](#build-pitfalls). From this network, Conan retries the `github.com/sony/nmos-cpp` source archive, which needs `HTTPS_PROXY` or a source tree placed ahead of time. |
| `--mdns` returns `172.18.32.1` or `169.254.x` | WSL and VMware adapters on the lab PC also show up in the resolved addresses. Use W1 to check `http://192.168.1.15:3211`. |
| The registry cannot read a `config.json` that was just written | PowerShell writes JSON with a BOM by default. Rewrite the same content as UTF-8 with no BOM. |
| The native `nmos-cpp-registry.exe` will not start because the port is taken | Stop the Docker registry first and free `3210`–`3213`. |

## Install the CLI

Needed only to run `nmos-reg-check`. Starting the native registry does not need this step. Python 3.10 or newer.

On the lab PC (Windows), the repo is `D:\trae_git\nmos-reg-check\`. Create the virtual environment in that directory:

```bat
cd /d D:\trae_git\nmos-reg-check
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

On other systems:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The install adds the `nmos-reg-check` command. `python -m nmos_reg_check` is the same entry point.

## Reference

After the steps above, use this section to check URL forms, exit codes, and the mDNS selection rules.

### Registry URL

`--registry` accepts any of:

- an origin: `http://host:port`. In the lab this is `http://192.168.1.15:3211`.
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

### Discovery with mdns

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

#### Limitations

- Multicast does not cross a typical Docker bridge, and it did not leave Docker Desktop onto the lab LAN. Static Query against the published ports still worked. Auto/mDNS in this lab uses the native registry in the steps above. A container on Linux needs host networking (`docker run --network host`) or an explicit `--registry`. The same limit applies to many VMs and WSL2 setups.
- Linux needs UDP port 5353 and a route for 224.0.0.251 (and IPv6 multicast when the host has IPv6). macOS and Windows receive mDNS on the host in the usual way; the library is [python-zeroconf](https://github.com/python-zeroconf/python-zeroconf) (`zeroconf` on PyPI), which supports all three.
- Link-local addresses are used only when the advertisement has no other address. An IPv6 link-local address is used without a zone index, so it may be unreachable. On the lab PC, a virtual NIC address such as `172.18.32.1` or `169.254.x` can be chosen; the LAN Query endpoint remains `http://192.168.1.15:3211`.
- This tool does not browse unicast DNS-SD and does not retry a different discovered registry in the same run.

### Report shape

The block below is what a report looks like, using fixture data (`http://192.168.1.20:8080`, nodes=2). It is not the 2026-10-13 lab output. For the lab, see [What counts as success](#6-what-counts-as-success).

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

### R01 reachable and version negotiated

R01 passes when the Query API root for the chosen version can be read and the four collections return HTTP 200 and JSON. A connection failure is still reported as R01, with exit code 2. An HTTP error, a non-JSON body, a server that does not advertise `query/`, or a version list with no v1.x release is R01 with exit code 1.

IS-04 error bodies `{"code", "error", "debug"}` contribute the `error` string to the R01 message.

### R02 stale heartbeat when a timestamp is present

IS-04 Query API **node** documents do not include a heartbeat. Confirmed against the v1.3.3 node schema and the Query API examples: a node has `id`, `version`, `label`, `href`, `api`, and so on. `version` is a TAI timestamp `<seconds>:<nanoseconds>` of the last attribute change. Heartbeats do not update it, so this tool does not treat `version` as a heartbeat. Doing so would flag every stable node.

The heartbeat timestamp is defined on the Registration API. `GET /x-nmos/registration/{version}/health/nodes/{nodeId}` (debug read) and the heartbeat `POST` response use:

```json
{"health": "1441974485"}
```

`health` is a string of integer seconds. nmos-cpp stores that value on the TAI clock (leap seconds are not applied). This program does not call the Registration API, so it does not see that field on a stock registry.

R02 instead reads these fields when a node object already carries them: `health`, `heartbeat`, `last_heartbeat`, `heartbeat_timestamp`, `last_seen`. A number, a digit string, or `seconds:nanoseconds` is TAI. A value with 13 or more digits is milliseconds; 15 or more is microseconds. An object may nest the timestamp under `health`, `timestamp`, `seconds`, or `tai`. An ISO-8601 value (a trailing `Z` is accepted) is UTC. The TAI offset used here is 37 seconds, the value in force since 2017-01-01.

If none of those fields exist, R02 is **info** and the process can still exit 0. A present value that is not a timestamp is info for that node. A timestamp older than 12 seconds is an error. A timestamp exactly 12 seconds old is not an error: the specification removes a node only after heartbeats have been missing for longer than the garbage-collection interval. The default interval is 12 seconds (two missed 5-second heartbeats).

### R05 duplicate UUIDs

Ids are compared case-insensitively with the IS-04 pattern (`8-4-4-4-12` lowercase hex, version nibble 1–5, variant nibble 8, 9, a, or b). The same id on two resource types is a duplicate: registration rejects an id that another resource type already uses. Ids that are not UUIDs are ignored. Sources and flows are not loaded in this version, so a clash that involves only those types is not visible.

An identical copy of a resource repeated on a later `Link: rel="next"` page is treated as page overlap, not as a second registration. Two copies in the same response are a duplicate.

## Tests

```bash
pytest
```

Tests load JSON fixtures from `tests/fixtures/` and answer them with an in-process HTTP mock. No live registry is required. mDNS is replaced with a fake browse, so the tests do not need multicast. The fixtures follow the IS-04 v1.3 Query API examples: version lists use a trailing slash (`"v1.3/"`), the API root lists `nodes/`, `devices/`, `senders/`, and `receivers/`, and resource bodies are JSON arrays.

## License

MIT. See [LICENSE](LICENSE).
