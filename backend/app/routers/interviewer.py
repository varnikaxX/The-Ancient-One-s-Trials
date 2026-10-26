from fastapi import APIRouter, Depends

from app.deps import idempotency_key, require_role, run_idempotent
from app.schemas import AvailabilityIn, CancelIn, EvaluationIn, InterviewerProfileIn, ResultIn
from app.services import (confirm_service, disruption_service, evaluation_service, result_service,
                          slot_service, user_service)

router = APIRouter(prefix="/interviewer", tags=["interviewer"])
INTERVIEWER = require_role("INTERVIEWER")


@router.put("/profile")
def put_profile(body: InterviewerProfileIn, user: dict = Depends(INTERVIEWER)):
    return user_service.update_interviewer_profile(user, body.company_id, body.skill_tags)


@router.put("/availability")
def put_availability(body: AvailabilityIn, user: dict = Depends(INTERVIEWER)):
    return slot_service.replace_availability(user["id"], body.slots)      # PUT = naturally idempotent


@router.get("/proposals")
def proposals(user: dict = Depends(INTERVIEWER)):
    return confirm_service.proposals_for(user["id"])


@router.post("/interviews/{interview_id}/confirm")
def confirm(interview_id: int, user: dict = Depends(INTERVIEWER), key: str = Depends(idempotency_key)):
    return run_idempotent(user["id"], f"confirm:{interview_id}", key,
                          lambda: confirm_service.interviewer_confirm(interview_id, user["id"]))


@router.post("/interviews/{interview_id}/cancel")
def cancel(interview_id: int, body: CancelIn, user: dict = Depends(INTERVIEWER), key: str = Depends(idempotency_key)):
    return run_idempotent(user["id"], f"cancel:{interview_id}", key,
                          lambda: disruption_service.cancel_interview(interview_id, user["id"], body.reason))


@router.post("/interviews/{interview_id}/result")
def result(interview_id: int, body: ResultIn, user: dict = Depends(INTERVIEWER), key: str = Depends(idempotency_key)):
    return run_idempotent(user["id"], f"result:{interview_id}", key,
                          lambda: result_service.declare_result(interview_id, user["id"], body.verdict, body.score))


@router.post("/interviews/{interview_id}/evaluation")
def evaluation(interview_id: int, body: EvaluationIn, user: dict = Depends(INTERVIEWER), key: str = Depends(idempotency_key)):
    return run_idempotent(user["id"], f"eval:{interview_id}", key,
                          lambda: evaluation_service.submit_evaluation(interview_id, user["id"], body.criteria))
