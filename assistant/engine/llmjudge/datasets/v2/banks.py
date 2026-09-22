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
