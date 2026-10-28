-- 001_init.sql : The Ancient One's Trials — schema (contract 4.2)
-- Plain SQL, PostgreSQL 14+. Run via db/migrate.py (tracks applied files).

CREATE EXTENSION IF NOT EXISTS btree_gist;

-- ───────────── enums (values are the shared contract strings) ─────────────
CREATE TYPE role_t              AS ENUM ('STUDENT', 'INTERVIEWER', 'COORDINATOR');
CREATE TYPE slot_status_t       AS ENUM ('FREE', 'HELD', 'BOOKED');
CREATE TYPE preference_status_t AS ENUM ('PENDING', 'MATCHED', 'UNMATCHED', 'CANCELLED');
CREATE TYPE interview_type_t    AS ENUM ('ONE_ON_ONE', 'PANEL');
CREATE TYPE interview_status_t  AS ENUM ('PROPOSED', 'INTERVIEWER_CONFIRMED', 'CONFIRMED', 'FLAGGED', 'CANCELLED', 'COMPLETED');
CREATE TYPE draft_status_t      AS ENUM ('DRAFT', 'APPROVED', 'SUPERSEDED');
CREATE TYPE verdict_t           AS ENUM ('PASS', 'FAIL');
CREATE TYPE channel_t           AS ENUM ('IN_APP', 'EMAIL');
CREATE TYPE outbox_status_t     AS ENUM ('PENDING', 'SENT', 'FAILED');

-- ───────────── identity ─────────────
CREATE TABLE users (
    id            serial PRIMARY KEY,
    name          text   NOT NULL CHECK (length(name) > 0),
    email         text   NOT NULL UNIQUE,
    password_hash text   NOT NULL,
    role          role_t NOT NULL
);

CREATE TABLE students (
    user_id       integer PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    reg_no        text    NOT NULL UNIQUE,
    branch        text    NOT NULL,
    skills        text[]  NOT NULL DEFAULT '{}',
    passed_rounds integer[] NOT NULL DEFAULT '{}'
);

CREATE TABLE companies (
    id            serial PRIMARY KEY,
    name          text   NOT NULL UNIQUE,
    rounds_config jsonb  NOT NULL DEFAULT '[]'::jsonb,
    panel_skills  text[] NOT NULL DEFAULT '{}'
);

CREATE TABLE interviewers (
    user_id    integer PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    company_id integer REFERENCES companies(id),
    skill_tags text[]  NOT NULL DEFAULT '{}',
    is_active  boolean NOT NULL DEFAULT true
);

CREATE TABLE rooms (
    id       serial PRIMARY KEY,
    name     text    NOT NULL UNIQUE,
    capacity integer NOT NULL DEFAULT 1 CHECK (capacity > 0)
);

-- ───────────── availability & preferences ─────────────
CREATE TABLE availability_slots (
    id             serial PRIMARY KEY,
    interviewer_id integer       NOT NULL REFERENCES interviewers(user_id) ON DELETE CASCADE,
    start_ts       timestamptz   NOT NULL,
    end_ts         timestamptz   NOT NULL,
    status         slot_status_t NOT NULL DEFAULT 'FREE',
    room_id        integer       REFERENCES rooms(id),
    CHECK (end_ts > start_ts),
    UNIQUE (interviewer_id, start_ts)
);
CREATE INDEX idx_slots_interviewer_start ON availability_slots (interviewer_id, start_ts);
CREATE INDEX idx_slots_status_start      ON availability_slots (status, start_ts);

CREATE TABLE slot_preferences (
    id              serial PRIMARY KEY,
    student_id      integer NOT NULL REFERENCES students(user_id) ON DELETE CASCADE,
    slot_id         integer NOT NULL REFERENCES availability_slots(id) ON DELETE CASCADE,
    company_id      integer NOT NULL REFERENCES companies(id),
    round_no        integer NOT NULL CHECK (round_no BETWEEN 1 AND 3),
    rank            integer NOT NULL CHECK (rank BETWEEN 1 AND 3),
    status          preference_status_t NOT NULL DEFAULT 'PENDING',
    idempotency_key text UNIQUE,
    UNIQUE (student_id, round_no, company_id, rank),
    UNIQUE (student_id, round_no, company_id, slot_id)
);
CREATE INDEX idx_prefs_company_round_status ON slot_preferences (company_id, round_no, status);

-- ───────────── scheduling output ─────────────
CREATE TABLE schedule_drafts (
    id              serial PRIMARY KEY,
    round_no        integer NOT NULL CHECK (round_no BETWEEN 1 AND 3),
    version         integer NOT NULL,
    status          draft_status_t NOT NULL DEFAULT 'DRAFT',
    objective_value numeric NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now(),
    matched         integer NOT NULL DEFAULT 0,           -- extra (denormalised count)
    unmatched       jsonb   NOT NULL DEFAULT '[]'::jsonb, -- extra: [{studentId, reason}]
    UNIQUE (round_no, version)
);

