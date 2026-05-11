import Database from 'better-sqlite3';
import { nanoid } from 'nanoid';

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

export class QAZillaStore {
  private db: Database.Database;

  constructor(dbPath?: string) {
    this.db = new Database(dbPath);
    this.db.pragma('journal_mode = WAL');
    this.initializeTables();
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
    `);
  }

  createTestPlan(data: Omit<TestPlan, 'id' | 'created_at' | 'updated_at'>): TestPlan {
    const id = `tp_${nanoid()}`;
    const now = new Date().toISOString();
    const stmt = this.db.prepare(`
      INSERT INTO test_plans (id, title, feature, scope, objectives, status, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `);
    stmt.run(id, data.title, data.feature, data.scope, data.objectives, data.status, now, now);
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
    const stmt = this.db.prepare(`
      INSERT INTO test_cases (id, plan_id, title, type, steps, expected_result, status, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `);
    stmt.run(id, data.plan_id, data.title, data.type, data.steps, data.expected_result, data.status, now);
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
    const stmt = this.db.prepare(`
      INSERT INTO test_scenarios (id, plan_id, title, scenario, tags, created_at)
      VALUES (?, ?, ?, ?, ?, ?)
    `);
    stmt.run(id, data.plan_id, data.title, data.scenario, data.tags, now);
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
    const stmt = this.db.prepare(`
      INSERT INTO bug_reports (id, title, severity, priority, steps_to_reproduce, expected, actual, environment, status, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);
    stmt.run(id, data.title, data.severity, data.priority, data.steps_to_reproduce, data.expected, data.actual, data.environment, data.status, now);
    return { ...data, id, created_at: now };
  }

  listBugReports(): BugReport[] {
    const stmt = this.db.prepare('SELECT * FROM bug_reports ORDER BY created_at DESC');
    return stmt.all() as BugReport[];
  }

  createQualityGate(data: Omit<QualityGate, 'id' | 'created_at' | 'updated_at'>): QualityGate {
    const id = `qg_${nanoid()}`;
    const now = new Date().toISOString();
    const stmt = this.db.prepare(`
      INSERT INTO quality_gates (id, name, criteria, metrics, status, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `);
    stmt.run(id, data.name, data.criteria, data.metrics, data.status, now, now);
    return { ...data, id, created_at: now, updated_at: now };
  }

  listQualityGates(): QualityGate[] {
    const stmt = this.db.prepare('SELECT * FROM quality_gates ORDER BY created_at DESC');
    return stmt.all() as QualityGate[];
  }

  close(): void {
    this.db.close();
  }
}
