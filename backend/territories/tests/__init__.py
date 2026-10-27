from games.tests import make_game_with_players, make_numeric_questions  # noqa: F401
from territories.services import initialize_game


def make_initialized_game():
    game, players = make_game_with_players(3)
    initialize_game(game)
    game.refresh_from_db()
    return game, players
