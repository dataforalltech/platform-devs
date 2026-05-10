import { describe, it, expect } from 'vitest';
import { TOOL_SCHEMAS } from '../src/tools/index.js';
import { getProductZillaPrompt } from '../src/prompts/productzillaPrompt.js';

describe('ProductZilla MCP Server', () => {
  it('should have exactly 18 tools', () => {
    const toolCount = Object.keys(TOOL_SCHEMAS).length;
    expect(toolCount).toBe(18);
  });

  it('should have all required tool names', () => {
    const expectedTools = [
      'analyze_product_problem',
      'define_product_vision',
      'map_user_personas',
      'map_user_journey',
      'generate_feature_spec',
      'generate_user_stories',
      'generate_acceptance_criteria',
      'prioritize_backlog',
      'calculate_rice_score',
      'define_mvp_scope',
      'define_product_metrics',
      'generate_release_plan',
      'generate_discovery_questions',
      'map_product_risks',
      'generate_go_to_market_brief',
      'generate_handoff_to_design',
      'generate_handoff_to_architecture',
      'generate_handoff_to_engineering',
    ];

    const actualTools = Object.keys(TOOL_SCHEMAS);
    expect(actualTools.sort()).toEqual(expectedTools.sort());
  });

  it('should have system prompt defined', () => {
    const prompt = getProductZillaPrompt();
    expect(prompt).toBeDefined();
    expect(prompt.length).toBeGreaterThan(0);
    expect(prompt).toContain('ProductZilla');
  });

  it('each tool should have name, description, and inputSchema', () => {
    Object.values(TOOL_SCHEMAS).forEach((schema) => {
      expect(schema.name).toBeDefined();
      expect(schema.name.length).toBeGreaterThan(0);
      expect(schema.description).toBeDefined();
      expect(schema.description.length).toBeGreaterThan(0);
      expect(schema.inputSchema).toBeDefined();
    });
  });
});
