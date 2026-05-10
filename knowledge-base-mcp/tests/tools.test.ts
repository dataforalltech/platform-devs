import { describe, it, expect } from 'vitest';
import { dispatch, TOOL_SCHEMAS } from '../src/tools/index.js';

describe('Knowledge Base Tools', () => {
  it('should have tool schemas defined', () => {
    expect(Object.keys(TOOL_SCHEMAS).length).toBeGreaterThan(0);
  });

  it('should list tool names', () => {
    const toolNames = Object.keys(TOOL_SCHEMAS);
    expect(toolNames).toContain('index_documentation');
    expect(toolNames).toContain('search_knowledge_base');
    expect(toolNames).toContain('get_document');
    expect(toolNames).toContain('list_documents');
  });

  it('should dispatch index_documentation', async () => {
    const result = await dispatch('index_documentation', {
      title: 'Test Doc',
      content: 'Test content',
    });
    const parsed = JSON.parse(result);
    expect(parsed.status).toBe('indexed');
  });

  it('should dispatch search_knowledge_base', async () => {
    const result = await dispatch('search_knowledge_base', {
      query: 'test query',
    });
    const parsed = JSON.parse(result);
    expect(parsed.query).toBe('test query');
    expect(parsed.results).toBeDefined();
  });

  it('should dispatch get_document', async () => {
    const result = await dispatch('get_document', {
      doc_id: 'doc123',
    });
    const parsed = JSON.parse(result);
    expect(parsed.doc_id).toBe('doc123');
  });

  it('should dispatch list_documents', async () => {
    const result = await dispatch('list_documents', {});
    const parsed = JSON.parse(result);
    expect(parsed.documents).toBeDefined();
  });

  it('should throw on unknown tool', async () => {
    try {
      await dispatch('unknown_tool', {});
      expect.fail('Should have thrown');
    } catch (e) {
      expect((e as Error).message).toContain('Unknown tool');
    }
  });
});
