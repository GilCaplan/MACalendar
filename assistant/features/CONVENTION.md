# Adding a feature to this assistant

A **feature** is one of this assistant's own surfaces — a tab on the phone, a
panel on the Mac: Calendar, Tasks, Coursework, Workout, Timer, Teach, Jude.

> **Not the same thing as an integration.** `assistant/integrations/` is for
> hosting somebody else's PROGRAM — its own repository, its own server, its own
> process. It asks where the checkout is, what command starts it, which port to
> wait on, and how to gate its ollama calls. Tasks has none of those. Making a
> tab subclass `Integration` would mean five methods returning `None` to
> satisfy a base class describing something it isn't.
>
> The two conventions share one idea and nothing else: **a surface owns a
> folder, declares itself once to a registry, ships its own routes, and the
> generic layer never learns its name.** Jude is the only thing that is both —
> Jude-the-tab is a Feature, Jude-the-program is an Integration.

## The problem this exists to stop

Before it, adding a tab meant editing **three hand-synced lists on iOS**
(`contentTabs`, `tabContent`, the `onChange` bounce-off handlers) and **five
wiring sites on the Mac** (import, construct, `addWidget`, the toolbar loop,
the `_set_view` dict), plus a decision about caching that each tab made
differently.

They had already drifted, in ways nobody reported as bugs:

- **Timer had no bounce-off handler.** Hiding it while it was on screen left a
  blank screen with a working tab bar under it.
- **Tag 3 was a hole** left by Settings when it stopped being a tab, so the tab
  numbers were non-contiguous and encoded nothing.
- **Coursework's offline writes were dropped on the floor** while
  `CourseStore.swift` documented the opposite: *"offline writes are queued in
  LocalStore.shared.enqueue() and replayed on reconnect."* No `/courses` path
  appeared in any `enqueue` call site. Delete a course offline and it came
  back. (Fixed 2026-09-17: every write goes through `APIClient.mutate`, and
  `tests/unit/test_ios_offline.py` fails the build for one that does not.)
- **`refresh()` on two Mac panels, `reload()` on two others**, which is why
  `window.py` could only refresh todos.
- **Three visibility systems** — iOS `UserDefaults`, Mac `ui.show_*`, and
  `jude.enabled` — with no mapping, no key at all for Teach, and an iOS comment
  admitting *"isn't synced from it"*.

Every one of those is the same failure: a decision that had to be repeated by
hand, repeated slightly differently.

## Structure is declared; only VISIBILITY travels

Which features exist, and their label, icon and order, are declared **in code
on each platform**. Only the on/off switch is shared state:

    GET   /features            every surface + whether it is switched on
    PATCH /features/<name>     {"visible": true|false}

This split is about the phone working on a train. If the tab bar were built
from the server's list it could not be drawn until a request came back, and
when the Mac is asleep it would never be drawn at all. So each platform knows
its own surfaces offline and asks the Mac only which of them you switched off.

Visibility lives in `config.yaml` under `features:`, a plain `name -> bool`
map. Adding a feature therefore adds no config schema. The old `ui.show_*` keys
are still read as the initial value when `features:` has nothing to say about a
name, so an existing config.yaml cannot silently turn three tabs back on; the
first write moves it across and the legacy key stops mattering.

## Pinned

`pinned = True` means the surface cannot be hidden, and
`PATCH /features/calendar {"visible": false}` answers **409** with a sentence.
Calendar and Tasks are pinned: they are what this app *is*, and a switch that
empties the app is not a feature. It is a declared exception to a uniform
mechanism, not a special case in the tab bar.

## Adding one

**Start with the scaffold.** It writes every file and every registration line,
refuses a taken name or `order`, and prints what is left:

    python scripts/new_feature.py recipes --label Recipes --icon fork.knife --order 35
    #   --store recipes.db   the tab keeps its own per-user file
    #   --no-mac / --no-ios  one platform only (Teach is phone-only)
    #   --dry-run            show the writes, make none

Then build the tab inside the folders it made. Flashcards
(`assistant/features/flashcards/`) is the worked example of a full one: its
own store, routes, a Mac panel, a phone tab that studies offline, and an
`extension APIClient` of its own calls.

### The checklist

Each step either the scaffold does, or a test goes red naming it. Nothing here
relies on remembering.

- [ ] **Feature folder** — `assistant/features/<name>/`: `feature.py` (the
  `Feature` subclass), `routes.py` (its blueprint), `__init__.py`. *Scaffold.*
