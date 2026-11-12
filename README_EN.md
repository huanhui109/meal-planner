# FAN·DECIDE (饭决)

[简体中文](README.md) | English

> **Never decide "what's for dinner" again.** A household meal assistant built around **this one meal**:
> open it to see a suggestion → accept or tweak it → cook or order takeout → log what was actually eaten.
>
> Recommendations are rule-driven: **no model key and no pre-filled inventory required**. AI is an
> optional adjustment layer, and every conclusion is re-validated by the server against real data.
>
> **Current version 2.9.0** · Updated 2026-11-12 · see [CHANGELOG.md](CHANGELOG.md)

---

## What it does

| Situation | What FAN·DECIDE does |
| --- | --- |
| What should we eat now? | Produces a complete meal from household size, cook vs takeout, budget, reference cooking time, spice level and temporary restrictions. Conflicting conditions are reported, never silently dropped. |
| Don't want a model in the loop | The decision engine is pure rules plus a soft-random draw within a score band; on network failure it serves a *local answer* from the bundled dish pool. |
| Want to tweak it in plain language | Click "Hand to AI" and say something like "something warming, not too spicy". One request returns a structured proposal that only takes effect after server-side re-validation. |
| The dish I want isn't in the pool | The in-app *candidate dishes skill* proposes 3–5 **real** dishes from a vague description, each with a reality basis and cooking steps; only validated entries can join the pool. |
| After the meal | `viewed / rejected / accepted / eaten` are tracked separately; only "eaten" enters dietary history. Inventory is not deducted by default, and undoing restores it. |

The public dish count is **342** (`is_dish=1`).

## Core design

- **Rules first, model optional** — `shared/decide.ts` is an isomorphic subset of the server's
  `decision_service.py`: three hard rules and rule-based reasons of ≤20 characters. Models never
  take part in scoring or ranking.
- **No invented dishes** — the candidate pool is the `recipe` table, the 62 dishes in
  [`data/local_dish_pool.json`](data/local_dish_pool.json), and rice. AI may not invent dish names,
  ingredients or prices. The single exception is filling a gap with dishes that **actually exist**,
  each carrying a reality basis, cooking steps and provenance, admitted through one gate: `write_dish()`.
- **The server has the final say** — AI only suggests. Restrictions, spice level, meal slot, tools,
  optimistic locking and candidate authenticity are re-checked in `MealService.propose()`; invalid
  proposals fail and leave the original plan untouched.
- **Low latency by default** — AI adjustment and candidate filling are single-hop requests with a
  short timeout, no retries and no follow-up questions. Sparse input still yields reasonable
  candidates; failures degrade to the rule-based recommendation rather than making the user wait.
- **One shared source of truth** — the H5 client (React + Vite) and the Mini Program (Taro + React)
  share `shared/` types, formatting, decision rules, endpoints and design tokens.

## In-app skills

| Skill | Scope | Description |
| --- | --- | --- |
| [`skills/fandecide/`](skills/fandecide/SKILL.md) | Pick dishes | May only assemble a meal from real candidate keys supplied by the server; it cannot add candidates. Ships a local CLI and is distributed at runtime via `/api/assistant/skill.zip`. |
| [`skills/fandecide-candidates/`](skills/fandecide-candidates/SKILL.md) | Fill the pool | Takes a vague taste / occasion / ingredient description and returns **4 by default (3–5)** real dishes in one consistent shape, with fields that map back onto the `recipe` table. |

The two skills have mutually exclusive scopes, and neither relaxes the "no invented dishes" rule.
Triggers, inputs, output fields and default count are specified in
[SKILL.md](skills/fandecide-candidates/SKILL.md) and [contract.json](skills/fandecide-candidates/contract.json).
For the domain model, migrations and constraints of the workspace, see
[docs/meal-workspace.md](docs/meal-workspace.md).

## Tech stack

