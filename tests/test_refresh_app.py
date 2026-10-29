import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.conf import settings
from app.db.models import CrawlRun, Store
from app.main import app
from app.scraper.scrape_zoommer import ZoommerCrawlError
from app.services import scraper_service
from app.services.errors import RefreshInProgressError
from app.services.scraper_service import CatalogRefreshSummary
from app.services.zmr_inges import IngestionSummary
from tests.helpers import bearer, register_and_login


def ingestion(run_id: int, scraped: int) -> IngestionSummary:
    return IngestionSummary(
        scraped=scraped,
        ingested=scraped,
        crawl_run_id=run_id,
        listings_created=1,
        listings_updated=scraped - 1,
        prices_recorded=scraped,
        crawl_run_ids=(run_id,),
    )


def catalog_summary(
    *,
    succeeded: tuple[str, ...] = ("Zoommer", "Alta", "iSpace"),
    failed: tuple[str, ...] = (),
) -> CatalogRefreshSummary:
    return CatalogRefreshSummary(
        scraped=30,
        listings_created=3,
        listings_updated=27,
        prices_recorded=12,
        crawl_run_ids=(41, 42, 43),
        succeeded_stores=succeeded,
        failed_stores=failed,
    )


async def add_crawl_run(
    session_factory: async_sessionmaker[AsyncSession],
    started_at: datetime,
) -> None:
    async with session_factory() as session:
        store = Store(title="Zoommer", web_url="https://zoommer.ge")
        session.add(store)
        await session.flush()
        session.add(
            CrawlRun(store_id=store.id, status="succeeded", started_at=started_at)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_full_catalog_refresh_isolates_store_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zoommer = AsyncMock(side_effect=ZoommerCrawlError("upstream failed"))
    alta = AsyncMock(return_value=ingestion(42, 20))
    ispace = AsyncMock(return_value=ingestion(43, 10))
    elit = AsyncMock(return_value=ingestion(44, 5))
    megatechnica = AsyncMock(side_effect=RuntimeError("layout changed"))
    monkeypatch.setattr(scraper_service, "run_zoommer_ingestion", zoommer)
    monkeypatch.setattr(scraper_service, "run_alta_ingestion", alta)
    monkeypatch.setattr(scraper_service, "run_ispace_ingestion", ispace)
    monkeypatch.setattr(scraper_service, "run_elit_ingestion", elit)
    monkeypatch.setattr(scraper_service, "run_megatechnica_ingestion", megatechnica)
    monkeypatch.setattr(scraper_service, "run_extra_ingestion", AsyncMock(return_value=ingestion(45, 4)))
    monkeypatch.setattr(scraper_service, "run_pcshop_ingestion", AsyncMock(return_value=ingestion(46, 3)))

    summary = await scraper_service.refresh_full_catalog()

    assert summary == CatalogRefreshSummary(
        scraped=42,
        listings_created=5,
        listings_updated=37,
        prices_recorded=42,
        crawl_run_ids=(42, 43, 44, 45, 46),
        succeeded_stores=("Alta", "iSpace", "Elit Electronics", "Extra.ge", "PCShop"),
        failed_stores=("Zoommer", "Megatechnica"),
    )
    for runner in (zoommer, alta, ispace, elit, megatechnica):
        runner.assert_awaited_once()


@pytest.mark.asyncio
async def test_full_catalog_refresh_rejects_concurrent_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_ingestion() -> IngestionSummary:
        started.set()
        await release.wait()
        return ingestion(1, 1)

    for name in (
        "run_zoommer_ingestion",
        "run_alta_ingestion",
        "run_ispace_ingestion",
        "run_elit_ingestion",
        "run_megatechnica_ingestion",
        "run_extra_ingestion",
        "run_pcshop_ingestion",
    ):
        monkeypatch.setattr(scraper_service, name, slow_ingestion)

    first = asyncio.create_task(scraper_service.refresh_full_catalog())
    await started.wait()
    with pytest.raises(RefreshInProgressError):
        await scraper_service.refresh_full_catalog()
    release.set()
    assert (await first).succeeded_stores == (
        "Zoommer",
        "Alta",
        "iSpace",
        "Elit Electronics",
        "Megatechnica",
        "Extra.ge",
        "PCShop",
    )


@pytest.mark.asyncio
async def test_refresh_requires_sign_in(client: httpx.AsyncClient) -> None:
    response = await client.post("/refresh")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_user_refresh_success(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = await register_and_login(client, email="shopper@example.com")
    mocked = AsyncMock(return_value=catalog_summary(succeeded=("Alta", "iSpace"), failed=("Zoommer",)))
    monkeypatch.setattr(scraper_service, "refresh_full_catalog", mocked)

    response = await client.post("/refresh", headers=bearer(token))

    assert response.status_code == 200, response.text
    assert response.json() == {
        "last_refreshed_at": None,
        "next_manual_refresh_at": None,
        "crawl_run_ids": [41, 42, 43],
        "products_found": 30,
        "listings_created": 3,
        "listings_updated": 27,
        "prices_recorded": 12,
        "succeeded_stores": ["Alta", "iSpace"],
        "failed_stores": ["Zoommer"],
    }
    mocked.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_cooldown_blocks_users_but_not_admins(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started_at = datetime.now(UTC) - timedelta(minutes=10)
    await add_crawl_run(session_factory, started_at)
    mocked = AsyncMock(return_value=catalog_summary())
    monkeypatch.setattr(scraper_service, "refresh_full_catalog", mocked)
    user_token = await register_and_login(client, email="shopper@example.com")
    admin_token = await register_and_login(
        client,
        email="admin@example.com",
        admin=True,
        session_factory=session_factory,
    )

    status = (await client.get("/refresh")).json()
    assert datetime.fromisoformat(status["last_refreshed_at"]) == started_at
    assert datetime.fromisoformat(status["next_manual_refresh_at"]) == (
        started_at + timedelta(hours=1)
    )

    blocked = await client.post("/refresh", headers=bearer(user_token))
    assert blocked.status_code == 429
    assert 49 * 60 <= int(blocked.headers["Retry-After"]) <= 50 * 60
    mocked.assert_not_awaited()

    allowed = await client.post("/refresh", headers=bearer(admin_token))
    assert allowed.status_code == 200, allowed.text
    mocked.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_allowed_after_cooldown(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await add_crawl_run(session_factory, datetime.now(UTC) - timedelta(minutes=61))
    monkeypatch.setattr(
        scraper_service,
        "refresh_full_catalog",
        AsyncMock(return_value=catalog_summary()),
    )
    token = await register_and_login(client, email="shopper@example.com")

    assert (await client.get("/refresh")).json()["next_manual_refresh_at"] is None
    response = await client.post("/refresh", headers=bearer(token))
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "status_code"),
    [
        (AsyncMock(return_value=catalog_summary(succeeded=(), failed=("Zoommer", "Alta", "iSpace"))), 502),
        (AsyncMock(side_effect=RefreshInProgressError("already running")), 409),
    ],
)
async def test_refresh_failure_mapping(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    outcome: AsyncMock,
    status_code: int,
) -> None:
    token = await register_and_login(client, email="shopper@example.com")
    monkeypatch.setattr(scraper_service, "refresh_full_catalog", outcome)
    response = await client.post("/refresh", headers=bearer(token))
    assert response.status_code == status_code


@pytest.mark.asyncio
async def test_schedule_refreshes_when_due_and_waits_otherwise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays = iter([0.0, 5.0])
    sleeps: list[float] = []
    refresh = AsyncMock(return_value=catalog_summary())

    async def seconds_until() -> float:
        return next(delays)

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(scraper_service, "_seconds_until_scheduled_refresh", seconds_until)
    monkeypatch.setattr(scraper_service, "refresh_full_catalog", refresh)
    monkeypatch.setattr(scraper_service.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await scraper_service.run_refresh_schedule()

    refresh.assert_awaited_once()
    assert sleeps == [5.0]


@pytest.mark.asyncio
async def test_schedule_backs_off_when_every_store_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(
        scraper_service,
        "_seconds_until_scheduled_refresh",
        AsyncMock(return_value=0.0),
    )
    monkeypatch.setattr(
        scraper_service,
        "refresh_full_catalog",
        AsyncMock(return_value=catalog_summary(succeeded=(), failed=("Zoommer",))),
    )
    monkeypatch.setattr(scraper_service.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await scraper_service.run_refresh_schedule()

    assert sleeps == [3600.0]


@pytest.mark.asyncio
async def test_lifespan_disposes_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    dispose = AsyncMock()
    monkeypatch.setattr("app.main.engine", SimpleNamespace(dispose=dispose))
    settings.jwt_secret()
    async with app.router.lifespan_context(app):
        pass
    dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_starts_and_cancels_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def schedule() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr("app.main.engine", SimpleNamespace(dispose=AsyncMock()))
    monkeypatch.setattr("app.main.run_refresh_schedule", schedule)
    monkeypatch.setattr(settings, "REFRESH_SCHEDULER_ENABLED", True)

    async with app.router.lifespan_context(app):
        await started.wait()

    assert cancelled.is_set()


def test_openapi_contains_all_requested_routes():
    expected = {
        "/",
        "/auth/register",
        "/auth/login",
        "/search",
        "/products",
        "/products/{product_id}",
        "/products/{product_id}/listings",
        "/products/{product_id}/prices",
        "/products/{product_id}/prices/extremes",
        "/tracked-products",
        "/tracked-products/{product_id}",
        "/products/{product_id}/alerts",
        "/alerts",
        "/alerts/{alert_id}",
        "/notification-settings/email",
        "/notification-settings/email/test",
        "/notification-settings/email/verification",
        "/notification-settings/email/verify",
        "/refresh",
    }
    assert set(app.openapi()["paths"]) == expected
