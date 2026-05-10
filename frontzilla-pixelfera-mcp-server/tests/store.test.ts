import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { FrontzillaPixelferaStore } from '../src/db/store';

describe('FrontzillaPixelferaStore', () => {
  let store: FrontzillaPixelferaStore;

  beforeEach(() => {
    store = new FrontzillaPixelferaStore(':memory:');
  });

  afterEach(() => {
    store.close();
  });

  describe('Features', () => {
    it('should create a feature', () => {
      const feature = store.createFeature('Test Feature', 'This is a test requirement', {
        screens: ['Dashboard', 'Settings'],
      });

      expect(feature.id).toMatch(/^feat_/);
      expect(feature.name).toBe('Test Feature');
      expect(feature.status).toBe('draft');
    });

    it('should retrieve a feature by ID', () => {
      const created = store.createFeature('Test', 'Requirement', {});
      const retrieved = store.getFeature(created.id);

      expect(retrieved).not.toBeNull();
      expect(retrieved?.name).toBe('Test');
    });

    it('should list features', () => {
      store.createFeature('Feature 1', 'Req 1', {});
      store.createFeature('Feature 2', 'Req 2', {});

      const features = store.listFeatures();
      expect(features.length).toBeGreaterThanOrEqual(2);
    });

    it('should update feature status', () => {
      const feature = store.createFeature('Test', 'Req', {});
      store.updateFeatureStatus(feature.id, 'analysis', { spec: 'data' });

      const updated = store.getFeature(feature.id);
      expect(updated?.status).toBe('analysis');
      expect(updated?.spec).toBeDefined();
    });
  });

  describe('Components', () => {
    it('should create a component', () => {
      const component = store.createComponent(
        'Button',
        'atom',
        'shared',
        { variant: 'primary' }
      );

      expect(component.id).toMatch(/^comp_/);
      expect(component.name).toBe('Button');
      expect(component.category).toBe('atom');
    });

    it('should retrieve a component', () => {
      const created = store.createComponent('Card', 'molecule', 'shared', {});
      const retrieved = store.getComponent(created.id);

      expect(retrieved).not.toBeNull();
      expect(retrieved?.name).toBe('Card');
    });

    it('should list components by agent', () => {
      store.createComponent('Button', 'atom', 'frontzilla', {});
      store.createComponent('Icon', 'atom', 'pixelfera', {});

      const frontzillaComponents = store.listComponents(undefined, 'frontzilla');
      expect(frontzillaComponents.length).toBeGreaterThan(0);
    });

    it('should update component', () => {
      const component = store.createComponent('Button', 'atom', 'shared', {});
      store.updateComponent(component.id, { doc: 'Component documentation' });

      const updated = store.getComponent(component.id);
      expect(updated?.doc).toBe('Component documentation');
    });
  });

  describe('Design Tokens', () => {
    it('should create design tokens', () => {
      const tokens = store.createDesignTokens(
        'Primary Palette',
        {
          primary: '#2563eb',
          secondary: '#7c3aed',
        },
        'css-vars'
      );

      expect(tokens.id).toMatch(/^tok_/);
      expect(tokens.format).toBe('css-vars');
    });

    it('should retrieve design tokens', () => {
      const created = store.createDesignTokens('Test', { color: '#fff' });
      const retrieved = store.getDesignTokens(created.id);

      expect(retrieved).not.toBeNull();
      expect(retrieved?.name).toBe('Test');
    });
  });

  describe('Workflows', () => {
    it('should create a workflow', () => {
      const feature = store.createFeature('Test', 'Req', {});
      const workflow = store.createWorkflow(feature.id);

      expect(workflow.id).toMatch(/^wf_/);
      expect(workflow.status).toBe('running');
    });

    it('should complete a workflow', () => {
      const feature = store.createFeature('Test', 'Req', {});
      const workflow = store.createWorkflow(feature.id);

      store.completeWorkflow(workflow.id, 'completed', { result: 'success' });

      const retrieved = store.getWorkflow(workflow.id);
      expect(retrieved?.status).toBe('completed');
      expect(retrieved?.result).toBeDefined();
    });
  });
});
