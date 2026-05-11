import { nanoid } from 'nanoid';
import * as /home/dev/repos/platform-devs/pozilla-mcp-server/src/db/store-postgres.ts from '/home/dev/repos/platform-devs/pozilla-mcp-server/src/db/store-postgres.ts';
import * as fs from 'fs';
import { ZillaPostgresStore } from '../../../platform-service-template/lib/postgres_sync';

// ============================================================================
// Interfaces
// ============================================================================

export interface Epic {
  id: string;
  title: string;
  feature: string;
  scope: string;
  objectives: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface Feature {
  id: string;
  plan_id?: string;
  title: string;
  type: string;
  steps: string;
  expected_result: string;
  status: string;
  created_at: string;
}

export interface Story {
  id: string;
  plan_id?: string;
  title: string;
  scenario: string;
  tags: string;
  created_at: string;
}

export interface BugReport {
  id: string;
  title: string;
  severity: string;
  priority: string;
  steps_to_reproduce: string;
  expected: string;
  actual: string;
  environment: string;
  status: string;
  created_at: string;
}

export interface QualityGate {
  id: string;
  name: string;
  criteria: string;
  threshold?: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface TestResult {
  id: string;
  plan_id: string;
  status: string;
  passed?: number;
  failed?: number;
  coverage?: number;
  notes?: string;
  recorded_at: string;
}

export interface Checklist {
  id: string;
  title: string;
  items: unknown;
  status: string;
  created_at: string;
}

export interface Task {
  id: string;
  plan_id?: string;
  status: string;
  started_at?: string;
  completed_at?: string;
  created_at: string;
}

// ============================================================================
// PozillaStore — PostgreSQL Primary
// ============================================================================

export class PozillaStore {
  private pg: ZillaPostgresStore;
  private logger: any;

  constructor() {
    const postgresConfig = {
      host: process.env.POSTGRES_HOST || 'claude-dev',
      port: parseInt(process.env.POSTGRES_PORT || '5432', 10),
      user: process.env.POSTGRES_USER || 'postgres',
      password: process.env.POSTGRES_PASSWORD || 'postgres_password_local_dev',
      database: process.env.POSTGRES_DB || 'app',
    };

    this.logger = this.initializeLogger();

    try {
      this.pg = new ZillaPostgresStore('pozilla', postgresConfig);
      this.logger.info('✅ PozillaStore: PostgreSQL initialized');
    } catch (error) {
      this.logger.error(`❌ PozillaStore: Failed to initialize: ${error}`);
      throw error;
    }
  }

  private initializeLogger(): any {
    const logsDir = /home/dev/repos/platform-devs/pozilla-mcp-server/src/db/store-postgres.ts.join(process.env.HOME || '/tmp', '.platform', 'logs');
    if (!fs.existsSync(logsDir)) {
      fs.mkdirSync(logsDir, { recursive: true });
    }

    const logFile = /home/dev/repos/platform-devs/pozilla-mcp-server/src/db/store-postgres.ts.join(logsDir, 'pozilla.log');

    return {
      info: (msg: string) => {
        const timestamp = new Date().toISOString();
        console.log(`[${timestamp}] ℹ️  ${msg}`);
        fs.appendFileSync(logFile, `[${timestamp}] INFO: ${msg}\n`);
      },
      warn: (msg: string) => {
        const timestamp = new Date().toISOString();
        console.warn(`[${timestamp}] ⚠️  ${msg}`);
        fs.appendFileSync(logFile, `[${timestamp}] WARN: ${msg}\n`);
      },
      error: (msg: string) => {
        const timestamp = new Date().toISOString();
        console.error(`[${timestamp}] ❌ ${msg}`);
        fs.appendFileSync(logFile, `[${timestamp}] ERROR: ${msg}\n`);
      },
      debug: (msg: string) => {
        if (process.env.DEBUG === 'true') {
          const timestamp = new Date().toISOString();
          console.debug(`[${timestamp}] 🐛 ${msg}`);
          fs.appendFileSync(logFile, `[${timestamp}] DEBUG: ${msg}\n`);
        }
      },
    };
  }

  // ============================================================================
  // Test Plans
  // ============================================================================

