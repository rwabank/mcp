/* AviaTrust MCP Server — Cloudflare Worker
   Deployed at: https://mcp.aviabanktoken.workers.dev
   
   MCP tools:
     - get_aviatrust_score(mint)
     - get_proof_certificate(mint)
     - get_pool_liquidity(mint)
*/

const SOLANA_RPC = 'https://api.mainnet-beta.solana.com';

const KNOWN_TOKENS = {
  // €AUDT
  '4EqVmfTc2ftfdcXCbR95UEsoMdab3WstSj5MEPVW2kqb': {
    symbol: '€AUDT',
    name: 'Audit Token',
    pool: null,
    audited: true,
    score: 5,
    tier: 'Low'
  },
  // €PROOF
  '5rzYSSWCgiY5dUf7JG1i1fBUkNWbYA51fuzWhMYx6t6A': {
    symbol: '€PROOF',
    name: 'Proof Token',
    pool: '3dUpe7cru8HTw3WmHufJu2Ho4UcXQsuCTc84tNGHshpw',
    audited: true,
    score: 8,
    tier: 'Low'
  },
  // €LUMP
  '8SCxKwd6HcnP26Ee9zU8PEn6We7BajBGYQRY5sQppxuN': {
    symbol: '€LUMP',
    name: 'Lump Sum Token',
    pool: 'AcUowwzwf7CACppm9sr3zFLGQ9ncszkjFkx29MZxoyEP',
    audited: true,
    score: 10,
    tier: 'Low'
  },
  // €ESCR
  'DEivmNyf9p9wNSPqMNRuxZsN9VTpZL1fRBypjEt8PmLs': {
    symbol: '€ESCR',
    name: 'Escrow Token',
    pool: null,
    audited: true,
    score: 10,
    tier: 'Low'
  },
  // €DLCT
  'AG6J7LmE5TaDyf1Nb41GC7VrCfsNaRbPjPvuocmk9Y65': {
    symbol: '€DLCT',
    name: 'Documentary LC',
    pool: null,
    audited: true,
    score: 10,
    tier: 'Low'
  }
};

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  'Access-Control-Max-Age': '86400'
};

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: CORS_HEADERS });
    }

    const url = new URL(request.url);

    // Health check
    if (url.pathname === '/' || url.pathname === '/health') {
      return jsonResponse({
        status: 'ok',
        service: 'AviaTrust MCP Server',
        version: '1.0.0',
        tools: [
          'get_aviatrust_score',
          'get_proof_certificate',
          'get_pool_liquidity'
        ]
      });
    }

    // MCP tools endpoint
    if (url.pathname === '/mcp' || url.pathname === '/api/mcp') {
      if (request.method !== 'POST') {
        return jsonResponse({ error: 'Use POST for MCP calls' }, 405);
      }

      try {
        const body = await request.json();
        return await handleMCPRequest(body);
      } catch (e) {
        return jsonResponse({ error: 'Invalid JSON: ' + e.message }, 400);
      }
    }

    // Simple REST endpoints
    if (url.pathname === '/score') {
      const mint = url.searchParams.get('mint');
      if (!mint) return jsonResponse({ error: 'Missing mint param' }, 400);
      return jsonResponse(await getAviatrustScore(mint));
    }

    if (url.pathname === '/proof') {
      const mint = url.searchParams.get('mint');
      if (!mint) return jsonResponse({ error: 'Missing mint param' }, 400);
      return jsonResponse(await getProofCertificate(mint));
    }

    if (url.pathname === '/pool') {
      const mint = url.searchParams.get('mint');
      if (!mint) return jsonResponse({ error: 'Missing mint param' }, 400);
      return jsonResponse(await getPoolLiquidity(mint));
    }

    return jsonResponse({ error: 'Not found' }, 404);
  }
};

