# ADR 0001: FastAPI + React/Vite as the application stack

**Status:** accepted (2026-10-17)

**Context.** The product needs a JSON API with strict input validation, a background worker that
calls Python tools (Ruff, Bandit, git) and the Anthropic SDK, and an interactive UI for reading
code and findings.

**Options.** Django + DRF; FastAPI; Node/Express for everything. For the UI: server-rendered
templates; Next.js; React + Vite SPA.

**Decision.** FastAPI with Pydantic for the API, React + TypeScript + Vite for the UI.

**Benefits.** The analyzers and the LLM SDK are Python, so the backend shares one runtime with
them. Pydantic validates requests and also validates model output with the same tool. An SPA fits
a tool with live polling and a two-pane review layout; Vite keeps feedback fast.

**Costs.** Two toolchains (uv and npm). No server-side rendering (not needed: every page is behind
login). FastAPI has fewer batteries than Django: no admin, and session auth is assembled from
established primitives (argon2, secure cookies) rather than provided.

**Revisit if** the product needs an admin back office (Django) or public SEO pages (SSR).
