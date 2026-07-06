/**
 * DevTeamIntegration.ts — Integração modular para todos os 8 DevTeam
 *
 * Padrão:
 * 1. Chamar knowledge-base-mcp para contexto documentação
 * 2. Executar cross-devteam-validators antes de handoff
 * 3. Validar gates com quality-gates-system
 * 4. Registrar métricas no observatory
 */

import { mcpClient } from '@platform/mcp-client';

export class DevTeamIntegration {
  private mcpClient: typeof mcpClient;

  constructor(private devteamName: string) {
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
   * Executa validadores de handoff antes de passar para próximo DevTeam
   */
  async validateHandoff(fromDevTeam: string, toDevTeam: string, payload: Record<string, unknown>) {
    const validators = [
      'validate_completeness',
      'validate_schema_compliance',
      'validate_dependencies',
      'validate_risk_assessment',
    ];

    for (const validator of validators) {
      const result = await this.mcpClient.call('cross-devteam-validators', validator, {
        from_devteam: fromDevTeam,
        to_devteam: toDevTeam,
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
    return await this.mcpClient.call('devteam-observatory', 'report_metrics', {
      devteam: this.devteamName,
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
      await this.validateDocumentationContext({ task, devteam: this.devteamName });

      // 2. Validar handoffs com outros DevTeam
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

export default DevTeamIntegration;