| Layer | Tech |
| --- | --- |
| Backend | Python 3.11+ (3.12 for development) / FastAPI / SQLAlchemy 2.0 async / aiomysql |
| Database | MySQL 8.0 (utf8mb4) / Alembic migrations `0001 → 0028` |
| API | Business routers in `backend/app/api/` plus the Feishu webhook, all under `/api` |
| Tasks / scheduling | DB task table + in-process worker (`SELECT ... FOR UPDATE SKIP LOCKED`); APScheduler off by default |
| Auth | Feishu QR / WeChat Mini Program + self-signed JWT; assistant-scope credentials are separate |
| Recommendation | Pure rules by default (no model call); optional GLM-4 / Qwen / DeepSeek or a locally authorised assistant connection |
| H5 | React 18 / Vite 7 / TypeScript / Ant Design 5 / Vitest 3 |
| Mini Program | Taro 4.2 / React 18 / TypeScript / SCSS (hand-rolled light components, no UI library) |
| Shared | `shared/` pure TS: types / formatting / decision rules / endpoints / design tokens |
| Deployment | nginx + systemd + certbot (see [deploy/README.md](deploy/README.md)) |

## Quick start

### Option 1: one command (recommended)

```bash
bash scripts/setup_local.sh
```

The script installs MySQL 8.0 / Python 3.12, creates the database and user, generates `.env`,
runs all migrations, imports seed data, installs front-end dependencies and runs the test suite
once. Then bring the services up in the background (does not block your terminal):

```bash
make up             # database + backend + frontend
make status         # status
make logs           # follow logs
make down           # stop
```

Prefer a menu? Open the interactive ops console with live status:

```bash
make ops
```

Mini Program (optional, separate project):

```bash
make install-miniapp   # install dependencies
make build-miniapp     # build; output at miniapp/dist
```

Then import the `miniapp/` directory with WeChat DevTools. Full steps for AppID, legal domains and
dev-time bypass are in **[docs/miniapp-setup.md](docs/miniapp-setup.md)**.

For live uvicorn / vite output (debugging): `make dev-backend` + `make dev-frontend`.

Locally, "local dev login" (no Feishu needed) and "demo mode" (no LLM key needed) are enabled by
default, so it works out of the box. Full steps, a troubleshooting table and manual fallbacks are in
**[docs/local-setup.md](docs/local-setup.md)**.

> Already have another MySQL on the machine? The script detects it and **reuses the system
> MySQL 8.0 on 3306**. Only if that instance is unusable (for example its data directory was
> created by 9.x and 8.0 cannot downgrade it) does it — **without touching that data** — start a
> project-dedicated instance (fallback port `3307`), managed with
> `make db-status` / `make db-start` / `make db-stop`.
> Connection config lives in one place: `APP__DATABASE__URL` in `.env`. See
> [docs/database-config.md](docs/database-config.md) and appendix C of
> [docs/local-setup.md](docs/local-setup.md).

### Option 2: manual steps

```bash
make setup                  # backend pip install -e ".[dev]" + frontend npm install
cp .env.example .env        # fill APP__DATABASE__URL / APP__AUTH__JWT_SECRET / LLM key
make migrate                # alembic upgrade head (all migrations)
make seed                   # import ingredients and reference prices
make test                   # export TEST_DATABASE_URL first
```

> ⚠ Without `TEST_DATABASE_URL` the integration cases **skip, they do not pass**. Before trusting a
> green run, confirm those cases actually executed.

Real configuration lives only in `.env` (git-ignored); the repository contains placeholder
templates such as `.env.example` and `config/default.yaml`.

---

## Project structure

