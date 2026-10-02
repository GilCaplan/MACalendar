# Putting the iPhone app on the App Store

Where the app stands against Apple's review, what was done for it, and what is
left — most of it Gil's (an account, a listing, a policy URL). Written
2026-10-02 with DEVQA Q85 ("improve so the app can work alone if no server
connected … so it could potentially be published to the appstore").

## The one thing review needed: the app works with no Mac

A reviewer has no MACalendar server. Until Q85 the phone was a client of the
user's own Mac, and without one it could only show a calendar and queue
commands for a Mac that never comes — guideline 2.1 (app completeness) fails
that. Now a fresh install asks how it runs:

- **Use it on this iPhone** — everything on the phone. Voice and typed
  commands are read ON the phone (`Engine/LocalEngine.swift`, deterministic,
  every iPhone; Apple's on-device model helps on iOS 26 where the rules read
  nothing): add, move, rename, delete, tick off, and questions. Repeating
  events, the icons beside titles, the Jewish calendar and Shabbat times are
  all worked out on the phone. Nothing leaves it.
- **Connect my Mac** — the full assistant, as before. What a phone made on
  its own goes up to the Mac through the change queue when one is paired.

Measured (scripts/phone_engine_board.py): the phone takes the right action on
93.9% of the FastRule set's single-ask TRAIN rows (n=4,023) and on 82.1% of
real HWU-64 commands outside the sealed 300 (n=2,699). It never acts on a
guess: an edit or delete that cannot name one row asks or says so.

## Done for review

| Guideline | What | Where |
|---|---|---|
| 2.1 completeness | Works with no server; first-launch choice | `Views/SetupGuideView.swift` (`WelcomeView`), `Engine/` |
| 5.1.1(v) account deletion | "Delete my account…" (password confirmed) and the admin's "Remove this account…" | `Views/UsersViews.swift`, `DELETE /auth/me`, `DELETE /admin/users/<id>` |
| Privacy manifest | `PrivacyInfo.xcprivacy` in the app AND the widget: no tracking, no collected data, UserDefaults reasons CA92.1 + 1C8F.1 | `MACalendar-iOS/`, `MACalendarWidgets/` |
| Purpose strings | The unused camera string ("Not used.") removed; microphone, speech, location, contacts and local-network strings each say what and why | `Info.plist` |
| On-device speech | `requiresOnDeviceRecognition = true`: speech never goes to Apple's servers | `Voice/VoiceRecorder.swift` |
| Mac-only tabs | Jude, Teach and Account are hidden on a phone with no Mac | `Features/FeatureRegistry.swift` (`needsMac`) |

## Left to do — Gil's

1. **Apple Developer Program** ($99/yr). The app is signed with a free personal
   team today (DEVQA Q45): builds expire in 7 days, no TestFlight, no App Store.
2. **App Store Connect**: the listing, a bundle id under the paid team
   (`com.macalendar.app` may need to change), screenshots (6.9" and 6.5"
   iPhone at least), an age rating, a category (Productivity).
3. **A privacy policy URL** — the draft below, published anywhere.
4. **App Privacy answers**: "Data Not Collected". True for phone-only use; a
   paired Mac is the user's own computer, not the developer's.
5. **Review notes** — paste the block below.
6. **Decide on `NSAllowsArbitraryLoads`.** It stays on: the phone talks plain
   HTTP to the user's OWN Mac, by LAN or Tailscale address (100.x, or a
   *.ts.net name), which has no certificate. Review accepts it with that
   reason; the review notes say so. Narrowing it to `NSAllowsLocalNetworking`
   plus a `ts.net` exception is possible but would break a user who types a
   bare IP elsewhere — say the word and it is a ten-line change.
7. **Optional:** the Hebrew-calendar defaults (Shabbat and yom tov kept off
   for series) suit an observant user; a general audience may want the
   observance switches off by default. That is a product decision.

## Draft privacy policy

> **MACalendar — Privacy**
>
> MACalendar does not collect, sell or share any personal data, and contains
> no tracking or analytics.
>
> Used on its own, everything you create — events, to-dos, settings — is
> stored only on your iPhone. Voice commands are transcribed on the device by
> Apple's on-device speech recognition and read by the app on the device.
>
> If you choose to connect your own Mac running the MACalendar server, your
> calendar, to-dos and spoken commands travel between your iPhone and that
> Mac only, over your own network or your private Tailscale network. That
> Mac is yours; the developer has no access to it.
>
> Location (optional) is used only to work out sunset times for Shabbat and
> holidays where you are, and is sent nowhere except your own Mac if you have
> one. Contacts (optional) are read only when you choose to import names into
> the assistant's vocabulary on your own Mac.
>
> Questions: [Gil's contact address].

## Review notes (paste into App Store Connect)

> The app works fully on its own; no account or server is needed. On first
> launch choose **"Use it on this iPhone"**. Then tap the microphone (or the
> small keyboard badge on it to type) and try: "dentist tomorrow at 3",
> "what do I have tomorrow", "move the dentist to Friday at 4", "buy milk",
> "mark buy milk as done", "cancel the dentist". The optional "Connect my
> Mac" choice pairs the app with a server the user runs on their own Mac; it
> is not needed to evaluate the app. HTTP (NSAllowsArbitraryLoads) is used
> only for that connection, to the user's own computer on their own network,
> which has no TLS certificate.
