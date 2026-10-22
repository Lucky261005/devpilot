# ADR 0005: Python `ast` for structure and lexical search for retrieval

**Status:** accepted (2026-10-17)

**Context.** The review needs function boundaries to build context, and users need to find code.
The original brief suggested Tree-sitter and optional semantic retrieval.

**Options.** Tree-sitter grammars; Python `ast`; embeddings + vector search; database full-text
search; plain `LIKE`.

**Decision.** `ast` for Python function boundaries (the only language with analyzers today).
Fixed overlapping 60-line windows for other languages. Search is a `LIKE` filter over chunks plus
exact line matching, with a definition-name mode backed by a `symbols` column.

**Benefits.** No native dependencies or model downloads. Code search is dominated by exact
identifiers, which lexical search handles well. Every result maps to an exact file and line.

**Costs.** No structure for non-Python files. `LIKE` scans every chunk of a repository (fine at
MVP scale). No semantic "find code that does X".

**Revisit if** analyzers for other languages are added (Tree-sitter), repositories exceed roughly
100k chunks (PostgreSQL `pg_trgm`/`tsvector` or SQLite FTS5), or a measured case appears for
semantic retrieval in the review context.
