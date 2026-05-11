import Database from 'better-sqlite3';
import { nanoid } from 'nanoid';
import * as path from 'path';
import * as fs from 'fs';
import ZillaPostgresSync from '../../../platform-service-template/lib/postgres_sync';

export class POZillaStore {
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

        this.postgres = new ZillaPostgresSync('pozilla', postgresConfig);
        this.logger.info('✅ POZillaStore: PostgreSQL sync enabled');
      } catch (error) {
        this.logger.warn(`⚠️  POZillaStore: PostgreSQL sync disabled: ${error}`);
      }
    }
  }

  private initializeLogger(): any {
    const logsDir = path.join(process.env.HOME || '/tmp', '.platform', 'logs');
    if (!fs.existsSync(logsDir)) {
      fs.mkdirSync(logsDir, { recursive: true });
    }

    const logFile = path.join(logsDir, 'pozilla.log');

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
      CREATE TABLE IF NOT EXISTS epics (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        objective TEXT,
        status TEXT DEFAULT 'backlog',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS features (
        id TEXT PRIMARY KEY,
        epic_id TEXT,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        acceptance_criteria TEXT,
        status TEXT DEFAULT 'backlog',
        created_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS stories (
        id TEXT PRIMARY KEY,
        feature_id TEXT,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        acceptance_criteria TEXT,
        priority TEXT,
        status TEXT DEFAULT 'backlog',
        created_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        story_id TEXT,
        title TEXT NOT NULL,
        description TEXT,
        type TEXT,
        status TEXT DEFAULT 'backlog',
        created_at TEXT NOT NULL
      );
    `);
  }

  createEpic(title: string, description: string): { id: string; created_at: string } {
    const id = `epic_${nanoid()}`;
    const now = new Date().toISOString();

    const stmt = this.db.prepare(`
      INSERT INTO epics (id, title, description, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?)
    `);

    stmt.run(id, title, description, now, now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'epics',
        {
          id,
          title,
          description,
          status: 'backlog',
          created_at: now,
          updated_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync epic created: ${err}`);
      });
    }

    return { id, created_at: now };
  }

  createFeature(data: { epic_id: string; title: string; description: string; acceptance_criteria?: string }): { id: string; created_at: string } {
    const id = `feat_${nanoid()}`;
    const now = new Date().toISOString();

    const stmt = this.db.prepare(`
      INSERT INTO features (id, epic_id, title, description, acceptance_criteria, created_at)
      VALUES (?, ?, ?, ?, ?, ?)
    `);

    stmt.run(id, data.epic_id, data.title, data.description, data.acceptance_criteria || null, now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'features',
        {
          id,
          epic_id: data.epic_id,
          title: data.title,
          description: data.description,
          acceptance_criteria: data.acceptance_criteria,
          status: 'backlog',
          created_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync feature created: ${err}`);
      });
    }

    return { id, created_at: now };
  }

  createStory(data: { feature_id: string; title: string; description: string; acceptance_criteria?: string; priority?: string }): { id: string; created_at: string } {
    const id = `story_${nanoid()}`;
    const now = new Date().toISOString();

    const stmt = this.db.prepare(`
      INSERT INTO stories (id, feature_id, title, description, acceptance_criteria, priority, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `);

    stmt.run(id, data.feature_id, data.title, data.description, data.acceptance_criteria || null, data.priority || null, now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'stories',
        {
          id,
          feature_id: data.feature_id,
          title: data.title,
          description: data.description,
          acceptance_criteria: data.acceptance_criteria,
          priority: data.priority,
          status: 'backlog',
          created_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync story created: ${err}`);
      });
    }

    return { id, created_at: now };
  }

  createTask(data: { story_id: string; title: string; description?: string; type?: string }): { id: string; created_at: string } {
    const id = `task_${nanoid()}`;
    const now = new Date().toISOString();

    const stmt = this.db.prepare(`
      INSERT INTO tasks (id, story_id, title, description, type, created_at)
      VALUES (?, ?, ?, ?, ?, ?)
    `);

    stmt.run(id, data.story_id, data.title, data.description || null, data.type || null, now);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'tasks',
        {
          id,
          story_id: data.story_id,
          title: data.title,
          description: data.description,
          type: data.type,
          status: 'backlog',
          created_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync task created: ${err}`);
      });
    }

    return { id, created_at: now };
  }

  getEpic(id: string): any {
    const stmt = this.db.prepare('SELECT * FROM epics WHERE id = ?');
    return stmt.get(id);
  }

  close(): void {
    if (this.postgres) {
      this.postgres.close();
    }
    this.db.close();
  }
}
