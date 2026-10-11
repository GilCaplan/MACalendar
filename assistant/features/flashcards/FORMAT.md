# Flashcard set files — the format

This is the contract for anything that makes flashcards for the Flashcards tab:
a person writing a file by hand, an agent asked to "make me flashcards for X",
or the tab's own editor (which exports to the same shape). The running app
serves this file at `GET /flashcards/format`, and every card that gets in by
any route is checked by `assistant/features/flashcards/cardformat.py`, so the
two cannot disagree for long — `tests/unit/test_flashcards.py` imports every
example below.

## The shape

A **subject** holds **sets**; a set holds **cards**. One file is one set:

```yaml
subject: First aid            # the group in the library; created if new
set: Kit contents             # the set's name as shown
set_id: kit-contents          # optional, short; re-importing the same subject+set_id UPDATES the set
lang: en                      # optional; he / ar make the set right-to-left
dir: ltr                      # optional; ltr or rtl (wins over lang)
source: "Red Cross manual, ch. 3"   # optional: where the facts come from
cards:
  - {type: basic, front: "What colour is a sterile dressing pack?", back: Green}
```

…or several sets of one subject in one file:

```yaml
subject: Spanish
lang: es
sets:
  - set: Verbs
    cards: [...]
  - set: Food
    cards: [...]
```

JSON with the same keys works everywhere YAML does.

## Card types

Every card may also carry `tags` (list of words), `page` (where in the source),
`explain` (shown after answering) and `note`. Those four are NOT part of a
card's identity: changing them keeps your progress. Changing anything else
makes it a new card.

```yaml
cards:
  # 1. basic — question and answer. both_ways also asks back -> front.
  - type: basic
    front: Capital of Peru
    back: Lima
    both_ways: true

  # 2. image — a picture, name what it shows.
  - type: image
    image: images/stethoscope.png
    back: Stethoscope
    front: What is this?          # optional prompt

  # 3. cloze — each {{gap}} is its own question, the rest stays visible.
  - type: cloze
    text: "The Eiffel Tower was designed by {{Gustave Eiffel}}'s company and finished in {{1889}}."

  # 4. mc — multiple choice. answer must equal one choice exactly.
  - type: mc
    question: In which year did the Berlin Wall fall?
    choices: ["1961", "1989", "1991", "1979"]
    answer: "1989"
    explain: 9 November 1989.

  # 5. order — put the steps in order. List them in the RIGHT order;
  #    the app shuffles them.
  - type: order
    prompt: Adult CPR, in order
    steps: [Check danger, Check response, Call for help, 30 compressions, 2 breaths]

  # 6. typed — write it out from memory; the app marks the words you missed.
  - type: typed
    front: Write the first verse of the poem
    answer: |-
      first line
      second line

  # 7. occlusion — a labelled picture with the labels hidden.
  #    box = [x, y, width, height] in PERCENT of the picture (0-100),
  #    measured from the top-left corner. Cover the printed label fully.
  - type: occlusion
    image: images/map.jpg
    ask: one_at_a_time            # each label is its own question (default)
                                  # all_at_once: reveal them one by one, graded together
    prompt: Name the hidden place
    labels:
      - {text: Haifa, box: [35.1, 15.3, 6.1, 1.3]}
      - {text: Eilat, box: [40.6, 93.5, 11.7, 1.8], tag: town}
```

| type | required | optional |
|---|---|---|
| basic | front, back | both_ways |
| image | image, back | front, both_ways |
| cloze | text (with at least one `{{…}}`) | |
| mc | question, choices (2-8, distinct), answer | |
| order | prompt, steps (2-20) | |
| typed | front, answer | |
| occlusion | image, labels [{text, box}] | ask, prompt |

An unknown field is an error, not ignored — a typo like `anwser` would
otherwise make a card that silently has no answer.

## Pictures

`image:` is a path relative to the set file. Deliver the pictures one of two ways:

- a **.zip** holding the set file and its pictures at those paths, or
- the set file in a folder with the pictures beside it (inbox / Mac import).

A path may not climb out of the folder (`../x.png` is refused).

## Getting a set into the app

1. **The inbox (for agents).** Write the file — or a .zip, or the file plus its
   `images/` — into the inbox folder. It is imported the next time the tab
   opens or anything calls `POST /flashcards/inbox`, then moved to
   `imported/` (or `failed/` with a `.error.txt` beside it saying why). The
   folder is `flashcards_inbox/` next to the user's `flashcards.db`
   (`~/.assistant_tools/users/<uid>/flashcards_inbox/`); `POST /flashcards/inbox`
   answers with its exact path, and the Mac tab shows it.
2. **The API.** `POST /flashcards/import` with a multipart `file` (.yaml, .json,
   .zip), or JSON `{"doc": {...}}` / `{"yaml": "..."}`. Add `mode`.
3. **The tab.** Import… on the Mac; Add cards by hand on either device.

**Replace or add.** Importing a set that already exists (same subject + set_id)
REPLACES it by default: the set becomes exactly the file, cards no longer in it
are removed, and cards that did not change keep their progress. To ADD to a set
instead — say, more cards for a set somebody is already studying — use
`mode: append` (API) or put `.append.` in the inbox file's name
(`verbs.append.yaml`); only cards the set does not already have are added.

## Writing good cards (for agents)

- One fact per card. Two facts on one card means you cannot tell which you knew.
- Every fact from the source you were given. Do not fill gaps from memory, and
  put the page or section in `page` so the learner can check.
- Multiple-choice wrong answers come from the same topic (other years, other
  people from the same set) — never jokes, never "all of the above".
- Use `order` for every sequence, chronology or procedure; `cloze` for
  definitions and quotes; `typed` for anything the learner must produce verbatim.
- Quote YAML strings that contain `: `, `#`, or start with a digit or a quote.
  Inside a one-line `{…}` card also quote anything with `?` `,` `[` `]` `{` `}` —
  or write the card in block style (one field per line), which needs none of this.
  Hebrew abbreviations: write gershayim as ״ (U+05F4) or use single quotes.
- Check your file: every `mc` answer is one of its choices, and every `image`
  path exists. The import refuses the whole file and names the card otherwise.
