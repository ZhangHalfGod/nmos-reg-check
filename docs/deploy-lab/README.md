# 实机部署：NMOS Registry 与 Explorer Auto/mDNS

Windows 11 实验机上的过程记录。要按顺序复现「启动 Registry → 指向设备 / Explorer → 跑检查 → 看结果」，用根 README 的[实验室操作顺序](../../README.md#实验室操作顺序)。本文保留当时怎么走到那套做法，包括没有走通的路径。

对象是一台真实的 ST2110 网关（nmos-node）和一台跑在本机上的 NMOS Registry，用来确认 [nmos-reg-check](../../README.md) 的两条路径都能对着实机工作：

- **W1**：手动指定 Registry URL（`--registry`），只对 Query API 做 HTTP GET。
- **W2**：`--mdns` 在局域网里浏览 `_nmos-query`、`_nmos-register`、`_nmos-registration`，选中一个服务后再走同一套检查。这和 Riedel Explorer 的 **Auto Discover** 是同一类动作：先找到 Registry，再访问它。

下面按实际走过的顺序写。命令、路径、地址保持实验时的写法。`D:\zc_softwate\...` 是这台实验 PC 上的目录，不是仓库里的路径。

## 最后能工作的状态

2026-10-13，PC 与设备在同一二层、同一子网：

| 角色 | 地址 |
| --- | --- |
| 实验 PC | `192.168.1.15` |
| DUT（ST2110 Encap 4K，nmos-node） | `192.168.1.11` |
| Registry 的 `host_address` | `192.168.1.15` |

Registry 是本机 Conan 编出来的 `nmos-cpp`，DNS-SD 走 Windows Bonjour（mdnsresponder），不是 Docker，也不是 mDNS reflector。端口与原先 Docker 那份配置相同：Registration `3210`，Query `3211`，Node `3212`，Query WebSocket `3213`。

当天的结果：

- Explorer **Auto Discover** 能找到这台 Registry。
- ST2110 Encap 4K（`192.168.1.11`）完成注册，Query 里能看到 nodes、devices、senders。
- `nmos-reg-check --mdns` 能发现 Query 服务。它有时会选到虚拟网卡上的地址（见文末），局域网真正要访问的仍是 `192.168.1.15`。

## 拓扑是怎么变的

### 公司网在 NAT 后面

一开始设备和 PC 不在同一个二层。

```text
公司网 192.168.1.0/24
  DUT (ST2110 Encap 4K)   192.168.1.11
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

Auto/mDNS 需要 PC 和设备在同一二层。PC 改到 `192.168.1.15`，DUT 仍是 `192.168.1.11`。Registry 配置里的 `host_address` 跟着改成 `192.168.1.15`。

```text
192.168.1.0/24
DUT  192.168.1.11  --------  PC  192.168.1.15
ST2110 Encap 4K              本机 nmos-cpp-registry
```

## Docker Registry：静态 Query 可以，Auto 不行

Registry 最初用 Docker Desktop 跑 `rhastie/nmos-cpp` 的 compose，目录在：

```text
D:\zc_softwate\Docker\WorkSpace\nmos-registry
```

`config.json` 里的 `host_address` 跟着拓扑改过三次：

| 阶段 | `host_address` | 原因 |
| --- | --- | --- |
| 只在本机回环 | `127.0.0.1` | 设备和局域网都访问不到 |
| PC 还在 NAT 后面 | `192.168.1.10` | 设备在 1 网段上能访问的是 Netgear WAN，再加端口映射 |
| PC 与设备同网段 | `192.168.1.15` | 广告和 HTTP 都使用 PC 在公司网上的地址 |

端口一直是 Registration `3210`、Query `3211`、Node `3212`、Query WebSocket `3213`。

Docker 在这次实验里只用来快速确认静态 Query。Auto/mDNS 的最终结果不使用它，也不要留着它占端口。

这一阶段的结论：

- 静态 Query 是通的。W1 的 `--registry` 能打到 Query API。
- Explorer Auto / mDNS 不通。Docker Desktop 里发出的 mDNS 广告到不了主机所在的局域网。
- 局域网本身的 mDNS 是好的：设备的 `_nmos-node` 在 LAN 上能被看到。缺的是 Registry 的广告从 Docker Desktop 出去。

所以没有改用 mDNS reflector。Registry 改到宿主机上跑，广告由 Windows Bonjour 直接发到 LAN。

### 写配置时带上了 BOM

用 PowerShell 改 `config.json` 时，默认写出的 JSON 带 BOM。Registry 读这份文件失败。把同一份内容重写成 **UTF-8、无 BOM** 之后恢复。

之后再改这个文件，用无 BOM 的写法，例如：

```powershell
$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText("config.json", $text, $utf8)
```

## 改用本机 nmos-cpp

选定的做法：Conan 安装 `nmos-cpp`，DNS-SD 选项 `with_dnssd=mdnsresponder`，由 Windows 的 Bonjour Service 发 mDNS。不是在 Docker 外面再加一层反射。

包和编译器：

- 包：`nmos-cpp/cci.20240223`
- 选项：`with_dnssd=mdnsresponder`
- 编译器：MSVC，`compiler.version=194`

构建过程中碰到的三件事：

1. **没有 194 的预编译包。** Conan 对不上 `compiler.version=194` 的 binary。对这个包加上 `--build=nmos-cpp/cci.20240223`，从源码编。
2. **从国内拉 GitHub 源码超时。** 需要代理，或者事先把源码放到 Conan 能取用的位置。这里不记录代理地址。
3. **链接错误 `__std_find_first_of_trivial_pos_2`。** 来自 cpprestsdk 的 ABI 和当前编译器不一致。用 `--build=cpprestsdk/*` 把这份依赖重编（其它对不上的依赖同样重编）。

部署用 `--deployer=direct_deploy`，输出在仓库目录下的 `direct_deploy/`，同时会生成 `conanrun*.bat`。这两个产物都是本机编译结果，已经写进 `.gitignore`，不要提交。

编出来的可执行文件：

```text
direct_deploy/nmos-cpp/bin/Release/nmos-cpp-registry.exe
direct_deploy/nmos-cpp/bin/Release/nmos-cpp-node.exe
```

这次充当 Registry 的是 `nmos-cpp-registry.exe`。`nmos-cpp-node.exe` 是同一次部署带出来的。

把上面几项合在一起，需要的就是这些参数（profile 里其余字段沿用实验机已有的 MSVC 设置；代理另配）：

```bat
conan install --requires=nmos-cpp/cci.20240223 ^
  -o with_dnssd=mdnsresponder ^
  -s compiler=msvc -s compiler.version=194 ^
  --build=nmos-cpp/cci.20240223 --build=cpprestsdk/* ^
  --deployer=direct_deploy
```

## 问题与处理

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 设备访问不了 `127.0.0.1` 或 `10.0.0.4` | 前者只在 Registry 本机；后者在 NAT 内侧，设备没有反向路径 | RDS 填 1 网段上可达的地址。NAT 阶段是 `192.168.1.10`，并映射 TCP `3210`–`3213` |
| 只有静态 Query，Explorer Auto 一直空 | PC 与设备隔着 NAT，mDNS 过不去 | 把 PC 改到 `192.168.1.15`，与 DUT `192.168.1.11` 同一子网 |
| Docker 时静态 Query 正常，Auto 仍失败 | Docker Desktop 的 mDNS 广告到不了主机 LAN；设备 `_nmos-node` 在 LAN 上可见，说明 LAN 的 mDNS 本身是通的 | 放弃 Docker 发广告，也不用 mDNS reflector |
| Registry 读不了刚写的 `config.json` | PowerShell 写出了带 BOM 的 JSON | 重写成 UTF-8、无 BOM |
| Conan 没有现成 binary | 预编译包没有 `compiler.version=194` | `--build=nmos-cpp/cci.20240223` |
| 源码下载超时 | 实验机在国内访问 GitHub | 代理，或手动准备源码 |
| 链接 `__std_find_first_of_trivial_pos_2` | cpprestsdk ABI 与当前 MSVC 不一致 | `--build=cpprestsdk/*`（或重编其它不匹配的依赖） |
| 本机 Registry 起不来，端口被占 | Docker Registry 仍占着 `3210`–`3213` | 先停掉 Docker 里的 Registry，再起本机进程 |

## 和 README 相同的启动命令

可重复的顺序以根 README 为准：Bonjour 与本机 Registry 就绪、启动、静态 Query 与 Auto Discover 分开、再跑 W1 / W2。下面只留实验机上的命令。

Docker compose 在 `D:\zc_softwate\Docker\WorkSpace\nmos-registry`。它只服务于当时的静态 Query。本机 Registry 启动前先停掉它，把 `3210`–`3213` 让出来。Bonjour Service 保持 Running。`config.json` 与 Docker 那份相同，`host_address` 为 `192.168.1.15`，UTF-8、无 BOM。Query API 是 `3211`。`3212` 是 Node 端口。设备是 `192.168.1.11`。

```bat
direct_deploy\nmos-cpp\bin\Release\nmos-cpp-registry.exe D:\zc_softwate\Docker\WorkSpace\nmos-registry\config.json
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
- Explorer Auto Discover 找到 Registry。
- ST2110 Encap 4K（`192.168.1.11`）已注册，nodes、devices、senders 在 Query 里可见。
- `nmos-reg-check --mdns` 发现了 Query 服务。

## 虚拟网卡上的地址

这台 PC 还有 WSL、VMware 等虚拟网卡。`--mdns` 解析广告时，可能得到 `172.18.32.1` 或 `169.254.x` 这类地址，而不是 `192.168.1.15`。

这不表示 Registry 只绑在虚拟网上。`config.json` 的 `host_address` 和局域网入口仍是 `192.168.1.15`，Query 端口 `3211`。发现结果看起来指向虚拟网卡时，用这个地址做 W1 对照：

```bat
nmos-reg-check --registry http://192.168.1.15:3211 --lang zh
```
