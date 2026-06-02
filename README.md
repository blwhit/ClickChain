# ClickChain  (v6.2)

> Investigate ClickFix infections that hide their C2 in smart contracts.
> Lure → contract → panel → payload → operator config → operator wallet → full inventory → funding source, in one command.

ClickChain is a **standalone, single-file** Python CLI for hunting **EtherHiding**-backed ClickFix kits (ErrTraffic, ClearFake, Aeternum, jobloom, and adjacent campaigns). It decodes obfuscated lure JS without executing it, resolves the on-chain C2 the lure points to, reads the operator's wallet straight off the chain, walks down every contract that wallet ever deployed, and walks back the wallet's funding source to identify exchange terminus vs operator bootstrapping.

The defensible/immutable threat data — **known actors, wallets, contracts, operators (`KNOWN_ACTORS`) and known panel hosts (`KNOWN_PANELS`)** — is **baked into the script**, so attribution works anywhere with no external files. Ephemeral data (the full IOC sweep list, the rolling lure memory) lives in optional external files.

## What's new in 6.2 (Session 39, 2026-05-29)

- **Standalone known-panel attribution.** The chain-verified panel host set (179, incl. historical/rotated) is now baked in as `KNOWN_PANELS`, alongside `KNOWN_ACTORS`. The `role=panel` rule + `known_panel_inventory` signal work out of the box on any host — no `PANELS_COMPREHENSIVE.json` to sync (this was the silent cause of the FlareVM 0-fire). `_load_panels_kb` = baked-in floor + **optional** external merge (`--panels-kb PATH`, or a `PANELS_COMPREHENSIVE.json`/`panels.txt` in the run dir, adds newer panels / richer metadata on top). Startup prints the KB in effect. Dropped `example*.com` placeholder hosts.
- **Lure memory clarified as optional.** The panel→lure map is in-memory and rolling (learns as it scans, no file needed); `--panel-lure-memory FILE` only adds cross-run persistence.

## What's new in 6.1 (Session 39, 2026-05-29)

- **Panel-vs-lure classification fix.** `_cf_role` now tags any host in the chain-verified panel KB (`analysis/PANELS_COMPREHENSIVE.json`) as `role=panel` even when its `/api/init` 404s today — a known panel that's down is still a panel. (Audited against the 12,948-record S37 sweep: 58 of 111 known panels were mis-roled `unknown_role`; replaying the fix recovers all 58.) `_load_panels_kb` now warns loudly when the KB file isn't found instead of degrading silently.
- **FULL operator config in every output.** `probe_panel_envelopes` emits `config_full` — the complete merged decrypted `/api/cfg` + `/api/settings` config — printed in full to stdout (every key, untruncated) and serialized to a new `bw_v2_config_json` CSV column (was: 11-key allowlist in stdout, 5 fields in CSV; full config buried in nested JSON).
- **Operator admin/install-panel probe.** New `probe_admin_panel()` passively GETs `/admin/login.php`, `/install.php`, etc. on every identified panel (panel-mode + lure→resolved-panel), severity-tiered (`exposed_unauth` / `install_wizard` / `exists_protected`), per-host cached, rendered + 3 CSV columns (`admin_panel_open` / `admin_surface_found` / `admin_findings`). Flags: `--no-admin-probe` (disable), `--probe-admin` (force on any IOC). Basis: Censys "Inside a GlitchFix Attack Panel".
- **Expanded, parallel port scan.** `fingerprint_server` probes 16 ports (was 3) — adds operator-panel `:3000/:1337` + service ports `22/21/3306/6379/9200/5432/3389/27017/8080/8000/8888` — via a TCP-connect thread pool (≤3 s/port). Bare dotted IPs kept.
- **Comprehensive panel inventory.** `panels.txt` (project root, **179** panel hosts) + regenerated `analysis/PANELS_COMPREHENSIVE.{json,csv,md}` (111→179); `analysis/sweep_2026-05-28/sweep_merged.txt` rebuilt to **13,331** hosts (panels ∪ lures ∪ resolved C2 ∪ curated, deduped). Rebuild + re-bake `KNOWN_PANELS` with `scripts/_s39_consolidate_panels.py`.

## What's new in 6.0 (Session 35)

- **Intelligent 3-artifact payload recovery.** Unified clipboard decoder (BW v2 string-XOR-hex / byte-array-XOR / AES-CBC / `-EncodedCommand` / plaintext) recovers raw clipboard PS + decoded PS + binary. Handles the newest ErrTraffic generation that ships the victim clipboard PowerShell **inside the `/api/init` token** (rolling-XOR-hex), plus the served-script chase (a `a=dl` text payload is decoded and the real binary fetched one level deep). Known panels are routed to the panel-direct flow regardless of today's init result.

