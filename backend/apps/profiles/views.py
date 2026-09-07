from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.search.serializers import (
    AuthenticationErrorResponseSerializer,
    NotFoundResponseSerializer,
)

from .models import Education, Experience, Profile, Skill
from .serializers import ProfileDetailSerializer


class ProfileDetailView(APIView):
    @extend_schema(
        tags=["profiles"],
        operation_id="profile_detail",
        summary="Retrieve a profile from PostgreSQL",
        description=(
            "Returns whitelisted public profile fields from PostgreSQL, the canonical source of "
            "truth. This endpoint does not require Elasticsearch."
        ),
        responses={
            200: ProfileDetailSerializer,
            401: AuthenticationErrorResponseSerializer,
            404: OpenApiResponse(
                response=NotFoundResponseSerializer,
                description="No profile exists with this id.",
            ),
        },
    )
    def get(self, request, pk: int):
        queryset = Profile.objects.prefetch_related(
            Prefetch("skills", queryset=Skill.objects.order_by("name", "pk")),
            Prefetch(
                "experiences",
                queryset=Experience.objects.order_by("source_order", "pk"),
            ),
            Prefetch(
                "educations",
                queryset=Education.objects.order_by("source_order", "pk"),
            ),
        )
        profile = get_object_or_404(queryset, pk=pk)
        return Response(ProfileDetailSerializer(profile).data)
