# Agent Instructions

- Output tokens are precious. Be succinct.
- Prefer `uv` for Python environments, dependencies, and test commands.
- Use Pydantic validation at API boundaries. Keep shared engine validation for non-HTTP callers.
- Use ASD-STE100 simplified technical English.
- The user is a technical support engineer. Give the result first. Do not make the user read an essay.

## Change validation

- Always validate changes locally where possible before shipping or declaring them complete. Use a local app or container and test the user outcome at the relevant boundary. Record what passed and any checks that could not run; local validation does not replace required live verification.
- Test the user outcome. A better error message is not a fix when the user needs the operation to succeed.
- Reproduce failures at the real system boundary when possible. For database type errors, test with the real database and driver.
- Separate storage types from logical application types. Use storage types for decoding and logical types for behavior.
- State clearly when a change is diagnostic, partial, or complete.

## Project memory

For Cohort Studio work, read `src/cohort-studio/docs/PROJECT_STATE.md` first. Keep it current when verified project state changes; record evidence and limitations, and do not treat unverified deployment or test status as complete. Claude Code should use the same file via the root `CLAUDE.md` pointer.

Keep `src/cohort-studio/docs/architecture.md` as the single maintained architecture reference. Update it when an architectural decision changes. Prefer E2E tests at the real user boundary before lower-level tests. Keep source comments sparse; add them only for required machine directives, legal notices, or runtime tool docstrings.

## Product decisions

- Prefer decisions that improve user, developer, and agent experience together. Preserve existing behavior and verify outcomes at the relevant boundary.
- Remove redundant taglines, helper text, and secondary labels. Make screens understandable through layout, grouping, and clear primary labels.
- Retain accessible labels, errors, data scope, counts, and warnings needed to make a correct decision. Keep setup details in Settings or developer documentation.
