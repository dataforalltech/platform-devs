import Database from 'better-sqlite3';
import { nanoid } from 'nanoid';

export class POZillaStore {
  private db: Database.Database;

  constructor(dbPath?: string) {
    this.db = new Database(dbPath);
    this.db.pragma('journal_mode = WAL');
    this.initializeTables();
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
    return { id, created_at: now };
  }

  getEpic(id: string): any {
    const stmt = this.db.prepare('SELECT * FROM epics WHERE id = ?');
    return stmt.get(id);
  }

  close(): void {
    this.db.close();
  }
}