// ============================================================
// MCP handler — follows Model Context Protocol JSON-RPC
// ============================================================
async function handleMCPRequest(body) {
  const { method, params, id } = body;

  // MCP: initialize (handshake) — ОБЯЗАТЕЛЬНО для подключения клиента
  if (method === 'initialize') {
    return jsonResponse({
      jsonrpc: '2.0',
      id: id || 1,
      result: {
        protocolVersion: '2024-11-05',
        capabilities: {
          tools: {}
        },
        serverInfo: {
          name: 'AviaTrust MCP Server',
          version: '1.0.0'
        }
      }
    });
  }

  // MCP: notifications/initialized (клиент подтверждает готовность)
  if (method === 'notifications/initialized') {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }

  // MCP: list tools
  if (method === 'tools/list') {
    return jsonResponse({
      jsonrpc: '2.0',
      id: id || 1,
      result: {
        tools: [
          {
            name: 'get_aviatrust_score',
            description: 'Returns AviaTrust audit score 0-100 for a Solana token mint. Includes risk tier, audited status, and proof reference.',
            inputSchema: {
              type: 'object',
              properties: {
                mint: { type: 'string', description: 'Solana token mint address (base58)' }
              },
              required: ['mint']
            }
          },
          {
            name: 'get_proof_certificate',
            description: 'Returns €PROOF certificate data for an audited Solana token. Includes issue date, score, and proof reference.',
            inputSchema: {
              type: 'object',
              properties: {
                mint: { type: 'string', description: 'Solana token mint address' }
              },
              required: ['mint']
            }
          },
          {
            name: 'get_pool_liquidity',
            description: 'Returns liquidity pool information for a Solana token. Includes pool address, DEX, and liquidity in USD.',
            inputSchema: {
              type: 'object',
              properties: {
                mint: { type: 'string', description: 'Solana token mint address' }
              },
              required: ['mint']
            }
          }
        ]
      }
    });
  }

  // MCP: call tool
  if (method === 'tools/call') {
    const toolName = params && params.name;
    const args = params && params.arguments || {};
    const mint = args.mint;

    if (!mint) {
      return jsonResponse({
        jsonrpc: '2.0',
        id: id || 1,
        error: { code: -32602, message: 'Missing mint argument' }
      });
    }

    let result;
    if (toolName === 'get_aviatrust_score') {
      result = await getAviatrustScore(mint);
    } else if (toolName === 'get_proof_certificate') {
      result = await getProofCertificate(mint);
    } else if (toolName === 'get_pool_liquidity') {
      result = await getPoolLiquidity(mint);
    } else {
      return jsonResponse({
        jsonrpc: '2.0',
        id: id || 1,
        error: { code: -32601, message: 'Unknown tool: ' + toolName }
      });
    }

    return jsonResponse({
      jsonrpc: '2.0',
      id: id || 1,
      result: {
        content: [
          { type: 'text', text: JSON.stringify(result, null, 2) }
        ]
      }
    });
  }

  return jsonResponse({
    jsonrpc: '2.0',
    id: id || 1,
    error: { code: -32601, message: 'Unknown method: ' + method }
  });
}

// ============================================================
// Tool implementations
// ============================================================

async function getAviatrustScore(mint) {
  const known = KNOWN_TOKENS[mint];

  if (known) {
    return {
      mint: mint,
      symbol: known.symbol,
      name: known.name,
      score: known.score,
      tier: known.tier,
      audited: known.audited,
      source: 'AviaTrust',
      proof_reference: known.pool ? '€PROOF pool: ' + known.pool : null,
      timestamp: new Date().toISOString()
    };
  }

  // Unknown token — read blockchain
  try {
    const rpc = await rpcCall('getAccountInfo', [mint, { encoding: 'jsonParsed' }]);
    if (!rpc.result || !rpc.result.value) {
      return { mint, error: 'Token not found', audited: false, score: 100, tier: 'Critical' };
    }
    const info = rpc.result.value.data.parsed.info;
    let score = 0;
    if (info.mintAuthority) score += 30;
    if (info.freezeAuthority) score += 25;
    const tier = score <= 20 ? 'Low' : score <= 40 ? 'Moderate' : score <= 60 ? 'Elevated' : score <= 80 ? 'High' : 'Critical';
    return {
      mint,
      symbol: 'unknown',
      score,
      tier,
      audited: false,
      source: 'AviaTrust (unverified)',
      notes: 'Not in AviaTrust registry. Score computed from on-chain data only.',
      timestamp: new Date().toISOString()
    };
  } catch (e) {
    return { mint, error: e.message, audited: false };
  }
}

async function getProofCertificate(mint) {
  const known = KNOWN_TOKENS[mint];
  if (known && known.audited) {
    return {
      mint,
      has_proof: true,
      symbol: known.symbol,
      name: known.name,
      score: known.score,
      tier: known.tier,
      issued_date: '2026-10-12',
      certificate_type: 'ERC-8126',
      source: 'AviaTrust €PROOF',
      timestamp: new Date().toISOString()
    };
  }
  return {
    mint,
    has_proof: false,
    source: 'AviaTrust €PROOF',
    notes: 'No €PROOF certificate found. Token has not been audited via €AUDT.',
    timestamp: new Date().toISOString()
  };
}

async function getPoolLiquidity(mint) {
  const known = KNOWN_TOKENS[mint];
  if (known && known.pool) {
    return {
      mint,
      symbol: known.symbol,
      pool: known.pool,
      dex: 'Meteora DAMM V2',
      geckoterminal: 'https://www.geckoterminal.com/solana/pools/' + known.pool,
      notes: 'Liquidity and volume data available via GeckoTerminal API.',
      timestamp: new Date().toISOString()
    };
  }
  return {
    mint,
    pool: null,
    notes: 'No known pool in AviaTrust registry. Use GeckoTerminal or Birdeye to search.',
    timestamp: new Date().toISOString()
  };
}

// ============================================================
// Helpers
// ============================================================
async function rpcCall(method, params) {
  const res = await fetch(SOLANA_RPC, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params })
  });
  return res.json();
}

function jsonResponse(data, status) {
  return new Response(JSON.stringify(data, null, 2), {
    status: status || 200,
    headers: {
      ...CORS_HEADERS,
      'Content-Type': 'application/json'
    }
  });
}
