import itertools

from accounts.tests import make_user
from questions.models import Category, NumericQuestion

from games.models import Game, Player

_username_counter = itertools.count()


def make_game_with_players(count=3, status=None):
    game = Game.objects.create()
    colors = [Player.RED, Player.GREEN, Player.BLUE, 'yellow']
    players = []
    for index in range(count):
        suffix = next(_username_counter)
        username = f'player_{suffix}'
        user = make_user(username, nickname=f'Knight{suffix}')
        players.append(Player.objects.create(game=game, user=user, color=colors[index]))
    if status is not None:
        game.status = status
        game.full_clean()
        game.save()
    return game, players


def make_numeric_questions(count, start_answer=10):
    category = Category.objects.create(name=f'Category-{NumericQuestion.objects.count()}')
    return [
        NumericQuestion.objects.create(
            category=category,
            text=f'Numeric question {index}',
            correct_answer=start_answer + index,
        )
        for index in range(count)
    ]
