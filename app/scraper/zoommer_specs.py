"""Phone specifications from a Zoommer product page.

The page embeds its spec table as JSON ("specificationGroup": [{groupName,
specifications: [{specificationName, specificationMeaning}]}]) with Georgian
names; this maps the ones the compare page uses onto stable English keys.
"""

import json

import httpx

from app.scraper.http import fetch_with_retries

SPEC_GROUP_KEY = '"specificationGroup":'
# Zoommer's Georgian spec name -> our key.
SPEC_KEYS = {
    "ჩიპსეტი": "chip",
    "ოპერატიული მეხსიერება": "ram",
    "ეკრანის ზომა": "display_size",
    "რეზოლუცია": "resolution",
    "განახლების სიხშირე": "refresh_rate",
    "ეკრანის სიკაშკაშე": "brightness",
    "ეკრანის ტიპი": "display_type",
    "ძირითადი კამერა": "main_camera",
    "დამატებითი კამერა": "extra_cameras",
    "წინა კამერა": "front_camera",
    "ძირითადი კამერის ვიდეო რეზოლუცია": "video",
    "ელემენტი": "battery",
    "დამუხტვის სიჩქარე": "charging",
    "უსადენოდ დამუხტვის სიჩქარე": "wireless_charging",
    "წონა": "weight",
    "IP დაცვა": "water_resistance",
    "გამოშვების თარიღი": "release_year",
    "დასამუხტი პორტი": "port",
}
# Zoommer writes "-" for specs it doesn't know.
MISSING_VALUES = {"", "-", "—"}


class ZoommerSpecsError(RuntimeError):
    """Raised when a Zoommer product page cannot be fetched."""


def specs_from_product_page(html: str) -> dict[str, str]:
    start = html.find(SPEC_GROUP_KEY)
    if start < 0:
        return {}
    try:
        groups, _ = json.JSONDecoder().raw_decode(html, start + len(SPEC_GROUP_KEY))
    except json.JSONDecodeError:
        return {}
    if not isinstance(groups, list):
        return {}

    specs: dict[str, str] = {}
    for group in groups:
        for spec in (group or {}).get("specifications") or []:
            key = SPEC_KEYS.get(str(spec.get("specificationName", "")).strip())
            value = str(spec.get("specificationMeaning") or "").strip()
            if key and value not in MISSING_VALUES and key not in specs:
                specs[key] = value
    return specs


async def scrape_zoommer_specs(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_attempts: int = 2,
    backoff_seconds: float = 1.0,
    request_delay_seconds: float = 0.5,
) -> dict[str, str]:
    response = await fetch_with_retries(
        client,
        url,
        store="Zoommer",
        error_type=ZoommerSpecsError,
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
        request_delay_seconds=request_delay_seconds,
    )
    return specs_from_product_page(response.text)
