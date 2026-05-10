import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { FrontzillaPixelferaStore } from '../src/db/store';
import { dispatchTool, getToolSchemas } from '../src/tools/index';
import { getSettings } from '../src/config/settings';

describe('Tools', () => {
  let store: FrontzillaPixelferaStore;
  const settings = getSettings();

  beforeEach(() => {
    store = new FrontzillaPixelferaStore(':memory:');
  });

  afterEach(() => {
    store.close();
  });

  describe('Tool Schemas', () => {
    it('should have 26 tool schemas', () => {
      const schemas = getToolSchemas();
      expect(schemas.length).toBe(26);
    });

    it('should have all required tools', () => {
      const schemas = getToolSchemas();
      const names = schemas.map((s) => s.name);

      expect(names).toContain('analyze_requirement');
      expect(names).toContain('generate_react_component');
      expect(names).toContain('generate_wireframe');
      expect(names).toContain('run_ui_feature_workflow');
    });
  });

  describe('Requirement Tools', () => {
    it('should analyze requirement', async () => {
      const result = await dispatchTool(
        'analyze_requirement',
        {
          requirement: 'Create a dashboard with user statistics and charts',
          context: 'For internal admins',
        },
        store,
        settings
      );

      expect(result).toBeDefined();
      expect(result.tool).toBe('analyze_requirement');
      expect((result as any).payload).toBeDefined();
    });
  });

  describe('Design Tools', () => {
    it('should generate wireframe', async () => {
      const result = await dispatchTool(
        'generate_wireframe',
        { screen_name: 'Dashboard' },
        store,
        settings
      );

      expect(result).toBeDefined();
      expect((result as any).payload).toBeDefined();
      expect((result as any).payload.ascii_diagram).toBeDefined();
    });

    it('should create design tokens', async () => {
      const result = await dispatchTool(
        'create_design_tokens',
        { brand: 'MyBrand' },
        store,
        settings
      );

      expect(result).toBeDefined();
      expect((result as any).payload.tokens).toBeDefined();
    });
  });

  describe('Frontend Tools', () => {
    it('should generate React component', async () => {
      const result = await dispatchTool(
        'generate_react_component',
        { name: 'Button' },
        store,
        settings
      );

      expect(result).toBeDefined();
      expect((result as any).payload.filename).toContain('Button');
      expect((result as any).payload.typescript_code).toContain('React');
    });

    it('should generate Next.js page', async () => {
      const result = await dispatchTool(
        'generate_nextjs_page',
        { route: '/dashboard' },
        store,
        settings
      );

      expect(result).toBeDefined();
      expect((result as any).payload.typescript_code).toContain('Suspense');
    });

    it('should generate TypeScript types', async () => {
      const result = await dispatchTool(
        'generate_typescript_types',
        { entity_name: 'User' },
        store,
        settings
      );

      expect(result).toBeDefined();
      expect((result as any).payload.type_name).toBe('User');
    });
  });

  describe('Design System Tools', () => {
    it('should generate component spec', async () => {
      // First create a feature to associate with component
      const feature = store.createFeature('Test Feature', 'Test req', {});

      const result = await dispatchTool(
        'generate_component_spec',
        { name: 'Button', category: 'atom', feature_id: feature.id },
        store,
        settings
      );

      expect(result).toBeDefined();
      expect((result as any).payload.name).toBe('Button');
    });
  });

  describe('Workflow Tools', () => {
    it('should run UI feature workflow', async () => {
      const result = await dispatchTool(
        'run_ui_feature_workflow',
        {
          requirement: 'Create a login form with email and password',
          target: 'complete',
          stack: 'nextjs',
        },
        store,
        settings
      );

      expect(result).toBeDefined();
      expect((result as any).payload.feature_id).toBeDefined();
      expect((result as any).payload.workflow_id).toBeDefined();
    });
  });

  describe('Error Handling', () => {
    it('should handle unknown tool', async () => {
      const result = await dispatchTool(
        'unknown_tool',
        {},
        store,
        settings
      );

      expect((result as any).error).toBe('unknown_tool');
    });
  });
});
