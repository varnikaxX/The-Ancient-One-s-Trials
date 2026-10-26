"""Registration, login, profiles."""
import psycopg

from app import db
from app.errors import ApiError
from app.security import create_token, hash_password, verify_password
from app.services import slot_service

DUMMY_HASH = hash_password("not-a-real-password")  # keeps login timing similar for unknown emails


def user_out(row) -> dict:
    return {"id": row["id"], "name": row["name"], "email": row["email"], "role": row["role"]}


def register_student(body) -> dict:
    email = body.email.strip().lower()
    pw_hash = hash_password(body.password)
    try:
        with db.transaction() as conn:
            u = conn.execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, 'STUDENT') "
                "RETURNING id, name, email, role", (body.name.strip(), email, pw_hash)).fetchone()
            conn.execute(
                "INSERT INTO students (user_id, reg_no, branch, skills) VALUES (%s, %s, %s, %s)",
                (u["id"], body.reg_no.strip(), body.branch.strip(), list(body.skills)))
    except psycopg.errors.UniqueViolation as exc:
        which = "email" if "email" in str(exc) else "registration number"
        raise ApiError("DUPLICATE", f"An account with this {which} already exists")
    return {"token": create_token(u["id"], u["role"]), "user": user_out(u)}


def login(email: str, password: str) -> dict:
    row = db.fetchone("SELECT id, name, email, role, password_hash FROM users WHERE email = %s",
                      (email.strip().lower(),))
    ok = verify_password(password, row["password_hash"] if row else DUMMY_HASH)
    if not row or not ok:
        raise ApiError("UNAUTHORIZED", "Wrong email or password")
    return {"token": create_token(row["id"], row["role"]), "user": user_out(row)}


def profile_for(conn, user: dict) -> dict:
    if user["role"] == "STUDENT":
        s = conn.execute("SELECT reg_no, branch, skills, passed_rounds FROM students WHERE user_id = %s",
                         (user["id"],)).fetchone() or {}
        return {"regNo": s.get("reg_no"), "branch": s.get("branch"), "skills": s.get("skills", []),
                "passedRounds": s.get("passed_rounds", [])}
    if user["role"] == "INTERVIEWER":
        iv = conn.execute(
            "SELECT iv.company_id, c.name AS company_name, iv.skill_tags, iv.is_active "
            "FROM interviewers iv LEFT JOIN companies c ON c.id = iv.company_id WHERE iv.user_id = %s",
            (user["id"],)).fetchone() or {}
        return {"companyId": iv.get("company_id"), "companyName": iv.get("company_name"),
                "skillTags": iv.get("skill_tags", []), "isActive": iv.get("is_active", False),
                "slots": slot_service.interviewer_future_slots(conn, user["id"])}
    return {}


def me(user: dict) -> dict:
    with db.transaction() as conn:
        return {"user": user_out(user), "profile": profile_for(conn, user)}


def update_interviewer_profile(user: dict, company_id: int, skill_tags) -> dict:
    with db.transaction() as conn:
        if not conn.execute("SELECT 1 FROM companies WHERE id = %s", (company_id,)).fetchone():
            raise ApiError("NOT_FOUND", "Company not found")
        conn.execute(
            """INSERT INTO interviewers (user_id, company_id, skill_tags) VALUES (%s, %s, %s)
               ON CONFLICT (user_id) DO UPDATE SET company_id = EXCLUDED.company_id, skill_tags = EXCLUDED.skill_tags""",
            (user["id"], company_id, sorted(set(skill_tags))))
        profile = profile_for(conn, user)
    from app.services import cache
    cache.invalidate_company_slots(company_id)
    return profile
