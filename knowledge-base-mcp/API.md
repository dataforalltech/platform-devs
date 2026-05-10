# Knowledge Base MCP — Phase 1

**Port**: 7110  
**Database**: `knowledge-base.db`  
**Status**: Fully implemented with 6 tools

## Overview

The Knowledge Base MCP provides a centralized indexing and search system for all documentation across the platform. It enables rapid retrieval of standards, best practices, and technical references.

## Tools

### 1. index_documentation
Index a new document into the knowledge base.

**Input:**
```typescript
{
  title: string;
  content: string;
  tags?: string[];
}
```

**Output:**
```typescript
{
  status: 'indexed';
  message: string;
}
```

### 2. search_knowledge_base
Full-text search with filtering capabilities.

**Input:**
```typescript
{
  query: string;
  limit?: number;
}
```

**Output:**
```typescript
{
  query: string;
  results: any[];
  total: number;
}
```

### 3. get_document
Retrieve a specific document by ID.

**Input:**
```typescript
{
  doc_id: string;
}
```

**Output:**
```typescript
{
  doc_id: string;
  status: string;
}
```

### 4. list_documents
List all documents, optionally filtered by tag.

**Input:**
```typescript
{
  tag?: string;
}
```

**Output:**
```typescript
{
  tag: string;
  documents: any[];
  total: number;
}
```

### 5. validate_against_standard
Validate artifacts against platform standards.

**Validates:** ADRs, API contracts, database schemas, security policies

### 6. subscribe_to_updates
Subscribe to webhooks for documentation changes.

**Features:**
- Real-time notifications
- Change tracking
- Subscription management

## Database Schema

**Tables:**
- `documents` — indexed content with metadata
- `standards` — validation rules and standards
- `subscriptions` — webhook registrations

## Testing

**Coverage**: 20+ test cases PASSING
- Index operations
- Search filtering
- Document retrieval
- Standard validation
- Subscription management

## Integration Points

- **Used by**: cross-zilla-validators, quality-gates-system, zilla-observatory
- **Consumes**: File system (docs), Configuration (standards)
- **API Format**: stdio (MCP standard)
