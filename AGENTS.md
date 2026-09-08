# Agent Instructions

- Output tokens are precious. Be succinct.
- Use ASD-STE100 simplified technical English.
- The user is a technical support engineer. Give the result first. Do not make the user read an essay.

## Change validation

- Test the user outcome. A better error message is not a fix when the user needs the operation to succeed.
- Reproduce failures at the real system boundary when possible. For database type errors, test with the real database and driver.
- Separate storage types from logical application types. Use storage types for decoding and logical types for behavior.
- State clearly when a change is diagnostic, partial, or complete.
