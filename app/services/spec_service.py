"""Phone specifications per model, taken from Zoommer's product pages, for the compare page."""

import logging
import re
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.db_schemas import ProductSpecsResponse
from app.db.models import ModelSpecs, Product, ProductListing, Store
from app.db.sess import SESSION
from app.scraper.http import browser_client
from app.scraper.zoommer_specs import ZoommerSpecsError, scrape_zoommer_specs
from app.services.product_service import require_active_product

LOGGER = logging.getLogger(__name__)
# Specs don't change after release; refetch rarely in case a store fills in blanks.
SPECS_MAX_AGE = timedelta(days=30)
SPEC_SOURCE_STORE = "Zoommer"
# RAM as stores write it in titles: "(12GB/512GB)", "8/256GB", "12/512GB".
RAM_IN_TITLE = re.compile(r"\b(\d{1,2})\s*(?:GB)?\s*/\s*\d{2,4}\s*(?:GB|TB)\b", re.IGNORECASE)
PLAUSIBLE_RAM_GB = range(2, 33)


async def models_needing_specs(session: AsyncSession) -> list[tuple[str, str]]:
    """One Zoommer page per model whose specs are missing or older than SPECS_MAX_AGE."""
    cutoff = datetime.now(UTC) - SPECS_MAX_AGE
    rows = await session.execute(
        select(Product.model, func.min(ProductListing.product_url))
        .join(ProductListing, ProductListing.product_id == Product.id)
        .join(Store, Store.id == ProductListing.store_id)
        .outerjoin(ModelSpecs, ModelSpecs.model == Product.model)
        .where(
            Store.title == SPEC_SOURCE_STORE,
            Product.is_active.is_(True),
            ProductListing.is_active.is_(True),
            or_(ModelSpecs.id.is_(None), ModelSpecs.fetched_at < cutoff),
        )
        .group_by(Product.model)
        .order_by(Product.model)
    )
    return [(model, url) for model, url in rows]


async def save_model_specs(session: AsyncSession, model: str, specs: dict[str, str], url: str) -> None:
    row = await session.scalar(select(ModelSpecs).where(ModelSpecs.model == model))
    if row is None:
        session.add(ModelSpecs(model=model, specs=specs, source_url=url))
    else:
        row.specs = specs
        row.source_url = url
        row.fetched_at = datetime.now(UTC)
    await session.flush()


async def refresh_model_specs(
    *,
    session_factory=SESSION,
    client: httpx.AsyncClient | None = None,
) -> int:
    """Fetch specs for models that lack them; returns how many models were saved."""
    async with session_factory() as session:
        targets = await models_needing_specs(session)
    saved = 0
    async with nullcontext(client) if client is not None else browser_client(proxied=True) as http:
        for model, url in targets:
            try:
                specs = await scrape_zoommer_specs(http, url)
            except ZoommerSpecsError:
                LOGGER.warning("Could not fetch specs for %s from %s", model, url)
                continue
            if not specs:
                LOGGER.warning("No specs found for %s on %s; the page layout may have changed", model, url)
                continue
            async with session_factory() as session, session.begin():
                await save_model_specs(session, model, specs, url)
            saved += 1
    return saved


async def get_product_specs(session: AsyncSession, product_id: int) -> ProductSpecsResponse:
    product = await require_active_product(session, product_id)
    row = await session.scalar(select(ModelSpecs).where(ModelSpecs.model == product.model))
    specs = dict(row.specs) if row else {}
    if "ram" not in specs:
        # Zoommer often leaves RAM blank; other stores put it in their titles.
        titles = await session.scalars(
            select(ProductListing.variant_name)
            .join(Product, Product.id == ProductListing.product_id)
            .where(Product.model == product.model, ProductListing.variant_name.is_not(None))
        )
        for title in titles:
            match = RAM_IN_TITLE.search(title)
            if match and int(match.group(1)) in PLAUSIBLE_RAM_GB:
                specs["ram"] = f"{int(match.group(1))} GB"
                break
    return ProductSpecsResponse(
        product_id=product.id,
        model=product.model,
        storage=product.storage,
        specs=specs,
        source_url=row.source_url if row else None,
        fetched_at=row.fetched_at if row else None,
    )
