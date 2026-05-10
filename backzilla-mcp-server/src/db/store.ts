import Database from 'better-sqlite3';
import { nanoid } from 'nanoid';
import * as path from 'path';
import * as fs from 'fs';
import ZillaPostgresSync from '../../../platform-service-template/lib/postgres_sync';

export class BackzillaStore {
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

        this.postgres = new ZillaPostgresSync('backzilla', postgresConfig);
        this.logger.info('✅ BackzillaStore: PostgreSQL sync enabled');
      } catch (error) {
        this.logger.warn(`⚠️  BackzillaStore: PostgreSQL sync disabled: ${error}`);
      }
    }
  }

  private initializeLogger(): any {
    const logsDir = path.join(process.env.HOME || '/tmp', '.platform', 'logs');
    if (!fs.existsSync(logsDir)) {
      fs.mkdirSync(logsDir, { recursive: true });
    }

    const logFile = path.join(logsDir, 'backzilla.log');

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
      CREATE TABLE IF NOT EXISTS apis (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        requirement TEXT NOT NULL,
        contract TEXT,
        implementation TEXT,
        tests TEXT,
        openapi_spec TEXT,
        status TEXT DEFAULT 'draft',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS services (
        id TEXT PRIMARY KEY,
        api_id TEXT,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        code TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS integrations (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        flow_diagram TEXT,
        auth_policy TEXT,
        error_handling TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS workflows (
        id TEXT PRIMARY KEY,
        api_id TEXT,
        status TEXT NOT NULL,
        result TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );
    `);
  }

  createAPI(name: string, requirement: string): { id: string; created_at: string } {
    const id = `api_${nanoid()}`;
    const now = new Date().toISOString();

    // SQLite write (PRIMARY) - always succeeds
    const stmt = this.db.prepare(`
      INSERT INTO apis (id, name, requirement, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?)
    `);

    stmt.run(id, name, requirement, now, now);

    // PostgreSQL write (SECONDARY) - async, non-blocking
    if (this.postgres) {
      this.postgres.sync(
        'apis',
        {
          id,
          name,
          requirement,
          status: 'draft',
          created_at: now,
          updated_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync API created: ${err}`);
      });
    }

    return { id, created_at: now };
  }

  updateAPI(id: string, updates: Record<string, any>): void {
    const now = new Date().toISOString();
    const validFields = ['name', 'requirement', 'contract', 'implementation', 'tests', 'openapi_spec', 'status'];
    const setClauses = validFields
      .filter((field) => updates[field] !== undefined)
      .map((field) => `${field} = ?`);

    if (setClauses.length === 0) return;

    setClauses.push('updated_at = ?');
    const values = validFields
      .filter((field) => updates[field] !== undefined)
      .map((field) => updates[field]);
    values.push(now);
    values.push(id);

    // SQLite write (PRIMARY)
    const stmt = this.db.prepare(`
      UPDATE apis
      SET ${setClauses.join(', ')}
      WHERE id = ?
    `);

    stmt.run(...values);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      const pgData = { id, ...updates, updated_at: now };
      this.postgres.sync('apis', pgData, 'update').catch((err) => {
        this.logger.warn(`Failed to sync API updated: ${err}`);
      });
    }
  }

  deleteAPI(id: string): void {
    // SQLite write (PRIMARY)
    const stmt = this.db.prepare('DELETE FROM apis WHERE id = ?');
    stmt.run(id);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync('apis', { id }, 'delete').catch((err) => {
        this.logger.warn(`Failed to sync API deleted: ${err}`);
      });
    }
  }

  getAPI(id: string): any {
    const stmt = this.db.prepare('SELECT * FROM apis WHERE id = ?');
    return stmt.get(id);
  }

  close(): void {
    if (this.postgres) {
      this.postgres.close();
    }
    this.db.close();
  }
}
