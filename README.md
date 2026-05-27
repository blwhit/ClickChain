# ClickChain

> Investigate ClickFix infections that hide their C2 in smart contracts.
> Lure → contract → panel → payload → operator wallet, in one command.

ClickChain is a single-file Python CLI for hunting **EtherHiding**-backed ClickFix kits (ErrTraffic, ClearFake, Aeternum, and adjacent campaigns). It decodes obfuscated lure JS without executing it, resolves the on-chain C2 the lure points to, and reads the operator's wallet straight off the chain.

---

## Quick start

Requires **Python 3.10+**. Standard library only — nothing to install.

```bash
python clickchain.py --help
```

Common commands:

```bash
# decode + resolve a single compromised site (passive, no JS execution)
python clickchain.py "victim[.]com" --comprehensive --resolve

# fast-sweep a list of domains, resolve on-chain panels
python clickchain.py targets.txt --workers 24 --resolve \
    --out-json sweep.json --out-csv sweep.csv --quiet

# investigate a contract's full C2-rotation history
python clickchain.py --investigate-contract 0xADDR --out-csv rotations.csv

# triage many contracts at once: who actually controls each?  (~10s for 80)
python clickchain.py --triage-contracts addrs.txt --out-csv triage.csv
```

---

## What it does

- **Static decode** — 5 obfuscation schemes (atob+byte-transform, charcode arrays, hex-escape blobs, etc.) through a sandboxed Python AST evaluator. Never runs attacker JS.
- **On-chain resolve** — passive read-only `eth_call` to public RPCs (Polygon / BSC / Ethereum). Reads the current C2 URL the contract is serving.
- **Contract investigate** — bytecode dispatch scan + full `setURL` rotation history via Etherscan API → `eth_getLogs` → batched block-scan fallback.
- **Triage** — fast batched read of `admin()` / `owner()` / `getURL()` across many contracts. Answers "one operator, N instances?" vs "N customers, N instances?"
- **Comprehensive single-IOC** — lure-vs-panel auto-detect, then fetch + decode + resolve + DNS/ports/TLS fingerprint + WordPress + Cloudflare detection + AES clipboard recovery + optional per-OS payload pull.
- **Batch** — 5,000-domain sweeps at ~200 ms/domain with `ThreadPoolExecutor`, streaming to text / JSON / JSONL / CSV simultaneously.

Eight modes total. See `--help` for the full list.

---

## Safety

| Operation | Network behavior |
|---|---|
| Static decode | Pure local. Sandboxed AST eval, no `eval` / `exec`, no JS engine. |
| URL fetch | Passive `urllib` GET, no JS, no form submission. Your IP **is** visible to the target — run from a sandbox / non-attributable network. |
| `--resolve` / `--investigate-contract` / `--triage-contracts` | Read-only `eth_call` to public RPCs. No gas, no writes, operator cannot see the read. |
| `--payload` *(opt-in)* | Contacts the attacker panel. Default = metadata only (hashes + headers + file-magic kept, **bytes discarded**). `--payload-files` to persist bytes with `.bin` suffix (never `.exe`). |

All emitted URLs are defanged.

---

## Optional env vars

- `POLYGONSCAN_API_KEY` — deeper `setURL` history than public free RPCs allow (they prune logs beyond ~80k blocks)
- `BSCSCAN_API_KEY`, `ETHERSCAN_API_KEY` — same, for BSC / Ethereum

Triage and resolve work without any keys.

---

## Modes

The right mode is auto-selected from your input + flags. Run `--help` for the
full epilog.

| # | Mode | Command | Description |
|---|---|---|---|
| 1 | Single static decode | `clickchain.py page.html` | Decode obfuscated loader in a local HTML / ClickGrab JSON / directory / stdin. No network unless `--resolve`. |
| 2 | Single passive fetch | `clickchain.py victim.com` | Passive HTTP GET (browser UA, no JS) then mode 1. Graceful on 404/DNS/TLS errors with hints. |
| 3 | Light batch | `clickchain.py list.txt --workers 24 --resolve` | Concurrent decode + on-chain resolve over a domain list. ~200 ms/domain. Add `--payload` for per-OS payload metadata cached per-panel. |
| 4 | Comprehensive (single IOC) | `clickchain.py victim.com --comprehensive` | Full single-IOC pipeline. Auto-detects LURE vs PANEL role and routes accordingly. |
| 5 | Contract investigate | `clickchain.py --investigate-contract 0xADDR` | Bytecode dispatch scan + live state + full `setURL` rotation timeline. |
| 6 | Comprehensive batch | `clickchain.py list.txt --comprehensive` | Mode 4 over every line in the list. Heavy — curated shortlist only. |
| 7 | Bulk contracts | `clickchain.py --investigate-contracts addrs.txt` *or* `--from-batch sweep.json` | Investigate many contracts. Emits contract-summary CSV + long rotations CSV. |
| 8 | Triage contracts | `clickchain.py --triage-contracts addrs.txt` | Fast state-only batched read on many addresses. `admin()` / `owner()` / `getURL()` per contract in ~100 ms. Answers "one operator or N customers?" |

