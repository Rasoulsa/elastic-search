from django.core.management.base import BaseCommand, CommandError

from apps.search.gateway import SearchIndexError, get_gateway


class Command(BaseCommand):
    help = "Create the versioned Elasticsearch profile index without indexing profiles."

    def handle(self, *args, **options) -> None:
        gateway = get_gateway()
        try:
            created = gateway.create_index()
        except SearchIndexError as exc:
            raise CommandError(str(exc)) from exc
        finally:
            gateway.close()
        status = "created" if created else "already existed"
        self.stdout.write(f"Profile index {status}.")
