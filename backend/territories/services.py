import random

from django.core.exceptions import ValidationError
from django.db import transaction

from games.models import Game

from .map_definition import find_capital_triples, get_map_definition
from .models import Capital, Territory


def initialize_game(game):
    """Create the game's territories and capitals from the project map, and activate it.

    Runs as a single atomic, re-checked-under-lock operation: a game can only be
    initialized once, from `waiting` with exactly `Game.REQUIRED_PLAYER_COUNT`
    players, and any failure leaves no partial territories, capitals or status
    change behind.
    """
    with transaction.atomic():
        locked_game = Game.objects.select_for_update().get(pk=game.pk)

        if locked_game.status != Game.WAITING:
            raise ValidationError('Only a waiting game can be initialized.')

        players = list(locked_game.players.all())
        if len(players) != Game.REQUIRED_PLAYER_COUNT:
            raise ValidationError(
                f'A game can only be initialized with exactly {Game.REQUIRED_PLAYER_COUNT} players.'
            )

        if locked_game.territories.exists():
            raise ValidationError('This game has already been initialized.')

        definition = get_map_definition()
        territories_by_slug = _create_territories(locked_game, definition)
        _assign_capitals(players, definition, territories_by_slug)

        locked_game.status = Game.ACTIVE
        locked_game.full_clean()
        locked_game.save()

    return locked_game


def _create_territories(game, definition):
    territories_by_slug = {}
    for entry in definition['territories']:
        territory = Territory(game=game, name=entry['name'], slug=entry['slug'])
        territory.full_clean()
        territory.save()
        territories_by_slug[entry['slug']] = territory

    for slug_a, slug_b in definition['neighbors']:
        territories_by_slug[slug_a].add_neighbor(territories_by_slug[slug_b])

    return territories_by_slug


def _assign_capitals(players, definition, territories_by_slug):
    capital_triples = find_capital_triples(definition['adjacency'])
    if not capital_triples:
        raise ValidationError('No valid capital assignment exists for this map.')

    chosen_slugs = list(random.choice(capital_triples))
    shuffled_players = list(players)
    random.shuffle(shuffled_players)

    for player, slug in zip(shuffled_players, chosen_slugs):
        territory = territories_by_slug[slug]
        territory.owner = player
        territory.full_clean()
        territory.save()

        capital = Capital(territory=territory, player=player, health=Capital.MAX_HEALTH)
        capital.full_clean()
        capital.save()
