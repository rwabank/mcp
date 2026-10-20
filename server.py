#!/usr/bin/env python3
"""
AviaTrust MCP Server v2
Provides AI agents with on-chain audit scores for tokens and derivatives.
"""

import asyncio
import json
import re
from typing import Any
from datetime import datetime, timezone

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# ==== CONFIG ====
SOLANA_RPC = "https://api.mainnet-beta.solana.com"

# ==== KNOWN TOKENS (registry) ====
KNOWN_TOKENS = {
    # --- Audit Layer ---
    "4EqVmfTc2ftfdcXCbR95UEsoMdab3WstSj5MEPVW2kqb": {
        "symbol": "€AUDT", "name": "Audit Token", "layer": "Audit",
        "role": "Working unit — burned per audit",
        "score": 8, "tier": "Low",
        "site": "https://aviabank.github.io/audt/"
    },
    "5rzYSSWCgiY5dUf7JG1i1fBUkNWbYA51fuzWhMYx6t6A": {
        "symbol": "€PROOF", "name": "Proof Token", "layer": "Audit",
        "role": "Certificate of audit",
        "score": 8, "tier": "Low",
        "site": "https://aviabank.github.io/proof/"
    },
    "BZ7ZJA3FgWshS9fqhhavfBXZ8165aC7h4FUhCrztcQjg": {
        "symbol": "€CERT", "name": "Cert Audit Revenue", "layer": "Audit",
        "role": "Revenue share + staking + insurance",
        "score": 8, "tier": "Low",
        "site": "https://aviabank.github.io/cert/"
    },
    # --- Financial Layer ---
    "DEivmNyf9p9wNSPqMNRuxZsN9VTpZL1fRBypjEt8PmLs": {
        "symbol": "€ESCR", "name": "Escrow Token", "layer": "Financial",
        "role": "Trust layer — collateral escrow",
        "score": 10, "tier": "Low",
        "site": "https://aviabank.github.io/escr/"
    },
    "AG6J7LmE5TaDyf1Nb41GC7VrCfsNaRbPjPvuocmk9Y65": {
        "symbol": "€DLCT", "name": "Documentary LC", "layer": "Financial",
        "role": "Tokenized DLC",
        "score": 10, "tier": "Low",
        "site": "https://aviabank.github.io/dlct/"
    },
    "58UQGvysLh5GZHPX8XEz1xc8tModHYCeSqeu5e49uZoA": {
        "symbol": "€SBLCT", "name": "Standby LC Token", "layer": "Financial",
        "role": "Guarantee layer — ISP98",
        "score": 10, "tier": "Low",
        "site": "https://aviabank.github.io/sblct/"
    },
    "8SCxKwd6HcnP26Ee9zU8PEn6We7BajBGYQRY5sQppxuN": {
        "symbol": "€LUMP", "name": "Lump Sum Token", "layer": "Financial",
        "role": "Fixed commission",
        "score": 10, "tier": "Low",
        "site": "https://aviabank.github.io/lump/"
    },
    # --- Derivatives Layer ---
    "3B6aBYVxQLzVSsrYJtZnmFhbR3tzA6TZoAhfJYmhgAnM": {
        "symbol": "€SWAP", "name": "AviaSwap", "layer": "Derivatives",
        "role": "Interest Rate Swap — hedging",
        "score": 12, "tier": "Low",
        "site": "https://aviabank.github.io/swap/",
        "requires_proof": True,
        "requires_cert_stake": True,
        "pool": "5Kpq5umZRNjsvQUhF3voPMr6PD9w1U2LxiFWhLpNj9ov"
    },
    "Eddd5iW7RWhkNd4JWUjgK9TByeSkdWELgDg4rmimZkBA": {
        "symbol": "€FWD", "name": "AviaForward", "layer": "Derivatives",
        "role": "Aircraft Forward — price lock",
        "score": 12, "tier": "Low",
        "site": "https://aviabank.github.io/fwd/",
        "requires_proof": True,
        "requires_cert_stake": True,
        "pool": "4ivvUsgGixdoWasY8EYLcYENKZ1GuozBuaVXHBz4bDKf"
    },
}

# ==== AUDIT GATE RULES ====
AUDIT_GATES = {
    "L1_aircraft": "Must be audited by AviaTrust (€PROOF required)",
    "L2_financial": "Must pass audit before transfer",
    "L3_audit": "Base layer — issuers of audit",
    "L4_derivatives": "Requires €AUDT burn + valid €PROOF + €CERT stake"
}


