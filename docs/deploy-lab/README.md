# 实机部署：NMOS Registry 与自动发现（mDNS）

本文为中文过程记录。工具说明：[中文](../../README.zh-CN.md) · [English](../../README.md)。

Windows 11 实验机上的过程记录。要按顺序复现「准备 → 启动 Registry → 指向设备 / Explorer 类工具 → 跑检查 → 看结果」，用中文 README 的[实验室操作顺序](../../README.zh-CN.md#实验室操作顺序)。本文保留当时怎么走到那套做法，包括没有走通的路径。Bonjour 安装、Conan 命令和编译问题见下面的[准备阶段](#准备阶段)。

对象是一台真机 Node（nmos-node，`192.168.1.11`）和一台跑在本机上的 NMOS Registry，用来确认 [nmos-reg-check](../../README.zh-CN.md) 的两条路径都能对着实机工作：

- **W1**：手动指定 Registry URL（`--registry`），只对 Query API 做 HTTP GET。
- **W2**：`--mdns` 在局域网里浏览 `_nmos-query`、`_nmos-register`、`_nmos-registration`，选中一个服务后再走同一套检查。这和 Explorer 类工具的 **Auto Discover** 是同一类动作：先找到 Registry，再访问它。

下面按实际走过的顺序写。命令、路径、地址保持实验时的写法。仓库和 Conan deployer 的工作目录是 `D:\trae_git\nmos-reg-check\`。Docker 与当时的 `config.json` 在 `D:\zc_softwate\Docker\WorkSpace\nmos-registry\`。同一份内容现已提交为 `lab/config.json`。

## 最后能工作的状态

2026-10-13，PC 与设备在同一二层、同一子网：

| 角色 | 地址 |
| --- | --- |
| 实验 PC | `192.168.1.15` |
| 真机 Node（DUT，测试设备，nmos-node） | `192.168.1.11` |
| Registry 的 `host_address` | `192.168.1.15` |

Registry 是本机 Conan 编出来的 `nmos-cpp`，DNS-SD 走 Windows Bonjour（mdnsresponder），不是 Docker，也不是 mDNS reflector。端口与原先 Docker 那份配置相同：Registration `3210`，Query `3211`，Node `3212`，Query WebSocket `3213`。

当天的结果：

- Explorer 类工具的 **Auto Discover** 能找到这台 Registry。
- 真机 Node（`192.168.1.11`）完成注册，Query 里能看到 nodes、devices、senders。
- `nmos-reg-check --mdns` 能发现 Query 服务。它有时会选到虚拟网卡上的地址（见文末），局域网真正要访问的仍是 `192.168.1.15`。

## 拓扑是怎么变的

### 公司网在 NAT 后面

一开始设备和 PC 不在同一个二层。

```text
公司网 192.168.1.0/24
  真机 Node (DUT)         192.168.1.11
  Netgear WAN             192.168.1.10
        |
        |  NAT，内侧 10.0.0.0/24
        |
  PC                      10.0.0.4
```

设备在 `192.168.1.0/24`。PC 接在 Netgear 后面，WAN 是 `192.168.1.10`，LAN 是 `10.0.0.0/24`，PC 当时是 `10.0.0.4`。

这一段只能先做静态 Query，做不了 Auto/mDNS。mDNS 不过这层 NAT。

静态路径上做过的事：

- 在 Netgear 上把 TCP `3210`–`3213` 映射到 PC。
- 设备上的 RDS（它用来找 Registry 的地址）必须填 `192.168.1.0/24` 上设备真能访问到的地址，也就是当时的 WAN / PC 侧 `192.168.1.10`。
- 不能填 `127.0.0.1`。那只在 Registry 自己那台机器上有意义。
- 不能填 `10.0.0.4`。设备在 `192.168.1.0/24` 上，没有反向 NAT 时到不了 `10.0.0.0/24`。

### 后来把 PC 放到设备同一子网

Auto/mDNS 需要 PC 和设备在同一二层。PC 改到 `192.168.1.15`，真机 Node 仍是 `192.168.1.11`。Registry 配置里的 `host_address` 跟着改成 `192.168.1.15`。配置文件是 `D:\zc_softwate\Docker\WorkSpace\nmos-registry\config.json`。

```text
192.168.1.0/24
真机 Node  192.168.1.11  --------  PC  192.168.1.15
DUT                                 本机 nmos-cpp-registry
```

## Docker Registry：静态 Query 可以，Auto 不行

Registry 最初用 Docker Desktop 跑 `rhastie/nmos-cpp` 的 compose，目录在：

```text
D:\zc_softwate\Docker\WorkSpace\nmos-registry
```

`D:\zc_softwate\Docker\WorkSpace\nmos-registry\config.json` 里的 `host_address` 跟着拓扑改过三次：

| 阶段 | `host_address` | 原因 |
| --- | --- | --- |
| 只在本机回环 | `127.0.0.1` | 设备和局域网都访问不到 |
| PC 还在 NAT 后面 | `192.168.1.10` | 设备在 1 网段上能访问的是 Netgear WAN，再加端口映射 |
| PC 与设备同网段 | `192.168.1.15` | 广告和 HTTP 都使用 PC 在公司网上的地址 |

端口一直是 Registration `3210`、Query `3211`、Node `3212`、Query WebSocket `3213`。

Docker 在这次实验里只用来快速确认静态 Query。Auto/mDNS 的最终结果不使用它，也不要留着它占端口。

这一阶段的结论：

- 静态 Query 是通的。W1 的 `--registry` 能打到 Query API。
- Explorer 类工具的 Auto / mDNS 不通。Docker Desktop 里发出的 mDNS 广告到不了主机所在的局域网。
- 局域网本身的 mDNS 是好的：设备的 `_nmos-node` 在 LAN 上能被看到。缺的是 Registry 的广告从 Docker Desktop 出去。

所以没有改用 mDNS reflector。Registry 改到宿主机上跑，广告由 Windows Bonjour 直接发到 LAN。

### 写配置时带上了 BOM

用 PowerShell 改 `D:\zc_softwate\Docker\WorkSpace\nmos-registry\config.json` 时，默认写出的 JSON 带 BOM。Registry 读这份文件失败。把同一份内容重写成 **UTF-8、无 BOM** 之后恢复。

之后再改这个文件，用无 BOM 的写法，例如：

```powershell
$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText("D:\zc_softwate\Docker\WorkSpace\nmos-registry\config.json", $text, $utf8)
```

## 准备阶段

选定的做法：Conan 安装 `nmos-cpp`，DNS-SD 选项 `with_dnssd=mdnsresponder`，由 Windows 的 Bonjour Service 发 mDNS。不是在 Docker 外面再加一层反射。下面是实验机上要先做完的三件事：装 Bonjour、装 Conan、把二进制部署到 `D:\trae_git\nmos-reg-check\direct_deploy\`。

### Bonjour（Windows 11）

Conan 的 `mdnsresponder` 可能带上 `dns-sd` 一类工具，但 **操作系统里的 Bonjour Service 要另外安装**，并且状态是 Running。没有这个服务，局域网上看不到 Registry 的 `_nmos-query`。

安装 Apple 的 **Bonjour Print Services for Windows**（支持文档 [DL999](https://support.apple.com/kb/DL999)，页面标题为 Bonjour Print Services for Windows v2.0.2）。这份安装包会注册名为 `Bonjour Service` 的 Windows 服务。装完后把该服务的启动类型设为自动，并启动它。

安装后确认，二选一：

- 打开「服务」（`services.msc`），**Bonjour Service** 的状态是 **Running**。
- 或在 PowerShell：

```powershell
Get-Service 'Bonjour Service'
```

`Status` 为 `Running` 即可。若提示找不到服务，说明操作系统里还没有装上，Conan 包不能代替它。

### 安装 Conan

实验机使用 Conan 2.x。在已有 Python 的 Windows 上：

```bat
pip install conan
conan --version
```

从源码编译需要 Visual Studio 的 C++ 工作负载：在 Visual Studio Installer 里勾选「使用 C++ 的桌面开发」（Desktop development with C++）。实验机的 profile 是 `compiler=msvc`、`compiler.version=194`（Visual Studio 2022 的 MSVC 19.4x）。

包和编译器：

- 包：`nmos-cpp/cci.20240223`
- 选项：`with_dnssd=mdnsresponder`
- 编译器：MSVC，`compiler.version=194`
- 工作目录：`D:\trae_git\nmos-reg-check\`

### 用 Conan 部署二进制

在 `D:\trae_git\nmos-reg-check\` 下执行。`--deployer=direct_deploy` 把文件写到当前目录。工作目录保持为这一路径，输出才落在 `D:\trae_git\nmos-reg-check\direct_deploy\`。

没有 `compiler.version=194` 的预编译包时，从源码编 `nmos-cpp`：

```bat
cd /d D:\trae_git\nmos-reg-check
conan install --requires=nmos-cpp/cci.20240223 --deployer=direct_deploy --build=nmos-cpp/cci.20240223
```

链接 cpprestsdk 出现 `LNK2019` 时，把这份依赖也从源码重编：

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

产物（本机编译结果，已写进 `.gitignore`，不要提交）：

```text
D:\trae_git\nmos-reg-check\direct_deploy\nmos-cpp\bin\Release\nmos-cpp-registry.exe
D:\trae_git\nmos-reg-check\direct_deploy\nmos-cpp\bin\Release\nmos-cpp-node.exe
```

同一次部署还会在 `D:\trae_git\nmos-reg-check\` 生成 `conanrun*.bat`。这次充当 Registry 的是 `D:\trae_git\nmos-reg-check\direct_deploy\nmos-cpp\bin\Release\nmos-cpp-registry.exe`。`nmos-cpp-node.exe` 是同一次部署带出来的 Node 程序。

### 编译时实际碰到的三件事

1. **没有 194 的预编译包。** Conan 对不上 `compiler.version=194` 的 binary。对这个包加上 `--build=nmos-cpp/cci.20240223`，从源码编。
2. **从国内拉 GitHub 源码超时。** Conan 会重试 `github.com/sony/nmos-cpp` 的源码归档。给当前环境设置 `HTTPS_PROXY`（或 `https_proxy`），或事先把源码放到 Conan 能取用的位置。这里不记录代理地址。
3. **链接错误 `LNK2019: __std_find_first_of_trivial_pos_2`。** 未解析符号来自 cpprestsdk，预编译包的 ABI 和当前 MSVC 不一致。用匹配的 MSVC 从源码重编：`--build=cpprestsdk/*`（其它对不上的依赖同样重编）。

## 问题与处理

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 设备访问不了 `127.0.0.1` 或 `10.0.0.4` | 前者只在 Registry 本机；后者在 NAT 内侧，设备没有反向路径 | RDS 填 1 网段上可达的地址。NAT 阶段是 `192.168.1.10`，并映射 TCP `3210`–`3213` |
| 只有静态 Query，Explorer 类工具的 Auto 一直空 | PC 与设备隔着 NAT，mDNS 过不去 | 把 PC 改到 `192.168.1.15`，与真机 Node `192.168.1.11` 同一子网 |
| Docker 时静态 Query 正常，Auto 仍失败 | Docker Desktop 的 mDNS 广告到不了主机 LAN；设备 `_nmos-node` 在 LAN 上可见，说明 LAN 的 mDNS 本身是通的 | 放弃 Docker 发广告，也不用 mDNS reflector。改用[准备阶段](#准备阶段)的本机 Registry |
| Registry 读不了刚写的 `config.json` | PowerShell 写出了带 BOM 的 JSON | 把 `D:\zc_softwate\Docker\WorkSpace\nmos-registry\config.json` 重写成 UTF-8、无 BOM |
| `Get-Service 'Bonjour Service'` 找不到服务 | 操作系统里还没有 Bonjour，Conan 的 `mdnsresponder` 不会注册这个服务 | 安装 Bonjour Print Services，确认服务为 Running。见[准备阶段](#准备阶段) |
| Conan 没有现成 binary | 预编译包没有 `compiler.version=194` | `--build=nmos-cpp/cci.20240223` |
| 源码下载超时 | 实验机在国内访问 GitHub。Conan 重试 `github.com/sony/nmos-cpp` 的源码归档 | 设置 `HTTPS_PROXY`（或 `https_proxy`），或手动准备源码。不记录代理地址 |
| 链接 `LNK2019: __std_find_first_of_trivial_pos_2` | cpprestsdk ABI 与当前 MSVC 不一致 | 用同一套 MSVC 从源码重编：`--build=cpprestsdk/*` |
| 本机 Registry 起不来，端口被占 | Docker Registry 仍占着 `3210`–`3213` | 先停掉 Docker 里的 Registry，再起本机进程 |

## 和 README 相同的启动命令

日常在 Windows 上启动本机 Registry，用 [`scripts/start-lab-registry.bat`](../../scripts/start-lab-registry.bat)（见[一键启动](../../README.zh-CN.md#一键启动)）。

可重复的顺序以中文 README 的[实验室操作顺序](../../README.zh-CN.md#实验室操作顺序)为准：准备阶段里的 Bonjour 与本机 Registry 就绪、启动、静态 Query 与 Auto Discover 分开、再跑 W1 / W2。下面只留实验机上的命令。

Docker compose 在 `D:\zc_softwate\Docker\WorkSpace\nmos-registry`。它只服务于当时的静态 Query。本机 Registry 启动前先停掉它，把 `3210`–`3213` 让出来。Bonjour Service 保持 Running（`Get-Service 'Bonjour Service'` 的 `Status` 为 `Running`）。配置文件是 `D:\zc_softwate\Docker\WorkSpace\nmos-registry\config.json`，`host_address` 为 `192.168.1.15`，UTF-8、无 BOM。Query API 是 `3211`。`3212` 是 Node 端口。真机 Node 是 `192.168.1.11`。

```bat
D:\trae_git\nmos-reg-check\direct_deploy\nmos-cpp\bin\Release\nmos-cpp-registry.exe D:\zc_softwate\Docker\WorkSpace\nmos-registry\config.json
```

起来之后注册 `_nmos-query`、`_nmos-registration`、`_nmos-register`、`_nmos-node`。

静态 Query 手填 `http://192.168.1.15:3211`。Auto Discover 和 `--mdns` 不手填 URL，PC 与设备保持在 `192.168.1.0/24`。

```bat
nmos-reg-check --registry http://192.168.1.15:3211 --lang zh
nmos-reg-check --mdns --lang zh
```

## 2026-10-13 的结果

- Bonjour Service 处于 Running。
- 本机 Registry 注册了 `_nmos-query`、`_nmos-registration`、`_nmos-register`、`_nmos-node`。
- Explorer 类工具的 Auto Discover 找到 Registry。
- 真机 Node（`192.168.1.11`）已注册，nodes、devices、senders 在 Query 里可见。
- `nmos-reg-check --mdns` 发现了 Query 服务。

## 虚拟网卡上的地址

这台 PC 还有 WSL、VMware 等虚拟网卡。`--mdns` 解析广告时，可能得到 `172.18.32.1` 或 `169.254.x` 这类地址，而不是 `192.168.1.15`。

这不表示 Registry 只绑在虚拟网上。`D:\zc_softwate\Docker\WorkSpace\nmos-registry\config.json` 的 `host_address` 和局域网入口仍是 `192.168.1.15`，Query 端口 `3211`。发现结果看起来指向虚拟网卡时，用这个地址做 W1 对照：

```bat
nmos-reg-check --registry http://192.168.1.15:3211 --lang zh
```
