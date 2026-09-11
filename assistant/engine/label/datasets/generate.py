"""Build the label datasets — and the labels are NOT the rules' output.

    python -m assistant.engine.label.datasets.generate

Writes `event_categories.jsonl` and `task_tags.jsonl` beside this file.
**A generator lives in the folder whose data it generates** (CLAUDE.md).

## The problem this exists to solve

Every category label this project owned was `categories.classify()`'s own
answer — `fastrule/datasets/generate.py` computes its gold by calling it. A
model trained on that can only DISTILL the keyword table, which is why a
decision tree scored **exactly 100%** on the old board and why every model lost
to the rules on real data (events 71.4% vs 50%).

**So the direction is inverted: the LABEL COMES FIRST and the text is generated
from it.** A row's class is what it was generated AS, not what a keyword matcher
says about it afterwards. That makes the ground truth independent of the
incumbent, which is the only way a model can be shown to beat it rather than
approximate it.

## Why this can beat the rules rather than merely match them

`tagging.KEYWORDS["Groceries"]` is **179 hand-typed words**. It gets "zucchini"
and "gatorade" because somebody added them. It will not get the next vegetable.

The seed vocabulary below is broader than any keyword list and — critically —
**split so that the test half uses subjects the training half never saw**. A
model that scores on the novel-vocabulary split has learned the semantic
neighbourhood; the keyword rules score 0 there by construction, because a word
not in the list is not in the list.

That is the honest comparison, and it is the one the old dataset could not make:
it had **8 novel-vocabulary rows in 1,179**.

## The two problems are different shapes

Events are SINGLE-label over the category palette. Tasks are MULTI-label — a
task can be Groceries and Errands at once — so they are generated and scored
separately, and never share a split.
"""
from __future__ import annotations

import json
import pathlib
import random

HERE = pathlib.Path(__file__).resolve().parent
EVENTS_OUT = HERE / "event_categories.jsonl"
TASKS_OUT = HERE / "task_tags.jsonl"