def score_to_tier(score: int) -> str:
    if score <= 20: return "Low"
    if score <= 40: return "Moderate"
    if score <= 60: return "Elevated"
    if score <= 80: return "High"
    return "Critical"


# ==== SOLANA RPC ====
async def rpc_call(method: str, params: list) -> dict:
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(SOLANA_RPC, json=body)
        return r.json()


async def get_mint_info(mint: str) -> dict:
    try:
        account_task = rpc_call("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
        supply_task = rpc_call("getTokenSupply", [mint])
        account_data, supply_data = await asyncio.gather(account_task, supply_task)

        if "error" in account_data:
            return {"error": account_data["error"].get("message", "RPC error")}

        value = account_data.get("result", {}).get("value")
        if not value:
            return {"error": "Token not found on Solana mainnet"}

        info = value["data"]["parsed"]["info"]
        supply = "unknown"
        if "result" in supply_data and supply_data["result"].get("value"):
            supply = supply_data["result"]["value"].get("uiAmountString", "unknown")

        return {
            "mint": mint,
            "mintAuthority": info.get("mintAuthority"),
            "freezeAuthority": info.get("freezeAuthority"),
            "decimals": info.get("decimals"),
            "supply": supply,
            "owner": value.get("owner"),
            "exists": True
        }
    except Exception as e:
        return {"error": f"RPC fetch failed: {str(e)}"}


async def scan_site_markers(url: str) -> dict:
    if not url:
        return {"found": False, "reason": "no site url"}
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "AviaTrust-MCP/2.0"})
            html = r.text[:500_000]

        def grab(pattern):
            m = re.search(pattern, html, re.IGNORECASE)
            return m.group(1).strip() if m else None

        return {
            "found": True,
            "audit_score": grab(r"<!--\s*audit-score:\s*([0-9]+)\s*-->"),
            "audit_tier": grab(r"<!--\s*audit-tier:\s*([A-Za-z]+)\s*-->"),
            "proof": grab(r"<!--\s*proof:\s*([A-Za-z0-9x]+)\s*-->"),
            "audit_source": grab(r"<!--\s*audit-source:\s*([A-Za-z0-9 _-]+)\s*-->")
        }
    except Exception as e:
        return {"found": False, "reason": str(e)}


def compute_score(mint_info: dict, known: dict | None) -> tuple[int, str, dict]:
    if known:
        return known["score"], known["tier"], {"source": "AviaTrust registry (verified)"}

    if "error" in mint_info:
        return 100, "Critical", {"source": "unverified", "note": mint_info["error"]}

    score = 0
    reasons = []

    if mint_info.get("mintAuthority"):
        score += 30
        reasons.append("Mint authority is ACTIVE (+30)")

    if mint_info.get("freezeAuthority"):
        score += 25
        reasons.append("Freeze authority is ACTIVE (+25)")

    supply = mint_info.get("supply")
    if supply in (None, "unknown", "0"):
        score += 15
        reasons.append("Supply unknown or zero (+15)")

    decimals = mint_info.get("decimals")
    if decimals is None:
        score += 5
        reasons.append("Decimals missing (+5)")

    score = min(score, 100)
    return score, score_to_tier(score), {"source": "on-chain heuristic", "reasons": reasons}


