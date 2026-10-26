"""Pydantic models for contract 4.3. Python snake_case <-> JSON camelCase (aliases)."""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

Skill = Literal["Coding", "Tech", "HR"]
EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ───────── requests ─────────
class RegisterIn(CamelModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(pattern=EMAIL_RE, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    reg_no: str = Field(min_length=1, max_length=40)
    branch: str = Field(min_length=1, max_length=80)
    skills: List[Skill] = []


class LoginIn(CamelModel):
    email: str
    password: str


class InterviewerProfileIn(CamelModel):
    company_id: int
    skill_tags: List[Skill]


class SlotRange(CamelModel):
    start: str
    end: str


class AvailabilityIn(CamelModel):
    slots: List[SlotRange]


class CancelIn(CamelModel):
    reason: str = Field(default="", max_length=500)


class ResultIn(CamelModel):
    verdict: Literal["PASS", "FAIL"]
    score: Optional[float] = Field(default=None, ge=0, le=100)


class Choice(CamelModel):
    slot_id: int
    rank: int


class PreferencesIn(CamelModel):
    company_id: int
    round_no: int = Field(ge=1, le=3)
    choices: List[Choice]


class MatchRunIn(CamelModel):
    round_no: int = Field(ge=1, le=3)


class ApproveIn(CamelModel):
    version: int


class NoticeIn(CamelModel):
    message: str = Field(min_length=1, max_length=1000)
    audience: Literal["ALL", "STUDENT", "INTERVIEWER", "STUDENTS", "INTERVIEWERS"] = "ALL"


class EvaluationIn(CamelModel):
    criteria: Dict[str, float]


# ───────── responses (documentation + validation of the camelCase shapes) ─────────
class UserOut(CamelModel):
    id: int
    name: str
    email: str
    role: str


class TokenOut(CamelModel):
    token: str
    user: UserOut


class PanelMember(CamelModel):
    interviewer_id: int
    name: str
    skill: Optional[str] = None


class InterviewOut(CamelModel):
    id: int
    student_id: int
    student_name: str
    company_id: int
    company_name: str
    round_no: int
    type: str
    start: str
    end: str
    room: Optional[str] = None
    status: str
    version: int
    panel: List[PanelMember]


class SlotOut(CamelModel):
    slot_id: int
    start: str
    end: str
    interviewer_names: List[str]
    room: Optional[str] = None


class CompanyOut(CamelModel):
    id: int
    name: str
    rounds_config: Any
    open_slot_count: int


class DraftSummaryOut(CamelModel):
    draft_id: int
    version: int
    status: str
    objective_value: float
    matched: int
    unmatched: int
    round_no: int


class CalendarEventOut(CamelModel):
    id: int
    title: str
    start: str
    end: str
    room: Optional[str] = None
    interviewer_names: List[str]
    status: str
