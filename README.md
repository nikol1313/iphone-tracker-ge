# iPhone Price Monitor Georgia

A Georgian iPhone price comparison and tracking app. It imports retailer listings, records price changes, and lets shoppers track products and set target-price alerts.

## Features

- Search the iPhone catalog by model and variant.
- Compare retailer listings and availability.
- View price history for tracked products.
- Register an account, track products, and configure target-price alerts.
- Configure Telegram notifications for price alerts.
- Refresh the catalog from Zoommer and Alta and record crawl outcomes.
- Explore the REST API using Swagger UI.

## Technology

- Python 3.12, FastAPI, Pydantic, async SQLAlchemy
- PostgreSQL and Alembic migrations
- Retailer-specific product scrapers
- Responsive HTML, CSS, and vanilla JavaScript frontend
- Docker Compose and Nginx
- pytest with HTTPX and SQLite test fixtures

## Run locally

Requirements: Docker with the Compose plugin.

1. Copy `.env.example` to `.env`.
2. Set `JWT_SECRET` in `.env` to a random value of at least 32 characters (for example, generate one with `openssl rand -hex 32`).
3. Start the services with `docker compose up --build`.
4. Open [http://localhost:8080](http://localhost:8080). API docs are available at [http://localhost:8080/docs](http://localhost:8080/docs).

Database migrations run when the backend starts. Populate or refresh the local product catalog by running `docker compose exec backend python -m app.services.scraper_service`.

Stop the containers with `docker compose down`. To also remove the local database volume, use `docker compose down -v`.

## Run tests

Requirements: Python 3.12 and `uv`.

```sh
uv sync --group dev
uv run pytest
```

## Current scope and limitations

- Catalog refresh is manual; scheduled background crawling is not set up yet.
- Retailer HTML can change, so scraper results should be monitored and parser coverage maintained.
- The admin setup helper requires `ADMIN_EMAIL` and `ADMIN_PASSWORD` of at least 12 characters; never use a shared default password.
- The Compose fallback credentials are for local development only. Use unique secrets and database credentials for any public deployment.

Never commit `.env` or real credentials.