#: SUBJECTS per event category — the noun phrase the event is ABOUT.
#:
#: Deliberately wide and deliberately including things no keyword list contains:
#: that is the whole experiment. Each list mixes the obvious members with
#: peripheral ones, because a classifier that only learns the obvious ones has
#: learned the keyword table with extra steps.
EVENT_SUBJECTS: "dict[str, list[str]]" = {
    "Work": [
        "standup", "sprint planning", "retro", "one-on-one with my manager",
        "performance review", "quarterly planning", "client call", "handover",
        "code review", "onboarding session", "board meeting", "budget review",
        "vendor call", "contract signing", "shift at the warehouse",
        "interview panel", "pitch rehearsal", "stakeholder update",
        "payroll run", "audit prep", "team offsite", "product demo",
        "supplier negotiation", "invoice reconciliation", "hiring sync",
        "all-hands", "1:1", "roadmap review", "backlog grooming",
        "design review", "postmortem", "escalation call", "partner sync",
        "sales pitch", "renewal call", "compliance training",
        "security briefing", "headcount review", "okr review",
        "procurement call", "site visit", "trade show booth",
        "press briefing", "investor update", "due diligence call",
        "handover to the night shift", "rota planning", "stocktake",
        "supplier audit", "tender submission", "kpi review",
        "expenses deadline", "appraisal", "probation review",
        "notice period chat", "workshop facilitation", "training delivery",
        "certification exam for work", "grant application",
        "ethics submission", "peer review deadline", "standup with ops",
        "capacity planning", "incident review",
        "daily standup", "weekly wrap", "monthly report", "annual review",
        "team retro", "cross-team sync", "architecture review",
        "threat modelling", "runbook review", "on-call handover",
        "release sign-off", "change board", "pen test debrief", "data review",
        "pricing meeting", "campaign review", "content planning",
        "brand workshop", "user research session", "usability test",
        "customer interview", "churn review", "renewal negotiation",
        "partnership call", "legal review", "nda signing", "invoice chase",
        "supplier onboarding", "warehouse count", "delivery slot",
        "van inspection", "health and safety walk", "fire drill",
        "first aid training", "manual handling training", "shift swap",
        "overtime approval", "rota publish", "timesheet deadline",
        "expenses cutoff",
        "the status report", "the weekly update", "the meeting notes",
        "the action items", "the risk register", "the project plan",
        "the gantt chart", "the budget forecast", "the purchase order",
        "the supplier invoice", "the credit note", "the vat return",
        "the payroll submission", "the pension upload", "the holiday request",
        "the sickness form", "the appraisal form", "the objectives doc",
        "the job description", "the interview scorecard", "the offer letter",
        "the reference check", "the induction pack", "the training record",
        "the policy review", "the risk assessment", "the method statement",
        "the incident form", "the audit evidence", "the compliance checklist",
        "the customer proposal", "the pricing sheet", "the contract redline",
        "the sow", "the handover notes",
    ],
    "Study": [
        "lecture", "tutorial", "lab session", "exam", "midterm", "final",
        "thesis meeting", "study group", "revision block", "office hours",
        "problem set", "dissertation chapter", "seminar", "reading week catch-up",
        "coursework deadline", "viva prep", "literature review", "flashcards",
        "past papers", "research meeting", "poster session", "defence rehearsal",
        "supervision", "cohort meeting", "journal club", "methods workshop",
        "stats clinic", "language class", "conversation exchange",
        "coding bootcamp session", "revision sprint", "mock exam",
        "oral exam", "practical assessment", "field trip",
        "dissertation submission", "ethics form deadline", "reading group",
        "writing retreat", "conference talk", "abstract deadline",
        "peer feedback session", "study hall", "library session",
        "thesis proofread", "referencing workshop", "exam board", "resit",
        "open day", "matriculation", "enrolment", "module selection",
        "problem class", "support class", "drop-in session",
        "academic advising", "module intro", "course induction",
        "lab induction", "safety briefing for the lab", "data collection",
        "participant session", "transcription work", "coding the interviews",
        "analysis session", "supervisor catch-up", "progress review",
        "upgrade viva", "conference registration", "travel grant deadline",
        "poster printing", "slide practice", "presentation dry run",
        "exam registration", "special access arrangements", "results day",
        "graduation ceremony", "alumni talk", "careers fair", "cv workshop",
        "internship interview", "placement meeting",
    ],
    "Meeting": [
        # "check-in" was here and is genuinely ambiguous — a workplace check-in
        # and a hotel check-in are different events with the same name. An
        # ambiguous subject in a SINGLE-label problem teaches noise and, worse,
        # leaks across the vocabulary split (it landed in train for one category
        # and test for another). Dropped rather than assigned arbitrarily.
        "catch-up", "sync", "coffee chat", "intro call",
        "kickoff", "debrief", "alignment call", "roundtable", "working session",
        "steering committee", "weekly sync", "status update", "planning session",
        "quick chat", "touch base", "walkthrough", "handoff call",
        "scoping call", "discovery call", "follow-up call", "review call",
        "briefing", "huddle", "council session", "committee meeting", "agm",
        "panel discussion", "consultation", "negotiation", "mediation",
        "interview", "screening call", "reference call", "onboarding chat",
        "exit interview", "supplier meeting", "site meeting",
        "residents meeting", "association meeting", "trustee meeting",
        "working group", "task force meeting", "coordination call",
        "stand-up", "weekly one to one", "fortnightly sync",
        "quarterly review call", "project board", "risk review",
        "governance call", "escalation review", "supplier review",
        "customer check-in", "onboarding kickoff", "offboarding call",
        "team retro call", "planning poker", "estimation session",
        "prioritisation workshop", "stakeholder mapping",
        "requirements gathering", "sign-off meeting", "handover meeting",
        "induction meeting", "appraisal chat", "probation meeting",
        "grievance hearing", "disciplinary meeting", "union meeting",
        "works council", "parish council", "school governors",
        "charity board",
    ],
    "Shabbat Meal": [
        "friday night dinner", "shabbat lunch", "seudah shlishit", "kiddush",
        "shabbos meal", "friday night meal", "shabbat dinner with the family",
        "melave malka", "shalosh seudos", "erev shabbat dinner",
        "seudah", "shabbos lunch", "friday dinner at home", "shabbat table",
        "erev yom tov meal", "yom tov lunch", "seder", "rosh hashanah dinner",
        "break fast", "sukkah meal", "chanukah dinner", "purim seudah",
        "shavuot dinner", "simchat torah lunch", "kiddush after shul",
        "shabbaton meal", "oneg", "friday night at my parents",
        "shabbat guests", "third meal",
        "friday night seudah", "shabbos morning kiddush",
        "shalosh seudos at shul", "yom tov seudah", "chag meal",
        "erev pesach meal", "seder night", "second seder",
        "sukkot meal in the sukkah", "simchat torah kiddush",
        "shavuot cheesecake", "rosh hashanah simanim",
        "tzom gedalia break fast", "yom kippur pre-fast meal",
        "motzei shabbat melave malka", "shabbat chatan meal", "sheva brachot",
        "bar mitzvah kiddush", "aufruf kiddush",
        "shabbat lunch with the neighbours",
    ],
    "Social": [
        "drinks", "birthday party", "dinner out", "housewarming", "picnic",
        "barbecue", "game night", "concert", "pub quiz", "wedding",
        "engagement party", "brunch", "gallery opening", "comedy night",
        "leaving do", "book club", "karaoke", "reunion", "festival",
        "escape room", "bowling", "dinner party", "cocktails", "beach day",
        "house party", "street food market", "pub trip", "cinema", "theatre",
        "gig", "clubbing", "board games evening", "trivia night",
        "wine tasting", "brewery tour", "paint and sip",
        "pottery class with friends", "salsa night", "open mic",
        "poetry reading", "art class", "supper club", "potluck",
        "camping trip", "day at the races", "football match", "rugby match",
        "cricket day", "boat party", "rooftop drinks", "speed dating",
        "blind date", "coffee with an old friend", "catch-up walk",
        "sunday roast with mates", "leaving drinks", "baby shower", "hen do",
        "stag do", "anniversary dinner",
        "street party", "pub garden", "garden party", "bbq at the park",
        "picnic in the park", "beach bonfire", "kayaking with friends",
        "paddleboarding", "crazy golf", "axe throwing", "darts night",
        "snooker", "pool night", "arcade bar", "silent disco", "jazz night",
        "folk session", "club night", "house gathering", "flat warming",
        "movie marathon", "anime night", "cosplay meetup",
        "tabletop rpg session", "dungeons and dragons", "chess meetup",
        "running club social", "cycling club ride", "hiking group",
        "photography meetup", "language exchange evening", "salsa social",
        "swing dance", "ceilidh", "quiz league", "charity gala",
        "fundraiser dinner", "auction night", "secret santa",
        "new year's eve party",
    ],
    "Family": [
        "parents' anniversary", "visit to grandma", "family dinner",
        "school play", "parent-teacher conference", "sports day",
        "sibling's graduation", "cousin's bar mitzvah", "family photos",
        "nephew's birthday", "in-laws visiting", "christening", "family walk",
        "grandparents' visit", "school assembly", "nativity play",
        "prize giving", "open evening", "parents evening", "school run",
        "childcare handover", "family reunion", "christmas lunch",
        "easter with the family", "mother's day lunch", "father's day",
        "sibling's wedding", "niece's recital", "cousin's christening",
        "family game night", "visiting my aunt", "care home visit",
        "hospital visit to dad", "family budgeting chat", "will reading",
        "house clearance with siblings", "godchild's birthday",
        "family holiday planning", "school uniform shopping",
        "nan's birthday", "grandad's birthday", "mum's birthday",
        "dad's birthday", "anniversary lunch", "school sports day",
        "swimming lesson for the kids", "ballet run", "football training run",
        "scouts pickup", "brownies dropoff", "piano lesson for the kids",
        "tutoring session", "parents association", "pta meeting",
        "school fete", "summer fair", "nativity rehearsal",
        "harvest festival", "sports awards", "family court appointment",
        "adoption meeting", "fostering review", "guardianship meeting",
        "care review", "grandparents lunch", "cousin's baby shower",
        "family christening", "memorial service", "grave visit",
    ],
    "Prayer": [
        "shacharit", "mincha", "maariv", "davening", "shiur", "selichot",
        "megillah reading", "torah reading", "minyan", "tehillim group",
        "hashkama minyan", "neilah", "kabbalat shabbat",
        "shiur with the rabbi", "chevruta", "daf yomi", "mussar seder",
        "kollel", "hashkafa class", "parsha class", "halacha shiur",
        "tefillah group", "psalms group", "vasper", "evening prayers",
        "morning service", "mass", "confession", "bible study",
        "youth service", "carol service", "jummah", "taraweeh",
        "meditation sit", "sangha", "kirtan", "vigil", "yahrzeit", "kaddish",
        "shiva visit", "brit milah", "pidyon haben",
        "shacharit at the vatikin minyan", "early minyan", "late maariv",
        "mincha gedola", "mincha ketana", "rosh chodesh davening", "hallel",
        "yizkor", "selichot before rosh hashanah", "tashlich",
        "hoshana rabba", "simchat torah hakafot", "megillat esther",
        "eicha reading", "kinnot", "shiur before mincha", "gemara shiur",
        "mishna yomit", "chumash class", "navi shiur",
        "tehillim for a refuah", "hachnasat sefer torah", "siyum", "hadran",
        "shabbaton shiur", "sunday school", "confirmation class",
        "choir practice at church", "evensong", "compline",
    ],
    "Fitness": [
        "gym session", "easy run", "threshold run", "long run", "intervals",
        "spin class", "yoga", "pilates", "swim", "climbing", "boxing",
        "5k parkrun", "leg day", "calisthenics", "hiit class", "stretching",
        "cycling", "rowing", "tennis", "football practice", "netball",
        "personal training", "cold plunge", "mobility work", "track session",
        "deadlift session", "bench day", "push day", "pull day", "upper body",
        "core session", "mobility class", "barre", "zumba", "aqua aerobics",
        "circuit training", "crossfit wod", "hyrox training", "tempo run",
        "fartlek", "hill reps", "recovery jog", "brick session",
        "turbo trainer", "sea swim", "lane swim", "squash", "badminton",
        "padel", "table tennis", "martial arts", "judo", "bjj", "muay thai",
        "fencing", "archery", "sports massage", "physio exercises",
        "foam rolling", "sauna and cold plunge", "hike", "trail run",
        "bouldering", "gymnastics", "dance class",
        "easy 5k", "tempo 8k", "long 18k", "recovery 4k", "progression run",
        "hill sprints", "stair climbs", "sled push", "farmers carry",
        "kettlebell circuit", "clean and jerk session", "snatch practice",
        "olympic lifting", "powerlifting session", "strongman training",
        "calisthenics skills", "handstand practice", "muscle up practice",
        "ring work", "parallel bars", "front squat day", "back squat day",
        "overhead press day", "romanian deadlifts", "accessory work",
        "yin yoga", "vinyasa flow", "hot yoga", "reformer pilates",
        "mat pilates", "open water swim", "masters swim", "triathlon brick",
        "duathlon training", "trail loop", "ultra long run", "taper run",
        "race day", "parkrun volunteering", "stretch and mobility",
    ],
    "Health": [
        "dentist", "physio", "gp appointment", "blood test", "optician",
        "dermatology referral", "vaccination", "smear test", "x-ray",
        "therapy session", "orthodontist", "flu jab", "check-up", "scan",
        "consultant appointment", "podiatrist", "hearing test", "allergy clinic",
        "mri", "ct scan", "ultrasound", "endoscopy", "colonoscopy",
        "mammogram", "eye test", "contact lens fitting", "hygienist",
        "root canal", "wisdom teeth removal", "sports injury clinic",
        "chiropractor", "osteopath", "acupuncture", "counselling",
        "psychiatry appointment", "dietitian", "nutritionist", "sleep clinic",
        "cardiology follow-up", "dermatologist", "antenatal appointment",
        "midwife", "health visitor", "immunisation", "booster jab",
        "blood donation", "medication review", "pharmacy consultation",
        "occupational health", "fit note appointment",
        "diabetes review", "asthma review", "copd clinic",
        "anticoagulation clinic", "warfarin check", "bp check",
        "cholesterol test", "thyroid test", "iron infusion", "b12 injection",
        "allergy testing", "patch test", "skin check", "mole mapping",
        "biopsy", "pre-op assessment", "post-op review", "surgery",
        "day case procedure", "discharge appointment", "fertility clinic",
        "ivf appointment", "scan at twelve weeks", "glucose tolerance test",
        "postnatal check", "smoking cessation", "weight management clinic",
        "cardiac rehab", "pulmonary rehab", "pain clinic", "audiology",
        "speech therapy", "occupational therapy", "hydrotherapy",
        "podiatry review",
    ],
    "Errand": [
        "car service", "mot", "post office run", "bank appointment",
        "dry cleaning", "package pickup", "locksmith", "boiler inspection",
        "passport renewal", "furniture delivery", "returning the library books",
        "picking up the prescription", "council appointment", "tyre change",
        "mot booking", "tyre fitting", "windscreen repair", "valeting",
        "bike service", "shoe cobbler", "tailoring", "alterations",
        "watch repair", "phone repair", "laptop repair", "key cutting",
        "photo printing", "framing the print", "charity shop drop-off",
        "tip run", "recycling centre", "storage unit visit",
        "estate agent viewing", "solicitor appointment", "notary appointment",
        "visa centre", "dvla appointment", "tax office visit",
        "insurance renewal call", "mortgage appointment", "utilities switch",
        "broadband installation", "boiler service", "chimney sweep",
        "pest control", "gardener visit", "cleaner visit",
        "furniture assembly",
        "click and collect", "parcel drop", "royal mail collection",
        "courier pickup", "returns drop-off", "supermarket click and collect",
        "bottle bank", "garden waste collection", "bulky waste pickup",
        "skip hire", "van hire pickup", "trailer return", "tool hire",
        "ladder return", "paint mixing", "curtain fitting", "carpet measure",
        "blind installation", "kitchen survey", "bathroom quote",
        "roof inspection", "gutter clearing", "window cleaner", "damp survey",
        "electrical safety check", "gas safety check", "epc assessment",
        "meter reading", "water meter install", "smart meter appointment",
        "car tax renewal", "insurance quote call", "breakdown cover renewal",
        "number plate collection", "service plan setup",
    ],
    "Meal": [
        "lunch", "breakfast", "dinner", "brunch with the team", "takeaway",
        "meal prep", "iftar", "supper", "afternoon tea", "food shop delivery",
        "lunch break", "team lunch", "client dinner", "date night dinner",
        "sunday lunch", "picnic lunch", "packed lunch prep", "batch cooking",
        "sourdough bake", "sunday meal prep", "grocery delivery slot",
        "restaurant booking", "tasting menu", "pizza night", "curry night",
        "taco tuesday", "soup and bread", "coffee and pastry", "elevenses",
        "supper with neighbours",
        "quick lunch", "working lunch", "early dinner", "late supper",
        "brunch at home", "sunday breakfast", "bagels and coffee", "fry up",
        "porridge and fruit", "smoothie prep", "lunch with a colleague",
        "dinner with the neighbours", "potluck contribution", "bake off",
        "sunday bake", "slow cooker prep", "freezer meal batch",
        "lunchbox prep", "office bring-a-dish", "charity bake sale",
    ],
    "Travel": [
        "flight", "train to the coast", "airport transfer", "check-in",
        "road trip", "ferry crossing", "coach to the airport", "hotel checkout",
        "visa appointment", "packing", "border crossing", "connecting flight",
        "long haul flight", "red eye", "layover", "shuttle bus",
        "car hire pickup", "car hire return", "hotel check-in",
        "airbnb checkout", "eurostar", "sleeper train", "ferry to the island",
        "cruise embarkation", "customs appointment", "esta application",
        "travel jabs", "currency exchange", "parking at the airport",
        "taxi to the station", "coach journey", "campsite arrival",
        "road trip leg two", "border control", "baggage drop",
        "seat selection", "travel insurance call",
        "outbound flight", "return flight", "internal flight", "first leg",
        "second leg", "airport parking booking", "lounge access",
        "fast track security", "gate close", "boarding", "train to london",
        "train from manchester", "platform change", "seat reservation",
        "rail replacement", "coach to the ferry", "ferry boarding",
        "cabin check-in", "cruise disembark", "port transfer",
        "hire car collection", "hire car drop", "fuel up before returning",
        "toll pass setup", "congestion charge", "campervan pickup",
        "campsite check-in", "hostel check-in", "apartment key collection",
        "luggage storage",
    ],
    "Personal": [
        "haircut appointment", "quiet time", "journalling", "admin block",
        "budgeting", "reading", "meditation", "tidying the flat", "laundry",
        "planning the week", "guitar practice", "piano practice", "photography walk",
        "therapy homework", "journaling session", "weekly review",
        "inbox zero session", "photo backup", "digital declutter",
        "wardrobe sort", "spring clean", "plant watering", "bike maintenance",
        "guitar lesson", "piano lesson", "language practice", "chess club",
        "crossword", "reading an hour", "podcast catch-up",
        "film night alone", "long bath", "skincare routine", "haircut",
        "barber", "manicure", "massage", "budget review at home",
        "pension review", "savings check", "birthday planning",
        "christmas shopping", "gift wrapping", "letter writing",
        "volunteering shift",
        "morning pages", "evening reflection", "gratitude list",
        "goal setting", "quarterly planning at home", "finance review",
        "isa top up", "pension contribution", "share portfolio review",
        "tax return", "self assessment deadline", "expenses reconciliation",
        "subscription audit", "password rotation", "backup check",
        "photo album sort", "scrapbooking", "letter to grandma",
        "thank you cards", "birthday card writing", "wardrobe declutter",
        "charity bag", "selling on marketplace", "ebay listings",
        "car boot sale", "houseplant repotting", "seed sowing",
        "allotment visit", "lawn mowing", "hedge trimming",
        "guitar practice hour", "singing practice", "art journalling",
        "life drawing", "pottery at home",
    ],
}

