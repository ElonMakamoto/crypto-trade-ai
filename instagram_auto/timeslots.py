"""Daily upload times in New York time (America/New_York, follows daylight saving time)."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    TZ = ZoneInfo("America/New_York")  # Windows needs the tzdata package for this (bundled with the app)
except ZoneInfoNotFoundError:
    TZ = timezone(timedelta(hours=-5), "EST")
KST = timezone(timedelta(hours=9), "KST")
TZ_LABEL = "뉴욕시간"
SLOTS = 5
OFF = "사용 안 함"
# choices for each slot: every 30 minutes
CHOICES = [OFF] + [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]


def parse(text):
    """'09:00,12:00,-,...' -> sorted unique [(9, 0), (12, 0), ...]; invalid or empty entries are ignored."""
    times = set()
    for part in (text or "").split(","):
        try:
            hour, minute = (int(x) for x in part.strip().split(":"))
        except ValueError:
            continue
        if 0 <= hour < 24 and 0 <= minute < 60:
            times.add((hour, minute))
    return sorted(times)


def now():
    return datetime.now(TZ)


def next_slot(times, after=None):
    """The first upload time (New York) strictly after `after` (default: now), or None if no times are set."""
    if not times:
        return None
    after = after or now()
    for day in (0, 1, 2):
        date = (after + timedelta(days=day)).date()
        for hour, minute in times:
            slot = datetime(date.year, date.month, date.day, hour, minute, tzinfo=TZ)
            if slot > after:
                return slot
    return None


def describe(slot):
    """'21:00 뉴욕시간 (한국 10:00)'"""
    return f"{slot:%H:%M} {TZ_LABEL} (한국 {slot.astimezone(KST):%H:%M})"
