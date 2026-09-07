from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import pytest
from elastic_transport import ConnectionError

from apps.search.gateway import (
    BulkIndexError,
    BulkResult,
    ElasticsearchGateway,
    SearchIndexError,
)
from apps.search.index import INDEX_MAPPING, INDEX_SETTINGS


def test_gateway_creates_the_explicit_index_when_absent():
    indices = Mock()
    indices.exists.return_value = False
    gateway = ElasticsearchGateway(SimpleNamespace(indices=indices), "linkedin_profiles_v1")

    assert gateway.create_index() is True
    indices.create.assert_called_once_with(
        index="linkedin_profiles_v1",
        settings=INDEX_SETTINGS,
        mappings=INDEX_MAPPING,
    )


def test_gateway_does_not_create_an_existing_index():
    indices = Mock()
    indices.exists.return_value = True
    gateway = ElasticsearchGateway(SimpleNamespace(indices=indices), "linkedin_profiles_v1")

    assert gateway.create_index() is False
    indices.create.assert_not_called()


def test_gateway_replacement_deletes_the_existing_index_before_recreation():
    indices = Mock()
    indices.exists.return_value = True
    gateway = ElasticsearchGateway(SimpleNamespace(indices=indices), "linkedin_profiles_v1")

    gateway.replace_index()

    assert indices.method_calls == [
        call.exists(index="linkedin_profiles_v1"),
        call.delete(index="linkedin_profiles_v1"),
        call.create(
            index="linkedin_profiles_v1",
            settings=INDEX_SETTINGS,
            mappings=INDEX_MAPPING,
        ),
    ]


def test_gateway_counts_bulk_item_results_without_exposing_error_documents():
    gateway = ElasticsearchGateway(Mock(), "linkedin_profiles_v1")

    def streaming_bulk(_client, actions, **_kwargs):
        actions = iter(actions)
        next(actions)
        yield True, {"index": {"_id": "1", "status": 201}}
        next(actions)
        yield False, {"index": {"_id": "2", "status": 400, "error": {"reason": "private"}}}

    with patch("apps.search.gateway.helpers.streaming_bulk", side_effect=streaming_bulk):
        result = gateway.bulk_index(
            [("1", {"profile_id": "1"}), ("2", {"profile_id": "2"})],
            batch_size=100,
        )

    assert result == BulkResult(attempted=2, indexed=1, failed=1, unprocessed=0)
    assert not hasattr(result, "errors")


def test_gateway_preserves_success_before_transport_failure():
    gateway = ElasticsearchGateway(Mock(), "linkedin_profiles_v1")

    def streaming_bulk(_client, actions, **_kwargs):
        actions = iter(actions)
        next(actions)
        yield True, {"index": {"status": 201}}
        next(actions)
        raise ConnectionError("connection failed")

    with (
        patch("apps.search.gateway.helpers.streaming_bulk", side_effect=streaming_bulk),
        pytest.raises(BulkIndexError, match="Elasticsearch is unavailable") as error,
    ):
        gateway.bulk_index(
            [("1", {"profile_id": "1"}), ("2", {"profile_id": "2"})],
            batch_size=100,
        )

    assert error.value.progress == BulkResult(
        attempted=2,
        indexed=1,
        failed=0,
        unprocessed=0,
    )


def test_gateway_reports_transport_failure_before_any_confirmed_item():
    gateway = ElasticsearchGateway(Mock(), "linkedin_profiles_v1")

    def streaming_bulk(_client, actions, **_kwargs):
        next(iter(actions))
        raise ConnectionError("connection failed")
        yield

    with (
        patch("apps.search.gateway.helpers.streaming_bulk", side_effect=streaming_bulk),
        pytest.raises(BulkIndexError) as error,
    ):
        gateway.bulk_index(
            [("1", {"profile_id": "1"}), ("2", {"profile_id": "2"})],
            batch_size=100,
        )

    assert error.value.progress == BulkResult(
        attempted=1,
        indexed=0,
        failed=0,
        unprocessed=1,
    )


def test_gateway_preserves_mixed_item_results_before_transport_failure():
    gateway = ElasticsearchGateway(Mock(), "linkedin_profiles_v1")

    def streaming_bulk(_client, actions, **_kwargs):
        actions = iter(actions)
        next(actions)
        yield True, {"index": {"status": 201}}
        next(actions)
        yield False, {"index": {"status": 400}}
        next(actions)
        raise ConnectionError("connection failed")

    with (
        patch("apps.search.gateway.helpers.streaming_bulk", side_effect=streaming_bulk),
        pytest.raises(BulkIndexError) as error,
    ):
        gateway.bulk_index(
            [
                ("1", {"profile_id": "1"}),
                ("2", {"profile_id": "2"}),
                ("3", {"profile_id": "3"}),
            ],
            batch_size=100,
        )

    assert error.value.progress == BulkResult(
        attempted=3,
        indexed=1,
        failed=1,
        unprocessed=0,
    )


def test_gateway_translates_connection_errors_to_a_stable_error():
    indices = Mock()
    indices.exists.side_effect = ConnectionError("connection failed")
    gateway = ElasticsearchGateway(SimpleNamespace(indices=indices), "linkedin_profiles_v1")

    with pytest.raises(SearchIndexError, match="^Elasticsearch is unavailable\\.$"):
        gateway.index_exists()


def test_gateway_closes_only_a_client_it_owns():
    external_client = Mock()
    owned_client = Mock()

    ElasticsearchGateway(external_client, "index").close()
    ElasticsearchGateway(owned_client, "index", owns_client=True).close()

    external_client.close.assert_not_called()
    owned_client.close.assert_called_once_with()