  async createTestPlan(data: Omit<Epic, 'id' | 'created_at' | 'updated_at'>): Promise<Epic> {
    const id = `tp_${nanoid()}`;
    const now = new Date().toISOString();

    await this.pg.execute(
      `INSERT INTO epics (id, title, feature, scope, objectives, status, created_at, updated_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
      [id, data.title, data.feature, data.scope, data.objectives, data.status, now, now]
    );

    return { ...data, id, created_at: now, updated_at: now };
  }

  async getTestPlan(id: string): Promise<Epic | null> {
    const rows = await this.pg.query<Epic>('SELECT * FROM epics WHERE id = $1', [id]);
    return rows[0] || null;
  }

  async listTestPlans(): Promise<Epic[]> {
    return this.pg.query<Epic>('SELECT * FROM epics ORDER BY created_at DESC', []);
  }

  // ============================================================================
  // Test Cases
  // ============================================================================

  async createTestCase(data: Omit<Feature, 'id' | 'created_at'>): Promise<Feature> {
    const id = `tc_${nanoid()}`;
    const now = new Date().toISOString();

    await this.pg.execute(
      `INSERT INTO po_features (id, plan_id, title, type, steps, expected_result, status, created_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
      [id, data.plan_id, data.title, data.type, data.steps, data.expected_result, data.status, now]
    );

    return { ...data, id, created_at: now };
  }

  async listTestCases(planId?: string): Promise<Feature[]> {
    if (planId) {
      return this.pg.query<Feature>(
        'SELECT * FROM po_features WHERE plan_id = $1 ORDER BY created_at DESC',
        [planId]
      );
    }
    return this.pg.query<Feature>('SELECT * FROM po_features ORDER BY created_at DESC', []);
  }

  // ============================================================================
  // Test Scenarios
  // ============================================================================

  async createTestScenario(data: Omit<Story, 'id' | 'created_at'>): Promise<Story> {
    const id = `ts_${nanoid()}`;
    const now = new Date().toISOString();

    await this.pg.execute(
      `INSERT INTO po_stories (id, plan_id, title, scenario, tags, created_at)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [id, data.plan_id, data.title, data.scenario, data.tags, now]
    );

    return { ...data, id, created_at: now };
  }

  async addTestScenario(planId: string, data: Omit<Story, 'id' | 'created_at' | 'plan_id'>): Promise<Story> {
    return this.createTestScenario({ ...data, plan_id: planId });
  }

  async listTestScenarios(planId?: string): Promise<Story[]> {
    if (planId) {
      return this.pg.query<Story>(
        'SELECT * FROM po_stories WHERE plan_id = $1 ORDER BY created_at DESC',
        [planId]
      );
    }
    return this.pg.query<Story>('SELECT * FROM po_stories ORDER BY created_at DESC', []);
  }

  // ============================================================================
  // Bug Reports
  // ============================================================================

  async createBugReport(data: Omit<BugReport, 'id' | 'created_at'>): Promise<BugReport> {
    const id = `bug_${nanoid()}`;
    const now = new Date().toISOString();

    await this.pg.execute(
      `INSERT INTO bug_reports (id, title, severity, priority, steps_to_reproduce, expected, actual, environment, status, created_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`,
      [id, data.title, data.severity, data.priority, data.steps_to_reproduce, data.expected, data.actual, data.environment, data.status, now]
    );

    return { ...data, id, created_at: now };
  }

  async listBugReports(): Promise<BugReport[]> {
    return this.pg.query<BugReport>('SELECT * FROM bug_reports ORDER BY created_at DESC', []);
  }

  // ============================================================================
  // Quality Gates
  // ============================================================================

  async createQualityGate(data: Omit<QualityGate, 'id' | 'created_at' | 'updated_at'>): Promise<QualityGate> {
    const id = `qg_${nanoid()}`;
    const now = new Date().toISOString();

    await this.pg.execute(
      `INSERT INTO quality_gates (id, name, criteria, threshold, status, created_at, updated_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7)`,
      [id, data.name, data.criteria, data.threshold, data.status, now, now]
    );

    return { ...data, id, created_at: now, updated_at: now };
  }

  async listQualityGates(): Promise<QualityGate[]> {
    return this.pg.query<QualityGate>('SELECT * FROM quality_gates ORDER BY created_at DESC', []);
  }

  // ============================================================================
  // Test Results
  // ============================================================================

  async createTestResult(data: Omit<TestResult, 'id' | 'recorded_at'>): Promise<TestResult> {
    const id = `tr_${nanoid()}`;
    const now = new Date().toISOString();

    await this.pg.execute(
      `INSERT INTO test_results (id, plan_id, status, passed, failed, coverage, notes, recorded_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
      [id, data.plan_id, data.status, data.passed, data.failed, data.coverage, data.notes, now]
    );

    return { ...data, id, recorded_at: now };
  }

  async listTestResults(planId?: string): Promise<TestResult[]> {
    if (planId) {
      return this.pg.query<TestResult>(
        'SELECT * FROM test_results WHERE plan_id = $1 ORDER BY recorded_at DESC',
        [planId]
      );
    }
    return this.pg.query<TestResult>('SELECT * FROM test_results ORDER BY recorded_at DESC', []);
  }

  // ============================================================================
  // Checklists
  // ============================================================================

  async createChecklist(data: Omit<Checklist, 'id' | 'created_at'>): Promise<Checklist> {
    const id = `cl_${nanoid()}`;
    const now = new Date().toISOString();

    await this.pg.execute(
      `INSERT INTO checklists (id, title, items, status, created_at)
       VALUES ($1, $2, $3, $4, $5)`,
      [id, data.title, JSON.stringify(data.items), data.status, now]
    );

    return { ...data, id, created_at: now };
  }

  // ============================================================================
  // QA Executions
  // ============================================================================

  async createQAExecution(data: Omit<Task, 'id' | 'created_at'>): Promise<Task> {
    const id = `qa_${nanoid()}`;
    const now = new Date().toISOString();

    await this.pg.execute(
      `INSERT INTO po_tasks (id, plan_id, status, started_at, completed_at, created_at)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [id, data.plan_id, data.status, data.started_at, data.completed_at, now]
    );

    return { ...data, id, created_at: now };
  }

  // ============================================================================
  // Cleanup
  // ============================================================================

  async close(): Promise<void> {
    await this.pg.close();
  }
}
