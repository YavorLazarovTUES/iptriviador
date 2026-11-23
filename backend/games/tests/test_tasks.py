from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from games import tasks
from games.models import Game, Round
from games.services import InvalidStateError, create_round, start_round, submit_answer
from games.tests import make_game_with_players, make_numeric_questions
from territories.models import CaptureRight
from territories.services import (
    WIN_REWARD,
    create_city_capture_round,
    start_city_capture_round,
    submit_city_capture_answer,
)
from territories.tests import make_initialized_game


def _expire(rq):
    rq.deadline = timezone.now() - timedelta(seconds=1)
    rq.save(update_fields=['deadline'])


class DeadlineSchedulingTests(TestCase):
    def setUp(self):
        self.game, self.players = make_game_with_players(3, status=Game.ACTIVE)
        make_numeric_questions(3, start_answer=10)

    def test_starting_a_round_queues_a_delayed_task_at_the_deadline_after_commit(self):
        round_ = create_round(self.game, Round.CITY_CAPTURE, 1, required_places=1)
        with mock.patch.object(tasks.close_expired_round_question, 'apply_async') as apply_async:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                round_ = start_round(round_)
            apply_async.assert_not_called()  # nothing is queued before the commit
            for callback in callbacks:
                callback()

        rq = round_.round_questions.get(sequence=1)
        apply_async.assert_called_once_with(args=[rq.pk], eta=rq.deadline)

    def test_a_tie_break_question_gets_its_own_delayed_task(self):
        round_ = start_round(create_round(self.game, Round.BONUS, 1, required_places=1))
        rq = round_.round_questions.get(sequence=1)
        _expire(rq)
        with mock.patch.object(tasks.close_expired_round_question, 'apply_async') as apply_async:
            with self.captureOnCommitCallbacks(execute=True):
                tasks.close_expired_round_questions()  # nobody answered -> follow-up

        followup = round_.round_questions.get(sequence=2)
        apply_async.assert_called_once_with(args=[followup.pk], eta=followup.deadline)

    def test_broker_outage_does_not_fail_the_request(self):
        round_ = create_round(self.game, Round.CITY_CAPTURE, 1, required_places=1)
        with mock.patch.object(
            tasks.close_expired_round_question, 'apply_async', side_effect=ConnectionError('broker down'),
        ):
            with self.assertLogs(level='ERROR'):
                with self.captureOnCommitCallbacks(execute=True):
                    round_ = start_round(round_)
        self.assertEqual(round_.status, Round.ACTIVE)


class CloseRoundQuestionTests(TestCase):
    def setUp(self):
        self.game, self.players = make_game_with_players(3, status=Game.ACTIVE)
        make_numeric_questions(3, start_answer=10)
        self.round = start_round(create_round(self.game, Round.BONUS, 1, required_places=1))
        self.rq = self.round.round_questions.get(sequence=1)

    def test_task_before_the_deadline_does_nothing_and_requeues_itself(self):
        with mock.patch.object(tasks.close_expired_round_question, 'apply_async') as apply_async:
            outcome = tasks.close_expired_round_question(self.rq.pk)

        self.assertEqual(outcome, tasks.NOT_YET)
        apply_async.assert_called_once_with(args=[self.rq.pk], eta=self.rq.deadline)
        self.rq.refresh_from_db()
        self.assertIsNone(self.rq.resolved_at)

    def test_task_after_the_deadline_resolves_the_question(self):
        submit_answer(self.rq, self.players[0], self.rq.correct_answer)
        _expire(self.rq)

        self.assertEqual(tasks.close_expired_round_question(self.rq.pk), tasks.CLOSED)
        self.round.refresh_from_db()
        self.assertEqual(self.round.status, Round.COMPLETED)
        self.assertEqual(self.round.winner, self.players[0])

    def test_repeated_delivery_is_a_no_op(self):
        submit_answer(self.rq, self.players[0], self.rq.correct_answer)
        _expire(self.rq)
        tasks.close_expired_round_question(self.rq.pk)
        self.round.refresh_from_db()
        completed_at = self.round.completed_at

        self.assertEqual(tasks.close_expired_round_question(self.rq.pk), tasks.NOTHING_TO_DO)
        self.round.refresh_from_db()
        self.assertEqual(self.round.completed_at, completed_at)
        self.assertEqual(self.round.round_questions.count(), 1)

    def test_missing_question_is_a_no_op(self):
        self.assertEqual(tasks.close_expired_round_question(999999), tasks.NOTHING_TO_DO)

    def test_deadline_is_enforced_even_before_any_worker_ran(self):
        _expire(self.rq)
        with self.assertRaises(InvalidStateError):
            submit_answer(self.rq, self.players[0], 10)


class PeriodicSweepTests(TestCase):
    def test_sweep_only_touches_expired_open_questions(self):
        game, players = make_game_with_players(3, status=Game.ACTIVE)
        other_game, _ = make_game_with_players(3, status=Game.ACTIVE)
        make_numeric_questions(4, start_answer=10)
        expired_round = start_round(create_round(game, Round.BONUS, 1, required_places=1))
        running_round = start_round(create_round(other_game, Round.BONUS, 1, required_places=1))
        expired_rq = expired_round.round_questions.get(sequence=1)
        submit_answer(expired_rq, players[1], 10)
        _expire(expired_rq)

        self.assertEqual(tasks.close_expired_round_questions(), 1)

        expired_round.refresh_from_db()
        running_round.refresh_from_db()
        self.assertEqual(expired_round.status, Round.COMPLETED)
        self.assertEqual(expired_round.winner, players[1])
        self.assertEqual(running_round.status, Round.ACTIVE)
        self.assertIsNone(running_round.round_questions.get(sequence=1).resolved_at)
        self.assertEqual(tasks.close_expired_round_questions(), 0)

    def test_city_capture_rewards_are_applied_exactly_once(self):
        game, (p1, p2, p3) = make_initialized_game()
        make_numeric_questions(2, start_answer=10)
        round_ = start_city_capture_round(create_city_capture_round(game, 1))
        rq = round_.round_questions.get(sequence=1)
        submit_city_capture_answer(rq, p1, rq.correct_answer)
        submit_city_capture_answer(rq, p2, rq.correct_answer + 3)
        _expire(rq)  # p3 never answers

        tasks.close_expired_round_questions()
        tasks.close_expired_round_questions()
        tasks.close_expired_round_question(rq.pk)

        round_.refresh_from_db()
        p1.refresh_from_db()
        self.assertEqual(round_.status, Round.COMPLETED)
        self.assertTrue(round_.rewards_applied)
        self.assertEqual((round_.winner, round_.second_place), (p1, p2))
        self.assertEqual(p1.score, WIN_REWARD)
        self.assertEqual(CaptureRight.objects.filter(round=round_).count(), 2)
