from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .serializers import CurrentUserSerializer, RegistrationSerializer


class RegistrationView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Authentication"],
        summary="Register a user",
        auth=[],
        request=RegistrationSerializer,
        responses={201: RegistrationSerializer},
    )
    def post(self, request):
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(RegistrationSerializer(user).data, status=201)


class PublicTokenObtainPairView(TokenObtainPairView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Authentication"],
        summary="Obtain access and refresh tokens",
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class PublicTokenRefreshView(TokenRefreshView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Authentication"],
        summary="Refresh an access token",
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class CurrentUserView(APIView):
    @extend_schema(
        tags=["Authentication"],
        summary="Get the current user",
        responses=CurrentUserSerializer,
    )
    def get(self, request):
        return Response(CurrentUserSerializer(request.user).data)
