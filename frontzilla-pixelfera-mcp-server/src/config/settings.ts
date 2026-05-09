export interface Settings {
  dbPath: string;
  environment: 'development' | 'production' | 'test';
  logLevel: 'debug' | 'info' | 'warn' | 'error';
}

export function getSettings(): Settings {
  const env = process.env.NODE_ENV || 'development';
  const dbPath = process.env.DB_PATH || '.frontzilla-pixelfera.db';
  const logLevel = (process.env.LOG_LEVEL || 'info') as Settings['logLevel'];

  const settings: Settings = {
    dbPath,
    environment: env as 'development' | 'production' | 'test',
    logLevel,
  };

  return settings;
}
