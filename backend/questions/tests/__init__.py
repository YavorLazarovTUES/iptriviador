import itertools

from questions.models import AnswerOption, Category, ChoiceQuestion

_category_counter = itertools.count()


def make_choice_question(category, correct_index=0, text='2 + 2?'):
    question = ChoiceQuestion.objects.create(category=category, text=text)
    for index in range(4):
        AnswerOption.objects.create(
            question=question,
            text=str(index),
            is_correct=(index == correct_index),
        )
    return question


def make_choice_questions(count, correct_index=0):
    category = Category.objects.create(name=f'ChoiceCategory-{next(_category_counter)}')
    return [
        make_choice_question(category, correct_index, text=f'Choice question {index}')
        for index in range(count)
    ]
