import { describe, it, expect } from 'vitest';
import { getToolSchemas } from '../src/tools/index.js';
import { getDevOpsPrompt } from '../src/prompts/index.js';

describe('DevOps MCP Server', () => {
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

  it('should have DevOps system prompt', () => {
    const prompt = getDevOpsPrompt();
    expect(prompt).toContain('DevOps');
    expect(prompt).toContain('DevOps');
    expect(prompt).toContain('infraestrutura');
  });
});
