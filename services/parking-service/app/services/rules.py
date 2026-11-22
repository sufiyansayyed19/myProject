from datetime import date, datetime, time, timedelta
from decimal import Decimal

from app.core.clock import get_business_tz
from app.core.errors import AppError

OPEN_TIME = time(7, 0)
CLOSE_TIME = time(22, 0)
MAX_DURATION_HOURS = 12
NORMAL_HOURLY_RATE = Decimal("10.00")
CHARGING_HOURLY_RATE = Decimal("20.00")


def validate_booking_interval(booking_date: date, start_time: time, end_time: time, now: datetime) -> None:
    tz = get_business_tz()
    now_local = now.astimezone(tz)
    today = now_local.date()
    tomorrow = today + timedelta(days=1)

    # Booking horizon: today and tomorrow only
    if booking_date not in (today, tomorrow):
        raise AppError(
            422,
            "BOOKING_WINDOW_VIOLATION",
            "Bookings are only allowed for today or tomorrow.",
        )

    # Sunday is closed (Monday=0 .. Sunday=6)
    if booking_date.weekday() == 6:
        raise AppError(
            422,
            "BOOKING_WINDOW_VIOLATION",
            "Parking facility is closed on Sundays.",
        )

    # Whole-hour boundaries only
    if start_time.minute != 0 or start_time.second != 0 or end_time.minute != 0 or end_time.second != 0:
        raise AppError(
            422,
            "INVALID_BOOKING_TIME",
            "Booking start and end times must be whole hours (e.g., 09:00, 11:00).",
        )

    # Operating hours 07:00 - 22:00 and end > start
    if start_time < OPEN_TIME or end_time > CLOSE_TIME or end_time <= start_time:
        raise AppError(
            422,
            "INVALID_BOOKING_TIME",
            "Booking must be within operating hours (07:00-22:00) with end_time after start_time.",
        )

    duration_hours = end_time.hour - start_time.hour
    if duration_hours > MAX_DURATION_HOURS:
        raise AppError(
            422,
            "INVALID_BOOKING_TIME",
            "Maximum booking duration is 12 hours.",
        )

    # Minimum advance (>15 min) & same-hour exception (first 30 min of current hour)
    start_dt = datetime.combine(booking_date, start_time, tzinfo=tz)
    if booking_date == today:
        if start_time.hour == now_local.hour:
            if now_local.minute > 30:
                raise AppError(
                    422,
                    "INVALID_BOOKING_TIME",
                    "Current-hour bookings are only permitted during the first 30 minutes of the hour.",
                )
        elif start_time.hour < now_local.hour:
            raise AppError(
                422,
                "INVALID_BOOKING_TIME",
                "Cannot book a time slot in the past.",
            )
        else:
            if (start_dt - now_local) <= timedelta(minutes=15):
                raise AppError(
                    422,
                    "INVALID_BOOKING_TIME",
                    "Future whole-hour bookings require strictly more than 15 minutes advance notice.",
                )
    else:
        # Tomorrow's booking: still verify > 15 min ahead (handles late-night edge case)
        if (start_dt - now_local) <= timedelta(minutes=15):
            raise AppError(
                422,
                "INVALID_BOOKING_TIME",
                "Bookings require strictly more than 15 minutes advance notice.",
            )


def validate_charging_compatibility(is_ev: bool, requires_charging: bool) -> None:
    if requires_charging and not is_ev:
        raise AppError(
            422,
            "CHARGING_NOT_SUPPORTED",
            "Charging cannot be requested for a non-EV vehicle.",
        )


def calculate_hourly_rate(requires_charging: bool) -> Decimal:
    return CHARGING_HOURLY_RATE if requires_charging else NORMAL_HOURLY_RATE


def calculate_booking_amount(start_time: time, end_time: time, requires_charging: bool) -> Decimal:
    hours = end_time.hour - start_time.hour
    return calculate_hourly_rate(requires_charging) * Decimal(hours)


def can_cancel_booking(booking_date: date, start_time: time, now: datetime) -> bool:
    tz = get_business_tz()
    now_local = now.astimezone(tz)
    start_dt = datetime.combine(booking_date, start_time, tzinfo=tz)
    return (start_dt - now_local) > timedelta(minutes=5)
