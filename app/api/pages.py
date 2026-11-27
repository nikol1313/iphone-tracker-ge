"""The HTML entry page, with link-preview tags filled in on the server, and the sitemap.

Facebook, Messenger and search engines read the page without running JavaScript, so
the title, description and preview image of a shared phone link, and the Today page's
cheapest price per model, are written here.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from html import escape, unescape
from itertools import pairwise
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conf import settings
from app.db.db_schemas import ProductSummary
from app.db.models import Product
from app.dependencies import SessionDep
from app.services import product_service, scraper_service
from app.services.errors import NotFoundError
from app.services.normalization import product_slug

router = APIRouter(include_in_schema=False)

INDEX_PATH = Path(__file__).resolve().parent.parent / "static" / "index.html"
# Store icons saved as static/img/stores/<slug>.png, e.g. "Extra.ge" -> extra-ge.png.
STORE_LOGOS_DIR = INDEX_PATH.parent / "img" / "stores"
STORE_LOGOS = frozenset(path.stem for path in STORE_LOGOS_DIR.glob("*.png"))
NOT_FOUND_PATH = INDEX_PATH.with_name("404.html")
# A phone's own address, e.g. /iphone-17-pro-256gb-silver; core.js matches the same shape.
PRODUCT_SLUG = re.compile(r"iphone-[a-z0-9-]+")
META_MARKER = "<!--server-meta-->"
MODELS_MARKER = '<ul id="modelPrices" class="model-prices" aria-live="polite"><!--server-models--></ul>'
MODELS_TOGGLE = (
    '<button class="fold-toggle" id="modelPricesToggle" type="button" '
    'aria-controls="modelPrices" aria-expanded="false" hidden><span></span>'
)
INTRO_TITLE = '<h1 id="overviewTitle" data-i18n="intro.title">iPhone-ის ფასები საქართველოში</h1>'
INTRO_STATS = '<p class="intro-stats" id="overviewStats" role="status"></p>'
INTRO_TREND = '<figure class="intro-trend" id="introTrend" hidden></figure>'
INTRO_STORES = '<table class="intro-stores" id="introStores" hidden></table>'
INTRO_INSIGHTS = '<ul class="intro-insights" id="introInsights" hidden></ul>'
# The chart under the headline: the model's best price over this window.
TREND_WINDOW = timedelta(days=30)
# "Lowest price in N days" needs at least this much history to mean anything.
INSIGHT_MIN_DAYS = 7
WEEKDAYS_KA = ("ორშაბათობით", "სამშაბათობით", "ოთხშაბათობით", "ხუთშაბათობით", "პარასკევობით", "შაბათობით", "კვირაობით")
# The headline's phone: the newest standard model (e.g. "iPhone 17"), the one most people buy.
HEADLINE_MODEL = re.compile(r"iPhone \d+")
# Same as catalog.js: the Today list starts folded to the newest few models.
MODELS_FOLDED = 6
TITLE_PATTERN = re.compile(r"<title>(.*?)</title>", re.DOTALL)
DESCRIPTION_PATTERN = re.compile(r'<meta name="description" content="([^"]*)">')
NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}


def _price(value: Decimal, currency: str | None = "GEL") -> str:
    # "3,199 ₾" like the page itself: whole lari, as core.js money() rounds them.
    amount = f"{value.quantize(Decimal(1), ROUND_HALF_UP):,.0f}"
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


def _percent(change: Decimal, base: Decimal) -> str:
    # Same as catalog.js percent(): "9%", or "<1%" for a move that rounds to nothing.
    share = int((abs(change) * 100 / base).quantize(Decimal(1), ROUND_HALF_UP))
    return f"{share}%" if share else "<1%"


def _row_photo(image_url: str | None) -> str:
    # Same as catalog.js rowPhoto: the store's photo, or an empty frame to keep rows aligned.
    if not image_url or not image_url.startswith(("https://", "http://")):
        return '<span class="row-photo"></span>'
    return (
        f'<span class="row-photo"><img src="{escape(image_url)}" alt="" loading="lazy" '
        'referrerpolicy="no-referrer"></span>'
    )


def _model_row(product: ProductSummary, *, hidden: bool) -> str:
    # The same markup catalog.js renderOverview writes, in Georgian.
    color = (
        f'<span class="color-name"><span class="swatch" data-color="{escape(product.color)}" '
        f'aria-hidden="true"></span>{escape(product.color)}</span>'
        if product.color
        else ""
    )
    variant = " · ".join(part for part in (escape(product.storage or ""), color) if part)
    meta = (
        f"{variant or 'მეხსიერება და ფერი მითითებული არ არის'}"
        f" · {product.available_listing_count} მაღაზია"
    )
    pill = ""
    week_ago = product.price_week_ago
    if week_ago is not None and week_ago - product.lowest_price >= week_ago * Decimal("0.01"):
        change = week_ago - product.lowest_price
        drop = f"−{_price(change, product.currency)} · −{_percent(change, week_ago)}"
        pill = f'<span class="change-pill drop">{escape(drop)}</span>'
    return (
        f'<li class="model-price" data-model="{escape(product.model)}" '
        f'data-product-id="{product.id}" tabindex="0"{" hidden" if hidden else ""}>'
        f"{_row_photo(product.image_url)}"
        f'<span class="model-price-name">{escape(_phone_name(product))}</span>'
        f'<span class="model-price-meta">{meta}</span>{pill}'
        f'<span class="model-price-value">{escape(_price(product.lowest_price, product.currency))}</span></li>'
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
    # (day end, the model's best price), for each of the last TREND_WINDOW days, oldest first.
    history: Sequence[tuple[datetime, Decimal]] = ()
    storage: str | None = None
    # (store, cheapest in-stock price, its page) for the headline's model and storage, cheapest first.
    store_prices: Sequence[tuple[str, Decimal, str]] = ()
    # (store, weekday with Monday = 0) when one store's price cuts cluster on a weekday.
    drop_weekday: tuple[str, int] | None = None


def _store_logo(store: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", store.casefold()).strip("-")
    if slug not in STORE_LOGOS:
        return ""
    return f'<img class="store-logo" src="/static/img/stores/{slug}.png" alt="" width="18" height="18">'


def _store_table(intro: Intro) -> str:
    """Every store's price for the headline phone, with each one's gap to the cheapest."""
    cheapest = intro.store_prices[0][1]
    spread = max(price for _, price, _ in intro.store_prices) - cheapest

    def place(price: Decimal, url: str) -> str:
        # Where this store sits between today's cheapest (0%) and priciest (100%),
        # and, on hover, a box that opens the phone on the store's site.
        pos = (price - cheapest) / spread * 100 if spread else 0
        link = (
            f'<a class="store-go" href="{escape(url)}" target="_blank" rel="noopener noreferrer nofollow" '
            '><span data-i18n="intro.openStore">საიტზე გადასვლა</span></a>'
            if url.startswith(("https://", "http://"))
            else ""
        )
        return (
            f'<td class="intro-store-range"><span class="spread"><i style="--pos:{pos:.0f}%"></i></span>'
            f"{link}</td>"
        )

    rows = "".join(
        f'<tr tabindex="0"><th scope="row">{_store_logo(store)}{escape(store)}</th>'
        f'<td class="intro-store-price">{escape(_price(price))}</td>'
        + (
            f'<td class="intro-store-gap">+{escape(_price(price - cheapest))}</td>'
            if price > cheapest
            else '<td class="intro-store-gap best" data-i18n="intro.cheapest">ყველაზე იაფი</td>'
        )
        + place(price, url)
        + "</tr>"
        # The headline's store leads a tie for cheapest, as the headline names it.
        for store, price, url in sorted(intro.store_prices, key=lambda row: (row[1], row[0] != intro.store))
    )
    caption = " ".join(part for part in (intro.model, intro.storage) if part)
    return f'<table class="intro-stores" id="introStores"><caption>{escape(caption)}</caption><tbody>{rows}</tbody></table>'


def _moves_ka(days: int, up: int, down: int) -> str:
    # Mirrors i18n.js "intro.moves".
    parts = [f"{up}-ჯერ გაძვირდა"] * bool(up) + [f"{down}-ჯერ გაიაფდა"] * bool(down)
    return f"ბოლო {days} დღეში {' და '.join(parts)}"


def _insights(intro: Intro) -> list[tuple[dict[str, str | int], str]]:
    """What only the price history shows: (data for catalog.js, the Georgian sentence)."""
    found: list[tuple[dict[str, str | int], str]] = []
    prices = [price for _, price in intro.history]
    if len(prices) >= 2:
        days = (intro.history[-1][0] - intro.history[0][0]).days + 1
        if days >= INSIGHT_MIN_DAYS and min(prices) < max(prices) and intro.price <= min(prices):
            found.append(({"insight": "low", "days": days}, f"{days} დღის ყველაზე დაბალი ფასი"))
        up = sum(after > before for before, after in pairwise(prices))
        down = sum(after < before for before, after in pairwise(prices))
        if up or down:
            found.append(({"insight": "moves", "days": days, "up": up, "down": down}, _moves_ka(days, up, down)))
    if intro.drop_weekday:
        store, weekday = intro.drop_weekday
        found.append((
            {"insight": "weekday", "store": store, "day": weekday},
            f"{store} ფასებს ჩვეულებრივ {WEEKDAYS_KA[weekday]} აკლებს",
        ))
    return found


def _chart_series(history: Sequence[tuple[datetime, Decimal]]) -> str:
    """The best price at each change, as catalog.js renderTrend draws it."""
    points: list[dict[str, str]] = []
    for at, price in history:
        if not points or Decimal(points[-1]["price"]) != price:
            points.append({"recorded_at": at.isoformat(), "price": str(price)})
    return json.dumps(points)


def _headline_product(models: Sequence[ProductSummary]) -> ProductSummary | None:
    standard = [product for product in models if HEADLINE_MODEL.fullmatch(product.model)]
    ranked = _by_model(standard or list(models))
    return ranked[0] if ranked else None


def _render_intro(html: str, intro: Intro | None) -> str:
    if intro is None:
        return html
    # Non-breaking space keeps "2,799 ₾" together when the headline wraps.
    price = _price(intro.price).replace(" ", "\u00a0")
    title = f"{intro.model} დღეს ყველაზე იაფია {intro.store}-ში: {price}"
    html = html.replace(
        INTRO_TITLE,
        f'<h1 id="overviewTitle" data-model="{escape(intro.model)}" data-price="{intro.price}" '
        f'data-store="{escape(intro.store)}">{escape(title)}</h1>',
        1,
    )
    if intro.store_prices:
        html = html.replace(INTRO_STORES, _store_table(intro), 1)
    insights = _insights(intro)
    insights_html = (
        '<ul class="intro-insights" id="introInsights">'
        + "".join(
            "<li"
            + "".join(f' data-{key}="{escape(str(value))}"' for key, value in data.items())
            + f">{escape(text)}</li>"
            for data, text in insights
        )
        + "</ul>"
        if insights
        else ""
    )
    if len(intro.history) >= 2:
        # The insights read as the chart's footer, so they move inside its card.
        prices = [price for _, price in intro.history]
        low, high = min(prices), max(prices)
        html = html.replace(
            INTRO_TREND,
            f'<figure class="intro-trend" id="introTrend" data-low="{low}" data-high="{high}" '
            f'data-series="{escape(_chart_series(intro.history))}">'
            '<svg id="introChart" class="intro-chart" role="img" aria-labelledby="introTrendCaption"></svg>'
            f'<figcaption id="introTrendCaption">ბოლო 30 დღე · მინ. {escape(_price(low))} · '
            f"მაქს. {escape(_price(high))}</figcaption>{insights_html}</figure>",
            1,
        )
        html = html.replace(INTRO_INSIGHTS, "", 1)
    elif insights_html:
        html = html.replace(INTRO_INSIGHTS, insights_html, 1)
    checked = f' data-checked="{intro.checked_at.isoformat()}"' if intro.checked_at else ""
    return html.replace(
        INTRO_STATS,
        f'<p class="intro-stats" id="overviewStats" role="status" data-models="{intro.models}" '
        f'data-stores="{intro.stores}"{checked}>{intro.models} მოდელი · {intro.stores} მაღაზია</p>',
        1,
    )


async def _load_intro(session: AsyncSession, models: Sequence[ProductSummary]) -> Intro | None:
    product = _headline_product(models)
    if product is None or product.lowest_price_store is None:
        return None
    currency = product.currency or "GEL"
    return Intro(
        model=_phone_name(product),
        price=product.lowest_price,
        store=product.lowest_price_store,
        models=len(models),
        stores=await product_service.count_stores_in_stock(session),
        checked_at=await scraper_service.last_refresh_started_at(session),
        history=await product_service.model_daily_best_prices(
            session, product.model, currency, TREND_WINDOW
        ),
        storage=product.storage,
        store_prices=await product_service.model_store_prices(
            session, product.model, product.storage, currency
        ),
        drop_weekday=await product_service.store_drop_weekday(session),
    )


def _product_url(slug: str) -> str:
    return f"{settings.public_base_url}/{slug}"


def _preview_image(url: str) -> str:
    """The store photo at a size link previews show sharply (they want about 1200px)."""
    # shortcut: only the two stores whose photos are too small (Asbis CDN 512px webp,
    # Megatechnica 200px); add a store here when its previews look blurry.
    if url.startswith("https://prod-cdn.prod.asbis.io/"):
        return url.replace("/f:webp/", "/f:jpg/", 1).replace("/w:512/", "/w:1200/", 1)
    if url.startswith("https://www.megatechnica.ge/"):
        return re.sub(r"_200(\.\w+)$", r"\1", url)
    return url


def _not_found() -> HTMLResponse:
    return HTMLResponse(NOT_FOUND_PATH.read_text(encoding="utf-8"), status_code=404)


async def _product_or_none(session: AsyncSession, product_id: int) -> ProductSummary | None:
    try:
        return await product_service.get_product_summary(session, product_id)
    except NotFoundError:
        return None


async def _product_id_for_slug(session: AsyncSession, slug: str) -> int | None:
    # shortcut: scans every phone's name (a few hundred rows); add a stored, indexed slug
    # column if the catalog grows to many thousands.
    rows = await session.execute(
        select(Product.id, Product.model, Product.storage, Product.color).order_by(Product.id)
    )
    return next((row.id for row in rows if product_slug(row.model, row.storage, row.color) == slug), None)


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
        url=_product_url(product.slug),
        image=_preview_image(product.image_url) if product.image_url else f"{base}/static/logo.png",
    )
    return html.replace(META_MARKER, meta, 1)


async def _page(session: AsyncSession, product: ProductSummary | None) -> HTMLResponse:
    models = await product_service.cheapest_in_stock_per_model(session)
    intro = await _load_intro(session, models)
    return HTMLResponse(render_index(product, models, intro), headers=NO_CACHE)


@router.get("/", response_class=HTMLResponse)
async def index(
    session: SessionDep, page: str | None = None, id: str | None = None
) -> Response:
    # Old phone links (/?page=products&id=9) move to the phone's own address.
    if page == "products" and id is not None:
        product = await _product_or_none(session, int(id)) if id.isdigit() else None
        if product is None:
            return _not_found()
        return RedirectResponse(_product_url(product.slug), status_code=301)
    return await _page(session, None)


@router.get("/sitemap.xml")
async def sitemap(session: SessionDep) -> Response:
    base = settings.public_base_url
    rows = await session.execute(
        select(Product.model, Product.storage, Product.color)
        .where(Product.is_active.is_(True))
        .order_by(Product.id)
    )
    slugs = dict.fromkeys(product_slug(row.model, row.storage, row.color) for row in rows)
    urls = [f"{base}/", f"{base}/?page=products", f"{base}/?page=compare"]
    urls += [_product_url(slug) for slug in slugs]
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


# Last route: it catches every other one-segment path, and anything that isn't a phone is a 404.
@router.get("/{slug}", response_class=HTMLResponse)
async def product_page(session: SessionDep, slug: str) -> HTMLResponse:
    product_id = await _product_id_for_slug(session, slug) if PRODUCT_SLUG.fullmatch(slug) else None
    product = await _product_or_none(session, product_id) if product_id is not None else None
    if product is None:
        return _not_found()
    return await _page(session, product)
