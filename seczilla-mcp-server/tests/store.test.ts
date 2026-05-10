import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { SecZillaStore } from '../src/db/store';
import * as fs from 'fs';
import * as path from 'path';

const testDbPath = path.join(__dirname, 'test.db');

describe('SecZillaStore', () => {
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

  describe('Threat Models', () => {
    it('should create a threat model', () => {
      const model = store.createThreatModel({
        title: 'E-commerce Platform',
        application: 'Online Store',
        architecture: JSON.stringify({ layers: ['frontend', 'api', 'database'] }),
        assets: JSON.stringify({ critical: ['user_data', 'payment_info'] }),
        threats: JSON.stringify({ stride: ['spoofing', 'tampering'] }),
        controls: JSON.stringify({ preventive: ['mfa', 'encryption'] }),
        risk_score: 'high',
        status: 'draft',
      });

      expect(model.id).toBeDefined();
      expect(model.id).toMatch(/^tm_/);
      expect(model.title).toBe('E-commerce Platform');
      expect(model.status).toBe('draft');
    });

    it('should retrieve a threat model', () => {
      const created = store.createThreatModel({
        title: 'Test Model',
        application: 'Test App',
        architecture: '{}',
        assets: '{}',
        threats: '{}',
        controls: '{}',
        risk_score: 'medium',
        status: 'draft',
      });

      const retrieved = store.getThreatModel(created.id);
      expect(retrieved).toBeDefined();
      expect(retrieved?.title).toBe('Test Model');
    });

    it('should list all threat models', () => {
      store.createThreatModel({
        title: 'Model 1',
        application: 'App 1',
        architecture: '{}',
        assets: '{}',
        threats: '{}',
        controls: '{}',
        risk_score: 'low',
        status: 'draft',
      });

      store.createThreatModel({
        title: 'Model 2',
        application: 'App 2',
        architecture: '{}',
        assets: '{}',
        threats: '{}',
        controls: '{}',
        risk_score: 'high',
        status: 'draft',
      });

      const models = store.listThreatModels();
      expect(models).toHaveLength(2);
      expect(models.some(m => m.title === 'Model 1')).toBe(true);
      expect(models.some(m => m.title === 'Model 2')).toBe(true);
    });
  });

  describe('Vulnerabilities', () => {
    it('should create a vulnerability', () => {
      const vuln = store.createVulnerability({
        title: 'SQL Injection',
        category: 'owasp_top10',
        severity: 'critical',
        description: 'Unsanitized database queries',
        affected: JSON.stringify({ components: ['user_service'] }),
        remediation: JSON.stringify({ steps: ['Use parameterized queries'] }),
        status: 'open',
      });

      expect(vuln.id).toBeDefined();
      expect(vuln.id).toMatch(/^vuln_/);
      expect(vuln.severity).toBe('critical');
    });

    it('should list vulnerabilities', () => {
      store.createVulnerability({
        title: 'Vuln 1',
        category: 'owasp_top10',
        severity: 'high',
        description: 'Test',
        affected: '{}',
        remediation: '{}',
        status: 'open',
      });

      store.createVulnerability({
        title: 'Vuln 2',
        category: 'api_security',
        severity: 'medium',
        description: 'Test',
        affected: '{}',
        remediation: '{}',
        status: 'open',
      });

      const vulns = store.listVulnerabilities();
      expect(vulns).toHaveLength(2);
    });
  });

  describe('Security Controls', () => {
    it('should create a security control', () => {
      const ctrl = store.createSecurityControl({
        category: 'preventive',
        control: 'Input Validation',
        implementation: JSON.stringify({ method: 'whitelist_based' }),
        priority: 'P1',
        effort: 'low',
      });

      expect(ctrl.id).toBeDefined();
      expect(ctrl.id).toMatch(/^ctrl_/);
      expect(ctrl.priority).toBe('P1');
    });
  });

  describe('Security Checklists', () => {
    it('should create a security checklist', () => {
      const checklist = store.createSecurityChecklist({
        type: 'lgpd',
        title: 'LGPD Compliance Checklist',
        items: JSON.stringify({ items: ['data_mapping', 'consent_forms', 'retention_policy'] }),
        scope: 'user_data_handling',
      });

      expect(checklist.id).toBeDefined();
      expect(checklist.id).toMatch(/^chk_/);
      expect(checklist.type).toBe('lgpd');
    });

    it('should list checklists by type', () => {
      store.createSecurityChecklist({
        type: 'lgpd',
        title: 'LGPD Check 1',
        items: '{}',
        scope: 'test',
      });

      store.createSecurityChecklist({
        type: 'release',
        title: 'Release Check 1',
        items: '{}',
        scope: 'test',
      });

      const lgpdChecklists = store.listSecurityChecklists('lgpd');
      expect(lgpdChecklists).toHaveLength(1);
      expect(lgpdChecklists[0].type).toBe('lgpd');
    });
  });
});
