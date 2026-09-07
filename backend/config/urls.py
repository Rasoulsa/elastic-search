from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.permissions import AllowAny


class PublicSchemaView(SpectacularAPIView):
    permission_classes = [AllowAny]


class PublicSwaggerView(SpectacularSwaggerView):
    permission_classes = [AllowAny]


urlpatterns = [
    path("health/", include("apps.search.urls")),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/schema/", PublicSchemaView.as_view(), name="schema"),
    path("api/docs/", PublicSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
