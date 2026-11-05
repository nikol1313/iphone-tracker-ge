from bs4 import BeautifulSoup

from app.scraper.scrape_kontakt import products_from_page


def card(product_id: int, name: str, prices: str, *, in_stock: bool = True) -> str:
    slug = name.lower().replace(" ", "-")
    return f"""
    <div class="prodItem product-item" id="{product_id}" data-sku="SKU-{product_id}">
      <a href="https://kontakt.ge/{slug}" title="{name}" class="prodItem__img label-image-wrapper">
        <picture class="product-image"><img src="https://kontakt.ge/media/{product_id}.jpg" alt="{name}" class="product-image"></picture>
      </a>
      <div class="prodItem__title">{name}</div>
      <div class="prodItem__prices prodItem__prices--active"><strong>{prices}</strong><span>0% 6 თვე</span></div>
      {'<button class="prodItem__addCart tocart" type="submit"></button>' if in_stock else ''}
    </div>"""


def test_products_from_kontakt_cards() -> None:
    soup = BeautifulSoup(
        card(34481, "iPhone 18 Pro 256GB Black", "<i>4599,99 ₾</i><b>4269,99 ₾</b>")
        + card(32272, "Xiaomi Poco X8 Pro Max 12GB/256GB White", "<b>1499,99 ₾</b>")
        + card(34490, "iPhone 18 Pro 1TB Glacier", "6259,99 ₾", in_stock=False),
        "html.parser",
    )

    assert products_from_page(soup) == [
        {
            "name": "iPhone 18 Pro 256GB Black",
            "price": 4269.99,
            "currency": "GEL",
            "url": "https://kontakt.ge/iphone-18-pro-256gb-black",
            "image_url": "https://kontakt.ge/media/34481.jpg",
            "store": "Kontakt",
            "is_available": True,
            "external_product_id": "34481",
        },
        {
            "name": "iPhone 18 Pro 1TB Glacier",
            "price": 6259.99,
            "currency": "GEL",
            "url": "https://kontakt.ge/iphone-18-pro-1tb-glacier",
            "image_url": "https://kontakt.ge/media/34490.jpg",
            "store": "Kontakt",
            "is_available": False,
            "external_product_id": "34490",
        },
    ]
