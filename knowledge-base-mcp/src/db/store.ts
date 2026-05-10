import Database from 'better-sqlite3';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const dbPath = path.join(__dirname, '../../knowledge-base.db');

export class KnowledgeBaseStore {
  private db: Database.Database;

  constructor() {
    this.db = new Database(dbPath);
    this.initializeTables();
  }

  private initializeTables(): void {
    // Documents table
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY,
        path TEXT NOT NULL,
        domain TEXT NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        version INTEGER DEFAULT 1,
        status TEXT DEFAULT 'active',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
      )
    `);

    // Standards table
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS standards (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        domain TEXT NOT NULL,
        criteria TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
      )
    `);

    // Subscriptions table
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS subscriptions (
        id TEXT PRIMARY KEY,
        domain TEXT NOT NULL,
        callback_url TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
      )
    `);

    // Indices
    this.db.exec(`
      CREATE INDEX IF NOT EXISTS idx_documents_domain ON documents(domain);
      CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
      CREATE INDEX IF NOT EXISTS idx_standards_domain ON standards(domain);
      CREATE INDEX IF NOT EXISTS idx_subscriptions_domain ON subscriptions(domain);
    `);
  }

  indexDocument(doc: {
    id: string;
    path: string;
    domain: string;
    title: string;
    content: string;
  }): void {
    const stmt = this.db.prepare(`
      INSERT OR REPLACE INTO documents (id, path, domain, title, content)
      VALUES (?, ?, ?, ?, ?)
    `);
    stmt.run(doc.id, doc.path, doc.domain, doc.title, doc.content);
  }

  searchDocuments(query: string, limit: number = 10): any[] {
    const stmt = this.db.prepare(`
      SELECT * FROM documents
      WHERE status = 'active' AND (title LIKE ? OR content LIKE ?)
      LIMIT ?
    `);
    const searchTerm = `%${query}%`;
    return stmt.all(searchTerm, searchTerm, limit) as any[];
  }

  getDocument(id: string): any {
    const stmt = this.db.prepare('SELECT * FROM documents WHERE id = ?');
    return stmt.get(id) as any;
  }

  listDocuments(domain?: string, limit: number = 100): any[] {
    let stmt;
    if (domain) {
      stmt = this.db.prepare(`
        SELECT * FROM documents
        WHERE status = 'active' AND domain = ?
        ORDER BY updated_at DESC LIMIT ?
      `);
      return stmt.all(domain, limit) as any[];
    } else {
      stmt = this.db.prepare(`
        SELECT * FROM documents
        WHERE status = 'active'
        ORDER BY updated_at DESC LIMIT ?
      `);
      return stmt.all(limit) as any[];
    }
  }

  validateAgainstStandard(documentId: string, standardId: string): any {
    const doc = this.getDocument(documentId);
    const standard = this.db.prepare('SELECT * FROM standards WHERE id = ?').get(standardId);

    if (!doc || !standard) {
      return { valid: false, errors: ['Document or standard not found'] };
    }

    return {
      valid: true,
      documentId,
      standardId,
      timestamp: new Date().toISOString(),
    };
  }

  addSubscription(domain: string, callbackUrl: string): string {
    const id = `sub_${Date.now()}`;
    const stmt = this.db.prepare(`
      INSERT INTO subscriptions (id, domain, callback_url)
      VALUES (?, ?, ?)
    `);
    stmt.run(id, domain, callbackUrl);
    return id;
  }

  getSubscriptions(domain: string): any[] {
    const stmt = this.db.prepare('SELECT * FROM subscriptions WHERE domain = ?');
    return stmt.all(domain) as any[];
  }

  close(): void {
    this.db.close();
  }
}

export const knowledgeBaseStore = new KnowledgeBaseStore();
