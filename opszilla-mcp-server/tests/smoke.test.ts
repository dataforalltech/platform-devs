import { describe, it, expect } from 'vitest';
import { getToolSchemas } from '../src/tools/index.js';
import { getOpsZillaPrompt } from '../src/prompts/index.js';

describe('OpsZilla MCP Server', () => {
  it('should have 19 tools', () => {
    const tools = getToolSchemas();
    expect(tools).toHaveLength(19);
  });

  it('should have tools with correct names', () => {
    const tools = getToolSchemas();
    const toolNames = tools.map(t => t.name);
    expect(toolNames).toContain('analyze_infrastructure_requirement');
    expect(toolNames).toContain('generate_dockerfile');
    expect(toolNames).toContain('generate_kubernetes_manifest');
    expect(toolNames).toContain('generate_terraform_module');
  });

  it('should have OpsZilla system prompt', () => {
    const prompt = getOpsZillaPrompt();
    expect(prompt).toContain('OpsZilla');
    expect(prompt).toContain('DevOps');
    expect(prompt).toContain('infraestrutura');
  });
});
