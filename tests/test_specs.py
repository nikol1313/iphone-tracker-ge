import json

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.scraper.zoommer_specs import specs_from_product_page
from app.services.spec_service import refresh_model_specs
from app.services.zmr_inges import ingest_alta, ingest_zoommer

ZOOMMER_URL = "https://zoommer.ge/mobiluri-telefonebi/apple-iphone-17-pro-256gb-p1"


def spec_page(**values: str) -> str:
    names = {
        "chip": "ჩიპსეტი",
        "ram": "ოპერატიული მეხსიერება",
        "refresh_rate": "განახლების სიხშირე",
        "weight": "წონა",
    }
    groups = [{
        "groupName": "ტექნიკური მახასიათებლები",
        "specifications": [
            {"specificationName": names[key], "specificationMeaning": value}
            for key, value in values.items()
        ],
    }]
    return f'<script>{{"product":{{"specificationGroup":{json.dumps(groups, ensure_ascii=False)},"x":1}}}}</script>'


def test_specs_are_read_from_the_embedded_spec_table() -> None:
    page = spec_page(chip="Apple A19 Pro", ram="-", refresh_rate="120 Hz", weight="206 g")

    # "-" means Zoommer doesn't know it, so RAM is left out rather than stored as "-".
    assert specs_from_product_page(page) == {
        "chip": "Apple A19 Pro",
        "refresh_rate": "120 Hz",
        "weight": "206 g",
    }
    assert specs_from_product_page("<html>no specs</html>") == {}


@pytest.mark.asyncio
async def test_specs_are_fetched_once_per_model_and_served_with_ram_from_titles(
    session_factory: async_sessionmaker[AsyncSession],
    client: httpx.AsyncClient,
) -> None:
    async with session_factory() as session, session.begin():
        await ingest_zoommer(session, [
            {"name": "Apple iPhone 17 Pro | 256GB Deep Blue", "price": 3999, "url": ZOOMMER_URL},
            {"name": "Apple iPhone 17 Pro | 512GB Deep Blue", "price": 4599,
             "url": "https://zoommer.ge/mobiluri-telefonebi/apple-iphone-17-pro-512gb-p2"},
        ])
        await ingest_alta(session, [
            {"name": "Apple iPhone 17 Pro (12GB/256GB) - Deep Blue", "price": 4099,
             "url": "https://alta.ge/iphone-17-pro-256"},
        ])

    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fetched.append(str(request.url))
        return httpx.Response(200, text=spec_page(chip="Apple A19 Pro", ram="-", refresh_rate="120 Hz"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        assert await refresh_model_specs(session_factory=session_factory, client=http) == 1
        # Both storages share one model, so one page was enough; a second run fetches nothing.
        assert len(fetched) == 1
        assert await refresh_model_specs(session_factory=session_factory, client=http) == 0

    product_id = (await client.get("/products?limit=10")).json()["items"][0]["id"]
    specs = (await client.get(f"/products/{product_id}/specs")).json()
    assert specs["model"] == "iPhone 17 Pro"
    assert specs["specs"] == {"chip": "Apple A19 Pro", "refresh_rate": "120 Hz", "ram": "12 GB"}
    assert specs["source_url"] in {ZOOMMER_URL, "https://zoommer.ge/mobiluri-telefonebi/apple-iphone-17-pro-512gb-p2"}

    assert (await client.get("/products/999999/specs")).status_code == 404
