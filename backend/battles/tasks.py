"""Background deadline processing for battle questions (M09).

Same contract as `games.tasks`: the deadline is enforced on every answer by
`battles.services`, and these tasks only process what follows once it has
passed - resolve the open question, and if that completes the battle, apply
its result. Re-running a task never changes the outcome: resolved questions
and finished battles are skipped, and `apply_battle_result` is guarded by
`Battle.rewards_applied`, so points are never granted twice.
"""
import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from config.celery import publish_quickly
from games.services import InvalidStateError

from .models import Battle, BattleQuestion

logger = logging.getLogger(__name__)

CLOSED = 'closed'
NOT_YET = 'not_yet'
NOTHING_TO_DO = 'nothing_to_do'


def close_battle_question_if_expired(battle_question_id):
    """Resolve the given battle question if it is still open and its deadline
    has passed; apply the battle's result if that completed it. Returns one
    of `CLOSED`, `NOT_YET` or `NOTHING_TO_DO`.

    Both steps share one transaction: if the second one fails, the question
    stays open, so a retry or the sweep does all of it again. Committed
    separately, a crash in between would leave a completed battle that no
    task looks at any more, and its rewards would be lost.
    """
    from .services import apply_battle_result, resolve_battle

    try:
        battle_question = BattleQuestion.objects.select_related('battle').get(pk=battle_question_id)
    except BattleQuestion.DoesNotExist:
        return NOTHING_TO_DO

    battle = battle_question.battle
    if battle_question.resolved_at is not None or not battle_question.is_started():
        return NOTHING_TO_DO
    if battle.status != Battle.ACTIVE:
        return NOTHING_TO_DO
    if timezone.now() < battle_question.deadline:
        return NOT_YET

    try:
        with transaction.atomic():
            battle = resolve_battle(battle)
            if battle.status == Battle.COMPLETED:
                try:
                    apply_battle_result(battle)
                except InvalidStateError as exc:
                    # The territory changed hands in a concurrent battle; the
                    # outcome stays recorded, only the reward step is refused
                    # (and rolled back to its own savepoint).
                    logger.warning('Battle %s completed but its result was not applied: %s', battle.pk, exc)
    except InvalidStateError:
        # Lost a race: an answer or another worker resolved it first.
        return NOTHING_TO_DO
    return CLOSED


@shared_task(name='battles.tasks.close_expired_battle_question')
def close_expired_battle_question(battle_question_id):
    """Delayed task, queued with `eta=deadline` when the question opens; an
    early delivery re-queues itself for the deadline."""
    outcome = close_battle_question_if_expired(battle_question_id)
    if outcome == NOT_YET:
        deadline = BattleQuestion.objects.values_list('deadline', flat=True).get(pk=battle_question_id)
        close_expired_battle_question.apply_async(args=[battle_question_id], eta=deadline)
    return outcome


@shared_task(name='battles.tasks.close_expired_battle_questions')
def close_expired_battle_questions():
    """Periodic sweep: close every open battle question past its deadline.

    A question that fails is logged and left open for the next sweep; it
    must not keep the questions behind it from being closed.
    """
    expired_ids = list(
        BattleQuestion.objects.filter(
            resolved_at__isnull=True,
            started_at__isnull=False,
            deadline__lte=timezone.now(),
            battle__status=Battle.ACTIVE,
        ).values_list('pk', flat=True)
    )
    closed = 0
    for pk in expired_ids:
        try:
            closed += close_battle_question_if_expired(pk) == CLOSED
        except Exception:
            logger.exception('Could not close expired battle question %s.', pk)
    if closed:
        logger.info('Closed %d expired battle question(s).', closed)
    return closed


def schedule_deadline_check(battle_question):
    """Queue the delayed close task after commit; a broker error is logged,
    not raised, since the periodic sweep covers the question anyway."""
    pk, deadline = battle_question.pk, battle_question.deadline
    transaction.on_commit(
        lambda: publish_quickly(close_expired_battle_question, args=[pk], eta=deadline),
        robust=True,
    )
