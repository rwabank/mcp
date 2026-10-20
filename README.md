# AviaTrust MCP Server

Model Context Protocol server for AviaTrust audit data.

## What is this?

MCP (Model Context Protocol) is the standard for connecting AI agents (Claude, Cursor, custom bots) to external tools. This server gives AI agents three tools:

- **`get_aviatrust_score(mint)`** — returns audit score 0-100 for any Solana token
- **`get_proof_certificate(mint)`** — returns €PROOF certificate data
- **`get_pool_liquidity(mint)`** — returns liquidity pool information

## Endpoint

