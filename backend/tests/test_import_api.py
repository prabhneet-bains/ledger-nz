import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.deps import Principal, get_principal
from app.localdb import DEV_ORG_ID, DEV_USER_ID, SessionLocal, init_local_db, reset_engine, seed_local_practice
from app.main import app
from app.store import SqlStore

SAMPLE = """Date,Amount,Payee,Particulars,Reference
01/10/2026,5750.00,Acme Consulting,October retainer,INV-1042
02/10/2026,-64.50,Z Energy Papamoa,Fuel,CARD
02/10/2026,-64.50,TFR 06-0492-0123456-00,To savings,TFR
03/10/2026,64.50,TRANSFER FROM CHEQUE,From everyday,TFR
04/10/2026,-22.99,Adobe Systems,Subscription,ADOBE
05/10/2026,-115.00,Countdown Tauranga,Groceries,POS
"""

MAPPING = '{"date":"Date","amount":"Amount","payee":"Payee","reference":"Reference","description":"Particulars"}'


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("ALLOW_DEV_AUTH", "true")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")
    monkeypatch.setenv("SEED_FY_STATEMENT", "false")
    get_settings.cache_clear()
    reset_engine()
    init_local_db()
    seed_local_practice()
    session = SessionLocal()
    store = SqlStore(session)
    app.dependency_overrides[get_principal] = lambda: Principal(DEV_USER_ID, DEV_ORG_ID, "test", store)
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
    session.close()
    reset_engine()
    get_settings.cache_clear()


def test_csv_import_excludes_transfers_from_pnl(api: TestClient):
    files = {"file": ("bank.csv", SAMPLE, "text/csv")}
    preview = api.post("/csv/preview", files=files)
    assert preview.status_code == 200
    assert preview.json()["row_count"] == 6

    analyzed = api.post("/csv/analyze", files={"file": ("bank.csv", SAMPLE, "text/csv")}, data={"mapping": MAPPING})
    assert analyzed.status_code == 200
    body = analyzed.json()
    assert body["internal_transfers"] == 2
    assert body["pending_review"] == 1
    assert body["ready"] == 3

    imported = api.post("/csv/import", files={"file": ("bank.csv", SAMPLE, "text/csv")}, data={"mapping": MAPPING})
    assert imported.status_code == 200
    assert imported.json()["inserted"] == 6

    again = api.post("/csv/import", files={"file": ("bank.csv", SAMPLE, "text/csv")}, data={"mapping": MAPPING})
    assert again.json()["skipped_duplicates"] == 6
    assert again.json()["inserted"] == 0

    pnl = api.get("/dashboard/pnl", params={"start": "2026-04-01", "end": "2027-03-31"})
    assert pnl.status_code == 200
    snapshot = pnl.json()
    assert snapshot["total_income"] == "5000.00"
    assert snapshot["total_expense"] == "76.08"
    assert snapshot["net_profit"] == "4923.92"
    assert snapshot["transfers_excluded"] == 2
    assert snapshot["uncoded_count"] == 1

    gst = api.get("/dashboard/gst", params={"start": "2026-04-01", "end": "2027-03-31"})
    schedule = gst.json()
    assert schedule["output_gst"] == "750.00"
    assert schedule["input_gst"] == "11.41"
    assert schedule["gst_to_pay"] == "738.59"

    names = {line["account_name"] for line in snapshot["lines"]}
    assert "Countdown Tauranga" not in names
    assert "Consulting Fees" in names


def test_logbook_chains_odometer(api: TestClient):
    first = api.post("/logbook", json={"date": "2026-10-01", "odometer_end": 12010, "purpose": "Business", "odometer_start": 12000})
    assert first.status_code == 200
    assert first.json()["distance"] == 10
    second = api.post("/logbook", json={"date": "2026-10-02", "odometer_end": 12040, "purpose": "Personal"})
    assert second.status_code == 200
    assert second.json()["odometer_start"] == 12010
    assert second.json()["distance"] == 30
    listed = api.get("/logbook")
    assert listed.json()["next_odometer_start"] == 12040


