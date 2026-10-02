"""The filler banks and the temporal vocabulary the grammar draws on.

**Every term here is INVENTED** — generic activity nouns, loanwords and
ordinary compounds, the same privacy constraint `scripts/vocab_repair_bench.py`
and `scripts/gen_personas.py` work under. No word of the author's real
vocabulary is used, and nothing was copied out of a real transcript.

What is NOT invented is the temporal vocabulary: the clock FORMS below are the
ones `decompose_validate/ARCHITECTURE.md`'s conventions table says both readers
know (including the compact and dotted ones cycle 35 added), and the cadences
are the four `recurrence` may ever be.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# 1 · subjects
# ---------------------------------------------------------------------------

#: Noun phrases that name an EVENT. Two-word compounds dominate on purpose:
#: a damage operation needs a head word to land on, and a one-word subject
#: gives the vocabulary repair nothing to re-split (`vocab_repair_bench`'s
#: HEADS/COMPOUNDS are shaped the same way and for the same reason).
EVENT_SUBJECTS = [
    "barista course", "pilates class", "dentist appointment", "physio session",
    "orchestra rehearsal", "kayaking trip", "calligraphy workshop",
    "book club", "car service", "eye exam", "board meeting", "budget review",
    "team standup", "piano lesson", "flamenco class", "sourdough workshop",
    "podiatry appointment", "chiropractor visit", "parkour session",
    "tax filing meeting", "boiler inspection", "quarterly audit",
    "violin practice", "mahjong night", "ukulele lesson", "zumba class",
    "acupuncture session", "capoeira training", "taekwondo grading",
    "phlebotomy appointment", "obstetrics scan", "macrame workshop",
    "sudoku club", "origami class", "vinyasa session", "karate grading",
    "espresso tasting", "matcha tasting", "ramen night", "paella evening",
    "risotto class", "tiramisu workshop", "halloumi tasting", "gnocchi night",
    "linguine supper", "meringue class", "pierogi evening", "empanada night",
    "shawarma run", "falafel lunch", "croissant delivery", "kombucha order",
    "dry cleaning drop off", "grocery store run", "hair cut", "bike ride",
    "dog walk", "car wash", "sun screen order", "tool box delivery",
]

#: Verb phrases that name a TO-DO. A to-do title is what you DO, which is why
#: these start with a verb and the event ones do not.
TASK_SUBJECTS = [
    "pick up the dry cleaning", "order the cold brew", "book the car wash",
    "renew the parking permit", "return the rain coat", "pay the water bill",
    "call the chiropractor", "email the orchestra", "print the tax forms",
    "buy the sun screen", "collect the croissant order", "water the plants",
    "refill the espresso beans", "sort the tool box", "wash the bike",
    "post the insurance form", "confirm the eye exam", "charge the batteries",
    "replace the note book", "pack the board game", "label the storage boxes",
    "top up the travel card", "defrost the freezer", "hem the rain coat",
    "back up the laptop", "book the boiler inspection", "return the textbooks",
    "cancel the gym membership", "photograph the receipts", "sharpen the knives",
    "order the halloumi", "chase the prescription", "fix the bike light",
    "sweep the balcony", "tidy the tool shed", "restring the ukulele",
    "polish the violin", "measure the window frames", "mend the kayak strap",
    "order the matcha powder", "book the podiatry slot", "file the receipts",
]

#: Invented attendee names — used by the one-word-swap operation, which the
#: real-usage taxonomy shows landing on a person's name more often than on a
#: subject (class `disfluency`, rows where the wrong attendee was kept).
NAMES = ["Rona", "Dalit", "Yoram", "Tamsin", "Bram", "Nadia", "Ilan", "Petra",
         "Kiro", "Selma", "Odine", "Marek", "Ayla", "Denne", "Fabio", "Lior"]

#: The program's own furniture and the KIND words, kept apart because Q42
#: (Gil, 2026-09-22) rules them differently: a bare KIND word commits with the
#: details; the program's furniture still refuses.
KIND_WORDS = {"event": ["meeting", "appointment", "event"],
              "task": ["reminder", "task", "alert"]}

# ---------------------------------------------------------------------------
# 2 · when
# ---------------------------------------------------------------------------

#: (phrase, deliberate) — `deliberate` marks the days cycle 36 (2026-09-22)
#: says BEAT a weekday when the two disagree: "tomorrow", "today", an ordinal
#: and a month-day are days the speaker chose; a weekday is a gloss they
#: mis-say. The `stated_day_wrong_weekday` damage may only land on a
#: deliberate day, or it would change the gold instead of testing it.
DATE_PHRASES = [
    ("tomorrow", True),
    ("today", True),
    ("on monday", False),
    ("on tuesday", False),
    ("on wednesday", False),
    ("on thursday", False),
    ("on sunday", False),
    ("next monday", False),
    ("next friday", False),
    ("this coming sunday", False),
    ("on the 9th of october", True),
    ("on the 13th", True),
    ("tomorrow morning", True),
    ("on the 3rd of november", True),
]

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "sunday"]

#: THE CLOCK VALUES, and which spoken forms each can be said in. The forms are
#: the conventions table's, one name per shape:
#:
#:   colon          "at 3:45 pm"        dotted        "at 3.45 pm"
#:   dotted_mer     "at 3:45 p.m."      compact_ap    "at 345pm"
#:   compact_bare   "for 830"           zero_padded   "at 0910 am"
#:   oclock         "at 8 o'clock"      bare_hour     "at 7"
#:   words          "at half past four" twentyfour    "at 17:30"
#:   plain_mer      "at 5pm"
#:
#: `words` carries its own spelling per value because "half past four" and
#: "eight thirty in the morning" are not derivable from each other.
CLOCKS = [
    {"value": "15:45", "h12": "3:45", "mer": "pm", "compact": "345",
     "words": "quarter to four in the afternoon"},
    {"value": "09:10", "h12": "9:10", "mer": "am", "compact": "910",
     "words": "ten past nine in the morning", "pad": "0910"},
    {"value": "08:30", "h12": "8:30", "mer": "am", "compact": "830",
     "words": "eight thirty in the morning", "pad": "0830"},
    {"value": "10:40", "h12": "10:40", "mer": "am", "compact": "1040",
     "words": "twenty to eleven in the morning"},
    {"value": "17:00", "h12": "5:00", "mer": "pm", "compact": "500",
     "words": "five in the afternoon", "hour": 5},
    {"value": "08:00", "h12": "8:00", "mer": "am", "compact": "800",
     "words": "eight in the morning", "hour": 8, "oclock": "8 o'clock"},
    {"value": "16:30", "h12": "4:30", "mer": "pm", "compact": "430",
     "words": "half past four in the afternoon"},
    {"value": "12:30", "h12": "12:30", "mer": "pm", "compact": "1230",
     "words": "half past twelve"},
    {"value": "18:00", "h12": "6:00", "mer": "pm", "compact": "600",
     "words": "six in the evening", "hour": 6},
    {"value": "07:00", "h12": "7:00", "mer": "am", "compact": "700",
     "words": "seven in the morning", "hour": 7, "oclock": "7 o'clock"},
    {"value": "11:15", "h12": "11:15", "mer": "am", "compact": "1115",
     "words": "quarter past eleven in the morning"},
    {"value": "14:00", "h12": "2:00", "mer": "pm", "compact": "200",
     "words": "two in the afternoon", "hour": 2},
    {"value": "20:30", "h12": "8:30", "mer": "pm", "compact": "830",
     "words": "half past eight in the evening"},
    {"value": "13:00", "h12": "1:00", "mer": "pm", "compact": "100",
     "words": "one in the afternoon", "hour": 1},
]

#: The four cadences and nothing else (CLAUDE.md). `recur_days` carries WHICH
#: weekdays a weekly series lands on — that is not a fifth cadence.
RECURRENCES = [
    {"phrase": "every day", "cadence": "daily", "days": []},
    {"phrase": "every tuesday", "cadence": "weekly", "days": ["tuesday"]},
    {"phrase": "every monday and wednesday", "cadence": "weekly",
     "days": ["monday", "wednesday"]},
    {"phrase": "every tuesday and thursday", "cadence": "weekly",
     "days": ["tuesday", "thursday"]},
    {"phrase": "every week on monday", "cadence": "weekly", "days": ["monday"]},
    {"phrase": "every month on the 3rd", "cadence": "monthly", "days": []},
    {"phrase": "every month on the 18th", "cadence": "monthly", "days": []},
    {"phrase": "every year on the 9th of may", "cadence": "yearly", "days": []},
]

#: The anaphoric edit the brief asks for and the real-usage taxonomy's
#: `anaphoric-edit` class is made of: a target named by its recency rather
#: than by its words.
ANAPHORS = ["the one you just made", "the event you just made",
            "the last event you created", "the one from before"]

#: THE SAME THING, SAID AGAIN. A comma run with no conjunction is a speaker
#: restating one subject, not listing three (DEVQA Q43, 2026-09-22) — so the
#: run needs a second way of saying the SAME thing, or it would be a list
#: wearing a run's punctuation. Invented like everything else here.
RESTATEMENTS = {
    "physio session": "physiotherapy",
    "board meeting": "board sync",
    "eye exam": "optician",
    "dentist appointment": "the dentist",
    "barista course": "coffee course",
    "book club": "reading group",
    "car service": "the garage",
    "piano lesson": "piano",
    "budget review": "the budget",
    "team standup": "the standup",
    "violin practice": "violin",
    "boiler inspection": "the boiler",
    "quarterly audit": "the audit",
    "hair cut": "the barber",
    "dog walk": "walking the dog",
    "bike ride": "cycling",
    "grocery store run": "the shop",
    "orchestra rehearsal": "rehearsal",
    "chiropractor visit": "the chiropractor",
    "podiatry appointment": "the foot clinic",
}


# ---------------------------------------------------------------------------
# 3 · the TIER banks (2026-10-01) — read ONLY by the 10k / 40k tiers
# ---------------------------------------------------------------------------
#
# Gil, 2026-10-01: *"a lot of the datasets seem really small, they should be at
# least 40k with enough variation in the data."* The committed set (the `base`
# tier) is drawn from the lists ABOVE by index, so appending to them would move
# every base row. The tier generator instead swaps these in for the NEW
# families only (`extended()`), and the base lists stay exactly as they were.
#
# Same rules as everything above: every term is INVENTED — generic activity
# nouns, loanwords and ordinary compounds — no real transcript and no word of
# anyone's personal vocabulary. Event subjects keep a content head of five or
# more letters, because the recogniser operations need one to land on. No
# to-do subject names a person or a role to call or meet (Q47 / Q50 would move
# its gold and this bank is not where that should be decided).

TIER_EVENT_SUBJECTS = [
    "glassblowing class", "pottery workshop", "archery session",
    "fencing practice", "climbing session", "rowing practice",
    "aquafit lesson", "badminton match", "volleyball training",
    "cricket nets", "squash game", "triathlon briefing", "marathon clinic",
    "hiking meetup", "birdwatching walk", "stargazing evening",
    "astronomy lecture", "chemistry tutorial", "geography seminar",
    "statistics lecture", "portfolio review", "pension consultation",
    "mortgage meeting", "insurance renewal call", "warranty inspection",
    "chimney sweep visit", "plumbing inspection", "window cleaning",
    "carpet fitting", "furniture delivery", "kitchen survey",
    "allotment meeting", "compost workshop", "beekeeping course",
    "orchard tour", "vineyard tasting", "cheese tasting", "chocolate workshop",
    "dumpling night", "tapas evening", "brunch reservation",
    "barbecue afternoon", "picnic outing", "museum visit", "gallery opening",
    "theatre matinee", "cinema screening", "concert rehearsal",
    "madrigal rehearsal", "drumming circle", "saxophone lesson", "cello recital",
    "harmonica workshop", "dance rehearsal", "salsa class", "tango lesson",
    "ballet recital", "puppet show", "magic show", "trivia night",
    "chess tournament", "bowling league", "darts evening", "snooker match",
    "sketching session", "printmaking class", "watercolour workshop",
    "photography walk", "editing session", "podcast recording",
    "interview rehearsal", "induction session", "safety briefing",
    "planning session", "strategy offsite", "vendor demo", "product launch",
    "release review", "design critique", "sprint planning", "retrospective meeting",
    "vaccination appointment", "dermatology appointment", "hearing test",
    "allergy clinic", "nutrition consultation", "massage appointment",
    "osteopath session", "orthodontic check", "blood donation",
    "curriculum evening", "prizegiving rehearsal", "sports carnival", "science fair",
    "library storytime", "homework club", "graduation rehearsal",
]

TIER_TASK_SUBJECTS = [
    "defrost the salmon", "descale the kettle", "oil the bike chain",
    "repot the cactus", "prune the roses", "clean the gutters",
    "bleed the radiators", "test the smoke alarm", "change the bed sheets",
    "iron the shirts", "polish the shoes", "darn the socks",
    "renew the library card", "update the address book", "shred the old bills",
    "scan the warranty cards", "archive the photos", "clear the inbox",
    "export the spreadsheet", "rename the project folder", "install the updates",
    "reset the router", "replace the printer cartridge", "order the bin bags",
    "buy the birthday candles", "wrap the presents", "write the thank you cards",
    "plan the weekly menu", "prepare the packed lunches", "soak the chickpeas",
    "marinate the tofu", "bake the banana bread", "freeze the leftovers",
    "empty the dishwasher", "descale the shower head", "vacuum the stairs",
    "mop the hallway", "dust the bookshelves", "tidy the wardrobe",
    "donate the old coats", "sell the spare bike", "list the camping gear",
    "inflate the bike tyres", "check the tyre pressure", "top up the screen wash",
    "renew the car insurance", "book the mot test", "pay the parking fine",
    "submit the expense claim", "sign the tenancy form", "fill in the census form",
    "photocopy the passport", "laminate the timetable", "sharpen the pencils",
    "restock the first aid kit", "charge the power bank", "pack the gym bag",
]

#: More days, with the same `deliberate` reading (cycle 36): a weekday is a
#: gloss, a relative day or a month-day is chosen. Saturday is left out for
#: the same reason the base list leaves it out.
TIER_DATE_PHRASES = [
    ("on friday", False),
    ("next tuesday", False),
    ("next wednesday", False),
    ("this coming thursday", False),
    ("on the 21st", True),
    ("on the 2nd of december", True),
    ("on the 15th of october", True),
    ("the day after tomorrow", True),
]

#: More clock values, each with every field its forms need. The same
#: refusals apply (`voices.render_clock`): no `oclock` on an afternoon hour,
#: and `bare_hour` only where the conventions table reads it the same way.
TIER_CLOCKS = [
    {"value": "09:45", "h12": "9:45", "mer": "am", "compact": "945",
     "words": "quarter to ten in the morning", "pad": "0945"},
    {"value": "19:00", "h12": "7:00", "mer": "pm", "compact": "700",
     "words": "seven in the evening", "hour": 7},
    {"value": "10:00", "h12": "10:00", "mer": "am", "compact": "1000",
     "words": "ten in the morning", "hour": 10},
    {"value": "15:15", "h12": "3:15", "mer": "pm", "compact": "315",
     "words": "quarter past three in the afternoon"},
    {"value": "11:30", "h12": "11:30", "mer": "am", "compact": "1130",
     "words": "half past eleven in the morning"},
    {"value": "16:00", "h12": "4:00", "mer": "pm", "compact": "400",
     "words": "four in the afternoon", "hour": 4},
    {"value": "07:45", "h12": "7:45", "mer": "am", "compact": "745",
     "words": "quarter to eight in the morning", "pad": "0745"},
    {"value": "18:30", "h12": "6:30", "mer": "pm", "compact": "630",
     "words": "half past six in the evening"},
]

TIER_RECURRENCES = [
    {"phrase": "every friday", "cadence": "weekly", "days": ["friday"]},
    {"phrase": "every wednesday and friday", "cadence": "weekly",
     "days": ["wednesday", "friday"]},
    {"phrase": "every week on thursday", "cadence": "weekly",
     "days": ["thursday"]},
    {"phrase": "every month on the 10th", "cadence": "monthly", "days": []},
    {"phrase": "every year on the 2nd of march", "cadence": "yearly",
     "days": []},
]

TIER_ANAPHORS = ["the one i just added", "that last event",
                 "the event from a minute ago"]

TIER_RESTATEMENTS = {
    "aquafit lesson": "aquafit",
    "pottery workshop": "pottery",
    "chess tournament": "the chess",
    "museum visit": "the museum",
    "salsa class": "salsa",
    "trivia night": "the quiz",
    "sprint planning": "planning",
    "hearing test": "the audiologist",
    "curriculum evening": "the school evening",
    "furniture delivery": "the delivery",
    "climbing session": "climbing",
    "cinema screening": "the film",
}


def extended():
    """Swap the tier banks in for the duration of a `with` block.

    The generator reads `banks.X` at call time, so this is the one switch that
    gives the NEW families the wider vocabulary while every base row keeps
    drawing from the lists it was built from. Restores on exit, even on error.
    """
    import contextlib

    @contextlib.contextmanager
    def _swap():
        g = globals()
        saved = {k: g[k] for k in ("EVENT_SUBJECTS", "TASK_SUBJECTS",
                                   "DATE_PHRASES", "CLOCKS", "RECURRENCES",
                                   "ANAPHORS", "RESTATEMENTS")}
        try:
            g["EVENT_SUBJECTS"] = saved["EVENT_SUBJECTS"] + TIER_EVENT_SUBJECTS
            g["TASK_SUBJECTS"] = saved["TASK_SUBJECTS"] + TIER_TASK_SUBJECTS
            g["DATE_PHRASES"] = saved["DATE_PHRASES"] + TIER_DATE_PHRASES
            g["CLOCKS"] = saved["CLOCKS"] + TIER_CLOCKS
            g["RECURRENCES"] = saved["RECURRENCES"] + TIER_RECURRENCES
            g["ANAPHORS"] = saved["ANAPHORS"] + TIER_ANAPHORS
            g["RESTATEMENTS"] = {**saved["RESTATEMENTS"], **TIER_RESTATEMENTS}
            yield
        finally:
            g.update(saved)
    return _swap()
