export interface Settings {
  dbPath: string;
  logLevel: 'debug' | 'info' | 'warn' | 'error';
  environment: 'development' | 'production';
}

export function getSettings(): Settings {
  return {
    dbPath: process.env.BACKZILLA_DB_PATH || '/tmp/backzilla.db',
    logLevel: (process.env.BACKZILLA_LOG_LEVEL || 'info') as Settings['logLevel'],
    environment: (process.env.NODE_ENV || 'development') as Settings['environment'],
  };
}
