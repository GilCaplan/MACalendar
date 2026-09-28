# Users, login and sharing — the plan, and where it stands

Gil's rulings are DEVQA **Q65** (2026-09-28). This is the plan built on them:
a Fable planning pass over the code (every claim checked against file:line on
`tips-on-ios` at `f1baefa5`), then implemented phase by phase. Each phase ships
green on its own; nothing is visible to a user until phase 4.

## The crux the plan found

Eighteen personal stores read their path from a module constant at import;
six process-wide singletons cache a store object; and the Mac window opens the
calendar file directly rather than through the API. So the user cannot be
passed as an argument without reshaping every call site, and must not travel
through `EngineState`, whose contract is frozen.

**It travels the way request priority already does** (`model_protocol.serving`):
a `ContextVar`. `assistant/users` holds it; every store asks
`users.current()` and resolves its path through `users.paths.resolve(path)`:

| bound? | resolves to |
|---|---|
| nobody (no `users.json` yet — before the migration, and every test that binds no one) | the path it always had |
| a user | `<root>/users/<uid>/<same file name>`, `<root>` = the directory holding `users.json` |

**Who is bound:** the API binds the session's user per request (phase 2); the
Mac window and the HUD set a process default (phase 4); a new thread inherits
its creator's user only through `users.thread(...)` (a test scans
`assistant/engine` and `assistant/api` for any `threading.Thread(` that would
drop it). Until login is required (`policy.require_login` in `users.json`,
false until phase 5), a process nobody logged into acts as the **admin** — so
after the migration the assistant reads exactly the data it read before, from
its new folder.

Stays global (a device's or the machine's, not a person's): `model.lock`,
`device_secret`, `devices.json`, `device.json`, `heartbeats/`,
`hud_position.json`, `location.json`, `checkpoints/`, `config.yaml`.

## Phases

| # | phase | status |
|---|---|---|
| 1 | **Foundation** — `assistant/users/` (context, paths, registry, passwords), every personal store per user, `ContextMemory` per user, threads carry the user, the migration with backup / verification / automatic rollback / `--rollback`, scratch redirects | **done 2026-09-28**; the real data MIGRATED the same day (7 stores, counts verified, backup `~/.assistant_tools.backup-20260928-151343`) |
| 2 | **Auth API** — sessions (`sessions.json`, token hashed), `/auth/*`, `/users/*`, `/admin/*`, device → user binding, route authorisation for own data, login rate limit | **done 2026-09-28** |
| 3 | **Sharing + merged views** (**done 2026-09-28**) — owner-namespaced ids (`seq << 32 \| row_id` for SHARED rows only; own ids unchanged), `MergedReader` used by the API and the Mac window in-process, permission-checked write routing, the admin's view toggles, calendar-sync per user, shared vocabulary (`registry.vocab_sources`) | |
| 4 | **Mac UI** (**done 2026-09-28**) — login dialog, user chip + switcher, Settings › Account & Sharing, Admin console, the HUD follows the Mac session | |
| 5 | **iOS** (**done 2026-09-28**; `require_login` left OFF until Gil turns it on) — LoginView, AccountView, AdminUsersView, per-user cache folders, owner name/colour on rows; then `require_login: true` (every device logs in once) | |
| 6 | **Notifications per user + finish** (**done 2026-09-28**) — digests per user, `notify_shared`, the admin never spammed with others' items; docs; an end-to-end scenario script | |

## Phase 1 — what exists

- `assistant/users/__init__.py` — `current()`, `bind()`, `set_process_default()`, `thread()`, `each_user()`.
- `assistant/users/paths.py` — `registry_path()`, `root()`, `user_dir()`, `resolve()`.
- `assistant/users/registry.py` — `users.json`: one admin; users (lower-case unique usernames, a colour each, `seq`); per-user settings (`notify_shared`, `todos_group_by_owner`); shares (`view`/`edit`, one per pair); `admin_view` (off by default); `vocab_shares`; `policy.require_login`. Atomic writes, mtime-cached reads, refuses the real file under pytest.
- `assistant/users/passwords.py` — scrypt (n=2¹⁴, r=8, p=1), constant-time verify, 12-character generated passwords without look-alike letters.
- `assistant/users/migrate.py` + `scripts/migrate_users.py` — `--dry-run` / `--apply --admin gil` / `--rollback`. Refuses while the window, API or HUD runs; copies the whole directory to `…/.assistant_tools.backup-<ts>` first; snapshots row counts + md5s before and after the move; any mismatch rolls back on the spot. Old `*.bak*` files move to `legacy/`.
- Stores made per user: calendar DB (`get_db` and the `CalendarDB()` constructor), command memory, vocabulary, categories, lexicon, label feedback and models, trace bus, LLM log, observance exceptions, Google token, MSAL cache. Caches keyed on path as well as mtime.
- `tests/unit/test_users_foundation.py` (24): paths, passwords, registry rules, the isolation proof (store by store, and through the real engine), the thread scan, and the migration round trip (dry run, apply, refusal, mismatch → rollback, rollback byte-for-byte, rollback refused once another user exists). The rest of the suite, which binds no one, is the proof the compat contract holds.

## Decided in the plan (Gil can veto)

- `uid` is `u_` + 8 hex, never the username (a rename stays cheap).
- `policy.require_login` lives in `users.json`, not `config.yaml` — it is account policy the admin console changes.
- A user's colour is theirs; the admin can override it; a viewer cannot recolour someone else's items.
- A new user starts with an empty vocabulary; the admin's reaches them only if he shares it.
- With nobody logged in on the Mac (after "Log out"), the Mac's notifier stays silent.
- Sessions (revised by Gil the same day): a sign-in lasts until signed out;
  the admin may turn on auto sign-out after N days unused
  (`policy.auto_signout_days`, read by `sessions.idle_days()`), and sign a
  person out everywhere (`POST /admin/users/<uid>/signout`). Both live in the
  **Account tab** (`assistant/features/account/`), the admin's dashboard.
