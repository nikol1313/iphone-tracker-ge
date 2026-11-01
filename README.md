# iPhone Tracker (iphonetracker.ge)

A Georgian iPhone price comparison and tracking app. It imports retailer listings, records price changes, and lets shoppers track products and set target-price alerts.

## Features

- Search the iPhone catalog by model and variant.
- Compare one phone across retailers: titles like "Apple iPhone 17 (8GB/256GB) - Sage" and
  "iPhone 17, 256 GB, Sage" are parsed into the same model, storage, and color.
- Filter by model, storage, and stock; sort by price, store savings, or store count.
- See the cheapest in-stock price per model on the Today page, plus weekly drops and lowest-recorded tags on catalog cards.
- View price history for tracked products.
- Register an account, track products, and set, edit, or remove target-price alerts.
- Get price alerts by email once the address is confirmed through an emailed link.
- Reset a forgotten password with a one-hour, single-use emailed link.
- Login, sign-up, and password-reset attempts are rate limited per IP, and an account locks
  for 15 minutes after 5 wrong passwords. Counts are kept in memory, so run one uvicorn worker.
- Refresh the catalog from Zoommer, Alta, iSpace, Elit Electronics, Megatechnica, Extra.ge, PCShop, and Metromart automatically every 12 hours and record crawl outcomes.
- Refresh prices on demand from the catalog page (signed-in users, once per hour).
- Explore the REST API using Swagger UI.

## Technology

- Python 3.12, FastAPI, Pydantic, async SQLAlchemy
- PostgreSQL and Alembic migrations
- Retailer-specific product scrapers
- Responsive HTML, CSS, and vanilla JavaScript frontend
- Docker Compose and Nginx
- pytest with HTTPX and SQLite test fixtures
