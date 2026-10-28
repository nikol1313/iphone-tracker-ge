import re
import string
from dataclasses import dataclass

_WHITESPACE = re.compile(r"\s+")

# Retailers title the same phone differently, e.g. "Apple iPhone 17 (8GB/256GB) - Sage",
# "iPhone 17, 256 GB, Sage", "Apple iPhone 17 8GB 256GB NFC Sage" and "APPLE iPhone 17 256GB Sage eSIM".
_IPHONE = re.compile(r"\biphone\b", re.IGNORECASE)
_IPHONE_MODEL = re.compile(
    # "iPhone 17 Air" is the iPhone Air.
    r"\s*(?:\d{1,2}\s+(?=Air\b))?(\d{1,2}e?|SE|XR|XS|X|Air|Duo)((?:\s+(?:Pro|Max|Plus|mini))*)\b",
    re.IGNORECASE,
)
_ESIM = re.compile(r"\b(?:only\s+)?e-?sim(?:\s+only)?\b", re.IGNORECASE)
# RAM before storage: "8GB/256GB", "(12/256GB)" or "12GB 256GB".
_RAM_AND_STORAGE = re.compile(
    r"\(?\b\d{1,2}\s*(?:GB)?\s*/\s*(\d+\s*(?:GB|TB))\b\)?",
    re.IGNORECASE,
)
_RAM_BEFORE_STORAGE = re.compile(r"\b\d{1,2}\s*GB\s+(?=\d+\s*(?:GB|TB)\b)", re.IGNORECASE)
# Feature words and non-Latin text (e.g. Georgian "mobile phone") are not colors.
_NOISE = re.compile(r"\bNFC\b|\bsmartphone\b|[^\x00-\x7F]+", re.IGNORECASE)
_STORAGE = re.compile(r"\b(\d+)\s*(GB|TB)\b", re.IGNORECASE)
# Apple part numbers such as "MK2D4" or "MFYP4ZD/A".
_PART_NUMBER = re.compile(r"\bM[A-Z0-9]{3}\d(?:[A-Z]{2})?(?:/A)?(?=\s|$)")
_SEPARATORS = re.compile(r"[|,()/]|(?:^|\s)-(?=\s|$)")
# Models sold only as eSIM everywhere; the flag would split identical phones.
_ESIM_ONLY_MODELS = frozenset({"iPhone Air"})


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


@dataclass(frozen=True, slots=True)
class ParsedIphone:
    model: str
    storage: str | None
    color: str | None


def _canonical_model(generation: str, suffixes: str) -> str:
    if generation[0].isdigit():
        generation = generation.lower()
    elif generation.upper() in {"SE", "XR", "XS", "X"}:
        generation = generation.upper()
    else:
        generation = generation.capitalize()
    words = [
        "mini" if word.casefold() == "mini" else word.capitalize()
        for word in suffixes.split()
    ]
    return " ".join(["iPhone", generation, *words])


def parse_iphone_title(title: str) -> ParsedIphone | None:
    """Split a retailer's iPhone title into a canonical model, storage and color."""
    iphone = _IPHONE.search(title)
    if iphone is None:
        return None
    model_match = _IPHONE_MODEL.match(title, iphone.end())
    if model_match is None:
        return None

    model = _canonical_model(model_match.group(1), model_match.group(2))
    rest = title[model_match.end():]
    if _ESIM.search(rest) and model not in _ESIM_ONLY_MODELS:
        model = f"{model} eSIM"
    rest = _ESIM.sub(" ", rest)
    rest = _PART_NUMBER.sub(" ", rest)
    rest = _RAM_AND_STORAGE.sub(r" \1 ", rest)
    rest = _RAM_BEFORE_STORAGE.sub(" ", rest)
    rest = _NOISE.sub(" ", rest)

    storage = None
    storage_match = _STORAGE.search(rest)
    if storage_match is not None:
        storage = f"{int(storage_match.group(1))}{storage_match.group(2).upper()}"
        rest = rest[: storage_match.start()] + " " + rest[storage_match.end():]

    color = normalize_text(_SEPARATORS.sub(" ", rest))
    return ParsedIphone(
        model=model,
        storage=storage,
        color=string.capwords(color) if color else None,
    )


def normalize_email(value: str) -> str:
    return value.strip().lower()
