from collections.abc import Iterable
from dataclasses import dataclass

from django.conf import settings
from elastic_transport import ConnectionError, ConnectionTimeout, TransportError
from elasticsearch import ApiError, Elasticsearch, helpers

from .index import INDEX_MAPPING, INDEX_SETTINGS


class SearchIndexError(Exception):
    """Stable application error for expected Elasticsearch failures."""


@dataclass(frozen=True)
class BulkResult:
    attempted: int
    indexed: int
    failed: int
    unprocessed: int


class BulkIndexError(SearchIndexError):
    """Expected bulk transport failure with sanitized observed progress."""

    def __init__(self, message: str, progress: BulkResult):
        super().__init__(message)
        self.progress = progress


class ElasticsearchGateway:
    def __init__(
        self,
        client: Elasticsearch,
        index_name: str,
        *,
        owns_client: bool = False,
    ):
        self.client = client
        self.index_name = index_name
        self.owns_client = owns_client

    def index_exists(self) -> bool:
        return bool(self._request(self.client.indices.exists, index=self.index_name))

    def create_index(self) -> bool:
        if self.index_exists():
            return False
        self._request(
            self.client.indices.create,
            index=self.index_name,
            settings=INDEX_SETTINGS,
            mappings=INDEX_MAPPING,
        )
        return True

    def replace_index(self) -> None:
        if self.index_exists():
            self._request(self.client.indices.delete, index=self.index_name)
        self._request(
            self.client.indices.create,
            index=self.index_name,
            settings=INDEX_SETTINGS,
            mappings=INDEX_MAPPING,
        )

    def bulk_index(self, documents: Iterable[tuple[str, dict]], batch_size: int) -> BulkResult:
        document_batch = list(documents)
        attempted = 0
        indexed = 0
        failed = 0

        def actions():
            nonlocal attempted
            for document_id, document in document_batch:
                attempted += 1
                yield {
                    "_op_type": "index",
                    "_index": self.index_name,
                    "_id": document_id,
                    "_source": document,
                }

        try:
            for succeeded, _item in helpers.streaming_bulk(
                self.client,
                actions(),
                chunk_size=batch_size,
                max_retries=0,
                raise_on_error=False,
                raise_on_exception=True,
            ):
                if succeeded:
                    indexed += 1
                else:
                    failed += 1
        except (ConnectionError, ConnectionTimeout) as exc:
            raise BulkIndexError(
                "Elasticsearch is unavailable.",
                progress=BulkResult(
                    attempted=attempted,
                    indexed=indexed,
                    failed=failed,
                    unprocessed=len(document_batch) - attempted,
                ),
            ) from exc
        except (ApiError, TransportError) as exc:
            raise BulkIndexError(
                "Elasticsearch request failed.",
                progress=BulkResult(
                    attempted=attempted,
                    indexed=indexed,
                    failed=failed,
                    unprocessed=len(document_batch) - attempted,
                ),
            ) from exc
        return BulkResult(
            attempted=attempted,
            indexed=indexed,
            failed=failed,
            unprocessed=len(document_batch) - attempted,
        )

    def refresh(self) -> None:
        self._request(self.client.indices.refresh, index=self.index_name)

    def search(self, request: dict):
        response = self._request(
            self.client.search,
            index=self.index_name,
            **request,
        )
        return getattr(response, "body", response)

    def close(self) -> None:
        if self.owns_client:
            self.client.close()

    @staticmethod
    def _request(operation, **kwargs):
        try:
            return operation(**kwargs)
        except (ConnectionError, ConnectionTimeout) as exc:
            raise SearchIndexError("Elasticsearch is unavailable.") from exc
        except (ApiError, TransportError) as exc:
            raise SearchIndexError("Elasticsearch request failed.") from exc


def get_gateway() -> ElasticsearchGateway:
    client = Elasticsearch(
        settings.ELASTICSEARCH_URL,
        request_timeout=settings.ELASTICSEARCH_REQUEST_TIMEOUT,
    )
    return ElasticsearchGateway(
        client=client,
        index_name=settings.ELASTICSEARCH_INDEX,
        owns_client=True,
    )
