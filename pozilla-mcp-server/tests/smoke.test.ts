import { describe, it, expect } from 'vitest';
import { TOOL_SCHEMAS } from '../src/tools/index.js';
import { getPOZillaPrompt } from '../src/prompts/pozillaPrompt.js';

describe('POZilla MCP Smoke Tests', () => {
  it('should have exactly 17 tools', () => {
    const tools = Object.keys(TOOL_SCHEMAS);
    expect(tools).toHaveLength(17);
  });

  it('should have all required tool names', () => {
    const expectedTools = [
      'analyze_business_demand',
      'generate_epic',
      'generate_feature_breakdown',
      'generate_user_stories',
      'generate_acceptance_criteria',
      'generate_gherkin_scenarios',
      'define_definition_of_ready',
      'define_definition_of_done',
      'prioritize_backlog_items',
      'map_dependencies',
      'identify_scope_risks',
      'prepare_sprint_backlog',
      'generate_release_notes',
      'generate_homologation_checklist',
      'generate_jira_tasks',
      'refine_feature',
      'validate_story_readiness',
    ];

    const actualTools = Object.keys(TOOL_SCHEMAS).sort();
    const expectedSorted = expectedTools.sort();

    expect(actualTools).toEqual(expectedSorted);
  });

  it('should have valid system prompt', () => {
    const prompt = getPOZillaPrompt();
    expect(prompt).toBeTruthy();
    expect(prompt.length).toBeGreaterThan(100);
    expect(prompt).toContain('POZilla');
    expect(prompt).toContain('Product Owner');
  });

  it('all tools should have required schema properties', () => {
    Object.entries(TOOL_SCHEMAS).forEach(([toolName, schema]) => {
      expect(schema.name).toBe(toolName);
      expect(schema.description).toBeTruthy();
      expect(schema.description.length).toBeGreaterThan(10);
      expect(schema.inputSchema).toBeTruthy();
    });
  });
});
