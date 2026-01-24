# Project Rules

> Project-specific rules for DocKit mobile app (Expo / React Native).

## Development Workflow (Reference)

Commands for testing native functionality:
```bash
# Build development client
eas build --profile development --platform ios

# Run with dev client
npx expo start --dev-client
```

## Debugging & Logging

- MUST: Add reasonable console.log/console.warn statements at critical points for new implementations or edits
- SHOULD: Log function entry/exit for complex async operations
- SHOULD: Include relevant context in logs (component name, action, key values)

## Implementation Discipline

- MUST: Ask clarification questions when requirements are ambiguous - do NOT make internal decisions silently
- MUST: Surface design decisions explicitly before implementing
- SHOULD: Follow existing code style and patterns in this repository

## New Package Integration

- MUST: Perform thorough web research before adopting a new package
- MUST: Dump full API documentation using `gitingest` to `docs/packages/<package-name>.md`
  ```bash
  # Example: Dump package docs
  cd docs/packages && gitingest https://github.com/owner/repo -o package-name.md

  # For monorepo subpath
  gitingest https://github.com/expo/expo/tree/main/packages/expo-image-picker -o expo-image-picker.md
  ```
- MUST: After implementation, verify API usage against docs (function signatures, param names, return types)
- SHOULD: Evaluate package maintenance status, bundle size, and Expo compatibility
- SHOULD: Check if package requires native code (affects EAS build)
