"""Policy-specific evidence deadlines, using UTC dates and calendar-month anniversaries."""

from calendar import monthrange
from datetime import UTC, date, datetime, timedelta


def field(value, path):
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def calendar_date(value):
    """Preserve printed dates; normalize instants to UTC before taking their date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("Datetime evidence must include a timezone")
        return value.astimezone(UTC).date()
    if isinstance(value, date):
        return value
    if len(value) == 10:
        return date.fromisoformat(value)
    return calendar_date(datetime.fromisoformat(value))


def add_months(value, months):
    ordinal = value.year * 12 + value.month - 1 + months
    year, month = divmod(ordinal, 12)
    if year > 9999:
        return date.max
    month += 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def add_days(value, days):
    return value + timedelta(days=min(days, (date.max - value).days))


def document_dates(document, option, today):
    payload = document["payload"]
    freshness = (
        calendar_date(field(payload, option.freshness_field)) if option.freshness_field else None
    )
    fresh_until = None
    if freshness is not None:
        fresh_until = (
            add_months(freshness, option.max_age_months)
            if option.max_age_months is not None
            else add_days(freshness, option.max_age_days)
        )
    expiration = (
        calendar_date(payload.get("expiration_date"))
        if option.require_unexpired and payload.get("validity_type") != "permanent"
        else None
    )
    renewal_from = None
    if option.renewal_interval_months is not None:
        renewal_from = calendar_date(
            (document.get("latest_review") or {}).get("reviewed_at")
            if option.renewal_basis == "reviewed_at"
            else document.get("submitted_at")
        )
    renewal_due = add_months(renewal_from, option.renewal_interval_months) if renewal_from else None
    deadlines = []
    if fresh_until and fresh_until < date.max:
        deadlines.append((add_days(fresh_until, 1), "replace_evidence"))
    if expiration and expiration < date.max:
        deadlines.append((add_days(expiration, 1), "replace_evidence"))
    if renewal_due:
        deadlines.append(
            (
                renewal_due,
                "review_again" if option.renewal_basis == "reviewed_at" else "submit_new_revision",
            )
        )
    due, action = min(deadlines) if deadlines else (None, None)
    state = (
        "overdue"
        if due and due < today
        else "due_today"
        if due == today
        else "due_soon"
        if due and due <= add_days(today, 30)
        else "current"
        if due
        else "not_scheduled"
    )
    return {
        "freshness_date": freshness.isoformat() if freshness else None,
        "fresh_until": fresh_until.isoformat() if fresh_until else None,
        "expires_on": expiration.isoformat() if expiration else None,
        "renewal_from": renewal_from.isoformat() if renewal_from else None,
        "renewal_due_on": renewal_due.isoformat() if renewal_due else None,
        "renewal_basis": option.renewal_basis if option.renewal_interval_months else None,
        "action_due_on": due.isoformat() if due else None,
        "due_status": state,
        "action": action,
    }
