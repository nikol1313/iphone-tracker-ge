"""The HTML entry page, with link-preview tags filled in on the server, and the sitemap.

Facebook, Messenger and search engines read the page without running JavaScript, so
the title, description and preview image of a shared phone link are written here.
"""

import re
from decimal import Decimal
from html import escape, unescape
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.conf import settings
from app.db.db_schemas import ProductSummary
from app.db.models import Product
from app.dependencies import SessionDep
from app.services import product_service
from app.services.errors import NotFoundError

router = APIRouter(include_in_schema=False)

INDEX_PATH = Path(__file__).resolve().parent.parent / "static" / "index.html"
META_MARKER = "<!--server-meta-->"
TITLE_PATTERN = re.compile(r"<title>(.*?)</title>", re.DOTALL)
DESCRIPTION_PATTERN = re.compile(r'<meta name="description" content="([^"]*)">')
NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}


def _price(value: Decimal) -> str:
    # "3,199 ₾" like the page itself; tetri only when there are any.
    return f"{value:,.0f} ₾" if value == value.to_integral() else f"{value:,.2f} ₾"


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


def render_index(product: ProductSummary | None) -> str:
    html = INDEX_PATH.read_text(encoding="utf-8")
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
    return HTMLResponse(render_index(product), headers=NO_CACHE)


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
