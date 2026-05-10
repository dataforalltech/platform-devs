import Database from 'better-sqlite3';
import { nanoid } from 'nanoid';
import * as path from 'path';
import * as fs from 'fs';
import ZillaPostgresSync from '../../../platform-service-template/lib/postgres_sync';

export interface TestPlan {
  id: string;
  title: string;
  feature: string;
  scope: string;
  objectives: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface TestCase {
  id: string;
  plan_id?: string;
  title: string;
  type: string;
  steps: string;
  expected_result: string;
  status: string;
  created_at: string;
}

export interface TestScenario {
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
  metrics: string;
  status: string;
  created_at: string;
  updated_at: string;
}

// PHASE 1: New interfaces
export interface TestResult {
  id: string;
  plan_id: string;
  scenario_id: string;
  status: string;
  duration_ms?: number;
  evidence?: string;
  recorded_at: string;
}

export interface Checklist {
  id: string;
  title: string;
  type: string;
  items: unknown[];
  created_at: string;
}

export interface QAExecution {
  id: string;
  tool_name: string;
  result: unknown;
  executed_at: string;
}

export class QAZillaStore {
  private db: Database.Database;
  private postgres: ZillaPostgresSync | null = null;
  private logger: any;

  constructor(dbPath: string) {
    this.db = new Database(dbPath);
    this.db.pragma('journal_mode = WAL');
    this.logger = this.initializeLogger();
    this.initializeTables();

    // Initialize PostgreSQL sync layer
    if (process.env.POSTGRES_SYNC_ENABLED === 'true') {
      try {
        const postgresConfig = {
          host: process.env.POSTGRES_HOST || 'claude-dev',
          port: parseInt(process.env.POSTGRES_PORT || '5432', 10),
          user: process.env.POSTGRES_USER || 'postgres',
          password: process.env.POSTGRES_PASSWORD || 'postgres_password_local_dev',
          database: process.env.POSTGRES_DB || 'app',
        };

        this.postgres = new ZillaPostgresSync('qazilla', postgresConfig);
        this.logger.info('✅ QAZillaStore: PostgreSQL sync enabled');
      } catch (error) {
        this.logger.warn(`⚠️  QAZillaStore: PostgreSQL sync disabled: ${error}`);
      }
    }
  }

  private initializeLogger(): any {
    const logsDir = path.join(process.env.HOME || '/tmp', '.platform', 'logs');
    if (!fs.existsSync(logsDir)) {
      fs.mkdirSync(logsDir, { recursive: true });
    }

    const logFile = path.join(logsDir, 'qazilla.log');

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
      debug: (msg: string) => {
        if (process.env.DEBUG === 'true') {
          const timestamp = new Date().toISOString();
          console.debug(`[${timestamp}] 🐛 ${msg}`);
          fs.appendFileSync(logFile, `[${timestamp}] DEBUG: ${msg}\n`);
        }
      },
    };
  }

