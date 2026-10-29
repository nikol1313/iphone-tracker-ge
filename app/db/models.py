from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.sess import Base


class Store(Base):
    __tablename__ = "stores"
    __table_args__ = (UniqueConstraint("title", name="uq_store_title"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(100))
    web_url: Mapped[str] = mapped_column(String(500))

    listings: Mapped[list["ProductListing"]] = relationship(
        back_populates="store",
        cascade="all, delete-orphan",
    )
    crawl_runs: Mapped[list["CrawlRun"]] = relationship(
        back_populates="store",
        cascade="all, delete-orphan",
    )


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("identity_key", name="uq_products_identity_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    brand: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    storage: Mapped[str | None] = mapped_column(String(20))
    color: Mapped[str | None] = mapped_column(String(50))
    image_url: Mapped[str | None] = mapped_column(String(1000))
    identity_key: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    listings: Mapped[list["ProductListing"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    tracked_by: Mapped[list["TrackedProduct"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    alerts: Mapped[list["PriceAlert"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )


class ProductListing(Base):
    __tablename__ = "product_listing"
    __table_args__ = (
        UniqueConstraint(
            "store_id",
            "product_id",
            name="uq_store_product_listing",
        ),
        CheckConstraint("current_price > 0", name="ck_product_listing_current_price_positive"),
        Index(
            "uq_store_external_product_id",
            "store_id",
            "external_product_id",
            unique=True,
            postgresql_where=text("external_product_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    store_id: Mapped[int] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )

    product_url: Mapped[str] = mapped_column(String(500), nullable=False)
    current_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="GEL", nullable=False)
    last_checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    variant_name: Mapped[str | None] = mapped_column(String(100))
    external_product_id: Mapped[str | None] = mapped_column(String(100))

    store: Mapped["Store"] = relationship(back_populates="listings")
    product: Mapped["Product"] = relationship(back_populates="listings")
    price_history: Mapped[list["PriceHist"]] = relationship(
        back_populates="listing",
        cascade="all, delete-orphan",
    )


class PriceHist(Base):
    __tablename__ = "price_history"
    __table_args__ = (
        CheckConstraint("price > 0", name="ck_price_history_price_positive"),
        Index("ix_price_history_listing_id_recorded_at", "listing_id", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("product_listing.id", ondelete="CASCADE"),
        nullable=False,
    )
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="GEL", nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    listing: Mapped["ProductListing"] = relationship(back_populates="price_history")


class CrawlRun(Base):
    __tablename__ = "crawl_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_crawl_run_status",
        ),
        Index(
            "uq_crawl_runs_store_running",
            "store_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
            sqlite_where=text("status = 'running'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    products_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    products_ingested: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(2000))

    store: Mapped["Store"] = relationship(back_populates="crawl_runs")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Where price alerts are emailed; None turns email alerts off.
    notification_email: Mapped[str | None] = mapped_column(String(320))
    # Alerts are only emailed once the owner of notification_email clicks the link.
    notification_email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    verification_email_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    tracked_products: Mapped[list["TrackedProduct"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    alerts: Mapped[list["PriceAlert"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class TrackedProduct(Base):
    __tablename__ = "tracked_products"
    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_tracked_product_user_product"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="tracked_products")
    product: Mapped["Product"] = relationship(back_populates="tracked_by")


class PriceAlert(Base):
    __tablename__ = "price_alerts"
    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_price_alert_user_product"),
        CheckConstraint("target_price > 0", name="ck_price_alert_target_price_positive"),
        CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name="ck_price_alert_currency_format",
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    target_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="alerts")
    product: Mapped["Product"] = relationship(back_populates="alerts")
