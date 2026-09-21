# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Quick links

- Repo entry & setup: `README.md`
- Build & run: `docs/build.md`
- Architecture: `docs/architecture.md`
- Module responsibilities: `docs/modules.md`
- Design constraints: `docs/design_constraints.md`
- Config reference: `docs/config_reference.md`
- Web interface: `docs/web.md`
- Code style: `docs/code_style.md`
- Review checklist: `docs/review_checklist.md`
- Full usage: `USAGE.md`
- Module deep dive: `INTRODUCTION.md`
- Chunk structures & Qdrant audits: `docs/chunk-structures.md`, `docs/qdrant-data-audit.md`
- Search strategy: `docs/query/chunk-aware-search-strategy.md`
- Collaboration patterns: `docs/collaboration_patterns.md`

## What you need to know before changing code

chunk is a multi-format document processing and vectorization pipeline inspired by Onyx. It converts documents (PDF, Word, Excel, Markdown, HTML, images, CSV/TSV, JSON, XML, logs) into semantic chunks with optional embeddings and Qdrant storage. It powers RAG services for i2Agent's log analysis engine.

### High-level flow

```
Document → Extract → Enrich (optional) → Chunk → Large Chunk → Contextual RAG → Embed → Vector Store → Save
```

Data flows in one direction through `pipeline.py`, with each stage mutating a list of `DocAwareChunk` objects.

### Key abstractions

- `Document` → `Section` (`TEXT | IMAGE | TABULAR`) → `DocAwareChunk` → `IndexChunk` (with `ChunkEmbedding`).
- Extractors implement `DocumentExtractor`; dispatch happens via `EXTRACTOR_MAP` by file extension.
- Embedding backends implement `BaseEmbeddingModel`; created through `embedding/factory.py`.
- Vector stores implement `BaseVectorStore`; currently only `QdrantVectorStore`.
- Search uses mini-chunk retrieval + large-chunk aggregation + keyword fallback (`hybrid_search`).
- Log pattern library: `log_patterns/` package imports structured patterns (JSON/YAML/CSV/Excel) → 1 standard + 2~4 mini chunks → independent `log_patterns_collection`; structured fields travel via `DocAwareChunk.custom_payload` / `mini_chunk_payloads`.

### Key constraints

- Pipeline stages must not create backward references.
- `DocAwareChunk` is mutated in-place; do not overwrite fields set by earlier stages.
- Large chunks must never contain mini-chunks (`Embedder` enforces this with `RuntimeError`).
- Qdrant `vector_size` in `qdrant.yml` must match the embedding model dimension.
- New extractors, embedding backends, and vector stores must be registered in their respective factory maps.
- `.env` contains `OPENAI_API_KEY`; never commit real keys.
- Enrichment must run **after** table detection, and annotations are appended as independent `Section`s.
- Log patterns must go to their own collection (default `log_patterns_collection`), never the document collection; `log_fingerprint` stays a `string[]` in payloads.

### When in doubt

- For commands, dependencies, and verification, see `docs/build.md`.
- For data flow, design patterns, and data model details, see `docs/architecture.md`.
- For per-file responsibilities, see `docs/modules.md`.
- For config precedence, Qdrant dimensions, and registration rules, see `docs/design_constraints.md`.
- For `.env` and `qdrant.yml` details, see `docs/config_reference.md`.
- For Web UI/API details, see `docs/web.md`.
- For coding conventions, see `docs/code_style.md`.
- Before committing, run `pytest`（`pip install -r requirements-dev.txt`）and run through `docs/review_checklist.md`.

## Collaboration Rules

When working with this codebase:

1. **Plan before code.** For non-trivial changes, enter plan mode and get approval before writing code. If the implementation becomes complex, stop and return to plan mode.
2. **Understand before changing.** Study existing implementations first; follow established patterns and reuse existing functions.
3. **Fix root causes.** Don't apply surface patches. Identify the underlying issue and verify the fix with a reproduction or build.
4. **Rewrite elegantly when needed.** If the current approach is wrong, throw it away and produce a clean solution.
5. **Quiz me before big moves.** Before a PR or significant change, ask clarifying questions to confirm the implications are understood.
6. **Review plans for risks.** Audit plans for hidden edge cases, missing tests, and operational concerns.
7. **Prove no regressions.** Compare against `main` or baseline behavior when existing functionality could be affected.
8. **Impact analysis.** Before deleting a function or changing an interface, identify all callers and failure points.
9. **Use subagents.** For complex multi-part tasks, spawn multiple subagents to work in parallel.
10. **Use diagrams.** Draw architecture diagrams when they help clarify the codebase or a change.
11. **Keep progress notes.** For complex tasks, create a note directory and update it after each significant step.
12. **Review uncommitted changes.** Before commit or PR, review diffs and flag risky or unintended changes.
13. **Interview before new features.** For new features, interview the user first to understand behavior, interactions, and edge cases.
14. **Learn from mistakes.** When corrected or a bug is found, update this file or `docs/collaboration_patterns.md` with the lesson.
15. **Just fix it.** When given a complete error and context, fix the root cause directly.

Full list: `docs/collaboration_patterns.md`.
