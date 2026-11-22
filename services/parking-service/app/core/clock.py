from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings

IST_FALLBACK = timezone(timedelta(hours=5, minutes=30))


def get_business_tz():
    try:
        return ZoneInfo(settings.BUSINESS_TIMEZONE)
    except ZoneInfoNotFoundError:
        return IST_FALLBACK


def get_now() -> datetime:
    """Controllable clock dependency returning current time in Asia/Kolkata."""
    return datetime.now(get_business_tz())


def as_utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc) if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
