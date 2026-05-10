import Database from 'better-sqlite3';
import { nanoid } from 'nanoid';
import * as path from 'path';
import * as fs from 'fs';
import ZillaPostgresSync from '../../../platform-service-template/lib/postgres_sync';

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

        this.postgres = new ZillaPostgresSync('seczilla', postgresConfig);
        this.logger.info('✅ SecZillaStore: PostgreSQL sync enabled');
      } catch (error) {
        this.logger.warn(`⚠️  SecZillaStore: PostgreSQL sync disabled: ${error}`);
      }
    }
  }

  private initializeLogger(): any {
    const logsDir = path.join(process.env.HOME || '/tmp', '.platform', 'logs');
    if (!fs.existsSync(logsDir)) {
      fs.mkdirSync(logsDir, { recursive: true });
    }

    const logFile = path.join(logsDir, 'seczilla.log');

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

    // SQLite write (PRIMARY)
    const stmt = this.db.prepare(`
      INSERT INTO threat_models (id, title, application, architecture, assets, threats, controls, risk_score, status, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);
    stmt.run(id, data.title, data.application, data.architecture, data.assets, data.threats, data.controls, data.risk_score, data.status, now, now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'threat_models',
        {
          id,
          title: data.title,
          application: data.application,
          architecture: data.architecture,
          assets: data.assets,
          threats: data.threats,
          controls: data.controls,
          risk_score: data.risk_score,
          status: data.status,
          created_at: now,
          updated_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync threat model created: ${err}`);
      });
    }

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

    // SQLite write (PRIMARY)
    const stmt = this.db.prepare(`
      INSERT INTO vulnerabilities (id, model_id, title, category, severity, cvss_score, description, affected, remediation, status, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);
    stmt.run(id, data.model_id, data.title, data.category, data.severity, data.cvss_score, data.description, data.affected, data.remediation, data.status, now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'vulnerabilities',
        {
          id,
          model_id: data.model_id,
          title: data.title,
          category: data.category,
          severity: data.severity,
          cvss_score: data.cvss_score,
          description: data.description,
          affected: data.affected,
          remediation: data.remediation,
          status: data.status,
          created_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync vulnerability created: ${err}`);
      });
    }

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

    // SQLite write (PRIMARY)
    const stmt = this.db.prepare(`
      INSERT INTO security_controls (id, model_id, category, control, implementation, priority, effort, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `);
    stmt.run(id, data.model_id, data.category, data.control, data.implementation, data.priority, data.effort, now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'security_controls',
        {
          id,
          model_id: data.model_id,
          category: data.category,
          control: data.control,
          implementation: data.implementation,
          priority: data.priority,
          effort: data.effort,
          created_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync security control created: ${err}`);
      });
    }

    return { ...data, id, created_at: now };
  }

  createSecurityChecklist(data: Omit<SecurityChecklist, 'id' | 'created_at' | 'updated_at'>): SecurityChecklist {
    const id = `chk_${nanoid()}`;
    const now = new Date().toISOString();

    // SQLite write (PRIMARY)
    const stmt = this.db.prepare(`
      INSERT INTO security_checklists (id, type, title, items, scope, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `);
    stmt.run(id, data.type, data.title, data.items, data.scope, now, now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'security_checklists',
        {
          id,
          type: data.type,
          title: data.title,
          items: data.items,
          scope: data.scope,
          created_at: now,
          updated_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync security checklist created: ${err}`);
      });
    }

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

  // PHASE 2: Additional helper method for security integration
  getControls(modelId: string): SecurityControl[] {
    const stmt = this.db.prepare('SELECT * FROM security_controls WHERE model_id = ? ORDER BY priority, created_at');
    return stmt.all(modelId) as SecurityControl[];
  }

  close(): void {
    if (this.postgres) {
      this.postgres.close();
    }
    this.db.close();
  }
}
