from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from games.services import InvalidStateError
from games.tests import make_numeric_questions
from questions.models import Category
from questions.tests import make_choice_questions

from battles.models import Battle, BattleAnswer, BattleQuestion
from battles.services import create_battle, resolve_battle, start_battle, submit_choice_answer
from battles.tests import make_fully_captured_game, owned_neighbor_of


def _expire(step):
    step.deadline = timezone.now() - timedelta(seconds=1)
    step.save(update_fields=['deadline'])


def _answer_choice(step, player, option, offset_seconds=1):
    return BattleAnswer.objects.create(
        battle_question=step, player=player, selected_option=option,
        answered_at=step.started_at + timedelta(seconds=offset_seconds),
    )


def _answer_numeric(step, player, value, offset_seconds=1):
    return BattleAnswer.objects.create(
        battle_question=step, player=player, value=value,
        answered_at=step.started_at + timedelta(seconds=offset_seconds),
    )


class ChoiceQuestionResolutionTests(TestCase):
    def setUp(self):
        self.game, self.players = make_fully_captured_game()
        self.category = Category.objects.create(name='Cat')
        make_choice_questions(3)
        make_numeric_questions(3)
        self.attacker = self.players[0]
        self.target = owned_neighbor_of(self.attacker)
        self.defender = self.target.owner
        self.battle = start_battle(create_battle(self.attacker, self.target))
        self.step1 = self.battle.battle_questions.get(sequence=1)

    def test_one_correct_answer_wins_outright(self):
        correct_option = self.step1.choice_question.answer_options.get(is_correct=True)
        wrong_option = self.step1.choice_question.answer_options.filter(is_correct=False).first()
        submit_choice_answer(self.step1, self.attacker, correct_option)
        battle = submit_choice_answer(self.step1, self.defender, wrong_option).battle_question.battle

        battle.refresh_from_db()
        self.assertEqual(battle.status, Battle.COMPLETED)
        self.assertEqual(battle.winner, self.attacker)
        self.assertEqual(battle.battle_questions.count(), 1)

    def test_two_correct_answers_spawn_a_numeric_question(self):
        correct_option = self.step1.choice_question.answer_options.get(is_correct=True)
        submit_choice_answer(self.step1, self.attacker, correct_option)
        battle = submit_choice_answer(self.step1, self.defender, correct_option).battle_question.battle

        battle.refresh_from_db()
        self.assertEqual(battle.status, Battle.ACTIVE)
        self.assertIsNone(battle.winner)
        self.assertEqual(battle.battle_questions.count(), 2)
        followup = battle.battle_questions.get(sequence=2)
        self.assertEqual(followup.question_type, BattleQuestion.NUMERIC)
        self.assertIsNotNone(followup.started_at)
        self.assertEqual(followup.deadline, followup.started_at + timedelta(seconds=Battle.ANSWER_WINDOW_SECONDS))

    def test_zero_correct_answers_spawn_a_new_choice_question(self):
        wrong_option_1, wrong_option_2 = self.step1.choice_question.answer_options.filter(is_correct=False)[:2]
        submit_choice_answer(self.step1, self.attacker, wrong_option_1)
        battle = submit_choice_answer(self.step1, self.defender, wrong_option_2).battle_question.battle

        battle.refresh_from_db()
        self.assertEqual(battle.status, Battle.ACTIVE)
        self.assertEqual(battle.battle_questions.count(), 2)
        followup = battle.battle_questions.get(sequence=2)
        self.assertEqual(followup.question_type, BattleQuestion.CHOICE)
        self.assertNotEqual(followup.choice_question_id, self.step1.choice_question_id)

    def test_missing_answer_is_no_better_than_wrong(self):
        correct_option = self.step1.choice_question.answer_options.get(is_correct=True)
        wrong_option = self.step1.choice_question.answer_options.filter(is_correct=False).first()
        submit_choice_answer(self.step1, self.attacker, wrong_option)
        _expire(self.step1)

        battle = resolve_battle(self.battle)
        self.assertEqual(battle.status, Battle.ACTIVE)
        followup = battle.battle_questions.get(sequence=2)
        self.assertEqual(followup.question_type, BattleQuestion.CHOICE)


