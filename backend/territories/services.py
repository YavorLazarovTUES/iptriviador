import random

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F

from games import services as games_services
from games.models import Game, Player, Round
from games.services import InvalidInputError, InvalidStateError

from .map_definition import find_capital_triples, get_map_definition
from .models import Capital, CaptureRight, Territory

# Scoring (M07). Values are this project's own choice, documented in the README:
# a round win is a flat reward; a territory capture reward is the territory's
# OWN score *after* this capture's increment is applied (so a once-recaptured
# territory - a later milestone's mechanic - is worth more to take than a
# never-contested one, since recapturing keeps raising its score).
WIN_REWARD = 10
TERRITORY_SCORE_INCREMENT = 1
CAPTURE_REWARD_MULTIPLIER = 5


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


def free_territory_count(game):
    return Territory.objects.filter(game=game, owner__isnull=True).count()


def _capture_rights_table(free_count):
    """Choice rights granted per the M07 table, from the free-territory count.

    Frozen at round creation (`Round.free_territories_at_start`) and
    recomputed from that same stored number when rewards are applied, so it
    is never re-derived from a possibly-different later territory count.
    """
    if free_count >= 3:
        return 2, 1
    if free_count == 2:
        return 2, 0
    if free_count == 1:
        return 1, 0
    raise InvalidStateError('No free territories remain; a city_capture round cannot be created.')


def create_city_capture_round(game, number):
    free_count = free_territory_count(game)
    rights_first, rights_second = _capture_rights_table(free_count)
    required_places = 2 if rights_second > 0 else 1
    return games_services.create_round(
        game,
        Round.CITY_CAPTURE,
        number,
        required_places=required_places,
        free_territories_at_start=free_count,
    )


def start_city_capture_round(round_obj):
    return games_services.start_round(round_obj)


def submit_city_capture_answer(round_question, player, value):
    with transaction.atomic():
        answer = games_services.submit_answer(round_question, player, value)
        _apply_rewards_if_just_completed(answer.round_question.round_id)
    return answer


def resolve_city_capture_round(round_obj):
    """Explicit resolve, as in M06, with the M07 reward/rights consequences
    applied in the same atomic operation the moment the round completes."""
    with transaction.atomic():
        result = games_services.resolve_round(round_obj)
        _apply_rewards_if_just_completed(result.pk)
    return Round.objects.get(pk=result.pk)


def _apply_rewards_if_just_completed(round_id):
    """Record the final ranking's win reward and choice rights, once.

    Guarded by `Round.rewards_applied` so it is a no-op on a round that was
    already rewarded, regardless of which of the two entry points above
    (or a repeated call) triggered the completion.
    """
    round_obj = Round.objects.select_for_update().get(pk=round_id)
    if round_obj.type != Round.CITY_CAPTURE:
        return
    if round_obj.status != Round.COMPLETED:
        return
    if round_obj.rewards_applied:
        return

    if round_obj.winner_id:
        winner = Player.objects.select_for_update().get(pk=round_obj.winner_id)
        winner.score += WIN_REWARD
        winner.full_clean()
        winner.save()

        rights_first, rights_second = _capture_rights_table(round_obj.free_territories_at_start)
        CaptureRight.objects.create(round=round_obj, player=winner, order=CaptureRight.FIRST, total=rights_first)

        if round_obj.second_place_id and rights_second > 0:
            second = Player.objects.select_for_update().get(pk=round_obj.second_place_id)
            CaptureRight.objects.create(
                round=round_obj, player=second, order=CaptureRight.SECOND, total=rights_second
            )

    round_obj.rewards_applied = True
    round_obj.save(update_fields=['rewards_applied'])


def _is_eligible_territory(player, territory):
    """A free territory is choosable if adjacent to one of the player's own
    territories (their capital counts, since it is owned by them too).

    Exception: if the player has no free neighbor anywhere, any free
    territory in the game is choosable instead.
    """
    if territory.neighbors.filter(owner=player).exists():
        return True
    has_free_neighbor_elsewhere = Territory.objects.filter(
        game_id=territory.game_id, owner__isnull=True, neighbors__owner=player,
    ).exists()
    return not has_free_neighbor_elsewhere


def choose_territory(round_obj, player, territory):
    """One player's one territory choice: ownership, territory score,
    capture reward and the spent right, as a single atomic operation."""
    with transaction.atomic():
        locked_game = Game.objects.select_for_update().get(pk=round_obj.game_id)
        if not locked_game.is_active():
            raise InvalidStateError('The game is not active.')

        try:
            right = CaptureRight.objects.select_for_update().get(round=round_obj, player=player)
        except CaptureRight.DoesNotExist:
            raise InvalidStateError('This player has no capture rights for this round.') from None

        if right.used >= right.total:
            raise InvalidStateError('This player has no remaining capture rights for this round.')

        if right.order == CaptureRight.SECOND:
            first_right = CaptureRight.objects.select_for_update().get(round=round_obj, order=CaptureRight.FIRST)
            if first_right.used < first_right.total:
                raise InvalidStateError("It is not yet the second-place player's turn.")

        locked_territory = Territory.objects.select_for_update().get(pk=territory.pk)
        if locked_territory.game_id != round_obj.game_id:
            raise InvalidStateError('The territory does not belong to this game.')
        if locked_territory.owner_id is not None:
            raise InvalidStateError('This territory is not free.')
        if not _is_eligible_territory(player, locked_territory):
            raise InvalidInputError('This territory is not adjacent to any territory of this player.')

        locked_territory.owner = player
        locked_territory.score += TERRITORY_SCORE_INCREMENT
        locked_territory.full_clean()
        locked_territory.save()

        reward = locked_territory.score * CAPTURE_REWARD_MULTIPLIER
        locked_player = Player.objects.select_for_update().get(pk=player.pk)
        locked_player.score += reward
        locked_player.full_clean()
        locked_player.save()

        right.used += 1
        right.full_clean()
        right.save()

    return locked_territory


def try_advance_capture_phase(game):
    """Create the game's next `city_capture` round, if the capture phase
    allows one right now.

    Explicit operation (mirrors M06's `resolve_round`): returns None,
    without changing anything, while a round is unfinished, its choice
    rights are not yet all used, or no free territory remains (the phase
    is over - a full map does not end the game by itself). Otherwise
    creates and returns the next round; if no valid question is available
    this raises `InvalidStateError` without creating anything, and can be
    retried once the bank is replenished.
    """
    with transaction.atomic():
        locked_game = Game.objects.select_for_update().get(pk=game.pk)
        current_round = locked_game.get_current_round()

        if current_round is not None:
            if current_round.status != Round.COMPLETED:
                return None
            if current_round.type == Round.CITY_CAPTURE:
                unfulfilled_rights = CaptureRight.objects.filter(round=current_round).filter(used__lt=F('total'))
                if unfulfilled_rights.exists():
                    return None

        if free_territory_count(locked_game) == 0:
            return None

        next_number = (current_round.number + 1) if current_round else 1
        return create_city_capture_round(locked_game, next_number)
