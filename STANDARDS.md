# Shared standards

Applies to every project in this portfolio: [shop-search](shop-search/PRD.md), [freelance-site](freelance-site/PRD.md), [docs-chat](docs-chat/PRD.md).

## Brand

This is Pooya's personal brand. No third-party logos, colours, or fonts.

| Token | Light | Dark |
|-------|-------|------|
| `--background` | `#FFFFFF` | `#0B0F14` |
| `--surface` | `#F6F7F9` | `#121821` |
| `--ink` | `#111827` | `#E6E8EB` |
| `--muted` | `#5B6472` | `#9AA3AF` |
| `--border` | `#E3E6EA` | `#232B36` |
| `--accent` | `#0F766E` | `#2DD4BF` |
| `--danger` | `#B42318` | `#F97066` |

- Light and dark themes switch automatically through `prefers-color-scheme`.
- Use Inter for UI and body text, loaded with `next/font/google`. Use JetBrains Mono for small accents such as filter tokens and code.
- Keep the look flat: no gradients and no drop shadows. Use 1px borders and an 8px radius.
- Build a clear hierarchy with generous whitespace. Aim for calm and editorial, not a flashy startup template.

## Quality bar

- Mobile first: works at 360px wide with 16px side gutters and no horizontal scroll.
- Accessibility:
  - WCAG AA contrast.
  - Every input has a label.
  - Everything works from the keyboard, with visible focus rings.
  - Streaming content is announced through `aria-live`.
- Every async view has empty, loading, and error states.
- The footer reads "Built by Pooya Nikbakht" and links to GitHub. Both values come from a single config file with placeholder URLs.

## Copy and tone

- Natural and plain: no hype, no "revolutionize", no buzzword stacks.
- **No em dashes (—)** in UI copy, READMEs, or code comments.
- Describe past work generically and use public-level facts only. No company names, internal project names, or non-public metrics.
- Senior full-stack framing (not lead or staff).

## AI provider layer (shop-search, docs-chat)

- `LLM_PROVIDER=anthropic|openai|offline`. If it is unset, pick the provider whose key is present: `ANTHROPIC_API_KEY`, then `OPENAI_API_KEY`. With no key, use `offline`.
- Use the official SDKs only:
  - TypeScript: `@anthropic-ai/sdk` and `openai`.
  - Python: `anthropic` and `openai`.
  - No OpenAI-compatible shims.
- Put each provider behind one small interface. Each adapter uses its provider's native features (structured outputs, citations). Normalized results come out of the interface so the UI never knows which provider answered, except through a small badge.
- **Claude adapter:**
  - Model comes from `ANTHROPIC_MODEL` and defaults to `claude-opus-5-5`, which is used for local runs and evals. Public deploys set `claude-haiku-5-5` to keep costs near zero (see "Public demos" below). Set effort through `output_config.effort`.
  - Turn on the server-side refusal fallback.
  - Follow the bundled claude-api skill docs exactly. On this model, thinking can't be disabled, and sampling params, forced tool_choice, and prefill are all rejected.
- **OpenAI adapter:**
  - Read the model from `OPENAI_MODEL`. No hardcoded default guess; `.env.example` shows an example value.
  - Get structured outputs through the SDK's zod (TS) or pydantic (Python) helpers.
- **Offline / mock adapter:** deterministic, key-free, and used by the tests. It keeps public demos free to host.
- Catch errors with the SDKs' typed exceptions and show friendly messages in the UI.
- API keys are read on the server only and never reach the browser.

## Public demos: cost controls

- **AI provider:** Claude Haiku 5.5 ($0.10 / $0.50 per million tokens), paid from a personal Anthropic account with $5 to $10 of prepaid credit and a monthly spend limit.
- **Usage caps:** a per-IP rate limit plus a global daily cap, both set through env vars.
- **Fallback:** when a cap is hit, or the provider errors or runs out of credit, the app switches to its offline/mock mode automatically and shows a small "demo mode" notice. The demo never breaks.
- **Gemini free tier:** an optional future adapter for $0 hosting, not in scope now. Google may use free-tier inputs to improve its products, so it is acceptable for shop-search queries but never for docs-chat uploads.

## Hosting and domains

- **Domain:** Pooya owns `pooya.website`, currently `www` on Google Sites. Subdomains cost nothing; each one is a DNS record.
- **Hosting:**
  - Frontends go on **Cloudflare Workers** via the OpenNext adapter. The free plan allows commercial use. Vercel Hobby is non-commercial only, which rules it out for a freelance site.
  - The docs-chat API goes on **Google Cloud Run**, which scales to zero, has a free monthly allowance, and starts in seconds. Render's free tier is the fallback, but it sleeps after 15 minutes idle and takes about a minute to wake.
- **Rollout, phase 1:** start on the free URLs (`*.workers.dev`, `*.run.app`).
- **Rollout, phase 2:** add these subdomains.

  | URL | Project |
  |-----|---------|
  | `shop.pooya.website` | shop-search |
  | `coffee.pooya.website` | docs-chat (sample site + widget) |
  | `api.pooya.website` | docs-chat backend |

- **Rollout, phase 3:** once freelance-site is ready, point `pooya.website` and `www` at it, replacing Google Sites. The useful Google Sites content moves into `/about`.
- **Deploy config:** each project ships deploy config (`wrangler.jsonc` / OpenNext, or a Dockerfile for Cloud Run) and README steps. Nothing is deployed during the build.

## Environment and tooling

- Node 22 via nvm (`~/.nvm/versions/node/v22.21.0`). Add `.nvmrc` and set `"engines": { "node": ">=20" }`. The system Node is v16, which is too old.
- Next.js 16 with the App Router, TypeScript (strict), and Tailwind. Use npm.
- Python 3.12 via `uv`, with `pyproject.toml`, `uv.lock`, and ruff.
- Commit `.env.example` files, never real `.env` files.
- No git init, commits, pushes, or deploys from the build step. Pooya publishes the repos himself.

## Every README

1. Pitch paragraph: what it is and who it's for.
2. Screenshots: desktop and mobile, from `docs/screenshots/`.
3. Architecture, as a mermaid diagram.
4. Key decisions and trade-offs, and what you'd do next in production.
5. How to run it locally, plus a table of env vars.
6. Deploy steps.

## Ports for local runs

| Project | Ports |
|---------|-------|
| shop-search | 3000 |
| docs-chat | 3010 (frontend), 8010 (backend) |
| freelance-site | 3020 |