class NumericFollowupResolutionTests(TestCase):
    def setUp(self):
        self.game, self.players = make_fully_captured_game()
        self.category = Category.objects.create(name='Cat')
        make_choice_questions(3)
        make_numeric_questions(3)
        self.attacker = self.players[0]
        self.target = owned_neighbor_of(self.attacker)
        self.defender = self.target.owner
        self.battle = start_battle(create_battle(self.attacker, self.target))
        self.step1 = self.battle.battle_questions.get(sequence=1)
        correct_option = self.step1.choice_question.answer_options.get(is_correct=True)
        submit_choice_answer(self.step1, self.attacker, correct_option)
        submit_choice_answer(self.step1, self.defender, correct_option)
        self.step2 = self.battle.battle_questions.get(sequence=2)
        self.battle.refresh_from_db()

    def test_closer_answer_wins(self):
        correct = self.step2.correct_answer
        _answer_numeric(self.step2, self.attacker, correct, 1)
        _answer_numeric(self.step2, self.defender, correct + 5, 1)
        _expire(self.step2)

        battle = resolve_battle(self.battle)
        self.assertEqual(battle.status, Battle.COMPLETED)
        self.assertEqual(battle.winner, self.attacker)

    def test_tie_in_closeness_broken_by_speed(self):
        correct = self.step2.correct_answer
        _answer_numeric(self.step2, self.attacker, correct - 2, 1)  # faster
        _answer_numeric(self.step2, self.defender, correct + 2, 5)  # slower, same deviation
        _expire(self.step2)

        battle = resolve_battle(self.battle)
        self.assertEqual(battle.winner, self.attacker)

    def test_full_tie_spawns_another_numeric_question_not_a_choice_question(self):
        correct = self.step2.correct_answer
        _answer_numeric(self.step2, self.attacker, correct - 2, 1)
        _answer_numeric(self.step2, self.defender, correct + 2, 1)
        _expire(self.step2)

        battle = resolve_battle(self.battle)
        self.assertEqual(battle.status, Battle.ACTIVE)
        self.assertEqual(battle.battle_questions.count(), 3)
        step3 = battle.battle_questions.get(sequence=3)
        self.assertEqual(step3.question_type, BattleQuestion.NUMERIC)

    def test_no_answers_spawns_another_numeric_question_for_the_same_pair(self):
        _expire(self.step2)
        battle = resolve_battle(self.battle)
        self.assertEqual(battle.status, Battle.ACTIVE)
        self.assertEqual(battle.battle_questions.count(), 3)
        self.assertEqual(battle.battle_questions.get(sequence=3).question_type, BattleQuestion.NUMERIC)

    def test_sole_respondent_wins_outright(self):
        _answer_numeric(self.step2, self.defender, self.step2.correct_answer, 1)
        _expire(self.step2)
        battle = resolve_battle(self.battle)
        self.assertEqual(battle.winner, self.defender)

    def test_win_resolved_on_third_question_does_not_spawn_a_fourth(self):
        _expire(self.step2)
        battle = resolve_battle(self.battle)  # no answers -> spawns question 3
        step3 = battle.battle_questions.get(sequence=3)
        _answer_numeric(step3, self.attacker, step3.correct_answer, 1)
        _expire(step3)

        battle = resolve_battle(battle)
        self.assertEqual(battle.battle_questions.count(), 3)
        self.assertEqual(battle.winner, self.attacker)
        self.assertEqual(battle.status, Battle.COMPLETED)
        self.assertEqual(battle.incomplete_reason, '')