#: Frames the subject is dropped into. The classifier must not be able to key on
#: the frame, so every frame is shared across every category.
#: Frames the subject is dropped into. Every frame is shared across every
#: category ON PURPOSE — if a frame belonged to one class the classifier could
#: key on it and the board would measure the frame, not the subject.
#:
#: The register varies deliberately: terse, verbose, polite, spoken, and
#: transcript-damaged. Real commands arrive as speech, and a model trained only
#: on tidy phrasings learns tidy phrasings — the persona finding this project
#: already recorded (swapping content nouns moves the classifiers 0-3 pt,
#: swapping PHRASING moves them 7-29 pt).
EVENT_FRAMES = [
    # terse
    "{s}", "{s} {t}", "{s} {d}", "{s} {d} {t}", "{s}, {d}",
    # ordinary imperative
    "book {s}", "schedule {s}", "add {s}", "put {s} in", "set up {s}",
    "book {s} {d}", "schedule {s} for {d}", "add {s} on {d}", "put {s} in for {d}",
    "book {s} {d} {t}", "schedule {s} {d} at {t}", "pencil in {s} for {d}",
    # with people and places
    "{s} with {who}", "book {s} with {who}", "{s} with {who} {d}",
    "{s} at {where}", "book {s} at {where} {d}", "{s} with {who} at {where}",
    # polite / verbose
    "can you book {s} for {d}", "could you put {s} in the diary for {d}",
    "please add {s} on {d}", "i need {s} booked {d}", "i've got {s} {d}",
    "remind me about {s} {d}", "don't let me forget {s} {d}",
    "get {s} in the calendar for {d}", "make a note of {s} {d}",
    # spoken / damaged, the way a transcript actually arrives
    "uh {s} {d}", "so {s} {d} i think", "{s} — {d}", "{s}... {d}",
    "erm can you add {s} {d}", "{s} {d} please", "yeah {s} {d}",
]

