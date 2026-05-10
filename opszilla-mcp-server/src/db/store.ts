import Database from 'better-sqlite3';
import { nanoid } from 'nanoid';

export class OpsZillaStore {
  private db: Database.Database;

  constructor(dbPath: string) {
    this.db = new Database(dbPath);
    this.db.pragma('journal_mode = WAL');
    this.initializeTables();
  }

  private initializeTables(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS deployments (
        id TEXT PRIMARY KEY,
        application TEXT NOT NULL,
        environment TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        pipeline_config TEXT,
        infrastructure_config TEXT,
        checklist TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS pipelines (
        id TEXT PRIMARY KEY,
        application TEXT NOT NULL,
        type TEXT NOT NULL,
        config TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS infrastructure (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        cloud_provider TEXT NOT NULL,
        terraform_config TEXT,
        manifests TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS incidents (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        severity TEXT NOT NULL,
        runbook TEXT,
        resolution TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );
    `);
  }

  createDeployment(application: string, environment: string): { id: string; created_at: string } {
    const id = `deploy_${nanoid()}`;
    const now = new Date().toISOString();

    const stmt = this.db.prepare(`
      INSERT INTO deployments (id, application, environment, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?)
    `);

    stmt.run(id, application, environment, now, now);
    return { id, created_at: now };
  }

  getDeployment(id: string): any {
    const stmt = this.db.prepare('SELECT * FROM deployments WHERE id = ?');
    return stmt.get(id);
  }

  close(): void {
    this.db.close();
  }
}
