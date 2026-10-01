"""The phone's Easter egg (Settings ▸ Easter egg): which words summon what,
when an utterance is nothing BUT magic words (played, and never sent to the
Mac), and that every built-in graphic renders in every motion.

Swift compiled on its own, as the other phone ports are
(`test_offline_protocol.py`, `test_label_export.py`); skipped off the Mac.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
EGG = ROOT / "MACalendar-iOS/MACalendar-iOS/EasterEgg"
TOOLS = ROOT / "MACalendar-iOS/Tools"
# The platform-neutral Easter-egg files — what the Mac helper compiles too.
SHARED = ["EggArt.swift", "EggFigures.swift", "EggJewish.swift", "EggEffects.swift", "EggCatalog.swift",
          "EggRules.swift", "EggStage.swift", "EggTrails.swift", "EggPuppet.swift", "EggLoader.swift",
          "EggWordBank.swift", "EggSymbol.swift", "EggOnDevice.swift", "EggImageCore.swift"]

pytestmark = pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("swiftc"),
                                reason="needs the Swift compiler (the Mac; CI's Linux runner has none)")


@pytest.fixture(scope="module")
def words(tmp_path_factory):
    exe = tmp_path_factory.mktemp("egg") / "words"
    subprocess.run(["swiftc", "-O", "-parse-as-library", str(TOOLS / "egg_words.swift"),
                    *[str(EGG / f) for f in SHARED], "-o", str(exe)], check=True, capture_output=True)

    def run(lines):
        out = subprocess.run([str(exe)], input="\n".join(lines) + "\n", capture_output=True,
                             text=True, check=True).stdout.splitlines()
        return [json.loads(l) for l in out]
    return run


CASES = {
    # said                                         ids                               bare
    "dragon":                                      (["dragon"], True),
    "Dragon!":                                     (["dragon"], True),
    "a dragon":                                    (["dragon"], True),
    "wow look, a unicorn":                         (["unicorn"], True),
    "dragon done":                                 (["dragon"], True),        # a spoken stop word
    "dogs":                                        (["dog"], True),           # plurals
    "puppies":                                     (["dog"], True),
    "wolves":                                      (["wolf"], True),
    "fairies":                                     (["fairy"], True),
    "dog dog dog":                                 (["dog", "dog", "dog"], True),   # a pack
    "german shepherd":                             (["dog"], True),           # one dog, not a dog and a stray
    "walk the dog at 5":                           (["dog"], False),
    "walk my dog's lead to the vet":               (["dog"], False),          # possessive
    "remind me to take the car and the dog to the vet": (["car", "dog"], False),
    "dragon and unicorn":                          (["dragon", "unicorn"], True),
    "dentist tomorrow at 3":                       ([], False),
    "cathedral tour":                              ([], False),               # "cat" is a whole word only
    "carpet cleaning":                             ([], False),
    "doggedly finish the report":                  ([], False),
    "birthday party saturday":                     (["confetti"], False),
    "fireworks":                                   (["fireworks"], True),
    "lulav and etrog":                             (["lulav", "etrog"], True),
    "dinner in the sukkah at 7":                   (["sukkah"], False),
    "chag sameach sukkot":                         (["sukkah"], False),
    "buy hamantaschen for purim":                  (["hamantasch", "mask"], False),
    "three dreidels":                              (["dreidel", "dreidel", "dreidel"], True),
    "light the menorah":                           (["menorah"], False),
    "":                                            ([], False),
}


def test_words_summon_the_right_things(words):
    said = list(CASES)
    got = words(said)
    wrong = [(s, g, CASES[s]) for s, g in zip(said, got) if (g["ids"], g["bare"]) != CASES[s]]
    assert not wrong, wrong


PACKS = {
    # said                          with plurals bringing 3           says a group word
    "dogs":                         (["dog", "dog", "dog"], False),
    "two dogs":                     (["dog", "dog"], False),
    "a couple of dragons":          (["dragon", "dragon"], False),
    "5 cats":                       (["cat", "cat", "cat", "cat", "cat"], False),
    "a dog":                        (["dog"], False),
    "wolves":                       (["wolf", "wolf", "wolf"], False),
    "puppies and a cat":            (["dog", "dog", "dog", "cat"], False),
    "a pack of dogs":               (["dog", "dog", "dog"], True),
    "a flock of eagles":            (["eagle", "eagle", "eagle"], True),
    "fireworks":                    (["fireworks"], False),     # a keyword that is plural already
    "walk the dogs at 5":           (["dog", "dog", "dog"], False),
}


def test_plurals_bring_a_pack_and_group_words_are_heard(words):
    said = list(PACKS)
    got = words(said)
    wrong = [(s, g, PACKS[s]) for s, g in zip(said, got) if (g["pack"], g["group"]) != PACKS[s]]
    assert not wrong, wrong
    bare = dict(zip(said, (g["bare"] for g in got)))
    assert bare["a pack of dogs"] and bare["a flock of eagles"]       # a group word is not a command
    assert not bare["walk the dogs at 5"]


def test_every_graphic_renders_in_every_motion(tmp_path):
    """All 40 graphics x all 17 motions, cycling through every trail, both
    directions, and a drawn path — drawn through the overlay's own renderer."""
    exe = tmp_path / "render"
    subprocess.run(["swiftc", "-O", "-parse-as-library", str(TOOLS / "egg_render.swift"),
                    *[str(EGG / f) for f in SHARED],
                    "-o", str(exe)], check=True, capture_output=True)
    png = tmp_path / "all.png"
    out = subprocess.run([str(exe), str(png)], capture_output=True, text=True, check=True)
    assert int(out.stdout.strip()) == 40
    assert png.stat().st_size > 50_000
    puppets = tmp_path / "all-puppets.png"          # every photo rig: walk, roll, flap, hop, still
    assert puppets.exists() and puppets.stat().st_size > 20_000
    symbols = tmp_path / "all-symbols.png"          # the user's own emoji, flags and SF Symbols
    assert symbols.exists() and symbols.stat().st_size > 20_000
    # The car picture's wheels are drawn at (58,156) and (158,156), r 17, in a
    # 200 box: the silhouette reading has to land on them.
    found = [[float(x) for x in w.split(",")] for w in out.stderr.strip().split(";")]
    assert len(found) == 2, found
    for (cx, cy, r), (ex, ey) in zip(found, [(0.29, 0.78), (0.79, 0.78)]):
        assert abs(cx - ex) < 0.05 and abs(cy - ey) < 0.05 and 0.05 <= r <= 0.12, found


