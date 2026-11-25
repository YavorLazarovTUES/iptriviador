"""Close every round question whose deadline has passed (M09).

    python manage.py close_expired_rounds
    python manage.py close_expired_rounds --loop --interval 5

The command only decides *when* the consequences of a passed deadline are
processed. The rules themselves stay in the M06/M07 services.
"""
import argparse
import logging
import time

from django.core.management.base import BaseCommand

from games.services import expired_open_questions
from games.tasks import CLOSED, close_round_question_if_expired

logger = logging.getLogger(__name__)


def positive_int(value):
    try:
        number = int(value)
    except ValueError:
        number = 0
    if number <= 0:
        raise argparse.ArgumentTypeError('must be a positive whole number of seconds')
    return number


class Command(BaseCommand):
    help = 'Closes all active round questions whose deadline has passed.'

    def add_arguments(self, parser):
        parser.add_argument('--loop', action='store_true', help='Repeat the check until stopped with Ctrl+C.')
        parser.add_argument(
            '--interval', type=positive_int, default=5, help='Seconds between two checks with --loop (default: 5).',
        )

    def handle(self, *args, **options):
        if not options['loop']:
            self.run_once()
            return

        interval = options['interval']
        self.stdout.write(f'Checking every {interval} s. Press Ctrl+C to stop.')
        try:
            while True:
                self.run_once()
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write('Stopped.')

    def run_once(self):
        processed = skipped = failed = 0
        for pk in list(expired_open_questions().values_list('pk', flat=True)):
            # Calls the existing M06 resolve_round (through M07's wrapper for
            # a city capture round, so its rewards are applied as well).
            # One broken question must not stop the others, or the loop.
            try:
                outcome = close_round_question_if_expired(pk)
            except Exception:
                logger.exception('Could not close expired round question %s.', pk)
                failed += 1
                continue
            if outcome == CLOSED:
                processed += 1
            else:
                skipped += 1
        summary = f'Processed: {processed}, skipped: {skipped}'
        if failed:
            summary += f', failed: {failed}'
        self.stdout.write(summary)
