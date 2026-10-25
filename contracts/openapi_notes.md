# Shared contracts — Section 4 of the master prompt (FROZEN)

Text extracted from the master prompt (PDF extraction may have reflowed table columns). Nobody edits this file. `sql_schema.sql` mirrors `backend/db/migrations/001_init.sql`; `solver_io.json` holds the 4.4 examples.

```text
4. SHARED CONTRACTS (FROZEN — do not alter)
4.1 Enums (exact strings)
     role : STUDENT | INTERVIEWER | COORDINATOR
     skill : Coding | Tech | HR
     slot_status : FREE | HELD | BOOKED
     preference_status : PENDING | MATCHED | UNMATCHED | CANCELLED
     interview_type : ONE_ON_ONE | PANEL
     interview_status : PROPOSED | INTERVIEWER_CONFIRMED | CONFIRMED | FLAGGED | CANCELLED | COMPLETED
     draft_status : DRAFT | APPROVED | SUPERSEDED
     verdict : PASS | FAIL
     channel : IN_APP | EMAIL
     round_name (round_no 1..3): 1= Coding , 2= Tech , 3= HR
     Time format: ISO-8601 UTC strings ( 2026-11-03T09:00:00Z ). Slot length: 30 min (configurable constant SLOT_MINUTES=30 ).
4.2 Database schema (OWNER: Ishika; others READ-ONLY knowledge)
Tables (PostgreSQL), column names exact:
     users(id, name, email UNIQUE, password_hash, role)
     students(user_id PK→users, reg_no UNIQUE, branch, skills text[], passed_rounds int[] DEFAULT '{}')
     companies(id, name UNIQUE, rounds_config jsonb, panel_skills text[])
     interviewers(user_id PK→users, company_id→companies, skill_tags text[], is_active bool)
     rooms(id, name, capacity)
     availability_slots(id, interviewer_id→interviewers, start_ts, end_ts, status slot_status, room_id→rooms NULL) —
     UNIQUE(interviewer_id,start_ts); EXCLUDE USING gist (interviewer_id WITH =, tstzrange(start_ts,end_ts) WITH &&) for non-
     FREE bookings via interviews
     slot_preferences(id, student_id, slot_id, company_id, round_no, rank CHECK 1..3, status, idempotency_key UNIQUE)
     — UNIQUE(student_id,round_no,company_id,rank), UNIQUE(student_id,round_no,company_id,slot_id)
     schedule_drafts(id, round_no, version int, status, objective_value, created_at) — UNIQUE(round_no,version)
     interviews(id, student_id, company_id, round_no, type, start_ts, end_ts, room_id, status, version, draft_id)
     interview_panel(interview_id, interviewer_id, slot_id) — a one-on-one is a panel of one; UNIQUE(slot_id) enforces no
     double-booking; EXCLUDE (btree_gist) on interviewer + time range
     results(interview_id PK, verdict, score numeric, declared_at, release_at)
     evaluations(id, interview_id, interviewer_id, criteria jsonb, total numeric, submitted_at) (stretch)
     notifications(id, user_id, type, payload jsonb, read_at, channel)
     outbox(id, kind, payload jsonb, status PENDING|SENT|FAILED, attempts int, created_at)
     idempotency_keys(key PK, response jsonb, created_at)
     config(key PK, value) — e.g. result_delay_minutes , matching_deadline

4.3 REST API (base /api , JSON, Authorization: Bearer <JWT> ; write endpoints require header Idempotency-Key )
Error shape (all errors): {"error": {"code": "SLOT_TAKEN", "message": "Slot just taken, please pick another"}} . Codes:
UNAUTHORIZED, FORBIDDEN, VALIDATION, NOT_FOUND, SLOT_TAKEN, STALE_DRAFT, DUPLICATE .
Method & path                                     Role                Request → Response

POST /auth/register                               public (student)     {name,email,password,regNo,branch,skills[]} → {token,user}

POST /auth/login                                  public               {email,password} → {token,user:{id,name,email,role}}

GET /me                                           any                 → {user, profile}

GET /companies                                    any                 → [{id,name,roundsConfig,openSlotCount}]

GET /companies/{id}/slots?roundNo=1               any                 → [{slotId,start,end,interviewerNames[],room}] (only FREE &
                                                                      bookable)

PUT /interviewer/profile                          INTERVIEWER          {companyId,skillTags[]} → profile

PUT /interviewer/availability                     INTERVIEWER          {slots:[{start,end}]} (replaces future FREE slots) → [slot]

GET /interviewer/proposals                        INTERVIEWER         → [interview] with status PROPOSED

 POST                                             INTERVIEWER          {} → interview
/interviewer/interviews/{id}/confirm

 POST                                             INTERVIEWER          {reason} → {flaggedInterviews:[id]} (triggers repair)
/interviewer/interviews/{id}/cancel

 POST                                             INTERVIEWER          {verdict,score} → result
/interviewer/interviews/{id}/result

POST /student/preferences                         STUDENT             {companyId,roundNo,choices:[{slotId,rank}]} (1–3, unique ranks)
                                                                      → {status:"PENDING"}

GET /student/status                               STUDENT             → {preferences[], interviews[], statusText}

GET /student/interviews/{id}/ics                  STUDENT/INTERVIEWER → text/calendar

POST /coordinator/matching/run                    COORDINATOR          {roundNo} → {jobId} (async Celery)

GET /coordinator/drafts?roundNo=1                 COORDINATOR         →
                                                                      [{draftId,version,status,objectiveValue,matched,unmatched}]

GET /coordinator/drafts/{draftId}                 COORDINATOR         → {draft, interviews[], unmatchedStudents[]}

 POST                                             COORDINATOR          {version} → {committed:n} ; STALE_DRAFT if outdated
/coordinator/drafts/{draftId}/approve

POST /coordinator/notice                          COORDINATOR          {message,audience} → {queued:n}

GET /calendar?from=&to=                           any                 → [{id,title,start,end,room,interviewerNames[],status}]
                                                                      (FullCalendar-ready)

 GET /notifications / POST                        any                 list / mark read
/notifications/{id}/read

GET /events (SSE)                                 any                 stream of {type, payload} live notifications

GET /coordinator/ranking?companyId=               COORDINATOR         stretch: aggregated candidate ranking matrix

 POST                                             INTERVIEWER         stretch: {criteria:{...}} blinded
/interviewer/interviews/{id}/evaluation


 interview object (everywhere):
 {id,studentId,studentName,companyId,companyName,roundNo,type,start,end,room,status,version,panel:
[{interviewerId,name,skill}]}

4.4 Solver I/O contract (Varnika implements, Ishika calls)
Public functions (pure, deterministic, no I/O):
  python

  solve_batch(data: dict, time_limit_sec: int = 20) -> dict
  reschedule(data: dict, time_limit_sec: int = 10) -> dict


solve_batch input:

  json

  {
      "roundNo": 1,
      "slots":   [{"slotId": 1, "interviewerId": 7, "start": "...Z", "end": "...Z", "roomId": 2, "skillTags": ["Coding"]}],
      "rooms":   [{"roomId": 2}],
      "students":[{"studentId": 11, "prefs": [{"slotId": 1, "rank": 1}, {"slotId": 4, "rank": 2}]}],
      "panelRequirements": {"companyId": 3, "requiredSkills": []},
      "weights": {"rank1": 100, "rank2": 60, "rank3": 30, "unmatchedPenalty": 1000}
  }


solve_batch output:

  json

  {
      "status": "OPTIMAL|FEASIBLE|INFEASIBLE",
      "objectiveValue": 3440,
      "assignments": [{"studentId": 11, "slotId": 1, "rankGot": 1, "interviewerIds": [7], "roomId": 2}],
      "unmatched": [{"studentId": 12, "reason": "ALL_PREFERRED_SLOTS_TAKEN"}],
      "stats": {"matched": 40, "unmatched": 2, "rank1": 30, "rank2": 8, "rank3": 2, "wallTimeSec": 0.8}
  }


 reschedule input adds: "currentInterviews": [{"interviewId","studentId","slotId","interviewerIds","roomId","roundNo"}] ,
 "cancelled": {"interviewerId": 7, "slotIds": [1,2]} , "freeSlots": [...same shape as slots...] , "moveWeights":
{"movePenalty": 500, "swapInterviewer": 50, "nextRanked": 150, "nearestSlot": 300} . Output: {"status","moves":
[{"interviewId","studentId","fromSlotId","toSlotId","strategy":"SWAP_INTERVIEWER|NEXT_RANKED|NEAREST_FREE|UNRESOLVED","
newInterviewerIds":[...]}],"untouched":n,"unresolved":[studentId]} .

4.5 SSE / notification payload
 {"type":"INTERVIEW_CONFIRMED|INTERVIEW_CHANGED|INTERVIEW_CANCELLED|REMINDER|MATCH_FAILED|NOTICE|RESULT_RELEASED","payl
oad":{"interviewId":..,"message":"..."}}

4.6 Core invariants (everyone must respect)
  1. No interviewer, room or student is double-booked (DB constraint is the final guard).
  2. Submitting preferences does no heavy work; solving runs only in a Celery worker, once per batch.
  3. Coordinator approves a specific draft version ; stale versions are rejected ( STALE_DRAFT ).
  4. Commit + outbox rows in one transaction; email/notification delivery is async with retries.
  5. Write endpoints are idempotent via Idempotency-Key .
  6. A one-on-one interview is a panel of one ( interview_panel always used).

```
