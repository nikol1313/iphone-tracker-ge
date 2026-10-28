# iPhone Price Monitor Georgia

A Georgian iPhone price comparison and tracking app. It imports retailer listings, records price changes, and lets shoppers track products and set target-price alerts.

## Features

- Search the iPhone catalog by model and variant.
- Compare retailer listings and availability.
- See price-drop and lowest-ever badges on catalog cards.
- View price history for tracked products.
- Register an account, track products, and configure target-price alerts.
- Configure Telegram notifications for price alerts.
- Refresh the catalog from Zoommer, Alta, and iSpace automatically every 12 hours and record crawl outcomes.
- Refresh prices on demand from the catalog page (signed-in users, once per hour).
- Explore the REST API using Swagger UI.

## Technology

- Python 3.12, FastAPI, Pydantic, async SQLAlchemy
- PostgreSQL and Alembic migrations
- Retailer-specific product scrapers
- Responsive HTML, CSS, and vanilla JavaScript frontend
- Docker Compose and Nginx
- pytest with HTTPX and SQLite test fixtures

## Running locally

The app currently runs locally only; a hosted deployment is in progress.

1. Copy `.env.example` to `.env` and fill in `POSTGRES_PASSWORD` and `JWT_SECRET`
   (`openssl rand -hex 32` generates a good value). Compose refuses to start without them.
2. Start the services with `docker compose up --build`.
3. Open [http://localhost:8080](http://localhost:8080).

Telegram alerts need `TELEGRAM_BOT_TOKEN` in `.env`. On a deployed server, set `PROD=true`:
the backend then refuses to start without a `DATABASE_URL` and a non-placeholder `JWT_SECRET`.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync                 # install app and dev dependencies
uv run ruff check .     # lint
uv run pytest -q        # tests (SQLite, no Postgres needed)
```

CI runs lint, tests, and a Docker build on every push and pull request
(`.github/workflows/ci.yml`).

### Scraper health

A crawl that returns zero products is recorded as a failed crawl run, so existing
listings are kept and the failure shows in the logs. A crawl that finds less than half
the products of the previous successful crawl logs a warning; both usually mean a
retailer changed its page layout.
