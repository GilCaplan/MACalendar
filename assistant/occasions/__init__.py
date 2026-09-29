"""Occasions: the yearly dates in a person's life, and extra calendars (Q73).

Gil, 2026-09-29: *"like we have for jewish calendar … a customizable option
for user to place like anniversaries, friends birthdays, other religious
events"*, and on display: *"all day but also customizable by user if they
want to edit it"*.

    store.py      each person's own occasions — birthdays, anniversaries,
                  yahrzeits, countdowns, other yearly dates (per user)
    dates.py      when each falls in a given range, by the regular OR the
                  Hebrew calendar (Adar in a leap year, a 30th that a month
                  lacks, Feb 29 in a common year)
    calendars.py  computed calendars: Jewish weekly extras (parasha, Omer,
                  Rosh Chodesh, Daf Yomi), national holidays by country,
                  Christian and Islamic holidays — each a switch
    feed.py       one list of all-day BANNERS for a date range: what both
                  apps draw, and what reminders are made from
    routes.py     /occasions — HTTP only

Occasions are banners, not events: they sit at the top of the day, never in
the timeline, are never moved by the assistant, and are not bookings. The
ones a person added are editable (the banner opens its editor); the computed
ones are switched on or off, and recoloured, in Settings ▸ Occasions.
Everything is computed here, offline — the phone draws what this sends and
caches it for when the Mac is away.
"""
