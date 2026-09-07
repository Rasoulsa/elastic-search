from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from config.settings import env_csv

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


def registration_payload(**overrides):
    payload = {
        "username": "reviewer",
        "email": "reviewer@example.com",
        "password": "ChangeThis-Test-Password-42!",
    }
    payload.update(overrides)
    return payload


def expired_token(token_class, user):
    token = token_class.for_user(user)
    token["exp"] = int((timezone.now() - timedelta(minutes=1)).timestamp())
    return str(token)


def schema_for(api_client):
    response = api_client.get(reverse("schema"), HTTP_ACCEPT="application/json")
    assert response.status_code == status.HTTP_200_OK
    return response.json()


def resolve_schema(schema, component):
    if "$ref" in component:
        prefix, name = component["$ref"].rsplit("/", maxsplit=1)
        assert prefix == "#/components/schemas"
        return schema["components"]["schemas"][name]
    return component


def response_schema(schema, path, response_status, method="post"):
    response = schema["paths"][path][method]["responses"][str(response_status)]
    content = response["content"]["application/json"]
    return resolve_schema(schema, content["schema"])


def visible_properties(schema_definition):
    return {
        name
        for name, definition in schema_definition.get("properties", {}).items()
        if not definition.get("writeOnly", False)
    }


def input_properties(schema_definition):
    return {
        name
        for name, definition in schema_definition.get("properties", {}).items()
        if not definition.get("readOnly", False)
    }


@pytest.mark.django_db
def test_registration_returns_public_user_fields_and_hashes_password(api_client):
    password = registration_payload()["password"]
    response = api_client.post(reverse("auth-register"), registration_payload(), format="json")

    assert response.status_code == 201
    assert set(response.json()) == {"id", "username", "email"}
    assert response.json()["username"] == "reviewer"
    assert response.json()["email"] == "reviewer@example.com"
    user = User.objects.get(username="reviewer")
    assert user.check_password(password)
    assert user.password != password
    assert "password" not in response.content.decode().lower()


@pytest.mark.django_db
def test_registration_rejects_duplicate_username(api_client):
    User.objects.create_user(username="reviewer", password="Existing-Password-42!")

    response = api_client.post(reverse("auth-register"), registration_payload(), format="json")

    assert response.status_code == 400
    assert "username" in response.json()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("payload", "field"),
    [
        (
            {
                "username": "reviewer",
                "email": "not-an-email",
                "password": registration_payload()["password"],
            },
            "email",
        ),
        (
            {"email": "reviewer@example.com", "password": registration_payload()["password"]},
            "username",
        ),
        ({"username": "reviewer", "email": "reviewer@example.com"}, "password"),
    ],
)
def test_registration_rejects_invalid_input(api_client, payload, field):
    response = api_client.post(reverse("auth-register"), payload, format="json")

    assert response.status_code == 400
    assert field in response.json()


@pytest.mark.django_db
def test_registration_rejects_weak_password(api_client):
    response = api_client.post(
        reverse("auth-register"), registration_payload(password="123"), format="json"
    )

    assert response.status_code == 400
    assert "password" in response.json()


@pytest.mark.django_db
def test_valid_credentials_return_access_and_refresh_tokens(api_client):
    User.objects.create_user(username="reviewer", password=registration_payload()["password"])

    response = api_client.post(
        reverse("auth-token"),
        {"username": "reviewer", "password": registration_payload()["password"]},
        format="json",
    )

    assert response.status_code == 200
    assert set(response.json()) == {"access", "refresh"}
    assert all(response.json().values())


@pytest.mark.django_db
def test_invalid_credentials_are_rejected(api_client):
    User.objects.create_user(username="reviewer", password=registration_payload()["password"])

    response = api_client.post(
        reverse("auth-token"),
        {"username": "reviewer", "password": "wrong-password"},
        format="json",
    )

    assert response.status_code == 401
    assert "detail" in response.json()


@pytest.mark.django_db
def test_refresh_token_returns_access_token(api_client):
    User.objects.create_user(username="reviewer", password=registration_payload()["password"])
    token_response = api_client.post(
        reverse("auth-token"),
        {"username": "reviewer", "password": registration_payload()["password"]},
        format="json",
    )

    response = api_client.post(
        reverse("auth-token-refresh"),
        {"refresh": token_response.json()["refresh"]},
        format="json",
    )

    assert response.status_code == 200
    assert set(response.json()) == {"access"}
    assert response.json()["access"]