def test_every_builtin_is_a_real_graphic():
    """The catalog names a figure or effect for each built-in; a typo would
    leave an object that plays nothing."""
    src = (EGG / "EggCatalog.swift").read_text()
    figures = (EGG / "EggFigures.swift").read_text()
    effects = (EGG / "EggEffects.swift").read_text()
    import re
    block = src[src.index("static let builtins"):src.index("static func defaults")]
    ids = re.findall(r'\("([a-z]+)", "', block)
    assert len(ids) == 40
    cases = set(re.findall(r"case ([a-z, ]+)\n", figures + effects))
    names = {n.strip() for c in cases for n in c.split(",")}
    assert set(ids) <= names, set(ids) - names


FESTIVAL_DAYS = {
    # Gregorian day (noon)  festivals on           why
    "2026-09-30": {"sukkot"},                      # 19 Tishrei 5787, chol hamoed
    "2026-10-03": {"sukkot", "simchat-torah", "shabbat"},   # 22 Tishrei, a Saturday
    "2026-09-12": {"rosh-hashanah", "shabbat"},    # 1 Tishrei 5787
    "2026-12-06": {"chanukah"},                    # 26 Kislev
    "2026-03-03": {"purim"},                       # 14 Adar 5786 (a plain year)
    "2027-03-23": {"purim"},                       # 14 Adar II 5787 (a leap year)
    "2027-02-21": set(),                           # 14 Adar I 5787 (Purim Katan): not Purim
    "2027-04-22": {"pesach"},                      # 15 Nisan 5787
    "2027-06-11": {"shavuot"},                     # 6 Sivan (a Friday: Shabbat is added below)
    "2026-07-15": set(),                           # an ordinary Wednesday
}


def test_festival_seasons_land_on_the_right_days(tmp_path):
    exe = tmp_path / "festivals"
    subprocess.run(["swiftc", "-O", "-parse-as-library", str(TOOLS / "egg_festivals.swift"),
                    *[str(EGG / f) for f in SHARED],
                    "-o", str(exe)], check=True, capture_output=True)
    out = subprocess.run([str(exe)], input="\n".join(FESTIVAL_DAYS) + "\n", capture_output=True,
                         text=True, check=True).stdout.splitlines()
    got = {l.split(" ")[0]: set(filter(None, (l.split(" ") + [""])[1].split(","))) for l in out}
    import datetime
    wrong = {}
    for day, want in FESTIVAL_DAYS.items():
        want = set(want) - {"shabbat"}
        if datetime.date.fromisoformat(day).weekday() in (4, 5):   # Friday, Saturday
            want |= {"shabbat"}
        if got.get(day) != want:
            wrong[day] = (got.get(day), want)
    assert not wrong, wrong


