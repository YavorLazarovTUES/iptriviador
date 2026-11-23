"""Celery application for background and periodic work (M09).

The web process never waits for a deadline: it records `deadline` in the
database and hands "close this question once its window is over" to a
worker through the broker. Run the pieces with (from `backend/`):

    celery -A config worker --loglevel=info        # add --pool=solo on Windows
    celery -A config beat --loglevel=info          # the periodic sweep

The broker defaults to a local Redis (`CELERY_BROKER_URL` overrides it).
"""
import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
