# Connecting Google and Outlook calendars

Your Mac (the brain, `assistant.api`) keeps connected calendars in step on its
own — every 15 minutes, calendar window open or not — and both apps have a
**Settings → Connected Calendars** section to connect, see the last sync,
disconnect and "Sync now". The sign-ins and tokens live only on the Mac
(`~/.assistant_tools/`); the phone only starts a connection and shows it.

This is the one documented OPT-IN exception to "never touches the internet":
nothing below contacts anyone until you connect something, and then only the
calendar service you connected.

| | What you get | One-time set-up |
|---|---|---|
| **A. Gmail / any calendar, read-only link** | Their events on your calendar, refreshed every sync. No editing. | None — copy one link (2 min) |
| **B. Google Calendar, two-way** | Pull + push: edits and deletes flow both ways, new local events optionally mirrored up | A free Google Cloud project (~10 min) |
| **C. Outlook / Microsoft 365, two-way** | Pull + push for Outlook events | A free Entra app registration (~10 min) |

Why the set-up for B and C: Google and Microsoft only let an app sign in to
your calendar if the app is *registered* with them. A personal app like this
one registers itself once, under your own account, for free — there is no
MACalendar company holding a shared key.

---

## A. Read-only: a calendar's secret iCal address

**Gmail / Google Calendar**
1. Open calendar.google.com on a computer → the gear (top right) → **Settings**.
2. Left column, under **Settings for my calendars**, click the calendar.
3. Scroll to **Integrate calendar** → copy **Secret address in iCal format**
   (ends in `/basic.ics`). Anyone with this link can read that calendar — treat
   it like a password.
4. In MACalendar: **Settings → Connected Calendars → Read-only calendar links**
   (Mac: the "Read-only calendar links (ICS)…" button; iPhone: the section at
   the bottom), paste it, give it a label, **Add**.

Google refreshes that feed on its side only every few hours, so a change can
take a while to appear. For instant updates and editing, use B.

**Outlook.com**: outlook.live.com → gear → **Calendar → Shared calendars →
Publish a calendar** → pick the calendar, "Can view all details" → **Publish**
→ copy the **ICS** link → add it as above. **iCloud**: Calendar app → the
calendar's info → **Public Calendar** → copy the link.

---

## B. Google Calendar, two-way

You create two things in Google Cloud: a **Desktop** client (signing in from
the Mac) and, if you want to sign in from the phone too, an **iOS** client.
You need only one to connect — the account stays connected for both apps.

### 1. Project and API
1. Go to **console.cloud.google.com** and sign in with the Google account
   whose calendar you want.
2. Top bar → the project picker → **New project** → name `MACalendar` →
   **Create**, and make sure it is selected.
3. **☰ → APIs & Services → Library** → search **Google Calendar API** →
   **Enable**.

### 2. The consent screen ("Google Auth Platform")
4. **☰ → APIs & Services → OAuth consent screen** (it may be called
   **Google Auth Platform**) → **Get started**.
   - App name `MACalendar`, your e-mail as support e-mail → **Next**.
   - Audience: **External** → **Next**.
   - Contact e-mail: yours → **Next** → agree → **Create**.
5. **Data Access → Add or remove scopes** → tick
   `.../auth/calendar.events`, `openid` and `.../auth/userinfo.email` (filter
   for "calendar.events" to find the first) → **Update → Save**.
6. **Audience → Publish app → Confirm** so the status reads **In production**.

   **Do not leave it in "Testing".** Google expires the refresh token of an app
   in Testing after **7 days**, so the sync would stop every week with
   "Google sign-in expired — reconnect". In production but **unverified** is
   fine for a personal app (up to 100 users, no review needed); the only cost
   is a warning screen when you sign in — see step 10.

### 3a. Desktop client (sign in from the Mac)
7. **Clients → Create client** → Application type **Desktop app** → name
   `MACalendar Mac` → **Create** → **Download JSON**.
8. Mac: **Settings → Connected Calendars → Google Calendar → Set up… →
   Choose client JSON…** and pick the downloaded file. (Or save it yourself as
   `~/.assistant_tools/google_client_secret.json`; the path is
   `google_calendar.client_secret_path` in config.yaml.)

