from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from games import services
from games.management.commands import close_expired_rounds
from games.models import Round
from games.services import InvalidStateError, expired_open_questions
from games.tasks import NOTHING_TO_DO
from games.tests import make_numeric_questions
from territories.models import CaptureRight
from territories.services import (
    WIN_REWARD,
    create_city_capture_round,
    start_city_capture_round,
    submit_city_capture_answer,
)
from territories.tests import make_initialized_game


def _run(*args):
    out = StringIO()
    call_command('close_expired_rounds', *args, stdout=out)
    return out.getvalue()


class CloseExpiredRoundsTests(TestCase):
    def setUp(self):
        self.game, self.players = make_initialized_game()
        make_numeric_questions(4, start_answer=10)
        self.round = start_city_capture_round(create_city_capture_round(self.game, 1))
        self.rq = self.round.round_questions.get(sequence=1)

    def _answer(self, *players):
        for offset, player in enumerate(players):
            submit_city_capture_answer(self.rq, player, self.rq.correct_answer + offset)

    def _expire(self, **ago):
        self.rq.deadline = timezone.now() - timedelta(**(ago or {'seconds': 1}))
        self.rq.save(update_fields=['deadline'])

    def test_running_question_is_left_alone(self):
        self.assertIn('Processed: 0, skipped: 0', _run())
        self.rq.refresh_from_db()
        self.assertIsNone(self.rq.resolved_at)

    def test_question_missed_long_ago_is_still_closed_and_rewarded_once(self):
        self._answer(*self.players[:2])
        self._expire(days=2)

        self.assertIn('Processed: 1, skipped: 0', _run())
        self.assertIn('Processed: 0, skipped: 0', _run())

        self.round.refresh_from_db()
        self.players[0].refresh_from_db()
        self.assertEqual(self.round.status, Round.COMPLETED)
        self.assertEqual(self.players[0].score, WIN_REWARD)
        self.assertEqual(CaptureRight.objects.filter(round=self.round).count(), 2)

    def test_no_answers_spawns_exactly_one_followup(self):
        self._expire()
        _run()
        _run()
        self.assertEqual(self.round.round_questions.count(), 2)

    def test_question_resolved_by_all_answers_before_the_deadline_is_ignored(self):
        self._answer(*self.players)
        self._expire()
        self.assertFalse(expired_open_questions().exists())
        self.assertIn('Processed: 0, skipped: 0', _run())

    def test_question_closed_by_someone_else_is_counted_as_skipped(self):
        self._expire()
        with mock.patch.object(
            close_expired_rounds, 'close_round_question_if_expired', return_value=NOTHING_TO_DO,
        ):
            self.assertIn('Processed: 0, skipped: 1', _run())

    def test_failing_question_is_reported_and_does_not_stop_the_command(self):
        self._expire()
        with mock.patch.object(
            close_expired_rounds, 'close_round_question_if_expired', side_effect=TypeError('broken row'),
        ):
            with self.assertLogs('games.management.commands.close_expired_rounds', level='ERROR'):
                self.assertIn('Processed: 0, skipped: 0, failed: 1', _run())

    def test_stale_resolve_changes_nothing(self):
        """Both processes read the question as open; only the first may close it."""
        self._answer(*self.players[:2])
        self._expire()
        stale_round = Round.objects.get(pk=self.round.pk)
        stale_question = services.RoundQuestion.objects.get(pk=self.rq.pk)
        _run()
        self.rq.refresh_from_db()
        resolved_at = self.rq.resolved_at

        with self.assertRaises(InvalidStateError):
            services._resolve_question(stale_round, stale_question)

        self.rq.refresh_from_db()
        self.players[0].refresh_from_db()
        self.assertEqual(self.rq.resolved_at, resolved_at)
        self.assertEqual(self.round.round_questions.count(), 1)
        self.assertEqual(self.players[0].score, WIN_REWARD)

    def test_late_answer_is_rejected_while_the_question_is_still_open(self):
        self._expire()
        with self.assertRaises(InvalidStateError):
            submit_city_capture_answer(self.rq, self.players[0], 10)
        self.rq.refresh_from_db()
        self.assertIsNone(self.rq.resolved_at)
        self.assertFalse(self.rq.answers.exists())

    def test_loop_repeats_and_stops_cleanly_on_ctrl_c(self):
        with mock.patch.object(close_expired_rounds.time, 'sleep', side_effect=[None, KeyboardInterrupt]) as sleep:
            output = _run('--loop', '--interval', '7')
        sleep.assert_called_with(7)
        self.assertEqual(output.count('Processed:'), 2)
        self.assertIn('Stopped.', output)

    def test_interval_must_be_positive(self):
        with self.assertRaises(CommandError):
            _run('--loop', '--interval', '0')