RULES = [
    # (case, expected ids, together, bare)
    ({"text": "dragon", "bare": True}, ["dragon"], True, True),
    ({"text": "walk the dog at 5", "bare": True}, [], True, False),            # a command: not bare
    ({"text": "walk the dog at 5", "bare": False}, ["dog"], True, False),
    ({"text": "walk the dog at 5", "bare": False, "settings": {"trigger": "onItsOwn"}}, [], True, False),
    ({"text": "dragon", "bare": True, "settings": {"trigger": "inCommand"}}, [], True, False),
    ({"text": "dragon", "bare": True, "settings": {"enabled": False}}, [], True, False),
    # Held back by quiet hours / cooldown / chance: still bare, so still not sent.
    ({"text": "dragon", "bare": True, "date": "2026-07-15 23:30", "settings": {"quietHours": True}}, [], True, True),
    ({"text": "dragon", "bare": True, "date": "2026-07-15 12:00", "settings": {"quietHours": True}}, ["dragon"], True, True),
    ({"text": "dragon", "bare": True, "lastPlayedAgo": 10, "settings": {"cooldown": 60}}, [], True, True),
    ({"text": "dragon", "bare": True, "lastPlayedAgo": 90, "settings": {"cooldown": 60}}, ["dragon"], True, True),
    ({"text": "dragon", "bare": True, "roll": 2, "settings": {"chance": 3}}, [], True, True),
    ({"text": "dragon", "bare": True, "roll": 1, "settings": {"chance": 3}}, ["dragon"], True, True),
    # The Jewish set: off, and in season only.
    ({"text": "lulav", "bare": True, "settings": {"jewish": False}}, [], True, False),
    ({"text": "lulav", "bare": True, "date": "2026-07-15 12:00", "settings": {"jewishInSeason": True}}, [], True, False),
    ({"text": "lulav", "bare": True, "date": "2026-09-30 12:00", "settings": {"jewishInSeason": True}}, ["lulav"], True, True),
    # Group words.
    ({"text": "dog and cat", "bare": True, "settings": {"group": "onGroupWord"}}, ["dog", "cat"], False, True),
    ({"text": "a pack of dog and cat", "bare": True, "settings": {"group": "onGroupWord"}}, ["dog", "cat"], True, True),
    ({"text": "dog and cat", "bare": True, "settings": {"group": "oneAfterAnother"}}, ["dog", "cat"], False, True),
]


def test_the_shared_decisions(tmp_path):
    """EggRules is what the phone AND the Mac helper decide with."""
    exe = tmp_path / "rules"
    subprocess.run(["swiftc", "-O", "-parse-as-library", str(TOOLS / "egg_rules.swift"),
                    *[str(EGG / f) for f in SHARED],
                    "-o", str(exe)], check=True, capture_output=True)
    out = subprocess.run([str(exe)], input="\n".join(json.dumps(c) for c, *_ in RULES) + "\n",
                         capture_output=True, text=True, check=True).stdout.splitlines()
    got = [json.loads(l) for l in out]
    wrong = [(c, g) for (c, ids, tog, bare), g in zip(RULES, got)
             if g["ids"] != ids or g["bare"] != bare or (ids and g["together"] != tog)]
    assert not wrong, wrong


def test_every_loading_screen_style_draws(tmp_path):
    """The loading screen (TASKS 48): every style, with one to four objects."""
    exe = tmp_path / "loaders"
    subprocess.run(["swiftc", "-O", "-parse-as-library", str(TOOLS / "egg_loaders.swift"),
                    *[str(EGG / f) for f in SHARED],
                    "-o", str(exe)], check=True, capture_output=True)
    png = tmp_path / "loaders.png"
    out = subprocess.run([str(exe), str(png)], capture_output=True, text=True, check=True)
    assert int(out.stdout.strip()) == 6
    assert png.stat().st_size > 30_000


