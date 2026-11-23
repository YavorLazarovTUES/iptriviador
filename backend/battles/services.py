"""Service layer for the battle workflow (M08).

Follows the same interface contract as `games.services` (see its own
docstring): malformed caller input raises `InvalidInputError`, a
disallowed-but-well-formed operation raises `InvalidStateError`, and a
missing record is left to surface as the model's own `DoesNotExist`. Both
exceptions are imported from `games.services` rather than redefined here,
so a caller catching either module's errors sees the same two types.
"""
import random
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from games.models import Player, Round
from games.services import InvalidInputError, InvalidStateError
from questions.models import AnswerOption, ChoiceQuestion, NumericQuestion
from territories.models import Capital, CaptureRight, Territory
from territories.services import CAPTURE_REWARD_MULTIPLIER, TERRITORY_SCORE_INCREMENT, WIN_REWARD

from .models import Battle, BattleAnswer, BattleQuestion


def _validate_integer(value):
    if isinstance(value, bool):
        raise InvalidInputError('A whole number answer is required.')
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            raise InvalidInputError('A whole number answer is required.')
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped.lstrip('-').isdigit():
            raise InvalidInputError('A whole number answer is required.')
        return int(stripped)
    raise InvalidInputError('A whole number answer is required.')


def _pick_unused_choice_question(game):
    used_ids = BattleQuestion.objects.filter(
        battle__game=game, question_type=BattleQuestion.CHOICE,
    ).values_list('choice_question_id', flat=True)
    candidates = list(ChoiceQuestion.objects.exclude(pk__in=used_ids))
    return random.choice(candidates) if candidates else None


def _pick_unused_numeric_question(game):
    """A `NumericQuestion` never used by *this* game before, in either a
    `city_capture` round (`games.RoundQuestion`) or an earlier battle -
    the game-wide "no repeat for this concrete model" rule the spec asks
    for.
    """
    from games.models import RoundQuestion

    used_in_rounds = RoundQuestion.objects.filter(round__game=game).values_list('question_id', flat=True)
    used_in_battles = BattleQuestion.objects.filter(
        battle__game=game, question_type=BattleQuestion.NUMERIC,
    ).values_list('numeric_question_id', flat=True)
    used_ids = list(used_in_rounds) + list(used_in_battles)
    candidates = list(NumericQuestion.objects.exclude(pk__in=used_ids))
    return random.choice(candidates) if candidates else None


def _has_unfinished_round(game):
    return Round.objects.filter(game=game).exclude(status=Round.COMPLETED).exists()


def _has_unfulfilled_capture_rights(game):
    return CaptureRight.objects.filter(round__game=game).filter(used__lt=F('total')).exists()


def _is_adjacent_to_attacker(attacker, territory):
    return territory.neighbors.filter(owner=attacker).exists()


