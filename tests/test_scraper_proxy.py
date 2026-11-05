import asyncio
import importlib

import pytest
from pydantic import SecretStr

from app.scraper import http, scrape_alta

PROXY = "http://user:pass@proxy.example:8000"


def _capture_client_kwargs(monkeypatch) -> list[dict]:
    calls: list[dict] = []
    monkeypatch.setattr(http.httpx, "AsyncClient", lambda **kwargs: calls.append(kwargs))
    return calls


def test_proxied_client_uses_scraper_proxy(monkeypatch):
    monkeypatch.setattr(http.settings, "SCRAPER_PROXY_URL", SecretStr(PROXY))
    calls = _capture_client_kwargs(monkeypatch)

    http.browser_client(proxied=True)
    http.browser_client()

    assert calls[0]["proxy"] == PROXY
    assert calls[1]["proxy"] is None


def test_proxied_client_goes_direct_without_proxy_setting(monkeypatch):
    monkeypatch.setattr(http.settings, "SCRAPER_PROXY_URL", None)
    calls = _capture_client_kwargs(monkeypatch)

    http.browser_client(proxied=True)

    assert calls[0]["proxy"] is None


def test_alta_scraper_uses_scraper_proxy(monkeypatch):
    class FakeScraper:
        proxies: dict = {}

    fake = FakeScraper()
    monkeypatch.setattr(http.settings, "SCRAPER_PROXY_URL", SecretStr(PROXY))
    monkeypatch.setattr(scrape_alta.cloudscraper, "create_scraper", lambda **_: fake)
    monkeypatch.setattr(scrape_alta, "_scrape_price_windows", lambda fetch: [])

    scrape_alta.scrape_alta()

    assert fake.proxies == {"http": PROXY, "https": PROXY}


class _Stop(Exception):
    pass


@pytest.mark.parametrize(
    ("module_name", "function_name", "proxied"),
    [
        ("scrape_zoommer", "scrape_zoommer", True),
        ("scrape_ispace", "scrape_ispace", True),
        ("scrape_elit", "scrape_elit", True),
        ("scrape_pcshop", "scrape_pcshop", True),
        ("scrape_kontakt", "scrape_kontakt", True),
        ("scrape_gstore", "scrape_gstore", False),
        ("scrape_icity", "scrape_icity", False),
        ("scrape_extra", "scrape_extra", False),
        ("scrape_megatechnica", "scrape_megatechnica", False),
        ("scrape_metromart", "scrape_metromart", False),
    ],
)
def test_only_cloudflare_stores_use_the_proxy(monkeypatch, module_name, function_name, proxied):
    # Only the stores that block datacenter IPs spend proxy traffic.
    module = importlib.import_module(f"app.scraper.{module_name}")
    requested: list[bool] = []

    def fake_client(*, proxied: bool = False):
        requested.append(proxied)
        raise _Stop

    monkeypatch.setattr(module, "browser_client", fake_client)

    with pytest.raises(_Stop):
        asyncio.run(getattr(module, function_name)())

    assert requested == [proxied]
