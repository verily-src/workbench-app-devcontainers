# Dataset Statistical Explorer (stat-expl)

A 5-page scientific workspace for senior biostatisticians to assess EHR/registry dataset fitness.

## Phase 1 Status ✓

**Completed:**
- Vite + React + TypeScript scaffold
- App shell with routing
- Nav component with 5 pages
- CohortContext (global state for filters, flags, variable tags)
- schema.ts loader with utility functions
- All placeholder pages created
- Test page to verify schema loading and context access

**Structure:**
```
src/
  context/
    CohortContext.tsx     — cohort filters, flags, variable tags
  pages/
    Passport.tsx          — placeholder (Phase 2)
    Population.tsx        — placeholder (Phase 3)
    Variables.tsx         — placeholder (Phase 4)
    Quality.tsx           — placeholder (Phase 5)
    Hypotheses.tsx        — placeholder (Phase 6)
    TestPage.tsx          — Phase 1 test page
  components/
    Nav.tsx               — top navigation
  lib/
    schema.ts             — schema loader and utilities
  App.tsx                 — main app shell
  main.tsx                — React entry point
```

## Development

```bash
# Install dependencies
npm install

# Run dev server
npm run dev

# Build for production
npm run build
```

## Test Routes

- `/passport` - Passport page (placeholder)
- `/population` - Population page (placeholder)
- `/variables` - Variables page (placeholder)
- `/quality` - Quality page (placeholder)
- `/hypotheses` - Hypotheses page (placeholder)
- `/test` - Phase 1 test page (schema loading & context test)

## Next Steps

**Phase 2:** Build Passport page, CohortBar, FlagTray, and lib/flags.ts
