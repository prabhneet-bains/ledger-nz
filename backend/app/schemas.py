from datetime import date as Date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


AccountType = Literal["Income", "Expense", "Asset", "Liability", "Equity"]
TxSource = Literal["CSV_Upload", "AdHoc", "ReceiptScan"]
TxStatus = Literal["Reconciled", "Pending_Review", "Ignored"]
DepreciationMethod = Literal["Straight_Line", "Diminishing_Value", "Maximum_Permissible"]
VehiclePurpose = Literal["Business", "Personal"]
PeriodType = Literal["GST", "IncomeTax"]


class AccountOut(BaseModel):
    account_id: UUID
    account_name: str
    account_type: AccountType
    tax_rate: Decimal
    business_claim_percentage: Decimal


class AccountCreate(BaseModel):
    account_name: str = Field(min_length=1, max_length=200)
    account_type: AccountType
    tax_rate: Decimal = Decimal("15.00")
    business_claim_percentage: Decimal = Decimal("100.00")


class TransactionCreate(BaseModel):
    date: Date
    account_id: UUID
    description: str
    gross_amount: Decimal
    payee: str = ""
    source: TxSource = "AdHoc"
    status: TxStatus | None = None
    business_claim_percentage: Decimal | None = Field(default=None, ge=0, le=100)


class TransactionPatch(BaseModel):
    date: Date | None = None
    account_id: UUID | None = None
    description: str | None = None
    payee: str | None = None
    gross_amount: Decimal | None = None
    business_claim_percentage: Decimal | None = Field(default=None, ge=0, le=100)
    status: TxStatus | None = None


class BulkCode(BaseModel):
    account_id: UUID
    transaction_ids: list[UUID] = Field(min_length=1, max_length=200)
    remember_payee: bool = False
    business_claim_percentage: Decimal | None = Field(default=None, ge=0, le=100)


class TransactionOut(BaseModel):
    transaction_id: UUID
    date: Date
    account_id: UUID | None = None
    payee: str = ""
    description: str
    gross_amount: Decimal
    gst_amount: Decimal
    net_amount: Decimal
    business_claim_percentage: Decimal = Decimal("100")
    is_internal_transfer: bool = False
    source: TxSource
    status: TxStatus


class CsvMapping(BaseModel):
    date: str
    payee: str
    amount: str | None = None
    debit: str | None = None
    credit: str | None = None
    reference: str | None = None
    description: str | None = None


class LogEntryCreate(BaseModel):
    date: Date
    odometer_start: int | None = None
    odometer_end: int
    purpose: VehiclePurpose
    notes: str | None = None


class LogBulkCreate(BaseModel):
    entries: list[LogEntryCreate]


class AssetCreate(BaseModel):
    asset_name: str
    asset_class: str = "other"
    purchase_date: Date
    original_cost: Decimal
    depreciation_method: DepreciationMethod = "Diminishing_Value"
    depreciation_rate: Decimal = Decimal("0")
    business_use_percentage: Decimal = Field(default=Decimal("100"), ge=0, le=100)
    accumulated_depreciation: Decimal = Decimal("0")


class CapitaliseVehicle(BaseModel):
    transaction_id: UUID
    asset_name: str = ""
    depreciation_method: DepreciationMethod = "Diminishing_Value"
    business_use_percentage: Decimal = Field(default=Decimal("100"), ge=0, le=100)
    gst_inclusive: bool = True


class TaxRecordCreate(BaseModel):
    period_type: PeriodType
    start_date: Date
    end_date: Date
    total_income: Decimal
    tax_paid: Decimal
    notes: str | None = None


class DashboardQuery(BaseModel):
    start: Date | None = None
    end: Date | None = None