PARTIAL = """Date,Amount,Payee,Particulars,Reference
01/10/2026,5750.00,Acme Consulting,October retainer,
02/10/2026,-64.50,Z Energy Papamoa,Fuel,
06/10/2026,-5.50,Cafe Flat White,Coffee,
"""

FULL_YEAR = """Date,Amount,Payee,Particulars,Reference
01/10/2026,5750.00,Acme Consulting,October retainer,INV-1042
02/10/2026,-64.50,Z Energy Papamoa,Fuel,CARD
02/10/2026,-64.50,TFR 06-0492-0123456-00,To savings,TFR
03/10/2026,64.50,TRANSFER FROM CHEQUE,From everyday,TFR
04/10/2026,-22.99,Adobe Systems,Subscription,ADOBE
05/10/2026,-115.00,Countdown Tauranga,Groceries,POS
06/10/2026,-5.50,Cafe Flat White,Coffee,POS
06/10/2026,-5.50,Cafe Flat White,Coffee,POS
"""

OPERATING = """Date,Amount,Payee,Particulars,Reference
01/04/2026,-500.00,SAVINGS,Move surplus,OP1
02/04/2026,-300.00,GST provision,Set aside GST,OP2
03/04/2026,-800.00,TAX provision,Set aside tax,OP3
01/04/2026,-500.00,Z Energy Papamoa,Fuel,CARD
04/04/2026,-900.00,Inland Revenue,GST payment,IRD
"""

SAVINGS = """Date,Amount,Payee,Particulars,Reference
01/04/2026,500.00,TRANSACTIONS,From operating,SV1
02/04/2026,300.00,TRANSACTIONS,GST set aside,SV2
03/04/2026,800.00,TRANSACTIONS,Tax set aside,SV3
"""


def _import(api: TestClient, text: str):
    return api.post("/csv/import", files={"file": ("bank.csv", text, "text/csv")}, data={"mapping": MAPPING})


def test_partial_then_full_year_skips_overlap_and_keeps_twins(api: TestClient):
    first = _import(api, PARTIAL)
    assert first.status_code == 200
    assert first.json()["inserted"] == 3

    second = _import(api, FULL_YEAR)
    assert second.json()["inserted"] == 5
    assert second.json()["skipped_duplicates"] == 3

    pnl = api.get("/dashboard/pnl", params={"start": "2026-04-01", "end": "2027-03-31"})
    snapshot = pnl.json()
    assert snapshot["total_income"] == "5000.00"
    assert snapshot["total_expense"] == "76.08"
    assert snapshot["transfers_excluded"] == 2
    cafes = [row for row in api.get("/transactions").json() if row["payee"] == "Cafe Flat White"]
    assert len(cafes) == 2


def test_savings_and_transactions_transfers_pair_across_uploads(api: TestClient):
    operating = _import(api, OPERATING)
    assert operating.json()["inserted"] == 5
    assert operating.json()["internal_transfers"] == 1

    savings = _import(api, SAVINGS)
    assert savings.json()["inserted"] == 3
    assert savings.json()["internal_transfers"] == 3

    rows = api.get("/transactions").json()

    def flagged(payee: str) -> list[bool]:
        return [row["is_internal_transfer"] for row in rows if row["payee"] == payee]

    assert flagged("SAVINGS") == [True]
    assert flagged("GST provision") == [True]
    assert flagged("TAX provision") == [True]
    assert flagged("TRANSACTIONS") == [True, True, True]
    assert flagged("Z Energy Papamoa") == [False]
    assert flagged("Inland Revenue") == [False]

    pnl = api.get("/dashboard/pnl", params={"start": "2026-04-01", "end": "2027-03-31"})
    assert pnl.json()["transfers_excluded"] == 6
    assert pnl.json()["total_income"] == "0.00"


CLIENTS = """Date,Amount,Payee,Particulars,Reference
01/06/2026,1000.00,Harbour Clinic,June,A
02/06/2026,800.00,Harbour Clinic,July,B
03/06/2026,-40.00,Harbour Clinic,Refund,C
04/06/2026,500.00,Other Client,Work,D
"""

LATER = """Date,Amount,Payee,Particulars,Reference
05/07/2026,900.00,Harbour Clinic,August,E
05/07/2026,-25.00,Harbour Clinic,Coffee,F
"""