```
meal-planner/
├── backend/
│   ├── app/
│   │   ├── api/          # business routers (auth / decide / menus / meals / assistant / ...)
│   │   ├── models/       # SQLAlchemy ORM models
│   │   ├── schemas/      # Pydantic request/response models and serialization
│   │   └── services/     # decision, menu, inventory, this-meal workspace, assistant bridge, candidate filling
│   ├── alembic/          # migrations 0001 → 0028
│   └── tests/            # unit / integration
├── frontend/             # React + Vite H5 client (This Meal / Kitchen / History)
├── miniapp/              # WeChat Mini Program (Taro 4.2 + React), compatibility UI
├── shared/               # single source of truth: types / formatting / rules / endpoints / tokens
├── skills/
│   ├── fandecide/            # dish-picking Skill definition and local CLI
│   └── fandecide-candidates/ # candidate-dish Skill spec and output contract
├── data/                 # open recipe seeds and utterance corpus
├── config/               # default.yaml and prompt templates
├── deploy/               # nginx / systemd / MySQL init / production runbook
├── docs/                 # setup, architecture, database, design system, Mini Program config
├── scripts/              # local bootstrap, service ops, backfill and calibration
├── .github/workflows/    # CI and deployment pipelines
├── output/               # calibration output and test CSV (other local artefacts are not tracked)
└── logs/                 # background service logs (git-ignored)
```

## Documentation

- [This Meal workspace design](docs/meal-workspace.md) — domain model, data boundaries, migrations, constraints
- [Candidate dishes skill spec](skills/fandecide-candidates/SKILL.md) · [Output contract](skills/fandecide-candidates/contract.json)
- [Architecture](docs/architecture.md) · [Database config](docs/database-config.md) · [Database reference (generated snapshot)](docs/database.md)
- [Dish data design](docs/dish-data-design.md) · [System One integration](docs/system-one-integration.md)
- [Design system](docs/design-system.md) · [Mini Program brand assets](docs/miniapp-brand-assets.md)
- [Local setup guide](docs/local-setup.md) · [Production runbook](deploy/README.md) · [Internal test rollout](deploy/internal-test.md)
- [Mini Program setup](docs/miniapp-setup.md) · [Mini Program troubleshooting](docs/miniapp-troubleshooting.md) · [Build notes](miniapp/BUILD.md)
- [Feishu QR login setup](docs/feishu-setup.md)
- [Privacy policy template](docs/legal/privacy.md) · [Terms template](docs/legal/terms.md) — draft templates, not effective legal texts
- [Product spec V2.0 (historical)](docs/product-v2.md)

> `docs/database.md` is generated by `make db-doc` from a point-in-time local schema; its table
> count is a **snapshot value**. The current design baseline lives in `backend/app/models/` and
> the Alembic migrations.

## Compatibility and limits

- Feishu QR, WeChat Mini Program and local dev login coexist as isolated identity namespaces.
  Every query is user-scoped and cross-access returns 404.
- Weekly menus, shopping lists, fridge inventory, nutrition / budget / diversity / allergens,
  photo-to-inventory and the Feishu bot remain available as a compatibility layer. The web app's
  top-level navigation is *This Meal / Kitchen / History*; the Mini Program receives no new features.
- "Hand to AI" relies on a locally authorised assistant connection. It is **not an official public
  API** and may break when the upstream changes; when the connection is missing or expired the app
  reports it honestly and degrades to rule-based recommendations, leaving the main flow unaffected.
  So far this path has only been verified with local simulation and automated tests — end-to-end
  behaviour with a real account is not yet validated.
- Phase 2 price-scraping capabilities are **not enabled**; the current release contains no
  collection behaviour.

## Disclaimer

This tool is intended for personal learning and household use and does not provide medical or
nutritional advice. Users assume the risks of deployment and of connecting third-party services.

## License & distribution

Released under the **MIT License** — see [LICENSE](LICENSE).

The bundled recipe data comes from open-source projects whose original licenses take
precedence: HowToCook ([Anduin2017/HowToCook](https://github.com/Anduin2017/HowToCook),
Unlicense) and proj.kitchen. Source annotations live in `data/` and `scripts/import_recipes/`.

> The repository became public on 2026-10-12; the earlier "private / source not available"
> statement in this README is void.

---

Last updated: 2026-11-12
