export type Agent = 'frontzilla' | 'pixelfera' | 'shared' | 'orchestrator';

export interface StructuredPayload<T> extends Record<string, unknown> {
  tool: string;
  agent: Agent;
  timestamp: string;
  payload: T;
  instructions: string;
  context_for_llm: string;
  metadata?: {
    feature_id?: string;
    component_id?: string;
    related_tools?: string[];
  };
}

export function createStructuredPayload<T>(params: {
  tool: string;
  agent: Agent;
  payload: T;
  instructions: string;
  context_for_llm: string;
  feature_id?: string;
  component_id?: string;
  related_tools?: string[];
}): StructuredPayload<T> {
  return {
    tool: params.tool,
    agent: params.agent,
    timestamp: new Date().toISOString(),
    payload: params.payload,
    instructions: params.instructions,
    context_for_llm: params.context_for_llm,
    metadata: {
      feature_id: params.feature_id,
      component_id: params.component_id,
      related_tools: params.related_tools,
    },
  };
}

export function errorResponse(tool: string, error: string): Record<string, unknown> {
  return {
    error: true,
    tool,
    message: error,
    timestamp: new Date().toISOString(),
  };
}
