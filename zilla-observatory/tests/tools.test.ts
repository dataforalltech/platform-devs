import { describe, it, expect } from 'vitest';
import { dispatch, TOOL_SCHEMAS } from '../src/tools/index.js';

describe('Zilla Observatory Tools', () => {
  it('should have tool schemas defined', () => {
    expect(Object.keys(TOOL_SCHEMAS).length).toBeGreaterThan(0);
  });

  it('should list tool names', () => {
    const toolNames = Object.keys(TOOL_SCHEMAS);
    expect(toolNames).toContain('get_ecosystem_metrics');
    expect(toolNames).toContain('get_zilla_status');
    expect(toolNames).toContain('get_dashboard');
    expect(toolNames).toContain('list_dashboards');
  });

  it('should dispatch get_ecosystem_metrics', async () => {
    const result = await dispatch('get_ecosystem_metrics', {});
    const parsed = JSON.parse(result);
    expect(parsed.metrics).toBeDefined();
  });

  it('should dispatch get_zilla_status', async () => {
    const result = await dispatch('get_zilla_status', {
      zilla_name: 'test-zilla',
    });
    const parsed = JSON.parse(result);
    expect(parsed.status).toBe('healthy');
  });

  it('should dispatch get_dashboard', async () => {
    const result = await dispatch('get_dashboard', {
      dashboard_id: 'dash1',
    });
    const parsed = JSON.parse(result);
    expect(parsed.dashboard_id).toBe('dash1');
  });

  it('should dispatch list_dashboards', async () => {
    const result = await dispatch('list_dashboards', {});
    const parsed = JSON.parse(result);
    expect(parsed.dashboards).toBeDefined();
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
