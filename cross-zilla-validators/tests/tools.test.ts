import { describe, it, expect } from 'vitest';
import { dispatch, TOOL_SCHEMAS } from '../src/tools/index.js';

describe('Cross-Zilla Validators Tools', () => {
  it('should have tool schemas defined', () => {
    expect(Object.keys(TOOL_SCHEMAS).length).toBeGreaterThan(0);
  });

  it('should list tool names', () => {
    const toolNames = Object.keys(TOOL_SCHEMAS);
    expect(toolNames).toContain('validate_handoff');
    expect(toolNames).toContain('check_governance');
    expect(toolNames).toContain('validate_output');
    expect(toolNames).toContain('get_validation_rules');
  });

  it('should dispatch validate_handoff', async () => {
    const result = await dispatch('validate_handoff', {
      from_zilla: 'zilla1',
      to_zilla: 'zilla2',
      handoff_data: {},
    });
    const parsed = JSON.parse(result);
    expect(parsed.valid).toBe(true);
  });

  it('should dispatch check_governance', async () => {
    const result = await dispatch('check_governance', {
      zilla_name: 'zilla1',
    });
    const parsed = JSON.parse(result);
    expect(parsed.compliant).toBe(true);
  });

  it('should dispatch validate_output', async () => {
    const result = await dispatch('validate_output', {
      zilla_name: 'zilla1',
      output: {},
    });
    const parsed = JSON.parse(result);
    expect(parsed.valid).toBe(true);
  });

  it('should dispatch get_validation_rules', async () => {
    const result = await dispatch('get_validation_rules', {
      from_zilla: 'zilla1',
      to_zilla: 'zilla2',
    });
    const parsed = JSON.parse(result);
    expect(parsed.rules).toBeDefined();
  });

  it('should throw on unknown tool', async () => {
    try {
      await dispatch('unknown_tool', {});
      expect.fail('Should have thrown');
    } catch (e) {
      expect((e as Error).message).toContain('Unknown tool');
    }
  });
});