@pytest.mark.django_db
def test_expired_access_token_is_rejected_without_token_details(api_client):
    user = User.objects.create_user(
        username="reviewer", password=registration_payload()["password"]
    )
    token = expired_token(AccessToken, user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    response = api_client.get(reverse("auth-me"))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json().get("detail")
    assert token not in response.content.decode()


@pytest.mark.django_db
def test_expired_refresh_token_is_rejected_without_token_details(api_client):
    user = User.objects.create_user(
        username="reviewer", password=registration_payload()["password"]
    )
    token = expired_token(RefreshToken, user)

    response = api_client.post(
        reverse("auth-token-refresh"),
        {"refresh": token},
        format="json",
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json().get("detail")
    assert token not in response.content.decode()


@pytest.mark.django_db
def test_invalid_refresh_token_is_rejected(api_client):
    response = api_client.post(reverse("auth-token-refresh"), {"refresh": "invalid"}, format="json")

    assert response.status_code == 401
    assert "detail" in response.json()


@pytest.mark.django_db
def test_current_user_returns_only_public_fields(api_client):
    password = registration_payload()["password"]
    user = User.objects.create_user(
        username="reviewer", email="reviewer@example.com", password=password
    )
    token_response = api_client.post(
        reverse("auth-token"), {"username": user.username, "password": password}, format="json"
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_response.json()['access']}")

    response = api_client.get(reverse("auth-me"))

    assert response.status_code == 200
    assert response.json() == {
        "id": user.id,
        "username": "reviewer",
        "email": "reviewer@example.com",
    }
    assert "password" not in response.content.decode().lower()


@pytest.mark.parametrize("authorization", [None, "Bearer invalid-token"])
def test_current_user_requires_a_valid_bearer_token(api_client, authorization):
    if authorization:
        api_client.credentials(HTTP_AUTHORIZATION=authorization)

    response = api_client.get(reverse("auth-me"))

    assert response.status_code == 401
    assert "password" not in response.content.decode().lower()


@pytest.mark.django_db
def test_health_endpoints_remain_public(api_client):
    assert api_client.get(reverse("health-live")).status_code == 200
    assert api_client.get(reverse("health-ready")).status_code == 200


def test_schema_and_swagger_remain_public(api_client):
    schema_response = api_client.get(reverse("schema"), HTTP_ACCEPT="application/json")
    docs_response = api_client.get(reverse("swagger-ui"))

    assert schema_response.status_code == 200
    assert docs_response.status_code == 200
    assert "SwaggerUIBundle" in docs_response.content.decode()


def test_cors_allows_configured_origin_and_rejects_unconfigured_origin(api_client):
    allowed = api_client.get(reverse("health-live"), HTTP_ORIGIN="http://localhost:5173")
    rejected = api_client.get(reverse("health-live"), HTTP_ORIGIN="http://evil.example")

    assert allowed.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert "Access-Control-Allow-Origin" not in rejected.headers


def test_schema_contains_authentication_endpoints_and_bearer_scheme(api_client):
    schema = schema_for(api_client)

    assert "/api/v1/auth/register/" in schema["paths"]
    assert "/api/v1/auth/token/" in schema["paths"]
    assert "/api/v1/auth/token/refresh/" in schema["paths"]
    assert "/api/v1/auth/me/" in schema["paths"]

    bearer_schemes = {
        name
        for name, scheme in schema["components"]["securitySchemes"].items()
        if scheme.get("type") == "http" and scheme.get("scheme") == "bearer"
    }
    assert bearer_schemes
    current_user_security = schema["paths"]["/api/v1/auth/me/"]["get"]["security"]
    assert any(bearer_schemes.intersection(requirement) for requirement in current_user_security)


def test_schema_marks_public_routes_and_protected_current_user(api_client):
    schema = schema_for(api_client)
    public_operations = {
        "/health/live/": "get",
        "/health/ready/": "get",
        "/api/v1/auth/register/": "post",
        "/api/v1/auth/token/": "post",
        "/api/v1/auth/token/refresh/": "post",
    }

    for path, method in public_operations.items():
        assert schema["paths"][path][method].get("security", []) in ([], [{}])

    assert schema["paths"]["/api/v1/auth/me/"]["get"].get("security")


def test_schema_documents_public_response_fields_and_token_contract(api_client):
    schema = schema_for(api_client)
    registration_operation = schema["paths"]["/api/v1/auth/register/"]["post"]
    registration_request = registration_operation["requestBody"]["content"]["application/json"][
        "schema"
    ]
    registration_request = resolve_schema(schema, registration_request)

    assert registration_request["properties"]["password"]["writeOnly"] is True
    assert "password" in registration_request["required"]
    assert visible_properties(response_schema(schema, "/api/v1/auth/register/", 201)) == {
        "id",
        "username",
        "email",
    }
    assert visible_properties(schema["components"]["schemas"]["CurrentUser"]) == {
        "id",
        "username",
        "email",
    }
    assert visible_properties(response_schema(schema, "/api/v1/auth/me/", 200, method="get")) == {
        "id",
        "username",
        "email",
    }

    token_operation = schema["paths"]["/api/v1/auth/token/"]["post"]
    token_request = token_operation["requestBody"]["content"]["application/json"]["schema"]
    token_schema = response_schema(schema, "/api/v1/auth/token/", 200)
    refresh_schema = response_schema(schema, "/api/v1/auth/token/refresh/", 200)
    refresh_operation = schema["paths"]["/api/v1/auth/token/refresh/"]["post"]
    refresh_request = refresh_operation["requestBody"]["content"]["application/json"]["schema"]

    assert input_properties(resolve_schema(schema, token_request)) == {"username", "password"}
    assert visible_properties(token_schema) == {"access", "refresh"}
    assert visible_properties(refresh_schema) == {"access"}
    assert input_properties(resolve_schema(schema, refresh_request)) == {"refresh"}


def test_cors_configuration_trims_whitespace_and_ignores_empty_origins(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", " http://one.example, ,http://two.example ")

    assert env_csv("CORS_ALLOWED_ORIGINS", "") == [
        "http://one.example",
        "http://two.example",
    ]


def test_cors_does_not_allow_credentials_or_wildcard_origins():
    assert settings.CORS_ALLOW_CREDENTIALS is False
    assert "*" not in settings.CORS_ALLOWED_ORIGINS


def test_cors_preflight_allows_configured_origin_and_rejects_other_origins(api_client):
    allowed = api_client.options(
        reverse("health-live"),
        HTTP_ORIGIN="http://localhost:5173",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
    )
    rejected = api_client.options(
        reverse("health-live"),
        HTTP_ORIGIN="http://evil.example",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
    )

    assert allowed.status_code == status.HTTP_200_OK
    assert allowed.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert rejected.status_code == status.HTTP_200_OK
    assert "Access-Control-Allow-Origin" not in rejected.headers