#: Fillers. Generic on purpose: this file is COMMITTED, and the personal
#: vocabulary (`~/.assistant_tools/vocab.json`) holds real people and places.
#: Personalisation belongs at training time from the local store, never baked
#: into a dataset in git.
_WHO = ["Tal", "Sam", "Dana", "Alex", "Jordan", "Casey", "Morgan", "Riley",
        "the team", "my manager", "the client", "mum", "dad", "my brother",
        "the neighbours", "Avery", "Blake", "Harper", "Reese", "Sage"]
_WHERE = ["the office", "home", "the studio", "the clinic", "town",
          "the community centre", "the park", "the hall", "theirs", "the cafe"]
_DAY = ["today", "tomorrow", "on monday", "on tuesday", "next week",
        "this weekend", "on the 14th", "next month", "on friday", "thursday",
        "the day after tomorrow", "in two weeks", "on sunday", "next thursday"]
_TIME = ["at 7", "at 7am", "at half past nine", "in the morning",
         "in the afternoon", "this evening", "at noon", "at 6pm",
         "first thing", "late afternoon", "at quarter to five", "at midday"]


def _fill(frame: str, subject: str, rng: random.Random) -> str:
    return (frame.replace("{s}", subject)
                 .replace("{who}", rng.choice(_WHO))
                 .replace("{where}", rng.choice(_WHERE))
                 .replace("{d}", rng.choice(_DAY))
                 .replace("{t}", rng.choice(_TIME)))


