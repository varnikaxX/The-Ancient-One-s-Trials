"""Environment-driven settings. Every value has a dev-friendly default."""
import os
import sys
from pathlib import Path

# The scheduler package lives next to backend/ at the repo root: make it importable.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _bool(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")

def _load_dotenv():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

_load_dotenv()

class Settings:
    def __init__(self):
        e = os.environ.get
        self.database_url = e("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/trials")
        self.db_pool_min = int(e("DB_POOL_MIN", "2"))
        self.db_pool_max = int(e("DB_POOL_MAX", "30"))
        self.redis_url = e("REDIS_URL", "redis://localhost:6379/0")
        self.jwt_secret = e("JWT_SECRET", "dev-only-change-me-please-0123456789")
        self.jwt_expiry_minutes = int(e("JWT_EXPIRY_MINUTES", "720"))
        self.slot_minutes = int(e("SLOT_MINUTES", "30"))          # contract constant SLOT_MINUTES=30
        self.cache_ttl_seconds = int(e("CACHE_TTL_SECONDS", "60"))
        self.cors_origins = [o.strip() for o in e("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
        # solver wiring (see master prompt section 6)
        self.use_stub_solver = _bool("USE_STUB_SOLVER", "true")
        self.solver_time_limit = int(e("SOLVER_TIME_LIMIT", "20"))
        self.reschedule_time_limit = int(e("RESCHEDULE_TIME_LIMIT", "10"))
        # email
        self.email_from = e("EMAIL_FROM", "trials@example.com")
        self.resend_api_key = e("RESEND_API_KEY", "")
        self.sendgrid_api_key = e("SENDGRID_API_KEY", "")
        self.smtp_host = e("SMTP_HOST", "")                      # optional: e.g. smtp.gmail.com (local dev)
        self.smtp_port = int(e("SMTP_PORT", "587"))
        self.smtp_user = e("SMTP_USER", "")
        self.smtp_password = e("SMTP_PASSWORD", "").replace(" ", "")
        self.email_dry_run = _bool("EMAIL_DRY_RUN", "true")        # no keys -> just log
        self.public_base_url = e("PUBLIC_BASE_URL", "http://localhost:5173")
        # outbox / celery
        self.outbox_max_attempts = int(e("OUTBOX_MAX_ATTEMPTS", "5"))
        self.outbox_batch = int(e("OUTBOX_BATCH", "50"))
        self.celery_eager = _bool("CELERY_EAGER", "false")         # run tasks inline (demo without worker)
        self.reminder_hours = [24, 1]


settings = Settings()