  private initializeTables(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS test_plans (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        feature TEXT NOT NULL,
        scope TEXT NOT NULL,
        objectives TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS test_cases (
        id TEXT PRIMARY KEY,
        plan_id TEXT,
        title TEXT NOT NULL,
        type TEXT NOT NULL,
        steps TEXT NOT NULL,
        expected_result TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS test_scenarios (
        id TEXT PRIMARY KEY,
        plan_id TEXT,
        title TEXT NOT NULL,
        scenario TEXT NOT NULL,
        tags TEXT NOT NULL,
        created_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS bug_reports (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        severity TEXT NOT NULL,
        priority TEXT NOT NULL,
        steps_to_reproduce TEXT NOT NULL,
        expected TEXT NOT NULL,
        actual TEXT NOT NULL,
        environment TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        created_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS quality_gates (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        criteria TEXT NOT NULL,
        metrics TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS test_results (
        id TEXT PRIMARY KEY,
        plan_id TEXT NOT NULL,
        scenario_id TEXT NOT NULL,
        status TEXT NOT NULL,
        duration_ms INTEGER,
        evidence TEXT,
        recorded_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS checklists (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        type TEXT NOT NULL,
        items TEXT NOT NULL,
        created_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS qa_executions (
        id TEXT PRIMARY KEY,
        tool_name TEXT NOT NULL,
        result TEXT NOT NULL,
        executed_at TEXT NOT NULL
      );
    `);
  }

  createTestPlan(data: Omit<TestPlan, 'id' | 'created_at' | 'updated_at'>): TestPlan {
    const id = `tp_${nanoid()}`;
    const now = new Date().toISOString();

    // SQLite write (PRIMARY)
    const stmt = this.db.prepare(`
      INSERT INTO test_plans (id, title, feature, scope, objectives, status, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `);
    stmt.run(id, data.title, data.feature, data.scope, data.objectives, data.status, now, now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'test_plans',
        {
          id,
          title: data.title,
          feature: data.feature,
          scope: data.scope,
          objectives: data.objectives,
          status: data.status,
          created_at: now,
          updated_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync test plan created: ${err}`);
      });
    }

    return { ...data, id, created_at: now, updated_at: now };
  }

  getTestPlan(id: string): TestPlan | undefined {
    const stmt = this.db.prepare('SELECT * FROM test_plans WHERE id = ?');
    return stmt.get(id) as TestPlan | undefined;
  }

  listTestPlans(): TestPlan[] {
    const stmt = this.db.prepare('SELECT * FROM test_plans ORDER BY created_at DESC');
    return stmt.all() as TestPlan[];
  }

  createTestCase(data: Omit<TestCase, 'id' | 'created_at'>): TestCase {
    const id = `tc_${nanoid()}`;
    const now = new Date().toISOString();

    // SQLite write (PRIMARY)
    const stmt = this.db.prepare(`
      INSERT INTO test_cases (id, plan_id, title, type, steps, expected_result, status, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `);
    stmt.run(id, data.plan_id, data.title, data.type, data.steps, data.expected_result, data.status, now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'test_cases',
        {
          id,
          plan_id: data.plan_id,
          title: data.title,
          type: data.type,
          steps: data.steps,
          expected_result: data.expected_result,
          status: data.status,
          created_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync test case created: ${err}`);
      });
    }

    return { ...data, id, created_at: now };
  }

  listTestCases(planId?: string): TestCase[] {
    let stmt;
    if (planId) {
      stmt = this.db.prepare('SELECT * FROM test_cases WHERE plan_id = ? ORDER BY created_at DESC');
      return stmt.all(planId) as TestCase[];
    }
    stmt = this.db.prepare('SELECT * FROM test_cases ORDER BY created_at DESC');
    return stmt.all() as TestCase[];
  }

  createTestScenario(data: Omit<TestScenario, 'id' | 'created_at'>): TestScenario {
    const id = `ts_${nanoid()}`;
    const now = new Date().toISOString();

    // SQLite write (PRIMARY)
    const stmt = this.db.prepare(`
      INSERT INTO test_scenarios (id, plan_id, title, scenario, tags, created_at)
      VALUES (?, ?, ?, ?, ?, ?)
    `);
    stmt.run(id, data.plan_id, data.title, data.scenario, data.tags, now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'test_scenarios',
        {
          id,
          plan_id: data.plan_id,
          title: data.title,
          scenario: data.scenario,
          tags: data.tags,
          created_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync test scenario created: ${err}`);
      });
    }

    return { ...data, id, created_at: now };
  }

  listTestScenarios(planId?: string): TestScenario[] {
    let stmt;
    if (planId) {
      stmt = this.db.prepare('SELECT * FROM test_scenarios WHERE plan_id = ? ORDER BY created_at DESC');
      return stmt.all(planId) as TestScenario[];
    }
    stmt = this.db.prepare('SELECT * FROM test_scenarios ORDER BY created_at DESC');
    return stmt.all() as TestScenario[];
  }

  createBugReport(data: Omit<BugReport, 'id' | 'created_at'>): BugReport {
    const id = `bug_${nanoid()}`;
    const now = new Date().toISOString();

    // SQLite write (PRIMARY)
    const stmt = this.db.prepare(`
      INSERT INTO bug_reports (id, title, severity, priority, steps_to_reproduce, expected, actual, environment, status, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);
    stmt.run(id, data.title, data.severity, data.priority, data.steps_to_reproduce, data.expected, data.actual, data.environment, data.status, now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'bug_reports',
        {
          id,
          title: data.title,
          severity: data.severity,
          priority: data.priority,
          steps_to_reproduce: data.steps_to_reproduce,
          expected: data.expected,
          actual: data.actual,
          environment: data.environment,
          status: data.status,
          created_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync bug report created: ${err}`);
      });
    }

