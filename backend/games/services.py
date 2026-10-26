"""Service layer for the Round question/answer workflow (M06).

Interface contract
-------------------
Callers of this module need to tell apart three different failure shapes:

- **Invalid input** (the caller passed something malformed, e.g. a
  non-integer answer value) -> :class:`InvalidInputError`.
- **Invalid state** (the input is well-formed, but the operation is not
  allowed right now, e.g. the game is not active, the round is not
  ``pending``, or the answer window has already closed) ->
  :class:`InvalidStateError`.
- **Missing record** (a referenced row does not exist) -> the normal
  Django ``<Model>.DoesNotExist`` exception, e.g. ``Round.DoesNotExist``
  when resolving a round id that was never created. This module never
  wraps that exception, since catching the model's own ``DoesNotExist``
  is already the standard Django idiom callers already rely on
  elsewhere in this project (see ``territories.services.initialize_game``,
  which lets a bad ``game.pk`` surface as ``Game.DoesNotExist``).

Both ``InvalidInputError`` and ``InvalidStateError`` subclass Django's
``ValidationError`` so existing ``except ValidationError`` call sites
(e.g. the admin actions) keep working unchanged, while a caller that
cares about the distinction can catch the specific subclass. Example
from this project: ``submit_answer`` raises ``InvalidInputError`` for a
value such as ``"3.5"`` (not a whole number), ``InvalidStateError`` for
an answer submitted after the 10 second deadline, and lets
``RoundQuestion.DoesNotExist`` propagate when given an id for a question
that was never created.
"""
import random
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from questions.models import NumericQuestion

from .models import Round, RoundAnswer, RoundQuestion


class InvalidInputError(ValidationError):
    """The caller-supplied data itself is malformed."""


class InvalidStateError(ValidationError):
    """The operation is not allowed given the current round/game state."""


def _pick_numeric_question(game):
    used_ids = RoundQuestion.objects.filter(round__game=game).values_list('question_id', flat=True)
    candidates = list(NumericQuestion.objects.exclude(pk__in=used_ids))
    if not candidates:
        return None
    return random.choice(candidates)


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


def create_round(game, round_type, number, required_places, free_territories_at_start=None):
    """Create a `pending` round with its first (unstarted) question.

    `required_places` (1 or 2) and `free_territories_at_start` are decided
    by the caller before the round starts (see
    `territories.services.create_city_capture_round`) and are stored as-is.
    """
    if required_places not in (1, 2):
        raise InvalidInputError('required_places must be 1 or 2.')

    with transaction.atomic():
        if not game.is_active():
            raise InvalidStateError('A round can only be created for an active game.')

        players = list(game.players.all())
        if len(players) != game.REQUIRED_PLAYER_COUNT:
            raise InvalidStateError(
                f'A round requires exactly {game.REQUIRED_PLAYER_COUNT} players in the game.'
            )

        question = _pick_numeric_question(game)
        if question is None:
            raise InvalidStateError('No valid unused numeric question is available.')

        round_obj = Round(
            game=game,
            number=number,
            type=round_type,
            status=Round.PENDING,
            required_places=required_places,
            free_territories_at_start=free_territories_at_start,
        )
        round_obj.full_clean()
        round_obj.save()

        round_question = RoundQuestion(
            round=round_obj,
            sequence=1,
            target_rank=RoundQuestion.FIRST_PLACE,
            question=question,
            question_text=question.text,
            correct_answer=question.correct_answer,
        )
        round_question.full_clean()
        round_question.save()
        round_question.contenders.set(players)

    return round_obj


def start_round(round_obj):
    with transaction.atomic():
        locked = Round.objects.select_for_update().get(pk=round_obj.pk)
        if not locked.game.is_active():
            raise InvalidStateError('A round can only be started for an active game.')
        if locked.status != Round.PENDING:
            raise InvalidStateError('Only a pending round can be started.')

        round_question = locked.round_questions.get(sequence=1)
        now = timezone.now()
        round_question.started_at = now
        round_question.deadline = now + timedelta(seconds=Round.ANSWER_WINDOW_SECONDS)
        round_question.full_clean()
        round_question.save()

        locked.status = Round.ACTIVE
        locked.full_clean()
        locked.save()

    return locked


def _current_open_question(locked_round):
    return locked_round.round_questions.filter(resolved_at__isnull=True).order_by('-sequence').first()


def submit_answer(round_question, player, value):
    with transaction.atomic():
        locked_round = Round.objects.select_for_update().get(pk=round_question.round_id)
        if not locked_round.game.is_active():
            raise InvalidStateError('The game is not active.')
        if locked_round.status != Round.ACTIVE:
            raise InvalidStateError('The round is not active.')

        open_question = _current_open_question(locked_round)
        if open_question is None or open_question.pk != round_question.pk:
            raise InvalidStateError('This question is not currently open for answers.')
        if not open_question.is_started():
            raise InvalidStateError('This question has not started yet.')
        if player.game_id != locked_round.game_id:
            raise InvalidStateError('The player does not belong to this game.')
        if not open_question.contenders.filter(pk=player.pk).exists():
            raise InvalidStateError('This player is not eligible to answer this question.')

        clean_value = _validate_integer(value)

        now = timezone.now()
        if now >= open_question.deadline:
            raise InvalidStateError('The answer window has closed.')

        if RoundAnswer.objects.filter(round_question=open_question, player=player).exists():
            raise InvalidStateError('This player has already answered this question.')

        answer = RoundAnswer(round_question=open_question, player=player, value=clean_value, answered_at=now)
        answer.full_clean()
        answer.save()

        answered_count = RoundAnswer.objects.filter(round_question=open_question).count()
        contenders_count = open_question.contenders.count()
        if answered_count == contenders_count:
            _resolve_question(locked_round, open_question)

    return answer


