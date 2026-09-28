from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from questions.models import AnswerOption, Category, ChoiceQuestion, NumericQuestion


def make_choice_question(category, correct_index=0):
    question = ChoiceQuestion.objects.create(category=category, text='2 + 2?')
    for index in range(4):
        AnswerOption.objects.create(
            question=question,
            text=str(index),
            is_correct=(index == correct_index),
        )
    return question


class CategoryModelTests(TestCase):
    def test_create_category(self):
        category = Category.objects.create(name='Geography')
        self.assertEqual(category.name, 'Geography')

    def test_name_must_be_unique(self):
        Category.objects.create(name='Geography')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Category.objects.create(name='Geography')


class ChoiceQuestionModelTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Geography')

    def test_create_valid_choice_question(self):
        question = make_choice_question(self.category)
        question.full_clean()
        self.assertEqual(question.category, self.category)
        self.assertEqual(question.answer_options.count(), 4)
        self.assertEqual(question.answer_options.filter(is_correct=True).count(), 1)

    def test_invalid_with_wrong_number_of_answers(self):
        question = ChoiceQuestion.objects.create(category=self.category, text='2 + 2?')
        AnswerOption.objects.create(question=question, text='4', is_correct=True)
        AnswerOption.objects.create(question=question, text='5', is_correct=False)
        with self.assertRaises(ValidationError):
            question.full_clean()

    def test_invalid_with_no_correct_answer(self):
        question = ChoiceQuestion.objects.create(category=self.category, text='2 + 2?')
        for index in range(4):
            AnswerOption.objects.create(question=question, text=str(index), is_correct=False)
        with self.assertRaises(ValidationError):
            question.full_clean()

    def test_invalid_with_more_than_one_correct_answer(self):
        question = ChoiceQuestion.objects.create(category=self.category, text='2 + 2?')
        for index in range(4):
            AnswerOption.objects.create(question=question, text=str(index), is_correct=True)
        with self.assertRaises(ValidationError):
            question.full_clean()

    def test_deleting_question_deletes_answer_options(self):
        question = make_choice_question(self.category)
        option_ids = list(question.answer_options.values_list('id', flat=True))
        question.delete()
        self.assertFalse(AnswerOption.objects.filter(id__in=option_ids).exists())


class NumericQuestionModelTests(TestCase):
    def test_create_numeric_question(self):
        category = Category.objects.create(name='Math')
        question = NumericQuestion.objects.create(
            category=category, text='How many continents are there?', correct_answer=7
        )
        question.full_clean()
        self.assertEqual(question.correct_answer, 7)


class CategoryProtectionTests(TestCase):
    def test_category_with_choice_question_cannot_be_deleted(self):
        category = Category.objects.create(name='Geography')
        make_choice_question(category)
        with self.assertRaises(ProtectedError):
            category.delete()

    def test_category_with_numeric_question_cannot_be_deleted(self):
        category = Category.objects.create(name='Math')
        NumericQuestion.objects.create(category=category, text='2 + 2?', correct_answer=4)
        with self.assertRaises(ProtectedError):
            category.delete()
