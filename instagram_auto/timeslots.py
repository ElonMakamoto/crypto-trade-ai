"""Daily upload times in a channel's time zone (New York for English, Korea for Korean/Japanese)."""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# fixed offsets used only if the time zone database is missing (Windows needs the bundled tzdata)
FALLBACK = {"America/New_York": timezone(timedelta(hours=-5), "EST"), "Asia/Seoul": timezone(timedelta(hours=9), "KST")}
KST = FALLBACK["Asia/Seoul"]
SLOTS = 5
OFF = "사용 안 함"
# choices for each slot: every 30 minutes
CHOICES = [OFF] + [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]


@lru_cache(maxsize=None)
def zone(name):
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return FALLBACK.get(name, timezone.utc)


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


def now(tz_name):
    return datetime.now(zone(tz_name))


def next_slot(times, tz_name, after=None):
    """The first upload time strictly after `after` (default: now) in the zone, or None if no times are set."""
    if not times:
        return None
    tz = zone(tz_name)
    after = after or datetime.now(tz)
    for day in (0, 1, 2):
        date = (after + timedelta(days=day)).date()
        for hour, minute in times:
            slot = datetime(date.year, date.month, date.day, hour, minute, tzinfo=tz)
            if slot > after:
                return slot
    return None


def describe(slot, tz_label):
    """'21:00 뉴욕시간 (한국 10:00)', or '21:00 한국시간' when the zone already is Korea time."""
    korea = slot.astimezone(KST)
    if korea.utcoffset() == slot.utcoffset():
        return f"{slot:%H:%M} {tz_label}"
    return f"{slot:%H:%M} {tz_label} (한국 {korea:%H:%M})"
