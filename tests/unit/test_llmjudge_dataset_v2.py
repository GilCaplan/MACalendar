"""The v2 judge set's invariants — the ones a regeneration could quietly break.

The generator is deterministic and model-free, so these run the real catalog
rather than a fixture: `build_commands()` is a second's work and a fixture of a
dataset generator is a second copy of the thing under test.

What is pinned here, and why each one is a defect that has happened somewhere
in this project before:

    DETERMINISM     a generated corpus whose regeneration differs from the
                    committed file cannot be reviewed or reproduced.
    FAMILY SPLIT    the split unit is the family; a family on both sides turns
                    the test half into a memorisation check.
    REACHABILITY    a gold value the words cannot reach is one no parser could
                    produce, so a board built on it measures the dataset.
    VOICE INVARIANCE  the seven renderings of a command share one gold. Five
                    utterances diverged during development because a noise
                    operation ran before a recogniser one and broke the
                    subject lookup on some voices only.
    Q43             a comma run with NO conjunction is ONE ask. That is a
                    RULING (DEVQA Q43, 2026-09-22), and a generator that
                    quietly makes it three would teach the judge the opposite
                    of what Gil decided.
"""
from __future__ import annotations

import collections
import json

import pytest

from assistant.engine.llmjudge.datasets.v2 import (
    banks, damage, generate_v2 as gen, voices)


@pytest.fixture(scope="module")
def rows():
    return gen.build_commands()


def _gold(row):
    """Everything the gold claims, with the RENDERING left out — the frame, the
    clock's spoken form and the article habit are the voice's business."""
    return [(a["action"], a["kind"], a["title"], a["intended_title"],
             a["date_phrase"], a["clock"], a["end_clock"], a["recurrence"],
             tuple(a["recur_days"]), a["anaphor"], a["bare_kind"])
            for a in row["asks"]]


# ---------------------------------------------------------------------------

def test_the_generator_is_deterministic_under_its_seed(rows):
    again = gen.build_commands()
    assert json.dumps(rows, sort_keys=True) == json.dumps(again, sort_keys=True)


def test_a_different_seed_produces_a_different_set(rows):
    other = gen.build_commands(seed=gen.SEED + 1)
    assert {r["text"] for r in other} != {r["text"] for r in rows}


def test_no_family_is_in_both_halves(rows):
    splits = collections.defaultdict(set)
    for r in rows:
        splits[r["family"]].add(r["split"])
    leaked = [f for f, s in splits.items() if len(s) > 1]
    assert not leaked, f"families on both sides: {leaked[:5]}"


def test_the_halves_share_no_command_text(rows):
    train = {r["text"] for r in rows if r["split"] == "train"}
    test = {r["text"] for r in rows if r["split"] == "test"}
    assert not (train & test)


def test_the_split_is_a_pure_function_of_the_family(rows):
    by_family = {}
    for r in rows:
        by_family.setdefault(r["family"], r["split"])
    for shapes, joiner, list_n in gen.families():
        fam = gen.family_id(shapes, joiner, list_n)
        assert gen.split_of(fam, shapes, joiner) == by_family[fam]


def test_both_halves_are_big_enough_to_compare(rows):
    per = collections.Counter(r["split"] for r in rows)
    assert min(per.values()) > 0.35 * len(rows)


# ---------------------------------------------------------------------------

def test_every_gold_title_is_reachable_from_the_words(rows):
    """`assistant/intent/correction.py`'s rule: every content word of a title
    must be in the transcript. This is the invariant the recogniser damage
    operations are written AROUND — they move the gold with the words, rather
    than leaving a gold nobody could have said."""
    from assistant.intent import correction

    bad = []
    for r in rows:
        words = correction._words(r["text"])
        for a in r["asks"]:
            if not a["title"]:
                continue
            content = correction._content(a["title"])
            if not content or not all(w in words for w in content):
                bad.append((r["id"], a["title"], r["text"]))
    assert not bad, f"{len(bad)} unreachable titles, e.g. {bad[:3]}"


