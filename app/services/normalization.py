import re

_WHITESPACE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    return _WHITESPACE.sub(" ", value.strip())


def normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = normalize_text(value)
    return normalized or None


def normalize_storage(value: str | None) -> str | None:
    normalized = normalize_optional_text(value)
    if normalized is None:
        return None
    return re.sub(r"\s+", "", normalized).upper()


def normalize_color(value: str | None) -> str | None:
    return normalize_optional_text(value)


def product_identity_key(
    brand: str,
    model: str,
    storage: str | None,
    color: str | None,
) -> str:
    values = (
        normalize_text(brand).casefold(),
        normalize_text(model).casefold(),
        (normalize_storage(storage) or "").casefold(),
        (normalize_color(color) or "").casefold(),
    )
    return "\x1f".join(values)


def normalize_email(value: str) -> str:
    return value.strip().lower()
