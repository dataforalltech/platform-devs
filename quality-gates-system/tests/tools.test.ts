import { describe, it, expect } from 'vitest';
import { dispatch, TOOL_SCHEMAS } from '../src/tools/index.js';

describe('Quality Gates System Tools', () => {
  it('should have tool schemas defined', () => {
    expect(Object.keys(TOOL_SCHEMAS).length).toBeGreaterThan(0);
  });

  it('should list tool names', () => {
    const toolNames = Object.keys(TOOL_SCHEMAS);
    expect(toolNames).toContain('register_gate');
    expect(toolNames).toContain('evaluate_gate');
    expect(toolNames).toContain('get_gate_status');
    expect(toolNames).toContain('list_gates');
  });

  it('should dispatch register_gate', async () => {
    const result = await dispatch('register_gate', {
      gate_id: 'gate1',
      gate_type: 'unit_tests',
    });
    const parsed = JSON.parse(result);
    expect(parsed.status).toBe('registered');
  });

  it('should dispatch evaluate_gate', async () => {
    const result = await dispatch('evaluate_gate', {
      gate_id: 'gate1',
    });
    const parsed = JSON.parse(result);
    expect(parsed.passed).toBe(true);
  });

  it('should dispatch get_gate_status', async () => {
    const result = await dispatch('get_gate_status', {
      gate_id: 'gate1',
    });
    const parsed = JSON.parse(result);
    expect(parsed.status).toBe('passing');
  });

  it('should dispatch list_gates', async () => {
    const result = await dispatch('list_gates', {});
    const parsed = JSON.parse(result);
    expect(parsed.gates).toBeDefined();
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
