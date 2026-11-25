from datetime import timedelta
from unittest import mock

from django.db import OperationalError
from django.test import TestCase
from django.utils import timezone

from games.tests import make_numeric_questions
from questions.tests import make_choice_questions
from territories.models import Territory
from territories.services import CAPTURE_REWARD_MULTIPLIER, WIN_REWARD

from battles import tasks
from battles.models import Battle, BattleQuestion
from battles.services import create_battle, start_battle, submit_choice_answer
from battles.tests import make_fully_captured_game


def _expire(step):
    step.deadline = timezone.now() - timedelta(seconds=1)
    step.save(update_fields=['deadline'])


class BattleDeadlineTaskTests(TestCase):
    def setUp(self):
        self.game, self.players = make_fully_captured_game()
        make_choice_questions(3)
        make_numeric_questions(3)
        self.attacker = self.players[0]
        self.target = next(
            t for t in Territory.objects.filter(game=self.game, neighbors__owner=self.attacker)
            .exclude(owner=self.attacker).exclude(capital__isnull=False).distinct()
        )
        self.defender = self.target.owner
        self.battle = create_battle(self.attacker, self.target)

    def _start(self):
        self.battle = start_battle(self.battle)
        return self.battle.battle_questions.get(sequence=1)

    def test_starting_a_battle_queues_a_delayed_task_after_commit(self):
        with mock.patch.object(tasks.close_expired_battle_question, 'apply_async') as apply_async:
            with self.captureOnCommitCallbacks(execute=True):
                step = self._start()
        apply_async.assert_called_once_with(
            args=[step.pk], eta=step.deadline, connection=mock.ANY, retry=False,
        )

    def test_task_before_the_deadline_requeues_itself(self):
        step = self._start()
        with mock.patch.object(tasks.close_expired_battle_question, 'apply_async') as apply_async:
            self.assertEqual(tasks.close_expired_battle_question(step.pk), tasks.NOT_YET)
        apply_async.assert_called_once_with(args=[step.pk], eta=step.deadline)
        step.refresh_from_db()
        self.assertIsNone(step.resolved_at)

    def test_expired_question_completes_the_battle_and_applies_the_result_once(self):
        step = self._start()
        correct = step.choice_question.answer_options.get(is_correct=True)
        submit_choice_answer(step, self.attacker, correct)  # defender never answers
        _expire(step)
        attacker_score = self.attacker.score

        self.assertEqual(tasks.close_expired_battle_questions(), 1)
        self.assertEqual(tasks.close_expired_battle_questions(), 0)
        self.assertEqual(tasks.close_expired_battle_question(step.pk), tasks.NOTHING_TO_DO)

        self.battle.refresh_from_db()
        self.target.refresh_from_db()
        self.attacker.refresh_from_db()
        self.assertEqual(self.battle.status, Battle.COMPLETED)
        self.assertEqual(self.battle.winner, self.attacker)
        self.assertTrue(self.battle.rewards_applied)
        self.assertEqual(self.target.owner, self.attacker)
        expected_gain = WIN_REWARD + self.target.score * CAPTURE_REWARD_MULTIPLIER
        self.assertEqual(self.attacker.score - attacker_score, expected_gain)

        tasks.close_expired_battle_question(step.pk)
        self.attacker.refresh_from_db()
        self.assertEqual(self.attacker.score - attacker_score, expected_gain)

    def _expired_win_for_attacker(self):
        step = self._start()
        submit_choice_answer(step, self.attacker, step.choice_question.answer_options.get(is_correct=True))
        _expire(step)
        return step

    def test_crash_while_applying_the_result_is_fully_retried(self):
        step = self._expired_win_for_attacker()
        with mock.patch('battles.services.apply_battle_result', side_effect=OperationalError('crash')):
            with self.assertRaises(OperationalError):
                tasks.close_expired_battle_question(step.pk)

        self.battle.refresh_from_db()
        step.refresh_from_db()
        self.assertEqual(self.battle.status, Battle.ACTIVE)
        self.assertIsNone(step.resolved_at)

        self.assertEqual(tasks.close_expired_battle_questions(), 1)
        self.battle.refresh_from_db()
        self.target.refresh_from_db()
        self.assertTrue(self.battle.rewards_applied)
        self.assertEqual(self.target.owner, self.attacker)

    def test_refused_result_keeps_the_battle_outcome(self):
        step = self._expired_win_for_attacker()
        self.target.owner = self.attacker  # a concurrent battle took it first
        self.target.save(update_fields=['owner'])

        with self.assertLogs('battles.tasks', level='WARNING'):
            self.assertEqual(tasks.close_expired_battle_question(step.pk), tasks.CLOSED)

        self.battle.refresh_from_db()
        self.attacker.refresh_from_db()
        self.assertEqual(self.battle.status, Battle.COMPLETED)
        self.assertEqual(self.battle.winner, self.attacker)
        self.assertFalse(self.battle.rewards_applied)
        self.assertEqual(self.attacker.score, 0)

    def test_failing_question_is_left_for_the_next_sweep(self):
        step = self._expired_win_for_attacker()
        with mock.patch('battles.services.apply_battle_result', side_effect=TypeError('broken row')):
            with self.assertLogs('battles.tasks', level='ERROR'):
                self.assertEqual(tasks.close_expired_battle_questions(), 0)
        self.assertEqual(tasks.close_expired_battle_questions(), 1)
        self.assertEqual(tasks.close_expired_battle_question(step.pk), tasks.NOTHING_TO_DO)

    def test_expired_question_without_answers_spawns_a_followup(self):
        step = self._start()
        _expire(step)

        self.assertEqual(tasks.close_expired_battle_question(step.pk), tasks.CLOSED)
        self.battle.refresh_from_db()
        self.assertEqual(self.battle.status, Battle.ACTIVE)
        followup = self.battle.battle_questions.get(sequence=2)
        self.assertEqual(followup.question_type, BattleQuestion.CHOICE)
        self.assertIsNone(followup.resolved_at)
        self.assertGreater(followup.deadline, timezone.now())
