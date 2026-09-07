from django.urls import path

from .views import (
    CurrentUserView,
    PublicTokenObtainPairView,
    PublicTokenRefreshView,
    RegistrationView,
)

urlpatterns = [
    path("register/", RegistrationView.as_view(), name="auth-register"),
    path("token/", PublicTokenObtainPairView.as_view(), name="auth-token"),
    path("token/refresh/", PublicTokenRefreshView.as_view(), name="auth-token-refresh"),
    path("me/", CurrentUserView.as_view(), name="auth-me"),
]
