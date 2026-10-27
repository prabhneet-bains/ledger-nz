from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from app.config import get_settings
from app.deps import Principal, get_principal
from app.services.categorizer import account_name_to_id
from app.services.drive import DriveStorage
from app.services.ledger import insert_transaction
from app.services.ocr import extract_receipt_best

DRIVE_STEPS = [
    "In Google Cloud Console, create or select a project and enable the Google Drive API.",
    "Create a service account and download its JSON key. Put that file outside the repo, for example backend/secrets/google-service-account.json.",
    "Set GOOGLE_SERVICE_ACCOUNT_FILE to that path and restart the API.",
    "In Google Drive, create a folder such as Ledger NZ Receipts. Share it with the service account email (Editor).",
    "Copy the folder id from the Drive URL (the part after /folders/) into GOOGLE_DRIVE_ROOT_FOLDER_ID and restart the API.",
    "Uploads then land in /FY{year ending 31 March}/Expenses/{Category}/{Vendor}_{Date}.",
]

router = APIRouter(prefix="/receipts", tags=["receipts"])


@router.get("")
def list_receipts(
    principal: Annotated[Principal, Depends(get_principal)],
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
):
    return principal.store.list_receipts(principal.org_id, start, end)


@router.get("/setup")
def receipt_setup(principal: Annotated[Principal, Depends(get_principal)]):
    settings = get_settings()
    storage = DriveStorage(settings)
    ready, drive_message = storage.status()
    return {
        "ocr_provider": settings.ocr_provider,
        "drive_ready": ready,
        "drive_message": drive_message,
        "steps": DRIVE_STEPS,
    }


@router.post("/upload")
async def upload_receipt(
    principal: Annotated[Principal, Depends(get_principal)],
    file: UploadFile = File(...),
    txn_date: date | None = Form(default=None),
):
    settings = get_settings()
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > 12 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Receipt exceeds 12 MB")

    mime = file.content_type or "application/octet-stream"
    txn_date = txn_date or date.today()
    extracted = await extract_receipt_best(settings, content, mime, file.filename or "receipt")

    accounts = principal.store.list_accounts(principal.org_id)
    account_id = account_name_to_id(accounts, extracted["category"])
    confidence = extracted["confidence"]
    needs_review = confidence < settings.confidence_floor or account_id is None
    if account_id is None:
        account_id = account_name_to_id(accounts, "Uncategorised Expense")

    category_label = extracted["category"]
    vendor = extracted["vendor_name"]
    drive_id = None
    drive_url = None
    storage = DriveStorage(settings)
    drive_ready, drive_message = storage.status()
    if drive_ready:
        try:
            drive_id, drive_url = storage.upload_receipt(
                txn_date=txn_date,
                category=category_label,
                vendor=vendor,
                filename=file.filename or "receipt",
                content=content,
                mime=mime,
            )
            drive_message = "Saved to Google Drive."
        except Exception as exc:
            drive_message = f"Drive upload failed: {exc}"

    transaction = insert_transaction(
        principal.store,
        org_id=principal.org_id,
        txn_date=txn_date,
        account_id=account_id,
        payee=vendor[:200],
        description=f"{vendor} (receipt)",
        gross_amount=Decimal(str(extracted["total_amount"])),
        source="ReceiptScan",
        status="Pending_Review" if needs_review else "Reconciled",
        metadata={
            "ocr_confidence": confidence,
            "ocr_provider": extracted.get("provider"),
            "ocr_error": extracted.get("error"),
            "gst_number": extracted.get("gst_number"),
        },
    )

    receipt = principal.store.insert_receipt(
        {
            "org_id": principal.org_id,
            "transaction_id": transaction["transaction_id"],
            "drive_file_id": drive_id,
            "drive_file_url": drive_url,
            "vendor_name": vendor,
            "extracted_amount": str(extracted["total_amount"]),
            "gst_number": extracted.get("gst_number"),
            "inferred_category": category_label,
            "confidence_score": confidence,
            "ocr_raw": extracted.get("raw") or "",
        }
    )
    return {
        "receipt": receipt,
        "transaction": transaction,
        "needs_review": needs_review,
        "ocr_provider": extracted.get("provider"),
        "ocr_error": extracted.get("error"),
        "drive_message": drive_message,
    }
