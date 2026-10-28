import json

import httpx
import pytest

from app.scraper.scrape_elit import ElitCrawlError, scrape_elit


def listing_page(*products: dict) -> str:
    payload = {"props": {"pageProps": {"initialListingData": {"products": list(products)}}}}
    return f'<script id="__NEXT_DATA__">{json.dumps(payload)}</script>'


def phone(product_id: int, name: str, price: float, **extra: object) -> dict:
    return {
        "id": product_id,
        "name": name,
        "price": price,
        "route": f"mobiluri-telefoni/phone-p{product_id}",
        "imageUrl": f"https://static.example/{product_id}.jpeg",
        **extra,
    }


@pytest.mark.asyncio
async def test_scrape_elit_pages_through_phones_and_keeps_iphones() -> None:
    pages = {
        "1": listing_page(
            phone(1, "APPLE iPhone 18 Pro 256GB Glacier", 4269.99, disableBuyButton=False),
            phone(2, "SAMSUNG Galaxy S26 256GB White", 2829.99),
        ),
        "2": listing_page(
            phone(3, "APPLE iPhone Duo 256GB Night Sky", 7639.99, disableBuyButton=True),
        ),
        "3": listing_page(),
    }
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page"]
        requested.append(page)
        return httpx.Response(200, text=pages[page])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        products = await scrape_elit(client=client, request_delay_seconds=0)

    assert requested == ["1", "2", "3"]
    assert [(p["name"], p["price"], p["is_available"]) for p in products] == [
        ("APPLE iPhone 18 Pro 256GB Glacier", 4269.99, True),
        ("APPLE iPhone Duo 256GB Night Sky", 7639.99, False),
    ]
    assert products[0]["url"] == "https://ee.ge/mobiluri-telefoni/phone-p1"
    assert products[0]["external_product_id"] == "1"


@pytest.mark.asyncio
async def test_scrape_elit_raises_after_failed_retries() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503))
    ) as client:
        with pytest.raises(ElitCrawlError):
            await scrape_elit(
                client=client,
                max_attempts=2,
                backoff_seconds=0,
                request_delay_seconds=0,
            )
