from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from questions.models import Category
from questions.tests import make_choice_question

from battles.models import Battle, BattleAnswer, BattleQuestion
from battles.tests import make_fully_captured_game, owned_neighbor_of


class BattleModelTests(TestCase):
    def setUp(self):
        self.game, self.players = make_fully_captured_game()
        self.attacker = self.players[0]
        self.territory = owned_neighbor_of(self.attacker)
        self.defender = self.territory.owner

    def test_attacker_and_defender_must_differ(self):
        battle = Battle(
            game=self.game, attacker=self.attacker, defender=self.attacker,
            territory=self.territory, type=Battle.BATTLE,
        )
        with self.assertRaises(ValidationError):
            battle.full_clean()

    def test_winner_must_be_a_participant(self):
        third = next(p for p in self.players if p.pk not in (self.attacker.pk, self.defender.pk))
        battle = Battle(
            game=self.game, attacker=self.attacker, defender=self.defender, territory=self.territory,
            type=Battle.BATTLE, status=Battle.COMPLETED, winner=third, completed_at=timezone.now(),
        )
        with self.assertRaises(ValidationError):
            battle.full_clean()

    def test_completed_requires_completed_at(self):
        battle = Battle(
            game=self.game, attacker=self.attacker, defender=self.defender, territory=self.territory,
            type=Battle.BATTLE, status=Battle.COMPLETED, winner=self.attacker,
        )
        with self.assertRaises(ValidationError):
            battle.full_clean()

    def test_completed_without_winner_requires_incomplete_reason(self):
        battle = Battle(
            game=self.game, attacker=self.attacker, defender=self.defender, territory=self.territory,
            type=Battle.BATTLE, status=Battle.COMPLETED, completed_at=timezone.now(),
        )
        with self.assertRaises(ValidationError):
            battle.full_clean()

    def test_territory_must_belong_to_the_same_game(self):
        other_game, other_players = make_fully_captured_game()
        other_territory = owned_neighbor_of(other_players[0])
        battle = Battle(
            game=self.game, attacker=self.attacker, defender=self.defender,
            territory=other_territory, type=Battle.BATTLE,
        )
        with self.assertRaises(ValidationError):
            battle.full_clean()


class BattleQuestionModelTests(TestCase):
    def setUp(self):
        self.game, self.players = make_fully_captured_game()
        self.attacker = self.players[0]
        self.territory = owned_neighbor_of(self.attacker)
        self.defender = self.territory.owner
        self.battle = Battle.objects.create(
            game=self.game, attacker=self.attacker, defender=self.defender,
            territory=self.territory, type=Battle.BATTLE,
        )
        self.category = Category.objects.create(name='Cat')

    def test_choice_step_requires_choice_question_only(self):
        choice_question = make_choice_question(self.category)
        step = BattleQuestion(
            battle=self.battle, sequence=1, question_type=BattleQuestion.CHOICE,
            choice_question=choice_question, question_text=choice_question.text,
        )
        step.full_clean()  # does not raise

    def test_choice_step_without_choice_question_is_invalid(self):
        step = BattleQuestion(battle=self.battle, sequence=1, question_type=BattleQuestion.CHOICE, question_text='x')
        with self.assertRaises(ValidationError):
            step.full_clean()

    def test_numeric_step_with_choice_question_is_invalid(self):
        choice_question = make_choice_question(self.category)
        step = BattleQuestion(
            battle=self.battle, sequence=1, question_type=BattleQuestion.NUMERIC,
            choice_question=choice_question, question_text='x', correct_answer=1,
        )
        with self.assertRaises(ValidationError):
            step.full_clean()


class BattleAnswerModelTests(TestCase):
    def setUp(self):
        self.game, self.players = make_fully_captured_game()
        self.attacker = self.players[0]
        self.territory = owned_neighbor_of(self.attacker)
        self.defender = self.territory.owner
        self.third = next(p for p in self.players if p.pk not in (self.attacker.pk, self.defender.pk))
        self.battle = Battle.objects.create(
            game=self.game, attacker=self.attacker, defender=self.defender,
            territory=self.territory, type=Battle.BATTLE,
        )
        self.category = Category.objects.create(name='Cat')
        self.choice_question = make_choice_question(self.category, correct_index=0)
        self.other_choice_question = make_choice_question(self.category, correct_index=0)
        self.step = BattleQuestion.objects.create(
            battle=self.battle, sequence=1, question_type=BattleQuestion.CHOICE,
            choice_question=self.choice_question, question_text=self.choice_question.text,
        )

    def test_valid_choice_answer(self):
        option = self.choice_question.answer_options.first()
        answer = BattleAnswer(
            battle_question=self.step, player=self.attacker, selected_option=option, answered_at=timezone.now(),
        )
        answer.full_clean()  # does not raise

    def test_option_from_another_question_is_rejected(self):
        foreign_option = self.other_choice_question.answer_options.first()
        answer = BattleAnswer(
            battle_question=self.step, player=self.attacker, selected_option=foreign_option,
            answered_at=timezone.now(),
        )
        with self.assertRaises(ValidationError):
            answer.full_clean()

    def test_third_participant_cannot_answer(self):
        option = self.choice_question.answer_options.first()
        answer = BattleAnswer(
            battle_question=self.step, player=self.third, selected_option=option, answered_at=timezone.now(),
        )
        with self.assertRaises(ValidationError):
            answer.full_clean()

    def test_choice_answer_cannot_also_set_value(self):
        option = self.choice_question.answer_options.first()
        answer = BattleAnswer(
            battle_question=self.step, player=self.attacker, selected_option=option, value=1,
            answered_at=timezone.now(),
        )
        with self.assertRaises(ValidationError):
            answer.full_clean()
