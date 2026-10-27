"""Parameterised data access. Production uses the Supabase client (RLS applies). Local mode uses SQLAlchemy."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Account, Asset, CategorizationRule, Profile, Receipt, TaxRecord, Transaction, VehicleLog
from app.services.gst import money


class DuplicateTransaction(Exception):
    pass


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _money(value) -> str:
    return str(money(Decimal(str(value))))


class SqlStore:
    def __init__(self, session: Session):
        self.session = session

    def get_profile(self, user_id: str) -> dict | None:
        row = self.session.get(Profile, user_id)
        if not row:
            return None
        return {"id": row.id, "org_id": row.org_id, "email": row.email, "full_name": row.full_name}

    def list_accounts(self, org_id: str) -> list[dict]:
        rows = self.session.scalars(
            select(Account).where(Account.org_id == org_id).order_by(Account.account_type, Account.account_name)
        ).all()
        return [self._account(row) for row in rows]

    def get_account(self, org_id: str, account_id: str) -> dict | None:
        row = self.session.get(Account, account_id)
        if not row or row.org_id != org_id:
            return None
        return self._account(row)

    def create_account(self, org_id: str, payload: dict) -> dict:
        row = Account(org_id=org_id, **payload)
        self.session.add(row)
        self.session.commit()
        return self._account(row)

    def list_rules(self, org_id: str) -> list[dict]:
        rows = self.session.scalars(select(CategorizationRule).where(CategorizationRule.org_id == org_id)).all()
        return [{"keyword": row.keyword, "account_id": row.account_id, "priority": row.priority} for row in rows]

    def upsert_rule(self, org_id: str, keyword: str, account_id: str, priority: int = 40) -> dict:
        row = self.session.scalar(
            select(CategorizationRule).where(CategorizationRule.org_id == org_id, CategorizationRule.keyword == keyword)
        )
        if row is None:
            row = CategorizationRule(org_id=org_id, keyword=keyword, account_id=account_id, priority=priority)
            self.session.add(row)
        else:
            row.account_id = account_id
            row.priority = priority
        self.session.commit()
        return {"keyword": keyword, "account_id": account_id, "priority": priority}

    def list_transactions(self, org_id: str, *, status: str | None, start: date | None, end: date | None, limit: int) -> list[dict]:
        query = select(Transaction).where(Transaction.org_id == org_id)
        if status:
            query = query.where(Transaction.status == status)
        if start:
            query = query.where(Transaction.date >= start)
        if end:
            query = query.where(Transaction.date <= end)
        rows = self.session.scalars(query.order_by(Transaction.date.desc(), Transaction.created_at.desc()).limit(limit)).all()
        return [self._transaction(row) for row in rows]

    def get_transaction(self, org_id: str, transaction_id: str) -> dict | None:
        row = self.session.get(Transaction, transaction_id)
        if not row or row.org_id != org_id:
            return None
        return self._transaction(row)

    def existing_import_hashes(self, org_id: str, hashes: list[str]) -> set[str]:
        if not hashes:
            return set()
        found: set[str] = set()
        for offset in range(0, len(hashes), 200):
            chunk = hashes[offset : offset + 200]
            rows = self.session.scalars(
                select(Transaction.import_hash).where(Transaction.org_id == org_id, Transaction.import_hash.in_(chunk))
            ).all()
            found.update(row for row in rows if row)
        return found

    def insert_transaction(self, payload: dict) -> dict:
        row = Transaction(
            org_id=payload["org_id"],
            date=date.fromisoformat(payload["date"]) if isinstance(payload["date"], str) else payload["date"],
            account_id=payload.get("account_id"),
            payee=payload.get("payee") or "",
            description=payload.get("description") or "",
            gross_amount=payload["gross_amount"],
            gst_amount=payload["gst_amount"],
            net_amount=payload["net_amount"],
            business_claim_percentage=str(payload.get("business_claim_percentage") or "100"),
            is_internal_transfer=bool(payload.get("is_internal_transfer")),
            source=payload["source"],
            status=payload["status"],
            import_hash=payload.get("import_hash"),
            external_id=payload.get("external_id"),
            metadata_json=json.dumps(payload.get("metadata") or {}),
        )
        self.session.add(row)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise DuplicateTransaction(str(exc)) from exc
        return self._transaction(row)

    def update_transaction(self, org_id: str, transaction_id: str, patch: dict) -> dict:
        row = self.session.get(Transaction, transaction_id)
        if not row or row.org_id != org_id:
            raise KeyError(transaction_id)
        for key, value in patch.items():
            if key == "date" and isinstance(value, str):
                value = date.fromisoformat(value)
            if key in {"gross_amount", "gst_amount", "net_amount", "business_claim_percentage"}:
                value = str(value)
            setattr(row, key, value)
        self.session.commit()
        return self._transaction(row)

    def transactions_in_range(self, org_id: str, start: date, end: date) -> list[dict]:
        rows = self.session.execute(
            select(Transaction, Account)
            .outerjoin(Account, Account.account_id == Transaction.account_id)
            .where(Transaction.org_id == org_id, Transaction.date >= start, Transaction.date <= end)
        ).all()
        result = []
        for txn, account in rows:
            item = self._transaction(txn)
            item["account_name"] = account.account_name if account else None
            item["account_type"] = account.account_type if account else None
            result.append(item)
        return result

    def transactions_between(self, org_id: str, start: date, end: date) -> list[dict]:
        rows = self.session.scalars(
            select(Transaction).where(
                Transaction.org_id == org_id,
                Transaction.date >= start,
                Transaction.date <= end,
            )
        ).all()
        items = []
        for row in rows:
            item = self._transaction(row)
            item["metadata"] = row.metadata_json
            items.append(item)
        return items

    def count_pending(self, org_id: str, start: date | None = None, end: date | None = None) -> int:
        query = select(Transaction.transaction_id).where(
            Transaction.org_id == org_id, Transaction.status == "Pending_Review"
        )
        if start:
            query = query.where(Transaction.date >= start)
        if end:
            query = query.where(Transaction.date <= end)
        return len(self.session.scalars(query).all())

    def list_receipts(self, org_id: str, start: date | None = None, end: date | None = None) -> list[dict]:
        query = select(Receipt).where(Receipt.org_id == org_id)
        if start:
            query = query.where(Receipt.created_at >= start)
        if end:
            query = query.where(Receipt.created_at < end + timedelta(days=1))
        rows = self.session.scalars(query.order_by(Receipt.created_at.desc()).limit(200)).all()
        return [self._receipt(row) for row in rows]

    def insert_receipt(self, payload: dict) -> dict:
        row = Receipt(
            org_id=payload["org_id"],
            transaction_id=payload.get("transaction_id"),
            drive_file_id=payload.get("drive_file_id"),
            drive_file_url=payload.get("drive_file_url"),
            vendor_name=payload.get("vendor_name"),
            extracted_amount=payload.get("extracted_amount"),
            gst_number=payload.get("gst_number"),
            inferred_category=payload.get("inferred_category"),
            confidence_score=None if payload.get("confidence_score") is None else str(payload["confidence_score"]),
            ocr_raw=payload.get("ocr_raw") or None,
        )
        self.session.add(row)
        self.session.commit()
        return self._receipt(row)

    def list_logs(self, org_id: str, start: date | None = None, end: date | None = None) -> list[dict]:
        query = select(VehicleLog).where(VehicleLog.org_id == org_id)
        if start:
            query = query.where(VehicleLog.date >= start)
        if end:
            query = query.where(VehicleLog.date <= end)
        rows = self.session.scalars(query.order_by(VehicleLog.date.desc(), VehicleLog.created_at.desc()).limit(400)).all()
        return [self._log(row) for row in rows]

    def latest_odometer(self, org_id: str) -> int | None:
        row = self.session.scalars(
            select(VehicleLog).where(VehicleLog.org_id == org_id).order_by(VehicleLog.date.desc(), VehicleLog.created_at.desc()).limit(1)
        ).first()
        return None if row is None else int(row.odometer_end)

    def insert_log(self, payload: dict) -> dict:
        start = int(payload["odometer_start"])
        end = int(payload["odometer_end"])
        row = VehicleLog(
            org_id=payload["org_id"],
            date=date.fromisoformat(payload["date"]) if isinstance(payload["date"], str) else payload["date"],
            odometer_start=start,
            odometer_end=end,
            distance=end - start,
            purpose=payload["purpose"],
            notes=payload.get("notes"),
        )
        self.session.add(row)
        self.session.commit()
        return self._log(row)

    def list_tax(self, org_id: str) -> list[dict]:
        rows = self.session.scalars(
            select(TaxRecord).where(TaxRecord.org_id == org_id).order_by(TaxRecord.end_date.desc())
        ).all()
        return [self._tax(row) for row in rows]

    def insert_tax(self, payload: dict) -> dict:
        row = TaxRecord(
            org_id=payload["org_id"],
            period_type=payload["period_type"],
            start_date=date.fromisoformat(payload["start_date"]) if isinstance(payload["start_date"], str) else payload["start_date"],
            end_date=date.fromisoformat(payload["end_date"]) if isinstance(payload["end_date"], str) else payload["end_date"],
            total_income=payload["total_income"],
            tax_paid=payload["tax_paid"],
            notes=payload.get("notes"),
        )
        self.session.add(row)
        self.session.commit()
        return self._tax(row)

    def list_assets(self, org_id: str) -> list[dict]:
        rows = self.session.scalars(
            select(Asset).where(Asset.org_id == org_id).order_by(Asset.purchase_date.desc())
        ).all()
        return [self._asset(row) for row in rows]

    def insert_asset(self, payload: dict) -> dict:
        row = Asset(
            org_id=payload["org_id"],
            asset_name=payload["asset_name"],
            asset_class=payload.get("asset_class") or "other",
            purchase_date=date.fromisoformat(payload["purchase_date"]) if isinstance(payload["purchase_date"], str) else payload["purchase_date"],
            original_cost=payload["original_cost"],
            depreciation_method=payload["depreciation_method"],
            depreciation_rate=payload["depreciation_rate"],
            business_use_percentage=str(payload.get("business_use_percentage") or "100"),
            accumulated_depreciation=payload.get("accumulated_depreciation") or "0",
        )
        self.session.add(row)
        self.session.commit()
        return self._asset(row)

    def update_asset(self, org_id: str, asset_id: str, patch: dict) -> dict:
        row = self.session.get(Asset, asset_id)
        if not row or row.org_id != org_id:
            raise KeyError(asset_id)
        if "purchase_date" in patch:
            value = patch["purchase_date"]
            row.purchase_date = date.fromisoformat(value) if isinstance(value, str) else value
        self.session.commit()
        return self._asset(row)

    @staticmethod
    def _account(row: Account) -> dict:
        return {
            "account_id": row.account_id,
            "account_name": row.account_name,
            "account_type": row.account_type,
            "tax_rate": _money(row.tax_rate),
            "business_claim_percentage": _money(row.business_claim_percentage),
        }

    @staticmethod
    def _transaction(row: Transaction) -> dict:
        return {
            "transaction_id": row.transaction_id,
            "date": _iso(row.date),
            "account_id": row.account_id,
            "payee": row.payee or "",
            "description": row.description or "",
            "gross_amount": _money(row.gross_amount),
            "gst_amount": _money(row.gst_amount),
            "net_amount": _money(row.net_amount),
            "business_claim_percentage": _money(row.business_claim_percentage or "100"),
            "is_internal_transfer": bool(row.is_internal_transfer),
            "source": row.source,
            "status": row.status,
            "import_hash": row.import_hash,
        }

    @staticmethod
    def _receipt(row: Receipt) -> dict:
        return {
            "receipt_id": row.receipt_id,
            "transaction_id": row.transaction_id,
            "drive_file_id": row.drive_file_id,
            "drive_file_url": row.drive_file_url,
            "vendor_name": row.vendor_name,
            "extracted_amount": None if row.extracted_amount is None else _money(row.extracted_amount),
            "gst_number": row.gst_number,
            "inferred_category": row.inferred_category,
            "confidence_score": None if row.confidence_score is None else float(row.confidence_score),
            "ocr_raw": row.ocr_raw or "",
            "created_at": _iso(row.created_at),
        }

    @staticmethod
    def _log(row: VehicleLog) -> dict:
        return {
            "log_id": row.log_id,
            "date": _iso(row.date),
            "odometer_start": row.odometer_start,
            "odometer_end": row.odometer_end,
            "distance": row.distance,
            "purpose": row.purpose,
            "notes": row.notes,
        }

    @staticmethod
    def _tax(row: TaxRecord) -> dict:
        return {
            "record_id": row.record_id,
            "period_type": row.period_type,
            "start_date": _iso(row.start_date),
            "end_date": _iso(row.end_date),
            "total_income": _money(row.total_income),
            "tax_paid": _money(row.tax_paid),
            "notes": row.notes,
        }

    @staticmethod
    def _asset(row: Asset) -> dict:
        return {
            "asset_id": row.asset_id,
            "asset_name": row.asset_name,
            "asset_class": row.asset_class or "other",
            "purchase_date": _iso(row.purchase_date),
            "original_cost": _money(row.original_cost),
            "depreciation_method": row.depreciation_method,
            "depreciation_rate": _money(row.depreciation_rate),
            "business_use_percentage": _money(row.business_use_percentage or "100"),
            "accumulated_depreciation": _money(row.accumulated_depreciation),
        }


class SupabaseStore:
    def __init__(self, client):
        self.client = client

    def get_profile(self, user_id: str) -> dict | None:
        result = self.client.table("profiles").select("id, org_id, email, full_name").eq("id", user_id).limit(1).execute()
        return result.data[0] if result.data else None

    def list_accounts(self, org_id: str) -> list[dict]:
        return (
            self.client.table("chart_of_accounts")
            .select("account_id, account_name, account_type, tax_rate, business_claim_percentage")
            .eq("org_id", org_id)
            .order("account_type")
            .order("account_name")
            .execute()
            .data
            or []
        )

    def get_account(self, org_id: str, account_id: str) -> dict | None:
        result = (
            self.client.table("chart_of_accounts")
            .select("account_id, account_name, account_type, tax_rate, business_claim_percentage")
            .eq("org_id", org_id)
            .eq("account_id", account_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def create_account(self, org_id: str, payload: dict) -> dict:
        body = {"org_id": org_id, **payload}
        for key in ("tax_rate", "business_claim_percentage"):
            body[key] = str(body[key])
        result = self.client.table("chart_of_accounts").insert(body).execute()
        if not result.data:
            raise RuntimeError("Could not create account")
        return result.data[0]

    def list_rules(self, org_id: str) -> list[dict]:
        return (
            self.client.table("categorization_rules")
            .select("keyword, account_id, priority")
            .eq("org_id", org_id)
            .execute()
            .data
            or []
        )

    def upsert_rule(self, org_id: str, keyword: str, account_id: str, priority: int = 40) -> dict:
        existing = (
            self.client.table("categorization_rules")
            .select("rule_id")
            .eq("org_id", org_id)
            .eq("keyword", keyword)
            .limit(1)
            .execute()
        )
        if existing.data:
            (
                self.client.table("categorization_rules")
                .update({"account_id": account_id, "priority": priority})
                .eq("rule_id", existing.data[0]["rule_id"])
                .execute()
            )
        else:
            self.client.table("categorization_rules").insert(
                {"org_id": org_id, "keyword": keyword, "account_id": account_id, "priority": priority}
            ).execute()
        return {"keyword": keyword, "account_id": account_id, "priority": priority}

    def list_transactions(self, org_id: str, *, status: str | None, start: date | None, end: date | None, limit: int) -> list[dict]:
        query = (
            self.client.table("transactions")
            .select(
                "transaction_id, date, account_id, payee, description, gross_amount, gst_amount, net_amount, business_claim_percentage, is_internal_transfer, source, status"
            )
            .eq("org_id", org_id)
            .order("date", desc=True)
            .limit(limit)
        )
        if status:
            query = query.eq("status", status)
        if start:
            query = query.gte("date", start.isoformat())
        if end:
            query = query.lte("date", end.isoformat())
        return query.execute().data or []

    def get_transaction(self, org_id: str, transaction_id: str) -> dict | None:
        result = (
            self.client.table("transactions")
            .select("*")
            .eq("org_id", org_id)
            .eq("transaction_id", transaction_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def existing_import_hashes(self, org_id: str, hashes: list[str]) -> set[str]:
        found: set[str] = set()
        for offset in range(0, len(hashes), 200):
            chunk = hashes[offset : offset + 200]
            result = (
                self.client.table("transactions")
                .select("import_hash")
                .eq("org_id", org_id)
                .in_("import_hash", chunk)
                .execute()
            )
            found.update(row["import_hash"] for row in (result.data or []) if row.get("import_hash"))
        return found

    def insert_transaction(self, payload: dict) -> dict:
        body = {
            "org_id": payload["org_id"],
            "date": payload["date"] if isinstance(payload["date"], str) else payload["date"].isoformat(),
            "account_id": payload.get("account_id"),
            "payee": payload.get("payee") or "",
            "description": payload.get("description") or "",
            "gross_amount": str(payload["gross_amount"]),
            "gst_amount": str(payload["gst_amount"]),
            "net_amount": str(payload["net_amount"]),
            "business_claim_percentage": str(payload.get("business_claim_percentage") or "100"),
            "is_internal_transfer": bool(payload.get("is_internal_transfer")),
            "source": payload["source"],
            "status": payload["status"],
            "metadata": payload.get("metadata") or {},
        }
        if payload.get("import_hash"):
            body["import_hash"] = payload["import_hash"]
        if payload.get("external_id"):
            body["external_id"] = payload["external_id"]
        try:
            result = self.client.table("transactions").insert(body).execute()
        except Exception as exc:
            message = str(exc).lower()
            if "duplicate" in message or "import_hash" in message or "23505" in message:
                raise DuplicateTransaction(str(exc)) from exc
            raise
        if not result.data:
            raise RuntimeError("Insert returned no row")
        return result.data[0]

    def update_transaction(self, org_id: str, transaction_id: str, patch: dict) -> dict:
        body = dict(patch)
        if "date" in body and not isinstance(body["date"], str):
            body["date"] = body["date"].isoformat()
        for key in ("gross_amount", "gst_amount", "net_amount", "business_claim_percentage"):
            if key in body:
                body[key] = str(body[key])
        result = (
            self.client.table("transactions").update(body).eq("org_id", org_id).eq("transaction_id", transaction_id).execute()
        )
        if not result.data:
            raise KeyError(transaction_id)
        return result.data[0]

    def transactions_in_range(self, org_id: str, start: date, end: date) -> list[dict]:
        result = (
            self.client.table("transactions")
            .select(
                "transaction_id, date, payee, description, gross_amount, gst_amount, net_amount, account_id, status, is_internal_transfer, chart_of_accounts(account_name, account_type)"
            )
            .eq("org_id", org_id)
            .gte("date", start.isoformat())
            .lte("date", end.isoformat())
            .execute()
        )
        rows = []
        for row in result.data or []:
            account = row.get("chart_of_accounts") or {}
            rows.append(
                {
                    "transaction_id": row.get("transaction_id"),
                    "date": row.get("date"),
                    "payee": row.get("payee") or "",
                    "description": row.get("description") or "",
                    "gross_amount": row.get("gross_amount"),
                    "gst_amount": row.get("gst_amount"),
                    "net_amount": row.get("net_amount"),
                    "account_id": row.get("account_id"),
                    "status": row.get("status"),
                    "is_internal_transfer": bool(row.get("is_internal_transfer")),
                    "account_name": account.get("account_name"),
                    "account_type": account.get("account_type"),
                }
            )
        return rows

    def transactions_between(self, org_id: str, start: date, end: date) -> list[dict]:
        result = (
            self.client.table("transactions")
            .select("transaction_id, date, gross_amount, payee, description, is_internal_transfer, metadata")
            .eq("org_id", org_id)
            .gte("date", start.isoformat())
            .lte("date", end.isoformat())
            .execute()
        )
        return result.data or []

    def count_pending(self, org_id: str, start: date | None = None, end: date | None = None) -> int:
        query = (
            self.client.table("transactions")
            .select("transaction_id", count="exact")
            .eq("org_id", org_id)
            .eq("status", "Pending_Review")
        )
        if start:
            query = query.gte("date", start.isoformat())
        if end:
            query = query.lte("date", end.isoformat())
        result = query.execute()
        return result.count or 0

    def list_receipts(self, org_id: str, start: date | None = None, end: date | None = None) -> list[dict]:
        query = self.client.table("receipts").select("*").eq("org_id", org_id).order("created_at", desc=True).limit(200)
        if start:
            query = query.gte("created_at", start.isoformat())
        if end:
            query = query.lte("created_at", f"{end.isoformat()}T23:59:59")
        return query.execute().data or []

    def insert_receipt(self, payload: dict) -> dict:
        result = self.client.table("receipts").insert(payload).execute()
        return result.data[0]

    def list_logs(self, org_id: str, start: date | None = None, end: date | None = None) -> list[dict]:
        query = self.client.table("vehicle_logbook").select("*").eq("org_id", org_id).order("date", desc=True).limit(400)
        if start:
            query = query.gte("date", start.isoformat())
        if end:
            query = query.lte("date", end.isoformat())
        return query.execute().data or []

    def latest_odometer(self, org_id: str) -> int | None:
        result = (
            self.client.table("vehicle_logbook")
            .select("odometer_end")
            .eq("org_id", org_id)
            .order("date", desc=True)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        return int(result.data[0]["odometer_end"])

    def insert_log(self, payload: dict) -> dict:
        body = {
            "org_id": payload["org_id"],
            "date": payload["date"] if isinstance(payload["date"], str) else payload["date"].isoformat(),
            "odometer_start": payload["odometer_start"],
            "odometer_end": payload["odometer_end"],
            "purpose": payload["purpose"],
            "notes": payload.get("notes"),
        }
        result = self.client.table("vehicle_logbook").insert(body).execute()
        return result.data[0]

    def list_tax(self, org_id: str) -> list[dict]:
        return (
            self.client.table("tax_records_historical")
            .select("*")
            .eq("org_id", org_id)
            .order("end_date", desc=True)
            .execute()
            .data
            or []
        )

    def insert_tax(self, payload: dict) -> dict:
        body = {
            "org_id": payload["org_id"],
            "period_type": payload["period_type"],
            "start_date": payload["start_date"] if isinstance(payload["start_date"], str) else payload["start_date"].isoformat(),
            "end_date": payload["end_date"] if isinstance(payload["end_date"], str) else payload["end_date"].isoformat(),
            "total_income": str(payload["total_income"]),
            "tax_paid": str(payload["tax_paid"]),
            "notes": payload.get("notes"),
        }
        return self.client.table("tax_records_historical").insert(body).execute().data[0]

    def list_assets(self, org_id: str) -> list[dict]:
        return (
            self.client.table("assets_depreciation")
            .select("*")
            .eq("org_id", org_id)
            .order("purchase_date", desc=True)
            .execute()
            .data
            or []
        )

    def insert_asset(self, payload: dict) -> dict:
        body = {
            "org_id": payload["org_id"],
            "asset_name": payload["asset_name"],
            "asset_class": payload.get("asset_class") or "other",
            "purchase_date": payload["purchase_date"] if isinstance(payload["purchase_date"], str) else payload["purchase_date"].isoformat(),
            "original_cost": str(payload["original_cost"]),
            "depreciation_method": payload["depreciation_method"],
            "depreciation_rate": str(payload["depreciation_rate"]),
            "business_use_percentage": str(payload.get("business_use_percentage") or "100"),
            "accumulated_depreciation": str(payload.get("accumulated_depreciation") or 0),
        }
        return self.client.table("assets_depreciation").insert(body).execute().data[0]

    def update_asset(self, org_id: str, asset_id: str, patch: dict) -> dict:
        body = {}
        if "purchase_date" in patch:
            value = patch["purchase_date"]
            body["purchase_date"] = value if isinstance(value, str) else value.isoformat()
        result = (
            self.client.table("assets_depreciation").update(body).eq("org_id", org_id).eq("asset_id", asset_id).execute()
        )
        if not result.data:
            raise KeyError(asset_id)
        return result.data[0]
