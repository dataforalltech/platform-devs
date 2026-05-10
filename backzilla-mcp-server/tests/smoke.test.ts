import { describe, it, expect } from 'vitest';
import { getToolSchemas } from '../src/tools/index.js';
import { getBackzillaPrompt } from '../src/prompts/index.js';

describe('BackZilla MCP Server', () => {
  it('should have 14 tools', () => {
    const tools = getToolSchemas();
    expect(tools).toHaveLength(14);
  });

  it('should have tools with correct names', () => {
    const tools = getToolSchemas();
    const toolNames = tools.map(t => t.name);
    expect(toolNames).toContain('analyze_backend_requirement');
    expect(toolNames).toContain('generate_api_contract');
    expect(toolNames).toContain('generate_fastapi_router');
    expect(toolNames).toContain('generate_nestjs_controller');
  });

  it('should have BackZilla system prompt', () => {
    const prompt = getBackzillaPrompt();
    expect(prompt).toContain('BackZilla');
    expect(prompt).toContain('Backend Engineering');
    expect(prompt).toContain('API');
  });
});
