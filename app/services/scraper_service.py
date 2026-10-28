import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CrawlRun
from app.db.sess import SESSION
from app.services.errors import RefreshCooldownError, RefreshInProgressError
from app.services.zmr_inges import (
    IngestionSummary,
    run_alta_ingestion,
    run_elit_ingestion,
    run_extra_ingestion,
    run_ispace_ingestion,
    run_megatechnica_ingestion,
    run_pcshop_ingestion,
    run_zoommer_ingestion,
)

SCHEDULED_REFRESH_INTERVAL = timedelta(hours=12)
MANUAL_REFRESH_COOLDOWN = timedelta(hours=1)
LOGGER = logging.getLogger(__name__)

_refresh_lock = asyncio.Lock()


@dataclass(frozen=True, slots=True)
class CatalogRefreshSummary:
    scraped: int
    listings_created: int
    listings_updated: int
    prices_recorded: int
    crawl_run_ids: tuple[int, ...]
    succeeded_stores: tuple[str, ...]
    failed_stores: tuple[str, ...]


def _store_runners() -> tuple[tuple[str, Callable[[], Awaitable[IngestionSummary]]], ...]:
    return (
        ("Zoommer", run_zoommer_ingestion),
        ("Alta", run_alta_ingestion),
        ("iSpace", run_ispace_ingestion),
        ("Elit Electronics", run_elit_ingestion),
        ("Megatechnica", run_megatechnica_ingestion),
        ("Extra.ge", run_extra_ingestion),
        ("PCShop", run_pcshop_ingestion),
    )


async def refresh_full_catalog() -> CatalogRefreshSummary:
    # Sequential so alert checks never race.
    if _refresh_lock.locked():
        raise RefreshInProgressError("A catalog refresh is already running")

    async with _refresh_lock:
        summaries: list[IngestionSummary] = []
        succeeded: list[str] = []
        failed: list[str] = []

        for store_title, run_ingestion in _store_runners():
            try:
                summaries.append(await run_ingestion())
                succeeded.append(store_title)
            except Exception:
                LOGGER.exception("%s refresh failed", store_title)
                failed.append(store_title)

    return CatalogRefreshSummary(
        scraped=sum(summary.scraped for summary in summaries),
        listings_created=sum(summary.listings_created for summary in summaries),
        listings_updated=sum(summary.listings_updated for summary in summaries),
        prices_recorded=sum(summary.prices_recorded for summary in summaries),
        crawl_run_ids=tuple(
            run_id for summary in summaries for run_id in summary.crawl_run_ids
        ),
        succeeded_stores=tuple(succeeded),
        failed_stores=tuple(failed),
    )


async def last_refresh_started_at(session: AsyncSession) -> datetime | None:
    started_at = await session.scalar(select(func.max(CrawlRun.started_at)))
    if started_at is not None and started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    return started_at


async def next_manual_refresh_at(session: AsyncSession) -> datetime | None:
    started_at = await last_refresh_started_at(session)
    if started_at is None:
        return None
    available_at = started_at + MANUAL_REFRESH_COOLDOWN
    return available_at if available_at > datetime.now(UTC) else None


async def request_manual_refresh(
    session: AsyncSession,
    *,
    bypass_cooldown: bool = False,
) -> CatalogRefreshSummary:
    if not bypass_cooldown:
        available_at = await next_manual_refresh_at(session)
        if available_at is not None:
            raise RefreshCooldownError(available_at)
    return await refresh_full_catalog()


async def _seconds_until_scheduled_refresh() -> float:
    async with SESSION() as session:
        started_at = await last_refresh_started_at(session)
    if started_at is None:
        return 0
    due_at = started_at + SCHEDULED_REFRESH_INTERVAL
    return max(0.0, (due_at - datetime.now(UTC)).total_seconds())


async def run_refresh_schedule() -> None:
    while True:
        try:
            delay = await _seconds_until_scheduled_refresh()
            if delay:
                await asyncio.sleep(delay)
                continue
            summary = await refresh_full_catalog()
            LOGGER.info("Scheduled refresh finished: %s", asdict(summary))
            if not summary.succeeded_stores:
                await asyncio.sleep(MANUAL_REFRESH_COOLDOWN.total_seconds())
        except asyncio.CancelledError:
            raise
        except RefreshInProgressError:
            await asyncio.sleep(60)
        except Exception:
            LOGGER.exception("Scheduled refresh failed")
            await asyncio.sleep(MANUAL_REFRESH_COOLDOWN.total_seconds())


def main() -> None:
    print(asdict(asyncio.run(refresh_full_catalog())))


if __name__ == "__main__":
    main()
