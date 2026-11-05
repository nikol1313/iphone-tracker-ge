from app.scraper.scrape_icity import products_from_variations


def variation(variation_id: int, parent: int, options: str, price: str, *, in_stock: bool = True) -> dict:
    return {
        "id": variation_id,
        "parent": parent,
        "variation": options,
        "prices": {"price": price, "currency_minor_unit": 0},
        "permalink": f"https://icity.ge/product/p{parent}/?v={variation_id}",
        "images": [{"thumbnail": f"https://icity.ge/{variation_id}.jpg"}],
        "is_in_stock": in_stock,
    }


def test_icity_variations_become_phones() -> None:
    products = products_from_variations(
        {1: "iPhone 18 Pro", 2: "iPhone Duo"},
        [
            variation(10, 1, "ფერი: Silver, მოცულობა: 256GB, სიმ ბარათის ტიპი: eSIM", "4099"),
            variation(11, 1, "ფერი: Black, მოცულობა: 512GB, სიმ ბარათის ტიპი: nano SIM+eSIM", "4929", in_stock=False),
            variation(12, 2, "ფერი: Night Sky, მოცულობა: 2TB", "0"),
            variation(13, 99, "ფერი: Black, მოცულობა: 256GB", "100"),
        ],
    )

    assert [(p["name"], p["price"], p["is_available"]) for p in products] == [
        ("iPhone 18 Pro 256GB Silver eSIM", 4099.0, True),
        ("iPhone 18 Pro 512GB Black", 4929.0, False),
    ]
    assert products[0]["url"] == "https://icity.ge/product/p1/?v=10"
    assert products[0]["external_product_id"] == "10"
    assert products[0]["store"] == "iCity"
