import base64
import json
import logging
import re
from decimal import Decimal, InvalidOperation

import httpx

from app.config import Settings
from app.services.wol import ensure_ocr_host

logger = logging.getLogger(__name__)

EXTRACT_PROMPT = """You extract New Zealand GST invoices/receipts.
Return ONLY valid JSON with keys:
vendor_name (string),
total_amount (number, GST-inclusive if shown),
gst_number (string or null, NZ GST / IRD number),
category (string: one of Advertising, Bank Fees, Computer & Software, Motor Vehicle, Office Expenses, Professional Development, Subscriptions, Telephone & Internet, Travel, Home Office, Insurance, Accounting Fees, Consulting Fees, Other Income, Uncategorised Expense),
confidence (number 0-1).
Do not wrap in markdown.
"""


def _parse_json_blob(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


async def extract_receipt(settings: Settings, image_b64: str, mime: str) -> dict:
    await ensure_ocr_host(settings)
    payload = {
        "model": settings.ocr_model,
        "stream": False,
        "format": "json",
        "messages": [
            {
                "role": "user",
                "content": EXTRACT_PROMPT,
                "images": [image_b64],
            }
        ],
    }
    url = f"{settings.ocr_tailscale_host.rstrip('/')}/api/chat"
    async with httpx.AsyncClient(timeout=settings.ocr_timeout_seconds) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        body = response.json()

    raw = body.get("message", {}).get("content") or body.get("response") or "{}"
    return _normalise(_parse_json_blob(raw), mime, provider="ollama", raw=raw)


def _normalise(parsed: dict, mime: str, provider: str, raw: str, error: str | None = None) -> dict:
    try:
        amount = Decimal(str(parsed.get("total_amount") or parsed.get("amount") or "0"))
    except InvalidOperation:
        amount = Decimal("0")
    try:
        confidence = float(parsed.get("confidence") or (0.9 if amount and parsed.get("vendor_name") or parsed.get("description") else 0))
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence > 1:
        confidence = confidence / 100
    vendor = (parsed.get("vendor_name") or parsed.get("description") or "Unknown vendor").strip()
    return {
        "vendor_name": vendor or "Unknown vendor",
        "total_amount": amount,
        "gst_number": parsed.get("gst_number"),
        "category": (parsed.get("category") or parsed.get("tax_tag") or "Uncategorised Expense").strip(),
        "confidence": max(0.0, min(confidence, 1.0)),
        "mime": mime,
        "provider": provider,
        "raw": raw,
        "error": error,
    }


def empty_extraction(mime: str, filename: str, error: str) -> dict:
    vendor = (filename or "Receipt").rsplit(".", 1)[0] or "Receipt"
    return {
        "vendor_name": vendor,
        "total_amount": Decimal("0"),
        "gst_number": None,
        "category": "Uncategorised Expense",
        "confidence": 0.0,
        "mime": mime,
        "provider": "none",
        "raw": "",
        "error": error,
    }


async def _groq_extract(settings: Settings, content: bytes, mime: str) -> dict:
    """Same vision JSON shape as the Expense Tracker Groq upload, aimed at NZ GST fields."""
    image_url = f"data:{mime or 'image/jpeg'};base64,{base64.b64encode(content).decode('ascii')}"
    payload = {
        "model": settings.groq_vision_model,
        "temperature": 0,
        "max_tokens": 400,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": EXTRACT_PROMPT},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
    raw = body["choices"][0]["message"]["content"]
    return _normalise(_parse_json_blob(raw), mime, provider="groq", raw=raw)


def _pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    import io

    reader = PdfReader(io.BytesIO(content))
    return "\n".join((page.extract_text() or "") for page in reader.pages)[:8000]


async def _groq_text(settings: Settings, text: str, mime: str) -> dict:
    payload = {
        "model": settings.groq_vision_model,
        "temperature": 0,
        "max_tokens": 400,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": f"{EXTRACT_PROMPT}\n\nReceipt text:\n{text}"}],
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
    raw = body["choices"][0]["message"]["content"]
    return _normalise(_parse_json_blob(raw), mime, provider="groq", raw=raw)


async def extract_receipt_best(settings: Settings, content: bytes, mime: str, filename: str) -> dict:
    """Always returns an extraction dict. Failures are recorded instead of aborting the upload."""
    provider = settings.ocr_provider
    try:
        if provider == "groq":
            if mime == "application/pdf" or (filename or "").lower().endswith(".pdf"):
                text = _pdf_text(content)
                if not text.strip():
                    return empty_extraction(mime, filename, "This PDF has no text layer. Photograph the receipt or upload an image.")
                return await _groq_text(settings, text, mime)
            return await _groq_extract(settings, content, mime)
        if provider == "ollama":
            if not mime.startswith("image/"):
                return empty_extraction(mime, filename, "Local Ollama OCR accepts images. Upload a photo, or set GROQ_API_KEY for PDFs.")
            encoded = base64.b64encode(content).decode("ascii")
            return await extract_receipt(settings, encoded, mime)
        return empty_extraction(
            mime,
            filename,
            "OCR is not configured. Set GROQ_API_KEY (same approach as Expense Tracker) or OCR_TAILSCALE_HOST for the local workstation.",
        )
    except Exception as exc:
        logger.exception("Receipt OCR failed")
        return empty_extraction(mime, filename, str(exc))