# What the models actually returned in the 2026-09-30 probes, and what the
# user should be shown from it (TASKS 49).
CLEAN = [
    ({"words": ["german shepherd", "german", "shepherd", "breed", "dog breed", "hound", "pooch", "pup", "doggy"],
      "name": "German Shepherd", "existing": ["dog", "puppy", "german shepherd"], "count": 10},
     ["breed", "dog breed", "hound", "pooch", "pup", "doggy"]),
    ({"words": ["dragon"] * 8, "name": "Dragon", "existing": ["dragon"], "count": 10}, []),
    ({"words": ["automobile", "motor vehicle", "motor car", "automobile", "motor vehicle"], "name": "Car",
      "existing": ["car"], "count": 10}, ["automobile", "motor vehicle", "motor car"]),
    ({"words": ["A type of dinosaur", "a member of theropod dinosaurs", "The King", "T-Rex!"], "name": "Rex",
      "existing": [], "count": 10}, ["king", "t-rex"]),
    ({"words": ["hootie", "moonbird", "night hunter", "silent flyer", "owlie"], "name": "Owl",
      "existing": ["owl"], "count": 3}, ["hootie", "moonbird", "night hunter"]),
    ({"words": ["a really very long phrase indeed", "booth"], "name": "Sukkah", "existing": ["sukkah"], "count": 5},
     ["booth"]),
]


def test_suggested_words_are_cleaned_before_anyone_sees_them(tmp_path):
    exe = tmp_path / "clean"
    subprocess.run(["swiftc", "-O", "-parse-as-library", str(TOOLS / "egg_clean.swift"),
                    *[str(EGG / f) for f in SHARED], "-o", str(exe)], check=True, capture_output=True)
    out = subprocess.run([str(exe)], input="\n".join(json.dumps(c) for c, _ in CLEAN) + "\n",
                         capture_output=True, text=True, check=True).stdout.splitlines()
    got = [json.loads(l) for l in out]
    wrong = [(c["name"], g, want) for (c, want), g in zip(CLEAN, got) if g != want]
    assert not wrong, wrong


def _bank(tmp_path, cases):
    exe = tmp_path / "bank"
    subprocess.run(["swiftc", "-O", "-parse-as-library", str(TOOLS / "egg_bank.swift"),
                    *[str(EGG / f) for f in SHARED], "-o", str(exe)], check=True, capture_output=True)
    out = subprocess.run([str(exe)], input="\n".join(json.dumps(c) for c in cases) + "\n",
                         capture_output=True, text=True, check=True).stdout.splitlines()
    return [json.loads(l) for l in out]


def test_the_word_bank_tops_up_to_the_count_with_names_and_adjective_phrases(tmp_path):
    """The fallback (Gil, 2026-09-30): when no model answers, or too few words
    come back, the built-in list fills the count — at random, never a word the
    object has, and partly adjective phrases ("baby dragon")."""
    cases = [
        {"words": [], "id": "dragon", "name": "Dragon", "existing": ["dragon"], "count": 10, "seed": 1},
        {"words": ["wyvern"], "id": "dragon", "name": "Dragon", "existing": ["dragon"], "count": 10, "seed": 2},
        {"words": [], "id": "dog", "name": "German Shepherd", "existing": ["dog", "puppy"], "count": 15, "seed": 3},
        {"words": [], "id": "custom-x", "name": "Rex", "existing": ["dog"], "count": 8, "seed": 4},
        {"words": ["a", "b", "c"], "id": "cat", "name": "Cat", "existing": ["cat"], "count": 3, "seed": 5},
        {"words": [], "id": "dragon", "name": "Dragon", "existing": ["dragon"], "count": 10, "seed": 9},
    ]
    got = _bank(tmp_path, cases)
    for c, g in zip(cases[:4], got[:4]):
        words = g["words"]
        assert len(words) == c["count"], (c["name"], words)
        assert len(set(words)) == len(words), words
        assert not set(words) & set(c["existing"]), words
        assert any(" " + (c["existing"][0]) in w for w in words), f"no adjective phrase: {words}"
    assert got[1]["words"][0] == "wyvern" and got[1]["fromBank"] == 9          # the model's words come first
    assert got[3]["words"] and all("rex" not in w or w.endswith("dog") for w in got[3]["words"])  # Rex is a dog
    assert got[4] == {"words": ["a", "b", "c"], "fromBank": 0}                 # enough already: untouched
    assert got[0]["words"] != got[5]["words"]                                  # the randomness


