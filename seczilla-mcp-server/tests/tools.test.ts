import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { dispatch, TOOL_SCHEMAS } from '../src/tools/index';
import { SecZillaStore } from '../src/db/store';
import * as fs from 'fs';
import * as path from 'path';

const testDbPath = path.join(__dirname, 'test-tools.db');

describe('SecZilla Tools', () => {
  let store: SecZillaStore;

  beforeEach(() => {
    if (fs.existsSync(testDbPath)) {
      fs.unlinkSync(testDbPath);
    }
    store = new SecZillaStore(testDbPath);
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

  describe('Threat Modeling Tools', () => {
    it('analyze_security_requirement should return analysis', async () => {
      const result = await dispatch('analyze_security_requirement', {
        requirement: 'Build an e-commerce platform with user accounts and payments',
        context: 'Production deployment on AWS',
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('asset');
    });

    it('generate_threat_model should create database record', async () => {
      const result = await dispatch('generate_threat_model', {
        application: 'Payment Service',
        architecture: 'Microservices with API Gateway',
        users: JSON.stringify(['admin', 'merchant', 'customer']),
        data_flows: JSON.stringify(['api_request', 'database_query']),
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('threat_model');

      const models = store.listThreatModels();
      expect(models.length).toBeGreaterThan(0);
      expect(models[0].application).toBe('Payment Service');
    });

    it('classify_security_risks should categorize risks', async () => {
      const result = await dispatch('classify_security_risks', {
        threats: ['SQL Injection', 'XSS'],
        framework: 'owasp',
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('high');
    });
  });

  describe('Code & API Security Tools', () => {
    it('review_secure_code should detect issues', async () => {
      const testCode = `
        const query = "SELECT * FROM users WHERE id = " + userId;
        db.query(query);
      `;

      const result = await dispatch('review_secure_code', {
        code: testCode,
        language: 'javascript',
        focus: JSON.stringify(['injection', 'xss']),
      }, store);

      expect(result).toBeDefined();
      expect(result.toLowerCase()).toContain('injection');
    });

    it('review_api_security should check API endpoints', async () => {
      const result = await dispatch('review_api_security', {
        spec: 'REST API with /users, /products, /orders endpoints',
        auth_type: 'jwt',
        endpoints: JSON.stringify(['GET /users/:id', 'POST /orders']),
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('finding');
    });

    it('generate_security_controls should create controls', async () => {
      const result = await dispatch('generate_security_controls', {
        threats: ['injection', 'xss', 'csrf'],
        architecture: 'Three-tier web application',
        compliance: ['owasp'],
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('preventive');
    });
  });

  describe('Compliance Tools', () => {
    it('generate_lgpd_checklist should create database record', async () => {
      const result = await dispatch('generate_lgpd_checklist', {
        system: 'Customer Portal',
        data_types: ['CPF', 'email', 'phone', 'address'],
        purpose: 'User account management',
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('lgpd');

      const checklists = store.listSecurityChecklists('lgpd');
      expect(checklists.length).toBeGreaterThan(0);
      expect(checklists[0].type).toBe('lgpd');
    });

    it('map_sensitive_data should classify data', async () => {
      const result = await dispatch('map_sensitive_data', {
        system: 'Healthcare Platform',
        flows: JSON.stringify(['user_registration', 'patient_records']),
        storage: JSON.stringify(['postgresql', 'redis_cache']),
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('sensitive');
    });

    it('scan_dependency_risks should detect vulnerabilities', async () => {
      const result = await dispatch('scan_dependency_risks', {
        dependencies: ['lodash@4.17.0', 'express@4.16.0'],
        ecosystem: 'npm',
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('CVE');
    });
  });

  describe('DevSecOps Tools', () => {
    it('generate_security_test_cases should create test matrix', async () => {
      const result = await dispatch('generate_security_test_cases', {
        feature: 'User Login',
        threat_model_id: 'tm_test',
        attack_vectors: JSON.stringify(['brute_force', 'injection', 'xss']),
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('test');
    });

    it('generate_devsecops_pipeline should create pipeline config', async () => {
      const result = await dispatch('generate_devsecops_pipeline', {
        stack: 'nodejs',
        platform: 'github-actions',
        stages: JSON.stringify(['sast', 'dast', 'sca']),
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('pipeline');
    });

    it('generate_security_release_checklist should create record', async () => {
      const result = await dispatch('generate_security_release_checklist', {
        feature: 'Payment Integration v2.0',
        release_type: 'major',
        environment: 'production',
      }, store);

      expect(result).toBeDefined();
      expect(result).toContain('checklist');

      const checklists = store.listSecurityChecklists('release');
      expect(checklists.length).toBeGreaterThan(0);
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
