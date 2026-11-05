# FAN·DECIDE (饭决) — Never Decide "What's for Dinner" Again

[简体中文](README.md) | English

> A household meal assistant built around **this one meal**: open it to see a suggestion →
> accept or tweak it → cook or order takeout → log what was actually eaten.
> Quick recommendations need no model key and no pre-filled inventory; the FAN·DECIDE Skill
> lets a host assistant understand natural language and shares the very same meal state with the web app.
>
> **Current version: 2.9.0** · Last updated 2026-11-06 · see [CHANGELOG.md](CHANGELOG.md)
>
> Domain model, migrations and constraints of the new workspace:
> [docs/meal-workspace.md](docs/meal-workspace.md). Historical design rationale for naming and
> information architecture: [docs/product-v2.md](docs/product-v2.md) (V2.0-era document).
>
> The web app's top-level navigation is *This Meal / Kitchen / History*. Weekly menus, shopping
> lists and the fridge remain available as a compatibility layer; the Mini Program receives no
> new features in this release.

---

## Features

### 2.9.0 · The "This Meal" Workspace

- **A complete meal, automatically** — generated from household size, cook vs takeout, budget
  target, reference cooking time, spice level and temporary restrictions. Conflicting conditions
  are reported explicitly, never silently dropped. An empty fridge never blocks a suggestion.
- **Four distinct states, fully undoable** — `viewed / rejected / accepted / eaten` are recorded
  separately; only "eaten" enters the dietary history. Inventory is **not** deducted by default —
  only on explicit opt-in — and every deduction keeps its own receipt with batch and expiry date so
  undoing "eaten" restores stock.
- **FAN·DECIDE Skill** — `skills/fandecide/` ships the Skill definition and a local CLI,
  downloadable from `/api/assistant/skill.zip`. The assistant holds only `meal:read` and
  `meal:propose` scopes, credentials are stored as SHA256 hashes and revocable at any time, and
  proposals may only be assembled from real candidate keys returned by the server.
- **Optional direct WorkBuddy connection** — edit a request in the web UI, send it directly, then
  wait for and display the new proposal. Supports refresh recovery, cancellation and offline copy.
  OAuth credentials are encrypted at rest and never exposed to the browser or the model.
- **One unified "Assistant connection" entry** — the avatar settings manage both direct web
  sending and Skill credentials; timed-out connections can be retried, and Skill credentials can
  be created even without WorkBuddy configured.
- **Bidirectional wake-up module (independent, OFF by default)** — nine inbound endpoints under
  `/api/inbound/bridge/*`, paired web/assistant tokens and a default-deny event allowlist.
  Two switches (L0 environment variable + L1 database row); when disabled the endpoints return 503.
  **"Add a gate, don't replace the bridge"**: quick recommendations, the existing
  `/api/assistant/adjustments` bridge and Skill connections are completely unaffected.
- **Server-side validation cannot be overridden by a model** — explicit restrictions, spice level,
  meal slot, available tools and the `expected_revision` optimistic lock are re-checked in
  `MealService` / `MealCatalog`. AI only suggests; it never overwrites explanations derived from
  real data.

> ⚠ **Integration status**: end-to-end integration with a real WorkBuddy account (real OAuth
> authorisation, live message delivery, host model quality) has **not** been performed. All current
> verification is local simulation and automated testing — a passing simulation is not a shipped
> integration.

### Compatibility Features (Earlier Releases, Still Available)

- **Login & isolation** — Feishu QR login (httpOnly cookie, access 2h / refresh 30d), WeChat Mini
  Program one-tap login and local dev login; the three identity namespaces coexist and are isolated.
  Every query is user-scoped and cross-access returns 404.
- **Decision engine** — `shared/decide.ts` is a client-side isomorphic subset of the server's
  `decision_service.py`: three hard rules, soft-random draw within a score band, rule-based reasons
  of ≤20 characters. On network failure or timeout it serves a *local answer* from the bundled dish
  pool. The public dish count is **342** (`is_dish=1`).
- **Weekly menu** — async task (`202 + task_id`, polled, page can be closed); local recipe library
  first (zero model calls when the local pool suffices); swap a dish, lock/unlock, mark as cooked.
  Generation quota has two independent buckets: 3/day for first generation, 10/day for regeneration.
- **Nutrition / budget / diversity / allergens** — daily calories and macro energy ratios;
  pricing from `ingredient.reference_price` with overspend warnings that never block generation;
  Jaccard comparison against dish names from the last 4 weeks; allergen matches are dropped before
  persistence and reported in the response.
