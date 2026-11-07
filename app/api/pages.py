"""The HTML entry page, with link-preview tags filled in on the server, and the sitemap.

Facebook, Messenger and search engines read the page without running JavaScript, so
the title, description and preview image of a shared phone link, and the Today page's
cheapest price per model, are written here.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from html import escape, unescape
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conf import settings
from app.db.db_schemas import ProductSummary
from app.db.models import Product
from app.dependencies import SessionDep
from app.services import product_service, scraper_service
from app.services.errors import NotFoundError

router = APIRouter(include_in_schema=False)

INDEX_PATH = Path(__file__).resolve().parent.parent / "static" / "index.html"
META_MARKER = "<!--server-meta-->"
MODELS_MARKER = '<ul id="modelPrices" class="model-prices" aria-live="polite"><!--server-models--></ul>'
MODELS_TOGGLE = (
    '<button class="fold-toggle" id="modelPricesToggle" type="button" '
    'aria-controls="modelPrices" aria-expanded="false" hidden><span></span>'
)
INTRO_TITLE = '<h1 id="overviewTitle" data-i18n="intro.title">iPhone-ის ფასები საქართველოში</h1>'
INTRO_STATS = '<p class="intro-stats" id="overviewStats" role="status"></p>'
# The headline's phone: the newest standard model (e.g. "iPhone 17"), the one most people buy.
HEADLINE_MODEL = re.compile(r"iPhone \d+")
# Same as catalog.js: the Today list starts folded to the newest few models.
MODELS_FOLDED = 6
TITLE_PATTERN = re.compile(r"<title>(.*?)</title>", re.DOTALL)
DESCRIPTION_PATTERN = re.compile(r'<meta name="description" content="([^"]*)">')
NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}


def _price(value: Decimal, currency: str | None = "GEL") -> str:
    # "3,199 ₾" like the page itself; tetri only when there are any.
    amount = f"{value:,.0f}" if value == value.to_integral() else f"{value:,.2f}"
    return f"{amount} ₾" if currency in (None, "GEL") else f"{amount} {currency}"


def _natural_key(text: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def _by_model(products: list[ProductSummary]) -> list[ProductSummary]:
    # catalog.js byModel: newest generation first, a model before its eSIM one.
    by_esim = sorted(products, key=lambda product: product.model.endswith(" eSIM"))
    return sorted(
        by_esim,
        key=lambda product: _natural_key(product.model.removesuffix(" eSIM").strip()),
        reverse=True,
    )


def _phone_name(product: ProductSummary) -> str:
    model = product.model.strip()
    return model if re.match(r"iphone\b", model, re.IGNORECASE) else f"iPhone {model}"


def _model_row(product: ProductSummary, *, hidden: bool) -> str:
    # The same markup catalog.js renderOverview writes, in Georgian.
    variant = " · ".join(part for part in (product.storage, product.color) if part)
    meta = f"მარაგშია {product.available_listing_count} მაღაზიაში"
    week_ago = product.price_week_ago
    if week_ago is not None and week_ago - product.lowest_price >= week_ago * Decimal("0.01"):
        drop = _price(week_ago - product.lowest_price, product.currency)
        meta += f' · <span class="card-change drop">{escape(f"−{drop} ამ კვირაში")}</span>'
    return (
        f'<li class="model-price" data-model="{escape(product.model)}" '
        f'data-product-id="{product.id}" tabindex="0"{" hidden" if hidden else ""}>'
        f'<span class="model-price-name">{escape(_phone_name(product))}'
        f"<small>{escape(variant or 'მეხსიერება და ფერი მითითებული არ არის')}</small></span>"
        f'<span class="model-price-value">{escape(_price(product.lowest_price, product.currency))}</span>'
        f'<span class="model-price-meta">{meta}</span></li>'
    )


def _render_models(html: str, models: list[ProductSummary]) -> str:
    """Fill the Today list so crawlers see every model's price; the rows past the fold are hidden."""
    if not models:
        return html
    models = _by_model(models)
    rows = "".join(
        _model_row(product, hidden=index >= MODELS_FOLDED) for index, product in enumerate(models)
    )
    html = html.replace(
        MODELS_MARKER,
        '<ul id="modelPrices" class="model-prices" aria-live="polite" data-server-rendered>'
        f"{rows}</ul>",
        1,
    )
    if len(models) > MODELS_FOLDED:
        html = html.replace(
            MODELS_TOGGLE,
            MODELS_TOGGLE.replace(" hidden><span></span>", f"><span>ყველა {len(models)} მოდელის ჩვენება</span>"),
            1,
        )
    return html


@dataclass(frozen=True, slots=True)
class Intro:
    """The Today headline's data; catalog.js formats it again in the reader's language."""

    model: str
    price: Decimal
    store: str
    models: int
    stores: int
    checked_at: datetime | None


def _headline_product(models: Sequence[ProductSummary]) -> ProductSummary | None:
    standard = [product for product in models if HEADLINE_MODEL.fullmatch(product.model)]
    ranked = _by_model(standard or list(models))
    return ranked[0] if ranked else None


