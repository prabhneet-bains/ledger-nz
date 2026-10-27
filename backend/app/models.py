import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.money_type import Money


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    gst_number: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Profile(Base):
    __tablename__ = "profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    email: Mapped[str | None] = mapped_column(String(320))
    full_name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuthIdentity(Base):
    """Maps an external login subject to a ledger profile. Used by the local SQLite path."""

    __tablename__ = "auth_identities"
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    email: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Account(Base):
    __tablename__ = "chart_of_accounts"
    __table_args__ = (UniqueConstraint("org_id", "account_name"),)
    account_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    account_name: Mapped[str] = mapped_column(String(200))
    account_type: Mapped[str] = mapped_column(String(32))
    tax_rate: Mapped[str] = mapped_column(Money, default="15.00")
    business_claim_percentage: Mapped[str] = mapped_column(Money, default="100.00")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("org_id", "import_hash"),)
    transaction_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("chart_of_accounts.account_id"), nullable=True)
    payee: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    gross_amount: Mapped[str] = mapped_column(Money)
    gst_amount: Mapped[str] = mapped_column(Money, default="0.00")
    net_amount: Mapped[str] = mapped_column(Money)
    business_claim_percentage: Mapped[str] = mapped_column(Money, default="100.00")
    is_internal_transfer: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    import_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    external_id: Mapped[str | None] = mapped_column(String(128))
    metadata_json: Mapped[str] = mapped_column("metadata", Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Receipt(Base):
    __tablename__ = "receipts"
    receipt_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    transaction_id: Mapped[str | None] = mapped_column(ForeignKey("transactions.transaction_id"), nullable=True)
    drive_file_id: Mapped[str | None] = mapped_column(String(128))
    drive_file_url: Mapped[str | None] = mapped_column(String(500))
    vendor_name: Mapped[str | None] = mapped_column(String(200))
    extracted_amount: Mapped[str | None] = mapped_column(Money, nullable=True)
    gst_number: Mapped[str | None] = mapped_column(String(20))
    inferred_category: Mapped[str | None] = mapped_column(String(200))
    confidence_score: Mapped[str | None] = mapped_column(String(16))
    ocr_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Asset(Base):
    __tablename__ = "assets_depreciation"
    asset_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    asset_name: Mapped[str] = mapped_column(String(200))
    asset_class: Mapped[str] = mapped_column(String(40), default="other")
    purchase_date: Mapped[date] = mapped_column(Date)
    original_cost: Mapped[str] = mapped_column(Money)
    depreciation_method: Mapped[str] = mapped_column(String(32))
    depreciation_rate: Mapped[str] = mapped_column(Money)
    business_use_percentage: Mapped[str] = mapped_column(Money, default="100.00")
    accumulated_depreciation: Mapped[str] = mapped_column(Money, default="0.00")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class VehicleLog(Base):
    __tablename__ = "vehicle_logbook"
    log_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date)
    odometer_start: Mapped[int] = mapped_column(Integer)
    odometer_end: Mapped[int] = mapped_column(Integer)
    distance: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(16))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TaxRecord(Base):
    __tablename__ = "tax_records_historical"
    record_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    period_type: Mapped[str] = mapped_column(String(16))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    total_income: Mapped[str] = mapped_column(Money, default="0.00")
    tax_paid: Mapped[str] = mapped_column(Money, default="0.00")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CategorizationRule(Base):
    __tablename__ = "categorization_rules"
    __table_args__ = (UniqueConstraint("org_id", "keyword"),)
    rule_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    keyword: Mapped[str] = mapped_column(String(120))
    account_id: Mapped[str] = mapped_column(ForeignKey("chart_of_accounts.account_id", ondelete="CASCADE"))
    priority: Mapped[int] = mapped_column(Integer, default=100)