def resolve_round(round_obj):
    """Explicitly try to resolve the round's current open question.

    Rejected (raises InvalidStateError) unless every contender has
    answered or the deadline has passed - this is the "explicit
    operation that may be called without a new answer" the spec asks
    for, while still refusing a premature attempt.
    """
    with transaction.atomic():
        locked_round = Round.objects.select_for_update().get(pk=round_obj.pk)
        if locked_round.status != Round.ACTIVE:
            raise InvalidStateError('Only an active round can be resolved.')

        open_question = _current_open_question(locked_round)
        if open_question is None:
            raise InvalidStateError('There is no open question to resolve.')
        if not open_question.is_started():
            raise InvalidStateError('The current question has not started yet.')

        answered_count = RoundAnswer.objects.filter(round_question=open_question).count()
        contenders_count = open_question.contenders.count()
        now = timezone.now()
        all_answered = answered_count == contenders_count
        deadline_passed = now >= open_question.deadline
        if not all_answered and not deadline_passed:
            raise InvalidStateError('The round question cannot be resolved yet.')

        _resolve_question(locked_round, open_question)

    return locked_round


def _resolve_question(locked_round, question):
    now = timezone.now()
    question.resolved_at = now
    question.save(update_fields=['resolved_at'])
    group = list(question.contenders.all())
    _attempt(locked_round, question.target_rank, group, question)


def _rank_group(source_question, players):
    """Rank `players` using only `source_question`'s own answers.

    Returns one of:
    - (player, None) if exactly one player is the clear best (or the
      sole respondent).
    - (None, tied_players) if two or more players are tied for best.
    - (None, None) if none of `players` answered `source_question`.
    """
    player_ids = {p.pk: p for p in players}
    answers = list(
        RoundAnswer.objects.filter(round_question=source_question, player_id__in=player_ids.keys())
    )
    if not answers:
        return None, None
    if len(answers) == 1:
        return player_ids[answers[0].player_id], None

    scored = sorted(
        ((answer.deviation(), answer.elapsed(), answer.player_id) for answer in answers),
        key=lambda item: (item[0], item[1]),
    )
    best_deviation, best_elapsed, _ = scored[0]
    tied_ids = [pid for deviation, elapsed, pid in scored if deviation == best_deviation and elapsed == best_elapsed]
    if len(tied_ids) == 1:
        return player_ids[tied_ids[0]], None
    return None, [player_ids[pid] for pid in tied_ids]


def _attempt(locked_round, rank, group_players, source_question):
    resolved_player, tied_players = _rank_group(source_question, group_players)

    if resolved_player is not None:
        _assign_rank(locked_round, rank, resolved_player)
        return

    if tied_players is not None:
        _spawn_followup(locked_round, rank, tied_players)
        return

    _spawn_followup(locked_round, rank, group_players)


def _assign_rank(locked_round, rank, player):
    if rank == RoundQuestion.FIRST_PLACE:
        locked_round.winner = player
    else:
        locked_round.second_place = player
    locked_round.full_clean()
    locked_round.save()

    if rank == RoundQuestion.FIRST_PLACE and locked_round.required_places == 2:
        anchor = _rank1_full_group_anchor(locked_round)
        remaining_group = [p for p in anchor.contenders.all() if p.pk != player.pk]
        _attempt(locked_round, RoundQuestion.SECOND_PLACE, remaining_group, anchor)
    else:
        _finalize_round(locked_round)


def _rank1_full_group_anchor(locked_round):
    """The most recent target_rank=1 question whose contenders are still
    the round's full original player set.

    A tie-break or no-answer redo that keeps asking the *whole* original
    group (a full-group tie, or nobody answering at all) produces the
    most reliable data to also rank the remaining players for second
    place from. A tie-break narrowed to a strict subset of the group
    does not: the players outside that subset never answered it, so it
    cannot be compared against seq1 (never compare deviations/times from
    different questions) - in that case seq1 itself (always a full-group
    question) is the answer, since nothing later narrowed-and-matched it.
    """
    original_ids = frozenset(
        locked_round.round_questions.get(sequence=1).contenders.values_list('pk', flat=True)
    )
    for candidate in locked_round.round_questions.filter(
        target_rank=RoundQuestion.FIRST_PLACE
    ).order_by('-sequence'):
        contender_ids = frozenset(candidate.contenders.values_list('pk', flat=True))
        if contender_ids == original_ids:
            return candidate
    return locked_round.round_questions.get(sequence=1)


def _spawn_followup(locked_round, rank, group_players):
    if locked_round.round_questions.count() >= Round.MAX_QUESTIONS_PER_ROUND:
        _finalize_incomplete(locked_round, Round.QUESTION_LIMIT_REACHED)
        return

    question = _pick_numeric_question(locked_round.game)
    if question is None:
        _finalize_incomplete(locked_round, Round.BANK_EXHAUSTED)
        return

    now = timezone.now()
    sequence = locked_round.round_questions.count() + 1
    round_question = RoundQuestion(
        round=locked_round,
        sequence=sequence,
        target_rank=rank,
        question=question,
        question_text=question.text,
        correct_answer=question.correct_answer,
        started_at=now,
        deadline=now + timedelta(seconds=Round.ANSWER_WINDOW_SECONDS),
    )
    round_question.full_clean()
    round_question.save()
    round_question.contenders.set(group_players)


def _finalize_incomplete(locked_round, reason):
    locked_round.incomplete_reason = reason
    locked_round.status = Round.COMPLETED
    locked_round.completed_at = timezone.now()
    locked_round.full_clean()
    locked_round.save()


def _finalize_round(locked_round):
    locked_round.status = Round.COMPLETED
    locked_round.completed_at = timezone.now()
    locked_round.full_clean()
    locked_round.save()