def test_one_word_summons_one_thing(tmp_path):
    """Gil: the same word on two objects is a conflict — ask to keep or move.
    A word and its plural are the same word ("dog" / "dogs")."""
    exe = tmp_path / "conflicts"
    subprocess.run(["swiftc", "-O", "-parse-as-library", str(TOOLS / "egg_conflicts.swift"),
                    *[str(EGG / f) for f in SHARED], "-o", str(exe)], check=True, capture_output=True)
    got = json.loads(subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout)
    assert got["same"] == [True, True, False]
    assert got["owner_cat_for_dog"] == "cat"
    assert got["owner_dogs_for_cat"] in ("dog", "rex")
    assert got["owner_cat_for_cat"] is None                       # your own word is not a conflict
    found = {c["word"]: sorted(c["ids"]) for c in got["conflicts"]}
    assert found.get("dog") == ["dog", "rex"]                     # dog / dogs
    assert found.get("puppy") == ["dog", "puppies"]               # puppy / puppies
    assert "cat" not in found


def test_suggestions_never_offer_a_word_another_object_has(tmp_path):
    """Gil: drop conflicting words deterministically and top up from the bank."""
    taken = ["hound", "pooch", "doggo", "mutt", "canine", "alsatian", "labrador", "retriever", "poodle", "beagle",
             "husky", "collie", "terrier", "good boy", "woof", "baby dog", "cat"]
    got = _bank(tmp_path, [
        {"words": ["hound", "wolfhound", "pooch"], "id": "dog", "name": "German Shepherd",
         "existing": ["dog", "puppy"], "count": 8, "taken": taken, "seed": 1},
        {"words": ["dogs"], "id": "dog", "name": "German Shepherd", "existing": ["puppy"], "count": 3,
         "taken": ["dog"], "seed": 2},
    ])
    words = got[0]["words"]
    assert words[0] == "wolfhound" and len(words) == 8, words          # model's free word kept, first
    assert not set(words) & set(taken), words                          # none of the taken ones
    assert "dogs" not in got[1]["words"]                               # a plural of a taken word is taken


# Real photographs that are not the user's: Apple's simulator sample set and
# two that ship with Python packages. Whichever exist on this Mac are used.
_SAMPLES = [
    *sorted(pathlib.Path("/Library/Developer/CoreSimulator/Volumes").glob(
        "*/Library/Developer/CoreSimulator/Profiles/Runtimes/*.simruntime/Contents/Resources/"
        "SampleContent/Media/DCIM/100APPLE/IMG_000[26].*"))[:2],
    *sorted(pathlib.Path("/Library/Frameworks/Python.framework/Versions").glob(
        "*/lib/python*/site-packages/ultralytics/assets/*.jpg"))[:2],
    *sorted(pathlib.Path("/Library/Frameworks/Python.framework/Versions").glob(
        "*/lib/python*/site-packages/sklearn/datasets/images/*.jpg"))[:2],
]


@pytest.mark.skipif(len(_SAMPLES) < 3, reason="no real sample photographs on this machine")
def test_real_photos_through_the_photo_pipeline(tmp_path):
    """TASKS 44/47: the photo path had only met drawn stand-ins. Run on real
    photographs (`Tools/egg_photo.swift`, the code the phone and the Mac
    share) it found the anime look turning them nearly black — the ink traced
    every texture as an edge, and the flattening ran in linear light. Each
    photo with a subject must cut out, keep 75%+ of its brightness when
    styled, and take a hand-drawn loop."""
    exe = tmp_path / "photo"
    subprocess.run(["swiftc", "-O", "-parse-as-library", str(TOOLS / "egg_photo.swift"),
                    *[str(EGG / f) for f in SHARED], "-o", str(exe)], check=True, capture_output=True)
    out = subprocess.run([str(exe), str(tmp_path / "sheet.png"), *map(str, _SAMPLES)],
                         capture_output=True, text=True, check=True, timeout=600)
    rows = [json.loads(l) for l in out.stdout.splitlines()]
    assert len(rows) == len(_SAMPLES)
    cut = [r for r in rows if r["cutout"]]
    assert len(cut) >= len(rows) // 2, rows             # landscapes have no subject; the rest do
    for r in cut:
        assert r["anime"] and r["luma_anime"] >= 0.75 * r["luma_cut"], r
    assert all(r["lasso"] for r in rows), rows
    by = {r["photo"]: r for r in rows}
    if "bus.jpg" in by:
        assert by["bus.jpg"]["rig"] == "roll"           # a vehicle rolls
    assert (tmp_path / "sheet.png").stat().st_size > 50_000