- [ ] **Registry line** — the import and the tuple entry in `registry.py`, the
  only file under `features/` that learns names. *Scaffold;
  `test_features.py` checks names and orders are unique and in order.*
- [ ] **Mac panel** — `assistant/calendar_ui/<name>_view.py`, a `FeaturePanel`
  with `feature_name`, `reload`, `apply_theme`, `apply_ui_config`. The window
  builds it from the registry: no `window.py` edit. *Scaffold;
  `test_new_tab_checklist.py` checks `feature_name`.*
- [ ] **iOS tab** — `Features/<Name>/<Name>View.swift` and one entry in
  `FeatureRegistry.swift` with the same `name` and `order`. *Scaffold;
  `test_features.py` holds the two registries equal.*
- [ ] **Xcode project** — every new `.swift` file added to `project.pbxproj`
  with `python scripts/xcode_add.py <paths>` (four entries per file by hand
  otherwise). *Scaffold for its own files; `test_new_tab_checklist.py` fails
  for any Swift file under a target folder the project does not compile.*
- [ ] **Store redirect** — a tab with its own file reads it from a
  `MACALENDAR_<NAME>` override, resolved per user through `users.paths.resolve`,
  and that variable is in `tests/conftest.py`, `scratch_env.STORES` and
  CLAUDE.md's store list. *Scaffold with `--store`; `test_new_tab_checklist.py`
  fails for a variable read under the feature's folder and missing from any
  of the three.*
- [ ] **Tests** — `tests/unit/test_<name>.py`; a Mac panel's UI tests click
  real controls (`QTest.mouseClick`), they do not call handlers. *Scaffold
  starts it.*
- [ ] **API reference** — `python -m scripts.gen_api_reference` after adding a
  route. It also rewrites the endpoint count on the published architecture
  page, which `test_artifact_claims.py` checks. *Scaffold runs it once; run it
  again after your routes.*
- [ ] **Offline writes** — every phone write goes through `APIClient.mutate`
  (queued when the Mac is away), creates carry a `client_token`, and a write
  whose replay would be WRONG goes in `test_ios_offline.py`'s `NOT_QUEUEABLE`
  with its reason — and then fails loudly, never behind a `try?`. Put the
  tab's calls in an `extension APIClient` in its own folder; the rule reads
  every such file. *`test_ios_offline.py`.*
- [ ] **FEATURES.md entry** — a row in the table and a `###` section: what,
  where, how. *`test_new_tab_checklist.py` fails until the label is in the
  table.*

When the tab is done: the feature's tests, `test_features.py`,
`test_new_tab_checklist.py`, `test_ios_offline.py`, the iOS build, then the
full `scripts/run_tests.sh` with `PYTHON=./.venv/bin/python`.

**`order` is sparse (0, 10, 20, …) on purpose.** Sequential numbers mean
inserting a feature between two others renumbers every one after it, which is
the kind of churn that makes people append instead and leaves the order
meaningless.

**`name` is a string, never an integer.** The tabs used magic ints and tag 3
was left as a hole; the string is the same token the API, the config, the
registry and both clients already share.

**`mac: false` in the manifest is a legitimate answer** — Teach is iOS-only —
and the manifest says so rather than making a client guess. Everything
downstream on both platforms (the tab bar, the layer stack, the bounce-off
when a visible tab is switched off, the Settings toggles) is a loop over the
registry, so nothing else learns the new name. Visibility lives in
`FeatureVisibility` on the phone, cached in `UserDefaults`; a toggle applies
locally first and queues its PATCH when the Mac is away.

## Things that will bite

- **`ready`/`visible` is not `working`.** A visible tab whose backend is absent
  must say so in a sentence, the way `Integration.status()` does. A tab that
  renders empty is indistinguishable from a broken one.
- **Decide offline behaviour ONCE, in the client, not per tab.** Three
  mechanisms and one silent data-loss bug is what per-tab choice produced.
  A write that cannot go out is queued or it FAILS LOUDLY — never `try?` and
  a stale cache that the next sync overwrites. The one place that decides is
  `APIClient.mutate`; the exceptions are listed, with a reason each, in
  `tests/unit/test_ios_offline.py`'s `NOT_QUEUEABLE`. **A write whose replay
  would be WRONG is not queued quietly** — `/timers/<id>/start` and
  `/counters/<id>/press` now carry the instant they happened, precisely so
  that they can be.
- **Never let registration be two lists.** If adding a feature means editing
  the same knowledge in more than one place, that is the bug, and it will
  present as a blank screen months later.
