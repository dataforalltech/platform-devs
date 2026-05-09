import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { AnalyzeRequirementSchema } from '../../schemas/requirement.schema.js';

export async function analyzeRequirement(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = AnalyzeRequirementSchema.parse(args);

  const analysis = {
    screens: extractScreens(input.requirement),
    flows: extractFlows(input.requirement),
    actors: extractActors(input.requirement),
    complexity: estimateComplexity(input.requirement),
    estimated_effort_hours: estimateEffort(input.requirement),
  };

  const feature = store.createFeature(
    extractFeatureName(input.requirement),
    input.requirement,
    analysis
  );

  return createStructuredPayload({
    tool: 'analyze_requirement',
    agent: 'shared',
    payload: {
      feature_id: feature.id,
      analysis: feature.analysis,
    },
    instructions:
      'Use this analysis to guide design and frontend tasks. Share feature_id with team.',
    context_for_llm: `Feature: ${feature.name}. Estimated effort: ${analysis.estimated_effort_hours}h. Complexity: ${analysis.complexity}. Screens: ${analysis.screens.join(', ')}.`,
    feature_id: feature.id,
    related_tools: ['split_design_and_frontend_tasks', 'generate_feature_spec'],
  });
}

function extractFeatureName(requirement: string): string {
  const match = requirement.match(/^([^.!?]+)/);
  return match ? match[1].substring(0, 60) : 'Unnamed Feature';
}

function extractScreens(requirement: string): string[] {
  const screenPatterns = [
    /(?:page|screen|view|dialog|modal)s?\s+(?:named|called|for)?\s+["\']?([^"\'.,]+)/gi,
    /(?:create|show|edit|delete|list)\s+([a-z_\-\w]+)/gi,
  ];
  const screens = new Set<string>();
  for (const pattern of screenPatterns) {
    let match;
    while ((match = pattern.exec(requirement)) !== null) {
      if (match[1]) screens.add(match[1].trim());
    }
  }
  return Array.from(screens).slice(0, 5);
}

function extractFlows(requirement: string): string[] {
  const flowPatterns = [
    /(?:user\s+)?(?:can|should|must)\s+([^.!?]+)/gi,
    /(?:flow|process|workflow)\s+(?:for|to)\s+([^.!?]+)/gi,
  ];
  const flows = new Set<string>();
  for (const pattern of flowPatterns) {
    let match;
    while ((match = pattern.exec(requirement)) !== null) {
      if (match[1]) flows.add(match[1].trim().substring(0, 80));
    }
  }
  return Array.from(flows).slice(0, 5);
}

function extractActors(requirement: string): string[] {
  const actorPatterns = ['user', 'admin', 'guest', 'customer', 'client', 'viewer', 'editor'];
  const actors = new Set<string>();
  const lowerReq = requirement.toLowerCase();
  for (const actor of actorPatterns) {
    if (lowerReq.includes(actor)) actors.add(actor);
  }
  return Array.from(actors);
}

function estimateComplexity(requirement: string): string {
  const wordCount = requirement.split(/\s+/).length;
  const hasApiMentioned = /(?:api|endpoint|service|request|response)/i.test(requirement);
  const hasAuthMentioned = /(?:auth|login|permission|role|access)/i.test(requirement);
  const hasMultipleForms = /(?:form|input|validation)/i.test(requirement);

  let complexity = 'low';
  if (wordCount > 100 || (hasApiMentioned && hasAuthMentioned) || hasMultipleForms) {
    complexity = 'high';
  } else if (wordCount > 50 || hasApiMentioned || hasAuthMentioned) {
    complexity = 'medium';
  }

  return complexity;
}

function estimateEffort(requirement: string): number {
  const complexity = estimateComplexity(requirement);
  const baseHours: Record<string, number> = { low: 4, medium: 8, high: 16 };
  return baseHours[complexity] || 8;
}
