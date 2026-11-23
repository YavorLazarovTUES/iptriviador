"""Background deadline processing for round questions (M09).

The deadline itself is data (`RoundQuestion.deadline`) and is enforced on
every answer by `games.services.submit_answer`, regardless of whether a
worker has processed it yet. These tasks only carry out the *consequences*
of a passed deadline: resolve the open question, which either completes the
round (and, for a city capture round, applies its rewards) or spawns the
next tie-break question.

Both tasks are idempotent. A question that is already resolved, a round
that is no longer active, or a duplicate delivery of the same message all
end as a no-op, and city capture rewards are guarded by
`Round.rewards_applied`, so nothing is ever granted twice.
"""
import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import Round, RoundQuestion
from .services import InvalidStateError

logger = logging.getLogger(__name__)

# Outcomes of `close_round_question_if_expired`.
CLOSED = 'closed'
NOT_YET = 'not_yet'
NOTHING_TO_DO = 'nothing_to_do'


def close_round_question_if_expired(round_question_id):
    """Resolve the given round question if it is still open and its deadline
    has passed. Returns one of `CLOSED`, `NOT_YET` or `NOTHING_TO_DO`."""
    # Imported lazily: territories.services imports games.services.
    from territories.services import resolve_city_capture_round

    from .services import resolve_round

    try:
        round_question = RoundQuestion.objects.select_related('round').get(pk=round_question_id)
    except RoundQuestion.DoesNotExist:
        return NOTHING_TO_DO

    round_obj = round_question.round
    if round_question.resolved_at is not None or not round_question.is_started():
        return NOTHING_TO_DO
    if round_obj.status != Round.ACTIVE:
        return NOTHING_TO_DO
    if timezone.now() < round_question.deadline:
        return NOT_YET

    resolver = resolve_city_capture_round if round_obj.type == Round.CITY_CAPTURE else resolve_round
    try:
        resolver(round_obj)
    except InvalidStateError:
        # Lost a race: an answer or another worker resolved it first, and
        # the question now open (if any) has its own, later deadline.
        return NOTHING_TO_DO
    return CLOSED


@shared_task(name='games.tasks.close_expired_round_question')
def close_expired_round_question(round_question_id):
    """Delayed task, queued with `eta=deadline` when the question opens.

    The eta is the earliest moment the worker may run it, not an exact one;
    if it still arrives early (e.g. clock skew between hosts), it re-queues
    itself for the deadline instead of resolving prematurely.
    """
    outcome = close_round_question_if_expired(round_question_id)
    if outcome == NOT_YET:
        deadline = RoundQuestion.objects.values_list('deadline', flat=True).get(pk=round_question_id)
        close_expired_round_question.apply_async(args=[round_question_id], eta=deadline)
    return outcome


@shared_task(name='games.tasks.close_expired_round_questions')
def close_expired_round_questions():
    """Periodic sweep: close every open round question past its deadline."""
    expired_ids = list(
        RoundQuestion.objects.filter(
            resolved_at__isnull=True,
            started_at__isnull=False,
            deadline__lte=timezone.now(),
            round__status=Round.ACTIVE,
        ).values_list('pk', flat=True)
    )
    closed = sum(1 for pk in expired_ids if close_round_question_if_expired(pk) == CLOSED)
    if closed:
        logger.info('Closed %d expired round question(s).', closed)
    return closed


def schedule_deadline_check(round_question):
    """Queue the delayed close task once the surrounding transaction commits.

    `robust=True`: if the broker is unreachable the error is logged instead
    of failing the request that opened the question - the periodic sweep
    picks the question up anyway.
    """
    pk, deadline = round_question.pk, round_question.deadline
    transaction.on_commit(
        lambda: close_expired_round_question.apply_async(args=[pk], eta=deadline),
        robust=True,
    )
