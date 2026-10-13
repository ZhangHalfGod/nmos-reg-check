# nmos-reg-check

Read-only health check for an [NMOS IS-04](https://specs.amwa.tv/is-04/) registry. It sends **HTTP GET only** to the Query API and reports three results: the registry answers and a v1.x version is negotiated (**R01**), a node heartbeat is stale when that field exists (**R02**), and a UUID is reused across resources (**R05**).

下面按实验机上的顺序写：先做准备（Bonjour、Conan、本机 Registry），再启动 Registry，再让设备和 Explorer 类工具指向它，然后跑 W1、W2，最后看什么样算通过。2026-10-13 的实机结果也在这一节。编译和排错过程在部署笔记里。

## 文档导航

- [实机部署过程（Registry 与自动发现）](docs/deploy-lab/README.md)
- [实验室操作顺序](#实验室操作顺序)
- [准备阶段](#1-准备阶段)
- [安装 CLI](#安装-cli)
- [检查项](#checks)
- [测试](#tests)
- [许可证](#license)

[`docs/deploy-lab/`](docs/deploy-lab/README.md) 是 Windows 11 实验机的过程记录：公司网 NAT、Docker Desktop 的 mDNS 到不了主机局域网，以及最后改用本机 Conan `nmos-cpp` 加 Windows Bonjour。要复现通过的那条路径，按下面的顺序做。

## 实验室操作顺序

两条路最后做的是同一组检查。

- **W1** 手写 Registry 的 Query API：`--registry http://192.168.1.15:3211`。
- **W2** 让程序在局域网里找 Registry：`--mdns`。这和 Explorer 类工具的 **Auto Discover** 是同一类动作。

2026-10-13 能工作的地址：

| 角色 | 地址 | 用途 |
| --- | --- | --- |
| 实验 PC，本机 Registry | `192.168.1.15` | `config.json` 的 `host_address`，也是局域网入口 |
| Query API | `http://192.168.1.15:3211` | W1、Explorer 类工具的静态查询。端口 `3211` |
| Node API | 端口 `3212` | Registry 自己的 Node 端口。检查命令不填这个端口 |
| 真机 Node（DUT，测试设备） | `192.168.1.11` | 已经注册进来的 nmos-node |

Registration 端口是 `3210`，Query WebSocket 是 `3213`。`nmos-reg-check` 只访问 Query API。

### 1. 准备阶段

做第 2 步之前，Windows 11 实验机上要有正在运行的 **Bonjour Service**，以及编好的本机 Registry。仓库和 Conan deployer 的工作目录是 `D:\trae_git\nmos-reg-check\`。`config.json` 不在仓库里，在 `D:\zc_softwate\Docker\WorkSpace\nmos-registry\config.json`。更完整的过程在 [部署笔记](docs/deploy-lab/README.md#准备阶段)。

#### Bonjour（Windows 11）

本机 Registry 的 DNS-SD 选项是 `with_dnssd=mdnsresponder`。Conan 的 `mdnsresponder` 包可能带上 `dns-sd` 一类工具，但 **操作系统里的 Bonjour Service 要另外安装**，并且状态是 Running。没有这个服务，局域网上看不到 `_nmos-query`。

安装 Apple 的 **Bonjour Print Services for Windows**（支持文档 [DL999](https://support.apple.com/kb/DL999)，页面标题为 Bonjour Print Services for Windows v2.0.2）。这份安装包会注册名为 `Bonjour Service` 的 Windows 服务。装完后把该服务的启动类型设为自动，并启动它。

安装后确认，二选一：

- 打开「服务」（`services.msc`），**Bonjour Service** 的状态是 **Running**。
- 或在 PowerShell：

```powershell
Get-Service 'Bonjour Service'
```

`Status` 为 `Running` 即可。若提示找不到服务，说明操作系统里还没有装上，Conan 的 `mdnsresponder` 不能代替它。

#### 安装 Conan

实验机使用 Conan 2.x。在已有 Python 的 Windows 上，推荐用 pip 安装，然后核对版本：

```bat
pip install conan
conan --version
```

从源码编译需要 Visual Studio 的 C++ 工作负载：在 Visual Studio Installer 里勾选「使用 C++ 的桌面开发」（Desktop development with C++）。实验机的 profile 是 `compiler=msvc`、`compiler.version=194`（Visual Studio 2022 的 MSVC 19.4x）。

#### 用 Conan 部署二进制

在 `D:\trae_git\nmos-reg-check\` 下执行。`--deployer=direct_deploy` 把文件写到当前目录，工作目录保持为这一路径，输出才落在 `D:\trae_git\nmos-reg-check\direct_deploy\`。

没有 `compiler.version=194` 的预编译包时，从源码编 `nmos-cpp`：

```bat
cd /d D:\trae_git\nmos-reg-check
conan install --requires=nmos-cpp/cci.20240223 --deployer=direct_deploy --build=nmos-cpp/cci.20240223
```

链接 cpprestsdk 出现下面的 `LNK2019` 时，把这份依赖也从源码重编：

```bat
cd /d D:\trae_git\nmos-reg-check
conan install --requires=nmos-cpp/cci.20240223 --deployer=direct_deploy --build=nmos-cpp/cci.20240223 --build=cpprestsdk/*
```

DNS-SD 必须是 `with_dnssd=mdnsresponder`，编译器是 MSVC 194。实验机上实际成功的命令是（profile 里其余字段沿用这台机器已有的 MSVC 设置；代理另配，不写在这里）：

```bat
cd /d D:\trae_git\nmos-reg-check
conan install --requires=nmos-cpp/cci.20240223 ^
  -o with_dnssd=mdnsresponder ^
  -s compiler=msvc -s compiler.version=194 ^
  --build=nmos-cpp/cci.20240223 --build=cpprestsdk/* ^
  --deployer=direct_deploy
```

产物在 `D:\trae_git\nmos-reg-check\direct_deploy\nmos-cpp\bin\Release\`。同一次部署还会在 `D:\trae_git\nmos-reg-check\` 生成 `conanrun*.bat`。这些都是本机编译结果，已经写进 `.gitignore`，不要提交。这次充当 Registry 的是：

```text
D:\trae_git\nmos-reg-check\direct_deploy\nmos-cpp\bin\Release\nmos-cpp-registry.exe
```

同一次部署还带出 `D:\trae_git\nmos-reg-check\direct_deploy\nmos-cpp\bin\Release\nmos-cpp-node.exe`。Registry 用上面的 `nmos-cpp-registry.exe`。

#### 编译时踩过的坑

| 现象 | 处理 |
| --- | --- |
| 没有 `compiler.version=194` 的预编译包 | 加上 `--build=nmos-cpp/cci.20240223`，从源码编 |
| 从国内拉 GitHub 源码超时。Conan 会重试 `github.com/sony/nmos-cpp` 的源码归档 | 给环境设置 `HTTPS_PROXY`（或 `https_proxy`），或事先把源码放到 Conan 能取用的位置。这里不写代理地址 |
| 链接错误 `LNK2019: __std_find_first_of_trivial_pos_2`，来自 cpprestsdk，ABI 和当前 MSVC 不一致 | 用同一套 MSVC 从源码重编：`--build=cpprestsdk/*` |

其余实验条件：

- 做 Auto Discover 或 `--mdns` 时，PC 和设备在同一二层。实验里是 PC `192.168.1.15`，真机 Node `192.168.1.11`，子网 `192.168.1.0/24`。
- PC 还在 Netgear NAT 后面时（当时 PC 是 `10.0.0.4`，WAN 是 `192.168.1.10`），只能做静态 Query。mDNS 过不了那层 NAT。
- Docker Desktop 里的 `rhastie/nmos-cpp` 只用来快速确认静态 Query。Auto/mDNS 用本机 Registry。容器如果还占着 `3210`–`3213`，先停掉。Compose 目录是 `D:\zc_softwate\Docker\WorkSpace\nmos-registry\`。
- 跑第 4、5 步之前安装命令行工具，见 [安装 CLI](#安装-cli)。启动 Registry 不需要这个安装。

### 2. 启动 Registry

配置沿用实验机上的 `config.json`：`host_address` 为 `192.168.1.15`，编码是 UTF-8、无 BOM。可执行文件在仓库工作目录下（不提交），配置文件在 Docker 那份目录里：

```bat
D:\trae_git\nmos-reg-check\direct_deploy\nmos-cpp\bin\Release\nmos-cpp-registry.exe D:\zc_softwate\Docker\WorkSpace\nmos-registry\config.json
```

起来之后，Bonjour 上会注册 `_nmos-query`、`_nmos-registration`、`_nmos-register`、`_nmos-node`。

### 3. 让设备和 Explorer 类工具指向 Registry

静态查询和 Auto Discover 是两种用法。

**静态 Query。** 地址由人填写，填 Registry 的 Query API：

```text
http://192.168.1.15:3211
```

`192.168.1.15` 是跑 Registry 的 PC。`3211` 是 Query API。设备侧的 RDS 填设备在网上能够访问到的 Registry 主机：和 PC 同一子网时是 `192.168.1.15`。PC 还在 NAT 后面时，设备填 Netgear WAN `192.168.1.10`，并已把 TCP `3210`–`3213` 映射到 PC。

**Auto Discover。** 在 Explorer 类工具里使用 Auto Discover。PC 与设备保持同一二层，Registry 用第 2 步的本机进程，由 Bonjour 发广告。

### 4. W1：手写 Query API

在实验 PC 上：

```bat
nmos-reg-check --registry http://192.168.1.15:3211 --lang zh
```

这个 URL 是 Registry 的 Query API。程序接着请求 `/x-nmos/query/`，再读取 nodes、devices、senders、receivers。中文报告加上 `--lang zh`，要 JSON 再加上 `--json`。

W1 适合已经知道 Registry 地址的时候，也用来核对 W2 选中的是不是局域网入口。

### 5. W2：`--mdns`

Registry 已经在发 mDNS、并且就在这台 PC 上（或同一二层）时：

```bat
nmos-reg-check --mdns --lang zh
```

W2 用来确认「不手填 URL 也能找到 Registry」，也就是 Explorer 类工具里 Auto Discover 在做的事。它浏览 `_nmos-query`，没有 Query 时再用 `_nmos-register`，仍没有再用旧的 `_nmos-registration`。浏览对象是 Registry。设备的 `_nmos-node` 不在浏览范围内。

默认听 3 秒。需要更长时间时：

```bat
nmos-reg-check --mdns --mdns-timeout 5 --lang zh
```

同时写了 `--registry` 和 `--mdns` 时，使用写出的 URL，不再浏览，stderr 会说明已跳过 mDNS。

W2 报告开头有一行发现结果，标出选中的服务、类型、优先级和找到的个数。这台 PC 上还有 WSL、VMware 网卡时，这一行里的地址可能是 `172.18.32.1` 或 `169.254.x`。局域网入口仍然是 `http://192.168.1.15:3211`，用第 4 步再查一次。

### 6. 怎样算成功

2026-10-13 在上面这套地址上看到的是：

- Explorer 类工具的 **Auto Discover** 找到 Registry。
- 真机 Node（`192.168.1.11`）已经注册，nodes、devices、senders 可见。
- `nmos-reg-check --mdns` 发现了 Query 服务。解析到的地址可能是虚拟网卡，见第 5 步。

命令行通过时退出码是 0，表格里没有「错误」。对着这台 nmos-cpp Registry，Query 的 node 文档通常没有心跳字段，R02 会是「信息」，这仍然是退出码 0。下面是 `--lang zh` 时的报告形状，尖括号里的版本和个数随当天的 Registry 变化，不是一份保存下来的 2026-10-13 原始输出：

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

资源行里应能对上 Explorer 类工具里已经看见的真机节点、设备和发送器。心跳字段存在而且早于 12 秒时，R02 变为错误，退出码为 1。连不上 Registry 时退出码为 2。各项判定见 [检查项](#checks)。

### 7. 常见问题

| 现象 | 处理 |
| --- | --- |
| 设备连不上 Registry，RDS 里写了 `127.0.0.1` | `127.0.0.1` 只指向填写它的那台机器。设备填它能访问的 Registry 主机：同网段用 `192.168.1.15`；NAT 阶段用 `192.168.1.10`，并映射 TCP `3210`–`3213`。`10.0.0.4` 在 NAT 内侧，设备没有反向路径。 |
| 静态 Query 正常，Explorer 类工具的 Auto 为空 | Docker Desktop 发出的 mDNS 到不了主机局域网。设备的 `_nmos-node` 当时在 LAN 上是可见的。Auto/mDNS 改用第 2 步的本机 Registry 和 Bonjour，PC 与设备放在同一二层。 |
| Conan 编不过：没有 194 的预编译包、GitHub 源码超时，或 `LNK2019: __std_find_first_of_trivial_pos_2` | 见上面的[编译时踩过的坑](#编译时踩过的坑)。国内访问时 Conan 会重试 `github.com/sony/nmos-cpp` 的源码归档，需要 `HTTPS_PROXY` 或事先放好源码。 |
| `--mdns` 给出 `172.18.32.1` 或 `169.254.x` | 实验 PC 上的 WSL、VMware 网卡也会出现在解析结果里。用 W1 核对 `http://192.168.1.15:3211`。 |
| Registry 读不了刚写的 `config.json` | PowerShell 默认会写出带 BOM 的 JSON。把同一份内容重写成 UTF-8、无 BOM。 |
| 本机 `nmos-cpp-registry.exe` 起不来，端口被占 | 先停掉 Docker 里的 Registry，释放 `3210`–`3213`。 |

## 安装 CLI

只有运行 `nmos-reg-check` 时需要。启动本机 Registry 不需要这一步。Python 3.10 或更新。

实验 PC（Windows）。仓库在 `D:\trae_git\nmos-reg-check\`，在该目录里创建虚拟环境：

```bat
cd /d D:\trae_git\nmos-reg-check
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

其它系统：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

安装后得到 `nmos-reg-check`。`python -m nmos_reg_check` 是同一个入口。

## 参考

做完上面的步骤之后，再用这一节核对 URL 写法、退出码和 mDNS 选择规则。

### Registry URL

`--registry` 接受：

- 主机根地址：`http://host:port`。实验里是 `http://192.168.1.15:3211`。
- `/x-nmos/` 前面的路径前缀：`http://host:port/nms`
- Query API 根：`http://host:port/x-nmos/query/`
- 写死的版本：`http://host:port/x-nmos/query/v1.3/`（末尾的 `/nodes` 会被忽略）

从主机根地址或 Query API 根出发时，使用 Registry 声明的最高 **v1** 次版本。v1.0 到 Registry 列出的任意 v1 次版本都可以。更高的主版本不会被使用。写死的版本按原文请求。

客户端读取：

- `GET /x-nmos/`
- `GET /x-nmos/query/`
- `GET /x-nmos/query/{version}/`
- `GET /x-nmos/query/{version}/nodes`
- `GET /x-nmos/query/{version}/devices`
- `GET /x-nmos/query/{version}/senders`
- `GET /x-nmos/query/{version}/receivers`

这些集合 URL 是 IS-04 v1.3 规定的。每个响应是资源的 JSON 数组。Registry 用 `paging.since` / `paging.until` 分页时，会跟随 `Link: rel="next"`。单个资源对象也可以，包装 `{"nodes": [...]}` 和 `{"data": [...]}` 也可以（还有 `items`、`resources`、`results`、`result`）。

### Options

| Option | Meaning |
| --- | --- |
| `--registry URL` | Registry 主机根地址或 Query API URL。与 `--mdns` 同时给出时使用这个 URL。 |
| `--mdns` | 用 mDNS 发现 Registry，再做同一组检查。 |
| `--mdns-timeout SECONDS` | 听 mDNS 的秒数，默认 3，必须大于 0。 |
| `--json` | 把报告以 JSON 写到 stdout。 |
| `--lang en\|zh` | 报告语言，默认 `en`。 |
| `--insecure` | 不校验 TLS 证书。 |

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | 没有 severity 为 `error` 的结果。信息项，包括跳过的心跳检查，仍然是 0。 |
| 1 | Registry 有响应，并且至少一项检查报了错误。 |
| 2 | 没有 HTTP 响应（DNS、连接、超时、TLS），或者命令本身不能运行（URL 不对、缺少 `--registry` / `--mdns`、`--mdns-timeout` 非法、mDNS 什么都没找到、mDNS 自身失败）。 |

### Discovery (`--mdns`)

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

下面这段是报告长什么样，用的是一组夹具数据（`http://192.168.1.20:8080`，nodes=2）。它不是 2026-10-13 的实机输出。实机看第 6 步。

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
