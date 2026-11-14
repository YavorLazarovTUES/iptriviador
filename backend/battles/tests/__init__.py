import itertools

from territories.models import Territory
from territories.tests import make_initialized_game


def make_fully_captured_game():
    """An initialized game (M05) with every remaining free territory also
    assigned an owner, round-robin, and no `Round`/`CaptureRight` rows at
    all - a minimal way to reach the M08 precondition ("the map is fully
    captured, no unfinished round, no unfulfilled capture rights") without
    driving the whole M06/M07 city_capture flow in every test.
    """
    game, players = make_initialized_game()
    free_territories = Territory.objects.filter(game=game, owner__isnull=True).order_by('pk')
    cycle = itertools.cycle(players)
    for territory in free_territories:
        territory.owner = next(cycle)
        territory.score = 1
        territory.full_clean()
        territory.save()
    return game, players


def owned_neighbor_of(player):
    """A territory owned by someone else, adjacent to one of `player`'s own - a valid attack target."""
    owned = Territory.objects.filter(game=player.game, owner=player)
    return (
        Territory.objects.filter(game=player.game, neighbors__in=owned)
        .exclude(owner=player)
        .distinct()
        .first()
    )


def owned_non_neighbor_of(player):
    """A territory owned by someone else, not adjacent to any of `player`'s own - an invalid attack target."""
    owned = Territory.objects.filter(game=player.game, owner=player)
    neighbor_ids = Territory.objects.filter(game=player.game, neighbors__in=owned).values_list('pk', flat=True)
    return (
        Territory.objects.filter(game=player.game)
        .exclude(owner=player)
        .exclude(pk__in=neighbor_ids)
        .first()
    )
