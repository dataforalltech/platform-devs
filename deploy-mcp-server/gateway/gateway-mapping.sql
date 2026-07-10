-- =============================================================================
-- gateway-mapping.sql — registro DECLARATIVO (pull-based) do deploy-mcp no
-- MCP Gateway central (platform-mcp-gateway), REGISTRY_SOURCE=db.
-- Derivado de docs/_templates/mcp-gateway-integration/gateway-mapping.migration.sql.template
-- do platform-service-template. Ver STD-MCP-001 (CI-3) e IT-006.
--
-- INVARIANTE Nº 1 (audiência): o gateway deriva namespace = name_microservice sem o
-- prefixo 'platform-' → 'deploy-mcp', e audience = 'mcp:deploy-mcp'. O PEP do
-- sidecar (MCP_TWIN_AUDIENCE) re-verifica o inner token EXATAMENTE nessa audiência.
-- name_microservice='platform-deploy-mcp' ⇒ audience esperada 'mcp:deploy-mcp'.
-- O gateway NUNCA se auto-registra (nada de push) — ele LÊ esta tabela no boot/refresh.
-- MySQL 8.x (ADMIN_DATAFORALL). Idempotente.
-- =============================================================================

-- (1) Guard de esquema — adiciona as 5 colunas mcp_http só se `kind` ainda não existir
--     (casa com o DDL canônico do platform-admin; no-op se já criadas).
SET @need_mcp_cols := (
  SELECT COUNT(*) = 0 FROM information_schema.columns
  WHERE table_schema = 'ADMIN_DATAFORALL'
    AND table_name  = 'GATEWAY_MAPPING'
    AND column_name = 'kind'
);
SET @ddl_mcp_cols := IF(@need_mcp_cols,
  'ALTER TABLE ADMIN_DATAFORALL.GATEWAY_MAPPING
     ADD COLUMN kind            VARCHAR(32)  NOT NULL DEFAULT ''rest'',
     ADD COLUMN mcp_url         VARCHAR(512)          DEFAULT NULL,
     ADD COLUMN tools_list_path VARCHAR(255)          DEFAULT ''/mcp/tools/list'',
     ADD COLUMN tools_call_path VARCHAR(255)          DEFAULT ''/mcp/tools/call'',
     ADD COLUMN call_style      VARCHAR(16)           DEFAULT ''mcp''',
  'DO 0'
);
PREPARE _mcp_cols_stmt FROM @ddl_mcp_cols;
EXECUTE _mcp_cols_stmt;
DEALLOCATE PREPARE _mcp_cols_stmt;

-- (2) Registro do sidecar mcp_http (idempotente). mcp_url = DNS do container na rede da
--     plataforma (= name_microservice). health_path = /v1/health (sidecar canônico).
INSERT INTO ADMIN_DATAFORALL.GATEWAY_MAPPING
  (name_microservice, internal_url, health_path, timeout_seconds,
   kind, mcp_url, tools_list_path, tools_call_path, call_style)
VALUES
  ('platform-deploy-mcp', NULL, '/v1/health', 30,
   'mcp_http', 'http://platform-deploy-mcp:7100', '/mcp/tools/list', '/mcp/tools/call', 'mcp')
ON DUPLICATE KEY UPDATE
  kind            = VALUES(kind),
  mcp_url         = VALUES(mcp_url),
  tools_list_path = VALUES(tools_list_path),
  tools_call_path = VALUES(tools_call_path),
  call_style      = VALUES(call_style),
  health_path     = VALUES(health_path),
  timeout_seconds = VALUES(timeout_seconds);

-- VERIFICAÇÃO:
--   SELECT name_microservice, kind, mcp_url, call_style, health_path
--     FROM ADMIN_DATAFORALL.GATEWAY_MAPPING WHERE name_microservice='platform-deploy-mcp';
--   -- audiência derivada esperada: mcp:deploy-mcp
