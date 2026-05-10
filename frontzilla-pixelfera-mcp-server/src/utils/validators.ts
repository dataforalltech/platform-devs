import { z } from 'zod';

export const UUIDv4Regex = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export const AgentSchema = z.enum(['frontzilla', 'pixelfera', 'shared', 'orchestrator']);

export const EnvironmentSchema = z.enum(['development', 'production', 'test']);

export const DetailLevelSchema = z.enum(['minimal', 'standard', 'detailed']).default('standard');

export const ComponentCategorySchema = z.enum([
  'atom',
  'molecule',
  'organism',
  'template',
  'page',
]);

export const DesignTokensFormatSchema = z.enum(['css-vars', 'tailwind', 'js-object']);

export const FrontendLibrarySchema = z.enum(['react-hook-form', 'formik', 'react-final-form']);

export const StyleFrameworkSchema = z.enum(['tailwind', 'styled-components', 'emotion', 'css-modules']);

export const TestFrameworkSchema = z.enum(['vitest', 'jest', 'playwright']);

export const TestTypeSchema = z.enum(['unit', 'integration', 'e2e']);

export const ToneSchema = z.enum(['professional', 'casual', 'friendly', 'technical']);

export const DesignSystemSchema = z.record(z.unknown());

export function generateId(prefix: string): string {
  const uuid = crypto.randomUUID();
  return `${prefix}_${uuid.replace(/-/g, '').substring(0, 12)}`;
}

export function validateJSON<T>(data: unknown, schema: z.ZodSchema<T>): T {
  return schema.parse(data);
}
