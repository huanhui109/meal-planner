# FAN·DECIDE (饭决) — Never decide "what's for dinner" again

简体中文 | [English](README_EN.md)

> Let AI handle a whole week of meals: Feishu QR / WeChat one-tap login → set preferences
> → generate a weekly menu → reorder groceries → cooking deducts from inventory.
> H5, WeChat Mini Program and other front-ends share one business layer and one design system.
>
> Product spec (naming, logo, information architecture, interaction priorities):
> [docs/product-v2.md](docs/product-v2.md).
>
> Current version: **2.8.0** — see [CHANGELOG.md](CHANGELOG.md).

## Features

**Shipped**

- **Feishu QR login** — web app flow: QR on desktop, deep-links the Feishu app on mobile;
  httpOnly cookie session (access 2h / refresh 30d)
- **Per-user isolation** — every query is scoped to the logged-in user; cross-access returns 404.
  Generation quota has two independent buckets: 3/day for first generation, 10/day for regeneration
- **Self-service Feishu bot config** — under *Me → Automation*, users paste their own App ID /
  App Secret / recipients and send a test message. App Secret is encrypted at rest and only
  returned masked
- **Smart recipe generation** — async task (`202 + task_id`, polled, page can be closed);
  an existing draft for the same week is reused instead of consuming quota again
- **Local recipe library first** — 300+ built-in open recipes (proj.kitchen + HowToCook,
  MIT / Unlicense). A weekly menu is scored and assembled locally by
  *calorie fit / inventory hits / preferred cuisine*; **when the local pool covers the week
  there are zero model calls**, and only the shortfall goes to AI as a fallback shortlist.
  Every menu and meal is labelled with its source (local library / local + AI / AI), and the
  strategy is switchable via `mode` (`auto` / `local` / `ai`)
- **Replacement is local-first too** — swap a dish from the local pool first, only call AI if
  that fails; a local swap can still be escalated with "let AI pick another" (`force_ai`)
- **Nutrition balance check** — daily calories and macro energy ratios are aggregated,
  deviations surface as warnings
- **Budget control** — priced from `ingredient.reference_price`; overspend warns but never
  blocks generation
- **Diversity control** — Jaccard comparison against dish names from the last 4 weeks;
  collisions trigger one automatic regeneration
- **Allergen guard** — dishes matching an allergen are dropped *before* persistence and
  reported in the response
- **Visual weekly menu editing** — 7 days × meal slots; swap a dish, lock/unlock
  (locked slots survive regeneration), mark as cooked
- **Shopping list** — set difference between menu requirements and fridge inventory, with
  gap quantities and unit conversion; one-tap copy
- **Inventory closed loop** — marking a meal cooked deducts from inventory (expiring first)
  and writes `consumption_record`; missing items never block and are returned as detail
- **Today page (one request, everything)** — `GET /api/today` returns today's budget, meal
  slots, shopping gaps, reorder suggestions, cook-vs-takeout comparison, expiring items and
  the automation timeline. Any single block failing never fails the whole page
- **Reorder decision** — gaps are priced from reference prices; when under the minimum order,
  it tops up from "things you'll need this week anyway" and emits a deeplink
- **Cook vs takeout** — home cost comes from menu cost, takeout price from user reference
  prices (edited prices are remembered); verdict is `homemade` / `takeout` / `either`
- **Photo recognition → inventory** — photo → vision model → editable candidate list →
  confirm to store; rate-limited by `llm.vision.daily_limit`, degrades to manual entry
- **Undo** — both dish swap and "mark cooked" (inventory + consumption rollback) have a
  regret window
- **Bot status card** — `GET /api/automation/status` truthfully reports Feishu connection,
  scheduler switch, next run and recent pushes
- **4-tab architecture** — Today / Weekly / Shopping / Fridge, with *Me* in a drawer
- **Responsive H5** — Bento home; floating capsule TabBar below 1024px, left rail + right
  drawer at 1024px and above
- **WeChat Mini Program** — standalone `miniapp/` (Taro 4 + React), feature-parity with H5;
  WeChat one-tap login auto-creates an account that coexists with (and is not bound to) the
  Feishu account; shares `shared/` types, formatting, next-step rules and design tokens
- **Design system** — neutral grey + semantic colours (green = done, orange = attention) with
  black capsule primary buttons; tokens have a single source of truth, zero drift across ends,
  see [docs/design-system.md](docs/design-system.md)
- **Feishu bot** — event callbacks (signature check + AES decrypt + `event_id` dedupe +
  sub-second response); commands `menu / inventory / add inventory / finish a meal / help`
  query the DB directly; scheduled pushes for menu, gaps and expiry reminders (off by default,
  MySQL `GET_LOCK` guarantees one push across multiple workers)
- **Offline decision ("always has an answer")** — `shared/decide.ts` is a client-side
  isomorphic subset of the server decision service. On network failure, timeout or empty
  server result it serves from the bundled local dish pool and the result card is badged
  *local answer*

**Phase 2 (not enabled, does not affect launch)**

- Xiaoxiang supermarket scraping (Playwright session, product library, price snapshots,
  ingredient-product matching). V2.0 already closes the reorder loop with "reference price +
  deeplink"; scraping would only replace estimates with real prices.

## Tech stack

