from django.contrib.auth import authenticate, login, logout
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .serializers import ProfileSerializer, RegisterSerializer, UserSerializer


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is not None:
        response.data = {'errors': response.data}
    return response


@ensure_csrf_cookie
@api_view(['GET'])
@permission_classes([AllowAny])
def csrf(request):
    return Response(status=204)


@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = serializer.save()
    login(request, user)
    return Response(UserSerializer(user).data, status=201)


@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    user = authenticate(request, username=request.data.get('username'), password=request.data.get('password'))
    if user is None:
        raise ValidationError({'non_field_errors': ['Invalid username or password.']})
    login(request, user)
    return Response(UserSerializer(user).data)


@api_view(['POST'])
def logout_view(request):
    logout(request)
    return Response(status=204)


@api_view(['GET', 'PATCH'])
def me(request):
    if request.method == 'PATCH':
        serializer = ProfileSerializer(request.user.profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
    return Response(UserSerializer(request.user).data)
