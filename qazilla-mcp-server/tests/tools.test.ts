import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { dispatch, TOOL_SCHEMAS } from '../src/tools/index';
import { QAZillaStore } from '../src/db/store';
import * as fs from 'fs';
import * as path from 'path';

const testDbPath = path.join(__dirname, 'test-tools.db');

describe('QAZilla Tools', () => {
  let store: QAZillaStore;

  beforeEach(() => {
    if (fs.existsSync(testDbPath)) {
      fs.unlinkSync(testDbPath);
    }
    store = new QAZillaStore(testDbPath);
  });

  afterEach(() => {
    store.close();
    if (fs.existsSync(testDbPath)) {
      fs.unlinkSync(testDbPath);
    }
  });

  it('should have 20 tools registered', () => {
    const toolNames = Object.keys(TOOL_SCHEMAS);
    expect(toolNames).toHaveLength(20);
  });

  describe('Test Planning Tools', () => {
    it('analyze_quality_requirement should return analysis', async () => {
      const result = await dispatch('analyze_quality_requirement', {
        requirement: 'User should be able to reset password',
        context: 'Security feature',
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('scenario');
    });

    it('generate_test_plan should create database record', async () => {
      const result = await dispatch('generate_test_plan', {
        feature: 'Password Reset',
        scope: 'Email-based password reset',
        objectives: ['Security', 'User experience'],
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('test_plan');

      const plans = store.listTestPlans();
      expect(plans.length).toBeGreaterThan(0);
    });

    it('review_acceptance_criteria should validate testability', async () => {
      const result = await dispatch('review_acceptance_criteria', {
        criteria: ['User can reset password', 'Email is sent', 'Link expires in 24h'],
        feature: 'Password Reset',
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('testable');
    });
  });

  describe('Test Case Generation Tools', () => {
    it('generate_test_cases should create test cases', async () => {
      const result = await dispatch('generate_test_cases', {
        feature: 'Login',
        scenario: 'Valid credentials',
        test_types: ['functional', 'api'],
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('test_cases');
    });

    it('generate_gherkin_scenarios should create BDD scenarios', async () => {
      const result = await dispatch('generate_gherkin_scenarios', {
        feature: 'Login',
        user_story: 'User can log in',
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('Given');
    });

    it('generate_e2e_tests should create end-to-end tests', async () => {
      const result = await dispatch('generate_e2e_tests', {
        feature: 'Checkout',
        critical_flows: ['add_to_cart', 'payment', 'confirmation'],
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('playwright');
    });

    it('generate_api_tests should create API tests', async () => {
      const result = await dispatch('generate_api_tests', {
        endpoint: '/api/users',
        method: 'POST',
        scenarios: ['success', 'validation_error', 'auth_error'],
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('api_tests');
    });
  });

  describe('Automation Tools', () => {
    it('generate_unit_tests should create unit tests', async () => {
      const result = await dispatch('generate_unit_tests', {
        component: 'UserService',
        language: 'typescript',
        framework: 'jest',
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('unit_tests');
    });

    it('generate_playwright_tests should create Playwright tests', async () => {
      const result = await dispatch('generate_playwright_tests', {
        feature: 'Landing Page',
        pages: ['home', 'about', 'contact'],
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('playwright');
    });

    it('generate_postman_collection should create API collection', async () => {
      const result = await dispatch('generate_postman_collection', {
        api_name: 'User API',
        endpoints: ['GET /users', 'POST /users', 'DELETE /users/:id'],
        auth_type: 'bearer',
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('postman_collection');
    });
  });

  describe('Bug Management Tools', () => {
    it('classify_bug_severity should classify bugs', async () => {
      const result = await dispatch('classify_bug_severity', {
        title: 'Application crashes on login',
        impact: 'Application crash - complete system failure',
        affected_users: 'All users',
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('critical');
    });

    it('generate_bug_report should create bug record', async () => {
      const result = await dispatch('generate_bug_report', {
        title: 'Login button not working',
        severity: 'high',
        steps: ['1. Open app', '2. Click login', '3. Observe error'],
        expected: 'Login form should appear',
        actual: 'Nothing happens',
        environment: 'staging',
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('bug_report');

      const bugs = store.listBugReports();
      expect(bugs.length).toBeGreaterThan(0);
    });

    it('validate_story_testability should validate stories', async () => {
      const result = await dispatch('validate_story_testability', {
        story: 'As a user, I want to reset my password',
        acceptance_criteria: ['Email is sent', 'Link works', 'Password is changed'],
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('testable');
    });
  });

  describe('Quality Gate Tools', () => {
    it('generate_quality_gate should create gate record', async () => {
      const result = await dispatch('generate_quality_gate', {
        gate_name: 'Release Quality Gate',
        criteria: ['No critical bugs', 'Coverage > 80%'],
        metrics: ['bug_count', 'coverage%'],
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('quality_gate');

      const gates = store.listQualityGates();
      expect(gates.length).toBeGreaterThan(0);
    });

    it('generate_uat_checklist should create UAT checklist', async () => {
      const result = await dispatch('generate_uat_checklist', {
        feature: 'Order Management',
        user_roles: ['admin', 'customer', 'support'],
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('checklist');
    });

    it('review_test_coverage should analyze coverage', async () => {
      const result = await dispatch('review_test_coverage', {
        component: 'UserService',
        coverage_target: 90,
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('coverage_review');
    });
  });

  describe('Regression & Smoke Tests', () => {
    it('generate_regression_suite should create regression tests', async () => {
      const result = await dispatch('generate_regression_suite', {
        feature: 'Checkout',
        previous_bugs: ['payment_timeout', 'validation_error'],
        critical_paths: ['happy_path', 'error_recovery'],
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('regression');
    });

    it('generate_smoke_test_suite should create smoke tests', async () => {
      const result = await dispatch('generate_smoke_test_suite', {
        application: 'E-commerce Platform',
        core_flows: ['login', 'search', 'checkout', 'logout'],
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('smoke');
    });
  });

  describe('Tool Schema Validation', () => {
    it('all tools should have valid schemas', () => {
      Object.entries(TOOL_SCHEMAS).forEach(([name, schema]) => {
        expect(schema).toBeDefined();
        expect(schema.name).toBe(name);
        expect(schema.description).toBeDefined();
        expect(schema.inputSchema).toBeDefined();
      });
    });
  });
});
