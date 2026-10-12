---
name: nmos-reg-check
description: Run the nmos-reg-check CLI against an NMOS IS-04 registry, either by URL or by mDNS discovery, and explain R01, R02, and R05 results. Use when checking registry reachability, heartbeats, duplicate resource UUIDs, or finding a registry on the LAN.
---

# nmos-reg-check

Check an IS-04 registry through the read-only Query API. A static URL and mDNS discovery are two ways to obtain that registry.

## Command

```bash
nmos-reg-check --registry http://host:port [--json] [--lang en|zh] [--insecure]
nmos-reg-check --mdns [--mdns-timeout SECONDS] [--json] [--lang en|zh] [--insecure]
```

- `--registry` is the static URL (origin, `/x-nmos/query/`, or a pinned `/x-nmos/query/v1.x/`).
- `--mdns` browses `_nmos-query._tcp`, `_nmos-register._tcp`, and legacy `_nmos-registration._tcp`, builds an `http(s)://address:port` origin from the advertisement, then runs the same checks.
- If both flags are set, the explicit URL is used and mDNS is not browsed. A warning says so.
- No usable advertisement, or an mDNS failure, exits 2.

Exit `0` when no check reports an error, `1` when a check reports an error, and `2` when the registry cannot be contacted or the command cannot be run.

Multicast does not cross a typical Docker bridge. Use host networking, or pass `--registry`, when the registry is outside the container.

## Checks

- **R01** — Query API is reachable and an IS-04 v1.x version was negotiated
- **R02** — node heartbeat or health timestamp is stale, only when that field is present
- **R05** — duplicate UUIDs across nodes, devices, senders, and receivers

The CLI sends HTTP GET requests to the IS-04 Query API only.
