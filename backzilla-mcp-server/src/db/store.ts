import Database from 'better-sqlite3';
import { nanoid } from 'nanoid';

export class BackzillaStore {
  private db: Database.Database;

  constructor(dbPath: string) {
    this.db = new Database(dbPath);
    this.db.pragma('journal_mode = WAL');
    this.initializeTables();
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

    const stmt = this.db.prepare(`
      INSERT INTO apis (id, name, requirement, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?)
    `);

    stmt.run(id, name, requirement, now, now);
    return { id, created_at: now };
  }

  getAPI(id: string): any {
    const stmt = this.db.prepare('SELECT * FROM apis WHERE id = ?');
    return stmt.get(id);
  }

  close(): void {
    this.db.close();
  }
}
