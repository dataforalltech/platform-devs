import { z } from 'zod';
import { ProductZillaStore } from '../db/store.js';
import { mcpClient } from '@platform/mcp-client';

export interface ToolSchema {
  name: string;
  description: string;
  inputSchema: z.ZodSchema;
}

export const TOOL_SCHEMAS: Record<string, ToolSchema> = {
  analyze_product_problem: {
    name: 'analyze_product_problem',
    description: 'Analyzes product problem: identifies root cause, user pain, market opportunity, and business impact',
    inputSchema: z.object({
      problem_statement: z.string(),
      context: z.string().optional(),
      affected_users: z.array(z.string()).optional(),
    }),
  },
  define_product_vision: {
    name: 'define_product_vision',
    description: 'Defines product vision, mission, goals, and success criteria',
    inputSchema: z.object({
      problem: z.string(),
      target_users: z.string(),
      business_goals: z.array(z.string()).optional(),
      time_horizon: z.enum(['3m', '6m', '1y', '2y', '3y']).optional(),
    }),
  },
  map_user_personas: {
    name: 'map_user_personas',
    description: 'Creates user personas: demographics, goals, pain points, behaviors, motivations',
    inputSchema: z.object({
      user_segment: z.string(),
      research_data: z.string().optional(),
      persona_count: z.number().optional(),
    }),
  },
  map_user_journey: {
    name: 'map_user_journey',
    description: 'Maps user journey: stages, touchpoints, emotions, pain points, opportunities',
    inputSchema: z.object({
      persona: z.string(),
      goal: z.string(),
      context: z.string().optional(),
    }),
  },
  generate_feature_spec: {
    name: 'generate_feature_spec',
    description: 'Generates feature specification: objective, scope, user value, acceptance criteria',
    inputSchema: z.object({
      feature_name: z.string(),
      problem: z.string(),
      target_users: z.string().optional(),
      success_metrics: z.array(z.string()).optional(),
    }),
  },
  generate_user_stories: {
    name: 'generate_user_stories',
    description: 'Generates user stories in format: "As a [role], I want [action], so that [benefit]"',
    inputSchema: z.object({
      feature: z.string(),
      personas: z.array(z.string()).optional(),
      story_count: z.number().optional(),
    }),
  },
  generate_acceptance_criteria: {
    name: 'generate_acceptance_criteria',
    description: 'Generates acceptance criteria: Given/When/Then format, testable, objective',
    inputSchema: z.object({
      user_story: z.string(),
      technical_context: z.string().optional(),
    }),
  },
  prioritize_backlog: {
    name: 'prioritize_backlog',
    description: 'Prioritizes backlog items using frameworks: RICE, MoSCoW, ICE, Kano Model',
    inputSchema: z.object({
      items: z.array(z.object({
        name: z.string(),
        impact: z.number().optional(),
        effort: z.number().optional(),
        confidence: z.number().optional(),
      })),
      framework: z.enum(['RICE', 'MoSCoW', 'ICE', 'Kano']).optional(),
    }),
  },
  calculate_rice_score: {
    name: 'calculate_rice_score',
    description: 'Calculates RICE score: Reach × Impact × Confidence / Effort',
    inputSchema: z.object({
      items: z.array(z.object({
        name: z.string(),
        reach: z.number(),
        impact: z.number(),
        confidence: z.number(),
        effort: z.number(),
      })),
    }),
  },
  define_mvp_scope: {
    name: 'define_mvp_scope',
    description: 'Defines MVP scope: core features, nice-to-haves, out-of-scope, evolution phases',
    inputSchema: z.object({
      feature_spec: z.string(),
      constraints: z.array(z.string()).optional(),
      phases: z.number().optional(),
    }),
  },
  define_product_metrics: {
    name: 'define_product_metrics',
    description: 'Defines product metrics: KPIs, leading indicators, lagging indicators, tracking method',
    inputSchema: z.object({
      feature_name: z.string(),
      business_goal: z.string(),
      time_period: z.enum(['weekly', 'monthly', 'quarterly']).optional(),
    }),
  },
  generate_release_plan: {
    name: 'generate_release_plan',
    description: 'Generates release plan: phases, timeline, go-to-market, success criteria, risks',
    inputSchema: z.object({
      feature: z.string(),
      launch_date: z.string().optional(),
      phases: z.array(z.string()).optional(),
    }),
  },
  generate_discovery_questions: {
    name: 'generate_discovery_questions',
    description: 'Generates discovery research questions for validation and hypothesis testing',
    inputSchema: z.object({
      problem: z.string(),
      hypothesis: z.string().optional(),
      research_method: z.enum(['user_interview', 'survey', 'analytics', 'prototype_testing']).optional(),
    }),
  },
  map_product_risks: {
    name: 'map_product_risks',
    description: 'Maps product risks: value risk, usability risk, viability risk, feasibility risk',
    inputSchema: z.object({
      feature: z.string(),
      assumptions: z.array(z.string()).optional(),
    }),
  },
  generate_go_to_market_brief: {
    name: 'generate_go_to_market_brief',
    description: 'Generates GTM brief: target segment, key messages, launch timing, channels, success metrics',
    inputSchema: z.object({
      product: z.string(),
      launch_date: z.string().optional(),
      target_market: z.string().optional(),
    }),
  },
  generate_handoff_to_design: {
    name: 'generate_handoff_to_design',
    description: 'Generates handoff document for Design: user journeys, wireframes brief, design tokens needs',
    inputSchema: z.object({
      feature_spec: z.string(),
      design_system: z.string().optional(),
    }),
  },
  generate_handoff_to_architecture: {
    name: 'generate_handoff_to_architecture',
    description: 'Generates handoff for Architecture: tech requirements, integration needs, scale expectations',
    inputSchema: z.object({
      feature: z.string(),
      scale_expectations: z.string().optional(),
    }),
  },
  generate_handoff_to_engineering: {
    name: 'generate_handoff_to_engineering',
    description: 'Generates handoff for Engineering: user stories, acceptance criteria, dependencies, timeline',
    inputSchema: z.object({
      feature_spec: z.string(),
      user_stories: z.array(z.string()).optional(),
      timeline: z.string().optional(),
    }),
  },
};

