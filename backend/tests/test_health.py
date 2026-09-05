from unittest.mock import patch

import pytest
from django.db import DatabaseError, connections
from django.urls import reverse


def test_live_health_endpoint_does_not_access_database(client):
    with patch.object(connections["default"], "cursor") as cursor:
        response = client.get(reverse("health-live"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    cursor.assert_not_called()


@pytest.mark.django_db
def test_ready_health_endpoint_when_database_is_available(client):
    response = client.get(reverse("health-ready"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_ready_health_endpoint_hides_database_error(client):
    database_error = "database credentials should not be exposed"
    with patch.object(connections["default"], "cursor", side_effect=DatabaseError(database_error)):
        response = client.get(reverse("health-ready"))

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unavailable"}
    assert database_error not in response.content.decode()
