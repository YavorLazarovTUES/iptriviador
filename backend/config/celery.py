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

# Limits for queueing a task from inside a request. With the defaults an
# unreachable broker holds the request for 4+ seconds (OS connect timeouts,
# then kombu's own retries) - out of a 10 second answer window. The worker and
# beat do not use these, so they keep waiting patiently for a broker restart.
QUICK_PUBLISH_OPTIONS = {
    'socket_connect_timeout': 0.5,
    'socket_timeout': 1,
    'max_retries': 0,
}


def publish_quickly(task, **options):
    """Queue `task` with one short attempt; raises if the broker is down.

    A connection of its own, because pooled connections are shared with
    callers that want the default, longer limits.
    """
    with app.connection_for_write(transport_options=QUICK_PUBLISH_OPTIONS) as connection:
        return task.apply_async(connection=connection, retry=False, **options)
