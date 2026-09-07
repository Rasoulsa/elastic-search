import argparse

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Prefetch

from apps.profiles.models import Education, Experience, Profile, Skill
from apps.search.documents import profile_document_id, project_profile
from apps.search.gateway import BulkIndexError, SearchIndexError, get_gateway

DEFAULT_BATCH_SIZE = 500
MAX_BATCH_SIZE = 1000


def positive_integer(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= MAX_BATCH_SIZE:
        raise argparse.ArgumentTypeError(f"batch size must be between 1 and {MAX_BATCH_SIZE}")
    return parsed


class Command(BaseCommand):
    help = "Replace and rebuild the complete profile index from PostgreSQL."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--batch-size",
            type=positive_integer,
            default=DEFAULT_BATCH_SIZE,
        )

    def handle(self, *args, **options) -> None:
        try:
            batch_size = positive_integer(options["batch_size"])
        except (argparse.ArgumentTypeError, TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        gateway = get_gateway()
        attempted = 0
        indexed = 0
        failed = 0
        completed = False
        try:
            gateway.replace_index()
            for batch in self._profile_batches(batch_size):
                documents = [
                    (profile_document_id(profile), project_profile(profile)) for profile in batch
                ]
                result = gateway.bulk_index(documents, batch_size=batch_size)
                attempted += result.attempted
                indexed += result.indexed
                failed += result.failed
            completed = True
            if failed == 0:
                gateway.refresh()
        except BulkIndexError as exc:
            attempted += exc.progress.attempted
            indexed += exc.progress.indexed
            failed += exc.progress.failed
            self._write_summary(attempted, indexed, failed, unprocessed=None)
            raise CommandError(str(exc)) from exc
        except SearchIndexError as exc:
            self._write_summary(
                attempted,
                indexed,
                failed,
                unprocessed=0 if completed else None,
            )
            raise CommandError(str(exc)) from exc
        finally:
            gateway.close()

        self._write_summary(attempted, indexed, failed, unprocessed=0)
        if failed:
            raise CommandError("Profile index rebuild had bulk document failures.")

    def _profile_batches(self, batch_size):
        queryset = Profile.objects.order_by("pk").prefetch_related(
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
        batch = []
        for profile in queryset.iterator(chunk_size=batch_size):
            batch.append(profile)
            if len(batch) == batch_size:
                yield batch
                batch = []
        if batch:
            yield batch

    def _write_summary(self, attempted, indexed, failed, unprocessed) -> None:
        unprocessed_value = "unknown" if unprocessed is None else str(unprocessed)
        self.stdout.write(
            "Profile index rebuild: "
            f"attempted={attempted} indexed={indexed} failed={failed} "
            f"unprocessed={unprocessed_value}"
        )
