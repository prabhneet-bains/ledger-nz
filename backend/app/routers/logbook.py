from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import Principal, get_principal
from app.schemas import LogBulkCreate, LogEntryCreate

router = APIRouter(prefix="/logbook", tags=["logbook"])


@router.get("")
def list_logs(
    principal: Annotated[Principal, Depends(get_principal)],
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
):
    return {
        "logs": principal.store.list_logs(principal.org_id, start, end),
        "next_odometer_start": principal.store.latest_odometer(principal.org_id),
    }


def _insert(principal: Principal, entry: LogEntryCreate, running: int | None) -> tuple[dict, int]:
    start = entry.odometer_start if entry.odometer_start is not None else running
    if start is None:
        raise HTTPException(status_code=400, detail="odometer_start required for the first log entry")
    if entry.odometer_end < start:
        raise HTTPException(status_code=400, detail="odometer_end must be >= odometer_start")
    row = principal.store.insert_log(
        {
            "org_id": principal.org_id,
            "date": entry.date.isoformat(),
            "odometer_start": start,
            "odometer_end": entry.odometer_end,
            "purpose": entry.purpose,
            "notes": entry.notes,
        }
    )
    return row, entry.odometer_end


@router.post("")
def create_log(body: LogEntryCreate, principal: Annotated[Principal, Depends(get_principal)]):
    row, _end = _insert(principal, body, principal.store.latest_odometer(principal.org_id))
    return row


@router.post("/bulk")
def bulk_logs(body: LogBulkCreate, principal: Annotated[Principal, Depends(get_principal)]):
    created = []
    running = principal.store.latest_odometer(principal.org_id)
    for entry in sorted(body.entries, key=lambda item: item.date):
        row, running = _insert(principal, entry, running)
        created.append(row)
    return {"created": created, "next_odometer_start": running}
