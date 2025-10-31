from __future__ import annotations

from celery import Celery

from app.core.settings import get_settings

celery_app = Celery("aie_dxproject")


def configure_celery_app() -> None:
    settings = get_settings()
    celery_app.conf.update(
        broker_url=settings.celery.broker_url,
        result_backend=settings.celery.result_backend,
        task_default_queue=settings.celery.task_default_queue,
        task_always_eager=settings.celery.task_always_eager,
        task_eager_propagates=settings.celery.task_eager_propagates,
        task_default_retry_delay=settings.celery.task_default_retry_delay,
        task_max_retries=settings.celery.task_max_retries,
    )


configure_celery_app()
celery_app.autodiscover_tasks(["app.workers"])
