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
        "schedule": crontab(minute=0),  # каждый час
    },
    "cleanup-ingest-logs": {
        "task": "mirror.workers.tasks.ingest.cleanup_ingest_logs",
        "schedule": crontab(hour=3, minute=0),  # ежедневно в 03:00 UTC
    },
}