class LimitAndBankExhaustionTests(TestCase):
    def setUp(self):
        self.game, self.players = make_fully_captured_game()
        self.attacker = self.players[0]
        self.target = owned_neighbor_of(self.attacker)
        self.defender = self.target.owner

    def test_question_limit_reached_leaves_winner_empty_with_reason(self):
        make_choice_questions(3)
        make_numeric_questions(3)
        battle = start_battle(create_battle(self.attacker, self.target))

        # sequence 1: choice, zero correct -> spawns sequence 2 (choice)
        step1 = battle.battle_questions.get(sequence=1)
        wrong_a, wrong_b = step1.choice_question.answer_options.filter(is_correct=False)[:2]
        submit_choice_answer(step1, self.attacker, wrong_a)
        submit_choice_answer(step1, self.defender, wrong_b)
        battle.refresh_from_db()

        # sequence 2: choice, two correct -> spawns sequence 3 (numeric)
        step2 = battle.battle_questions.get(sequence=2)
        correct_option = step2.choice_question.answer_options.get(is_correct=True)
        submit_choice_answer(step2, self.attacker, correct_option)
        submit_choice_answer(step2, self.defender, correct_option)
        battle.refresh_from_db()

        # sequence 3: numeric, full tie -> would need a 4th question, but the limit is 3
        step3 = battle.battle_questions.get(sequence=3)
        _answer_numeric(step3, self.attacker, step3.correct_answer - 1, 1)
        _answer_numeric(step3, self.defender, step3.correct_answer + 1, 1)
        _expire(step3)
        battle = resolve_battle(battle)

        self.assertEqual(battle.battle_questions.count(), 3)
        self.assertEqual(battle.status, Battle.COMPLETED)
        self.assertIsNone(battle.winner)
        self.assertEqual(battle.incomplete_reason, Battle.QUESTION_LIMIT_REACHED)

    def test_bank_exhausted_leaves_winner_empty_with_reason(self):
        make_choice_questions(1)
        battle = start_battle(create_battle(self.attacker, self.target))
        step1 = battle.battle_questions.get(sequence=1)
        wrong_a, wrong_b = step1.choice_question.answer_options.filter(is_correct=False)[:2]
        submit_choice_answer(step1, self.attacker, wrong_a)
        battle = submit_choice_answer(step1, self.defender, wrong_b).battle_question.battle

        battle.refresh_from_db()
        self.assertEqual(battle.battle_questions.count(), 1)
        self.assertEqual(battle.status, Battle.COMPLETED)
        self.assertIsNone(battle.winner)
        self.assertEqual(battle.incomplete_reason, Battle.BANK_EXHAUSTED)

    def test_limit_takes_precedence_over_bank_exhaustion_as_reason(self):
        # Plenty of unused choice questions remain (the bank is never
        # exhausted), yet a 4th question is still refused once the
        # 3-question limit is hit - the limit must be the recorded reason.
        make_choice_questions(5)
        battle = start_battle(create_battle(self.attacker, self.target))

        step1 = battle.battle_questions.get(sequence=1)
        wrong_a, wrong_b = step1.choice_question.answer_options.filter(is_correct=False)[:2]
        submit_choice_answer(step1, self.attacker, wrong_a)
        submit_choice_answer(step1, self.defender, wrong_b)
        battle.refresh_from_db()

        step2 = battle.battle_questions.get(sequence=2)
        wrong_a, wrong_b = step2.choice_question.answer_options.filter(is_correct=False)[:2]
        submit_choice_answer(step2, self.attacker, wrong_a)
        submit_choice_answer(step2, self.defender, wrong_b)
        battle.refresh_from_db()

        step3 = battle.battle_questions.get(sequence=3)
        wrong_a, wrong_b = step3.choice_question.answer_options.filter(is_correct=False)[:2]
        submit_choice_answer(step3, self.attacker, wrong_a)
        submit_choice_answer(step3, self.defender, wrong_b)
        battle.refresh_from_db()

        self.assertEqual(battle.battle_questions.count(), 3)
        self.assertEqual(battle.status, Battle.COMPLETED)
        self.assertIsNone(battle.winner)
        self.assertEqual(battle.incomplete_reason, Battle.QUESTION_LIMIT_REACHED)


class BattleIntegrityTests(TestCase):
    def setUp(self):
        self.game, self.players = make_fully_captured_game()
        make_choice_questions(2)
        self.attacker = self.players[0]
        self.target = owned_neighbor_of(self.attacker)
        self.defender = self.target.owner
        self.battle = start_battle(create_battle(self.attacker, self.target))
        self.step1 = self.battle.battle_questions.get(sequence=1)

    def test_resolving_a_completed_battle_again_is_rejected(self):
        correct_option = self.step1.choice_question.answer_options.get(is_correct=True)
        submit_choice_answer(self.step1, self.attacker, correct_option)
        wrong_option = self.step1.choice_question.answer_options.filter(is_correct=False).first()
        submit_choice_answer(self.step1, self.defender, wrong_option)

        with self.assertRaises(InvalidStateError):
            resolve_battle(self.battle)

    def test_premature_resolve_is_rejected(self):
        with self.assertRaises(InvalidStateError):
            resolve_battle(self.battle)

    def test_third_participant_cannot_submit_an_answer(self):
        third = next(p for p in self.players if p.pk not in (self.attacker.pk, self.defender.pk))
        correct_option = self.step1.choice_question.answer_options.get(is_correct=True)
        with self.assertRaises(InvalidStateError):
            submit_choice_answer(self.step1, third, correct_option)

    def test_answer_rejected_after_deadline(self):
        _expire(self.step1)
        correct_option = self.step1.choice_question.answer_options.get(is_correct=True)
        with self.assertRaises(InvalidStateError):
            submit_choice_answer(self.step1, self.attacker, correct_option)