def create_battle(attacker, territory, defender=None):
    """Create a `pending` battle with its first (unstarted) choice question.

    The target's current owner determines the defender; passing a
    different `defender` is rejected rather than silently overridden.
    Raises `InvalidStateError` for a game/round/rights state that doesn't
    allow a battle yet (game not active, the map not fully captured, an
    unfinished round, unfulfilled capture rights) or for an empty choice
    question bank, and `InvalidInputError` for a bad target (free, the
    attacker's own, from another game, or not adjacent to any of the
    attacker's territories) or a mismatched `defender`. Nothing is created
    on any failure.
    """
    with transaction.atomic():
        game = territory.game

        if not game.is_active():
            raise InvalidStateError('A battle can only be created for an active game.')

        # The target itself is checked before the game-wide "map fully
        # captured"/round/rights gates below, so a bad target (free, the
        # attacker's own, foreign, non-adjacent) is always reported as
        # exactly that - never masked by an unrelated free territory
        # elsewhere on the map.
        if attacker.game_id != game.pk:
            raise InvalidInputError('The attacker does not belong to this game.')
        if territory.owner_id is None:
            raise InvalidInputError('A free territory cannot be attacked.')
        if territory.owner_id == attacker.pk:
            raise InvalidInputError('A player cannot attack their own territory.')
        if not _is_adjacent_to_attacker(attacker, territory):
            raise InvalidInputError('The target territory is not adjacent to any territory of the attacker.')

        actual_defender = territory.owner
        if defender is not None and defender.pk != actual_defender.pk:
            raise InvalidInputError("The submitted defender does not match the target territory's owner.")

        if Territory.objects.filter(game=game, owner__isnull=True).exists():
            raise InvalidStateError('A battle can only start once the whole map is captured.')
        if _has_unfinished_round(game):
            raise InvalidStateError('A battle cannot start while a round is unfinished.')
        if _has_unfulfilled_capture_rights(game):
            raise InvalidStateError('A battle cannot start while capture rights remain unfulfilled.')

        battle_type = Battle.CAPITAL_ATTACK if Capital.objects.filter(territory=territory).exists() else Battle.BATTLE

        question = _pick_unused_choice_question(game)
        if question is None:
            raise InvalidStateError('No valid unused choice question is available.')

        battle = Battle(
            game=game,
            attacker=attacker,
            defender=actual_defender,
            territory=territory,
            type=battle_type,
            status=Battle.PENDING,
        )
        battle.full_clean()
        battle.save()

        battle_question = BattleQuestion(
            battle=battle,
            sequence=1,
            question_type=BattleQuestion.CHOICE,
            choice_question=question,
            question_text=question.text,
        )
        battle_question.full_clean()
        battle_question.save()

    return battle


def start_battle(battle):
    with transaction.atomic():
        locked = Battle.objects.select_for_update().get(pk=battle.pk)
        if not locked.game.is_active():
            raise InvalidStateError('A battle can only be started for an active game.')
        if locked.status != Battle.PENDING:
            raise InvalidStateError('Only a pending battle can be started.')

        battle_question = locked.battle_questions.get(sequence=1)
        now = timezone.now()
        battle_question.started_at = now
        battle_question.deadline = now + timedelta(seconds=Battle.ANSWER_WINDOW_SECONDS)
        battle_question.full_clean()
        battle_question.save()
        _schedule_deadline_check(battle_question)

        locked.status = Battle.ACTIVE
        locked.full_clean()
        locked.save()

    return locked


def _schedule_deadline_check(battle_question):
    """Hand the "close this question at its deadline" work to a Celery
    worker (M09); queued only after the current transaction commits."""
    from .tasks import schedule_deadline_check

    schedule_deadline_check(battle_question)


def _current_open_question(locked_battle):
    return locked_battle.battle_questions.filter(resolved_at__isnull=True).order_by('-sequence').first()


def submit_choice_answer(battle_question, player, option):
    return _submit_answer(battle_question, player, selected_option=option)


def submit_numeric_answer(battle_question, player, value):
    clean_value = _validate_integer(value)
    return _submit_answer(battle_question, player, value=clean_value)


def _submit_answer(battle_question, player, selected_option=None, value=None):
    with transaction.atomic():
        locked_battle = Battle.objects.select_for_update().get(pk=battle_question.battle_id)
        if not locked_battle.game.is_active():
            raise InvalidStateError('The game is not active.')
        if locked_battle.status != Battle.ACTIVE:
            raise InvalidStateError('The battle is not active.')

        open_question = _current_open_question(locked_battle)
        if open_question is None or open_question.pk != battle_question.pk:
            raise InvalidStateError('This question is not currently open for answers.')
        if not open_question.is_started():
            raise InvalidStateError('This question has not started yet.')
        if player.pk not in (locked_battle.attacker_id, locked_battle.defender_id):
            raise InvalidStateError('This player is not a participant in this battle.')

        now = timezone.now()
        if now >= open_question.deadline:
            raise InvalidStateError('The answer window has closed.')

        if BattleAnswer.objects.filter(battle_question=open_question, player=player).exists():
            raise InvalidStateError('This player has already answered this question.')

        if open_question.question_type == BattleQuestion.CHOICE:
            if selected_option is None or value is not None:
                raise InvalidInputError('A choice answer requires a selected option only.')
            if selected_option.question_id != open_question.choice_question_id:
                raise InvalidInputError('The selected option does not belong to this question.')
        else:
            if value is None or selected_option is not None:
                raise InvalidInputError('A numeric answer requires a value only.')

        answer = BattleAnswer(
            battle_question=open_question,
            player=player,
            selected_option=selected_option,
            value=value,
            answered_at=now,
        )
        answer.full_clean()
        answer.save()

        answered_count = BattleAnswer.objects.filter(battle_question=open_question).count()
        if answered_count == 2:
            _resolve_question(locked_battle, open_question)

    return answer


