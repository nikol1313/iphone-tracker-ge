from bs4 import BeautifulSoup

from app.scraper.scrape_pcshop import products_from_page


def card(product_id: int, name: str, price_html: str, *, stock: str = "instock") -> str:
    return f"""
    <li class="product type-product {stock}">
      <a href="https://pcshop.ge/shop/phone-{product_id}/" class="woocommerce-LoopProduct-link">
        <img src="//pcshop.ge/wp-content/uploads/{product_id}.jpg">
        <h2 class="woocommerce-loop-product__title">{name}</h2>
        <span class="price">{price_html}</span>
      </a>
      <a data-product_id="{product_id}" class="button add_to_cart_button">Add</a>
    </li>"""


def amount(value: str) -> str:
    return f'<span class="woocommerce-Price-amount amount"><bdi>₾{value}</bdi></span>'


def test_products_from_pcshop_page() -> None:
    soup = BeautifulSoup(
        "<ul>"
        + card(
            313062,
            "Apple iPhone 18 Pro 12GB 256GB NFC Silver (eSIM Only)",
            f"<del>{amount('4,349.00')}</del><ins>{amount('4,199.00')}</ins>",
        )
        + card(1, "Samsung Galaxy S26 256GB", amount("2,899.00"))
        + card(301253, "Apple iPhone 17 8GB 256GB White", amount("2,849.00"), stock="outofstock")
        + "</ul>",
        "html.parser",
    )

    assert [
        (p["name"], p["price"], p["is_available"], p["external_product_id"], p["image_url"])
        for p in products_from_page(soup)
    ] == [
        (
            "Apple iPhone 18 Pro 12GB 256GB NFC Silver (eSIM Only)",
            4199.0,
            True,
            "313062",
            "https://pcshop.ge/wp-content/uploads/313062.jpg",
        ),
        (
            "Apple iPhone 17 8GB 256GB White",
            2849.0,
            False,
            "301253",
            "https://pcshop.ge/wp-content/uploads/301253.jpg",
        ),
    ]