class BattleDataPersistenceTests(TestCase):
    def setUp(self):
        self.game, self.players = make_fully_captured_game()
        make_choice_questions(2)
        make_numeric_questions(2)
        self.attacker = self.players[0]
        self.target = owned_neighbor_of(self.attacker)
        self.defender = self.target.owner
        self.battle = start_battle(create_battle(self.attacker, self.target))

    def test_choice_then_numeric_sequence_is_reconstructed_without_loss(self):
        step1 = self.battle.battle_questions.get(sequence=1)
        correct_option = step1.choice_question.answer_options.get(is_correct=True)
        submit_choice_answer(step1, self.attacker, correct_option)
        answer = submit_choice_answer(step1, self.defender, correct_option)
        self.battle.refresh_from_db()

        step2 = self.battle.battle_questions.get(sequence=2)
        _answer_numeric(step2, self.attacker, step2.correct_answer, 1)
        _answer_numeric(step2, self.defender, step2.correct_answer + 1, 1)
        self.battle.refresh_from_db()

        # Editing the source questions afterwards must not change the history.
        step1.choice_question.text = 'edited choice text'
        step1.choice_question.save()
        step2.numeric_question.text = 'edited numeric text'
        step2.numeric_question.correct_answer = 999999
        step2.numeric_question.save()

        reloaded_step1 = BattleQuestion.objects.get(pk=step1.pk)
        reloaded_step2 = BattleQuestion.objects.get(pk=step2.pk)
        self.assertEqual(reloaded_step1.question_type, BattleQuestion.CHOICE)
        self.assertNotEqual(reloaded_step1.question_text, step1.choice_question.text)
        self.assertEqual(reloaded_step2.question_type, BattleQuestion.NUMERIC)
        self.assertNotEqual(reloaded_step2.correct_answer, step2.numeric_question.correct_answer)

        reloaded_answer = BattleAnswer.objects.get(pk=answer.pk)
        self.assertEqual(reloaded_answer.selected_option_id, correct_option.pk)

class SameIdDifferentModelsTests(TestCase):
    """Its own class, with exactly one `ChoiceQuestion` and one
    `NumericQuestion` created in `setUp`, so each is deterministically the
    first (and only) row of its own model - pk=1 in both tables."""

    def setUp(self):
        self.game, self.players = make_fully_captured_game()
        make_choice_questions(1)
        make_numeric_questions(1)
        self.attacker = self.players[0]
        self.target = owned_neighbor_of(self.attacker)
        self.defender = self.target.owner
        self.battle = start_battle(create_battle(self.attacker, self.target))

    def test_same_id_in_choice_and_numeric_models_is_not_confused(self):
        """`ChoiceQuestion` and `NumericQuestion` have independent primary
        keys, so the very first row of each (as created by this test's
        setUp) both get pk=1 - yet the two `BattleQuestion` steps that
        reference them must never be confused, because each has its own
        typed FK column rather than one shared (model, id) pair."""
        step1 = self.battle.battle_questions.get(sequence=1)
        choice_question = step1.choice_question
        correct_option = choice_question.answer_options.get(is_correct=True)
        submit_choice_answer(step1, self.attacker, correct_option)
        submit_choice_answer(step1, self.defender, correct_option)
        self.battle.refresh_from_db()

        step2 = self.battle.battle_questions.get(sequence=2)
        numeric_question = step2.numeric_question
        self.assertEqual(choice_question.pk, numeric_question.pk)

        self.assertEqual(step1.question_type, BattleQuestion.CHOICE)
        self.assertEqual(step1.choice_question_id, choice_question.pk)
        self.assertIsNone(step1.numeric_question_id)

        self.assertEqual(step2.question_type, BattleQuestion.NUMERIC)
        self.assertEqual(step2.numeric_question_id, numeric_question.pk)
        self.assertIsNone(step2.choice_question_id)
        self.assertNotEqual(step1.question_text, step2.question_text)