### 3b. iOS client (sign in from the phone) — optional
9. **Clients → Create client** → Application type **iOS** → name
   `MACalendar iPhone` → Bundle ID **`com.macalendar.app`** → **Create** →
   copy the **Client ID** (`1234-abc….apps.googleusercontent.com`). Paste it
   in either app: Mac **Set up… → iPhone sign-in**, or iPhone **Set up (paste
   client id)…**. It lands in config.yaml as `google_calendar.ios_client_id`.
   iOS clients have no secret; the redirect
   `com.googleusercontent.apps.<id>:/oauth2redirect` is derived from the id,
   so there is nothing else to enter.

### 4. Connect
10. **Connect…** (Mac: opens your browser; iPhone: opens a sign-in sheet) →
    pick the account → *"Google hasn't verified this app"* → **Advanced → Go
    to MACalendar (unsafe)** — it is your own app → allow calendar access.
    The Mac says *Connected.* and the first sync starts at once.

What syncs: your **primary** calendar (`google_calendar.calendar_id`), from 30
days back. Google events arrive as editable rows; edit or delete one and the
change goes up next sync. Plain local events stay local unless you set
`google_calendar.mirror_new_events: true` (every event created after
connecting is pushed up). Recurring Google series arrive as single instances,
each editable; local recurring series are not pushed (the same v1 limit as
Outlook). Conflicts: the later edit wins.

---

## C. Outlook / Microsoft 365, two-way

1. Go to **entra.microsoft.com** (or portal.azure.com → **Microsoft Entra
   ID**) and sign in with your Microsoft account. With a personal
   outlook.com/hotmail account you may be asked to create a free Azure account
   first — app registrations cost nothing.
2. **Applications → App registrations → New registration**.
   - Name `MACalendar`.
   - Supported account types: **Accounts in any organizational directory and
     personal Microsoft accounts** (this is what `tenant_id: common` expects).
   - Redirect URI: leave empty. → **Register**.
3. **Authentication** (left) → **Advanced settings → Allow public client
   flows → Yes** → **Save**. (The device-code sign-in needs it.)
4. **API permissions → Add a permission → Microsoft Graph → Delegated** →
   tick **Calendars.ReadWrite** (User.Read is already there) → **Add
   permissions**. No admin consent is needed for your own account.
5. **Overview** → copy **Application (client) ID**. Paste it in **Settings →
   Connected Calendars → Outlook → Set up…** on either app (it is written to
   config.yaml as `microsoft.client_id`).
6. **Connect…** → the app shows a code → **Copy code & open** →
   microsoft.com/devicelogin → paste → sign in → accept. The app notices by
   itself and the first sync starts. The same flow works from the phone.

Two-way is on for a new connection (the **Two-way** switch turns pushing off).
Only events that came from Outlook are pushed back — a plain local event is
never created in your Outlook account.

---

## Afterwards

- **Status**: each row shows the account, the last sync and the last error.
  "Sign-in expired — reconnect" means the refresh token was revoked or expired:
  press **Reconnect**.
- **Disconnect** signs out and asks whether to **keep** the synced events as
  ordinary local events or **remove** them; they stay in your account either
  way.
- **Interval**: `calendar_sync.interval_minutes` in config.yaml (default 15);
  `calendar_sync.enabled: false` stops the automatic sync (Sync now still works).
- **Where things live**: tokens `~/.assistant_tools/google_token.json` and
  `msal_token_cache.json` (mode 0600), the Google client JSON beside them. Tests
  redirect all three (`MACALENDAR_GOOGLE_TOKEN`,
  `MACALENDAR_GOOGLE_CLIENT_SECRET`, `MACALENDAR_MSAL_CACHE`).
- **Code**: `assistant/calendar_sync/` — `scheduler.py` (the loop and "Sync
  now"), `google_sync.py` / `outlook_sync.py` / `ics_subscription.py` (the
  providers), `connect.py` (sign-in flows, status, disconnect), `routes.py`
  (`/calendar_sync/*`).
