import Database from 'better-sqlite3';
import { generateId } from '../utils/validators.js';

export interface Feature {
  id: string;
  name: string;
  raw_req: string;
  analysis: Record<string, unknown>;
  spec?: Record<string, unknown>;
  status: 'draft' | 'analysis' | 'designed' | 'developed' | 'completed';
  created_at: string;
  updated_at: string;
}

export interface Component {
  id: string;
  feature_id?: string;
  name: string;
  category: 'atom' | 'molecule' | 'organism' | 'template' | 'page';
  agent: 'frontzilla' | 'pixelfera' | 'shared';
  spec: Record<string, unknown>;
  doc?: string;
  story?: string;
  created_at: string;
  updated_at: string;
}

export interface DesignToken {
  id: string;
  feature_id?: string;
  name: string;
  tokens: Record<string, unknown>;
  format: 'css-vars' | 'tailwind' | 'js-object';
  created_at: string;
}

export interface Workflow {
  id: string;
  feature_id: string;
  status: 'running' | 'completed' | 'failed';
  result?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export class FrontzillaPixelferaStore {
  private db: Database.Database;

  constructor(dbPath: string = '.frontzilla-pixelfera.db') {
    this.db = new Database(dbPath);
    this.db.pragma('journal_mode = WAL');
    this.initDb();
  }

  private initDb(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS features (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        raw_req TEXT NOT NULL,
        analysis TEXT NOT NULL,
        spec TEXT,
        status TEXT NOT NULL DEFAULT 'draft',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS components (
        id TEXT PRIMARY KEY,
        feature_id TEXT,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        agent TEXT NOT NULL,
        spec TEXT NOT NULL,
        doc TEXT,
        story TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(feature_id) REFERENCES features(id)
      );

      CREATE TABLE IF NOT EXISTS design_tokens (
        id TEXT PRIMARY KEY,
        feature_id TEXT,
        name TEXT NOT NULL,
        tokens TEXT NOT NULL,
        format TEXT NOT NULL DEFAULT 'css-vars',
        created_at TEXT NOT NULL,
        FOREIGN KEY(feature_id) REFERENCES features(id)
      );

      CREATE TABLE IF NOT EXISTS workflows (
        id TEXT PRIMARY KEY,
        feature_id TEXT NOT NULL,
        status TEXT NOT NULL,
        result TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(feature_id) REFERENCES features(id)
      );

      CREATE INDEX IF NOT EXISTS idx_features_status ON features(status);
      CREATE INDEX IF NOT EXISTS idx_components_feature ON components(feature_id);
      CREATE INDEX IF NOT EXISTS idx_components_agent ON components(agent);
      CREATE INDEX IF NOT EXISTS idx_design_tokens_feature ON design_tokens(feature_id);
      CREATE INDEX IF NOT EXISTS idx_workflows_feature ON workflows(feature_id);
    `);
  }

  // ─── Features ───────────────────────────────────────────────────────────── //

  createFeature(
    name: string,
    raw_req: string,
    analysis: Record<string, unknown>
  ): Feature {
    const id = generateId('feat');
    const now = new Date().toISOString();

    const stmt = this.db.prepare(`
      INSERT INTO features (id, name, raw_req, analysis, status, created_at, updated_at)
      VALUES (?, ?, ?, ?, 'draft', ?, ?)
    `);

    stmt.run(id, name, raw_req, JSON.stringify(analysis), now, now);
    return { id, name, raw_req, analysis, status: 'draft', created_at: now, updated_at: now };
  }

  getFeature(id: string): Feature | null {
    const stmt = this.db.prepare('SELECT * FROM features WHERE id = ?');
    const row = stmt.get(id) as Record<string, unknown> | undefined;
    return row ? this.parseFeature(row) : null;
  }

  listFeatures(status?: string, limit: number = 50, offset: number = 0): Feature[] {
    let query = 'SELECT * FROM features WHERE 1=1';
    const params: unknown[] = [];

    if (status) {
      query += ' AND status = ?';
      params.push(status);
    }

    query += ' ORDER BY created_at DESC LIMIT ? OFFSET ?';
    params.push(limit, offset);

    const stmt = this.db.prepare(query);
    const rows = stmt.all(...params) as Record<string, unknown>[];
    return rows.map((row) => this.parseFeature(row));
  }

  updateFeatureStatus(id: string, status: string, spec?: Record<string, unknown>): void {
    const now = new Date().toISOString();
    const stmt = this.db.prepare(`
      UPDATE features SET status = ?, spec = ?, updated_at = ? WHERE id = ?
    `);
    stmt.run(status, spec ? JSON.stringify(spec) : null, now, id);
  }

  // ─── Components ──────────────────────────────────────────────────────────── //

  createComponent(
    name: string,
    category: string,
    agent: string,
    spec: Record<string, unknown>,
    feature_id?: string
  ): Component {
    const id = generateId('comp');
    const now = new Date().toISOString();

    const stmt = this.db.prepare(`
      INSERT INTO components (id, feature_id, name, category, agent, spec, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `);

    stmt.run(id, feature_id || null, name, category, agent, JSON.stringify(spec), now, now);
    return {
      id,
      feature_id,
      name,
      category: category as Component['category'],
      agent: agent as Component['agent'],
      spec,
      created_at: now,
      updated_at: now,
    };
  }

  getComponent(id: string): Component | null {
    const stmt = this.db.prepare('SELECT * FROM components WHERE id = ?');
    const row = stmt.get(id) as Record<string, unknown> | undefined;
    return row ? this.parseComponent(row) : null;
  }

  listComponents(feature_id?: string, agent?: string, limit: number = 50): Component[] {
    let query = 'SELECT * FROM components WHERE 1=1';
    const params: unknown[] = [];

    if (feature_id) {
      query += ' AND feature_id = ?';
      params.push(feature_id);
    }
    if (agent) {
      query += ' AND agent = ?';
      params.push(agent);
    }

    query += ' ORDER BY created_at DESC LIMIT ?';
    params.push(limit);

    const stmt = this.db.prepare(query);
    const rows = stmt.all(...params) as Record<string, unknown>[];
    return rows.map((row) => this.parseComponent(row));
  }

  updateComponent(id: string, updates: Partial<Component>): void {
    const now = new Date().toISOString();
    const fields: string[] = [];
    const values: unknown[] = [];

    if (updates.doc !== undefined) {
      fields.push('doc = ?');
      values.push(updates.doc);
    }
    if (updates.story !== undefined) {
      fields.push('story = ?');
      values.push(updates.story);
    }
    if (updates.spec !== undefined) {
      fields.push('spec = ?');
      values.push(JSON.stringify(updates.spec));
    }

    if (fields.length === 0) return;

    fields.push('updated_at = ?');
    values.push(now);
    values.push(id);

    const query = `UPDATE components SET ${fields.join(', ')} WHERE id = ?`;
    const stmt = this.db.prepare(query);
    stmt.run(...values);
  }

  // ─── Design Tokens ──────────────────────────────────────────────────────── //

  createDesignTokens(
    name: string,
    tokens: Record<string, unknown>,
    format: string = 'css-vars',
    feature_id?: string
  ): DesignToken {
    const id = generateId('tok');
    const now = new Date().toISOString();

    const stmt = this.db.prepare(`
      INSERT INTO design_tokens (id, feature_id, name, tokens, format, created_at)
      VALUES (?, ?, ?, ?, ?, ?)
    `);

    stmt.run(id, feature_id || null, name, JSON.stringify(tokens), format, now);
    return {
      id,
      feature_id,
      name,
      tokens,
      format: format as DesignToken['format'],
      created_at: now,
    };
  }

  getDesignTokens(id: string): DesignToken | null {
    const stmt = this.db.prepare('SELECT * FROM design_tokens WHERE id = ?');
    const row = stmt.get(id) as Record<string, unknown> | undefined;
    return row ? this.parseDesignToken(row) : null;
  }

  listDesignTokensByFeature(feature_id: string): DesignToken[] {
    const stmt = this.db.prepare('SELECT * FROM design_tokens WHERE feature_id = ? ORDER BY created_at DESC');
    const rows = stmt.all(feature_id) as Record<string, unknown>[];
    return rows.map((row) => this.parseDesignToken(row));
  }

  // ─── Workflows ──────────────────────────────────────────────────────────── //

  createWorkflow(feature_id: string): Workflow {
    const id = generateId('wf');
    const now = new Date().toISOString();

    const stmt = this.db.prepare(`
      INSERT INTO workflows (id, feature_id, status, created_at, updated_at)
      VALUES (?, ?, 'running', ?, ?)
    `);

    stmt.run(id, feature_id, now, now);
    return {
      id,
      feature_id,
      status: 'running',
      created_at: now,
      updated_at: now,
    };
  }

  getWorkflow(id: string): Workflow | null {
    const stmt = this.db.prepare('SELECT * FROM workflows WHERE id = ?');
    const row = stmt.get(id) as Record<string, unknown> | undefined;
    return row ? this.parseWorkflow(row) : null;
  }

  completeWorkflow(id: string, status: string, result: Record<string, unknown>): void {
    const now = new Date().toISOString();
    const stmt = this.db.prepare(`
      UPDATE workflows SET status = ?, result = ?, updated_at = ? WHERE id = ?
    `);
    stmt.run(status, JSON.stringify(result), now, id);
  }

  // ─── Parsing helpers ────────────────────────────────────────────────────── //

  private parseFeature(row: Record<string, unknown>): Feature {
    return {
      id: row.id as string,
      name: row.name as string,
      raw_req: row.raw_req as string,
      analysis: JSON.parse(row.analysis as string),
      spec: row.spec ? JSON.parse(row.spec as string) : undefined,
      status: row.status as Feature['status'],
      created_at: row.created_at as string,
      updated_at: row.updated_at as string,
    };
  }

  private parseComponent(row: Record<string, unknown>): Component {
    return {
      id: row.id as string,
      feature_id: row.feature_id as string | undefined,
      name: row.name as string,
      category: row.category as Component['category'],
      agent: row.agent as Component['agent'],
      spec: JSON.parse(row.spec as string),
      doc: row.doc as string | undefined,
      story: row.story as string | undefined,
      created_at: row.created_at as string,
      updated_at: row.updated_at as string,
    };
  }

  private parseDesignToken(row: Record<string, unknown>): DesignToken {
    return {
      id: row.id as string,
      feature_id: row.feature_id as string | undefined,
      name: row.name as string,
      tokens: JSON.parse(row.tokens as string),
      format: row.format as DesignToken['format'],
      created_at: row.created_at as string,
    };
  }

  private parseWorkflow(row: Record<string, unknown>): Workflow {
    return {
      id: row.id as string,
      feature_id: row.feature_id as string,
      status: row.status as Workflow['status'],
      result: row.result ? JSON.parse(row.result as string) : undefined,
      created_at: row.created_at as string,
      updated_at: row.updated_at as string,
    };
  }

  close(): void {
    this.db.close();
  }
}
