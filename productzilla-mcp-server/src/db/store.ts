import Database from 'better-sqlite3';
import { nanoid } from 'nanoid';
import * as path from 'path';
import * as fs from 'fs';
import ZillaPostgresSync from '../../../platform-service-template/lib/postgres_sync';

export class ProductZillaStore {
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

        this.postgres = new ZillaPostgresSync('productzilla', postgresConfig);
        this.logger.info('✅ ProductZillaStore: PostgreSQL sync enabled');
      } catch (error) {
        this.logger.warn(`⚠️  ProductZillaStore: PostgreSQL sync disabled: ${error}`);
      }
    }
  }

  private initializeLogger(): any {
    const logsDir = path.join(process.env.HOME || '/tmp', '.platform', 'logs');
    if (!fs.existsSync(logsDir)) {
      fs.mkdirSync(logsDir, { recursive: true });
    }

    const logFile = path.join(logsDir, 'productzilla.log');

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
      CREATE TABLE IF NOT EXISTS features (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        problem_statement TEXT NOT NULL,
        vision TEXT,
        status TEXT DEFAULT 'discovery',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS user_stories (
        id TEXT PRIMARY KEY,
        feature_id TEXT,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        acceptance_criteria TEXT,
        created_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS backlogs (
        id TEXT PRIMARY KEY,
        feature_id TEXT,
        items TEXT,
        priority_framework TEXT,
        scores TEXT,
        created_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS releases (
        id TEXT PRIMARY KEY,
        feature_id TEXT,
        phase TEXT,
        metrics TEXT,
        timeline TEXT,
        created_at TEXT NOT NULL
      );
    `);
  }

  createFeature(name: string, problem: string): { id: string; created_at: string } {
    const id = `feat_${nanoid()}`;
    const now = new Date().toISOString();

    const stmt = this.db.prepare(`
      INSERT INTO features (id, name, problem_statement, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?)
    `);

    stmt.run(id, name, problem, now, now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'features',
        {
          id,
          name,
          problem_statement: problem,
          status: 'discovery',
          created_at: now,
          updated_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync feature created: ${err}`);
      });
    }

    return { id, created_at: now };
  }

  createUserStory(data: { feature_id: string; title: string; description: string; acceptance_criteria?: string }): { id: string; created_at: string } {
    const id = `story_${nanoid()}`;
    const now = new Date().toISOString();

    const stmt = this.db.prepare(`
      INSERT INTO user_stories (id, feature_id, title, description, acceptance_criteria, created_at)
      VALUES (?, ?, ?, ?, ?, ?)
    `);

    stmt.run(id, data.feature_id, data.title, data.description, data.acceptance_criteria || null, now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'user_stories',
        {
          id,
          feature_id: data.feature_id,
          title: data.title,
          description: data.description,
          acceptance_criteria: data.acceptance_criteria,
          created_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync user story created: ${err}`);
      });
    }

    return { id, created_at: now };
  }

  createBacklog(data: { feature_id: string; items: string; priority_framework?: string; scores?: string }): { id: string; created_at: string } {
    const id = `backlog_${nanoid()}`;
    const now = new Date().toISOString();

    const stmt = this.db.prepare(`
      INSERT INTO backlogs (id, feature_id, items, priority_framework, scores, created_at)
      VALUES (?, ?, ?, ?, ?, ?)
    `);

    stmt.run(id, data.feature_id, data.items, data.priority_framework || null, data.scores || null, now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'backlogs',
        {
          id,
          feature_id: data.feature_id,
          items: data.items,
          priority_framework: data.priority_framework,
          scores: data.scores,
          created_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync backlog created: ${err}`);
      });
    }

    return { id, created_at: now };
  }

  createRelease(data: { feature_id: string; phase: string; metrics?: string; timeline?: string }): { id: string; created_at: string } {
    const id = `release_${nanoid()}`;
    const now = new Date().toISOString();

    const stmt = this.db.prepare(`
      INSERT INTO releases (id, feature_id, phase, metrics, timeline, created_at)
      VALUES (?, ?, ?, ?, ?, ?)
    `);

    stmt.run(id, data.feature_id, data.phase, data.metrics || null, data.timeline || null, now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'releases',
        {
          id,
          feature_id: data.feature_id,
          phase: data.phase,
          metrics: data.metrics,
          timeline: data.timeline,
          created_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync release created: ${err}`);
      });
    }

    return { id, created_at: now };
  }

  getFeature(id: string): any {
    const stmt = this.db.prepare('SELECT * FROM features WHERE id = ?');
    return stmt.get(id);
  }

  close(): void {
    if (this.postgres) {
      this.postgres.close();
    }
    this.db.close();
  }
}
