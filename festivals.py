"""Indian festival calendar, for Home's festival tip (the yellow banner).

The owner's ask, 27 Oct 2026: Prism should nudge a user, a few days
ahead, toward making an on-brand Instagram post or reel for an upcoming
Indian festival -- a small yellow tip on Home, "X is in N days -- want
to make a post about it?" (and a second one for a reel), Yes/No. On Yes
the prompt box is pre-filled with a short, specific ask, so all that is
left is attaching the company's own logo/photos and pressing Generate.
See widgets/home_panel.py's own `_FestivalTip` for the UI half.

CALENDAR is keyed by YEAR because these dates genuinely change every
year -- most are lunar or lunisolar, and a few (Eid al-Fitr, Eid
al-Adha) are only fixed by an actual moon sighting a day or two before
they happen. This is deliberately a plain data table to edit once a
year, not a date-maths function: there is no single formula that gets
every one of these right, and guessing one wrong is worse than a
one-line yearly update.

2026's dates were researched 27 Oct 2026 against drikpanchang.com,
hindu-blog.com, the CAG government holiday list, CDSL's holiday list and
a few other panchang sources. Where sources disagreed by a day --
common, since different panchang/regional observance can land a lunar
festival's start on either side of local midnight -- the majority or
the more specific source was used, and `note` says so on that entry.
Eid al-Fitr and Eid al-Adha are marked approximate for the same reason,
one layer deeper: they depend on a moon actually being sighted, not
just which panchang you trust. Before relying on an exact day for
anything other than this tip (a client-facing commitment, a holiday
notice), check a current panchang or moon-sighting announcement.

**Adding next year:** copy the structure below under the new year's key.
Nothing elsewhere in this file, or in widgets/home_panel.py, needs to
change -- `upcoming()` reads whichever year(s) are actually here.
"""
from __future__ import annotations
from datetime import date

MAJOR = "major"
MINOR = "minor"

# year -> [ {name, month, day, category, note?} ]
CALENDAR: dict[int, list[dict]] = {
    2026: [
        {"name": "New Year's Day", "month": 1, "day": 1, "category": MINOR},
        {"name": "Lohri", "month": 1, "day": 13, "category": MINOR},
        {"name": "Makar Sankranti / Pongal", "month": 1, "day": 14, "category": MAJOR},
        {"name": "Vasant Panchami", "month": 1, "day": 23, "category": MINOR},
        {"name": "Republic Day", "month": 1, "day": 26, "category": MAJOR},
        {"name": "Maha Shivratri", "month": 2, "day": 15, "category": MAJOR},
        {"name": "Holi", "month": 3, "day": 4, "category": MAJOR,
         "note": "Sources split between 3 and 4 March -- confirm locally."},
        {"name": "Ugadi / Gudi Padwa", "month": 3, "day": 19, "category": MAJOR},
        {"name": "Eid al-Fitr", "month": 3, "day": 21, "category": MAJOR,
         "note": "Depends on moon sighting -- could land a day either side."},
        {"name": "Ram Navami", "month": 3, "day": 26, "category": MAJOR},
        {"name": "Baisakhi / Vaisakhi", "month": 4, "day": 14, "category": MINOR},
        {"name": "Akshaya Tritiya", "month": 4, "day": 19, "category": MINOR},
        {"name": "Buddha Purnima", "month": 5, "day": 1, "category": MINOR},
        {"name": "Eid al-Adha / Bakrid", "month": 5, "day": 27, "category": MAJOR,
         "note": "Depends on moon sighting -- could land a day either side."},
        {"name": "Rath Yatra", "month": 6, "day": 15, "category": MINOR},
        {"name": "Guru Purnima", "month": 7, "day": 29, "category": MINOR},
        {"name": "Independence Day", "month": 8, "day": 15, "category": MAJOR},
        {"name": "Nag Panchami", "month": 8, "day": 17, "category": MINOR},
        {"name": "Onam", "month": 8, "day": 26, "category": MAJOR},
        {"name": "Raksha Bandhan", "month": 8, "day": 28, "category": MAJOR},
        {"name": "Varalakshmi Puja", "month": 8, "day": 28, "category": MINOR},
        {"name": "Janmashtami", "month": 9, "day": 4, "category": MAJOR},
        {"name": "Ganesh Chaturthi", "month": 9, "day": 14, "category": MAJOR},
        {"name": "Gandhi Jayanti", "month": 10, "day": 2, "category": MAJOR},
        {"name": "Navratri begins", "month": 10, "day": 11, "category": MAJOR},
        {"name": "Dussehra / Vijayadashami", "month": 10, "day": 20, "category": MAJOR},
        {"name": "Sharad Purnima", "month": 10, "day": 25, "category": MINOR},
        {"name": "Karva Chauth", "month": 10, "day": 29, "category": MINOR},
        {"name": "Dhanteras", "month": 11, "day": 5, "category": MAJOR,
         "note": "Approximate -- two days before Diwali."},
        {"name": "Diwali", "month": 11, "day": 8, "category": MAJOR},
        {"name": "Govardhan Puja", "month": 11, "day": 10, "category": MINOR},
        {"name": "Bhai Dooj", "month": 11, "day": 11, "category": MAJOR,
         "note": "Approximate -- the day after Govardhan Puja."},
        {"name": "Chhath Puja", "month": 11, "day": 15, "category": MAJOR},
        {"name": "Tulsi Vivah", "month": 11, "day": 21, "category": MINOR},
        {"name": "Dev Deepawali", "month": 11, "day": 24, "category": MINOR},
        {"name": "Guru Nanak Jayanti / Gurpurab", "month": 11, "day": 24, "category": MAJOR,
         "note": "Approximate -- same full moon as Dev Deepawali."},
        {"name": "Christmas", "month": 12, "day": 25, "category": MAJOR},
    ],
}


