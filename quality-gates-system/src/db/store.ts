import Database from 'better-sqlite3';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const dbPath = path.join(__dirname, '../../gates.db');

export class GatesStore {
  private db: Database.Database;

  constructor() {
    this.db = new Database(dbPath);
    this.initializeTables();
  }

  private initializeTables(): void {
    // Gates table
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS gates (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        enabled BOOLEAN DEFAULT 1,
        blocking BOOLEAN DEFAULT 0,
        timeout_hours INTEGER DEFAULT 24,
        auto_retry BOOLEAN DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
      )
    `);

    // Gate results table
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS gate_results (
        id TEXT PRIMARY KEY,
        gate_id TEXT NOT NULL,
        feature_id TEXT,
        passed BOOLEAN NOT NULL,
        criteria_status TEXT,
        failure_reason TEXT,
        evaluated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(gate_id) REFERENCES gates(id)
      )
    `);

    // Gate history table
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS gate_history (
        id TEXT PRIMARY KEY,
        gate_id TEXT NOT NULL,
        feature_id TEXT,
        passed BOOLEAN NOT NULL,
        status_changed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(gate_id) REFERENCES gates(id)
      )
    `);

    // Indices
    this.db.exec(`
      CREATE INDEX IF NOT EXISTS idx_gates_type ON gates(type);
      CREATE INDEX IF NOT EXISTS idx_gates_enabled ON gates(enabled);
      CREATE INDEX IF NOT EXISTS idx_results_gate ON gate_results(gate_id);
      CREATE INDEX IF NOT EXISTS idx_results_feature ON gate_results(feature_id);
      CREATE INDEX IF NOT EXISTS idx_history_gate ON gate_history(gate_id);
      CREATE INDEX IF NOT EXISTS idx_history_feature ON gate_history(feature_id);
    `);
  }

  registerGate(gate: {
    id: string;
    name: string;
    type: string;
    blocking?: boolean;
    timeout_hours?: number;
  }): string {
    const stmt = this.db.prepare(`
      INSERT OR REPLACE INTO gates (id, name, type, blocking, timeout_hours)
      VALUES (?, ?, ?, ?, ?)
    `);
    stmt.run(gate.id, gate.name, gate.type, gate.blocking ? 1 : 0, gate.timeout_hours || 24);
    return gate.id;
  }

  evaluateGate(gateId: string, featureId: string, passed: boolean, reason?: string): string {
    const resultId = `result_${Date.now()}`;
    const stmt = this.db.prepare(`
      INSERT INTO gate_results (id, gate_id, feature_id, passed, failure_reason)
      VALUES (?, ?, ?, ?, ?)
    `);
    stmt.run(resultId, gateId, featureId, passed ? 1 : 0, reason || null);

    // Record in history
    const historyId = `hist_${Date.now()}`;
    const histStmt = this.db.prepare(`
      INSERT INTO gate_history (id, gate_id, feature_id, passed)
      VALUES (?, ?, ?, ?)
    `);
    histStmt.run(historyId, gateId, featureId, passed ? 1 : 0);

    return resultId;
  }

  getGateStatus(gateId: string): any {
    const gate = this.db.prepare('SELECT * FROM gates WHERE id = ?').get(gateId);
    const latestResult = this.db
      .prepare('SELECT * FROM gate_results WHERE gate_id = ? ORDER BY evaluated_at DESC LIMIT 1')
      .get(gateId);

    return {
      gate,
      latest_result: latestResult,
    };
  }

  listGates(type?: string): any[] {
    let stmt;
    if (type) {
      stmt = this.db.prepare('SELECT * FROM gates WHERE type = ? AND enabled = 1');
      return stmt.all(type) as any[];
    } else {
      stmt = this.db.prepare('SELECT * FROM gates WHERE enabled = 1');
      return stmt.all() as any[];
    }
  }

  getGateResults(gateId: string, limit: number = 50): any[] {
    const stmt = this.db.prepare(`
      SELECT * FROM gate_results
      WHERE gate_id = ?
      ORDER BY evaluated_at DESC
      LIMIT ?
    `);
    return stmt.all(gateId, limit) as any[];
  }

  getGateHistory(gateId: string, limit: number = 100): any[] {
    const stmt = this.db.prepare(`
      SELECT * FROM gate_history
      WHERE gate_id = ?
      ORDER BY status_changed_at DESC
      LIMIT ?
    `);
    return stmt.all(gateId, limit) as any[];
  }

  getGatesStatistics(): any {
    const stmt = this.db.prepare(`
      SELECT
        g.type,
        COUNT(g.id) as total_gates,
        SUM(CASE WHEN g.enabled = 1 THEN 1 ELSE 0 END) as enabled_gates,
        SUM(CASE WHEN g.blocking = 1 THEN 1 ELSE 0 END) as blocking_gates
      FROM gates g
      GROUP BY g.type
    `);
    return stmt.all() as any[];
  }

  close(): void {
    this.db.close();
  }
}

export const gatesStore = new GatesStore();