def resolve_battle(battle):
    """Explicitly try to resolve the battle's current open question.

    Rejected (raises `InvalidStateError`) unless both participants have
    answered or the deadline has passed - the same explicit-resolve
    contract as `games.services.resolve_round`.
    """
    with transaction.atomic():
        locked_battle = Battle.objects.select_for_update().get(pk=battle.pk)
        if locked_battle.status != Battle.ACTIVE:
            raise InvalidStateError('Only an active battle can be resolved.')

        open_question = _current_open_question(locked_battle)
        if open_question is None:
            raise InvalidStateError('There is no open question to resolve.')
        if not open_question.is_started():
            raise InvalidStateError('The current question has not started yet.')

        answered_count = BattleAnswer.objects.filter(battle_question=open_question).count()
        now = timezone.now()
        all_answered = answered_count == 2
        deadline_passed = now >= open_question.deadline
        if not all_answered and not deadline_passed:
            raise InvalidStateError('The battle question cannot be resolved yet.')

        _resolve_question(locked_battle, open_question)

    return locked_battle


def _resolve_question(locked_battle, question):
    now = timezone.now()
    question.resolved_at = now
    question.save(update_fields=['resolved_at'])

    if question.question_type == BattleQuestion.CHOICE:
        _resolve_choice_question(locked_battle, question)
    else:
        _resolve_numeric_question(locked_battle, question)


def _resolve_choice_question(locked_battle, question):
    """One, two or zero correct answers, per the M08 table.

    A wrong answer and no answer at all count the same (neither is
    "correct"), and two correct answers are never compared by speed - they
    always fall through to a numeric tie-break instead.
    """
    answers = list(BattleAnswer.objects.filter(battle_question=question))
    correct_players = [answer.player for answer in answers if answer.is_correct_choice()]

    if len(correct_players) == 1:
        _finalize_with_winner(locked_battle, correct_players[0])
    elif len(correct_players) == 2:
        _spawn_followup(locked_battle, BattleQuestion.NUMERIC)
    else:
        _spawn_followup(locked_battle, BattleQuestion.CHOICE)


def _resolve_numeric_question(locked_battle, question):
    """Only first place matters here: the closest `abs(value - correct)`
    wins, ties broken by the faster `answered_at - started_at`. A full tie
    or zero answers spawns another numeric question for the same two
    players - never back to a choice question.
    """
    answers = list(BattleAnswer.objects.filter(battle_question=question))

    if not answers:
        _spawn_followup(locked_battle, BattleQuestion.NUMERIC)
        return
    if len(answers) == 1:
        _finalize_with_winner(locked_battle, answers[0].player)
        return

    scored = sorted(
        ((answer.deviation(), answer.elapsed(), answer.player) for answer in answers),
        key=lambda item: (item[0], item[1]),
    )
    best_deviation, best_elapsed, best_player = scored[0]
    tied = [
        player for deviation, elapsed, player in scored
        if deviation == best_deviation and elapsed == best_elapsed
    ]
    if len(tied) == 1:
        _finalize_with_winner(locked_battle, best_player)
    else:
        _spawn_followup(locked_battle, BattleQuestion.NUMERIC)


