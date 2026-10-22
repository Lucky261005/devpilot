# DevPilot front screen: design notes

## Brief

- **Subject:** DevPilot, a local code-review tool. Analyzers run first; LLM findings are kept only
  when the file, lines and quoted code match the source.
- **Audience:** software-engineering recruiters and engineers opening the demo.
- **Job:** in 3 seconds, show what DevPilot is and let people sign in; on scroll, prove it is
  honest engineering (real pipeline, real benchmark numbers, ₹0 local setup).
- **Constraints:** lives inside the existing Vite + React app at `/login` (the app's front door).
  The e2e test signs up through this page, so the form, its labels and its buttons stay.
- **Assumptions:** no public repository URL or author name yet, so there are no GitHub or
  author links. Benchmark numbers are copied from `docs/evaluation.md` (dataset v1, label-blind).

## Concept card

```
Idea:        The page is the file under review.
Metaphor:    A source file in a code viewer: a gutter of line numbers, a scan line, margin findings.
Signature:   A fixed scan line sweeps the page as you scroll; each claim that crosses it gets a
             margin verdict stamped in (verified, rejected, flagged), with the line it cites.
Emotion:     Precise and calm. A tool that checks its own claims.
Motion verb: Snap into the margin like a lint mark (short slide plus clip reveal, 220 ms).
Screenshot:  The "check" section: one LLM claim verified, one rejected, both with line refs.
```

Concepts considered (1 to 5; portability lower is better):

| Concept | Original | Fit | Feasible | Portable |
|---|---|---|---|---|
| The page is the file under review (scan line + margin verdicts) | 4 | 5 | 5 | 1 |
| Courtroom: claims, evidence, verdict | 3 | 4 | 4 | 3 |
| Flight checklist ("pilot") with items ticking | 2 | 3 | 5 | 4 |

Picked the first: it is DevPilot's own mechanism (evidence checked against lines), so it can't
be moved to another product.

## System

- **Palette:** ground `#090B10`, panel `#10141C`, ink `#EDF2FA`, muted `#98A5B8`, line
  `#242D3B`, accent `#8B9CFF`; verdict colours verified `#4ADE80`, rejected `#FB7185`,
  flagged `#FBBF24`. Verdicts always carry a word, never colour alone.
- **Type:** Inter (display and body, display tracking -0.035em to -0.045em), JetBrains Mono
  (gutter, line refs, verdicts, labels). Body 16 to 17 px, leading 1.55.
- **Grid:** a 56 px gutter (line numbers) + 12 columns, 24 px gutter, max 1280 px. Ruled
  background every 28 px, the "line height" of the page.
- **Shape:** 8 px radius on controls, 12 px on panels. Nothing round otherwise.
- **Motion:** one ease, `cubic-bezier(0.23, 1, 0.32, 1)`. Stamps 220 ms, headline reveal
  700 ms, stagger 60 ms. GSAP ScrollTrigger is the only scroll listener. No smooth scroll: this
  is a tool's front door, native scrolling stays.
- **Idle:** the hero file keeps being scanned (the existing CSS loop). The page itself is still
  at rest on purpose; the scan line moves only with the reader.

## Sections

```
1 Hero     | headline + sign-in form (left 5 cols) | scanned file (right 7 cols)
2 Pipeline | sequence: 5 stages in one ruled index list, stage name huge, detail in mono
3 Check    | split: LLM claim left, source lines right, verdict stamps in the margin (signature)
4 Numbers  | 3 oversized numerals, each with the exact claim and its source
5 Local    | one sentence, full width, display size; specs as a definition list
6 Footer   | back to sign in, colophon
```

Genericness check: a generic model would put three feature cards and a gradient hero here.
Changed: features became a pipeline index (it is a real sequence), proof became verdict stamps
tied to line numbers, and numbers include the unflattering one (the local model found nothing).

## Decisions after QA (2026-10-20)

- **Still at rest, on purpose, below the hero.** The hero file keeps being scanned; the rest of
  the page moves only with the reader's scroll.
- **On phones** the tilted file is hidden: rendering it pushed throttled mobile LCP from about
  2 s to 5 s. The page's own scan line and verdict stamps carry the idea there.
- **GSAP and the signed-in pages load after first paint** (dynamic imports), so the front screen
  ships about 103 KB of JS gzipped.
- **Prerendered front screen:** `npm run build` renders `/login` into `dist/login.html`
  (`scripts/prerender.mjs`); `main.tsx` hydrates it. Unknown URLs still return 200 (SPA
  fallback of the server). No og:image or canonical until there is a public URL. No custom display font yet (system Inter
  fallback).
- **Critic scores** (a fresh critic each pass): 7.1, 6.8, then 7.1 after prerendering
  (WPO 9, throttled mobile LCP 1.2 s).
