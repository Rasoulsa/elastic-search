from django.db import DatabaseError, connections
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

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