export async function dispatch(
  toolName: string,
  toolInput: unknown,
  _store: ProductZillaStore,
): Promise<string> {
  const input = toolInput as Record<string, unknown>;

  switch (toolName) {
    case 'analyze_product_problem': {
      const analysis = {
        problem_statement: input.problem_statement,
        root_causes: [
          'Primary user friction',
          'Market gap or opportunity',
          'Technical or process limitation',
        ],
        affected_users: input.affected_users || ['Primary users', 'Secondary users'],
        business_impact: {
          revenue_impact: 'Potential revenue or cost impact',
          user_satisfaction: 'NPS/CSAT improvement potential',
          market_opportunity: 'Market size and growth',
        },
        validation_risks: ['Value risk', 'Usability risk', 'Viability risk'],
        recommended_next_steps: ['User research', 'Competitive analysis', 'Prototype validation'],
      };
      return JSON.stringify(analysis, null, 2);
    }

    case 'define_product_vision': {
      const vision = {
        problem: input.problem,
        vision_statement: `Clear vision for ${input.target_users}`,
        mission: 'Deliver core user value through product',
        goals: input.business_goals || [
          'Goal 1: Achieve product-market fit',
          'Goal 2: Build user base',
          'Goal 3: Prove business model',
        ],
        success_criteria: [
          'User adoption metrics',
          'Revenue metrics',
          'User satisfaction metrics',
        ],
        time_horizon: input.time_horizon || '1y',
      };
      return JSON.stringify(vision, null, 2);
    }

    case 'map_user_personas': {
      const personas = [
        {
          name: 'Primary Persona',
          role: 'Role description',
          goals: ['Goal 1', 'Goal 2', 'Goal 3'],
          pain_points: ['Pain point 1', 'Pain point 2'],
          behaviors: 'Usage patterns and frequency',
          motivations: 'What drives user action',
          demographics: 'Age, profession, tech-savviness',
        },
        {
          name: 'Secondary Persona',
          role: 'Alternative user type',
          goals: ['Goal 1', 'Goal 2'],
          pain_points: ['Pain point 1'],
          behaviors: 'Usage patterns',
          motivations: 'User motivations',
          demographics: 'User demographics',
        },
      ];
      return JSON.stringify(personas, null, 2);
    }

    case 'map_user_journey': {
      const journey = {
        persona: input.persona,
        goal: input.goal,
        stages: [
          {
            stage: 'Awareness',
            touchpoints: ['Discovery channel'],
            user_actions: ['Becomes aware of need'],
            emotions: 'Curious',
            pain_points: 'Finding solution',
            opportunities: 'Education, awareness',
          },
          {
            stage: 'Consideration',
            touchpoints: ['Research, evaluation'],
            user_actions: ['Evaluates options'],
            emotions: 'Thoughtful',
            pain_points: 'Too many options',
            opportunities: 'Simplify decision',
          },
          {
            stage: 'Purchase/Adoption',
            touchpoints: ['Sign-up, purchase'],
            user_actions: ['Adopts solution'],
            emotions: 'Hopeful',
            pain_points: 'Onboarding friction',
            opportunities: 'Smooth experience',
          },
          {
            stage: 'Retention',
            touchpoints: ['Product usage'],
            user_actions: ['Uses regularly'],
            emotions: 'Satisfied/Frustrated',
            pain_points: 'Feature gaps',
            opportunities: 'Improve core value',
          },
          {
            stage: 'Advocacy',
            touchpoints: ['Referrals, reviews'],
            user_actions: ['Recommends to others'],
            emotions: 'Delighted',
            pain_points: 'None',
            opportunities: 'Leverage advocacy',
          },
        ],
      };
      return JSON.stringify(journey, null, 2);
    }

    case 'generate_feature_spec': {
      const spec = {
        feature_name: input.feature_name,
        problem: input.problem,
        objective: `Clear objective for ${input.target_users || 'users'}`,
        user_value: 'Core benefit to user',
        scope: {
          in_scope: ['Feature 1', 'Feature 2'],
          out_of_scope: ['Feature 3', 'Future enhancement'],
          nice_to_haves: ['Enhancement 1'],
        },
        success_metrics: input.success_metrics || ['Adoption rate', 'User satisfaction', 'Revenue impact'],
        dependencies: ['Design system', 'Backend API', 'Third-party integrations'],
        risks: ['Technical risk', 'Market risk', 'Execution risk'],
      };

      // Integração: gerar plano de testes com test-mcp
      const testPlan = await mcpClient.callTestTool('create_test_plan', {
        title: `Test Plan: ${input.feature_name}`,
        scope: `Testing feature: ${input.feature_name}`,
      });

      return JSON.stringify({
        spec,
        test_plan: testPlan,
        status: 'feature_spec_created_with_test_plan',
      }, null, 2);
    }

    case 'generate_user_stories': {
      const stories = [
        {
          id: 'US1',
          title: 'As a [role], I want [action], so that [benefit]',
          description: 'User story description',
          acceptance_criteria: ['Scenario 1', 'Scenario 2'],
          priority: 'High',
        },
        {
          id: 'US2',
          title: 'As a [role], I want [action], so that [benefit]',
          description: 'User story description',
          acceptance_criteria: ['Scenario 1'],
          priority: 'Medium',
        },
      ];

      // Integração: validar stories com qa-mcp
      const qaValidation = await mcpClient.callQATool('run_linter', {
        repo_path: `features/${input.feature}`,
      });

      return JSON.stringify({
        stories,
        qa_validation: qaValidation,
        status: 'user_stories_generated_with_validation',
      }, null, 2);
    }

    case 'generate_acceptance_criteria': {
      const criteria = {
        user_story: input.user_story,
        acceptance_criteria: [
          {
            scenario: 'User completes happy path',
            given: 'User is on the page',
            when: 'User performs action',
            then: 'Expected outcome occurs',
          },
          {
            scenario: 'User encounters error',
            given: 'User is in error state',
            when: 'User performs action',
            then: 'Error message displayed',
          },
          {
            scenario: 'Edge case',
            given: 'Edge case condition',
            when: 'User performs action',
            then: 'System handles gracefully',
          },
        ],
        definition_of_done: [
          'Code reviewed',
          'Tests passing',
          'Design approved',
          'Documentation updated',
        ],
      };
      return JSON.stringify(criteria, null, 2);
    }

    case 'prioritize_backlog': {
      const items = Array.isArray(input.items) ? input.items : [];
      const framework = input.framework || 'RICE';
      const prioritized = items.map((item: any, idx: number) => ({
        ...item,
        priority: idx === 0 ? 'P0' : idx === 1 ? 'P1' : 'P2',
        score: item.impact ? (item.impact * (item.confidence || 1)) / (item.effort || 1) : 0,
      }));
      return JSON.stringify({
        framework,
        prioritized_items: prioritized.sort((a: any, b: any) => b.score - a.score),
        rationale: 'Scoring based on selected framework',
      }, null, 2);
    }

    case 'calculate_rice_score': {
      const items = Array.isArray(input.items) ? input.items : [];
      const scored = items.map((item: any) => ({
        name: item.name,
        reach: item.reach,
        impact: item.impact,
        confidence: item.confidence,
        effort: item.effort,
        rice_score: (item.reach * item.impact * item.confidence) / item.effort,
      }));
      return JSON.stringify({
        items: scored.sort((a: any, b: any) => b.rice_score - a.rice_score),
        top_priority: scored.length > 0 ? scored[0].name : 'N/A',
      }, null, 2);
    }

    case 'define_mvp_scope': {
      const mvp = {
        feature: input.feature_spec,
        mvp_phase: {
          core_features: ['Feature 1', 'Feature 2'],
          success_criteria: ['User adoption', 'Feature usage'],
          timeline: '4-6 weeks',
        },
        beta_phase: {
          new_features: ['Feature 3', 'Feature 4'],
          improvements: ['Performance', 'UX polish'],
          timeline: '6-8 weeks',
        },
        v2_roadmap: {
          major_features: ['Feature 5', 'Feature 6'],
          integrations: ['Third-party A', 'Third-party B'],
          timeline: '3-6 months',
        },
        nice_to_haves: ['Enhancement 1', 'Enhancement 2'],
        out_of_scope: ['Out of scope item'],
      };
      return JSON.stringify(mvp, null, 2);
    }

    case 'define_product_metrics': {
      const metrics = {
        feature: input.feature_name,
        business_goal: input.business_goal,
        primary_metric: 'North Star: Daily/Monthly Active Users',
        kpis: [
          {
            name: 'Adoption Rate',
            formula: 'New users / Total users',
            target: '+20% month-over-month',
            frequency: input.time_period || 'monthly',
          },
          {
            name: 'Feature Usage',
            formula: 'Users using feature / Total users',
            target: '>60% within 30 days',
            frequency: input.time_period || 'monthly',
          },
          {
            name: 'User Satisfaction',
            formula: 'NPS or CSAT score',
            target: '>40 NPS or >7/10',
            frequency: 'monthly',
          },
        ],
        leading_indicators: ['Sign-up completion rate', 'Onboarding completion'],
        lagging_indicators: ['Revenue impact', 'User churn'],
        tracking_method: 'Analytics platform, user research, business metrics',
      };
      return JSON.stringify(metrics, null, 2);
    }

    case 'generate_release_plan': {
      const plan = {
        feature: input.feature,
        launch_date: input.launch_date || '2026-06-15',
        phases: [
          {
            phase: 'Alpha (Week 1-2)',
            scope: 'Internal testing',
            users: 'Product team, key stakeholders',
            goals: ['Validate core functionality', 'Identify critical bugs'],
          },
          {
            phase: 'Beta (Week 3-4)',
            scope: 'Early adopter testing',
            users: '100-500 beta users',
            goals: ['Gather user feedback', 'Measure engagement'],
          },
          {
            phase: 'General Availability (Week 5+)',
            scope: 'Full product launch',
            users: 'All users',
            goals: ['Drive adoption', 'Monitor metrics', 'Support users'],
          },
        ],
        go_to_market: {
          channels: ['Email campaign', 'In-app announcement', 'Blog post', 'Social media'],
          messaging: 'Problem solved, user benefit, clear CTA',
          target_audience: 'Segments most likely to benefit',
        },
        success_criteria: ['X% adoption', 'Y NPS', 'Z% engagement'],
        risk_mitigation: ['Monitoring plan', 'Rollback plan', 'Support plan'],
      };

      // Integração: documentar plano com docs-mcp
      const docResult = await mcpClient.callDocsTool('generate_doc', {
        template_name: 'README',
        variables: {
          title: `Release Plan: ${input.feature}`,
          launch_date: input.launch_date || '2026-06-15',
        },
      });

      return JSON.stringify({
        plan,
        documentation: docResult,
        status: 'release_plan_created_with_documentation',
      }, null, 2);
    }

    case 'generate_discovery_questions': {
      const questions = {
        problem: input.problem,
        hypothesis: input.hypothesis || 'Users want solution X',
        research_type: input.research_method || 'user_interview',
        questions: [
          {
            question: 'How do users currently solve this problem?',
            type: 'Open-ended',
            goal: 'Understand current workflow',
          },
          {
            question: 'What frustrates you most about current solution?',
            type: 'Open-ended',
            goal: 'Identify pain points',
          },
          {
            question: 'Would you use a tool that [proposed solution]?',
            type: 'Closed-ended',
            goal: 'Validate problem-solution fit',
          },
          {
            question: 'What would make you switch to our solution?',
            type: 'Open-ended',
            goal: 'Identify decision factors',
          },
        ],
        sample_size: 'Minimum 5 users per segment',
        success_criteria: 'Validate or refute hypothesis',
      };
      return JSON.stringify(questions, null, 2);
    }

    case 'map_product_risks': {
      const risks = {
        feature: input.feature,
        risks: [
          {
            type: 'Value Risk',
            description: 'Users may not perceive value',
            likelihood: 'Medium',
            impact: 'High',
            mitigation: 'User research, problem validation',
          },
          {
            type: 'Usability Risk',
            description: 'Users may find product hard to use',
            likelihood: 'Medium',
            impact: 'High',
            mitigation: 'Usability testing, design review',
          },
          {
            type: 'Viability Risk',
            description: 'Business model may not work',
            likelihood: 'Low',
            impact: 'High',
            mitigation: 'Market analysis, pricing testing',
          },
          {
            type: 'Feasibility Risk',
            description: 'Technical implementation may fail',
            likelihood: 'Medium',
            impact: 'Medium',
            mitigation: 'Architecture review, POC',
          },
        ],
        validation_roadmap: 'Early user research → Prototype testing → Beta launch → Full launch',
      };
      return JSON.stringify(risks, null, 2);
    }

    case 'generate_go_to_market_brief': {
      const gtm = {
        product: input.product,
        launch_date: input.launch_date,
        target_market: input.target_market || 'Primary user segment',
        positioning: {
          value_proposition: 'Core benefit statement',
          differentiation: 'vs. competitors',
          key_messages: ['Message 1', 'Message 2', 'Message 3'],
        },
        target_segments: [
          { segment: 'Early adopters', size: 'X users', priority: 'P0' },
          { segment: 'Mainstream', size: 'Y users', priority: 'P1' },
        ],
        channels: {
          awareness: ['Organic search', 'Social media', 'PR'],
          consideration: ['Content marketing', 'Webinars', 'Demos'],
          conversion: ['Free trial', 'Sales outreach'],
        },
        timeline: {
          pre_launch: '4 weeks',
          launch_window: '2 weeks',
          post_launch: 'Ongoing',
        },
        success_metrics: ['Awareness metrics', 'Conversion rate', 'CAC'],
      };
      return JSON.stringify(gtm, null, 2);
    }

    case 'generate_handoff_to_design': {
      const handoff = {
        feature: input.feature_spec,
        design_requirements: {
          user_journeys: ['Happy path', 'Error states', 'Edge cases'],
          key_screens: ['Screen 1', 'Screen 2', 'Screen 3'],
          interactions: ['Primary CTA', 'Secondary actions', 'Navigation'],
          states: ['Default', 'Loading', 'Success', 'Error'],
        },
        design_system_needs: input.design_system || [
          'New component types?',
          'New color/typography?',
          'Animation specs?',
        ],
        accessibility_requirements: 'WCAG 2.1 AA compliance',
        deadline: '2 weeks',
        kickoff_topics: ['User research findings', 'User stories', 'Acceptance criteria'],
      };
      return JSON.stringify(handoff, null, 2);
    }

    case 'generate_handoff_to_architecture': {
      const handoff = {
        feature: input.feature,
        technical_requirements: {
          scale_expectations: input.scale_expectations || '10k users',
          data_requirements: 'Data model, storage needs',
          integration_points: 'External systems, APIs',
          performance_targets: 'Latency, throughput',
        },
        non_functional_requirements: [
          'Availability: 99.9% uptime',
          'Security: [compliance requirements]',
          'Privacy: [data handling]',
        ],
        dependencies: ['Database', 'Third-party APIs', 'Infrastructure'],
        constraints: ['Technical', 'Resource', 'Timeline'],
        kickoff_topics: ['Feature spec', 'User stories', 'Scale requirements'],
      };
      return JSON.stringify(handoff, null, 2);
    }

    case 'generate_handoff_to_engineering': {
      const handoff = {
        feature_spec: input.feature_spec,
        deliverables: {
          user_stories: input.user_stories || ['Story 1', 'Story 2'],
          acceptance_criteria: 'Per user story',
          api_contracts: 'Request/response specs',
          database_schema: 'Table designs',
        },
        timeline: input.timeline || '6 weeks',
        dependencies: ['Design specs', 'API specs', 'Database design'],
        testing_requirements: [
          'Unit tests',
          'Integration tests',
          'End-to-end tests',
          'Performance tests',
        ],
        definition_of_done: [
          'Code reviewed',
          'Tests passing',
          'Design approved',
          'Documentation updated',
          'Feature flagged for rollout',
        ],
        kickoff_date: 'Week of [date]',
      };
      return JSON.stringify(handoff, null, 2);
    }

    default:
      return JSON.stringify({ error: `Unknown tool: ${toolName}` });
  }
}
