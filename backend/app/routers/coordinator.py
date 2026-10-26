from fastapi import APIRouter, Depends, Query

from app.deps import idempotency_key, require_role, run_idempotent
from app.schemas import ApproveIn, MatchRunIn, NoticeIn
from app.services import confirm_service, coordinator_service, evaluation_service, matching_service

router = APIRouter(prefix="/coordinator", tags=["coordinator"])
COORD = require_role("COORDINATOR")


@router.post("/matching/run")
def run(body: MatchRunIn, user: dict = Depends(COORD), key: str = Depends(idempotency_key)):
    return run_idempotent(user["id"], "matching", key, lambda: matching_service.run_matching(body.round_no))


@router.get("/drafts")
def drafts(roundNo: int = Query(1), user: dict = Depends(COORD)):
    return coordinator_service.list_drafts(roundNo)


@router.get("/drafts/{draft_id}")
def draft(draft_id: int, user: dict = Depends(COORD)):
    return coordinator_service.draft_detail(draft_id)


@router.post("/drafts/{draft_id}/approve")
def approve(draft_id: int, body: ApproveIn, user: dict = Depends(COORD), key: str = Depends(idempotency_key)):
    return run_idempotent(user["id"], f"approve:{draft_id}", key, lambda: confirm_service.approve_draft(draft_id, body.version))


@router.post("/notice")
def notice(body: NoticeIn, user: dict = Depends(COORD), key: str = Depends(idempotency_key)):
    return run_idempotent(user["id"], "notice", key, lambda: coordinator_service.send_notice(body.message, body.audience))


@router.get("/ranking")
def ranking(companyId: int = Query(...), user: dict = Depends(COORD)):
    return evaluation_service.ranking_for_company(companyId)
