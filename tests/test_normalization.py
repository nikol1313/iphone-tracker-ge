import pytest

from app.services.normalization import ParsedIphone, parse_iphone_title


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (
            "Apple iPhone 18 Pro e-SIM Only | 256GB Burgundy",
            ParsedIphone("iPhone 18 Pro eSIM", "256GB", "Burgundy"),
        ),
        ("iPhone 18 Pro, 256 GB, Burgundy", ParsedIphone("iPhone 18 Pro", "256GB", "Burgundy")),
        (
            "Apple iPhone 17 (8GB/256GB) - Mist Blue",
            ParsedIphone("iPhone 17", "256GB", "Mist Blue"),
        ),
        (
            "Apple iPhone 17 e-SIM Only (8GB/256GB) - White",
            ParsedIphone("iPhone 17 eSIM", "256GB", "White"),
        ),
        (
            "Apple iPhone Air 12GB/256GB - Light Gold",
            ParsedIphone("iPhone Air", "256GB", "Light Gold"),
        ),
        # iPhone Air is eSIM-only everywhere, so the flag must not split it.
        (
            "Apple iPhone Air e-SIM | 256GB Cloud White",
            ParsedIphone("iPhone Air", "256GB", "Cloud White"),
        ),
        ("Apple iPhone 17e 256GB Soft Pink", ParsedIphone("iPhone 17e", "256GB", "Soft Pink")),
        (
            "Apple iPhone Duo 256GB MK2D4 Star White",
            ParsedIphone("iPhone Duo", "256GB", "Star White"),
        ),
        (
            "APPLE iPhone 18 Pro Max 256GB Silver eSIM",
            ParsedIphone("iPhone 18 Pro Max eSIM", "256GB", "Silver"),
        ),
        (
            "სმარტფონები Apple iPhone 17 Pro Max 256GB Deep Blue MFYP4ZD/A",
            ParsedIphone("iPhone 17 Pro Max", "256GB", "Deep Blue"),
        ),
        ("iPhone 17 Pro Max, 2 TB, Cosmic Orange", ParsedIphone("iPhone 17 Pro Max", "2TB", "Cosmic Orange")),
        ("Apple iPhone 15 | 128GB blue", ParsedIphone("iPhone 15", "128GB", "Blue")),
        (
            "Apple iPhone 18 Pro 12GB 256GB NFC Silver (eSIM Only)",
            ParsedIphone("iPhone 18 Pro eSIM", "256GB", "Silver"),
        ),
        ("Apple iphone 15 6GB 128GB NFC Black", ParsedIphone("iPhone 15", "128GB", "Black")),
        (
            "Apple iPhone 17 8/256GB Black Only E-Sim მობილური ტელეფონი",
            ParsedIphone("iPhone 17 eSIM", "256GB", "Black"),
        ),
        (
            "Apple iPhone 17 Air 12/256GB Light Gold მობილური ტელეფონი",
            ParsedIphone("iPhone Air", "256GB", "Light Gold"),
        ),
        (
            "Apple iPhone 18 Pro  256GB Burgundy მობილური ტელეფონი",
            ParsedIphone("iPhone 18 Pro", "256GB", "Burgundy"),
        ),
    ],
)
def test_parse_iphone_title(title: str, expected: ParsedIphone) -> None:
    assert parse_iphone_title(title) == expected


@pytest.mark.parametrize("title", ["Apple Watch Series 11", "iPhone case"])
def test_parse_iphone_title_rejects_non_phones(title: str) -> None:
    assert parse_iphone_title(title) is None
