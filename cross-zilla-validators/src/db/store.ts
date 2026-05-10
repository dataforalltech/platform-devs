import Database from 'better-sqlite3';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const dbPath = path.join(__dirname, '../../validators.db');

export class ValidatorStore {
  private db: Database.Database;

  constructor() {
    this.db = new Database(dbPath);
    this.initializeTables();
  }

  private initializeTables(): void {
    // Validation results table
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS validation_results (
        id TEXT PRIMARY KEY,
        validator_name TEXT NOT NULL,
        target_id TEXT NOT NULL,
        feature_id TEXT,
        passed BOOLEAN NOT NULL,
        issues TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
      )
    `);

    // Validator rules table
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS validator_rules (
        id TEXT PRIMARY KEY,
        validator_name TEXT NOT NULL,
        criteria TEXT NOT NULL,
        severity TEXT DEFAULT 'medium',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
      )
    `);

    // Indices
    this.db.exec(`
      CREATE INDEX IF NOT EXISTS idx_validation_validator ON validation_results(validator_name);
      CREATE INDEX IF NOT EXISTS idx_validation_feature ON validation_results(feature_id);
      CREATE INDEX IF NOT EXISTS idx_rules_validator ON validator_rules(validator_name);
    `);
  }

  recordValidationResult(result: {
    validator_name: string;
    target_id: string;
    feature_id?: string;
    passed: boolean;
    issues?: string;
  }): string {
    const id = `val_${Date.now()}`;
    const stmt = this.db.prepare(`
      INSERT INTO validation_results (id, validator_name, target_id, feature_id, passed, issues)
      VALUES (?, ?, ?, ?, ?, ?)
    `);
    stmt.run(
      id,
      result.validator_name,
      result.target_id,
      result.feature_id,
      result.passed ? 1 : 0,
      result.issues || null
    );
    return id;
  }

  getValidationResult(id: string): any {
    const stmt = this.db.prepare('SELECT * FROM validation_results WHERE id = ?');
    return stmt.get(id) as any;
  }

  listValidationResults(validatorName?: string, limit: number = 100): any[] {
    let stmt;
    if (validatorName) {
      stmt = this.db.prepare(`
        SELECT * FROM validation_results
        WHERE validator_name = ?
        ORDER BY created_at DESC LIMIT ?
      `);
      return stmt.all(validatorName, limit) as any[];
    } else {
      stmt = this.db.prepare(`
        SELECT * FROM validation_results
        ORDER BY created_at DESC LIMIT ?
      `);
      return stmt.all(limit) as any[];
    }
  }

  getValidationStatistics(): any {
    const stmt = this.db.prepare(`
      SELECT
        validator_name,
        COUNT(*) as total,
        SUM(CASE WHEN passed = 1 THEN 1 ELSE 0 END) as passed,
        SUM(CASE WHEN passed = 0 THEN 1 ELSE 0 END) as failed
      FROM validation_results
      GROUP BY validator_name
    `);
    return stmt.all() as any[];
  }

  addValidatorRule(rule: {
    validator_name: string;
    criteria: string;
    severity?: string;
  }): string {
    const id = `rule_${Date.now()}`;
    const stmt = this.db.prepare(`
      INSERT INTO validator_rules (id, validator_name, criteria, severity)
      VALUES (?, ?, ?, ?)
    `);
    stmt.run(id, rule.validator_name, rule.criteria, rule.severity || 'medium');
    return id;
  }

  getValidatorRules(validatorName: string): any[] {
    const stmt = this.db.prepare(`
      SELECT * FROM validator_rules WHERE validator_name = ?
    `);
    return stmt.all(validatorName) as any[];
  }

  close(): void {
    this.db.close();
  }
}

export const validatorStore = new ValidatorStore();
