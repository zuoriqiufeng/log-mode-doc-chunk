# Collaboration Patterns

各项目 `CLAUDE.md` 引用的协作规则总表。

## 1. Learn from mistakes

When a correction is made or a bug is found, update the relevant `CLAUDE.md` or `docs/` file with the lesson so it is not repeated.

## 2. Quiz before major changes

Before asking the user to create a PR or approve a significant change, ask clarifying questions to confirm the implications are understood.

## 3. Fix root causes, not symptoms

Do not apply surface patches. Identify and fix the underlying issue, then verify with a reproduction, build, or test.

## 4. Rewrite elegantly when needed

If the current approach is wrong, throw it away and produce a clean, elegant solution using full knowledge of the codebase.

## 5. Plan before coding

For non-trivial changes, enter plan mode and get user approval before writing code. If implementation reveals complexity, stop hard-coding and return to plan mode.

## 6. Review plans like a senior engineer

Audit development plans for hidden risks, edge cases, missing tests, and operational concerns before implementation starts.

## 7. Reuse existing code

Before writing new helpers, search the codebase for existing functions, patterns, or utilities that can be reused. Avoid reinventing wheels.

## 8. Prove no regressions

When a change could affect existing behavior, compare against `main` or baseline and demonstrate that nothing is broken.

## 9. Follow existing patterns

Study how similar features are implemented and follow the same conventions, file organization, and error-handling style.

## 10. Ask follow-up questions

When the user explains their understanding of a piece of code, ask targeted follow-ups to expose gaps or misconceptions.

## 11. Just fix it

When given a complete error message and enough context, fix the root cause directly without asking for unnecessary confirmation.

## 12. Use diagrams

Draw architecture diagrams when they help clarify the overall structure or a proposed change.

## 13. Keep progress notes

For complex tasks, create a note directory and update it after each significant step or commit.

## 14. Use subagents for complex tasks

For multi-part or independent work, spawn multiple subagents to run in parallel.

## 15. Interview before new features

For new features, interview the user first to fully understand behavior, interactions, edge cases, and constraints.

## 16. Review uncommitted changes

Before a commit or PR, review pending diffs and flag risky, incomplete, or unintended changes.

## 17. Impact analysis

Before deleting a function, changing a public interface, or modifying shared state, identify all callers and failure points.
