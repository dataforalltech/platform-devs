/**
 * ZillaIntegration.ts — Integração modular para todos os 8 Zillas
 *
 * Padrão:
 * 1. Chamar knowledge-base-mcp para contexto documentação
 * 2. Executar cross-zilla-validators antes de handoff
 * 3. Validar gates com quality-gates-system
 * 4. Registrar métricas no observatory
 */

import { mcpClient } from '@platform/mcp-client';

export class ZillaIntegration {
  private mcpClient: typeof mcpClient;

  constructor(private zillaName: string) {
    this.mcpClient = mcpClient;
  }

  /**
   * Valida contexto de documentação antes de iniciar tarefa
   */
  async validateDocumentationContext(context: Record<string, unknown>) {
    return await this.mcpClient.call('knowledge-base-mcp', 'search_governance_knowledge', {
      query: context,
    });
  }

  /**
   * Executa validadores de handoff antes de passar para próximo Zilla
   */
  async validateHandoff(fromZilla: string, toZilla: string, payload: Record<string, unknown>) {
    const validators = [
      'validate_completeness',
      'validate_schema_compliance',
      'validate_dependencies',
      'validate_risk_assessment',
    ];

    for (const validator of validators) {
      const result = await this.mcpClient.call('cross-zilla-validators', validator, {
        from_zilla: fromZilla,
        to_zilla: toZilla,
        payload,
      });

      if (!result.passed) {
        throw new Error(`Validator ${validator} failed: ${result.reason}`);
      }
    }
  }

  /**
   * Valida que todos os gates estão passed antes de prosseguir
   */
  async validateQualityGates(component: string): Promise<boolean> {
    const gateStatus = await this.mcpClient.call('quality-gates-system', 'check_gates', {
      component,
    });

    return gateStatus.all_passed;
  }

  /**
   * Registra progresso no Observatory
   */
  async reportMetrics(metrics: Record<string, unknown>) {
    return await this.mcpClient.call('zilla-observatory', 'report_metrics', {
      zilla: this.zillaName,
      timestamp: new Date().toISOString(),
      metrics,
    });
  }

  /**
   * Workflow completo: valida → executa → registra
   */
  async executeWorkflow(
    task: string,
    action: () => Promise<Record<string, unknown>>,
    dependencies: { from: string; to: string; payload: Record<string, unknown> }[]
  ): Promise<Record<string, unknown>> {
    try {
      // 1. Validar documentação
      await this.validateDocumentationContext({ task, zilla: this.zillaName });

      // 2. Validar handoffs com outros Zillas
      for (const dep of dependencies) {
        await this.validateHandoff(dep.from, dep.to, dep.payload);
      }

      // 3. Executar ação
      const result = await action();

      // 4. Validar gates de qualidade
      const gatesPassed = await this.validateQualityGates(task);
      if (!gatesPassed) {
        throw new Error(`Quality gates not passed for ${task}`);
      }

      // 5. Registrar no Observatory
      await this.reportMetrics({
        task,
        status: 'completed',
        gates_passed: gatesPassed,
        timestamp: new Date().toISOString(),
      });

      return result;
    } catch (error) {
      // Registrar falha no Observatory
      await this.reportMetrics({
        task,
        status: 'failed',
        error: String(error),
        timestamp: new Date().toISOString(),
      });
      throw error;
    }
  }
}

export default ZillaIntegration;
