import fetch, { type RequestInit, type Response } from 'node-fetch';

export interface MCPToolCall {
  service: string;
  tool: string;
  args: Record<string, unknown>;
}

export interface MCPResult {
  success: boolean;
  data?: unknown;
  error?: string;
}

export interface MCPClientOptions {
  gatewayUrl?: string;
  accessToken?: string;
  timeoutMs?: number;
  fetchImpl?: (url: string, init?: RequestInit) => Promise<Response>;
}

interface JsonRpcResponse {
  jsonrpc?: string;
  result?: unknown;
  error?: { code?: number; message?: string };
}

/**
 * Canonical gateway client. It never executes tools locally and never converts
 * transport failures into successful MCP results.
 */
export class MCPClient {
  private readonly gatewayUrl: string;
  private readonly accessToken: string;
  private readonly timeoutMs: number;
  private readonly fetchImpl: (url: string, init?: RequestInit) => Promise<Response>;
  private requestId = 0;

  constructor(options: MCPClientOptions = {}) {
    this.gatewayUrl = (options.gatewayUrl ?? process.env.MCP_GATEWAY_URL ?? '').replace(/\/$/, '');
    this.accessToken = options.accessToken ?? process.env.MCP_GATEWAY_TOKEN ?? '';
    this.timeoutMs = options.timeoutMs ?? 30_000;
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  async callQATool(tool: string, args: Record<string, unknown>): Promise<MCPResult> {
    return this.callTool('qa-mcp', tool, args);
  }

  async callTestTool(tool: string, args: Record<string, unknown>): Promise<MCPResult> {
    return this.callTool('test-mcp', tool, args);
  }

  async callDocsTool(tool: string, args: Record<string, unknown>): Promise<MCPResult> {
    return this.callTool('docs-mcp', tool, args);
  }

  async callDeployTool(tool: string, args: Record<string, unknown>): Promise<MCPResult> {
    return this.callTool('deploy-mcp', tool, args);
  }

  async callSessionTool(tool: string, args: Record<string, unknown>): Promise<MCPResult> {
    return this.callTool('session-mcp', tool, args);
  }

  async callInfraTool(tool: string, args: Record<string, unknown>): Promise<MCPResult> {
    return this.callTool('infra-mcp', tool, args);
  }

  async callGovernanceTool(tool: string, args: Record<string, unknown>): Promise<MCPResult> {
    return this.callTool('ai-governance-mcp', tool, args);
  }

  async callTool(service: string, tool: string, args: Record<string, unknown>): Promise<MCPResult> {
    if (!this.gatewayUrl) {
      return { success: false, error: 'MCP_GATEWAY_URL is required' };
    }
    if (!this.accessToken) {
      return { success: false, error: 'MCP_GATEWAY_TOKEN is required' };
    }
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(service)) {
      return { success: false, error: 'Invalid MCP service id' };
    }
    if (!/^[a-z][a-z0-9_-]*$/.test(tool)) {
      return { success: false, error: 'Invalid MCP tool name' };
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await this.fetchImpl(
        `${this.gatewayUrl}/mcp/${encodeURIComponent(service)}/tools/call`,
        {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${this.accessToken}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ id: ++this.requestId, name: tool, arguments: args }),
          signal: controller.signal,
        },
      );
      if (!response.ok) {
        return { success: false, error: `MCP gateway returned HTTP ${response.status}` };
      }
      let payload: JsonRpcResponse;
      try {
        payload = (await response.json()) as JsonRpcResponse;
      } catch {
        return { success: false, error: 'MCP gateway returned invalid JSON' };
      }
      if (payload.error) {
        return { success: false, error: payload.error.message ?? 'MCP tool returned an error' };
      }
      if (!Object.prototype.hasOwnProperty.call(payload, 'result')) {
        return { success: false, error: 'MCP gateway response has no result' };
      }
      return { success: true, data: payload.result };
    } catch (error) {
      const message = error instanceof Error && error.name === 'AbortError'
        ? 'MCP gateway request timed out'
        : 'MCP gateway request failed';
      return { success: false, error: message };
    } finally {
      clearTimeout(timer);
    }
  }

  async validateWithQA(docPath: string): Promise<boolean> {
    return (await this.callQATool('run_linter', { repo_path: docPath })).success;
  }

  async createTestPlan(feature: string): Promise<unknown> {
    return (await this.callTestTool('create_test_plan', {
      title: `Test Plan: ${feature}`,
      scope: `Testing ${feature}`,
    })).data;
  }

  async generateDocumentation(title: string, vars: Record<string, string>): Promise<unknown> {
    return (await this.callDocsTool('generate_doc', { template_name: title, variables: vars })).data;
  }

  async commitBacklog(files: Array<{ path: string; content: string }>): Promise<unknown> {
    return (await this.callDeployTool('commit_files', {
      repo: 'platform-devs', branch: 'main', message: 'docs: backlog and tasks created', files,
    })).data;
  }

  async recordArtifact(sessionId: string, type: string, content: string): Promise<MCPResult> {
    return this.callSessionTool('add_artifact', {
      session_id: sessionId, artifact_type: type, content,
    });
  }
}

let defaultClient: MCPClient | undefined;

export function getMCPClient(): MCPClient {
  defaultClient ??= new MCPClient();
  return defaultClient;
}

/** Backwards-compatible singleton; configuration is validated on first call. */
export const mcpClient = new MCPClient();