# ==== MCP SERVER ====
app = Server("aviatrust")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_aviatrust_score",
            description=(
                "Scan any Solana token and return an AviaTrust audit score in ERC-8126 format. "
                "Returns mint/freeze authority status, supply, decimals, a 0-100 risk score, "
                "and a risk tier. Use when the user asks if a Solana token is safe."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "mint": {"type": "string", "description": "Solana token mint address (base58)"}
                },
                "required": ["mint"]
            }
        ),
        Tool(
            name="list_aviatrust_tokens",
            description="List all tokens registered in the AviaTrust ecosystem (Audit + Financial + Derivatives).",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="get_aviatrust_ecosystem",
            description="Return the full AviaTrust ecosystem overview — 4 layers, all tokens, gate rules.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="get_derivative_info",
            description=(
                "Get details of an AviaTrust derivative (€SWAP, €FWD, etc). Returns contract, pool, "
                "audit gate requirements, price target. Use when user asks about derivatives."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Derivative symbol: SWAP, FWD, RIGHT, FLEET"}
                },
                "required": ["symbol"]
            }
        ),
        Tool(
            name="check_derivative_gates",
            description=(
                "Check whether a wallet can trade a specific derivative. Verifies €AUDT burn, "
                "€PROOF validity, €CERT stake. Returns pass/fail per gate."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "wallet": {"type": "string", "description": "Wallet address"},
                    "derivative": {"type": "string", "description": "Derivative symbol (SWAP, FWD, etc)"}
                },
                "required": ["wallet", "derivative"]
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "get_aviatrust_score":
        mint = arguments.get("mint", "").strip()
        if not mint or len(mint) < 32:
            return [TextContent(type="text", text=json.dumps({"error": "Invalid Solana mint address"}, indent=2))]

        known = KNOWN_TOKENS.get(mint)
        mint_info = await get_mint_info(mint)
        site_url = known["site"] if known else None
        site_markers = await scan_site_markers(site_url)
        score, tier, meta = compute_score(mint_info, known)

        result = {
            "@context": "https://erc8126.org/schema/v1",
            "mint": mint,
            "blockchain": mint_info,
            "audit": {
                "audited": known is not None,
                "score": score,
                "tier": tier,
                "source": meta.get("source"),
                "reasons": meta.get("reasons", []),
                "proof": site_markers.get("proof") if isinstance(site_markers, dict) else None
            },
            "site_markers": site_markers,
            "aviatrust_registry": known,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

    if name == "list_aviatrust_tokens":
        out = [{"mint": k, **v} for k, v in KNOWN_TOKENS.items()]
        return [TextContent(type="text", text=json.dumps(out, indent=2, ensure_ascii=False))]

    if name == "get_aviatrust_ecosystem":
        eco = {
            "name": "AviaTrust",
            "chain": "Solana",
            "standard": "Token-2022",
            "layers": {
                "L1_aircraft": {
                    "description": "Real aircraft as base assets",
                    "tokens": ["€B787", "€A350", "€C929", "€A220", "€E195", "€IL96"]
                },
                "L2_financial": {
                    "description": "Trade finance and guarantees",
                    "tokens": ["€ESCR", "€DLCT", "€SBLCT", "€LUMP"]
                },
                "L3_audit": {
                    "description": "Gatekeeper for all financial activity",
                    "tokens": ["€AUDT", "€PROOF", "€CERT"]
                },
                "L4_derivatives": {
                    "description": "Financial instruments on aircraft",
                    "tokens": ["€SWAP", "€FWD", "€RIGHT", "€FLEET"],
                    "live": ["€SWAP", "€FWD"],
                    "coming_soon": ["€RIGHT", "€FLEET"]
                }
            },
            "audit_gates": AUDIT_GATES,
            "website": "https://aviabank.github.io/audt/"
        }
        return [TextContent(type="text", text=json.dumps(eco, indent=2, ensure_ascii=False))]

    if name == "get_derivative_info":
        sym = arguments.get("symbol", "").upper().strip()
        if not sym.startswith("€"):
            sym = "€" + sym

        found = None
        for mint, info in KNOWN_TOKENS.items():
            if info.get("symbol") == sym and info.get("layer") == "Derivatives":
                found = {"mint": mint, **info}
                break

        if not found:
            return [TextContent(type="text", text=json.dumps({
                "error": f"Derivative {sym} not found in registry",
                "available": [i["symbol"] for i in KNOWN_TOKENS.values() if i.get("layer") == "Derivatives"]
            }, indent=2))]

        return [TextContent(type="text", text=json.dumps({
            "derivative": found,
            "gates_required": [
                {"gate": "€AUDT burn", "description": "Must burn €AUDT before mint"},
                {"gate": "€PROOF valid", "description": "Must have valid €PROOF on transfer"},
                {"gate": "€CERT stake", "description": "Must stake €CERT to trade"}
            ],
            "docs": found.get("site")
        }, indent=2, ensure_ascii=False))]

    if name == "check_derivative_gates":
        wallet = arguments.get("wallet", "").strip()
        deriv = arguments.get("derivative", "").strip().upper()
        if not deriv.startswith("€"):
            deriv = "€" + deriv

        if len(wallet) < 32:
            return [TextContent(type="text", text=json.dumps({"error": "Invalid wallet"}, indent=2))]

        return [TextContent(type="text", text=json.dumps({
            "wallet": wallet,
            "derivative": deriv,
            "note": "Full gate check requires on-chain program call — this is a scaffold. "
                    "Implementation returns placeholders until the derivative transfer hook is deployed.",
            "gates": {
                "audt_burned": {"pass": None, "reason": "Not yet queryable on-chain"},
                "proof_valid": {"pass": None, "reason": "Not yet queryable on-chain"},
                "cert_staked": {"pass": None, "reason": "Not yet queryable on-chain"}
            },
            "next_step": "Deploy the Transfer Hook program to enable real gate checks"
        }, indent=2))]

    return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


async def main():
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