#: SUBJECTS per task tag. MULTI-label: a subject may belong to several.
TASK_SUBJECTS: "dict[str, list[str]]" = {
    "Groceries": [
        "milk", "eggs", "sourdough", "zucchini", "aubergine", "pak choi",
        "gochujang", "tahini", "oat milk", "kefir", "halloumi", "za'atar",
        "pomegranate", "chickpeas", "rocket", "sumac", "harissa", "kimchi",
        "cold brew", "gatorade", "canola oil", "basmati", "tofu", "miso",
        "parmesan", "anchovies", "capers", "sriracha", "quinoa", "lentils",
        "persimmons", "clementines", "dates", "pistachios", "feta",
        "bananas", "avocados", "spinach", "kale", "broccoli", "cauliflower",
        "courgettes", "sweet potatoes", "red onions", "garlic", "ginger",
        "chillies", "coriander", "parsley", "dill", "mint", "basil", "lemons",
        "limes", "oranges", "apples", "pears", "berries", "blueberries",
        "raspberries", "mango", "pineapple", "melon", "grapes", "cucumber",
        "peppers", "mushrooms", "leeks", "celery", "carrots", "potatoes",
        "rice", "pasta", "couscous", "bulgur", "flour", "sugar", "honey",
        "olive oil", "vinegar", "soy sauce", "mustard", "mayonnaise",
        "ketchup", "yoghurt", "butter", "cheddar", "mozzarella",
        "cream cheese", "chicken", "salmon", "tuna", "mince", "sausages",
        "bacon", "bread", "pitta", "tortillas", "crackers", "cereal",
        "granola", "coffee beans", "tea bags", "orange juice",
        "sparkling water", "washing up liquid", "kitchen roll", "bin bags",
        "cling film", "foil", "toothpaste", "shampoo", "soap",
        "laundry detergent", "fabric softener", "nappies", "cat food",
        "dog food",
    ],
    "Coursework": [
        "the problem set", "the lab report", "chapter 4", "the essay draft",
        "the reading list", "the literature review", "the seminar notes",
        "the past papers", "the dissertation outline", "the group project",
        "the flashcards", "the revision timetable", "the bibliography",
        "the poster", "the presentation slides", "the exam checklist",
        "the stacks exercise", "the assignment brief", "the coursework upload",
        "the reading for week 5", "the seminar prep",
        "the tutorial questions", "the lab writeup", "the data analysis",
        "the methodology section", "the results chapter",
        "the discussion section", "the abstract", "the conclusion",
        "the appendix", "the references", "the citation check",
        "the plagiarism check", "the submission form", "the cover sheet",
        "the extension request", "the mitigating circumstances form",
        "the feedback review", "the marking rubric", "the group allocation",
        "the peer assessment", "the presentation script", "the demo prep",
        "the poster draft", "the ethics application", "the consent forms",
        "the participant recruitment", "the pilot study", "the transcription",
        "the coding frame", "the thematic analysis",
        "the statistics homework", "the exam revision plan",
        "the formula sheet",
    ],
    "Errands": [
        "the dry cleaning", "the parcel", "the prescription", "the passport form",
        "the library books", "the recycling", "the car keys", "the spare tyre",
        "the birthday card", "the printer cartridge", "the batteries",
        "the light bulbs", "the shoe repair", "the watch battery",
        "the parking permit", "the council form", "the key cutting",
        "the passport photos", "the visa documents",
        "the birth certificate copy", "the bank letter",
        "the proof of address", "the utility bill copy", "the p60",
        "the reference letter", "the dry cleaning ticket",
        "the shoe repair slip", "the watch strap", "the phone case",
        "the screen protector", "the charging cable", "the extension lead",
        "the smoke alarm batteries", "the doorbell battery", "the fuse",
        "the lightbulbs for the hall", "the curtain rail",
        "the picture hooks", "the wall plugs", "the sandpaper",
        "the wood glue", "the garden compost", "the plant pots",
        "the bird feed", "the cat litter", "the flea treatment",
        "the vet paperwork", "the parking ticket appeal",
        "the congestion charge", "the toll receipt",
        "the train ticket collection", "the theatre tickets",
    ],
    "Work": [
        "the invoice", "the timesheet", "the handover doc", "the expenses",
        "the client brief", "the deck", "the retro notes", "the standup update",
        "the contract draft", "the onboarding checklist", "the release notes",
        "the incident report", "the vendor quote", "the payroll file",
    ],
}

