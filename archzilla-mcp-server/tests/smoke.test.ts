import { describe, it, expect } from 'vitest';
import { TOOL_SCHEMAS } from '../src/tools/index.js';
import { getArchZillaPrompt } from '../src/prompts/archzillaPrompt.js';

describe('ArchZilla MCP Server', () => {
  it('should have exactly 18 tools', () => {
    const toolCount = Object.keys(TOOL_SCHEMAS).length;
    expect(toolCount).toBe(18);
  });

  it('should have all required tool names', () => {
    const expectedTools = [
      'analyze_architecture_requirement',
      'generate_solution_blueprint',
      'define_system_modules',
      'define_bounded_contexts',
      'generate_c4_diagram',
      'generate_sequence_diagram',
      'generate_api_guidelines',
      'generate_event_contracts',
      'generate_data_architecture',
      'define_non_functional_requirements',
      'generate_security_architecture',
      'generate_observability_architecture',
      'generate_adr',
      'review_architecture',
      'map_architecture_risks',
      'generate_technical_roadmap',
      'define_integration_strategy',
      'evaluate_architecture_tradeoffs',
    ];

    const actualTools = Object.keys(TOOL_SCHEMAS);
    expect(actualTools.sort()).toEqual(expectedTools.sort());
  });

  it('should have system prompt defined', () => {
    const prompt = getArchZillaPrompt();
    expect(prompt).toBeDefined();
    expect(prompt.length).toBeGreaterThan(0);
    expect(prompt).toContain('ArchZilla');
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
