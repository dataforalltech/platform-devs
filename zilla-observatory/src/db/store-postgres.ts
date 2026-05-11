import { nanoid } from 'nanoid';
import * as path from 'path';
import * as fs from 'fs';
import { ZillaPostgresStore } from '../../../platform-service-template/lib/postgres_sync';

// ============================================================================
// Interfaces
// ============================================================================

export interface Metric {
  id: string;
  zilla_name: string;
  metric_type: string;
  metric_value?: number;
  tags?: unknown;
  recorded_at: string;
}

export interface Dashboard {
  id: string;
  name: string;
  config?: unknown;
  created_at: string;
  updated_at: string;
}

export interface Alert {
  id: string;
  name: string;
  condition?: string;
  enabled?: boolean;
  created_at: string;
}

export interface AlertHistory {
  id: string;
  alert_id: string;
  status: string;
  message?: string;
  created_at: string;
}

// ============================================================================
// ZillaObservatoryStore — PostgreSQL Primary
// ============================================================================

export class ZillaObservatoryStore {
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
      this.pg = new ZillaPostgresStore('zilla-observatory', postgresConfig);
      this.logger.info('✅ ZillaObservatoryStore: PostgreSQL initialized');
    } catch (error) {
      this.logger.error(`❌ ZillaObservatoryStore: Failed to initialize: ${error}`);
      throw error;
    }
  }

  private initializeLogger(): any {
    const logsDir = path.join(process.env.HOME || '/tmp', '.platform', 'logs');
    if (!fs.existsSync(logsDir)) {
      fs.mkdirSync(logsDir, { recursive: true });
    }

    const logFile = path.join(logsDir, 'zilla-observatory.log');

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
  // Metrics
  // ============================================================================

  async createMetric(data: Omit<Metric, 'id' | 'recorded_at'>): Promise<Metric> {
    const id = `metric_${nanoid()}`;
    const now = new Date().toISOString();

    await this.pg.execute(
      `INSERT INTO metrics (id, zilla_name, metric_type, metric_value, tags, recorded_at)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [id, data.zilla_name, data.metric_type, data.metric_value, data.tags ? JSON.stringify(data.tags) : null, now]
    );

    return { ...data, id, recorded_at: now };
  }

  async listMetrics(zillaName?: string, metricType?: string): Promise<Metric[]> {
    if (zillaName && metricType) {
      return this.pg.query<Metric>(
        'SELECT * FROM metrics WHERE zilla_name = $1 AND metric_type = $2 ORDER BY recorded_at DESC',
        [zillaName, metricType]
      );
    } else if (zillaName) {
      return this.pg.query<Metric>(
        'SELECT * FROM metrics WHERE zilla_name = $1 ORDER BY recorded_at DESC',
        [zillaName]
      );
    }
    return this.pg.query<Metric>('SELECT * FROM metrics ORDER BY recorded_at DESC', []);
  }

  async getMetricStats(zillaName: string, metricType: string): Promise<{ avg: number; min: number; max: number; count: number } | null> {
    const rows = await this.pg.query<{ avg: number; min: number; max: number; count: number }>(
      'SELECT AVG(metric_value) as avg, MIN(metric_value) as min, MAX(metric_value) as max, COUNT(*) as count FROM metrics WHERE zilla_name = $1 AND metric_type = $2',
      [zillaName, metricType]
    );
    return rows[0] || null;
  }

  // ============================================================================
  // Dashboards (with UPSERT support)
  // ============================================================================

  async createDashboard(data: Omit<Dashboard, 'id' | 'created_at' | 'updated_at'>): Promise<Dashboard> {
    const id = `dash_${nanoid()}`;
    const now = new Date().toISOString();

    await this.pg.execute(
      `INSERT INTO dashboards (id, name, config, created_at, updated_at)
       VALUES ($1, $2, $3, $4, $5)`,
      [id, data.name, data.config ? JSON.stringify(data.config) : null, now, now]
    );

    return { ...data, id, created_at: now, updated_at: now };
  }

  async registerDashboard(data: Omit<Dashboard, 'created_at' | 'updated_at'>): Promise<Dashboard> {
    const now = new Date().toISOString();

    await this.pg.execute(
      `INSERT INTO dashboards (id, name, config, created_at, updated_at)
       VALUES ($1, $2, $3, $4, $5)
       ON CONFLICT (id) DO UPDATE SET name = $2, config = $3, updated_at = $5`,
      [data.id, data.name, data.config ? JSON.stringify(data.config) : null, now, now]
    );

    return { ...data, created_at: now, updated_at: now };
  }

  async listDashboards(): Promise<Dashboard[]> {
    return this.pg.query<Dashboard>('SELECT * FROM dashboards ORDER BY created_at DESC', []);
  }

  async getDashboard(id: string): Promise<Dashboard | null> {
    const rows = await this.pg.query<Dashboard>('SELECT * FROM dashboards WHERE id = $1', [id]);
    return rows[0] || null;
  }

  // ============================================================================
  // Alerts
  // ============================================================================

  async createAlert(data: Omit<Alert, 'id' | 'created_at'>): Promise<Alert> {
    const id = `alert_${nanoid()}`;
    const now = new Date().toISOString();

    await this.pg.execute(
      `INSERT INTO alerts (id, name, condition, enabled, created_at)
       VALUES ($1, $2, $3, $4, $5)`,
      [id, data.name, data.condition, data.enabled !== false, now]
    );

    return { ...data, id, created_at: now };
  }

  async listAlerts(enabled?: boolean): Promise<Alert[]> {
    if (enabled !== undefined) {
      return this.pg.query<Alert>(
        'SELECT * FROM alerts WHERE enabled = $1 ORDER BY created_at DESC',
        [enabled]
      );
    }
    return this.pg.query<Alert>('SELECT * FROM alerts ORDER BY created_at DESC', []);
  }

  async updateAlertStatus(id: string, enabled: boolean): Promise<void> {
    await this.pg.execute('UPDATE alerts SET enabled = $1 WHERE id = $2', [enabled, id]);
  }

  // ============================================================================
  // Alert History
  // ============================================================================

  async createAlertHistory(data: Omit<AlertHistory, 'id' | 'created_at'>): Promise<AlertHistory> {
    const id = `ah_${nanoid()}`;
    const now = new Date().toISOString();

    await this.pg.execute(
      `INSERT INTO alert_history (id, alert_id, status, message, created_at)
       VALUES ($1, $2, $3, $4, $5)`,
      [id, data.alert_id, data.status, data.message, now]
    );

    return { ...data, id, created_at: now };
  }

  async listAlertHistory(alertId?: string): Promise<AlertHistory[]> {
    if (alertId) {
      return this.pg.query<AlertHistory>(
        'SELECT * FROM alert_history WHERE alert_id = $1 ORDER BY created_at DESC',
        [alertId]
      );
    }
    return this.pg.query<AlertHistory>('SELECT * FROM alert_history ORDER BY created_at DESC', []);
  }

  // ============================================================================
  // Cleanup
  // ============================================================================

  async close(): Promise<void> {
    await this.pg.close();
  }
}
