import Database from 'better-sqlite3';
import path from 'path';
import { fileURLToPath } from 'url';
import * as fs from 'fs';
import ZillaPostgresSync from '../../../platform-service-template/lib/postgres_sync';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const dbPath = path.join(__dirname, '../../observatory.db');

export class ObservatoryStore {
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

        this.postgres = new ZillaPostgresSync('zilla-observatory', postgresConfig);
        this.logger.info('✅ ObservatoryStore: PostgreSQL sync enabled');
      } catch (error) {
        this.logger.warn(`⚠️  ObservatoryStore: PostgreSQL sync disabled: ${error}`);
      }
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
    // Metrics table
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS metrics (
        id TEXT PRIMARY KEY,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        zilla_name TEXT NOT NULL,
        metric_type TEXT NOT NULL,
        feature_id TEXT,
        values TEXT NOT NULL
      )
    `);

    // Dashboards table
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS dashboards (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        refresh_interval_sec INTEGER DEFAULT 60,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
      )
    `);

    // Alerts table
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS alerts (
        id TEXT PRIMARY KEY,
        condition TEXT NOT NULL,
        threshold REAL NOT NULL,
        notification_channel TEXT,
        enabled BOOLEAN DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
      )
    `);

    // Alert history table
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS alert_history (
        id TEXT PRIMARY KEY,
        alert_id TEXT NOT NULL,
        triggered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        value REAL,
        message TEXT,
        FOREIGN KEY(alert_id) REFERENCES alerts(id)
      )
    `);

    // Indices
    this.db.exec(`
      CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON metrics(timestamp);
      CREATE INDEX IF NOT EXISTS idx_metrics_zilla ON metrics(zilla_name);
      CREATE INDEX IF NOT EXISTS idx_metrics_type ON metrics(metric_type);
      CREATE INDEX IF NOT EXISTS idx_metrics_feature ON metrics(feature_id);
      CREATE INDEX IF NOT EXISTS idx_dashboards_name ON dashboards(name);
      CREATE INDEX IF NOT EXISTS idx_alerts_enabled ON alerts(enabled);
      CREATE INDEX IF NOT EXISTS idx_alert_history_alert ON alert_history(alert_id);
    `);
  }

  recordMetric(metric: {
    zilla_name: string;
    metric_type: string;
    feature_id?: string;
    values: Record<string, unknown>;
  }): string {
    const id = `metric_${Date.now()}`;
    const now = new Date().toISOString();
    const stmt = this.db.prepare(`
      INSERT INTO metrics (id, zilla_name, metric_type, feature_id, values)
      VALUES (?, ?, ?, ?, ?)
    `);
    stmt.run(id, metric.zilla_name, metric.metric_type, metric.feature_id || null, JSON.stringify(metric.values));

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'metrics',
        {
          id,
          zilla_name: metric.zilla_name,
          metric_type: metric.metric_type,
          feature_id: metric.feature_id,
          values: JSON.stringify(metric.values),
          timestamp: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync metric: ${err}`);
      });
    }

    return id;
  }

  getMetrics(zillaName?: string, metricType?: string, limit: number = 100): any[] {
    let stmt;
    if (zillaName && metricType) {
      stmt = this.db.prepare(`
        SELECT * FROM metrics
        WHERE zilla_name = ? AND metric_type = ?
        ORDER BY timestamp DESC LIMIT ?
      `);
      return stmt.all(zillaName, metricType, limit) as any[];
    } else if (zillaName) {
      stmt = this.db.prepare(`
        SELECT * FROM metrics
        WHERE zilla_name = ?
        ORDER BY timestamp DESC LIMIT ?
      `);
      return stmt.all(zillaName, limit) as any[];
    } else {
      stmt = this.db.prepare(`
        SELECT * FROM metrics
        ORDER BY timestamp DESC LIMIT ?
      `);
      return stmt.all(limit) as any[];
    }
  }

  registerDashboard(dashboard: {
    id: string;
    name: string;
    description?: string;
    refresh_interval_sec?: number;
  }): string {
    const now = new Date().toISOString();
    const stmt = this.db.prepare(`
      INSERT OR REPLACE INTO dashboards (id, name, description, refresh_interval_sec)
      VALUES (?, ?, ?, ?)
    `);
    stmt.run(dashboard.id, dashboard.name, dashboard.description || null, dashboard.refresh_interval_sec || 60);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'dashboards',
        {
          id: dashboard.id,
          name: dashboard.name,
          description: dashboard.description,
          refresh_interval_sec: dashboard.refresh_interval_sec || 60,
          created_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync dashboard: ${err}`);
      });
    }

    return dashboard.id;
  }

  getDashboard(id: string): any {
    const stmt = this.db.prepare('SELECT * FROM dashboards WHERE id = ?');
    return stmt.get(id) as any;
  }

  listDashboards(): any[] {
    const stmt = this.db.prepare('SELECT * FROM dashboards ORDER BY created_at DESC');
    return stmt.all() as any[];
  }

  addAlert(alert: {
    condition: string;
    threshold: number;
    notification_channel?: string;
  }): string {
    const id = `alert_${Date.now()}`;
    const now = new Date().toISOString();
    const stmt = this.db.prepare(`
      INSERT INTO alerts (id, condition, threshold, notification_channel)
      VALUES (?, ?, ?, ?)
    `);
    stmt.run(id, alert.condition, alert.threshold, alert.notification_channel || null);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'alerts',
        {
          id,
          condition: alert.condition,
          threshold: alert.threshold,
          notification_channel: alert.notification_channel,
          enabled: true,
          created_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync alert: ${err}`);
      });
    }

    return id;
  }

  recordAlertTriggered(alertId: string, value: number, message: string): string {
    const historyId = `hist_${Date.now()}`;
    const now = new Date().toISOString();
    const stmt = this.db.prepare(`
      INSERT INTO alert_history (id, alert_id, value, message)
      VALUES (?, ?, ?, ?)
    `);
    stmt.run(historyId, alertId, value, message);

    // PostgreSQL write (SECONDARY)
    if (this.postgres) {
      this.postgres.sync(
        'alert_history',
        {
          id: historyId,
          alert_id: alertId,
          value,
          message,
          triggered_at: now,
        },
        'create'
      ).catch((err) => {
        this.logger.warn(`Failed to sync alert history: ${err}`);
      });
    }

    return historyId;
  }

  getAlerts(enabled?: boolean): any[] {
    let stmt;
    if (enabled !== undefined) {
      stmt = this.db.prepare('SELECT * FROM alerts WHERE enabled = ?');
      return stmt.all(enabled ? 1 : 0) as any[];
    } else {
      stmt = this.db.prepare('SELECT * FROM alerts');
      return stmt.all() as any[];
    }
  }

  getAlertHistory(alertId: string, limit: number = 50): any[] {
    const stmt = this.db.prepare(`
      SELECT * FROM alert_history
      WHERE alert_id = ?
      ORDER BY triggered_at DESC LIMIT ?
    `);
    return stmt.all(alertId, limit) as any[];
  }

  getEcosystemStats(): any {
    const totalMetrics = (this.db.prepare('SELECT COUNT(*) as count FROM metrics').get() as any).count;
    const totalDashboards = (this.db.prepare('SELECT COUNT(*) as count FROM dashboards').get() as any).count;
    const activeAlerts = (this.db.prepare('SELECT COUNT(*) as count FROM alerts WHERE enabled = 1').get() as any)
      .count;

    return {
      total_metrics: totalMetrics,
      total_dashboards: totalDashboards,
      active_alerts: activeAlerts,
    };
  }

  close(): void {
    if (this.postgres) {
      this.postgres.close();
    }
    this.db.close();
  }
}

export const observatoryStore = new ObservatoryStore();
