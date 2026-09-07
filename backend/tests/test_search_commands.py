from io import StringIO
from unittest.mock import Mock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.profiles.models import Profile
from apps.search.gateway import (
    BulkIndexError,
    BulkResult,
    ElasticsearchGateway,
    SearchIndexError,
)
from apps.search.management.commands.rebuild_profile_index import (
    DEFAULT_BATCH_SIZE,
    MAX_BATCH_SIZE,
)


class RecordingGateway:
    def __init__(self, *, failure_at=None, unavailable=False, bulk_error=None):
        self.documents = {"stale": {"profile_id": "stale"}}
        self.failure_at = failure_at
        self.unavailable = unavailable
        self.bulk_error = bulk_error
        self.replacements = 0
        self.refreshes = 0
        self.closes = 0
        self.batch_sizes = []
        self.requested_batch_sizes = []

    def replace_index(self):
        if self.unavailable:
            raise SearchIndexError("Elasticsearch is unavailable.")
        self.replacements += 1
        self.documents = {}

    def bulk_index(self, documents, batch_size):
        documents = list(documents)
        self.batch_sizes.append(len(documents))
        self.requested_batch_sizes.append(batch_size)
        if self.bulk_error is not None:
            raise self.bulk_error
        indexed = 0
        failed = 0
        for document_id, document in documents:
            if self.failure_at == document_id:
                failed += 1
            else:
                self.documents[document_id] = document
                indexed += 1
        return BulkResult(
            attempted=len(documents),
            indexed=indexed,
            failed=failed,
            unprocessed=0,
        )

    def refresh(self):
        self.refreshes += 1

    def close(self):
        self.closes += 1


@pytest.mark.parametrize(
    ("created", "message"),
    [(True, "Profile index created."), (False, "Profile index already existed.")],
)
def test_create_profile_index_reports_created_or_existing(created, message):
    gateway = Mock()
    gateway.create_index.return_value = created
    output = StringIO()

    with patch(
        "apps.search.management.commands.create_profile_index.get_gateway",
        return_value=gateway,
    ):
        call_command("create_profile_index", stdout=output)

    assert output.getvalue().strip() == message
    gateway.create_index.assert_called_once_with()
    gateway.close.assert_called_once_with()


def test_create_profile_index_exits_nonzero_when_elasticsearch_is_unavailable():
    gateway = Mock()
    gateway.create_index.side_effect = SearchIndexError("Elasticsearch is unavailable.")

    with (
        patch(
            "apps.search.management.commands.create_profile_index.get_gateway",
            return_value=gateway,
        ),
        pytest.raises(CommandError, match="Elasticsearch is unavailable"),
    ):
        call_command("create_profile_index")

    gateway.close.assert_called_once_with()


@pytest.mark.parametrize("batch_size", [0, -1, MAX_BATCH_SIZE + 1])
def test_rebuild_rejects_out_of_range_batch_size_before_creating_gateway(batch_size):
    with (
        patch("apps.search.management.commands.rebuild_profile_index.get_gateway") as get_gateway,
        pytest.raises(CommandError, match=f"between 1 and {MAX_BATCH_SIZE}"),
    ):
        call_command("rebuild_profile_index", batch_size=batch_size)

    get_gateway.assert_not_called()


@pytest.mark.django_db
def test_rebuild_accepts_maximum_batch_size():
    Profile.objects.create(public_identifier="maximum-batch", full_name="Maximum")
    gateway = RecordingGateway()

    with patch(
        "apps.search.management.commands.rebuild_profile_index.get_gateway",
        return_value=gateway,
    ):
        call_command("rebuild_profile_index", batch_size=MAX_BATCH_SIZE)

    assert gateway.replacements == 1
    assert gateway.requested_batch_sizes == [MAX_BATCH_SIZE]
    assert gateway.closes == 1


@pytest.mark.django_db
def test_rebuild_uses_the_normal_default_batch_size():
    Profile.objects.create(public_identifier="default-batch", full_name="Default")
    gateway = RecordingGateway()

    with patch(
        "apps.search.management.commands.rebuild_profile_index.get_gateway",
        return_value=gateway,
    ):
        call_command("rebuild_profile_index")

    assert gateway.requested_batch_sizes == [DEFAULT_BATCH_SIZE]
    assert gateway.closes == 1