TASK_FRAMES = [
    "{s}", "buy {s}", "get {s}", "pick up {s}", "grab {s}",
    "order {s}", "collect {s}", "drop off {s}", "sort out {s}", "finish {s}",
    "do {s}", "chase up {s}", "sort {s}", "deal with {s}", "handle {s}",
    "add {s} to the list", "put {s} on the list", "remind me to get {s}",
    "remember {s}", "don't forget {s}", "need to get {s}",
    "{s} {d}", "buy {s} {d}", "get {s} before {d}", "{s} by {d}",
    "can you add {s}", "please add {s} to my list", "stick {s} on the list",
    "uh {s}", "{s} — don't forget", "and {s}", "also {s}",
]

#: Subjects that legitimately carry TWO tags — multi-label is not decoration.
TASK_MULTI = {
    "the birthday card": ["Errands", "Groceries"],
    "the printer cartridge": ["Errands", "Work"],
    "the coursework upload": ["Coursework", "Work"],
}


def _split_vocab(subjects: "list[str]", rng: random.Random, test_frac=0.3):
    """Hold subjects out, not rows.

    THE WHOLE POINT. Splitting rows would put "gym session on tuesday" in train
    and "gym session at 7" in test, and every model would score ~100% by
    remembering the noun. Splitting SUBJECTS means the test half asks the only
    question worth asking: does this generalise to a word nobody typed in?
    """
    pool = sorted(subjects)
    rng.shuffle(pool)
    cut = max(1, int(len(pool) * test_frac))
    return pool[cut:], pool[:cut]          # (train subjects, test subjects)