def test_every_gold_clock_is_on_the_five_minute_grid(rows):
    from assistant.intent import correction
    for r in rows:
        for a in r["asks"]:
            for field in ("clock", "end_clock"):
                if a[field]:
                    assert correction._on_spoken_grid(a[field]), (r["id"], a[field])


def test_every_stated_day_and_cadence_is_in_the_words(rows):
    from assistant.intent import correction
    for r in rows:
        words = correction._words(r["text"])
        for a in r["asks"]:
            if a["date_phrase"]:
                for w in correction._content(a["date_phrase"]):
                    assert w in words, (r["id"], a["date_phrase"], r["text"])
            if a["recurrence"]:
                assert correction._CADENCE.search(r["text"]), r["id"]


def test_the_item_words_are_the_action_words_without_the_time(rows):
    """`Item.text` is the action words and `Item.time` is the time reference as
    spoken — `decompose_validate` resolves the second. An item whose text
    swallowed its own time resolves nothing, which is how the first draft of
    this generator produced 5,000 rows with no clock on any of them."""
    for r in rows:
        for a in r["asks"]:
            item = a["item"]
            if item["time"]:
                assert item["time"] not in item["text"], (r["id"], item)


# ---------------------------------------------------------------------------

def test_one_command_has_one_gold_in_all_seven_voices(rows):
    by_utterance = collections.defaultdict(list)
    for r in rows:
        by_utterance[r["utterance"]].append(r)
    for utterance, group in by_utterance.items():
        assert {r["voice"] for r in group} == set(voices.VOICE_IDS), utterance
        golds = {json.dumps(_gold(r)) for r in group}
        assert len(golds) == 1, (
            f"{utterance}: the gold moved with the voice\n" +
            "\n".join(f"  {r['voice']}: {r['text']}" for r in group))


def test_every_voice_and_every_damage_operation_is_in_both_halves(rows):
    voice_splits = collections.defaultdict(set)
    op_splits = collections.defaultdict(set)
    for r in rows:
        voice_splits[r["voice"]].add(r["split"])
        for op in r["damage"]:
            op_splits[op].add(r["split"])
    for name in voices.VOICE_IDS:
        assert voice_splits[name] == {"train", "test"}, name
    for name in damage.OPERATIONS:
        assert op_splits[name] == {"train", "test"}, name


def test_undamaged_rows_exist_and_carry_no_operation(rows):
    clean = [r for r in rows if not r["damage"]]
    assert len(clean) > 0.2 * len(rows)
    assert all(r["clean_text"] is None for r in clean)


def test_only_the_declared_operations_move_the_gold(rows):
    """A row whose gold title differs from the bank's is a row a GOLD-CHANGING
    operation touched. Anything else moving the gold would be a bug the whole
    set rests on."""
    known = set(banks.EVENT_SUBJECTS) | set(banks.TASK_SUBJECTS)
    kinds = {w for group in banks.KIND_WORDS.values() for w in group}
    for r in rows:
        for a in r["asks"]:
            if a["title"] and a["title"] not in known and a["title"] not in kinds:
                assert set(r["damage"]) & set(damage.GOLD_CHANGING), (
                    r["id"], a["title"], r["damage"])


def test_a_retraction_leaves_its_repeated_ask_out_of_the_gold(rows):
    """The retraction op says an ask twice and cancels the second. The words
    hold both; the gold holds one — which is the whole defect (real usage
    id=223 made four items for two)."""
    rows_with = [r for r in rows if "retraction" in r["damage"]]
    assert rows_with, "no retraction rows at all"
    for r in rows_with:
        assert r["retracted_clause"] is True
        assert len(r["asks"]) == r["n_asks"]
        marker = any(m in r["text"].lower()
                     for m in ("no, i said that", "no i said that",
                               "wait, i said that", "wait i said that"))
        assert marker, r["text"]