    return { ...data, id, created_at: now };
  }

  listBugReports(): BugReport[] {
    const stmt = this.db.prepare('SELECT * FROM bug_reports ORDER BY created_at DESC');
    return stmt.all() as BugReport[];
  }

  createQualityGate(data: Omit<QualityGate, 'id' | 'created_at' | 'updated_at'>): QualityGate {
    const id = `qg_${nanoid()}`;
    const now = new Date().toISOString();

    // SQLite write (PRIMARY)
    const stmt = this.db.prepare(`
      INSERT INTO quality_gates (id, name, criteria, metrics, status, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `);
    stmt.run(id, data.name, data.criteria, data.metrics, data.status, now, now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'quality_gates',
        {
          id,
          name: data.name,
          criteria: data.criteria,
          metrics: data.metrics,
          status: data.status,
          created_at: now,
          updated_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync quality gate created: ${err}`);
      });
    }

    return { ...data, id, created_at: now, updated_at: now };
  }

  listQualityGates(): QualityGate[] {
    const stmt = this.db.prepare('SELECT * FROM quality_gates ORDER BY created_at DESC');
    return stmt.all() as QualityGate[];
  }

  // PHASE 1: Test Results and Checklists
  addTestScenario(data: Omit<TestScenario, 'created_at'>): TestScenario {
    const now = new Date().toISOString();

    // SQLite write (PRIMARY)
    const stmt = this.db.prepare(`
      INSERT INTO test_scenarios (id, plan_id, title, scenario, tags, created_at)
      VALUES (?, ?, ?, ?, ?, ?)
    `);
    stmt.run(data.id, data.plan_id, data.title || data.scenario, data.scenario, JSON.stringify(data), now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'test_scenarios',
        {
          id: data.id,
          plan_id: data.plan_id,
          title: data.title || data.scenario,
          scenario: data.scenario,
          tags: JSON.stringify(data),
          created_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync test scenario added: ${err}`);
      });
    }

    return { ...data, created_at: now };
  }

  recordTestResult(data: Omit<TestResult, 'recorded_at'>): TestResult {
    const now = new Date().toISOString();

    // SQLite write (PRIMARY)
    const stmt = this.db.prepare(`
      INSERT INTO test_results (id, plan_id, scenario_id, status, duration_ms, evidence, recorded_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `);
    stmt.run(data.id, data.plan_id, data.scenario_id, data.status, data.duration_ms, data.evidence, now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'test_results',
        {
          id: data.id,
          plan_id: data.plan_id,
          scenario_id: data.scenario_id,
          status: data.status,
          duration_ms: data.duration_ms,
          evidence: data.evidence,
          recorded_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync test result recorded: ${err}`);
      });
    }

    return { ...data, recorded_at: now };
  }

  getTestResults(planId: string): TestResult[] {
    const stmt = this.db.prepare('SELECT * FROM test_results WHERE plan_id = ? ORDER BY recorded_at DESC');
    return stmt.all(planId) as TestResult[];
  }

  createChecklist(data: Checklist): Checklist {
    // SQLite write (PRIMARY)
    const stmt = this.db.prepare(`
      INSERT INTO checklists (id, title, type, items, created_at)
      VALUES (?, ?, ?, ?, ?)
    `);
    stmt.run(data.id, data.title, data.type, JSON.stringify(data.items), data.created_at);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'checklists',
        {
          id: data.id,
          title: data.title,
          type: data.type,
          items: JSON.stringify(data.items),
          created_at: data.created_at,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync checklist created: ${err}`);
      });
    }

    return data;
  }

  recordQAExecution(toolName: string, result: unknown): QAExecution {
    const id = `exec_${nanoid()}`;
    const now = new Date().toISOString();

    // SQLite write (PRIMARY)
    const stmt = this.db.prepare(`
      INSERT INTO qa_executions (id, tool_name, result, executed_at)
      VALUES (?, ?, ?, ?)
    `);
    stmt.run(id, toolName, JSON.stringify(result), now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'qa_executions',
        {
          id,
          tool_name: toolName,
          result: JSON.stringify(result),
          executed_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync QA execution recorded: ${err}`);
      });
    }

    return { id, tool_name: toolName, result, executed_at: now };
  }

  close(): void {
    if (this.postgres) {
      this.postgres.close();
    }
    this.db.close();
  }
}
