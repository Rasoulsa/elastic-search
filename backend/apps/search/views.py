from django.db import DatabaseError, connections
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .query import DEFAULT_PAGE_SIZE, FACET_SIZE, MAX_PAGE_SIZE, MAX_RESULT_WINDOW
from .serializers import (
    AuthenticationErrorResponseSerializer,
    ProfileSearchParametersSerializer,
    ProfileSearchResponseSerializer,
    SearchUnavailableResponseSerializer,
    SearchValidationErrorResponseSerializer,
    search_parameter_data,
)
from .services import SearchUnavailableError, search_profiles

LiveResponse = inline_serializer(
    name="HealthLiveResponse",
    fields={"status": serializers.CharField()},
)
ReadyResponse = inline_serializer(
    name="HealthReadyResponse",
    fields={
        "status": serializers.CharField(),
        "database": serializers.CharField(),
    },
)


@extend_schema(responses=LiveResponse, auth=[])
@api_view(["GET"])
@permission_classes([AllowAny])
def live(request):
    return Response({"status": "ok"})


@extend_schema(responses={200: ReadyResponse, 503: ReadyResponse}, auth=[])
@api_view(["GET"])
@permission_classes([AllowAny])
def ready(request):
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        return Response({"status": "unavailable", "database": "unavailable"}, status=503)
    return Response({"status": "ok", "database": "ok"})


FILTER_PARAMETER_DESCRIPTION = (
    "Exact normalized keyword filter. Repeat this parameter for OR semantics within this filter; "
    "different filter categories use AND semantics. Blank values are ignored."
)

SEARCH_PARAMETERS = [
    OpenApiParameter(
        name="q",
        type=OpenApiTypes.STR,
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            "Optional scalar keyword query. Provide it at most once; surrounding whitespace is "
            "ignored; maximum 500 characters."
        ),
    ),
    *[
        OpenApiParameter(
            name=name,
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
            many=True,
            description=f"{FILTER_PARAMETER_DESCRIPTION} Maximum 20 values of 200 characters each.",
        )
        for name in ("skill", "job_title", "industry", "country", "company")
    ],
    OpenApiParameter(
        name="page",
        type={"type": "integer", "minimum": 1},
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            f"Positive scalar page number; provide it at most once. Defaults to 1; page requests "
            f"must remain within the {MAX_RESULT_WINDOW}-result Elasticsearch window."
        ),
        default=1,
    ),
    OpenApiParameter(
        name="page_size",
        type={"type": "integer", "minimum": 1, "maximum": MAX_PAGE_SIZE},
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            f"Scalar results-per-page value; provide it at most once. Defaults to "
            f"{DEFAULT_PAGE_SIZE}; maximum {MAX_PAGE_SIZE}."
        ),
        default=DEFAULT_PAGE_SIZE,
    ),
]


class ProfileSearchView(APIView):
    @extend_schema(
        tags=["profiles"],
        operation_id="profile_search",
        summary="Search profiles in Elasticsearch",
        description=(
            "Returns application-owned profile results and five facets. Facets use the current "
            f"keyword and filters and return at most {FACET_SIZE} buckets each."
        ),
        parameters=SEARCH_PARAMETERS,
        responses={
            200: ProfileSearchResponseSerializer,
            400: SearchValidationErrorResponseSerializer,
            401: AuthenticationErrorResponseSerializer,
            503: OpenApiResponse(
                response=SearchUnavailableResponseSerializer,
                description="Elasticsearch or the profile index is unavailable.",
            ),
        },
    )
    def get(self, request):
        parameter_serializer = ProfileSearchParametersSerializer(
            data=search_parameter_data(request.query_params)
        )
        parameter_serializer.is_valid(raise_exception=True)
        try:
            response_data = search_profiles(parameter_serializer.to_criteria())
        except SearchUnavailableError:
            return Response(
                {
                    "code": "search_unavailable",
                    "detail": "Profile search is temporarily unavailable.",
                },
                status=503,
            )
        return Response(response_data)
