from app.scraper.scrape_gstore import products_from_api


def item(product_id: int, name: str, price: str, *, condition: str = "NEW", device: str = "iPhones", in_stock: bool = True) -> dict:
    return {
        "id": product_id,
        "name": name,
        "permalink": f"https://gstore.ge/product/{product_id}/",
        "prices": {"price": price, "currency_code": "GEL", "currency_minor_unit": 0},
        "images": [{"src": f"https://gstore.ge/{product_id}.avif", "thumbnail": f"https://gstore.ge/{product_id}-600.avif"}],
        "attributes": [
            {"name": "Condition", "terms": [{"name": condition}]},
            {"name": "Device Type", "terms": [{"name": device}]},
        ],
        "is_in_stock": in_stock,
        "is_purchasable": True,
    }


def test_products_from_gstore_api_keep_new_iphones() -> None:
    products = products_from_api(
        [
            item(1, "iPhone 18 Pro Max 256GB Sliver", "4649"),
            item(2, "iPhone 16 Pro 128GB Black Titanium", "2480", condition="USED (A)"),
            item(3, "Remax OTG adapter USB Type C to iPhone Lightning", "29", device="Accessories"),
            item(4, "iPhone 17 256GB Sage eSIM", "2899", in_stock=False),
        ]
    )

    assert products == [
        {
            "name": "iPhone 18 Pro Max 256GB Silver",
            "price": 4649.0,
            "currency": "GEL",
            "url": "https://gstore.ge/product/1/",
            "image_url": "https://gstore.ge/1-600.avif",
            "store": "Gstore",
            "is_available": True,
            "external_product_id": "1",
        },
        {
            "name": "iPhone 17 256GB Sage eSIM",
            "price": 2899.0,
            "currency": "GEL",
            "url": "https://gstore.ge/product/4/",
            "image_url": "https://gstore.ge/4-600.avif",
            "store": "Gstore",
            "is_available": False,
            "external_product_id": "4",
        },
    ]


def test_gstore_prices_in_minor_units() -> None:
    entry = item(5, "iPhone Air 256GB Sky Blue e-SIM", "289950")
    entry["prices"]["currency_minor_unit"] = 2

    assert products_from_api([entry])[0]["price"] == 2899.5