| Layer | Tech |
|-------|------|
| Backend | Python 3.12 / FastAPI / SQLAlchemy 2.0 async / aiomysql |
| Database | MySQL 8.0 (utf8mb4) / Alembic migrations |
| Tasks | DB table + in-process worker (`SELECT ... FOR UPDATE SKIP LOCKED`) |
| Scheduling | APScheduler (off by default, MySQL `GET_LOCK` across workers) |
| Auth | Feishu QR / WeChat one-tap login + self-signed JWT (H5 httpOnly cookie, Mini Program Bearer) |
| LLM | GLM-4 → Qwen-Max → DeepSeek (optional local model fallback) |
| H5 | React 18 / Vite 6 / TypeScript / Ant Design 5 |
| Mini Program | Taro 4.2 / React 18 / TypeScript / SCSS (hand-rolled light components, no UI library) |
| Shared | `shared/` pure TS (types / formatting / next-step rules / design tokens) |
| Deployment | nginx + systemd + certbot (see `deploy/README.md`) |

## Quick start

### Option 1: one command (recommended)

```bash
bash scripts/setup_local.sh
```

The script installs MySQL 8.0 / Python 3.12, creates the database and user, generates `.env`,
creates tables, imports seed data, installs front-end dependencies and runs the test suite
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

Then import the `miniapp/` directory with WeChat DevTools. Full steps for AppID, legal
domains and dev-time bypass are in **[docs/miniapp-setup.md](docs/miniapp-setup.md)**.

For live uvicorn / vite output (debugging): `make dev-backend` + `make dev-frontend`.

Locally, "local dev login" (no Feishu needed) and "demo mode" (no LLM key needed) are enabled
by default, so it works out of the box. Full steps, a troubleshooting table and manual
fallbacks are in **[docs/local-setup.md](docs/local-setup.md)**.

> Already have another MySQL on the machine? The script detects it and **reuses the system
> MySQL 8.0 on 3306**. Only if that instance is unusable (for example its data directory was
> created by 9.x and 8.0 cannot downgrade it) does it — **without touching that data** — start
> a project-dedicated instance (fallback port `3307`), managed with
> `make db-status` / `make db-start` / `make db-stop`.
> Connection config lives in one place: `APP__DATABASE__URL` in `.env`. See
> [docs/database-config.md](docs/database-config.md) and appendix C of
> [docs/local-setup.md](docs/local-setup.md).

### Option 2: manual steps

```bash
make setup      # backend pip install -e ".[dev]" + frontend npm install
cp .env.example .env   # fill APP__DATABASE__URL / APP__AUTH__JWT_SECRET / LLM key
make migrate    # alembic upgrade head
make seed       # import ingredients and reference prices
make test       # export TEST_DATABASE_URL first
```

> ⚠ Without `TEST_DATABASE_URL` the integration cases **skip, they do not pass**.
> `759 passed, 142 skipped` is not a green integration layer — those 142 never ran.

## Project structure

```
meal-planner/
├── backend/
│   ├── app/
│   │   ├── api/          # routers: auth / preferences / menus / inventory / products
│   │   ├── auth/         # JWT tokens and Feishu OAuth client
│   │   ├── models/       # ORM definitions
│   │   ├── schemas/      # Pydantic request/response models and serialization
│   │   └── services/     # generation pipeline, menu, inventory, shopping, nutrition, budget, diversity
│   ├── alembic/          # migration scripts (0001_init is the baseline)
│   └── tests/            # unit / integration / e2e
├── frontend/             # React + Vite H5 client (Bento home + design system)
├── miniapp/              # WeChat Mini Program (Taro 4 + React), feature parity with H5
├── shared/               # pure TS layer shared by both clients (types / formatting / next-step / tokens)
├── config/               # default.yaml and prompt templates
├── deploy/               # nginx / systemd / MySQL init / production runbook
├── docs/                 # local setup, architecture, launch, Feishu config
├── logs/                 # background service logs and PIDs (git-ignored)
└── scripts/
    ├── setup_local.sh    # one-shot local environment bootstrap
    ├── service.sh        # ops console: start/stop/restart/logs/self-check
    ├── mysql_local.sh    # project-dedicated MySQL instance management
    ├── seed_data.py      # ingredient and reference-price seed data
    └── backup_db.py      # database backup
```

## Documentation

- [**Master plan**](docs/master-plan.md) — module structure and planning, requirements ×
  version ledger, gap alignment, roadmap, TAPD mapping
- [Project audit](docs/project-audit.md) — module split / dependencies / business flows /
  historical progress
- [Codebase audit](docs/codebase-audit.md) — module map, dependency direction, the offline
  isomorphism contract, quality gates and technical debt (2026-10-12)
- [Product spec V2.0](docs/product-v2.md)
- [Architecture](docs/architecture.md)
- [Database reference](docs/database.md) — tables / indexes / foreign keys / ER diagram /
  column meanings (generated by `make db-doc`)
- [V2.3 spec · recipe library and local-first generation](docs/requirements-v2.3.md)
- [Design system](docs/design-system.md)
- [WeChat Mini Program setup and debugging](docs/miniapp-setup.md)
- [Local setup guide](docs/local-setup.md)
- [Deployment guide](docs/deployment.md)
- [Production runbook](deploy/README.md)
- [Feishu QR login setup](docs/feishu-setup.md)

## Disclaimer

This tool is intended for personal learning and household use. The Phase 2 supermarket data
collection is an unofficial implementation and may violate platform terms of service; users
assume the risk themselves. Features shipped in the current release contain no collection
behaviour.

## License & Distribution

Released under the **MIT License** — see [LICENSE](LICENSE).

The bundled recipe data comes from open-source projects whose original licenses take
precedence: HowToCook ([Anduin2017/HowToCook](https://github.com/Anduin2017/HowToCook),
Unlicense) and proj.kitchen. Source annotations live in `data/` and
`scripts/import_recipes/`.
