from bs4 import BeautifulSoup

from app.scraper.scrape_megatechnica import products_from_cards


def card(product_id: int, name: str, price: str, *, buy: bool = True) -> str:
    url = f"https://www.megatechnica.ge/ka/product/{product_id}/phone"
    buttons = (
        f'<input type="hidden" name="product_id" value="{product_id}">'
        + ('<button class="buy" type="submit">იყიდე</button>' if buy else "")
    )
    return f"""
    <li itemprop="itemListElement">
      <img alt="" src="/storage/{product_id}_200.jpg" itemprop="image">
      <a class="link" href="{url}" itemprop="url"><span itemprop="name">{name}</span></a>
      <span class="price">{price}</span><span class="gel">ლარი</span>
      <form>{buttons}</form>
    </li>"""


def test_products_from_megatechnica_cards() -> None:
    soup = BeautifulSoup(
        "<ul>"
        + card(8367, "სმარტფონები Apple iPhone 17 Pro Max 256GB Deep Blue MFYP4ZD/A", "4049")
        + card(8550, "სმარტფონები Samsung S26 12GB/256GB Black", "2899")
        + card(6362, "სმარტფონები Apple iPhone 15 128GB Black", "2489", buy=False)
        + "</ul>",
        "html.parser",
    )

    assert products_from_cards(soup) == [
        {
            "name": "სმარტფონები Apple iPhone 17 Pro Max 256GB Deep Blue MFYP4ZD/A",
            "price": 4049.0,
            "currency": "GEL",
            "url": "https://www.megatechnica.ge/ka/product/8367/phone",
            "image_url": "https://www.megatechnica.ge/storage/8367_200.jpg",
            "store": "Megatechnica",
            "is_available": True,
            "external_product_id": "8367",
        },
        {
            "name": "სმარტფონები Apple iPhone 15 128GB Black",
            "price": 2489.0,
            "currency": "GEL",
            "url": "https://www.megatechnica.ge/ka/product/6362/phone",
            "image_url": "https://www.megatechnica.ge/storage/6362_200.jpg",
            "store": "Megatechnica",
            "is_available": False,
            "external_product_id": "6362",
        },
    ]