def _spawn_followup(locked_battle, question_type):
    """Create the next question step, unless the limit or the bank
    refuses it - the limit always takes precedence as the recorded reason.
    """
    if locked_battle.battle_questions.count() >= Battle.MAX_QUESTIONS:
        _finalize_incomplete(locked_battle, Battle.QUESTION_LIMIT_REACHED)
        return

    if question_type == BattleQuestion.CHOICE:
        question = _pick_unused_choice_question(locked_battle.game)
    else:
        question = _pick_unused_numeric_question(locked_battle.game)

    if question is None:
        _finalize_incomplete(locked_battle, Battle.BANK_EXHAUSTED)
        return

    now = timezone.now()
    sequence = locked_battle.battle_questions.count() + 1
    fields = dict(
        battle=locked_battle,
        sequence=sequence,
        question_type=question_type,
        question_text=question.text,
        started_at=now,
        deadline=now + timedelta(seconds=Battle.ANSWER_WINDOW_SECONDS),
    )
    if question_type == BattleQuestion.CHOICE:
        fields['choice_question'] = question
    else:
        fields['numeric_question'] = question
        fields['correct_answer'] = question.correct_answer

    battle_question = BattleQuestion(**fields)
    battle_question.full_clean()
    battle_question.save()
    _schedule_deadline_check(battle_question)


def _finalize_with_winner(locked_battle, player):
    locked_battle.winner = player
    locked_battle.status = Battle.COMPLETED
    locked_battle.completed_at = timezone.now()
    locked_battle.full_clean()
    locked_battle.save()


def _finalize_incomplete(locked_battle, reason):
    locked_battle.incomplete_reason = reason
    locked_battle.status = Battle.COMPLETED
    locked_battle.completed_at = timezone.now()
    locked_battle.full_clean()
    locked_battle.save()


def apply_battle_result(battle):
    """Apply a completed battle's consequences exactly once, atomically.

    Re-checks under lock that the target territory's owner still matches
    the battle's recorded defender (a different, concurrent battle may
    have captured it first) and raises `InvalidStateError` without
    changing anything if it doesn't - the previously accepted answers and
    the battle's own winner/incomplete_reason stay exactly as resolved;
    only the reward step is refused. Calling this again on a battle whose
    result was already applied is a no-op (`Battle.rewards_applied`), so
    rewards are never double-granted regardless of how many times it is
    called.

    Reward formulas reuse the project's own M07 constants
    (`territories.services`): the win reward is flat and unconditional;
    a successful `battle` attack additionally increments the target's
    `Territory.score` and credits the attacker with that post-increment
    score times the capture multiplier - the same two-part formula M07
    uses for a captured free territory, so a changed-owner territory's
    score only ever goes up, never resets. A successful defense or any
    `capital_attack` outcome grants the win reward alone: ownership,
    `Territory.score` and the capital's own fields never change.
    """
    with transaction.atomic():
        locked_battle = Battle.objects.select_for_update().get(pk=battle.pk)
        if locked_battle.status != Battle.COMPLETED:
            raise InvalidStateError('Only a completed battle can have its result applied.')
        if locked_battle.rewards_applied:
            return locked_battle

        locked_territory = Territory.objects.select_for_update().get(pk=locked_battle.territory_id)
        if locked_territory.owner_id != locked_battle.defender_id:
            raise InvalidStateError(
                'The target territory no longer matches this battle; nothing was applied.'
            )

        if locked_battle.winner_id:
            winner = Player.objects.select_for_update().get(pk=locked_battle.winner_id)
            reward = WIN_REWARD

            if locked_battle.type == Battle.BATTLE and locked_battle.winner_id == locked_battle.attacker_id:
                locked_territory.owner = winner
                locked_territory.score += TERRITORY_SCORE_INCREMENT
                locked_territory.full_clean()
                locked_territory.save()
                reward += locked_territory.score * CAPTURE_REWARD_MULTIPLIER

            winner.score += reward
            winner.full_clean()
            winner.save()

        locked_battle.rewards_applied = True
        locked_battle.save(update_fields=['rewards_applied'])

    return locked_battle
