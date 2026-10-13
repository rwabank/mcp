#!/bin/bash
# AviaTrust MCP Server — test script
# Replace YOUR-SUBDOMAIN with your real Cloudflare subdomain

BASE="https://aviatrust-mcp.YOUR-SUBDOMAIN.workers.dev"
MINT="5rzYSSWCgiY5dUf7JG1i1fBUkNWbYA51fuzWhMYx6t6A"

echo "=== Health check ==="
curl -s "$BASE/health" | head -20

echo ""
echo "=== Score ==="
curl -s "$BASE/score?mint=$MINT"

echo ""
echo "=== Proof ==="
curl -s "$BASE/proof?mint=$MINT"

echo ""
echo "=== Pool ==="
curl -s "$BASE/pool?mint=$MINT"

echo ""
echo "=== MCP tools/list ==="
curl -s -X POST "$BASE/mcp" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

echo ""
echo "=== MCP tools/call ==="
curl -s -X POST "$BASE/mcp" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_aviatrust_score","arguments":{"mint":"'"$MINT"'"}}}'
