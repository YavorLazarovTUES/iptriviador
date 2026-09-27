from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from .models import Profile


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ['nickname', 'avatar_key']


class UserSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True)

    class Meta:
        model = get_user_model()
        fields = ['id', 'username', 'email', 'profile']


class RegisterSerializer(UserSerializer):
    nickname = serializers.CharField(max_length=30, write_only=True, validators=[UniqueValidator(Profile.objects.all())])
    password = serializers.CharField(write_only=True)
    password_confirm = serializers.CharField(write_only=True)

    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + ['nickname', 'password', 'password_confirm']

    def validate(self, data):
        if data['password'] != data.pop('password_confirm'):
            raise serializers.ValidationError({'password_confirm': ['Passwords do not match.']})
        return data

    @transaction.atomic
    def create(self, data):
        nickname = data.pop('nickname')
        user = get_user_model().objects.create_user(**data)
        Profile.objects.create(user=user, nickname=nickname)
        return user