def _render_intro(html: str, intro: Intro | None) -> str:
    if intro is None:
        return html
    title = f"{intro.model} დღეს ყველაზე იაფია {intro.store}-ში: {_price(intro.price)}"
    html = html.replace(
        INTRO_TITLE,
        f'<h1 id="overviewTitle" data-model="{escape(intro.model)}" data-price="{intro.price}" '
        f'data-store="{escape(intro.store)}">{escape(title)}</h1>',
        1,
    )
    checked = f' data-checked="{intro.checked_at.isoformat()}"' if intro.checked_at else ""
    return html.replace(
        INTRO_STATS,
        f'<p class="intro-stats" id="overviewStats" role="status" data-models="{intro.models}" '
        f'data-stores="{intro.stores}"{checked}>{intro.models} მოდელი · {intro.stores} მაღაზია</p>',
        1,
    )


async def _load_intro(session: AsyncSession, models: Sequence[ProductSummary]) -> Intro | None:
    product = _headline_product(models)
    if product is None:
        return None
    cheapest = await product_service.list_product_listings(
        session, product_id=product.id, limit=1, offset=0
    )
    if not cheapest.items:
        return None
    return Intro(
        model=_phone_name(product),
        price=product.lowest_price,
        store=cheapest.items[0].store_name,
        models=len(models),
        stores=await product_service.count_stores_in_stock(session),
        checked_at=await scraper_service.last_refresh_started_at(session),
    )


def _product_url(product_id: int) -> str:
    return f"{settings.public_base_url}/?page=products&id={product_id}"


def _product_preview(product: ProductSummary) -> tuple[str, str]:
    name = " ".join(part for part in (product.model, product.storage, product.color) if part)
    if product.available_listing_count and product.lowest_price is not None:
        price = _price(product.lowest_price)
        title = f"{name} — {price}"
        description = (
            f"ყველაზე დაბალი ფასი საქართველოში: {price}, "
            f"{product.available_listing_count} მაღაზიაში მარაგშია. "
            "ფასის ისტორია და შეტყობინება ფასის დაკლებისას."
        )
    else:
        title = name
        description = (
            "ამჟამად მარაგში არ არის. ფასის ისტორია და შეტყობინება, "
            "როცა მარაგში დაბრუნდება."
        )
    return title, description


def _meta_tags(*, title: str, description: str, url: str, image: str) -> str:
    tags = {
        "og:type": "website",
        "og:site_name": "iPhone Tracker.ge",
        "og:title": title,
        "og:description": description,
        "og:url": url,
        "og:image": image,
    }
    lines = [f'<meta property="{key}" content="{escape(value)}">' for key, value in tags.items()]
    lines.append('<meta name="twitter:card" content="summary_large_image">')
    lines.append(f'<link rel="canonical" href="{escape(url)}">')
    return "\n  ".join(lines)


def render_index(
    product: ProductSummary | None,
    models: Sequence[ProductSummary] = (),
    intro: Intro | None = None,
) -> str:
    html = _render_models(INDEX_PATH.read_text(encoding="utf-8"), list(models))
    html = _render_intro(html, intro)
    base = settings.public_base_url
    if product is None:
        # index.html's own title and description are already escaped HTML.
        title = unescape(TITLE_PATTERN.search(html).group(1))
        description = unescape(DESCRIPTION_PATTERN.search(html).group(1))
        meta = _meta_tags(
            title=title,
            description=description,
            url=f"{base}/",
            image=f"{base}/static/logo.png",
        )
        return html.replace(META_MARKER, meta, 1)

    title, description = _product_preview(product)
    html = TITLE_PATTERN.sub(f"<title>{escape(title)} — iPhone Tracker</title>", html, count=1)
    html = DESCRIPTION_PATTERN.sub(
        f'<meta name="description" content="{escape(description)}">', html, count=1
    )
    meta = _meta_tags(
        title=title,
        description=description,
        url=_product_url(product.id),
        image=product.image_url or f"{base}/static/logo.png",
    )
    return html.replace(META_MARKER, meta, 1)


@router.get("/", response_class=HTMLResponse)
async def index(session: SessionDep, page: str | None = None, id: str | None = None) -> HTMLResponse:
    product = None
    if page == "products" and id and id.isdigit():
        try:
            product = await product_service.get_product_summary(session, int(id))
        except NotFoundError:
            product = None
    models = await product_service.cheapest_in_stock_per_model(session)
    intro = await _load_intro(session, models)
    return HTMLResponse(render_index(product, models, intro), headers=NO_CACHE)


@router.get("/sitemap.xml")
async def sitemap(session: SessionDep) -> Response:
    base = settings.public_base_url
    product_ids = (
        await session.scalars(
            select(Product.id).where(Product.is_active.is_(True)).order_by(Product.id)
        )
    ).all()
    urls = [f"{base}/", f"{base}/?page=products", f"{base}/?page=compare"]
    urls += [_product_url(product_id) for product_id in product_ids]
    body = "\n".join(f"  <url><loc>{xml_escape(url)}</loc></url>" for url in urls)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n</urlset>\n"
    )
    return Response(xml, media_type="application/xml")


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
