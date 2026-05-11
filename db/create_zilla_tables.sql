-- PostgreSQL DDL for Zilla MCPs
-- Created: 2026-05-11
-- Schema: public (shared with central platform)
-- All tables use TIMESTAMPTZ for timezone-aware timestamps

-- ============================================================================
-- QAZilla Tables
-- ============================================================================

CREATE TABLE IF NOT EXISTS test_plans (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  feature TEXT,
  scope TEXT,
  objectives TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS test_cases (
  id TEXT PRIMARY KEY,
  plan_id TEXT REFERENCES test_plans(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  type TEXT,
  steps TEXT,
  expected_result TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS test_scenarios (
  id TEXT PRIMARY KEY,
  plan_id TEXT REFERENCES test_plans(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  scenario TEXT,
  tags TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bug_reports (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  severity TEXT,
  priority TEXT,
  steps_to_reproduce TEXT,
  expected TEXT,
  actual TEXT,
  environment TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS quality_gates (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  criteria TEXT,
  threshold REAL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS test_results (
  id TEXT PRIMARY KEY,
  plan_id TEXT REFERENCES test_plans(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  passed INTEGER DEFAULT 0,
  failed INTEGER DEFAULT 0,
  coverage REAL,
  notes TEXT,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS checklists (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  items JSONB,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS qa_executions (
  id TEXT PRIMARY KEY,
  plan_id TEXT REFERENCES test_plans(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- SecZilla Tables
-- ============================================================================

CREATE TABLE IF NOT EXISTS threat_models (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT,
  scope TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS vulnerabilities (
  id TEXT PRIMARY KEY,
  model_id TEXT REFERENCES threat_models(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  severity TEXT,
  description TEXT,
  mitigation TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS security_controls (
  id TEXT PRIMARY KEY,
  model_id TEXT REFERENCES threat_models(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  description TEXT,
  priority TEXT,
  status TEXT NOT NULL DEFAULT 'proposed',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS security_checklists (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  type TEXT,
  items JSONB,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- ArchZilla Tables
-- ============================================================================

CREATE TABLE IF NOT EXISTS architectures (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT,
  version TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS arch_decisions (
  id TEXT PRIMARY KEY,
  architecture_id TEXT REFERENCES architectures(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  context TEXT,
  decision TEXT,
  consequences TEXT,
  status TEXT NOT NULL DEFAULT 'proposed',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS diagrams (
  id TEXT PRIMARY KEY,
  architecture_id TEXT REFERENCES architectures(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  diagram_type TEXT,
  content JSONB,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY,
  architecture_id TEXT REFERENCES architectures(id) ON DELETE CASCADE,
  reviewer_id TEXT,
  feedback TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- BackZilla Tables
-- ============================================================================

CREATE TABLE IF NOT EXISTS apis (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  requirement TEXT,
  contract TEXT,
  implementation TEXT,
  tests TEXT,
  openapi_spec JSONB,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS back_services (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS back_integrations (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  api_id TEXT REFERENCES apis(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS back_workflows (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  steps JSONB,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- FrontZilla Tables
-- ============================================================================

CREATE TABLE IF NOT EXISTS front_features (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  spec JSONB,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS components (
  id TEXT PRIMARY KEY,
  feature_id TEXT REFERENCES front_features(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  agent TEXT,
  doc TEXT,
  story TEXT,
  spec JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS design_tokens (
  id TEXT PRIMARY KEY,
  feature_id TEXT REFERENCES front_features(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  token_value TEXT,
  category TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS front_workflows (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  result JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- OpsZilla Tables
-- ============================================================================

CREATE TABLE IF NOT EXISTS deployments (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  environment TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pipelines (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS infrastructure (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  type TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS incidents (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  severity TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- POZilla Tables
-- ============================================================================

CREATE TABLE IF NOT EXISTS epics (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS po_features (
  id TEXT PRIMARY KEY,
  epic_id TEXT REFERENCES epics(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  description TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS po_stories (
  id TEXT PRIMARY KEY,
  feature_id TEXT REFERENCES po_features(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  description TEXT,
  points INTEGER,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS po_tasks (
  id TEXT PRIMARY KEY,
  story_id TEXT REFERENCES po_stories(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- ProductZilla Tables
-- ============================================================================

CREATE TABLE IF NOT EXISTS product_features (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  specification TEXT,
  acceptance_criteria JSONB,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_stories (
  id TEXT PRIMARY KEY,
  feature_id TEXT REFERENCES product_features(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  description TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS backlogs (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  items JSONB,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS releases (
  id TEXT PRIMARY KEY,
  version TEXT NOT NULL,
  release_date DATE,
  features JSONB,
  status TEXT NOT NULL DEFAULT 'planned',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- Cross-Zilla Validators Tables
-- ============================================================================

CREATE TABLE IF NOT EXISTS validation_results (
  id TEXT PRIMARY KEY,
  validator_name TEXT NOT NULL,
  target_id TEXT,
  target_type TEXT,
  result_status TEXT NOT NULL,
  details JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS validator_rules (
  id TEXT PRIMARY KEY,
  validator_name TEXT NOT NULL,
  rule_name TEXT NOT NULL,
  description TEXT,
  severity TEXT DEFAULT 'warning',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- Zilla Observatory Tables
-- ============================================================================

CREATE TABLE IF NOT EXISTS metrics (
  id TEXT PRIMARY KEY,
  zilla_name TEXT NOT NULL,
  metric_type TEXT NOT NULL,
  metric_value REAL,
  tags JSONB,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dashboards (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  config JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS alerts (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  condition TEXT,
  enabled BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS alert_history (
  id TEXT PRIMARY KEY,
  alert_id TEXT REFERENCES alerts(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- Indexes for Performance
-- ============================================================================

-- Test plans queries
CREATE INDEX IF NOT EXISTS idx_test_cases_plan_id ON test_cases(plan_id);
CREATE INDEX IF NOT EXISTS idx_test_scenarios_plan_id ON test_scenarios(plan_id);
CREATE INDEX IF NOT EXISTS idx_test_results_plan_id ON test_results(plan_id);
CREATE INDEX IF NOT EXISTS idx_qa_executions_plan_id ON qa_executions(plan_id);

-- Threat models queries
CREATE INDEX IF NOT EXISTS idx_vulnerabilities_model_id ON vulnerabilities(model_id);
CREATE INDEX IF NOT EXISTS idx_security_controls_model_id ON security_controls(model_id);

-- Architecture queries
CREATE INDEX IF NOT EXISTS idx_arch_decisions_arch_id ON arch_decisions(architecture_id);
CREATE INDEX IF NOT EXISTS idx_diagrams_arch_id ON diagrams(architecture_id);
CREATE INDEX IF NOT EXISTS idx_reviews_arch_id ON reviews(architecture_id);

-- API queries
CREATE INDEX IF NOT EXISTS idx_back_integrations_api_id ON back_integrations(api_id);

-- Frontend queries
CREATE INDEX IF NOT EXISTS idx_components_feature_id ON components(feature_id);
CREATE INDEX IF NOT EXISTS idx_design_tokens_feature_id ON design_tokens(feature_id);

-- Product queries
CREATE INDEX IF NOT EXISTS idx_user_stories_feature_id ON user_stories(feature_id);

-- PO queries
CREATE INDEX IF NOT EXISTS idx_po_features_epic_id ON po_features(epic_id);
CREATE INDEX IF NOT EXISTS idx_po_stories_feature_id ON po_stories(feature_id);
CREATE INDEX IF NOT EXISTS idx_po_tasks_story_id ON po_tasks(story_id);

-- Validators queries
CREATE INDEX IF NOT EXISTS idx_validation_results_validator ON validation_results(validator_name);
CREATE INDEX IF NOT EXISTS idx_validator_rules_validator ON validator_rules(validator_name);

-- Observatory queries
CREATE INDEX IF NOT EXISTS idx_metrics_zilla ON metrics(zilla_name);
CREATE INDEX IF NOT EXISTS idx_metrics_recorded ON metrics(recorded_at);
CREATE INDEX IF NOT EXISTS idx_alert_history_alert_id ON alert_history(alert_id);
CREATE INDEX IF NOT EXISTS idx_alerts_enabled ON alerts(enabled);
