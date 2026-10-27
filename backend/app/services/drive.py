import io
import logging
import os
import re
from datetime import date

from app.config import Settings
from app.services.dates import nz_tax_year_ending

logger = logging.getLogger(__name__)

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(value: str) -> str:
    cleaned = _SAFE.sub("_", (value or "unknown").strip())[:80]
    return cleaned or "unknown"


class DriveStorage:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._service = None

    def status(self) -> tuple[bool, str]:
        if not self.settings.google_service_account_file:
            return False, "Add the service account JSON path as GOOGLE_SERVICE_ACCOUNT_FILE."
        if not os.path.exists(self.settings.google_service_account_file):
            return False, "The service account JSON file was not found at GOOGLE_SERVICE_ACCOUNT_FILE."
        if not self.settings.google_drive_root_folder_id:
            return False, "Set GOOGLE_DRIVE_ROOT_FOLDER_ID to the Drive folder you shared with the service account."
        return True, "Google Drive is ready."

    def available(self) -> bool:
        return self.status()[0]

    def _service_client(self):
        if self._service is not None:
            return self._service
        if not self.available():
            raise RuntimeError("Google Drive is not configured")
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        path = self.settings.google_service_account_file
        if not os.path.exists(path):
            raise RuntimeError(f"Service account file missing: {path}")
        creds = service_account.Credentials.from_service_account_file(
            path, scopes=["https://www.googleapis.com/auth/drive"]
        )
        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def _find_child(self, parent_id: str, name: str) -> str | None:
        service = self._service_client()
        escaped = name.replace("'", "\\'")
        query = f"name = '{escaped}' and '{parent_id}' in parents and trashed = false"
        result = service.files().list(q=query, fields="files(id, name)", pageSize=1).execute()
        files = result.get("files") or []
        return files[0]["id"] if files else None

    def _ensure_folder(self, parent_id: str, name: str) -> str:
        existing = self._find_child(parent_id, name)
        if existing:
            return existing
        service = self._service_client()
        meta = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        created = service.files().create(body=meta, fields="id").execute()
        return created["id"]

    def upload_receipt(
        self,
        *,
        txn_date: date,
        category: str,
        vendor: str,
        filename: str,
        content: bytes,
        mime: str,
    ) -> tuple[str, str]:
        from googleapiclient.http import MediaIoBaseUpload

        root = self.settings.google_drive_root_folder_id
        year_folder = self._ensure_folder(root, f"FY{nz_tax_year_ending(txn_date)}")
        expenses = self._ensure_folder(year_folder, "Expenses")
        category_folder = self._ensure_folder(expenses, safe_name(category))

        stored_name = f"{safe_name(vendor)}_{txn_date.isoformat()}.pdf"
        if not filename.lower().endswith(".pdf"):
            stored_name = f"{safe_name(vendor)}_{txn_date.isoformat()}_{safe_name(filename)}"

        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime or "application/pdf", resumable=False)
        service = self._service_client()
        created = (
            service.files()
            .create(
                body={"name": stored_name, "parents": [category_folder]},
                media_body=media,
                fields="id, webViewLink",
            )
            .execute()
        )
        file_id = created["id"]
        url = created.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"
        logger.info("Stored receipt %s", stored_name)
        return file_id, url
