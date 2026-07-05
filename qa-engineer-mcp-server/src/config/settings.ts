export interface Settings {
  dbPath: string;
  logLevel: 'debug' | 'info' | 'warn' | 'error';
  environment: 'development' | 'production';
}

export function getSettings(): Settings {
  return {
    dbPath: process.env.QA_ENGINEER_DB_PATH || '/tmp/qa-engineer.db',
    logLevel: (process.env.QA_ENGINEER_LOG_LEVEL || 'info') as Settings['logLevel'],
    environment: (process.env.NODE_ENV || 'development') as Settings['environment'],
  };
}