def test_a_bare_kind_title_commits_bare(rows):
    """DEVQA Q41/Q42: a bare kind word with the day and the clock COMMITS, so
    the gold title becomes that word and no intended title is claimed — nobody
    ever said one."""
    rows_with = [r for r in rows if "bare_kind_title" in r["damage"]]
    assert rows_with
    kinds = {w for group in banks.KIND_WORDS.values() for w in group}
    for r in rows_with:
        bare = [a for a in r["asks"] if a["bare_kind"]]
        assert bare, r["id"]
        for a in bare:
            assert a["title"] in kinds, (r["id"], a["title"])
            assert a["intended_title"] is None


# ---------------------------------------------------------------------------

def test_a_comma_run_without_a_conjunction_is_one_ask(rows):
    """DEVQA Q43 (RULED 2026-09-22): a comma run with no conjunction is NOT a
    list — "TA, Office Hour, meeting" is one disfluent title, not three events.
    So the gold for this family is ONE ask, whatever the run's length."""
    runs = [r for r in rows if r["joiner"].startswith("comma_run_plain")]
    assert runs, "the catalog has no comma-run family"
    for r in runs:
        assert r["n_asks"] == 1, (r["id"], r["text"])
        assert len(r["asks"]) == 1
        assert " and " not in r["asks"][0]["said"]["subject"], r["text"]
        if not r["damage"]:            # a bare-kind plant replaces the run
            assert r["asks"][0]["said"]["subject"].count(",") >= 1, r["text"]


def test_a_comma_list_with_a_conjunction_is_several_asks(rows):
    """The other half of the same ruling, and the reason the run family is not
    simply "one more ask shape": Gil, 2026-09-20 — a calendar create over a
    LIST of things is several events, which is what
    `findings.COORDINATED_SUBJECT` exists to rewrite."""
    lists = [r for r in rows if r["joiner"].startswith("comma_list_and")]
    assert lists
    for r in lists:
        assert r["n_asks"] == int(r["joiner"][-1]), (r["id"], r["text"])
        assert " and " in r["text"]
        whens = {(a["date_phrase"], a["clock"]) for a in r["asks"]}
        assert len(whens) == 1, "one frame, one when, several things"


def test_the_catalog_is_diverse_enough_to_carry_a_claim(rows):
    """Gil, 2026-09-19: *"1,000 rows from 26 templates is 26 examples with a
    big denominator."* The numbers below are the floor this set is built to,
    not an aspiration — if a future edit drops under them, the set stops being
    able to say what it says."""
    assert len({r["family"] for r in rows}) >= 150
    assert len({"+".join(r["grammar"]) for r in rows}) >= 50
    assert len({r["joiner"] for r in rows}) >= 6
    assert len(damage.OPERATIONS) >= 12
    assert len({r["voice"] for r in rows}) == 7
    assert len({a["said"]["clock_form"] for r in rows for a in r["asks"]
                if a["said"]["clock_form"]}) >= 10
    assert len({a["recurrence"] for r in rows for a in r["asks"]
                if a["recurrence"]}) == 4          # daily/weekly/monthly/yearly
    assert len({r["text"] for r in rows}) > 0.95 * len(rows)


def test_every_recurrence_is_one_of_the_four_cadences(rows):
    for r in rows:
        for a in r["asks"]:
            assert a["recurrence"] in (None, "daily", "weekly", "monthly",
                                       "yearly")
            if a["recur_days"]:
                assert a["recurrence"] == "weekly", (r["id"], a)


# ---------------------------------------------------------------------------
# the generated files, when they are present (they are the deliverable, and a
# stale one is worse than a missing one — CLAUDE.md's "the committed output
# keeps working while the generator rots")
# ---------------------------------------------------------------------------

def _jsonl(path):
    if not path.exists():
        pytest.skip(f"{path.name} not generated")
    return [json.loads(l) for l in path.open() if l.strip()]


def test_the_written_commands_match_the_generator(rows):
    written = _jsonl(gen.COMMANDS)
    assert len(written) == len(rows)
    assert [r["id"] for r in written] == [r["id"] for r in rows]
    assert [r["text"] for r in written] == [r["text"] for r in rows]