---

## Flag reference

### Input / output

| Flag | Description |
|---|---|
| *(positional)* `input` | URL, domain (defang ok), file (HTML / ClickGrab JSON / target list), directory, or `-` for stdin. Omitted if `--investigate-contract` is set. |
| `--out DIR` | Directory for recovered `.js` files. Default: `<input>_clickchain`. Pass `''` to skip. |
| `--format {text,json,jsonl}` | stdout format. Default: `text`. |
| `--out-json FILE` | Also write a JSON array of every report to FILE. |
| `--out-jsonl FILE` | Also write JSONL (one record per line) to FILE. |
| `--out-csv FILE` | Also write a flat CSV (one row per `(input, group)`) to FILE. Comprehensive mode adds `.loaders.csv` + `.scripts.csv` sidecars. Bulk contracts adds `.rotations.csv`. |
| `--dump DIR` | DEBUG: dump every raw artifact (lure HTML, role probe, decoded JS, AES PS, decrypted PS, recovered binary, strategy diagnostics) into DIR. |
| `--quiet` | Hide per-block detail (text mode) / hide all stdout text (batch). |
| `--no-color` | Disable ANSI colors. Auto-disabled when piping. |

### Fetch / network

| Flag | Description |
|---|---|
| `--workers N` | Concurrent workers in batch mode. Default: 16. |
| `--fetch-timeout SECONDS` | Per-URL fetch timeout. Default: 20. |
| `--no-tls-verify` | Disable TLS verification (corp MITM / self-signed / stale clocks). |
| `--max-depth N` | Maximum recursive decode depth per block. |

### On-chain resolve

| Flag | Description |
|---|---|
| `--resolve` | For EtherHiding hits, also fire a passive `eth_call` to the RPC pool. |
| `--rpc-url URL` | Override RPC endpoint (e.g. `https://polygon.llamarpc.com`). |
| `--rpc-timeout SECONDS` | Per-RPC timeout. Default: 15. |
| `--chain {polygon,bsc,bsc-testnet,ethereum}` | Chain to use for contract modes. Default: `polygon`. |

### Contract modes (5 / 7 / 8)

| Flag | Description |
|---|---|
| `--investigate-contract ADDR` | Run mode 5 on a single `0x…` address. No positional input needed. |
| `--investigate-contracts FILE` | Run mode 7 on every `0x…` address in FILE. Comments / defang / blanks tolerated. |
| `--triage-contracts FILE` | Run mode 8 on every `0x…` address in FILE. Fast read-only state probe. |
| `--from-batch BATCH_FILE` | Auto-harvest every distinct contract address from a prior `--out-json` sweep. Combines with `--investigate-contracts` or `--triage-contracts`. |
| `--max-history N` | Max number of `setURL` events to reconstruct per contract. Default: 100. |
| `--max-block-scan N` | Max blocks to walk in the RPC-only fallback path. |
| `--skip-etherscan` | Skip the Etherscan API tier; use only `eth_getLogs` + block-scan. |

### Comprehensive / payload (mode 4 / 6)

| Flag | Description |
|---|---|
| `--comprehensive` | Full single-IOC pipeline (mode 4) or batch (mode 6 when input is a list). |
| `--payload` | Pull per-OS payloads from the resolved panel. Default = metadata only (hashes + headers + magic kept, bytes discarded). |
| `--payload-files` | Also persist bytes side-by-side with `.bin` / `.clipboard.ps1` / `.decoded.ps1` per OS. Implies `--payload`. |
| `--payload-token HEX` | Use a pre-captured download token (e.g. from a FLARE-VM walk-through) instead of trying to mint one. |
| `--payload-src LURE_HOST` | Required with `--payload-token` — the lure host the token was issued for. |
| `--payload-mode MODE` | Required with `--payload-token` — typically `cloudflare`. |
| `--detect-rotation N` | Re-resolve the on-chain C2 N times to detect ongoing rotation cadence. |

---

## Out of scope

ClickChain does **not** execute JavaScript, detonate payloads, write to the chain, submit files to VirusTotal, or replace a real malware sandbox. It is a defender / IR / research tool.

---

## Acknowledgments

CTI baseline informed by public research from LevelBlue, Trinity Cyber, Sekoia, Censys, Mandiant, Ctrl-Alt-Int3l, Menlo Security, Unit 42, and the abuse.ch family (URLhaus / MalwareBazaar / ThreatFox). Selectors resolved via `4byte.directory`.
