import json

import httpx
import pytest
from bs4 import BeautifulSoup

from app.scraper import scrape_zoommer as scrape_zoommer_module
from app.scraper.scrape_zoommer import products_from_next_data


def test_products_from_zoommer_next_data() -> None:
    payload = {
        "props": {
            "pageProps": {
                "initialFilteredProducts": {
                    "products": [
                        {
                            "id": 54834,
                            "name": "Apple iPhone 18 Pro | 256GB Burgundy",
                            "price": 4299,
                            "route": "mobiluri-telefonebi/apple-iphone-18-pro",
                            "imageUrl": "https://images.example/iphone.jpg",
                            "isInStock": True,
                        },
                        {
                            "id": 9,
                            "name": "Apple Watch",
                            "price": 999,
                            "route": "apple-watch",
                        },
                        {
                            "id": 10,
                            "name": "Apple iPhone without a price",
                            "price": None,
                            "route": "iphone-no-price",
                        },
                    ]
                }
            }
        }
    }
    soup = BeautifulSoup(
        f'<script id="__NEXT_DATA__">{json.dumps(payload)}</script>',
        "html.parser",
    )

    products = products_from_next_data(soup)

    assert products == [
        {
            "name": "Apple iPhone 18 Pro | 256GB Burgundy",
            "price": 4299.0,
            "currency": "GEL",
            "url": "https://zoommer.ge/mobiluri-telefonebi/apple-iphone-18-pro",
            "image_url": "https://images.example/iphone.jpg",
            "store": "Zoommer",
            "is_available": True,
            "external_product_id": "54834",
        }
    ]


def test_products_from_zoommer_next_data_handles_missing_payload() -> None:
    soup = BeautifulSoup("<html><body>No product data</body></html>", "html.parser")

    assert products_from_next_data(soup) == []


@pytest.mark.asyncio
async def test_scrape_zoommer_splits_price_windows_until_each_fits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scrape_zoommer_module, "PAGE_SIZE", 2)
    catalog = [
        {"id": i, "name": f"Apple iPhone 17 | 256GB Color{i}", "price": price, "route": f"p{i}"}
        for i, price in enumerate([1000, 2000, 3000, 60000], start=1)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        low = int(request.url.params["priceFrom"])
        high = int(request.url.params["priceTo"])
        matching = [item for item in catalog if low <= item["price"] <= high]
        payload = {
            "props": {
                "pageProps": {
                    "initialFilteredProducts": {
                        "productsCount": len(matching),
                        "products": matching[:2],
                    }
                }
            }
        }
        return httpx.Response(
            200,
            text=f'<script id="__NEXT_DATA__">{json.dumps(payload)}</script>',
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        products = await scrape_zoommer_module.scrape_zoommer(
            client=client,
            request_delay_seconds=0,
        )

    assert sorted(p["external_product_id"] for p in products) == ["1", "2", "3", "4"]
