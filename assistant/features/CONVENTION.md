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
  appears in any `enqueue` call site. Delete a course offline and it comes back.
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

### 1. A folder and a declaration

```
assistant/features/<name>/
  __init__.py
  feature.py       the Feature subclass
  routes.py        its Flask blueprint (optional)
  panel.py         its Mac FeaturePanel (optional)
```

```python
class ThingFeature(Feature):
    name = "thing"          # identity everywhere: config key, URL, both clients
    label = "Thing"
    icon = "hammer"         # SF Symbol, for the phone's tab bar
    order = 70              # SPARSE — see below
    pinned = False
    default_visible = True

    def blueprint(self):
        from assistant.features.thing.routes import blueprint
        return blueprint

    def panel(self):
        from assistant.features.thing.panel import ThingPanel
        return ThingPanel
```

**`order` is sparse (0, 10, 20, …) on purpose.** Sequential numbers mean
inserting a feature between two others renumbers every one after it, which is
the kind of churn that makes people append instead and leaves the order
meaningless.

**`name` is a string, never an integer.** The tabs used magic ints and tag 3
was left as a hole; the string is the same token the API, the config, the
registry and both clients already share.

### 2. One line in the registry

Add it to the tuple in `registry.all_features()`. That is the only file under
`features/` that learns your name — `base` stays generic, which is what makes
the next feature cheap.

### 3. Both clients

Each declares the feature locally (offline-first, see above) and reads
visibility from `GET /features`. `mac: false` in the manifest is a legitimate
answer — Teach is iOS-only — and the manifest says so rather than making a
client guess.

On the phone that declaration is one entry in
`MACalendar-iOS/MACalendar-iOS/Features/FeatureRegistry.swift` — same `name`,
same `order` — plus a folder under `Features/` holding the tab's own files.
Everything downstream (the tab bar, the layer stack, the bounce-off when a
visible tab is switched off, the Settings toggles) is a loop over that list,
so nothing else on iOS learns the new name. Visibility lives in
`FeatureVisibility`, cached in `UserDefaults` and seeded once from the old
`show*Tab` keys; a toggle applies locally first and queues its PATCH when the
Mac is away.

## Things that will bite

- **`ready`/`visible` is not `working`.** A visible tab whose backend is absent
  must say so in a sentence, the way `Integration.status()` does. A tab that
  renders empty is indistinguishable from a broken one.
- **Decide offline behaviour ONCE, in the client, not per tab.** Three
  mechanisms and one silent data-loss bug is what per-tab choice produced.
  A write that cannot go out is queued or it FAILS LOUDLY — never `try?` and
  a stale cache that the next sync overwrites.
- **Never let registration be two lists.** If adding a feature means editing
  the same knowledge in more than one place, that is the bug, and it will
  present as a blank screen months later.
