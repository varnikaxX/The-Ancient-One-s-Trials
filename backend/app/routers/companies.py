from fastapi import APIRouter, Depends, Query

from app import db
from app.deps import current_user
from app.errors import ApiError
from app.services import slot_service

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("")
def companies(user: dict = Depends(current_user)):
    rows = db.fetchall(
        """SELECT c.id, c.name, c.rounds_config,
                  (SELECT count(*) FROM availability_slots s JOIN interviewers iv ON iv.user_id = s.interviewer_id
                    WHERE iv.company_id = c.id AND iv.is_active AND s.status = 'FREE' AND s.room_id IS NOT NULL
                      AND s.start_ts > now()) AS open_slots
           FROM companies c ORDER BY c.name""")
    return [{"id": r["id"], "name": r["name"], "roundsConfig": r["rounds_config"], "openSlotCount": r["open_slots"]} for r in rows]


@router.get("/{company_id}/slots")
def company_slots(company_id: int, roundNo: int = Query(1), user: dict = Depends(current_user)):
    if not db.fetchone("SELECT 1 FROM companies WHERE id = %s", (company_id,)):
        raise ApiError("NOT_FOUND", "Company not found")
    return slot_service.list_company_slots(company_id, roundNo)