@pytest.mark.django_db
def test_successful_rebuild_is_bounded_repeatable_and_removes_stale_documents():
    profiles = [
        Profile.objects.create(public_identifier=f"profile-{index}", full_name=f"Profile {index}")
        for index in range(3)
    ]
    gateway = RecordingGateway()

    with patch(
        "apps.search.management.commands.rebuild_profile_index.get_gateway",
        return_value=gateway,
    ):
        first_output = StringIO()
        with CaptureQueriesContext(connection) as queries:
            call_command("rebuild_profile_index", batch_size=2, stdout=first_output)
        first_ids = set(gateway.documents)
        second_output = StringIO()
        call_command("rebuild_profile_index", batch_size=2, stdout=second_output)

    expected_ids = {str(profile.pk) for profile in profiles}
    assert first_ids == expected_ids
    assert set(gateway.documents) == expected_ids
    assert "stale" not in gateway.documents
    assert gateway.replacements == 2
    assert gateway.refreshes == 2
    assert gateway.closes == 2
    assert gateway.batch_sizes == [2, 1, 2, 1]
    assert len(queries) <= 7
    expected_summary = "Profile index rebuild: attempted=3 indexed=3 failed=0 unprocessed=0"
    assert first_output.getvalue().strip() == expected_summary
    assert second_output.getvalue().strip() == expected_summary


@pytest.mark.django_db
def test_rebuild_reports_truthful_partial_failure_counts_and_exits_nonzero():
    first = Profile.objects.create(public_identifier="first", full_name="First")
    second = Profile.objects.create(public_identifier="second", full_name="Second")
    gateway = RecordingGateway(failure_at=str(second.pk))
    output = StringIO()

    with (
        patch(
            "apps.search.management.commands.rebuild_profile_index.get_gateway",
            return_value=gateway,
        ),
        pytest.raises(CommandError, match="bulk document failures"),
    ):
        call_command("rebuild_profile_index", stdout=output)

    assert set(gateway.documents) == {str(first.pk)}
    assert gateway.refreshes == 0
    assert gateway.closes == 1
    assert output.getvalue().strip() == (
        "Profile index rebuild: attempted=2 indexed=1 failed=1 unprocessed=0"
    )


@pytest.mark.django_db
def test_rebuild_exits_nonzero_when_elasticsearch_is_unavailable():
    gateway = RecordingGateway(unavailable=True)
    output = StringIO()

    with (
        patch(
            "apps.search.management.commands.rebuild_profile_index.get_gateway",
            return_value=gateway,
        ),
        pytest.raises(CommandError, match="Elasticsearch is unavailable"),
    ):
        call_command("rebuild_profile_index", stdout=output)

    assert gateway.closes == 1
    assert output.getvalue().strip() == (
        "Profile index rebuild: attempted=0 indexed=0 failed=0 unprocessed=unknown"
    )


@pytest.mark.django_db
def test_rebuild_preserves_bulk_progress_and_exits_nonzero_on_transport_failure():
    Profile.objects.create(public_identifier="first", full_name="First")
    Profile.objects.create(public_identifier="second", full_name="Second")
    gateway = RecordingGateway(
        bulk_error=BulkIndexError(
            "Elasticsearch is unavailable.",
            progress=BulkResult(
                attempted=2,
                indexed=1,
                failed=0,
                unprocessed=0,
            ),
        )
    )
    output = StringIO()

    with (
        patch(
            "apps.search.management.commands.rebuild_profile_index.get_gateway",
            return_value=gateway,
        ),
        pytest.raises(CommandError, match="Elasticsearch is unavailable"),
    ):
        call_command("rebuild_profile_index", stdout=output)

    assert gateway.closes == 1
    assert output.getvalue().strip() == (
        "Profile index rebuild: attempted=2 indexed=1 failed=0 unprocessed=unknown"
    )


@pytest.mark.django_db
def test_rebuild_without_an_existing_index_creates_indexes_and_closes_client():
    profile = Profile.objects.create(public_identifier="new-index", full_name="New Index")
    client = Mock()
    client.indices.exists.return_value = False
    indexed_ids = []

    def streaming_bulk(_client, actions, **_kwargs):
        for action in actions:
            indexed_ids.append(action["_id"])
            yield True, {"index": {"status": 201}}

    gateway = ElasticsearchGateway(
        client,
        "linkedin_profiles_v1",
        owns_client=True,
    )
    output = StringIO()

    with (
        patch(
            "apps.search.management.commands.rebuild_profile_index.get_gateway",
            return_value=gateway,
        ),
        patch("apps.search.gateway.helpers.streaming_bulk", side_effect=streaming_bulk),
    ):
        call_command("rebuild_profile_index", stdout=output)

    client.indices.delete.assert_not_called()
    client.indices.create.assert_called_once()
    assert indexed_ids == [str(profile.pk)]
    assert output.getvalue().strip() == (
        "Profile index rebuild: attempted=1 indexed=1 failed=0 unprocessed=0"
    )
    client.close.assert_called_once_with()
