import json

from bs4 import BeautifulSoup

from app.scraper.scrape_alta import products_from_next_data


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