## What's new in 5.4 (Session 28, 2026-05-28)

- **`--enumerate-deployer WALLET`** — list every contract a wallet has ever deployed on the target chain. Etherscan v2 txlist paginated, filtered for contract-creation (`to == "" AND contractAddress != ""`). Returns chronological inventory with `creation_tx` / `block_time` / `gas_used`. Pair with `--to-triage-file FILE` to chain directly into `--triage-contracts`. Validated by walking LenAI's primary wallet → 184 contracts (vs KrakenLabs's public 32).
- **`--trace-funding WALLET --funding-hops N`** — walks back N hops of incoming MATIC. At each hop fetches `txlist + txlistinternal`, finds first inbound `value > 0`, tags source against `KNOWN_EXCHANGES` (24+ Binance/OKX/KuCoin/Bybit/MEXC/Gate.io/Coinbase/HTX/Bitget + Polygon bridges + ChangeNOW/SimpleSwap/FixedFloat) + `KNOWN_ACTORS`. Terminus types: `known_exchange` / `known_actor` / `depth_exhausted` / `no_funding` / `no_api_key` / `unsupported_chain`. Validated: "Customer A" and "Customer E" funding-traces both terminate at LenAI primary (= they're LenAI alts, not customers).
- **`TRIAGE_SELECTORS` extended to 6 entries:** added `getDomain()` (`0xb68d1809`, BW v2 / Aeternum read selector) + `getServer()` (`0x3bc5de30`, jobloom-cluster read selector). Closes the S27 gap where BW v2 contracts returned `current_url=None`. CSV writers + columns updated correspondingly.
- **`KNOWN_EXCHANGES`** dict added (~25 entries, sourced from Polygonscan public labels). New helper `lookup_exchange()` parallels `lookup_actor()`.
- **`KNOWN_ACTORS`** updated: `0xb0425bf2…` retagged "LenAI alt-wallet A" (was "Customer A"); `0xf1940ddb…` retagged "LenAI alt-wallet E". Both carry the funding-tx citation that proves the relabel.

## What's new in 5.3 (Session 27, 2026-05-28)

- **Lure-mode envelope_recovery wiring.** Every comprehensive lure run now decrypts the resolved panel's `/api/cfg` + `/api/settings` envelopes using the per-panel `API_Q2_KEY_HEX` that `extract_loader_intel` just harvested. Cached by `panel_host` (one probe per panel even when 50 lures resolve to the same panel).
- **KNOWN_ACTORS expanded.** 21 new BW v2 panel-router contracts + 5 new operator wallets, all admin()-verified via S27 triage. The kit ecosystem now has 7 distinct operators (was 2 in S25). Operator `0xb0425bf2…` scaled from 4 → 12 panels; LenAI (`0xcaf2c54e…`) scaled from 2 → 8.
- **Thread-safe `--log-file` Tee.** Was silently garbling output at `--workers 32`. Lock-serialized; `writelines` properly batches multi-line writes.
- **ErrTraffic v3 flagship rotation captured live:** `0x08207b…` is currently pointing at `megamegalodon.click` (previous: pusanik.shop → lenders.digital → krolikrojer.lat → comicstar.lat).
- **First .com BW v2 panel observed** (`macerapindasi.com`) — defenders should watch for kit-pattern detection on non-burner-TLD domains too.

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

- **Static decode** — 6 obfuscation schemes (BW v2 IIFE-wrapped XOR, atob+byte-transform, charcode arrays, hex-escape blobs, etc.) through a sandboxed Python AST evaluator. Never runs attacker JS.
- **On-chain resolve** — passive read-only `eth_call` to public RPCs (Polygon / BSC / Ethereum). Reads the current C2 URL the contract is serving. Handles both `getURL()` (v3 original) and `getDomain()` (Aeternum / BW v2 generation) selectors.
- **Envelope decrypt** — AES-256-GCM (`gcm1`) and RC4 (`q2`) — full port of the kit's own `decryptApiEnvelope()` function. Decrypts `/api/cfg` and `/api/settings` envelopes to recover the operator's live config. The **complete** decrypted config (`config_full`) is surfaced in every output — stdout (every key, untruncated), the `bw_v2_config_json` CSV column, and JSON — not just a hand-picked subset. All passive, no JS execution. (Coverage is key-bound: a panel's config only decrypts when its per-host `API_Q2_KEY_HEX` has been harvested from a loader.)
- **Contract investigate** — bytecode dispatch scan + full `setURL` rotation history via Etherscan API → `eth_getLogs` → batched block-scan fallback.
- **Triage** — fast batched read of `admin()` / `owner()` / `getURL()` across many contracts. Answers "one operator, N instances?" vs "N customers, N instances?"
- **Comprehensive single-IOC** — lure-vs-panel auto-detect (incl. chain-verified panel-KB lookup), then fetch + decode + resolve + DNS/16-port/TLS fingerprint + WordPress + Cloudflare detection + envelope decrypt (full config) + AES clipboard recovery + admin/install-panel probe + optional per-OS payload pull.
- **Payload chain** — 5 download strategies including the May-2026 BW v2 path (`init` → `{token:<hex>}` → `dl?uj=<hex>&rlm=…`).
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

## Kit families supported

`KNOWN_ACTORS` cross-references contracts + operator wallets so attribution surfaces automatically on triage / resolve / investigate. Currently covered:

| Family | Chain | Sample contract | Notes |
|---|---|---|---|
| **ErrTraffic v3** (LenAI) | Polygon | `0x08207B…7eD308` | `getURL()` selector. Original v3 panel kit (lenders.digital / comicstar.lat / krolikrojer.lat / pusanik.shop rotations). |
| **ErrTraffic v3 BW v2 generation** (LenAI) | Polygon | `0x07b4aB…327F8` | `getDomain()` selector + Aeternum-pattern router + AES-256-GCM `gcm1` envelope. May-2026 deployment (slndcdnclaud.beer). |
| **Aeternum Loader** (LenAI) | Polygon | `0x4d70C3…64B0` | Native C++ Windows botnet loader. `getDomain()` selector. |
| **ClearFake** | BSC testnet | 4 contracts | 3-tier validation / Windows-payload / macOS-payload / UUID-dedup. |
| **UNC5142 / CLEARSHORT** *(hooks ready)* | BSC | — | Will populate as Mandiant publishes contract addresses. |
| **UNC5342 / DPRK** *(hooks ready)* | Ethereum + BSC | — | Same. |

Selectors auto-resolved against [4byte.directory](https://www.4byte.directory): `getURL()` `0x38bcdc1c`, `setURL(string)` `0x77343408`, `url()` `0x5600f04f`, `admin()` `0xf851a440`, `owner()` `0x8da5cb5b`, `getDomain()` `0xb68d1809`, `kill()` `0x41c0e1b5`, `transferOwner(address)` `0x4fb2e45d`.

---

## ErrTraffic v3 BW v2 (May 2026 generation)

The kit author bumped the JS codebase to "BW v2" (internal marker
`__BW_SCRIPT_INITIALIZED_V2__`). On-the-wire architecture per LevelBlue
SpiderLabs 2026, full algorithm reverse-engineered from `/api/css.js`:

- **10-theme `MODE_FILE_MAP`** — browser / font / recaptcha / bsod / silent / cloudflare / cf_update / mac_recaptcha / mac_cloudflare / **recaptcha_win_r** (the new Win+R variant per Atos)
- **`gcm1` envelope** — AES-256-GCM, scope-keyed: `key = sha256(API_Q2_KEY || utf8(scope + "|gcm1"))`. Scope ∈ {`cfg`, `init`, `dl`, `evt`}. IV (12 B) prepended to ciphertext, GCM tag (128 bit) appended.
- **`q2` legacy envelope** — RC4 with `key = API_Q2_KEY || nonce(8 B)`.
- **URL param rename** — `token` → `uj`, `src` → `rlm`, encrypted-payload field is `q`.
- **Clipboard layer dropped** — BW v2 ships a plaintext `Invoke-WebRequest` launcher (no more AES-CBC clipboard wrap).

ClickChain ships the documented `API_Q2_KEY_HEX` for the May-2026 build (extractable from any panel's `/api/css.js`), so envelope decryption works out of the box.

---

## Out of scope

ClickChain does **not** execute JavaScript, detonate payloads, write to the chain, submit files to VirusTotal, or replace a real malware sandbox. It is a defender / IR / research tool.

---

## Acknowledgments

CTI baseline informed by public research from LevelBlue, Trinity Cyber, Sekoia, Censys, Mandiant, Ctrl-Alt-Int3l, Menlo Security, Unit 42, and the abuse.ch family (URLhaus / MalwareBazaar / ThreatFox). Selectors resolved via `4byte.directory`.
