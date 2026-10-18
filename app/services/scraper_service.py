import asyncio
from dataclasses import asdict

from app.services.zmr_inges import (
    IngestionSummary,
    run_alta_ingestion,
    run_zoommer_ingestion,
)


async def refresh_full_catalog() -> IngestionSummary:
    """Refresh the catalog from every configured retailer."""
    summaries = [
        await run_zoommer_ingestion(),
        await run_alta_ingestion(),
    ]
    run_ids = tuple(
        run_id
        for summary in summaries
        for run_id in (
            summary.crawl_run_ids
            or ((summary.crawl_run_id,) if summary.crawl_run_id else ())
        )
    )
    return IngestionSummary(
        scraped=sum(summary.scraped for summary in summaries),
        ingested=sum(summary.ingested for summary in summaries),
        crawl_run_id=run_ids[0] if run_ids else None,
        listings_created=sum(summary.listings_created for summary in summaries),
        listings_updated=sum(summary.listings_updated for summary in summaries),
        prices_recorded=sum(summary.prices_recorded for summary in summaries),
        crawl_run_ids=run_ids,
    )


def main() -> None:
    print(asdict(asyncio.run(refresh_full_catalog())))


if __name__ == "__main__":
    main()
