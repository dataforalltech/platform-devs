import Database from 'better-sqlite3';
import { nanoid } from 'nanoid';

export class ProductZillaStore {
  private db: Database.Database;

  constructor(dbPath?: string) {
    this.db = new Database(dbPath);
    this.db.pragma('journal_mode = WAL');
    this.initializeTables();
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
    return { id, created_at: now };
  }

  getFeature(id: string): any {
    const stmt = this.db.prepare('SELECT * FROM features WHERE id = ?');
    return stmt.get(id);
  }

  close(): void {
    this.db.close();
  }
}
