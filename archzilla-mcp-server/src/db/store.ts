import Database from 'better-sqlite3';
import { nanoid } from 'nanoid';
import * as path from 'path';
import * as fs from 'fs';
import ZillaPostgresSync from '../../../platform-service-template/lib/postgres_sync';

export class ArchZillaStore {
  private db: Database.Database;
  private postgres: ZillaPostgresSync | null = null;
  private logger: any;

  constructor(dbPath?: string) {
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

        this.postgres = new ZillaPostgresSync('archzilla', postgresConfig);
        this.logger.info('✅ ArchZillaStore: PostgreSQL sync enabled');
      } catch (error) {
        this.logger.warn(`⚠️  ArchZillaStore: PostgreSQL sync disabled: ${error}`);
      }
    }
  }

  private initializeLogger(): any {
    const logsDir = path.join(process.env.HOME || '/tmp', '.platform', 'logs');
    if (!fs.existsSync(logsDir)) {
      fs.mkdirSync(logsDir, { recursive: true });
    }

    const logFile = path.join(logsDir, 'archzilla.log');

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
      CREATE TABLE IF NOT EXISTS architectures (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        domain TEXT NOT NULL,
        style TEXT NOT NULL,
        blueprint TEXT,
        modules TEXT,
        status TEXT DEFAULT 'draft',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS decisions (
        id TEXT PRIMARY KEY,
        architecture_id TEXT,
        title TEXT NOT NULL,
        context TEXT NOT NULL,
        decision TEXT NOT NULL,
        consequences TEXT,
        created_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS diagrams (
        id TEXT PRIMARY KEY,
        architecture_id TEXT,
        type TEXT NOT NULL,
        svg TEXT,
        created_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS reviews (
        id TEXT PRIMARY KEY,
        architecture_id TEXT,
        findings TEXT,
        recommendations TEXT,
        score INTEGER,
        created_at TEXT NOT NULL
      );
    `);
  }

  createArchitecture(name: string, domain: string, style: string): { id: string; created_at: string } {
    const id = `arch_${nanoid()}`;
    const now = new Date().toISOString();

    const stmt = this.db.prepare(`
      INSERT INTO architectures (id, name, domain, style, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?)
    `);

    stmt.run(id, name, domain, style, now, now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'architectures',
        {
          id,
          name,
          domain,
          style,
          status: 'draft',
          created_at: now,
          updated_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync architecture created: ${err}`);
      });
    }

    return { id, created_at: now };
  }

  createDecision(data: { architecture_id: string; title: string; context: string; decision: string; consequences?: string }): { id: string; created_at: string } {
    const id = `dec_${nanoid()}`;
    const now = new Date().toISOString();

    const stmt = this.db.prepare(`
      INSERT INTO decisions (id, architecture_id, title, context, decision, consequences, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `);

    stmt.run(id, data.architecture_id, data.title, data.context, data.decision, data.consequences || null, now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'decisions',
        {
          id,
          architecture_id: data.architecture_id,
          title: data.title,
          context: data.context,
          decision: data.decision,
          consequences: data.consequences,
          created_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync decision created: ${err}`);
      });
    }

    return { id, created_at: now };
  }

  createDiagram(data: { architecture_id: string; type: string; svg?: string }): { id: string; created_at: string } {
    const id = `diag_${nanoid()}`;
    const now = new Date().toISOString();

    const stmt = this.db.prepare(`
      INSERT INTO diagrams (id, architecture_id, type, svg, created_at)
      VALUES (?, ?, ?, ?, ?)
    `);

    stmt.run(id, data.architecture_id, data.type, data.svg || null, now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'diagrams',
        {
          id,
          architecture_id: data.architecture_id,
          type: data.type,
          svg: data.svg,
          created_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync diagram created: ${err}`);
      });
    }

    return { id, created_at: now };
  }

  createReview(data: { architecture_id: string; findings: string; recommendations: string; score: number }): { id: string; created_at: string } {
    const id = `rev_${nanoid()}`;
    const now = new Date().toISOString();

    const stmt = this.db.prepare(`
      INSERT INTO reviews (id, architecture_id, findings, recommendations, score, created_at)
      VALUES (?, ?, ?, ?, ?, ?)
    `);

    stmt.run(id, data.architecture_id, data.findings, data.recommendations, data.score, now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'reviews',
        {
          id,
          architecture_id: data.architecture_id,
          findings: data.findings,
          recommendations: data.recommendations,
          score: data.score,
          created_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync review created: ${err}`);
      });
    }

    return { id, created_at: now };
  }

  getArchitecture(id: string): any {
    const stmt = this.db.prepare('SELECT * FROM architectures WHERE id = ?');
    return stmt.get(id);
  }

  close(): void {
    if (this.postgres) {
      this.postgres.close();
    }
    this.db.close();
  }
}
