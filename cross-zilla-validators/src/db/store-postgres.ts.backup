import { nanoid } from 'nanoid';
import * as path from 'path';
import * as fs from 'fs';
import { ZillaPostgresStore } from '../../../platform-service-template/lib/postgres_sync';

// ============================================================================
// Interfaces
// ============================================================================

export interface ValidationResult {
  id: string;
  validator_name: string;
  target_id?: string;
  target_type?: string;
  result_status: string;
  details?: unknown;
  created_at: string;
}

export interface ValidatorRule {
  id: string;
  validator_name: string;
  rule_name: string;
  description?: string;
  severity?: string;
  created_at: string;
}

// ============================================================================
// CrossZillaValidatorsStore — PostgreSQL Primary
// ============================================================================

export class CrossZillaValidatorsStore {
  private pg: ZillaPostgresStore;
  private logger: any;

  constructor() {
    const postgresConfig = {
      host: process.env.POSTGRES_HOST || 'claude-dev',
      port: parseInt(process.env.POSTGRES_PORT || '5432', 10),
      user: process.env.POSTGRES_USER || 'postgres',
      password: process.env.POSTGRES_PASSWORD || 'postgres_password_local_dev',
      database: process.env.POSTGRES_DB || 'app',
    };

    this.logger = this.initializeLogger();

    try {
      this.pg = new ZillaPostgresStore('cross-zilla-validators', postgresConfig);
      this.logger.info('✅ CrossZillaValidatorsStore: PostgreSQL initialized');
    } catch (error) {
      this.logger.error(`❌ CrossZillaValidatorsStore: Failed to initialize: ${error}`);
      throw error;
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
      error: (msg: string) => {
        const timestamp = new Date().toISOString();
        console.error(`[${timestamp}] ❌ ${msg}`);
        fs.appendFileSync(logFile, `[${timestamp}] ERROR: ${msg}\n`);
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

  // ============================================================================
  // Validation Results
  // ============================================================================

  async createValidationResult(data: Omit<ValidationResult, 'id' | 'created_at'>): Promise<ValidationResult> {
    const id = `vr_${nanoid()}`;
    const now = new Date().toISOString();

    await this.pg.execute(
      `INSERT INTO validation_results (id, validator_name, target_id, target_type, result_status, details, created_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7)`,
      [id, data.validator_name, data.target_id, data.target_type, data.result_status, JSON.stringify(data.details), now]
    );

    return { ...data, id, created_at: now };
  }

  async listValidationResults(validatorName?: string): Promise<ValidationResult[]> {
    if (validatorName) {
      return this.pg.query<ValidationResult>(
        'SELECT * FROM validation_results WHERE validator_name = $1 ORDER BY created_at DESC',
        [validatorName]
      );
    }
    return this.pg.query<ValidationResult>('SELECT * FROM validation_results ORDER BY created_at DESC', []);
  }

  async getValidationStatistics(validatorName?: string): Promise<{ validator: string; count: number }[]> {
    if (validatorName) {
      const result = await this.pg.query<{ validator_name: string; count: number }>(
        'SELECT validator_name as validator, COUNT(*) as count FROM validation_results WHERE validator_name = $1 GROUP BY validator_name',
        [validatorName]
      );
      return result;
    }
    const result = await this.pg.query<{ validator_name: string; count: number }>(
      'SELECT validator_name as validator, COUNT(*) as count FROM validation_results GROUP BY validator_name',
      []
    );
    return result;
  }

  // ============================================================================
  // Validator Rules
  // ============================================================================

  async createValidatorRule(data: Omit<ValidatorRule, 'id' | 'created_at'>): Promise<ValidatorRule> {
    const id = `rule_${nanoid()}`;
    const now = new Date().toISOString();

    await this.pg.execute(
      `INSERT INTO validator_rules (id, validator_name, rule_name, description, severity, created_at)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [id, data.validator_name, data.rule_name, data.description, data.severity, now]
    );

    return { ...data, id, created_at: now };
  }

  async listValidatorRules(validatorName?: string): Promise<ValidatorRule[]> {
    if (validatorName) {
      return this.pg.query<ValidatorRule>(
        'SELECT * FROM validator_rules WHERE validator_name = $1 ORDER BY created_at DESC',
        [validatorName]
      );
    }
    return this.pg.query<ValidatorRule>('SELECT * FROM validator_rules ORDER BY created_at DESC', []);
  }

  // ============================================================================
  // Cleanup
  // ============================================================================

  async close(): Promise<void> {
    await this.pg.close();
  }
}
