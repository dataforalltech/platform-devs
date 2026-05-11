import Database from 'better-sqlite3';
import { nanoid } from 'nanoid';

export class ArchZillaStore {
  private db: Database.Database;

  constructor(dbPath?: string) {
    this.db = new Database(dbPath);
    this.db.pragma('journal_mode = WAL');
    this.initializeTables();
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
    return { id, created_at: now };
  }

  getArchitecture(id: string): any {
    const stmt = this.db.prepare('SELECT * FROM architectures WHERE id = ?');
    return stmt.get(id);
  }

  close(): void {
    this.db.close();
  }
}
