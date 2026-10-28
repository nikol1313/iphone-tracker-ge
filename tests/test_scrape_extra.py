import json

import httpx
import pytest

from app.scraper.scrape_extra import scrape_extra


def offer(offer_id: int, title: str, price: float, **extra: object) -> dict:
    return {
        "offerSecondaryId": offer_id,
        "productSecondaryId": 1000 + offer_id,
        "productSlug": f"phone-{offer_id}",
        "productTitle": title,
        "offerPrice": price,
        "offerDiscountPrice": None,
        "offerStatus": 1,
        "condition": 1,
        "quantity": 3,
        "productMainImage": f"https://img.example/{offer_id}.jpg",
        **extra,
    }


def catalog_page(total: int, *offers: dict) -> str:
    state = {
        'catalog-products-categories::{"pageNumber":1}': {
            "products": list(offers),
            "offerTotalCount": total,
        }
    }
    return f'<script id="ng-state" type="application/json">{json.dumps(state)}</script>'


@pytest.mark.asyncio
async def test_scrape_extra_keeps_new_iphones_across_pages() -> None:
    pages = {
        "1": catalog_page(
            4,
            offer(1, "Apple iPhone 17 8/256GB Sage მობილური ტელეფონი", 2969, offerDiscountPrice=2899),
            offer(2, "Apple iPhone 16 128 GB Black (შეფასება A)", 2299),
            offer(3, "Apple iPhone 14 6/128GB MIDNIGHT", 1249, condition=2),
        ),
        "2": catalog_page(4, offer(4, "Apple iPhone 18 Pro 256GB Black", 4269, quantity=0)),
    }
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["p"]
        requested.append(page)
        return httpx.Response(200, text=pages[page])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        products = await scrape_extra(client=client, request_delay_seconds=0)

    assert requested == ["1", "2"]
    assert [(p["name"], p["price"], p["is_available"]) for p in products] == [
        ("Apple iPhone 17 8/256GB Sage მობილური ტელეფონი", 2899.0, True),
        ("Apple iPhone 18 Pro 256GB Black", 4269.0, False),
    ]
    assert products[0]["url"] == "https://extra.ge/product/phone-1/1001"
    assert products[0]["external_product_id"] == "1"
