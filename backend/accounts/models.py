from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models

AVATARS = ['knight-1', 'knight-2', 'knight-3', 'knight-4']


class User(AbstractUser):
    email = models.EmailField(unique=True)


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    nickname = models.CharField(max_length=30, unique=True)
    avatar_key = models.CharField(max_length=30, default=AVATARS[0], choices=[(a, a) for a in AVATARS])
