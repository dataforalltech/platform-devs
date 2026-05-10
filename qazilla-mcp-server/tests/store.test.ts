import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { QAZillaStore } from '../src/db/store';
import * as fs from 'fs';
import * as path from 'path';

const testDbPath = path.join(__dirname, 'test.db');

describe('QAZillaStore', () => {
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

  describe('Test Plans', () => {
    it('should create a test plan', () => {
      const plan = store.createTestPlan({
        title: 'E-commerce Feature Test Plan',
        feature: 'Checkout Flow',
        scope: 'Payment processing and order confirmation',
        objectives: JSON.stringify(['Validate payment', 'Verify email']),
        status: 'draft',
      });

      expect(plan.id).toBeDefined();
      expect(plan.id).toMatch(/^tp_/);
      expect(plan.title).toBe('E-commerce Feature Test Plan');
    });

    it('should retrieve a test plan', () => {
      const created = store.createTestPlan({
        title: 'Login Test Plan',
        feature: 'Authentication',
        scope: 'Login functionality',
        objectives: 'Validate login flows',
        status: 'draft',
      });

      const retrieved = store.getTestPlan(created.id);
      expect(retrieved).toBeDefined();
      expect(retrieved?.title).toBe('Login Test Plan');
    });

    it('should list test plans', () => {
      store.createTestPlan({
        title: 'Plan 1',
        feature: 'Feature 1',
        scope: 'Scope 1',
        objectives: 'Objectives 1',
        status: 'draft',
      });

      store.createTestPlan({
        title: 'Plan 2',
        feature: 'Feature 2',
        scope: 'Scope 2',
        objectives: 'Objectives 2',
        status: 'draft',
      });

      const plans = store.listTestPlans();
      expect(plans).toHaveLength(2);
    });
  });

  describe('Test Cases', () => {
    it('should create a test case', () => {
      const testCase = store.createTestCase({
        title: 'Valid Login Test',
        type: 'functional',
        steps: JSON.stringify(['Enter username', 'Enter password', 'Click login']),
        expected_result: 'User is logged in',
        status: 'pending',
      });

      expect(testCase.id).toBeDefined();
      expect(testCase.id).toMatch(/^tc_/);
      expect(testCase.type).toBe('functional');
    });

    it('should list test cases', () => {
      store.createTestCase({
        title: 'Test 1',
        type: 'functional',
        steps: 'Steps 1',
        expected_result: 'Result 1',
        status: 'pending',
      });

      store.createTestCase({
        title: 'Test 2',
        type: 'api',
        steps: 'Steps 2',
        expected_result: 'Result 2',
        status: 'pending',
      });

      const testCases = store.listTestCases();
      expect(testCases).toHaveLength(2);
    });
  });

  describe('Test Scenarios', () => {
    it('should create a test scenario', () => {
      const scenario = store.createTestScenario({
        title: 'User Registration Scenario',
        scenario: 'Given user on signup page When user enters email Then confirmation sent',
        tags: JSON.stringify(['signup', 'email']),
      });

      expect(scenario.id).toBeDefined();
      expect(scenario.id).toMatch(/^ts_/);
      expect(scenario.title).toBe('User Registration Scenario');
    });

    it('should list test scenarios', () => {
      store.createTestScenario({
        title: 'Scenario 1',
        scenario: 'Gherkin 1',
        tags: 'tag1',
      });

      store.createTestScenario({
        title: 'Scenario 2',
        scenario: 'Gherkin 2',
        tags: 'tag2',
      });

      const scenarios = store.listTestScenarios();
      expect(scenarios).toHaveLength(2);
    });
  });

  describe('Bug Reports', () => {
    it('should create a bug report', () => {
      const bug = store.createBugReport({
        title: 'Login button not responding',
        severity: 'high',
        priority: 'P1',
        steps_to_reproduce: '1. Click login 2. Observe',
        expected: 'Login form submits',
        actual: 'Button is unresponsive',
        environment: 'staging',
        status: 'open',
      });

      expect(bug.id).toBeDefined();
      expect(bug.id).toMatch(/^bug_/);
      expect(bug.severity).toBe('high');
    });

    it('should list bug reports', () => {
      store.createBugReport({
        title: 'Bug 1',
        severity: 'high',
        priority: 'P1',
        steps_to_reproduce: 'Steps',
        expected: 'Expected',
        actual: 'Actual',
        environment: 'dev',
        status: 'open',
      });

      const bugs = store.listBugReports();
      expect(bugs).toHaveLength(1);
    });
  });

  describe('Quality Gates', () => {
    it('should create a quality gate', () => {
      const gate = store.createQualityGate({
        name: 'Code Coverage Gate',
        criteria: JSON.stringify(['coverage >= 80%', 'no critical bugs']),
        metrics: JSON.stringify(['coverage%', 'bug_count']),
        status: 'pending',
      });

      expect(gate.id).toBeDefined();
      expect(gate.id).toMatch(/^qg_/);
      expect(gate.name).toBe('Code Coverage Gate');
    });

    it('should list quality gates', () => {
      store.createQualityGate({
        name: 'Gate 1',
        criteria: 'Criteria 1',
        metrics: 'Metrics 1',
        status: 'pending',
      });

      store.createQualityGate({
        name: 'Gate 2',
        criteria: 'Criteria 2',
        metrics: 'Metrics 2',
        status: 'pending',
      });

      const gates = store.listQualityGates();
      expect(gates).toHaveLength(2);
    });
  });
});
