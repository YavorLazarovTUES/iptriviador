import itertools
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from games.models import Game, Round, RoundAnswer, RoundQuestion
from games.services import (
    InvalidInputError,
    InvalidStateError,
    create_round,
    resolve_round,
    start_round,
    submit_answer,
)
from games.tests import make_game_with_players, make_numeric_questions


def now_sequence(base, *offsets_seconds):
    """A `timezone.now` side_effect: the given offsets in order, then repeats the last."""
    times = [base + timedelta(seconds=offset) for offset in offsets_seconds] or [base]
    return itertools.chain(times, itertools.repeat(times[-1]))


class RoundWorkflowTests(TestCase):
    def setUp(self):
        self.game, self.players = make_game_with_players(3, status=Game.ACTIVE)
        self.questions = make_numeric_questions(1, start_answer=10)

    def test_create_start_and_complete_with_correct_number_and_winner(self):
        round_ = create_round(self.game, Round.CITY_CAPTURE, number=1, required_places=1)
        self.assertEqual(round_.status, Round.PENDING)
        self.assertEqual(round_.round_questions.count(), 1)

        round_ = start_round(round_)
        self.assertEqual(round_.status, Round.ACTIVE)
        rq = round_.round_questions.get(sequence=1)
        self.assertIsNotNone(rq.started_at)
        self.assertEqual(rq.deadline, rq.started_at + timedelta(seconds=Round.ANSWER_WINDOW_SECONDS))

        base = rq.started_at
        with mock.patch('games.services.timezone.now') as mock_now:
            mock_now.side_effect = now_sequence(base, 1, 2, 3)
            submit_answer(rq, self.players[0], 10)  # exact match, dev 0
            submit_answer(rq, self.players[1], 12)
            round_ = submit_answer(rq, self.players[2], 15).round_question.round

        round_.refresh_from_db()
        self.assertEqual(round_.number, 1)
        self.assertEqual(round_.status, Round.COMPLETED)
        self.assertEqual(round_.winner, self.players[0])
        self.assertIsNotNone(round_.completed_at)

    def test_closeness_decides_before_speed(self):
        round_ = start_round(create_round(self.game, Round.CITY_CAPTURE, 1, required_places=1))
        rq = round_.round_questions.get(sequence=1)
        base = rq.started_at
        with mock.patch('games.services.timezone.now') as mock_now:
            mock_now.side_effect = now_sequence(base, 1, 9, 9)
            submit_answer(rq, self.players[0], 11)  # dev 1, fast
            submit_answer(rq, self.players[1], 10)  # dev 0, slow -> still wins
            submit_answer(rq, self.players[2], 1)  # dev 9, worse
        round_.refresh_from_db()
        self.assertEqual(round_.winner, self.players[1])

    def test_equal_closeness_is_broken_by_speed(self):
        round_ = start_round(create_round(self.game, Round.CITY_CAPTURE, 1, required_places=1))
        rq = round_.round_questions.get(sequence=1)
        base = rq.started_at
        with mock.patch('games.services.timezone.now') as mock_now:
            mock_now.side_effect = now_sequence(base, 1, 3, 2)
            submit_answer(rq, self.players[0], 8)  # dev 2, elapsed 1s
            submit_answer(rq, self.players[1], 12)  # dev 2, elapsed 3s
            submit_answer(rq, self.players[2], 1)  # dev 9, elapsed 2s
        round_.refresh_from_db()
        self.assertEqual(round_.winner, self.players[0])

    def test_single_answer_wins_outright_without_a_fictitious_second(self):
        round_ = start_round(create_round(self.game, Round.CITY_CAPTURE, 1, required_places=1))
        rq = round_.round_questions.get(sequence=1)
        RoundAnswer.objects.create(
            round_question=rq, player=self.players[0], value=10, answered_at=rq.started_at + timedelta(seconds=1)
        )
        rq.deadline = timezone.now() - timedelta(seconds=1)
        rq.save(update_fields=['deadline'])

        round_ = resolve_round(round_)
        self.assertEqual(round_.winner, self.players[0])
        self.assertIsNone(round_.second_place)
        self.assertEqual(round_.status, Round.COMPLETED)
        self.assertEqual(round_.incomplete_reason, '')