def _account_id(api: TestClient, name: str) -> str:
    accounts = api.get("/accounts").json()
    match = next(row for row in accounts if row["account_name"] == name)
    return match["account_id"]


def test_bulk_review_remembers_payee_for_later_imports(api: TestClient):
    imported = _import(api, CLIENTS)
    assert imported.json()["inserted"] == 4
    assert imported.json()["pending_review"] == 4

    pending = api.get("/transactions", params={"status": "Pending_Review"}).json()
    harbour_in = [row for row in pending if row["payee"] == "Harbour Clinic" and float(row["gross_amount"]) > 0]
    assert len(harbour_in) == 2
    first = harbour_in[0]
    similar = api.get(
        "/transactions/similar",
        params={"payee": "harbour   clinic", "direction": "in", "exclude": first["transaction_id"]},
    )
    assert similar.status_code == 200
    assert len(similar.json()) == 1
    assert similar.json()[0]["payee"] == "Harbour Clinic"

    coded = api.post(
        "/transactions/bulk-code",
        json={
            "account_id": _account_id(api, "Consulting Fees"),
            "transaction_ids": [row["transaction_id"] for row in harbour_in],
            "remember_payee": True,
        },
    )
    assert coded.status_code == 200
    assert coded.json()["updated"] == 2
    assert coded.json()["rule"]["keyword"] == "HARBOUR CLINIC"

    later = _import(api, LATER)
    assert later.json()["inserted"] == 2
    rows = api.get("/transactions").json()
    august = next(row for row in rows if row["description"].startswith("Harbour Clinic | August"))
    coffee = next(row for row in rows if "Coffee" in row["description"])
    refund = next(row for row in rows if "Refund" in row["description"])
    assert august["status"] == "Reconciled"
    assert august["account_id"] == _account_id(api, "Consulting Fees")
    assert coffee["status"] == "Pending_Review"
    assert refund["status"] == "Pending_Review"


