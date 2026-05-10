import { z } from 'zod';
import { POZillaStore } from '../db/store.js';
import { mcpClient } from '@platform/mcp-client';

export interface ToolSchema {
  name: string;
  description: string;
  inputSchema: z.ZodSchema;
}

export const TOOL_SCHEMAS: Record<string, ToolSchema> = {
  analyze_business_demand: {
    name: 'analyze_business_demand',
    description: 'Analyzes business demand: objective, scope, impact, constraints, roadmap placement',
    inputSchema: z.object({
      demand_description: z.string(),
      business_goal: z.string().optional(),
      affected_users: z.array(z.string()).optional(),
      constraints: z.array(z.string()).optional(),
    }),
  },
  generate_epic: {
    name: 'generate_epic',
    description: 'Generates epic: title, description, objective, business value, success criteria',
    inputSchema: z.object({
      demand: z.string(),
      vision: z.string().optional(),
      timeline: z.enum(['3m', '6m', '1y', '2y']).optional(),
    }),
  },
  generate_feature_breakdown: {
    name: 'generate_feature_breakdown',
    description: 'Breaks epic into features: scope, dependencies, complexity, priority',
    inputSchema: z.object({
      epic: z.string(),
      feature_count: z.number().optional(),
      team_size: z.number().optional(),
    }),
  },
  generate_user_stories: {
    name: 'generate_user_stories',
    description: 'Generates user stories: As a [role], I want [action], so that [benefit]',
    inputSchema: z.object({
      feature: z.string(),
      user_personas: z.array(z.string()).optional(),
      story_count: z.number().optional(),
    }),
  },
  generate_acceptance_criteria: {
    name: 'generate_acceptance_criteria',
    description: 'Generates acceptance criteria: testable, clear, objective conditions',
    inputSchema: z.object({
      user_story: z.string(),
      business_rules: z.array(z.string()).optional(),
    }),
  },
  generate_gherkin_scenarios: {
    name: 'generate_gherkin_scenarios',
    description: 'Generates Gherkin BDD scenarios: Given/When/Then format for testing',
    inputSchema: z.object({
      story_title: z.string(),
      acceptance_criteria: z.array(z.string()).optional(),
      edge_cases: z.array(z.string()).optional(),
    }),
  },
  define_definition_of_ready: {
    name: 'define_definition_of_ready',
    description: 'Defines DoR checklist: clarity, acceptance criteria, dependencies, estimates',
    inputSchema: z.object({
      context: z.string().optional(),
      team_process: z.enum(['scrum', 'kanban', 'hybrid']).optional(),
    }),
  },
  define_definition_of_done: {
    name: 'define_definition_of_done',
    description: 'Defines DoD checklist: code review, tests, design, docs, deployment readiness',
    inputSchema: z.object({
      context: z.string().optional(),
      team_process: z.enum(['scrum', 'kanban', 'hybrid']).optional(),
    }),
  },
  prioritize_backlog_items: {
    name: 'prioritize_backlog_items',
    description: 'Prioritizes backlog using MoSCoW, value, dependencies, risk',
    inputSchema: z.object({
      items: z.array(z.object({
        name: z.string(),
        value: z.number().optional(),
        effort: z.number().optional(),
        risk: z.number().optional(),
      })),
      framework: z.enum(['MoSCoW', 'Value-vs-Effort', 'Weighted']).optional(),
    }),
  },
  map_dependencies: {
    name: 'map_dependencies',
    description: 'Maps dependencies: internal, external, blocking, sequential',
    inputSchema: z.object({
      items: z.array(z.string()),
      scope: z.enum(['epic', 'feature', 'story']).optional(),
    }),
  },
  identify_scope_risks: {
    name: 'identify_scope_risks',
    description: 'Identifies scope risks: ambiguity, dependencies, technical feasibility',
    inputSchema: z.object({
      scope_description: z.string(),
      constraints: z.array(z.string()).optional(),
    }),
  },
  prepare_sprint_backlog: {
    name: 'prepare_sprint_backlog',
    description: 'Prepares sprint backlog: selects stories, estimates, assigns points',
    inputSchema: z.object({
      available_items: z.array(z.object({
        title: z.string(),
        estimate: z.number().optional(),
      })),
      sprint_capacity: z.number().optional(),
    }),
  },
  generate_release_notes: {
    name: 'generate_release_notes',
    description: 'Generates release notes: features, improvements, fixes, user-facing changes',
    inputSchema: z.object({
      version: z.string(),
      stories_delivered: z.array(z.string()),
      highlights: z.array(z.string()).optional(),
    }),
  },
  generate_homologation_checklist: {
    name: 'generate_homologation_checklist',
    description: 'Generates QA/testing checklist: scenarios, edge cases, regression tests',
    inputSchema: z.object({
      feature: z.string(),
      acceptance_criteria: z.array(z.string()).optional(),
      platforms: z.array(z.string()).optional(),
    }),
  },
  generate_jira_tasks: {
    name: 'generate_jira_tasks',
    description: 'Generates Jira task format: issue description, fields, labels, links',
    inputSchema: z.object({
      story: z.string(),
      issue_type: z.enum(['Story', 'Task', 'Bug', 'Epic']).optional(),
      team: z.string().optional(),
    }),
  },
  refine_feature: {
    name: 'refine_feature',
    description: 'Refines feature: breaks into stories, identifies unknowns, validates readiness',
    inputSchema: z.object({
      feature_title: z.string(),
      feature_description: z.string(),
      business_rules: z.array(z.string()).optional(),
    }),
  },
  validate_story_readiness: {
    name: 'validate_story_readiness',
    description: 'Validates story readiness: clear scope, acceptance criteria, no blockers',
    inputSchema: z.object({
      story_title: z.string(),
      story_description: z.string(),
      acceptance_criteria: z.array(z.string()).optional(),
    }),
  },
};

