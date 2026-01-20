# Sentinel Common Rules

> Default rules that apply to all AI-assisted coding sessions.
> These rules address the most common pitfalls identified in AI-generated code.

## Error Handling

- MUST: Raise exceptions for missing required data, never use silent defaults
- MUST: Include context in error messages (function name, relevant input values)
- MUST: Validate external data (API responses, file contents) before use
- AVOID: Bare `except:` or `except Exception:` clauses without re-raising or logging
- NEVER: Swallow exceptions silently without logging or notification

## Configuration

- MUST: Surface all magic numbers as named constants at module top
- MUST: Group related parameters in clearly labeled config blocks
- SHOULD: Document the meaning and valid range for each parameter
- SHOULD: Use environment variables or config files for deployment-specific values
- AVOID: Hardcoded paths, URLs, or credentials in source code

## Code Quality

- MUST: Keep functions focused on a single responsibility
- SHOULD: Add type hints to function signatures
- SHOULD: Write docstrings for public functions explaining purpose and parameters
- AVOID: Functions longer than 50 lines without clear justification
- AVOID: Deep nesting (more than 3 levels) - extract helper functions instead

## Verification

- MUST: Verify calculations manually on sample data before trusting
- SHOULD: Add intermediate print/log statements during development
- SHOULD: Check row counts before and after data transformations
- SHOULD: Validate assumptions about data shape and content explicitly

## Implementation Discipline

- MUST: Ask clarifying questions before making assumptions about ambiguous requirements
- MUST: Surface all design decisions explicitly rather than burying them in code
- SHOULD: Commit frequently with meaningful messages
- SHOULD: Test edge cases, not just happy paths
- AVOID: Over-engineering or adding features not explicitly requested

## [Tag: ml-pipeline]

- MUST: Check for lookahead bias in any feature using time-series data
- MUST: Validate feature values fall within expected ranges
- MUST: Verify row counts match at each pipeline stage
- NEVER: Use default values for missing signals in training data
- NEVER: Include future information in feature calculations

## [Tag: api-integration]

- MUST: Handle rate limiting with exponential backoff
- MUST: Validate response structure before accessing nested fields
- MUST: Log request/response pairs for debugging (sanitize sensitive data)
- SHOULD: Implement circuit breaker pattern for external dependencies
- AVOID: Assuming API responses are always well-formed

## [Tag: data-pipeline]

- MUST: Validate input data schema at pipeline entry
- MUST: Track row counts through each transformation
- MUST: Handle null/missing values explicitly
- SHOULD: Implement idempotent operations where possible
- NEVER: Silently drop rows without logging
