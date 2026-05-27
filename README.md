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