class RoundAnswerDenialTests(TestCase):
    def setUp(self):
        self.game, self.players = make_game_with_players(3, status=Game.ACTIVE)
        self.questions = make_numeric_questions(1, start_answer=10)
        self.round_ = create_round(self.game, Round.CITY_CAPTURE, 1, required_places=1)

    def test_cannot_answer_before_round_is_started(self):
        rq = self.round_.round_questions.get(sequence=1)
        with self.assertRaises(InvalidStateError):
            submit_answer(rq, self.players[0], 10)

    def test_foreign_player_cannot_answer(self):
        other_game, other_players = make_game_with_players(3, status=Game.ACTIVE)
        round_ = start_round(self.round_)
        rq = round_.round_questions.get(sequence=1)
        with self.assertRaises(InvalidStateError):
            submit_answer(rq, other_players[0], 10)

    def test_cannot_answer_twice(self):
        round_ = start_round(self.round_)
        rq = round_.round_questions.get(sequence=1)
        submit_answer(rq, self.players[0], 10)
        with self.assertRaises(InvalidStateError):
            submit_answer(rq, self.players[0], 11)

    def test_non_integer_answer_is_rejected_without_truncation(self):
        round_ = start_round(self.round_)
        rq = round_.round_questions.get(sequence=1)
        with self.assertRaises(InvalidInputError):
            submit_answer(rq, self.players[0], '3.5')
        with self.assertRaises(InvalidInputError):
            submit_answer(rq, self.players[0], 3.5)
        self.assertEqual(RoundAnswer.objects.filter(round_question=rq).count(), 0)

    def test_whole_number_float_is_accepted(self):
        round_ = start_round(self.round_)
        rq = round_.round_questions.get(sequence=1)
        answer = submit_answer(rq, self.players[0], 10.0)
        self.assertEqual(answer.value, 10)


class RoundDeadlineTests(TestCase):
    def setUp(self):
        self.game, self.players = make_game_with_players(3, status=Game.ACTIVE)
        self.questions = make_numeric_questions(1, start_answer=10)
        self.round_ = start_round(create_round(self.game, Round.CITY_CAPTURE, 1, required_places=1))
        self.rq = self.round_.round_questions.get(sequence=1)

    def test_answer_accepted_before_deadline(self):
        with mock.patch('games.services.timezone.now') as mock_now:
            mock_now.return_value = self.rq.deadline - timedelta(seconds=1)
            submit_answer(self.rq, self.players[0], 10)
        self.assertEqual(RoundAnswer.objects.filter(round_question=self.rq).count(), 1)

    def test_answer_rejected_exactly_at_deadline(self):
        with mock.patch('games.services.timezone.now') as mock_now:
            mock_now.return_value = self.rq.deadline
            with self.assertRaises(InvalidStateError):
                submit_answer(self.rq, self.players[0], 10)

    def test_answer_rejected_after_deadline(self):
        with mock.patch('games.services.timezone.now') as mock_now:
            mock_now.return_value = self.rq.deadline + timedelta(seconds=1)
            with self.assertRaises(InvalidStateError):
                submit_answer(self.rq, self.players[0], 10)


class ResolveRoundDenialTests(TestCase):
    def setUp(self):
        self.game, self.players = make_game_with_players(3, status=Game.ACTIVE)
        self.questions = make_numeric_questions(1, start_answer=10)
        self.round_ = start_round(create_round(self.game, Round.CITY_CAPTURE, 1, required_places=1))

    def test_premature_resolve_is_rejected(self):
        with self.assertRaises(InvalidStateError):
            resolve_round(self.round_)

    def test_resolving_a_completed_round_again_is_rejected(self):
        rq = self.round_.round_questions.get(sequence=1)
        RoundAnswer.objects.create(
            round_question=rq, player=self.players[0], value=10, answered_at=rq.started_at + timedelta(seconds=1)
        )
        rq.deadline = timezone.now() - timedelta(seconds=1)
        rq.save(update_fields=['deadline'])
        resolve_round(self.round_)
        with self.assertRaises(InvalidStateError):
            resolve_round(self.round_)


def _answer(rq, player, value, offset_seconds):
    return RoundAnswer.objects.create(
        round_question=rq, player=player, value=value, answered_at=rq.started_at + timedelta(seconds=offset_seconds)
    )


