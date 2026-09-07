from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

User = get_user_model()


class RegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True)
    email = serializers.EmailField(required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ("id", "username", "email", "password")
        read_only_fields = ("id",)

    def validate(self, attrs):
        user = User(username=attrs.get("username", ""), email=attrs.get("email", ""))
        try:
            validate_password(attrs["password"], user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class CurrentUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "email")
        read_only_fields = fields
