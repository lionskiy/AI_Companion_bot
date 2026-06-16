from celery import Celery
from celery.schedules import crontab

from mirror.config import settings

celery_app = Celery(
    "mirror",
    broker=settings.rabbitmq_url,
    backend=None,  # результаты не нужны
    include=[
        "mirror.workers.tasks.memory",
        "mirror.workers.tasks.daily_ritual",
        "mirror.workers.tasks.profile",
        "mirror.workers.tasks.ingest",
        "mirror.workers.tasks.journal",
        "mirror.workers.tasks.proactive",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

celery_app.conf.beat_schedule = {
    "send-daily-rituals": {
        "task": "mirror.workers.tasks.daily_ritual.send_daily_rituals",
        "schedule": crontab(minute=0),
    },
    "cleanup-ingest-logs": {
        "task": "mirror.workers.tasks.ingest.cleanup_ingest_logs",
        "schedule": crontab(hour=3, minute=0),
    },
    "check-evening-reflections": {
        "task": "mirror.workers.tasks.journal.check_evening_reflections",
        "schedule": crontab(minute="*/15"),
    },
    "generate-monthly-synthesis": {
        "task": "mirror.workers.tasks.journal.generate_monthly_synthesis",
        "schedule": crontab(hour=4, minute=0, day_of_month=1),
    },
    "proactive-dispatch": {
        "task": "mirror.workers.tasks.proactive.proactive_dispatch_batch",
        "schedule": crontab(minute="*/30"),
    },
    "decay-fact-importance": {
        "task": "mirror.workers.tasks.memory.decay_fact_importance",
        "schedule": crontab(hour=2, minute=0),
    },
}
