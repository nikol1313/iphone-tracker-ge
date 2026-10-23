import httpx
import pytest
from bs4 import BeautifulSoup

from app.scraper.scrape_ispace import (
    IspaceCrawlError,
    products_from_cards,
    scrape_ispace,
)


def card(
    name: str,
    slug: str,
    price: str,
    *,
    action_price: str | None = None,
    action: str = '<button class="button carousel-product_button">კალათაში</button>',
) -> str:
    discount = (
        f'<span class="carousel-product_price-value carousel-product_price-value__discount">{price}</span>'
        f'<span class="carousel-product_action-price">{action_price}</span>'
        if action_price
        else f'<span class="carousel-product_price-value">{price}</span>'
    )
    return f"""
    <div class="carousel-product" data-test="carousel-product">
      <div class="entity-card">
        <a href="/product/{slug}" class="entity-card_image-wrapper">
          <img src="https://cdn.example/{slug}.webp" class="entity-card_image">
        </a>
        <a href="/product/{slug}" class="entity-card_name">
          <span class="entity-card_name-text">{name}</span>
        </a>
      </div>
      <div class="carousel-product_price-wrapper">
        <p class="carousel-product_price">{discount}</p>
        {action}
      </div>
    </div>"""


def page(*cards: str) -> str:
    return f'<div class="products-grid_grid">{"".join(cards)}</div>'


def test_products_from_ispace_cards() -> None:
    soup = BeautifulSoup(
        page(
            card("iPhone 18 Pro, 256 GB, Black", "iphone-18-pro-256-gb-black-mjrp4af-a", "4 599 ₾"),
            card(
                "iPhone 17 Pro Max, 2 TB, Deep Blue",
                "iphone-17-pro-max-2-tb-deep-blue-mfyx4af-a",
                "7 169 ₾",
                action_price="6 849 ₾",
            ),
            card(
                "iPhone 17 Pro, 512 GB, Deep Blue",
                "iphone-17-pro-512-gb-deep-blue-mg8n4af-a",
                "5 099 ₾",
                action='<a class="button carousel-product_button">შემატყობინეთ</a>',
            ),
            card("iPhone 15, 128 GB, Black", "mtp03hxa-od-mtp03hx-a-od", "1 989 ₾"),
            card("AirPods Pro 3", "airpods-pro-3", "899 ₾"),
        ),
        "html.parser",
    )

    products = products_from_cards(soup)

    assert products == [
        {
            "name": "iPhone 18 Pro, 256 GB, Black",
            "price": 4599.0,
            "currency": "GEL",
            "url": "https://ispace.ge/product/iphone-18-pro-256-gb-black-mjrp4af-a",
            "image_url": "https://cdn.example/iphone-18-pro-256-gb-black-mjrp4af-a.webp",
            "store": "iSpace",
            "is_available": True,
            "external_product_id": "iphone-18-pro-256-gb-black-mjrp4af-a",
        },
        {
            "name": "iPhone 17 Pro Max, 2 TB, Deep Blue",
            "price": 6849.0,
            "currency": "GEL",
            "url": "https://ispace.ge/product/iphone-17-pro-max-2-tb-deep-blue-mfyx4af-a",
            "image_url": "https://cdn.example/iphone-17-pro-max-2-tb-deep-blue-mfyx4af-a.webp",
            "store": "iSpace",
            "is_available": True,
            "external_product_id": "iphone-17-pro-max-2-tb-deep-blue-mfyx4af-a",
        },
        {
            "name": "iPhone 17 Pro, 512 GB, Deep Blue",
            "price": 5099.0,
            "currency": "GEL",
            "url": "https://ispace.ge/product/iphone-17-pro-512-gb-deep-blue-mg8n4af-a",
            "image_url": "https://cdn.example/iphone-17-pro-512-gb-deep-blue-mg8n4af-a.webp",
            "store": "iSpace",
            "is_available": False,
            "external_product_id": "iphone-17-pro-512-gb-deep-blue-mg8n4af-a",
        },
    ]


@pytest.mark.asyncio
async def test_scrape_ispace_follows_pages_and_deduplicates_names() -> None:
    pages = {
        "1": page(
            card("iPhone 17, 256 GB, Black", "iphone-17-256-gb-black-mg6j4af-a", "2 999 ₾"),
            card(
                "iPhone 17, 256 GB, Black",
                "iphone-17-256-gb-black-mg6j4hx-a",
                "2 899 ₾",
                action='<a class="button carousel-product_button">შემატყობინეთ</a>',
            ),
        ),
        "2": page(
            card("iPhone 17, 256 GB, Black", "iphone-17-256-gb-black-mg6j4ll-a", "2 949 ₾"),
            card("iPhone Air, 256 GB, Sky Blue", "iphone-air-256-gb-sky-blue-mg2m4af-a", "3 299 ₾"),
        ),
        "3": page(),
    }
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.params["page"])
        return httpx.Response(200, text=pages[request.url.params["page"]])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        products = await scrape_ispace(request_delay_seconds=0, client=client)

    assert requested == ["1", "2", "3"]
    assert [(p["name"], p["price"], p["is_available"]) for p in products] == [
        ("iPhone 17, 256 GB, Black", 2949.0, True),
        ("iPhone Air, 256 GB, Sky Blue", 3299.0, True),
    ]


@pytest.mark.asyncio
async def test_scrape_ispace_raises_after_retries() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(IspaceCrawlError):
            await scrape_ispace(
                max_attempts=2,
                backoff_seconds=0,
                request_delay_seconds=0,
                client=client,
            )

    assert attempts == 2
