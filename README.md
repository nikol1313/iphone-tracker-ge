# iPhone Price Monitor Georgia

A Georgian iPhone price comparison and tracking app. It imports retailer listings, records price changes, and lets shoppers track products and set target-price alerts.

## Features

- Search the iPhone catalog by model and variant.
- Compare retailer listings and availability.
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

## Currently only available locally until i finish some features.
1. do the .env file by .env.example.
2. Start the services with `docker compose up --build`.
3. Open [http://localhost:8080](http://localhost:8080). 