def build_events(seed: int = 5, per_class: int = 1000) -> list:
    """`per_class` rows for every category, spread evenly over its subjects.

    Diversity comes from the SUBJECT first and the frame second: 1000 rows over
    78 subjects is ~13 phrasings each, drawn from 38 frames across five
    registers. Multiplying frames alone would manufacture near-duplicates and
    an inflated board.
    """
    rng = random.Random(seed)
    rows = []
    for cat, subjects in EVENT_SUBJECTS.items():
        train_s, test_s = _split_vocab(subjects, rng)
        for split, pool in (("train", train_s), ("test", test_s)):
            if not pool:
                continue
            want = int(per_class * (len(pool) / len(subjects)))
            seen = set()
            per = max(1, want // len(pool)) + 2
            for subj in pool:
                frames = list(EVENT_FRAMES)
                rng.shuffle(frames)
                made = 0
                for frame in frames:
                    if made >= per:
                        break
                    text = _fill(frame, subj, rng)
                    if text in seen:
                        continue
                    seen.add(text)
                    made += 1
                    rows.append({"text": text, "label": cat,
                                 "subject": subj, "split": split})
    rng.shuffle(rows)
    return rows


def build_tasks(seed: int = 5, per_class: int = 1000) -> list:
    """`per_class` rows per tag, spread evenly over its subjects. Same shape as
    `build_events`: subject diversity first, frames second."""
    rng = random.Random(seed)
    rows = []
    for tag, subjects in TASK_SUBJECTS.items():
        train_s, test_s = _split_vocab(subjects, rng)
        for split, pool in (("train", train_s), ("test", test_s)):
            if not pool:
                continue
            want = int(per_class * (len(pool) / len(subjects)))
            per = max(1, want // len(pool)) + 2
            seen = set()
            for subj in pool:
                labels = TASK_MULTI.get(subj, [tag])
                frames = list(TASK_FRAMES)
                rng.shuffle(frames)
                made = 0
                for frame in frames:
                    if made >= per:
                        break
                    text = _fill(frame, subj, rng)
                    if text in seen:
                        continue
                    seen.add(text)
                    made += 1
                    rows.append({"text": text, "labels": sorted(set(labels)),
                                 "subject": subj, "split": split})
    rng.shuffle(rows)
    return rows


def main() -> int:
    import collections
    for rows, out, key in ((build_events(), EVENTS_OUT, "label"),
                           (build_tasks(), TASKS_OUT, "labels")):
        with out.open("w") as fh:
            for r in rows:
                fh.write(json.dumps(r, sort_keys=True) + "\n")
        per = collections.Counter()
        for r in rows:
            for lab in ([r[key]] if key == "label" else r[key]):
                per[lab] += 1
        tr = sum(1 for r in rows if r["split"] == "train")
        print(f"{len(rows):5d} rows -> {out.name}   train {tr} / test {len(rows)-tr}")
        print("      " + "  ".join(f"{k} {v}" for k, v in sorted(per.items())))
        # Vocabulary overlap MUST be zero or the split is a lie.
        trs = {r["subject"] for r in rows if r["split"] == "train"}
        tes = {r["subject"] for r in rows if r["split"] == "test"}
        print(f"      subject overlap train∩test: {len(trs & tes)}  "
              f"({len(trs)} train subjects, {len(tes)} test)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