def _expire(rq):
    rq.deadline = timezone.now() - timedelta(seconds=1)
    rq.save(update_fields=['deadline'])


class RoundCompletionEdgeCaseTests(TestCase):
    def setUp(self):
        self.game, self.players = make_game_with_players(3, status=Game.ACTIVE)

    def test_full_tie_spawns_a_question_for_only_the_tied_group(self):
        make_numeric_questions(2, start_answer=10)
        round_ = start_round(create_round(self.game, Round.CITY_CAPTURE, 1, required_places=1))
        rq = round_.round_questions.get(sequence=1)
        correct = rq.correct_answer
        _answer(rq, self.players[0], correct - 2, 1)  # dev 2, elapsed 1s
        _answer(rq, self.players[1], correct + 2, 1)  # dev 2, elapsed 1s - exact tie with player 0
        _answer(rq, self.players[2], correct - 9, 5)  # dev 9, worse
        _expire(rq)

        round_ = resolve_round(round_)
        self.assertEqual(round_.status, Round.ACTIVE)
        self.assertIsNone(round_.winner)
        self.assertEqual(round_.round_questions.count(), 2)
        followup = round_.round_questions.get(sequence=2)
        self.assertEqual(followup.target_rank, RoundQuestion.FIRST_PLACE)
        self.assertEqual(set(followup.contenders.all()), {self.players[0], self.players[1]})

    def test_no_answers_spawns_a_question_for_the_same_group(self):
        make_numeric_questions(2, start_answer=10)
        round_ = start_round(create_round(self.game, Round.CITY_CAPTURE, 1, required_places=1))
        rq = round_.round_questions.get(sequence=1)
        _expire(rq)

        round_ = resolve_round(round_)
        self.assertEqual(round_.status, Round.ACTIVE)
        self.assertEqual(round_.round_questions.count(), 2)
        followup = round_.round_questions.get(sequence=2)
        self.assertEqual(set(followup.contenders.all()), set(self.players))

    def test_question_limit_reached_leaves_winner_empty_with_reason(self):
        make_numeric_questions(3, start_answer=10)
        round_ = start_round(create_round(self.game, Round.CITY_CAPTURE, 1, required_places=1))

        for _ in range(3):
            rq = round_.round_questions.order_by('-sequence').first()
            _expire(rq)
            round_ = resolve_round(round_)

        self.assertEqual(round_.round_questions.count(), 3)
        self.assertEqual(round_.status, Round.COMPLETED)
        self.assertIsNone(round_.winner)
        self.assertEqual(round_.incomplete_reason, Round.QUESTION_LIMIT_REACHED)
        self.assertIsNotNone(round_.completed_at)

    def test_bank_exhausted_leaves_winner_empty_with_reason(self):
        make_numeric_questions(1, start_answer=10)
        round_ = start_round(create_round(self.game, Round.CITY_CAPTURE, 1, required_places=1))
        rq = round_.round_questions.get(sequence=1)
        _expire(rq)

        round_ = resolve_round(round_)
        self.assertEqual(round_.round_questions.count(), 1)
        self.assertEqual(round_.status, Round.COMPLETED)
        self.assertIsNone(round_.winner)
        self.assertEqual(round_.incomplete_reason, Round.BANK_EXHAUSTED)

    def test_second_place_resolved_directly_from_first_question_without_extra_question(self):
        make_numeric_questions(1, start_answer=10)
        round_ = start_round(create_round(self.game, Round.CITY_CAPTURE, 1, required_places=2))
        rq = round_.round_questions.get(sequence=1)
        _answer(rq, self.players[0], 10, 1)  # dev 0 -> first
        _answer(rq, self.players[1], 12, 1)  # dev 2 -> second
        _answer(rq, self.players[2], 20, 1)  # dev 10
        _expire(rq)

        round_ = resolve_round(round_)
        self.assertEqual(round_.round_questions.count(), 1)
        self.assertEqual(round_.winner, self.players[0])
        self.assertEqual(round_.second_place, self.players[1])
        self.assertEqual(round_.status, Round.COMPLETED)

    def test_tied_second_place_spawns_a_rank_two_question_for_the_tied_pair(self):
        make_numeric_questions(2, start_answer=10)
        round_ = start_round(create_round(self.game, Round.CITY_CAPTURE, 1, required_places=2))
        rq = round_.round_questions.get(sequence=1)
        correct = rq.correct_answer
        _answer(rq, self.players[0], correct, 1)  # dev 0 -> first, no tie
        _answer(rq, self.players[1], correct - 2, 2)  # dev 2, elapsed 2s
        _answer(rq, self.players[2], correct + 2, 2)  # dev 2, elapsed 2s - tied with player 1
        _expire(rq)

        round_ = resolve_round(round_)
        self.assertEqual(round_.winner, self.players[0])
        self.assertIsNone(round_.second_place)
        self.assertEqual(round_.status, Round.ACTIVE)
        followup = round_.round_questions.get(sequence=2)
        self.assertEqual(followup.target_rank, RoundQuestion.SECOND_PLACE)
        self.assertEqual(set(followup.contenders.all()), {self.players[1], self.players[2]})

    def test_second_place_bank_exhausted_does_not_cancel_the_win(self):
        make_numeric_questions(1, start_answer=10)
        round_ = start_round(create_round(self.game, Round.CITY_CAPTURE, 1, required_places=2))
        rq = round_.round_questions.get(sequence=1)
        _answer(rq, self.players[0], 10, 1)  # dev 0 -> first
        _answer(rq, self.players[1], 8, 2)  # dev 2 elapsed 2s - tied with player 2 below
        _answer(rq, self.players[2], 12, 2)  # dev 2 elapsed 2s
        _expire(rq)

        round_ = resolve_round(round_)
        self.assertEqual(round_.winner, self.players[0])
        self.assertIsNone(round_.second_place)
        self.assertEqual(round_.status, Round.COMPLETED)
        self.assertEqual(round_.incomplete_reason, Round.BANK_EXHAUSTED)

    def test_win_resolved_on_the_third_question(self):
        make_numeric_questions(3, start_answer=10)
        round_ = start_round(create_round(self.game, Round.CITY_CAPTURE, 1, required_places=1))

        rq1 = round_.round_questions.get(sequence=1)
        correct1 = rq1.correct_answer
        _answer(rq1, self.players[0], correct1 - 2, 1)
        _answer(rq1, self.players[1], correct1 + 2, 1)  # exact tie with player 0
        _expire(rq1)
        round_ = resolve_round(round_)

        rq2 = round_.round_questions.get(sequence=2)
        _expire(rq2)  # no answers this time, same tied group asked again
        round_ = resolve_round(round_)

        rq3 = round_.round_questions.get(sequence=3)
        _answer(rq3, self.players[0], rq3.correct_answer - 1, 1)
        _expire(rq3)
        round_ = resolve_round(round_)

        self.assertEqual(round_.round_questions.count(), 3)
        self.assertEqual(round_.winner, self.players[0])
        self.assertEqual(round_.status, Round.COMPLETED)
        self.assertEqual(round_.incomplete_reason, '')


