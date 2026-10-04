from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from accounts.tests import make_user
from games.models import Game, GamePlayer, Round, RoundAnswer
from questions.models import AnswerOption, Category, ChoiceQuestion, NumericQuestion


def make_choice_question(category):
    question = ChoiceQuestion.objects.create(category=category, text='2 + 2?')
    for index in range(4):
        AnswerOption.objects.create(question=question, text=str(index), is_correct=(index == 0))
    return question


class GamePlayerConstraintTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.game = Game.objects.create(created_by=self.user)

    def test_user_cannot_join_the_same_game_twice(self):
        GamePlayer.objects.create(game=self.game, user=self.user, player_order=1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                GamePlayer.objects.create(game=self.game, user=self.user, player_order=2)

    def test_player_order_must_be_unique_within_a_game(self):
        other_user = make_user('player_two', nickname='ForestKnight')
        GamePlayer.objects.create(game=self.game, user=self.user, player_order=1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                GamePlayer.objects.create(game=self.game, user=other_user, player_order=1)

    def test_deleting_game_deletes_players(self):
        player = GamePlayer.objects.create(game=self.game, user=self.user, player_order=1)
        self.game.delete()
        self.assertFalse(GamePlayer.objects.filter(pk=player.pk).exists())

    def test_user_with_game_player_cannot_be_deleted(self):
        GamePlayer.objects.create(game=self.game, user=self.user, player_order=1)
        with self.assertRaises(ProtectedError):
            self.user.delete()


class RoundConstraintTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.game = Game.objects.create(created_by=self.user)
        self.category = Category.objects.create(name='Geography')

    def test_round_number_must_be_unique_within_a_game(self):
        question = make_choice_question(self.category)
        Round.objects.create(game=self.game, number=1, question_type=Round.CHOICE, choice_question=question)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Round.objects.create(
                    game=self.game, number=1, question_type=Round.CHOICE, choice_question=question
                )

    def test_choice_round_requires_a_choice_question(self):
        round_ = Round(game=self.game, number=1, question_type=Round.CHOICE)
        with self.assertRaises(ValidationError):
            round_.full_clean()

    def test_choice_round_cannot_also_have_a_numeric_question(self):
        choice_question = make_choice_question(self.category)
        numeric_question = NumericQuestion.objects.create(
            category=self.category, text='2 + 2?', correct_answer=4
        )
        round_ = Round(
            game=self.game,
            number=1,
            question_type=Round.CHOICE,
            choice_question=choice_question,
            numeric_question=numeric_question,
        )
        with self.assertRaises(ValidationError):
            round_.full_clean()

    def test_numeric_round_requires_a_numeric_question(self):
        round_ = Round(game=self.game, number=1, question_type=Round.NUMERIC)
        with self.assertRaises(ValidationError):
            round_.full_clean()

    def test_deleting_game_deletes_rounds(self):
        question = make_choice_question(self.category)
        round_ = Round.objects.create(
            game=self.game, number=1, question_type=Round.CHOICE, choice_question=question
        )
        self.game.delete()
        self.assertFalse(Round.objects.filter(pk=round_.pk).exists())

    def test_question_with_round_cannot_be_deleted(self):
        question = make_choice_question(self.category)
        Round.objects.create(game=self.game, number=1, question_type=Round.CHOICE, choice_question=question)
        with self.assertRaises(ProtectedError):
            question.delete()


class RoundAnswerConstraintTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.game = Game.objects.create(created_by=self.user)
        self.player = GamePlayer.objects.create(game=self.game, user=self.user, player_order=1)
        self.category = Category.objects.create(name='Geography')
        self.question = make_choice_question(self.category)
        self.round = Round.objects.create(
            game=self.game, number=1, question_type=Round.CHOICE, choice_question=self.question
        )

    def test_player_cannot_answer_the_same_round_twice(self):
        option = self.question.answer_options.first()
        RoundAnswer.objects.create(round=self.round, player=self.player, selected_option=option)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RoundAnswer.objects.create(round=self.round, player=self.player, selected_option=option)

    def test_answer_cannot_have_both_selected_option_and_numeric_value(self):
        option = self.question.answer_options.first()
        answer = RoundAnswer(round=self.round, player=self.player, selected_option=option, numeric_value=1)
        with self.assertRaises(ValidationError):
            answer.full_clean()

    def test_deleting_round_deletes_answers(self):
        option = self.question.answer_options.first()
        answer = RoundAnswer.objects.create(round=self.round, player=self.player, selected_option=option)
        self.round.delete()
        self.assertFalse(RoundAnswer.objects.filter(pk=answer.pk).exists())

    def test_deleting_player_deletes_answers(self):
        option = self.question.answer_options.first()
        answer = RoundAnswer.objects.create(round=self.round, player=self.player, selected_option=option)
        self.player.delete()
        self.assertFalse(RoundAnswer.objects.filter(pk=answer.pk).exists())

    def test_answer_option_with_round_answer_cannot_be_deleted(self):
        option = self.question.answer_options.first()
        RoundAnswer.objects.create(round=self.round, player=self.player, selected_option=option)
        with self.assertRaises(ProtectedError):
            option.delete()
