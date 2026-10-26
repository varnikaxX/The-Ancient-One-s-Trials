from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.deps import current_user_or_query_token, idempotency_key, require_role, run_idempotent
from app.schemas import PreferencesIn
from app.services import ics_service, preference_service

router = APIRouter(prefix="/student", tags=["student"])
STUDENT = require_role("STUDENT")


@router.post("/preferences")
def preferences(body: PreferencesIn, user: dict = Depends(STUDENT), key: str = Depends(idempotency_key)):
    return run_idempotent(user["id"], "preferences", key, lambda: preference_service.submit(user["id"], body, key))


@router.get("/status")
def status(user: dict = Depends(STUDENT)):
    return preference_service.student_status(user["id"])


@router.get("/interviews/{interview_id}/ics")
def ics(interview_id: int, user: dict = Depends(current_user_or_query_token)):
    interview = ics_service.can_download(user, interview_id)
    return Response(ics_service.build_ics_for(interview), media_type="text/calendar",
                    headers={"Content-Disposition": f'attachment; filename="interview-{interview_id}.ics"'})