class RoundDataPersistenceTests(TestCase):
    def setUp(self):
        self.game, self.players = make_game_with_players(3, status=Game.ACTIVE)
        self.questions = make_numeric_questions(1, start_answer=42)

    def test_reload_restores_question_deadline_and_ranking(self):
        round_ = start_round(create_round(self.game, Round.CITY_CAPTURE, 1, required_places=1))
        rq = round_.round_questions.get(sequence=1)
        base = rq.started_at
        with mock.patch('games.services.timezone.now') as mock_now:
            mock_now.side_effect = now_sequence(base, 1, 5, 5)
            answer = submit_answer(rq, self.players[0], 42)
            submit_answer(rq, self.players[1], 50)
            submit_answer(rq, self.players[2], 60)

        question = self.questions[0]
        question.correct_answer = 999
        question.text = 'edited after the fact'
        question.save()

        reloaded_rq = RoundQuestion.objects.get(pk=rq.pk)
        self.assertEqual(reloaded_rq.correct_answer, 42)
        self.assertNotEqual(reloaded_rq.question_text, question.text)
        self.assertEqual(reloaded_rq.deadline, rq.deadline)

        reloaded_answer = RoundAnswer.objects.get(pk=answer.pk)
        self.assertEqual(reloaded_answer.value, 42)

        round_.refresh_from_db()
        self.assertEqual(round_.winner, self.players[0])
