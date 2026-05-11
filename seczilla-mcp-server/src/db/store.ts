import Database from 'better-sqlite3';
import { nanoid } from 'nanoid';

export interface ThreatModel {
  id: string;
  title: string;
  application: string;
  architecture: string;
  assets: string;
  threats: string;
  controls: string;
  risk_score: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface Vulnerability {
  id: string;
  model_id?: string;
  title: string;
  category: string;
  severity: string;
  cvss_score?: number;
  description: string;
  affected: string;
  remediation: string;
  status: string;
  created_at: string;
}

export interface SecurityControl {
  id: string;
  model_id?: string;
  category: string;
  control: string;
  implementation: string;
  priority: string;
  effort: string;
  created_at: string;
}

export interface SecurityChecklist {
  id: string;
  type: string;
  title: string;
  items: string;
  scope: string;
  created_at: string;
  updated_at: string;
}

export class SecZillaStore {
  private db: Database.Database;

  constructor(dbPath?: string) {
    this.db = new Database(dbPath);
    this.db.pragma('journal_mode = WAL');
    this.initializeTables();
  }

  private initializeTables(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS threat_models (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        application TEXT NOT NULL,
        architecture TEXT NOT NULL,
        assets TEXT NOT NULL,
        threats TEXT NOT NULL,
        controls TEXT NOT NULL,
        risk_score TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS vulnerabilities (
        id TEXT PRIMARY KEY,
        model_id TEXT,
        title TEXT NOT NULL,
        category TEXT NOT NULL,
        severity TEXT NOT NULL,
        cvss_score REAL,
        description TEXT NOT NULL,
        affected TEXT NOT NULL,
        remediation TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        created_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS security_controls (
        id TEXT PRIMARY KEY,
        model_id TEXT,
        category TEXT NOT NULL,
        control TEXT NOT NULL,
        implementation TEXT NOT NULL,
        priority TEXT NOT NULL,
        effort TEXT NOT NULL,
        created_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS security_checklists (
        id TEXT PRIMARY KEY,
        type TEXT NOT NULL,
        title TEXT NOT NULL,
        items TEXT NOT NULL,
        scope TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );
    `);
  }

  createThreatModel(data: Omit<ThreatModel, 'id' | 'created_at' | 'updated_at'>): ThreatModel {
    const id = `tm_${nanoid()}`;
    const now = new Date().toISOString();
    const stmt = this.db.prepare(`
      INSERT INTO threat_models (id, title, application, architecture, assets, threats, controls, risk_score, status, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);
    stmt.run(id, data.title, data.application, data.architecture, data.assets, data.threats, data.controls, data.risk_score, data.status, now, now);
    return { ...data, id, created_at: now, updated_at: now };
  }

  getThreatModel(id: string): ThreatModel | undefined {
    const stmt = this.db.prepare('SELECT * FROM threat_models WHERE id = ?');
    return stmt.get(id) as ThreatModel | undefined;
  }

  listThreatModels(): ThreatModel[] {
    const stmt = this.db.prepare('SELECT * FROM threat_models ORDER BY created_at DESC');
    return stmt.all() as ThreatModel[];
  }

  createVulnerability(data: Omit<Vulnerability, 'id' | 'created_at'>): Vulnerability {
    const id = `vuln_${nanoid()}`;
    const now = new Date().toISOString();
    const stmt = this.db.prepare(`
      INSERT INTO vulnerabilities (id, model_id, title, category, severity, cvss_score, description, affected, remediation, status, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);
    stmt.run(id, data.model_id, data.title, data.category, data.severity, data.cvss_score, data.description, data.affected, data.remediation, data.status, now);
    return { ...data, id, created_at: now };
  }

  listVulnerabilities(modelId?: string): Vulnerability[] {
    let stmt;
    if (modelId) {
      stmt = this.db.prepare('SELECT * FROM vulnerabilities WHERE model_id = ? ORDER BY created_at DESC');
      return stmt.all(modelId) as Vulnerability[];
    }
    stmt = this.db.prepare('SELECT * FROM vulnerabilities ORDER BY created_at DESC');
    return stmt.all() as Vulnerability[];
  }

  createSecurityControl(data: Omit<SecurityControl, 'id' | 'created_at'>): SecurityControl {
    const id = `ctrl_${nanoid()}`;
    const now = new Date().toISOString();
    const stmt = this.db.prepare(`
      INSERT INTO security_controls (id, model_id, category, control, implementation, priority, effort, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `);
    stmt.run(id, data.model_id, data.category, data.control, data.implementation, data.priority, data.effort, now);
    return { ...data, id, created_at: now };
  }

  createSecurityChecklist(data: Omit<SecurityChecklist, 'id' | 'created_at' | 'updated_at'>): SecurityChecklist {
    const id = `chk_${nanoid()}`;
    const now = new Date().toISOString();
    const stmt = this.db.prepare(`
      INSERT INTO security_checklists (id, type, title, items, scope, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `);
    stmt.run(id, data.type, data.title, data.items, data.scope, now, now);
    return { ...data, id, created_at: now, updated_at: now };
  }

  listSecurityChecklists(type?: string): SecurityChecklist[] {
    let stmt;
    if (type) {
      stmt = this.db.prepare('SELECT * FROM security_checklists WHERE type = ? ORDER BY created_at DESC');
      return stmt.all(type) as SecurityChecklist[];
    }
    stmt = this.db.prepare('SELECT * FROM security_checklists ORDER BY created_at DESC');
    return stmt.all() as SecurityChecklist[];
  }

  close(): void {
    this.db.close();
  }
}
