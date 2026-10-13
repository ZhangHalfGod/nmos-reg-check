# nmos-reg-check — NMOS IS-04 注册中心健康检查

**Language / 语言:** [English](README.md) | [中文](README.zh-CN.md)

> **只读的 NMOS IS-04 注册中心健康检查：用手写 Query URL 核验实验室注册表（W1），或用 mDNS 发现注册中心后再做同一组检查（W2）。**

[![GitHub](https://img.shields.io/badge/GitHub-ZhangHalfGod%2Fnmos--reg--check-blue?logo=github)](https://github.com/ZhangHalfGod/nmos-reg-check)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![NMOS IS-04](https://img.shields.io/badge/NMOS-IS--04-0A7EA4)](https://specs.amwa.tv/is-04/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> **本仓做什么**：Python 命令行，只对 [NMOS IS-04](https://specs.amwa.tv/is-04/) Query API 发 **HTTP GET**，报告三项：**R01** 注册中心有响应且协商出 v1.x，**R02** 节点带心跳字段时该心跳已过期，**R05** 同一 UUID 被多个资源复用。  
> **实验顺序**：准备（Bonjour、Conan、本机 Registry）→ 启动 Registry → 让设备和 Explorer 类工具指向它 → **W1** `--registry` → **W2** `--mdns` → 怎样算成功。过程记录：[docs/deploy-lab/README.md](docs/deploy-lab/README.md)。  
> **2026-10-13 地址**：实验 PC `192.168.1.15`，真机 Node `192.168.1.11`，Query `http://192.168.1.15:3211`（端口 `3210`–`3213`）。  
> **报告语言**：`--lang en`（默认）· `--lang zh`。

---

## 目录

- [实验室操作顺序](#实验室操作顺序)
- [1. 准备阶段](#1-准备阶段)
- [2. 启动 Registry](#2-启动-registry)
- [3. 让设备和 Explorer 类工具指向 Registry](#3-让设备和-explorer-类工具指向-registry)
- [4. W1 手写 Query API](#4-w1-手写-query-api)
- [5. W2 使用 mdns](#5-w2-使用-mdns)
- [6. 怎样算成功](#6-怎样算成功)
- [7. 常见问题](#7-常见问题)
- [安装 CLI](#安装-cli)
- [参考](#参考)
- [检查项](#检查项)
- [测试](#测试)
- [许可证](#许可证)
- [实机部署过程](docs/deploy-lab/README.md)

---

## 实验室操作顺序

下面按实验机上的顺序写：先做准备（Bonjour、Conan、本机 Registry），再启动 Registry，再让设备和 Explorer 类工具指向它，然后跑 W1、W2，最后看什么样算通过。2026-10-13 的实机结果也在这一节。编译和排错过程在[部署笔记](docs/deploy-lab/README.md)。

[`docs/deploy-lab/`](docs/deploy-lab/README.md) 是 Windows 11 实验机的过程记录：公司网 NAT、Docker Desktop 的 mDNS 到不了主机局域网，以及最后改用本机 Conan `nmos-cpp` 加 Windows Bonjour。要复现通过的那条路径，按下面的顺序做。

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

#### Windows 11 上的 Bonjour

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

### 4. W1 手写 Query API

在实验 PC 上：

```bat
nmos-reg-check --registry http://192.168.1.15:3211 --lang zh
```

这个 URL 是 Registry 的 Query API。程序接着请求 `/x-nmos/query/`，再读取 nodes、devices、senders、receivers。中文报告加上 `--lang zh`，要 JSON 再加上 `--json`。

W1 适合已经知道 Registry 地址的时候，也用来核对 W2 选中的是不是局域网入口。

### 5. W2 使用 mdns

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

资源行里应能对上 Explorer 类工具里已经看见的真机节点、设备和发送器。心跳字段存在而且早于 12 秒时，R02 变为错误，退出码为 1。连不上 Registry 时退出码为 2。各项判定见 [检查项](#检查项)。

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

### 注册中心 URL

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

### 选项

| 选项 | 含义 |
| --- | --- |
| `--registry URL` | Registry 主机根地址或 Query API URL。与 `--mdns` 同时给出时使用这个 URL。 |
| `--mdns` | 用 mDNS 发现 Registry，再做同一组检查。 |
| `--mdns-timeout SECONDS` | 听 mDNS 的秒数，默认 3，必须大于 0。 |
| `--json` | 把报告以 JSON 写到 stdout。 |
| `--lang en\|zh` | 报告语言，默认 `en`。 |
| `--insecure` | 不校验 TLS 证书。 |

### 退出码

| 码 | 含义 |
| --- | --- |
| 0 | 没有 severity 为 `error` 的结果。信息项，包括跳过的心跳检查，仍然是 0。 |
| 1 | Registry 有响应，并且至少一项检查报了错误。 |
| 2 | 没有 HTTP 响应（DNS、连接、超时、TLS），或者命令本身不能运行（URL 不对、缺少 `--registry` / `--mdns`、`--mdns-timeout` 非法、mDNS 什么都没找到、mDNS 自身失败）。 |

### mDNS 发现

`--mdns` 在 `.local` 里浏览 IS-04 的 DNS-SD 组播类型：

| 服务类型 | 是什么 |
| --- | --- |
| `_nmos-query._tcp` | Query API。优先使用，因为检查打的就是 Query。 |
| `_nmos-register._tcp` | Registration API。只有找不到 Query 服务时才用。 |
| `_nmos-registration._tcp` | 旧的 Registration API（IS-04 v1.2 及更早）。上面两种都不可用时才用。 |

`_nmos-node._tcp` 是 Node API，不是注册中心，不浏览。单播 DNS-SD（规范里的另一条浏览路径，配置了搜索域时使用）没有实现。在局域网上，Auto Discover 就是这种组播浏览。

每条广告给出一个主机根地址，`http://address:port` 或 `https://address:port`。地址取自 mDNS 的 A/AAAA 记录，后面的 HTTP 请求不必再解析 `.local` 名字。优先单播 IPv4，然后单播 IPv6，然后链路本地地址，最后是回环地址。端口是 SRV 端口。HTTP 路径不在广告里；处理 `--registry` 的同一个客户端接着请求 `/x-nmos/query/`。

TXT 记录按 IS-04：

- `api_proto` — `http` 或 `https`。没有这个值时当作 `http`。旧实现同时列出两者时，使用 `https`。
- `api_ver` — 逗号分隔的版本。没有 v1.x 的服务会跳过。缺少 `api_ver` 时仍保留，Query 客户端按平时的方式协商 v1。
- `api_auth` — `true` 表示 API 需要授权。这些服务会跳过；本工具不发送凭据。
- `pri` — 数值越小优先级越高（`0` 最高）。缺失或不是整数时当作 `100`。IS-04 把 `100` 留给开发用注册中心，因此任何正在使用的注册中心（`0`–`99`）都会优先于它。

多于一个服务可用时，选择是稳定的（不是随机）：

1. 先 Query，再当前 Registration，再旧 Registration。
2. 更小的 `pri`。
3. `https` 先于 `http`。
4. 实例名，然后主机，然后端口。

文本报告和 stderr 会写出选中的服务、类型、优先级，以及找到了多少个。`--json` 增加一个 `discovery` 对象，包含同一次选择和完整候选列表。Registration 广告仍通过该主机和端口上的 Query API 检查。Registration 和 Query 放在同一台主机上时，通常就是这样部署的。该主机没有响应时，同一次运行不会自动改试下一个候选。

没有可用结果时退出码为 2。这包括浏览为空、每条广告都要求授权或没有 v1 API，以及 mDNS 自身失败（例如没有组播权限）。`--mdns-timeout` 是收听秒数，默认 3。响应里还没有地址时，解析每条应答最多再花 1 秒。

#### 限制

- 组播过不了常见的 Docker 网桥，这次实验里也没有从 Docker Desktop 到达主机局域网。对已发布端口做静态 Query 仍然是通的。本实验的 Auto/mDNS 使用上面步骤里的本机 Registry。Linux 上的容器需要主机网络（`docker run --network host`），或者显式传入 `--registry`。许多虚拟机和 WSL2 也是同样的限制。
- Linux 需要 UDP 5353，以及到 224.0.0.251 的路由（主机有 IPv6 时还要 IPv6 组播）。macOS 和 Windows 按通常方式在主机上接收 mDNS。所用库是 [python-zeroconf](https://github.com/python-zeroconf/python-zeroconf)（PyPI 上的 `zeroconf`），三个系统都支持。
- 只有广告里没有其它地址时才使用链路本地地址。IPv6 链路本地地址不带区域索引，因此可能不可达。实验 PC 上可能选中 `172.18.32.1` 或 `169.254.x` 这类虚拟网卡地址；局域网 Query 入口仍是 `http://192.168.1.15:3211`。
- 本工具不浏览单播 DNS-SD，同一次运行也不会改试另一个发现到的注册中心。

### 报告形状

下面这段是报告长什么样，用的是一组夹具数据（`http://192.168.1.20:8080`，nodes=2）。它不是 2026-10-13 的实机输出。实机看[怎样算成功](#6-怎样算成功)。

`--lang en` 时：

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

同一组夹具在 `--lang zh` 时，表头和说明换成中文（列宽由程序按显示宽度对齐，下面只保留措辞）：

```text
注册中心: http://192.168.1.20:8080
Query API: v1.3 http://192.168.1.20:8080/x-nmos/query/v1.3/
资源: 节点=2，设备=2，发送器=1，接收器=1

检查项  级别  资源  说明
R01     正常  -     Query API v1.3 可达，版本协商成功
R02     信息  -     节点没有 health/heartbeat 字段，已跳过心跳检查
R05     正常  -     节点、设备、发送器、接收器中没有重复 UUID

0 个错误，1 条信息，2 个正常
```

加上 `--json` 时，字段名不变，`message` 跟随 `--lang`。下面是 `--lang en` 的形状：

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

## 检查项

### R01 可达且完成版本协商

选定版本的 Query API 根能读到，并且四个集合都返回 HTTP 200 和 JSON 时，R01 通过。连接失败仍记为 R01，退出码为 2。HTTP 错误、非 JSON 正文、服务器没有声明 `query/`，或版本列表里没有 v1.x，都是 R01，退出码为 1。

IS-04 错误体 `{"code", "error", "debug"}` 会把其中的 `error` 字符串放进 R01 的说明。

### R02 有时间戳时检查过期心跳

IS-04 Query API 的 **node** 文档不含心跳。对照 v1.3.3 的 node schema 和 Query API 示例可以确认：节点有 `id`、`version`、`label`、`href`、`api` 等。`version` 是上次属性变更的 TAI 时间戳，格式为 `<秒>:<纳秒>`。心跳不会更新它，因此本工具不把 `version` 当作心跳。那样做会把每个稳定节点都标成异常。

心跳时间戳定义在 Registration API 上。`GET /x-nmos/registration/{version}/health/nodes/{nodeId}`（调试读取）和心跳 `POST` 的响应使用：

```json
{"health": "1441974485"}
```

`health` 是整秒的字符串。nmos-cpp 按 TAI 时钟保存这个值（不应用闰秒）。本程序不调用 Registration API，因此在未改过的注册中心上看不到这个字段。

节点对象自己已经带有下列字段时，R02 改为读取它们：`health`、`heartbeat`、`last_heartbeat`、`heartbeat_timestamp`、`last_seen`。数字、纯数字字符串，或 `秒:纳秒`，按 TAI 解释。13 位及以上按毫秒，15 位及以上按微秒。对象可以把时间戳嵌在 `health`、`timestamp`、`seconds` 或 `tai` 下面。ISO-8601（接受末尾的 `Z`）按 UTC。这里使用的 TAI 偏移是 37 秒，即 2017-01-01 起生效的值。

这些字段都不存在时，R02 为**信息**，进程仍可以退出码 0。字段在，但不是时间戳，对该节点记为信息。早于 12 秒的时间戳是错误。刚好 12 秒不是错误：规范只在心跳缺失时间长于垃圾回收间隔之后才删除节点。默认间隔是 12 秒（两次未收到的 5 秒心跳）。

### R05 重复 UUID

标识按 IS-04 模式做大小写不敏感比较（`8-4-4-4-12` 小写十六进制，版本半字节 1–5，变体半字节 8、9、a 或 b）。同一标识出现在两种资源类型上就是重复：注册会拒绝已被另一种资源类型占用的标识。不是 UUID 的标识忽略。这一版不加载 sources 和 flows，因此只涉及这两类的冲突看不到。

同一资源在后面的 `Link: rel="next"` 页上原样再出现一次，视为分页重叠，不是第二次注册。同一次响应里出现两份则是重复。

## 测试

```bash
pytest
```

测试从 `tests/fixtures/` 加载 JSON 夹具，用进程内的 HTTP 模拟来应答。不需要活的注册中心。mDNS 换成假的浏览，因此测试不需要组播。夹具遵循 IS-04 v1.3 Query API 示例：版本列表带末尾斜杠（`"v1.3/"`），API 根列出 `nodes/`、`devices/`、`senders/`、`receivers/`，资源正文是 JSON 数组。

## 许可证

MIT。见 [LICENSE](LICENSE)。
