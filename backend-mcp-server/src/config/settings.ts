export interface Settings {
  dbPath: string;
  logLevel: 'debug' | 'info' | 'warn' | 'error';
  environment: 'development' | 'production';
}

export function getSettings(): Settings {
  return {
    dbPath: process.env.BACKEND_DB_PATH || '/tmp/backend.db',
    logLevel: (process.env.BACKEND_LOG_LEVEL || 'info') as Settings['logLevel'],
    environment: (process.env.NODE_ENV || 'development') as Settings['environment'],
  };
}