def test_every_case_names_a_command_and_a_known_mutation():
    from assistant.engine.llmjudge.datasets.v2 import mutations
    from assistant.engine.llmjudge import findings

    cases = _jsonl(gen.CASES)
    known = {r["id"] for r in _jsonl(gen.COMMANDS)}
    types = {findings.UNGROUNDED_SUBJECT, findings.UNSUPPORTED_FIELD,
             findings.NOT_AN_ASK, findings.COORDINATED_SUBJECT,
             findings.UNSPLIT_SUBJECT}
    for c in cases:
        assert c["command_id"] in known, c["id"]
        assert c["mutation"] in mutations.EXPECT, c["id"]
        assert c["expect"] is None or c["expect"] in types, c
        assert c["defect"] == (c["mutation"] != "clean")


def test_every_mutation_is_on_both_halves_with_enough_rows():
    """Gil, 2026-09-19: 50 or 100 rows is a smoke test, not a measurement. Each
    mutation is planted to n >= 100 a half so its catch rate is a number rather
    than a shrug."""
    cases = _jsonl(gen.CASES)
    per = collections.Counter((c["mutation"], c["split"]) for c in cases)
    for mutation in {m for m, _s in per}:
        for split in ("train", "test"):
            assert per[(mutation, split)] >= 100, (mutation, split,
                                                   per[(mutation, split)])


def test_the_clean_cases_are_a_real_false_flag_pool():
    cases = _jsonl(gen.CASES)
    clean = [c for c in cases if not c["defect"]]
    assert len(clean) > 0.3 * len(cases)


def test_no_case_crosses_the_split_of_its_command():
    commands = {r["id"]: r for r in _jsonl(gen.COMMANDS)}
    for c in _jsonl(gen.CASES):
        assert c["split"] == commands[c["command_id"]]["split"], c["id"]


def test_a_list_merge_is_three_or_more_gold_event_subjects():
    """Cycle 42 (2026-09-22). The list-mode merge used to list the CONVERTER'S
    titles of whatever it had built — a task's verb phrase, a member still
    wearing its frame ("block off the car service"), or only two of three —
    and expected `coordinated_subject` of it. `findings.py` defines that
    finding as "a bare noun list of three or more things", and the reader
    refuses a command verb and a pair on purpose, so the plant was measuring
    its own construction. The members are the asks' gold `said.subject`, all
    events, three or more; a row that cannot supply that is a PLAIN merge
    (expect None), never a wrong expectation."""
    import re
    from assistant.engine.llmjudge import findings
    commands = {r["id"]: r for r in _jsonl(gen.COMMANDS)}
    # A frame LEADS a member ("block off the car service"); anchored at the
    # start so a noun that is also a verb ("the book club") is not a frame.
    frame = re.compile(r"^(i would like|i'd like|could you|would you|can you|"
                       r"please|remind me|schedule|block off|pencil in|book|"
                       r"tell me)\b", re.I)
    listed = [c for c in _jsonl(gen.CASES)
              if c["mutation"] == "merged_asks"
              and c["expect"] == findings.COORDINATED_SUBJECT]
    # 18 across both halves on 2026-09-22: a list needs THREE event asks with
    # subjects in one command, and the grammar mixes kinds. A thin n, said so
    # on the board; a list-of-events family is the way to more, not a looser plant.
    assert len(listed) >= 10, len(listed)
    for c in listed:
        row = commands[c["command_id"]]
        subjects = {a["said"]["subject"] for a in row["asks"]
                    if a["kind"] == "event" and a["said"].get("subject")}
        members = [m.strip() for m in re.split(r",\s*|\s+and\s+", c["plant"]["title"])]
        assert len(members) >= 3, (c["id"], members)
        for m in members:
            assert m in subjects, (c["id"], m, subjects)
            assert not frame.search(m), (c["id"], m)
        assert c["plant"]["title"] in c["plant"]["text"], c["id"]
        assert len(c["plant"]["drop"]) == len(members) - 1, c["id"]
