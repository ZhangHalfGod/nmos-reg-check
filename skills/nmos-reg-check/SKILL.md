---
name: nmos-reg-check
description: Run the nmos-reg-check CLI against an NMOS IS-04 registry URL and explain R01, R02, and R05 results. Use when checking registry reachability, heartbeats, or duplicate resource UUIDs.
---

# nmos-reg-check

W1 stub. The check is URL-only. mDNS discovery is not implemented.

## Command

```bash
nmos-reg-check --registry http://host:port [--json] [--lang en|zh] [--insecure]
```

Exit `0` when no check reports an error, `1` when a check reports an error, and `2` when the registry cannot be contacted or the command cannot be run.

## Checks

- **R01** — Query API is reachable and an IS-04 v1.x version was negotiated
- **R02** — node heartbeat or health timestamp is stale, only when that field is present
- **R05** — duplicate UUIDs across nodes, devices, senders, and receivers

The CLI sends HTTP GET requests to the IS-04 Query API only.
