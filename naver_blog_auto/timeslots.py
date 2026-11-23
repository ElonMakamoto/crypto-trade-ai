"""Daily posting times in Korea time, each moved by a random amount so posts never land on the same minute."""
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    KST = ZoneInfo("Asia/Seoul")
except ZoneInfoNotFoundError:  # Windows without the bundled tzdata
    KST = timezone(timedelta(hours=9), "KST")

SLOTS = 3  # up to 3 posts a day per account (more looks like spam to Naver)
OFF = "사용 안 함"
CHOICES = [OFF] + [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]
JITTER_MINUTES = 40


def parse(text):
    """'09:30,19:30' -> [(9, 30), (19, 30)]; invalid entries are ignored."""
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
    return datetime.now(KST)


def jittered(date, hour, minute, seed=""):
    """That time on that date moved by -40..+40 minutes; the same inputs always give the same moment."""
    base = datetime(date.year, date.month, date.day, hour, minute, tzinfo=KST)
    shift = random.Random(f"{seed}|{date.isoformat()}|{hour:02d}:{minute:02d}").randint(
        -JITTER_MINUTES * 60, JITTER_MINUTES * 60)
    return base + timedelta(seconds=shift)


def next_slot(times, after=None, seed=""):
    """The first posting moment strictly after `after` (default: now), or None if no times are set."""
    if not times:
        return None
    after = after or now()
    start = after.astimezone(KST).date()
    moments = [jittered(start + timedelta(days=d), h, m, seed) for d in (-1, 0, 1, 2) for h, m in times]
    later = [m for m in moments if m > after]
    return min(later) if later else None


def describe(slot):
    day = "오늘" if slot.date() == now().date() else ("내일" if slot.date() == now().date() + timedelta(days=1)
                                                      else f"{slot:%m/%d}")
    return f"{day} {slot:%H:%M}"