def _dated(year: int) -> list[dict]:
    out = []
    for f in CALENDAR.get(year, []):
        try:
            out.append({**f, "date": date(year, f["month"], f["day"])})
        except ValueError:
            continue
    return out


def upcoming(within_days: int = 3, today: date | None = None) -> list[dict]:
    """Every festival landing in [today, today + within_days], nearest
    first. Looks at next year's CALENDAR too, not just this year's --
    Dec 30 asking "within 3 days" must still find a Jan 1 festival next
    year; a year that has not been entered yet is skipped, never a
    crash, since this file is meant to be updated once a year, not
    necessarily the moment the clock turns."""
    today = today or date.today()
    pool = _dated(today.year) + _dated(today.year + 1)
    out = []
    for f in pool:
        days = (f["date"] - today).days
        if 0 <= days <= within_days:
            out.append({**f, "days_until": days})
    return sorted(out, key=lambda f: f["days_until"])


POST_PROMPT = (
    "Create an Instagram post for {name}, coming up {when}. Keep it warm "
    "and on-brand -- a short festive greeting for our customers, nothing "
    "generic. Attach your company's logo, a product photo or two, and "
    "any brand details you want included below, then press Generate.")

REEL_PROMPT = (
    "Create a short Instagram reel for {name}, coming up {when}. Keep it "
    "warm and on-brand -- a quick festive greeting for our customers. "
    "Attach your company's logo, a few photos or a short clip, and any "
    "brand details you want featured below, then press Generate.")


def when_phrase(f: dict) -> str:
    """"today" / "tomorrow" / "in N days" -- the Home tip's own wording
    and the two prompt templates below share this so they never disagree
    about how many days out the same festival is."""
    days = f["days_until"]
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"in {days} days"


def post_prompt(f: dict) -> str:
    return POST_PROMPT.format(name=f["name"], when=when_phrase(f))


def reel_prompt(f: dict) -> str:
    return REEL_PROMPT.format(name=f["name"], when=when_phrase(f))