def test_partial_business_use_feeds_pnl_gst_and_ird_tax(api: TestClient):
    home = _account_id(api, "Home Office")
    created = api.post(
        "/transactions",
        json={
            "date": "2026-10-01",
            "account_id": home,
            "description": "Power bill",
            "gross_amount": "230.00",
            "source": "AdHoc",
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["business_claim_percentage"] == "50.00"
    assert body["gross_amount"] == "-230.00"
    assert body["gst_amount"] == "-15.00"
    assert body["net_amount"] == "-100.00"

    adjusted = api.patch(
        f"/transactions/{body['transaction_id']}",
        json={"account_id": home, "business_claim_percentage": "80", "status": "Reconciled"},
    )
    assert adjusted.status_code == 200, adjusted.text
    assert adjusted.json()["business_claim_percentage"] == "80.00"
    assert adjusted.json()["gst_amount"] == "-24.00"
    assert adjusted.json()["net_amount"] == "-160.00"

    pnl = api.get("/dashboard/pnl", params={"start": "2026-04-01", "end": "2027-03-31"}).json()
    assert pnl["total_expense"] == "160.00"
    assert pnl["private_excluded"] == "46.00"
    assert pnl["expense_lines"][0]["account_name"] == "Home Office"
    gst = api.get("/dashboard/gst", params={"start": "2026-04-01", "end": "2027-03-31"}).json()
    assert gst["input_gst"] == "24.00"
    assert pnl["income_tax"]["income_tax"] == "0.00"

    income = api.post(
        "/transactions",
        json={
            "date": "2026-10-02",
            "account_id": _account_id(api, "Consulting Fees"),
            "description": "Retainer",
            "gross_amount": "5750.00",
            "source": "AdHoc",
        },
    )
    assert income.status_code == 200
    summary = api.get("/dashboard/summary").json()
    assert summary["pnl"]["total_income"] == "5000.00"
    assert summary["pnl"]["net_profit"] == "4840.00"
    assert summary["gst"]["output_gst"] == "750.00"
    assert summary["pnl"]["income_tax"]["income_tax"] == "508.20"


def test_registered_vehicle_purchase_leaves_expenses(api: TestClient):
    dealer = api.post(
        "/transactions",
        json={
            "date": "2026-09-28",
            "account_id": _account_id(api, "Motor Vehicle"),
            "description": "Santafe",
            "payee": "Easy auto 123 nz ltd",
            "gross_amount": "45488.00",
            "source": "AdHoc",
        },
    )
    deposit = api.post(
        "/transactions",
        json={
            "date": "2026-09-27",
            "account_id": _account_id(api, "Motor Vehicle"),
            "description": "Deposit",
            "payee": "EASYAUTO123 Manukau",
            "gross_amount": "500.00",
            "source": "AdHoc",
        },
    )
    fuel = api.post(
        "/transactions",
        json={
            "date": "2026-09-26",
            "account_id": _account_id(api, "Motor Vehicle"),
            "description": "Fuel",
            "payee": "Z Energy",
            "gross_amount": "64.50",
            "source": "AdHoc",
        },
    )
    assert dealer.status_code == deposit.status_code == fuel.status_code == 200
    added = api.post(
        "/assets",
        json={
            "asset_name": "Santafe",
            "asset_class": "passenger_vehicle",
            "purchase_date": "2026-10-01",
            "original_cost": "39989.56",
            "depreciation_method": "Diminishing_Value",
            "business_use_percentage": "80",
        },
    )
    assert added.status_code == 200, added.text

    pnl = api.get("/dashboard/pnl", params={"start": "2026-04-01", "end": "2027-03-31"}).json()
    names = {line["account_name"]: line["net_amount"] for line in pnl["expense_lines"]}
    assert "Motor Vehicle" in names
    assert abs(float(names["Motor Vehicle"])) < 100
    assert pnl["depreciation"]["total"] == "5598.54"
    assert pnl["depreciation"]["lines"][0]["months"] == 7
    assert float(pnl["total_expense"]) < 6000


def test_vehicle_purchase_is_depreciated_not_expensed(api: TestClient):
    created = api.post(
        "/transactions",
        json={
            "date": "2026-04-01",
            "account_id": _account_id(api, "Motor Vehicle"),
            "description": "Dealer invoice",
            "payee": "City Motors",
            "gross_amount": "23000.00",
            "source": "AdHoc",
        },
    )
    assert created.status_code == 200, created.text
    capital = api.post(
        "/assets/capitalise",
        json={
            "transaction_id": created.json()["transaction_id"],
            "asset_name": "Consultancy car",
            "business_use_percentage": "100",
            "depreciation_method": "Diminishing_Value",
        },
    )
    assert capital.status_code == 200, capital.text
    assert capital.json()["asset"]["depreciation_rate"] == "30.00"
    assert capital.json()["asset"]["original_cost"] == "20000.00"

    pnl = api.get("/dashboard/pnl", params={"start": "2026-04-01", "end": "2027-03-31"}).json()
    assert pnl["depreciation"]["total"] == "6000.00"
    assert pnl["total_expense"] == "6000.00"
    gst = api.get("/dashboard/gst", params={"start": "2026-04-01", "end": "2027-03-31"}).json()
    assert gst["input_gst"] == "3000.00"


def test_receipt_is_tracked_when_ocr_and_drive_are_off(api: TestClient, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("OCR_TAILSCALE_HOST", "")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
    monkeypatch.setenv("GOOGLE_DRIVE_ROOT_FOLDER_ID", "")
    get_settings.cache_clear()

    uploaded = api.post(
        "/receipts/upload",
        files={"file": ("note.png", b"\x89PNG\r\n", "image/png")},
        data={"txn_date": "2026-10-01"},
    )
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    assert body["needs_review"] is True
    assert body["ocr_provider"] == "none"
    assert "GOOGLE_DRIVE_ROOT_FOLDER_ID" in body["drive_message"] or "GOOGLE_SERVICE_ACCOUNT_FILE" in body["drive_message"]
    assert body["receipt"]["receipt_id"]

    listed = api.get("/receipts")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    setup = api.get("/receipts/setup")
    assert setup.json()["ocr_provider"] == "off"
    assert setup.json()["drive_ready"] is False
    assert len(setup.json()["steps"]) >= 5


def test_summary_and_lists_follow_the_selected_dates(api: TestClient):
    fees = _account_id(api, "Consulting Fees")
    september = api.post(
        "/transactions",
        json={
            "date": "2026-09-15",
            "account_id": fees,
            "description": "September retainer",
            "gross_amount": "115.00",
            "source": "AdHoc",
        },
    )
    assert september.status_code == 200, september.text
    october = api.post(
        "/transactions",
        json={
            "date": "2026-10-15",
            "account_id": fees,
            "description": "October retainer",
            "gross_amount": "230.00",
            "source": "AdHoc",
        },
    )
    assert october.status_code == 200, october.text

    summary = api.get("/dashboard/summary", params={"start": "2026-09-01", "end": "2026-09-30"})
    assert summary.status_code == 200, summary.text
    assert summary.json()["financial_year"] == {"start": "2026-09-01", "end": "2026-09-30"}
    assert summary.json()["pnl"]["total_income"] == "100.00"

    listed = api.get("/transactions", params={"start": "2026-10-01", "end": "2026-10-31"})
    assert [row["description"] for row in listed.json()] == ["October retainer"]

    api.post("/logbook", json={"date": "2026-09-02", "odometer_end": 10010, "purpose": "Business", "odometer_start": 10000})
    api.post("/logbook", json={"date": "2026-10-02", "odometer_end": 10040, "purpose": "Personal"})
    logs = api.get("/logbook", params={"start": "2026-10-01", "end": "2026-10-31"})
    assert logs.status_code == 200
    assert [row["date"] for row in logs.json()["logs"]] == ["2026-10-02"]
    assert logs.json()["next_odometer_start"] == 10040


def test_fy2027_statement_posts_july_to_september(api: TestClient):
    from app.localdb import ensure_fy2027_statement

    ensure_fy2027_statement()
    ensure_fy2027_statement()

    pnl = api.get("/dashboard/pnl", params={"start": "2026-07-01", "end": "2026-09-30"}).json()
    assert pnl["total_income"] == "47775.00"
    by_name = {line["account_name"]: line["net_amount"] for line in pnl["lines"]}
    assert by_name["Datacom income"] == "47775.00"
    assert by_name["Wages - Pammy"] == "-18000.00"
    assert by_name["Wages - Mannu"] == "-9000.00"
    assert by_name["Mortgage interest"] == "-1572.00"
    assert by_name["Air travel"] == "-1420.00"
    assert by_name["Subscriptions"] == "-219.00"

    gst = api.get("/dashboard/gst", params={"start": "2026-07-01", "end": "2026-09-30"}).json()
    assert gst["output_gst"] == "7166.25"

    september = api.get("/transactions", params={"start": "2026-09-01", "end": "2026-09-30", "limit": 500}).json()
    assert any(row["payee"] == "Datacom income" for row in september)
    july = api.get("/transactions", params={"start": "2026-07-01", "end": "2026-07-31", "limit": 500}).json()
    assert all(row["payee"] != "Datacom income" for row in july)

    assets = api.get("/assets", params={"start": "2026-04-01", "end": "2026-09-30"}).json()
    names = {row["asset_name"] for row in assets["assets"]}
    assert {"Plant and equipment", "Motor vehicle", "Motor vehicle (second)", "Office equipment"} <= names


def test_statement_skips_datacom_already_imported(api: TestClient):
    from app.localdb import ensure_fy2027_statement

    fees = _account_id(api, "Consulting Fees")
    created = api.post(
        "/transactions",
        json={
            "date": "2026-08-06",
            "account_id": fees,
            "payee": "DATACOM SYSTEMS",
            "description": "DATACOM SYSTEMS | V19225",
            "gross_amount": "10091.25",
            "source": "AdHoc",
        },
    )
    assert created.status_code == 200, created.text
    ensure_fy2027_statement()
    august = api.get("/transactions", params={"start": "2026-08-01", "end": "2026-08-31", "limit": 500}).json()
    assert [row["payee"] for row in august if row["payee"] == "Datacom income"] == []
    pnl = api.get("/dashboard/pnl", params={"start": "2026-08-01", "end": "2026-08-31"}).json()
    assert pnl["total_income"] == "8775.00"
