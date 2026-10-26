"""Celery app: Redis broker, retries/backoff, beat schedule.
Run:  celery -A workers.celery_app worker -B --loglevel=info"""
from celery import Celery

from app.config import settings

celery = Celery("trials", broker=settings.redis_url, backend=settings.redis_url, include=["workers.tasks"])
celery.conf.update(
    task_always_eager=settings.celery_eager,
    task_eager_propagates=True,         # CELERY_EAGER=true: run inline, no worker needed (demo)
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=5,
    broker_connection_retry_on_startup=True,
    result_expires=3600,
    timezone="UTC",
    beat_schedule={
        "deliver-outbox":     {"task": "workers.tasks.deliver_outbox_task",       "schedule": 10.0},
        "send-reminders":     {"task": "workers.tasks.send_reminders_task",       "schedule": 60.0},
        "release-results":    {"task": "workers.tasks.release_results_task",      "schedule": 30.0},
        "auto-match-deadline": {"task": "workers.tasks.auto_match_at_deadline_task", "schedule": 60.0},
    },
)
