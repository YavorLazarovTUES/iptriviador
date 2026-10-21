import random

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Game, Player, WaitingEntry


class AlreadyWaiting(Exception):
    pass


def is_eligible(user):
    return not Player.objects.filter(user=user, game__status__in=[Game.WAITING, Game.ACTIVE]).exists()


def join_waiting_room(user):
    if not is_eligible(user):
        raise ValidationError('Already in a waiting or active game.')
    entry, created = WaitingEntry.objects.get_or_create(user=user)
    if not created:
        raise AlreadyWaiting('Already waiting.')
    return entry

def leave_waiting_room(user):
    deleted, _ = WaitingEntry.objects.filter(user=user).delete()
    return deleted > 0

def form_game():
    with transaction.atomic():
        entries = [entry for entry in WaitingEntry.objects.select_for_update() if is_eligible(entry.user)]
        if len(entries) < 3:
            return None
        game = Game.objects.create()
        for entry, color in zip(random.sample(entries, 3), [Player.RED, Player.GREEN, Player.BLUE]):
            Player.objects.create(game=game, user=entry.user, color=color)
            entry.delete()
        return game
