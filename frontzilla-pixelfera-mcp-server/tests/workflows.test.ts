import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { FrontzillaPixelferaStore } from '../src/db/store';
import { dispatchTool } from '../src/tools/index';
import { getSettings } from '../src/config/settings';

describe('Workflows', () => {
  let store: FrontzillaPixelferaStore;
  const settings = getSettings();

  beforeEach(() => {
    store = new FrontzillaPixelferaStore(':memory:');
  });

  afterEach(() => {
    store.close();
  });

  describe('Feature Creation Workflow', () => {
    it('should analyze requirement and create feature', async () => {
      const result = await dispatchTool(
        'analyze_requirement',
        {
          requirement:
            'Create a user dashboard with profile settings, activity log, and notifications',
          context: 'For authenticated users',
        },
        store,
        settings
      );

      expect(result).toBeDefined();
      const payload = (result as any).payload;
      expect(payload.feature_id).toBeDefined();
      expect(payload.analysis).toBeDefined();
      expect(payload.analysis.screens).toBeDefined();
    });

    it('should split tasks between agents', async () => {
      // First create a feature
      const analyzeResult = await dispatchTool(
        'analyze_requirement',
        {
          requirement: 'Create a login form',
        },
        store,
        settings
      );

      const featureId = (analyzeResult as any).payload.feature_id;

      // Then split tasks
      const splitResult = await dispatchTool(
        'split_design_and_frontend_tasks',
        { feature_id: featureId },
        store,
        settings
      );

      expect(splitResult).toBeDefined();
      const payload = (splitResult as any).payload;
      expect(payload.pixelfera_tasks).toBeDefined();
      expect(payload.frontzilla_tasks).toBeDefined();
      expect(payload.collaboration_points).toBeDefined();
    });

    it('should generate feature spec', async () => {
      // Create feature
      const analyzeResult = await dispatchTool(
        'analyze_requirement',
        {
          requirement: 'Build a product listing page',
        },
        store,
        settings
      );

      const featureId = (analyzeResult as any).payload.feature_id;

      // Generate spec
      const specResult = await dispatchTool(
        'generate_feature_spec',
        { feature_id: featureId, detail_level: 'detailed' },
        store,
        settings
      );

      expect(specResult).toBeDefined();
      const payload = (specResult as any).payload;
      expect(payload.spec).toBeDefined();
      expect(payload.spec.wireframe_hints).toBeDefined();
      expect(payload.spec.api_contracts).toBeDefined();
      expect(payload.spec.component_list).toBeDefined();
    });
  });

  describe('Complete Feature Workflow', () => {
    it('should orchestrate complete UI feature workflow', async () => {
      const requirement = 'Build a user authentication flow with email signup and OAuth';

      const result = await dispatchTool(
        'run_ui_feature_workflow',
        {
          requirement,
          context: 'Critical path for new users',
          target: 'complete',
          stack: 'nextjs',
        },
        store,
        settings
      );

      expect(result).toBeDefined();
      const payload = (result as any).payload;

      expect(payload.feature_id).toBeDefined();
      expect(payload.workflow_id).toBeDefined();
      expect(payload.analysis).toBeDefined();
      expect(payload.design_tasks).toBeDefined();
      expect(payload.frontend_tasks).toBeDefined();
      expect(payload.collaboration_points).toBeDefined();

      // Verify analysis
      expect(payload.analysis.screens).toBeDefined();
      expect(payload.analysis.complexity).toMatch(/low|medium|high/);

      // Verify design tasks
      expect(payload.design_tasks.length).toBeGreaterThan(0);

      // Verify frontend tasks
      expect(payload.frontend_tasks.length).toBeGreaterThan(0);
    });
  });

  describe('Design System Workflow', () => {
    it('should create and document component spec', async () => {
      // Create feature first
      const feature = store.createFeature('Test Feature', 'Test req', {});

      // Create component spec
      const specResult = await dispatchTool(
        'generate_component_spec',
        { name: 'PrimaryButton', category: 'atom', feature_id: feature.id },
        store,
        settings
      );

      expect(specResult).toBeDefined();
      const componentSpec = (specResult as any).payload;
      expect(componentSpec.name).toBe('PrimaryButton');
      expect(componentSpec.props).toBeDefined();
      expect(componentSpec.variants).toBeDefined();

      // Get component_id from result
      const componentId = (specResult as any).component_id;
      if (componentId) {
        // Document component
        const docResult = await dispatchTool(
          'document_component',
          { component_id: componentId },
          store,
          settings
        );

        expect(docResult).toBeDefined();
        const documentation = (docResult as any).payload;
        expect(documentation.markdown).toBeDefined();
        expect(documentation.props_table).toBeDefined();
        expect(documentation.examples).toBeDefined();
      }
    });
  });

  describe('Integration Workflow', () => {
    it('should follow design to frontend workflow', async () => {
      // 1. Analyze requirement
      const analyzeResult = await dispatchTool(
        'analyze_requirement',
        { requirement: 'Create a product card component' },
        store,
        settings
      );
      const featureId = (analyzeResult as any).payload.feature_id;

      // 2. Design phase: Generate wireframe
      const wireframeResult = await dispatchTool(
        'generate_wireframe',
        { screen_name: 'Product Grid', feature_id: featureId },
        store,
        settings
      );
      expect((wireframeResult as any).payload.ascii_diagram).toBeDefined();

      // 3. Design phase: Create design tokens
      const tokensResult = await dispatchTool(
        'create_design_tokens',
        { feature_id: featureId },
        store,
        settings
      );
      expect((tokensResult as any).payload.tokens).toBeDefined();

      // 4. Frontend phase: Generate component
      const componentResult = await dispatchTool(
        'generate_react_component',
        { name: 'ProductCard' },
        store,
        settings
      );
      expect((componentResult as any).payload.typescript_code).toContain('React');

      // 5. Frontend phase: Generate tests
      const testResult = await dispatchTool(
        'generate_frontend_tests',
        { component_name: 'ProductCard' },
        store,
        settings
      );
      expect((testResult as any).payload.unit_tests).toBeDefined();
    });
  });
});
