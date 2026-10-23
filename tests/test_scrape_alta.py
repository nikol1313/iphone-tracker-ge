import json
from types import SimpleNamespace

from bs4 import BeautifulSoup

from app.scraper.scrape_alta import (
    PAGE_SIZE,
    _scrape_price_windows,
    products_from_next_data,
)


def test_products_from_alta_next_data() -> None:
    payload = {
        "props": {
            "pageProps": {
                "initialSearchData": {
                    "products": [
                        {
                            "name": "Apple iPhone 17 Pro 256GB",
                            "price": 4299,
                            "categoryId": 16,
                            "route": "apple-iphone-17-pro",
                            "imageUrl": "https://images.example/iphone.jpg",
                        },
                        {
                            "name": "Apple iPhone missing route",
                            "price": 999,
                            "categoryId": 16,
                        },
                        {
                            "name": "Apple iPhone unavailable",
                            "price": 0,
                            "categoryId": 16,
                            "route": "iphone-unavailable",
                        },
                        {
                            "name": "Apple Watch",
                            "price": 999,
                            "categoryId": 16,
                            "route": "apple-watch",
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

    assert products_from_next_data(soup) == [
        {
            "name": "Apple iPhone 17 Pro 256GB",
            "price": 4299.0,
            "currency": "GEL",
            "url": "https://alta.ge/apple-iphone-17-pro",
            "image_url": "https://images.example/iphone.jpg",
            "store": "Alta",
        }
    ]


def test_products_from_alta_next_data_handles_missing_payload() -> None:
    soup = BeautifulSoup("<html><body>No product data</body></html>", "html.parser")

    assert products_from_next_data(soup) == []

def next_data_page(products: list[dict], total: int) -> SimpleNamespace:
    payload = {
        "props": {
            "pageProps": {
                "initialSearchData": {"products": products, "productsCount": total}
            }
        }
    }
    return SimpleNamespace(
        text=f'<script id="__NEXT_DATA__">{json.dumps(payload)}</script>'
    )


def alta_phone(product_id: int, price: int) -> dict:
    return {
        "name": f"Apple iPhone 17 {product_id}",
        "price": price,
        "categoryId": 16,
        "route": f"mobiluri-telefonebi/apple-iphone-17-p{product_id}",
    }


def test_scrape_alta_splits_price_windows_past_page_limit() -> None:
    catalog = [alta_phone(product_id, 2000 + product_id * 100) for product_id in range(30)]
    requests_made: list[dict] = []

    def fetch(params: dict) -> SimpleNamespace:
        requests_made.append(params)
        assert params["cats"] == 16
        matches = [
            item
            for item in catalog
            if params["priceFrom"] <= item["price"] <= params["priceTo"]
        ]
        return next_data_page(matches[:PAGE_SIZE], len(matches))

    products = _scrape_price_windows(fetch)

    assert sorted(product["url"] for product in products) == sorted(
        f"https://alta.ge/{item['route']}" for item in catalog
    )
    assert len(requests_made) > 1
