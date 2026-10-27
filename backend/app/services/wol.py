import logging
import socket
import time

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


def _magic_packet(mac: str) -> bytes:
    clean = mac.replace(":", "").replace("-", "").replace(".", "").lower()
    if len(clean) != 12:
        raise ValueError("WOL_MAC_ADDRESS must be 12 hex digits")
    return bytes.fromhex("ff" * 6 + clean * 16)


def send_wol(settings: Settings) -> None:
    packet = _magic_packet(settings.wol_mac_address)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (settings.wol_broadcast, settings.wol_port))
    logger.info("Wake-on-LAN packet sent to %s", settings.wol_mac_address)


async def ollama_is_up(base_url: str, timeout: float = 4.0) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{base_url.rstrip('/')}/api/tags")
            return response.status_code == 200
    except httpx.HTTPError:
        return False


async def ensure_ocr_host(settings: Settings) -> None:
    if await ollama_is_up(settings.ocr_tailscale_host):
        return
    if not settings.wol_enabled or not settings.wol_mac_address:
        raise RuntimeError("OCR workstation is offline and Wake-on-LAN is not configured")

    send_wol(settings)
    deadline = time.monotonic() + settings.wol_wait_seconds
    while time.monotonic() < deadline:
        if await ollama_is_up(settings.ocr_tailscale_host, timeout=3.0):
            return
        time.sleep(3)
    raise RuntimeError("OCR workstation did not come online after Wake-on-LAN")
