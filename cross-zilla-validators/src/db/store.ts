import Database from 'better-sqlite3';
import path from 'path';
import { fileURLToPath } from 'url';
import * as fs from 'fs';
import ZillaPostgresSync from '../../../platform-service-template/lib/postgres_sync';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const dbPath = path.join(__dirname, '../../validators.db');

export class ValidatorStore {
  private db: Database.Database;
  private postgres: ZillaPostgresSync | null = null;
  private logger: any;

  constructor() {
    this.db = new Database(dbPath);
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

        this.postgres = new ZillaPostgresSync('cross-zilla-validators', postgresConfig);
        this.logger.info('✅ ValidatorStore: PostgreSQL sync enabled');
      } catch (error) {
        this.logger.warn(`⚠️  ValidatorStore: PostgreSQL sync disabled: ${error}`);
      }
    }
  }

  private initializeLogger(): any {
    const logsDir = path.join(process.env.HOME || '/tmp', '.platform', 'logs');
    if (!fs.existsSync(logsDir)) {
      fs.mkdirSync(logsDir, { recursive: true });
    }

    const logFile = path.join(logsDir, 'cross-zilla-validators.log');

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
    const now = new Date().toISOString();
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

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'validation_results',
        {
          id,
          validator_name: result.validator_name,
          target_id: result.target_id,
          feature_id: result.feature_id,
          passed: result.passed,
          issues: result.issues,
          created_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync validation result: ${err}`);
      });
    }

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
    const now = new Date().toISOString();
    const stmt = this.db.prepare(`
      INSERT INTO validator_rules (id, validator_name, criteria, severity)
      VALUES (?, ?, ?, ?)
    `);
    stmt.run(id, rule.validator_name, rule.criteria, rule.severity || 'medium');

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'validator_rules',
        {
          id,
          validator_name: rule.validator_name,
          criteria: rule.criteria,
          severity: rule.severity || 'medium',
          created_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync validator rule: ${err}`);
      });
    }

    return id;
  }

  getValidatorRules(validatorName: string): any[] {
    const stmt = this.db.prepare(`
      SELECT * FROM validator_rules WHERE validator_name = ?
    `);
    return stmt.all(validatorName) as any[];
  }

  close(): void {
    if (this.postgres) {
      this.postgres.close();
    }
    this.db.close();
  }
}

export const validatorStore = new ValidatorStore();