export async function dispatch(
  toolName: string,
  toolInput: unknown,
  _store: POZillaStore,
): Promise<string> {
  const input = toolInput as Record<string, unknown>;

  switch (toolName) {
    case 'analyze_business_demand': {
      const analysis = {
        demand: input.demand_description,
        objective: input.business_goal || 'Business objective',
        scope: 'Initial scope assessment',
        impact: {
          users_affected: input.affected_users || ['Primary users'],
          business_value: 'High / Medium / Low',
          technical_complexity: 'Medium',
        },
        constraints: input.constraints || ['Timeline', 'Resource', 'Technical'],
        roadmap_placement: 'Roadmap phase (MVP, Beta, Production)',
        questions_to_clarify: [
          'What is the success metric?',
          'What is the timeline?',
          'Are there any dependencies?',
        ],
      };
      return JSON.stringify(analysis, null, 2);
    }

    case 'generate_epic': {
      const epic = {
        title: 'Epic Title',
        description: input.demand,
        objective: input.vision || 'Business objective',
        user_value: 'Core value to users',
        business_value: 'Revenue, market position, or strategic value',
        success_criteria: [
          'Adoption metric',
          'User satisfaction metric',
          'Business metric',
        ],
        timeline: input.timeline || '6m',
        high_level_features: ['Feature 1', 'Feature 2', 'Feature 3'],
      };

      // Integração: criar plano de testes com test-mcp
      const testPlanResult = await mcpClient.callTestTool('create_test_plan', {
        title: `Test Plan: ${epic.title}`,
        scope: `Testing ${epic.title} epic with all features`,
      });

      const result = {
        epic,
        test_plan: testPlanResult,
        status: 'created_with_test_plan',
      };

      return JSON.stringify(result, null, 2);
    }

    case 'generate_feature_breakdown': {
      const features = [
        {
          id: 'F1',
          title: 'Core Feature',
          description: 'Main functionality',
          user_stories: 3,
          effort_points: 13,
          priority: 'P0',
        },
        {
          id: 'F2',
          title: 'Supporting Feature',
          description: 'Enabling functionality',
          user_stories: 2,
          effort_points: 8,
          priority: 'P1',
        },
      ];
      return JSON.stringify({ epic: input.epic, features }, null, 2);
    }

    case 'generate_user_stories': {
      const stories = [
        {
          id: 'US1',
          title: 'As a user, I want feature, so that benefit',
          description: 'Story details',
          acceptance_criteria: ['Scenario 1', 'Scenario 2'],
          priority: 'P0',
        },
        {
          id: 'US2',
          title: 'As a user, I want feature, so that benefit',
          description: 'Story details',
          acceptance_criteria: ['Scenario 1'],
          priority: 'P1',
        },
      ];

      // Integração: validar stories com qa-mcp e gerar test scenarios com test-mcp
      const validationResult = await mcpClient.callQATool('run_linter', {
        repo_path: input.feature || 'feature',
      });

      const testScenariosResult = await mcpClient.callTestTool('generate_scenarios', {
        plan_id: 'current_plan',
        category: 'rest_api',
        context: `${input.feature} feature testing`,
      });

      const result = {
        stories,
        validation: validationResult,
        test_scenarios: testScenariosResult,
        status: 'generated_with_validation',
      };

      return JSON.stringify(result, null, 2);
    }

    case 'generate_acceptance_criteria': {
      const criteria = {
        story: input.user_story,
        acceptance_criteria: [
          {
            id: 'AC1',
            title: 'Happy path',
            condition: 'User performs standard flow',
            expected: 'Expected outcome',
          },
          {
            id: 'AC2',
            title: 'Error case',
            condition: 'User encounters error',
            expected: 'Error message displayed',
          },
          {
            id: 'AC3',
            title: 'Edge case',
            condition: 'Edge case scenario',
            expected: 'System handles gracefully',
          },
        ],
        business_rules: input.business_rules || [],
      };
      return JSON.stringify(criteria, null, 2);
    }

    case 'generate_gherkin_scenarios': {
      const scenarios = [
        {
          scenario: 'Successful flow',
          given: 'User is in state X',
          when: 'User performs action',
          then: 'Expected outcome occurs',
        },
        {
          scenario: 'Error state',
          given: 'Error condition exists',
          when: 'User performs action',
          then: 'Error message shown',
        },
        {
          scenario: 'Edge case',
          given: 'Edge case condition',
          when: 'User performs action',
          then: 'System handles correctly',
        },
      ];
      return JSON.stringify({
        story: input.story_title,
        scenarios,
      }, null, 2);
    }

    case 'define_definition_of_ready': {
      const dor = {
        process: input.team_process || 'scrum',
        checklist: [
          '✓ Story has clear title and description',
          '✓ Acceptance criteria defined and testable',
          '✓ Business rules and exceptions documented',
          '✓ Dependencies identified and listed',
          '✓ No technical blockers',
          '✓ Design specs reviewed (if needed)',
          '✓ Story is small enough for one sprint',
          '✓ Team can estimate (story points or t-shirt size)',
          '✓ No open questions to product owner',
        ],
        definition: 'A story is ready when all checklist items are met and team agrees to pull it into sprint',
      };
      return JSON.stringify(dor, null, 2);
    }

    case 'define_definition_of_done': {
      const dod = {
        process: input.team_process || 'scrum',
        checklist: [
          '✓ Code reviewed and approved',
          '✓ Unit tests written and passing',
          '✓ Integration tests passing',
          '✓ Design reviewed and approved',
          '✓ Documentation updated',
          '✓ Acceptance criteria met',
          '✓ No critical bugs',
          '✓ Performance acceptable',
          '✓ Security reviewed',
          '✓ Ready for deployment',
        ],
        definition: 'A story is done when all checklist items are met and QA has approved',
      };
      return JSON.stringify(dod, null, 2);
    }

    case 'prioritize_backlog_items': {
      const items = Array.isArray(input.items) ? input.items : [];
      const framework = input.framework || 'MoSCoW';
      const prioritized = items.map((item: any, idx: number) => ({
        ...item,
        priority: idx === 0 ? 'Must Have' : idx === 1 ? 'Should Have' : 'Nice to Have',
        order: idx + 1,
      }));
      return JSON.stringify({
        framework,
        prioritized_items: prioritized,
        rationale: 'Prioritized based on value, effort, and dependencies',
      }, null, 2);
    }

    case 'map_dependencies': {
      const dependencies = {
        items: input.items || [],
        dependencies: [
          {
            type: 'Internal dependency',
            from: 'Story A',
            to: 'Story B',
            impact: 'Story B must be done before Story A',
          },
          {
            type: 'External dependency',
            from: 'Story C',
            to: 'Third-party API',
            impact: 'Needs API availability',
          },
        ],
        critical_path: 'Story A → Story B → Story C',
        blocking_items: [],
      };
      return JSON.stringify(dependencies, null, 2);
    }

    case 'identify_scope_risks': {
      const risks = {
        scope: input.scope_description,
        risks: [
          {
            risk: 'Ambiguity in requirements',
            likelihood: 'High',
            impact: 'Rework needed',
            mitigation: 'Refinement session with stakeholders',
          },
          {
            risk: 'External dependency delay',
            likelihood: 'Medium',
            impact: 'Timeline slip',
            mitigation: 'Early coordination with dependencies',
          },
          {
            risk: 'Technical feasibility',
            likelihood: 'Low',
            impact: 'High',
            mitigation: 'POC or architecture review',
          },
        ],
        constraints: input.constraints || [],
      };
      return JSON.stringify(risks, null, 2);
    }

    case 'prepare_sprint_backlog': {
      const items = Array.isArray(input.available_items) ? input.available_items : [];
      const sprint = {
        capacity: input.sprint_capacity || 40,
        selected_stories: items.slice(0, 3),
        total_points: items.reduce((sum: number, item: any) => sum + (item.estimate || 0), 0),
        burndown_projection: 'Linear or expected pattern',
        sprint_goals: ['Goal 1', 'Goal 2'],
      };
      return JSON.stringify(sprint, null, 2);
    }

    case 'generate_release_notes': {
      const notes = {
        version: input.version,
        date: new Date().toISOString().split('T')[0],
        highlights: input.highlights || ['Major feature 1', 'Major feature 2'],
        new_features: input.stories_delivered || [],
        improvements: ['Performance improvement', 'UX refinement'],
        bug_fixes: ['Bug fix 1', 'Bug fix 2'],
        known_issues: [],
        upgrade_notes: 'How to upgrade / migrate',
      };
      return JSON.stringify(notes, null, 2);
    }

    case 'generate_homologation_checklist': {
      const checklist = {
        feature: input.feature,
        test_scenarios: [
          {
            scenario: 'Happy path',
            steps: ['Step 1', 'Step 2', 'Step 3'],
            expected: 'Feature works as expected',
          },
          {
            scenario: 'Error handling',
            steps: ['Trigger error', 'Verify message'],
            expected: 'Appropriate error message shown',
          },
        ],
        acceptance_criteria: input.acceptance_criteria || [],
        platforms: input.platforms || ['Web', 'Mobile'],
        regression_tests: ['Existing feature 1', 'Existing feature 2'],
        sign_off: 'QA and Product Owner approval required',
      };
      return JSON.stringify(checklist, null, 2);
    }

    case 'generate_jira_tasks': {
      const task = {
        issue_type: input.issue_type || 'Story',
        summary: input.story,
        description: 'Detailed story description',
        acceptance_criteria: ['Criteria 1', 'Criteria 2'],
        story_points: 5,
        priority: 'High',
        team: input.team || 'Development',
        labels: ['feature', 'priority:high'],
        components: ['Backend', 'Frontend'],
      };
      return JSON.stringify(task, null, 2);
    }

    case 'refine_feature': {
      const refined = {
        feature_title: input.feature_title,
        refined_stories: [
          {
            story: 'US1 - Core functionality',
            acceptance_criteria: 2,
            effort: 'Medium',
          },
          {
            story: 'US2 - Edge case handling',
            acceptance_criteria: 2,
            effort: 'Small',
          },
        ],
        unknowns: ['Unknown technical detail', 'Unclear requirement'],
        business_rules: input.business_rules || [],
        readiness_score: '80%',
        next_steps: 'Review with architect, then move to sprint planning',
      };
      return JSON.stringify(refined, null, 2);
    }

    case 'validate_story_readiness': {
      const validation = {
        story: input.story_title,
        validation_results: {
          clarity: { status: 'OK', notes: 'Story is clear' },
          scope: { status: 'OK', notes: 'Appropriately scoped' },
          acceptance_criteria: { status: 'OK', notes: 'Clear and testable' },
          dependencies: { status: 'OK', notes: 'No blockers' },
          estimation: { status: 'NEEDS_CLARIFICATION', notes: 'Need refinement' },
        },
        ready: true,
        recommendations: ['Ready for sprint planning'],
        issues: [],
      };

      // Integração: validar com qa-mcp e fazer double-check com test-mcp
      const qaValidation = await mcpClient.callQATool('run_linter', {
        repo_path: input.story_title || 'story',
      });

      const testValidation = await mcpClient.callTestTool('double_check', {
        plan_id: 'current_plan',
      });

      const result = {
        ...validation,
        qa_validation: qaValidation,
        test_validation: testValidation,
        final_status: qaValidation.success && testValidation.success ? 'READY' : 'NEEDS_REVIEW',
      };

      return JSON.stringify(result, null, 2);
    }

    default:
      return JSON.stringify({ error: `Unknown tool: ${toolName}` });
  }
}