CREATE TABLE interviews (
    id         serial PRIMARY KEY,
    student_id integer NOT NULL REFERENCES students(user_id),
    company_id integer NOT NULL REFERENCES companies(id),
    round_no   integer NOT NULL CHECK (round_no BETWEEN 1 AND 3),
    type       interview_type_t   NOT NULL DEFAULT 'ONE_ON_ONE',
    start_ts   timestamptz NOT NULL,
    end_ts     timestamptz NOT NULL,
    room_id    integer REFERENCES rooms(id),
    status     interview_status_t NOT NULL DEFAULT 'PROPOSED',
    version    integer NOT NULL DEFAULT 1,
    draft_id   integer REFERENCES schedule_drafts(id) ON DELETE SET NULL,
    CHECK (end_ts > start_ts),
    -- Final guards (invariant 1): once an interview is committed, neither the room
    -- nor the student can be in two overlapping interviews. Deferrable so a repair
    -- transaction may shuffle rows and be checked at commit.
    CONSTRAINT interviews_room_no_overlap EXCLUDE USING gist
        (room_id WITH =, tstzrange(start_ts, end_ts) WITH &&)
        WHERE (room_id IS NOT NULL AND status IN ('CONFIRMED', 'FLAGGED', 'COMPLETED'))
        DEFERRABLE INITIALLY IMMEDIATE,
    CONSTRAINT interviews_student_no_overlap EXCLUDE USING gist
        (student_id WITH =, tstzrange(start_ts, end_ts) WITH &&)
        WHERE (status IN ('CONFIRMED', 'FLAGGED', 'COMPLETED'))
        DEFERRABLE INITIALLY IMMEDIATE
);
CREATE INDEX idx_interviews_student ON interviews (student_id, status);
CREATE INDEX idx_interviews_company_round ON interviews (company_id, round_no, status);
CREATE INDEX idx_interviews_draft ON interviews (draft_id);
-- one live interview per student per company per round
CREATE UNIQUE INDEX uq_interviews_live_student_company_round
    ON interviews (student_id, company_id, round_no)
    WHERE status <> 'CANCELLED';

-- A one-on-one interview is a panel of one: this table is always used.
-- start_ts/end_ts are copied from the slot so the exclusion constraint can see them.
-- `booked` becomes true only when the coordinator approves (PROPOSED rows may overlap
-- across drafts; BOOKED rows may never).
CREATE TABLE interview_panel (
    interview_id   integer     NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
    interviewer_id integer     NOT NULL REFERENCES interviewers(user_id),
    slot_id        integer     NOT NULL REFERENCES availability_slots(id),
    start_ts       timestamptz NOT NULL,
    end_ts         timestamptz NOT NULL,
    booked         boolean     NOT NULL DEFAULT false,
    confirmed      boolean     NOT NULL DEFAULT false,   -- extra: this panelist confirmed the proposal
    PRIMARY KEY (interview_id, interviewer_id),
    CHECK (end_ts > start_ts)
);
-- UNIQUE(slot_id): a slot can back only one interview (contract 4.2).
ALTER TABLE interview_panel ADD CONSTRAINT uq_panel_slot UNIQUE (slot_id);
ALTER TABLE interview_panel ADD CONSTRAINT panel_interviewer_no_overlap EXCLUDE USING gist
    (interviewer_id WITH =, tstzrange(start_ts, end_ts) WITH &&)
    WHERE (booked)
    DEFERRABLE INITIALLY IMMEDIATE;
CREATE INDEX idx_panel_slot ON interview_panel (slot_id);
CREATE INDEX idx_panel_interviewer ON interview_panel (interviewer_id);

-- ───────────── results / evaluations ─────────────
CREATE TABLE results (
    interview_id integer PRIMARY KEY REFERENCES interviews(id) ON DELETE CASCADE,
    verdict      verdict_t NOT NULL,
    score        numeric,
    declared_at  timestamptz NOT NULL DEFAULT now(),
    release_at   timestamptz NOT NULL DEFAULT now(),
    released     boolean NOT NULL DEFAULT false      -- extra: set by release_results_task
);
CREATE INDEX idx_results_release ON results (release_at) WHERE NOT released;

CREATE TABLE evaluations (
    id             serial PRIMARY KEY,
    interview_id   integer NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
    interviewer_id integer NOT NULL REFERENCES interviewers(user_id),
    criteria       jsonb   NOT NULL,
    total          numeric NOT NULL DEFAULT 0,
    submitted_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (interview_id, interviewer_id)
);

-- ───────────── notifications, outbox, idempotency, config ─────────────
CREATE TABLE notifications (
    id         serial PRIMARY KEY,
    user_id    integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type       text    NOT NULL,
    payload    jsonb   NOT NULL DEFAULT '{}'::jsonb,
    read_at    timestamptz,
    channel    channel_t NOT NULL DEFAULT 'IN_APP',
    created_at timestamptz NOT NULL DEFAULT now()       -- extra
);
CREATE INDEX idx_notifications_user ON notifications (user_id, read_at, id DESC);

CREATE TABLE outbox (
    id         bigserial PRIMARY KEY,
    kind       text NOT NULL CHECK (kind IN ('EMAIL', 'NOTIFY')),
    payload    jsonb NOT NULL,
    status     outbox_status_t NOT NULL DEFAULT 'PENDING',
    attempts   integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_error text
);
CREATE INDEX idx_outbox_status_created ON outbox (status, created_at);

CREATE TABLE idempotency_keys (
    key        text PRIMARY KEY,
    response   jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE config (
    key   text PRIMARY KEY,
    value text NOT NULL
);
INSERT INTO config (key, value) VALUES
    ('result_delay_minutes', '30'),
    ('matching_deadline',    '');   -- ISO-8601 UTC, empty = no automatic matching
