from django.core.exceptions import ValidationError
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .waiting_room import AlreadyWaiting, form_game, join_waiting_room, leave_waiting_room


@api_view(['POST'])
def join(request):
    try:
        join_waiting_room(request.user)
    except AlreadyWaiting:
        return Response({'error': 'Already waiting.'}, status=409)
    except ValidationError:
        return Response({'error': 'Already in a game.'}, status=400)
    game = form_game()
    return Response({'game_id': game.pk if game else None}, status=201)


@api_view(['POST'])
def leave(request):
    if not leave_waiting_room(request.user):
        return Response({'error': 'Not waiting.'}, status=404)
    return Response(status=204)
