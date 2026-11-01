import json

import httpx
import pytest

from app.scraper.scrape_metromart import (
    METROMART_IPHONES_URL,
    PRODUCT_FRAME_URL,
    scrape_metromart,
)


def category_page(*product_ids: int) -> str:
    return "".join(
        f'<div class="lazy-loading-product js-category" product-id="{product_id}"></div>'
        for product_id in product_ids
    )


def frame(name: str, price: str, slug: str) -> str:
    return f"""
        <a itemprop="url" href="/shop/product/{slug}"><img itemprop="image" src="/web/image/{slug}"/></a>
        <a itemprop="name" href="/shop/product/{slug}?category=385">{name}</a>
        <span class="oe_currency_value">{price}</span> ₾
    """


FRAMES = {
    101: frame("Apple iPhone 17 256GB e-SIM Only - Sage", "2,749 .95", "7923-iphone-17-101"),
    102: frame("Apple iPhone 15 128GB Black", "2,049 .95", "1096-iphone-15-102"),
    # A non-iPhone card under the Apple filter is skipped.
    103: frame("Apple Watch Ultra 3", "2,999 .00", "8000-watch-103"),
}


@pytest.mark.asyncio
async def test_scrape_metromart_reads_category_ids_then_product_frames() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        url = str(request.url.copy_with(query=None))
        if url == METROMART_IPHONES_URL:
            return httpx.Response(200, text=category_page(101, 102, 103))
        if url == f"{METROMART_IPHONES_URL}/page/2":
            # Odoo repeats the first page past the end.
            return httpx.Response(200, text=category_page(101, 102, 103))
        if url == PRODUCT_FRAME_URL:
            product_id = json.loads(request.content)["params"]["product_id"]
            return httpx.Response(200, json={"result": {"html": FRAMES[product_id]}})
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        products = await scrape_metromart(client=client, request_delay_seconds=0)

    assert products == [
        {
            "name": "Apple iPhone 17 256GB e-SIM Only - Sage",
            "price": 2749.95,
            "currency": "GEL",
            "url": "https://metromart.ge/shop/product/7923-iphone-17-101?category=385",
            "image_url": "https://metromart.ge/web/image/7923-iphone-17-101",
            "store": "Metromart",
            "is_available": True,
            "external_product_id": "101",
        },
        {
            "name": "Apple iPhone 15 128GB Black",
            "price": 2049.95,
            "currency": "GEL",
            "url": "https://metromart.ge/shop/product/1096-iphone-15-102?category=385",
            "image_url": "https://metromart.ge/web/image/1096-iphone-15-102",
            "store": "Metromart",
            "is_available": True,
            "external_product_id": "102",
        },
    ]
    assert requests[0].url.params["brand"] == "111"
