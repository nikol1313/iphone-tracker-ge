from datetime import datetime
from decimal import Decimal
from typing import Generic, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.services.normalization import (
    normalize_color,
    normalize_email,
    normalize_optional_text,
    normalize_storage,
    normalize_text,
)

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class StoreCreate(BaseModel):
    title: str
    web_url: str

    @field_validator("title", "web_url")
    @classmethod
    def non_empty(cls, value: str) -> str:
        normalized = normalize_text(value)
        if not normalized:
            raise ValueError("field cannot be empty")
        return normalized


class StoreResponse(StoreCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class UserCredentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=130)

    @field_validator("email")
    @classmethod
    def normalized_email(cls, value: EmailStr) -> str:
        return normalize_email(str(value))


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    is_active: bool
    created_at: datetime


class EmailSettingsUpdate(BaseModel):
    notification_email: EmailStr | None

    @field_validator("notification_email")
    @classmethod
    def normalized_email(cls, value: EmailStr | None) -> str | None:
        return normalize_email(str(value)) if value is not None else None


class EmailSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    notification_email: str | None
    # False until the server has SMTP settings, so the page can say so.
    delivery_configured: bool = False


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class ProductBase(BaseModel):
    brand: str
    model: str
    storage: str | None = None
    color: str | None = None

    @field_validator("brand", "model")
    @classmethod
    def required_text(cls, value: str) -> str:
        normalized = normalize_text(value)
        if not normalized:
            raise ValueError("field cannot be empty")
        return normalized

    @field_validator("storage")
    @classmethod
    def normalized_storage(cls, value: str | None) -> str | None:
        return normalize_storage(value)

    @field_validator("color")
    @classmethod
    def normalized_color(cls, value: str | None) -> str | None:
        return normalize_color(value)


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    brand: str | None = None
    model: str | None = None
    storage: str | None = None
    color: str | None = None

    @field_validator("brand", "model")
    @classmethod
    def required_text(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("field cannot be null")
        normalized = normalize_text(value)
        if not normalized:
            raise ValueError("field cannot be empty")
        return normalized

    @field_validator("storage")
    @classmethod
    def normalized_storage(cls, value: str | None) -> str | None:
        return normalize_storage(value)

    @field_validator("color")
    @classmethod
    def normalized_color(cls, value: str | None) -> str | None:
        return normalize_color(value)

    @model_validator(mode="after")
    def at_least_one_field(self) -> "ProductUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        return self


class ProductResponse(ProductBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    image_url: str | None = None


class ProductSummary(ProductResponse):
    lowest_price: Decimal | None
    currency: str | None
    listing_count: int
    available_listing_count: int = 0
    # Most expensive available offer in the lowest price's currency.
    highest_price: Decimal | None = None
    # Lowest price across listings PRICE_TREND_WINDOW ago, for "price drop" badges.
    price_week_ago: Decimal | None = None
    lowest_price_ever: Decimal | None = None
    highest_price_ever: Decimal | None = None


class ProductListingCreate(BaseModel):
    store_id: int
    product_id: int
    product_url: str
    current_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = "GEL"
    is_available: bool = True
    last_seen_at: datetime | None = None
    variant_name: str | None = None
    external_product_id: str | None = None

    @field_validator("product_url")
    @classmethod
    def url_not_empty(cls, value: str) -> str:
        normalized = normalize_text(value)
        if not normalized:
            raise ValueError("url cannot be empty")
        return normalized

    @field_validator("currency")
    @classmethod
    def currency_format(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha() or not normalized.isascii():
            raise ValueError("currency must contain exactly three ASCII letters")
        return normalized

    @field_validator("variant_name", "external_product_id")
    @classmethod
    def optional_text(cls, value: str | None) -> str | None:
        return normalize_optional_text(value)


class ProductListingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    store_id: int
    store_name: str
    product_url: str
    current_price: Decimal
    currency: str
    is_available: bool
    last_checked_at: datetime
    # The retailer's own title for this listing.
    variant_name: str | None = None


class PriceHistCreate(BaseModel):
    listing_id: int
    price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = "GEL"
    is_available: bool = True

    @field_validator("currency")
    @classmethod
    def currency_format(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha() or not normalized.isascii():
            raise ValueError("currency must contain exactly three ASCII letters")
        return normalized


class PriceHistoryResponse(BaseModel):
    id: int
    product_id: int
    listing_id: int
    store_id: int
    store_name: str
    price: Decimal
    currency: str
    is_available: bool
    recorded_at: datetime


class PriceExtremesResponse(BaseModel):
    currency: str
    lowest_price: Decimal | None
    highest_price: Decimal | None


class TrackedProductCreate(BaseModel):
    product_id: int


class TrackedProductCreated(BaseModel):
    product_id: int
    created_at: datetime


class AlertCreate(BaseModel):
    target_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str

    @field_validator("currency")
    @classmethod
    def currency_format(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha() or not normalized.isascii():
            raise ValueError("currency must contain exactly three ASCII letters")
        return normalized


class AlertBrief(BaseModel):
    id: int
    target_price: Decimal
    currency: str
    is_triggered: bool


class TrackedProductResponse(BaseModel):
    product: ProductSummary
    active_alert: AlertBrief | None
    created_at: datetime


class AlertResponse(BaseModel):
    id: int
    product: ProductResponse
    target_price: Decimal
    currency: str
    current_lowest_price: Decimal | None
    is_triggered: bool
    created_at: datetime


class CrawlRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    store_id: int
    status: Literal["running", "succeeded", "failed"]
    started_at: datetime
    finished_at: datetime | None
    products_found: int
    products_ingested: int
    error_message: str | None


class RefreshStatusResponse(BaseModel):
    last_refreshed_at: datetime | None
    next_manual_refresh_at: datetime | None


class RefreshResponse(RefreshStatusResponse):
    crawl_run_ids: list[int]
    products_found: int
    listings_created: int
    listings_updated: int
    prices_recorded: int
    succeeded_stores: list[str]
    failed_stores: list[str]