- **Shopping & inventory loop** — set difference between menu requirements and fridge inventory with
  gap quantities and unit conversion, one-tap copy; expiring-first deduction writes
  `consumption_record`; missing items never block and are returned as detail.
- **Today / reorder / cook vs takeout** — `GET /api/today` returns everything in one request and a
  single failing block never fails the whole page; gaps are priced to reach the minimum order and a
  deeplink is emitted; verdict is `homemade / takeout / either`.
- **Photo recognition → inventory**, **undo** (dish swap, mark-as-cooked), and a **bot status card**
  that truthfully reports connection and scheduler state.
- **Feishu bot** — event callbacks (signature check + AES decrypt + `event_id` dedupe + sub-second
  response); scheduled pushes are off by default and MySQL `GET_LOCK` guarantees one push across
  multiple workers.
- **Multi-client & design system** — responsive H5 (floating capsule tab bar below 1024px, left
  rail at 1024px and above); the Mini Program (Taro 4.2 + React) keeps its 4-tab compatibility UI.
  Both clients share `shared/` types, formatting, decision rules and design tokens — see
  [docs/design-system.md](docs/design-system.md).

### Phase 2 (Not Enabled, Does Not Affect Usage)

- Xiaoxiang supermarket scraping (Playwright session, product library, price snapshots,
  ingredient–product matching). The reorder loop already works via "reference price + deeplink";
  scraping would only replace estimates with real prices. **The current release contains no
  collection behaviour.**

---

## Tech Stack

| Layer | Tech |
|-------|------|
| Backend | Python 3.11+ (3.12 for development) / FastAPI / SQLAlchemy 2.0 async / aiomysql |
| Database | MySQL 8.0 (utf8mb4) / Alembic migrations (current head `0026`; 39 ORM business tables) |
| API | 17 business router modules in `backend/app/api/` plus the Feishu webhook, all under `/api` |
| Tasks | DB table + in-process worker (`SELECT ... FOR UPDATE SKIP LOCKED`) |
| Scheduling | APScheduler (off by default, MySQL `GET_LOCK` across workers) |
| Auth | Feishu QR / WeChat one-tap login + self-signed JWT; assistant scope credentials are separate |
| LLM | GLM-4 → Qwen-Max → DeepSeek (optional local model fallback); quick recommendations call no model |
| H5 | React 18 / Vite 7 / TypeScript / Ant Design 5 / Vitest 3 |
| Mini Program | Taro 4.2 / React 18 / TypeScript / SCSS (hand-rolled light components, no UI library) |
| Shared | `shared/` pure TS (types / formatting / decision rules / endpoints / design tokens) |
| Deployment | nginx + systemd + certbot (see [deploy/README.md](deploy/README.md)) |

---

## Quick Start

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

---

## Project Structure

```
meal-planner/
├── backend/
│   ├── app/
│   │   ├── api/          # 17 business routers (auth / decide / menus / meals / assistant / inbound_bridge / ...)
│   │   ├── models/       # 39 ORM business tables
│   │   ├── schemas/      # Pydantic request/response models and serialization
│   │   └── services/     # decision, menu, inventory, this-meal workspace, assistant bridge, inbound gateway
│   ├── alembic/          # migrations 0001 → 0026
│   └── tests/            # unit / integration
├── frontend/             # React + Vite H5 client (This Meal / Kitchen / History)
├── miniapp/              # WeChat Mini Program (Taro 4.2 + React), compatibility UI
├── shared/               # single source of truth: types / formatting / rules / endpoints / tokens
├── skills/fandecide/     # FAN·DECIDE Skill definition and local CLI (served by /api/assistant/skill.zip)
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

## Disclaimer

This tool is intended for personal learning and household use. The Phase 2 supermarket data
collection is an unofficial implementation and may violate platform terms of service; users
assume the risk themselves. Features shipped in the current release contain no collection
behaviour.

## License & Distribution

Released under the **MIT License** — see [LICENSE](LICENSE).

The bundled recipe data comes from open-source projects whose original licenses take
precedence: HowToCook ([Anduin2017/HowToCook](https://github.com/Anduin2017/HowToCook),
Unlicense) and proj.kitchen. Source annotations live in `data/` and `scripts/import_recipes/`.

> The repository became public on 2026-10-12; the earlier "private / source not available"
> statement in this README is void.

---

Last updated: 2026-11-06
