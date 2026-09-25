"""The in-app "how to connect" walkthroughs, written ONCE and drawn by both apps.

Gil, 2026-09-24: *"add in connected calendars simple tutorial of how to do,
step by step"*. The set-up guide lived only in DOCUMENTATION/CALENDAR_SYNC.md,
and both apps pointed at that path, which a phone cannot open and a Mac opens
in a text editor. These are the same steps in the words a person follows with
the page in front of them: one action per step, the button names exactly as
they appear, a link where there is somewhere to go. The long version, with the
why behind each choice, stays in CALENDAR_SYNC.md; `test_calendar_guide.py`
keeps the two naming the same buttons.

Served at GET /calendar_sync/guide; the Mac reads `GUIDES` directly.
"""
from __future__ import annotations


def _step(text: str, link: str = "", link_label: str = "") -> dict:
    return {"text": text, "link": link, "link_label": link_label or ("Open" if link else "")}


GUIDES: list[dict] = [
    {
        "key": "ics",
        "title": "Gmail, read-only",
        "time": "1 minute",
        "summary": "See your Google Calendar here. No sign-in; edits stay on Google's side.",
        "steps": [
            _step("On a computer, open Google Calendar's settings.",
                  "https://calendar.google.com/calendar/r/settings", "Open settings"),
            _step("In the left column, under “Settings for my calendars”, click your calendar."),
            _step("Scroll to “Integrate calendar” and copy “Secret address in iCal format”. "
                  "Treat it like a password: anyone with it can read that calendar."),
            _step("Back here, paste it under “Read-only calendar links”, give it a name, "
                  "and press Add link."),
        ],
        "done": "Events appear within a few minutes. Google refreshes the link every few "
                "hours, so for instant updates and editing use Google two-way below.",
    },
    {
        "key": "google",
        "title": "Google Calendar, two-way",
        "time": "10 minutes, once",
        "summary": "Edit here or in Google, and each side keeps up. You register a small "
                   "free app with Google once; after that it is one Connect button.",
        "steps": [
            _step("Create a project called MACalendar, signed in with the Google account "
                  "whose calendar you want.",
                  "https://console.cloud.google.com/projectcreate", "Create project"),
            _step("Turn on the Google Calendar API: open it and press Enable.",
                  "https://console.cloud.google.com/apis/library/calendar-json.googleapis.com",
                  "Open the API"),
            _step("Open Google Auth Platform and press Get started. App name MACalendar, "
                  "your e-mail, Audience External, then Create.",
                  "https://console.cloud.google.com/auth/overview", "Open"),
            _step("Under Data Access, press Add or remove scopes, tick “calendar.events”, "
                  "then Update and Save.",
                  "https://console.cloud.google.com/auth/scopes", "Open Data Access"),
            _step("Under Audience, press Publish app. Left in “Testing”, Google signs you "
                  "out every 7 days.",
                  "https://console.cloud.google.com/auth/audience", "Open Audience"),
            _step("Under Clients, press Create client, choose Desktop app, then Create and "
                  "Download JSON.",
                  "https://console.cloud.google.com/auth/clients", "Open Clients"),
            _step("On the Mac: Settings → Connected Calendars → Google Calendar → Set up… → "
                  "Choose client JSON…, and pick the file you downloaded."),
            _step("Press Connect…. Google says the app isn't verified: it is your own, so "
                  "press Advanced → Go to MACalendar, then Allow."),
            _step("Optional, to sign in from the iPhone as well: Create client again, choose "
                  "iOS, bundle ID com.macalendar.app, then copy the Client ID and paste it "
                  "in Set up… on either app.",
                  "https://console.cloud.google.com/auth/clients", "Open Clients"),
        ],
        "done": "It says Connected and the first sync starts. Your Mac keeps syncing every "
                "15 minutes, calendar open or not.",
    },
    {
        "key": "outlook",
        "title": "Outlook Calendar, two-way",
        "time": "5 minutes, once",
        "summary": "Edit here or in Outlook, and each side keeps up. You register a small "
                   "free app with Microsoft once; after that it is one Connect button.",
        "steps": [
            _step("Open app registrations and sign in with your Microsoft account. If it "
                  "asks you to create a free Azure account first, do that; registering an "
                  "app costs nothing.",
                  "https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
                  "Open app registrations"),
            _step("Press New registration. Name MACalendar. Account types: “Accounts in any "
                  "organizational directory and personal Microsoft accounts”. Leave Redirect "
                  "URI empty and press Register."),
            _step("Open Authentication, set “Allow public client flows” to Yes, and press Save."),
            _step("Open API permissions → Add a permission → Microsoft Graph → Delegated, "
                  "tick Calendars.ReadWrite, and press Add permissions."),
            _step("Open Overview and copy the Application (client) ID."),
            _step("Here: press Set up… under Outlook Calendar, paste the ID, and save it."),
            _step("Press Connect. Copy the code it shows, open the Microsoft page, paste the "
                  "code and sign in. This screen notices by itself when you're done.",
                  "https://microsoft.com/devicelogin", "Open the Microsoft page"),
        ],
        "done": "It says Connected and the first sync starts. The same sign-in works from "
                "the phone or the Mac.",
    },
]


def guides() -> list[dict]:
    return GUIDES
