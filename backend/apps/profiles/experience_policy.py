"""Deterministic selection of the experience shown as current."""

from collections.abc import Iterable, Mapping


def _text(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _source_name(value: object) -> str:
    if isinstance(value, Mapping):
        value = value.get("name")
    return _text(value)


def _source_is_valid(item: object) -> bool:
    return (
        isinstance(item, Mapping)
        and bool(_source_name(item.get("title")))
        and bool(_source_name(item.get("company")))
    )


def _source_is_open(item: Mapping) -> bool:
    end_date = item.get("end_date")
    return end_date is None or (isinstance(end_date, str) and not end_date.strip())


def select_source_experience(experiences: Iterable[object]):
    """Return ``(source_order, item)`` using the source list's original order.

    Multiple primary markers are treated as malformed and therefore fall back to
    the ordinary open-then-first policy.
    """

    valid = [(index, item) for index, item in enumerate(experiences) if _source_is_valid(item)]
    primary = [(index, item) for index, item in valid if item.get("is_primary") is True]
    if len(primary) == 1:
        return primary[0]
    open_experiences = [(index, item) for index, item in valid if _source_is_open(item)]
    return (open_experiences or valid or [None])[0]


def _persisted_is_valid(item: object) -> bool:
    return (
        bool(item)
        and bool(_text(getattr(item, "title", "")))
        and bool(_text(getattr(item, "company", "")))
    )


def select_persisted_experience(experiences: Iterable[object], selected_order: int | None = None):
    """Return one persisted experience using validated importer metadata when available."""

    ordered = sorted(
        (item for item in experiences if _persisted_is_valid(item)),
        key=lambda item: (item.source_order, item.pk or 0),
    )
    if selected_order is not None:
        selected = next(
            (item for item in ordered if item.source_order == selected_order),
            None,
        )
        if selected is not None:
            return selected
    open_experiences = [item for item in ordered if item.ended_at is None]
    return (open_experiences or ordered or [None])[0]
