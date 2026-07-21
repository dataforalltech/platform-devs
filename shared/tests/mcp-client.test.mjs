import assert from 'node:assert/strict';
import test from 'node:test';
import { Response } from 'node-fetch';

import { MCPClient } from '../dist/mcp-client.js';

test('calls the canonical gateway and returns the observed result', async () => {
  let observed;
  const client = new MCPClient({
    gatewayUrl: 'http://gateway',
    accessToken: 'opaque-token',
    fetchImpl: async (url, init) => {
      observed = { url, authorization: init.headers.Authorization, body: JSON.parse(init.body) };
      return new Response(JSON.stringify({ jsonrpc: '2.0', id: 1, result: { observed: true } }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    },
  });
  assert.deepEqual(await client.callTool('contracts-mcp', 'contracts_list', {}), {
    success: true,
    data: { observed: true },
  });
  assert.equal(observed.url, 'http://gateway/mcp/contracts-mcp/tools/call');
  assert.equal(observed.authorization, 'Bearer opaque-token');
  assert.equal(observed.body.name, 'contracts_list');
});

test('never reports HTTP or JSON-RPC failures as success', async () => {
  const httpFailure = new MCPClient({
    gatewayUrl: 'http://gateway', accessToken: 'token',
    fetchImpl: async () => new Response('', { status: 503 }),
  });
  assert.deepEqual(await httpFailure.callTool('contracts-mcp', 'contracts_list', {}), {
    success: false, error: 'MCP gateway returned HTTP 503',
  });

  const toolFailure = new MCPClient({
    gatewayUrl: 'http://gateway', accessToken: 'token',
    fetchImpl: async () => new Response(
      JSON.stringify({ jsonrpc: '2.0', id: 1, error: { code: -32603, message: 'failed' } }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ),
  });
  assert.deepEqual(await toolFailure.callTool('contracts-mcp', 'contracts_list', {}), {
    success: false, error: 'failed',
  });
});
