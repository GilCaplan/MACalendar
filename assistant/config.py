"""Configuration loading and validation."""

import os
from typing import Union, List, Literal, Optional

import yaml
from pydantic import BaseModel, field_validator

from assistant.exceptions import ConfigError


class HotkeyConfig(BaseModel):
    modifiers: List[str]
    key: str

    @field_validator("modifiers")
    @classmethod
    def validate_modifiers(cls, v: List[str]) -> List[str]:
        allowed = {"cmd", "shift", "ctrl", "alt"}
        for m in v:
            if m not in allowed:
                raise ValueError(f"Unknown modifier '{m}'. Allowed: {allowed}")
        return v


class WhisperConfig(BaseModel):
    model_size: str = "base"
    compute_type: str = "int8"
    device: str = "cpu"
    language: Optional[str] = "en"
    beam_size: int = 1  # 1 = greedy decode; faster for short voice commands


class MlxWhisperConfig(BaseModel):
    """Whisper on the Apple GPU via MLX (stt_engine: "mlx")."""
    model: str = "mlx-community/whisper-base-mlx"   # …/whisper-small-mlx, …/whisper-large-v3-turbo
    language: Optional[str] = "en"


class GoogleSTTConfig(BaseModel):
    api_key: Optional[str] = None


class OllamaConfig(BaseModel):
    base_url: str = "http://localhost:11434"
    model: str = "llama3.1:8b"
    temperature: float = 0.1
    timeout_seconds: int = 60
    # Keep the model resident in memory between commands ("30m", "-1" = forever).
    # Ollama's default (5 min) means the first command after a pause pays a
    # multi-second reload — that's most of the perceived latency.
    keep_alive: Union[int, str] = -1   # int seconds (-1 = forever) or "30m"
    # Two-tier models: `model` answers the user (latency matters); `verify_model`
    # does the background self-check / re-reasoning where a slower, stronger
    # model is fine. None = same as `model`.
    verify_model: Optional[str] = None
    # Context window. Ollama's default (4096) is SMALLER than our system prompt
    # (~4k tokens): the window overflows on every call, the prefix cache is
    # lost and the date table gets truncated. 8192 fits prompt + few-shot + output.
    num_ctx: int = 8192
    # Warm the model at startup so the first command is fast.
    warm_up: bool = True


class OpenAIConfig(BaseModel):
    api_key: Optional[str] = None
    model: str = "gpt-4o"
    temperature: float = 0.1


class GeminiConfig(BaseModel):
    api_key: Optional[str] = None
    model: str = "gemini-1.5-pro"
    temperature: float = 0.1


class ClaudeConfig(BaseModel):
    api_key: Optional[str] = None
    model: str = "claude-3-5-sonnet-20240620"
    temperature: float = 0.1


class MicrosoftConfig(BaseModel):
    client_id: str
    tenant_id: str = "common"
    token_cache_path: str = "~/.assistant_tools/msal_token_cache.json"


class AudioConfig(BaseModel):
    sample_rate: int = 16000
    silence_threshold: float = 0.01
    silence_duration_sec: float = 20.0   # stop after 20s of silence
    max_recording_sec: int = 120         # hard cap
    # Comma-separated words/phrases that trigger early recording stop.
    # Merged with the built-in defaults (execute, done, stop, …).
    stop_phrases: List[str] = []
    # Optional spoken separator between multiple events in one recording.
    # When non-empty, the transcript is split on this phrase and each
    # segment is parsed independently (faster — avoids LLM for multi-event).
    # Recommended: "next event"  e.g. "meeting at 10am next event lunch at noon"
    event_separator: str = ""
    # After recording, show a Redo / Add more / Send bar for `review_seconds`
    # before sending (the same bar the iPhone shows). A spoken stop word
    # ("execute", "done", …) always sends immediately — saying it *is* the
    # decision, so there's nothing left to wait for.
    review_before_send: bool = True
    review_seconds: int = 3


class TTSConfig(BaseModel):
    mute: bool = False
    voice: str = "Samantha"
    rate: int = 200


class TodoSyncConfig(BaseModel):
    mode: Literal["today", "general", "off"] = "off"
    auto_sync_on_open: bool = False


class TodoConfig(BaseModel):
    sync: TodoSyncConfig = TodoSyncConfig()
    show_completed: bool = False
    default_list: Literal["today", "general"] = "today"
    # "Tag mode": every newly created task (Mac UI, voice, API without explicit
    # tags) automatically gets this tag. Empty = off.
    auto_tag: str = ""
    # When no tag was said and tag mode is off, infer one from the title
    # ("buy chicken" → Groceries). Only tags already in the palette are used.
    auto_tag_infer: bool = True
    # Second net under `client_token` for callers that send no token at all.
    # A token-less POST /todos naming a task that is ALREADY open, spelled the
    # same, in the same list, and created less than this many seconds ago is
    # treated as a replay of that create rather than a new ask. The partial
    # unique index only referees non-empty tokens, so without this a token-less
    # client could still stack copies — which is exactly how 45 "buy groceries"
    # rows accumulated (2026-08-31..09-07). 0 disables the net.
    duplicate_window_seconds: int = 120


class UIConfig(BaseModel):
    font_month: int = 11
    font_week: int = 11
    font_day: int = 13
    font_tasks: int = 13
    font_coursework: int = 13
    compact_ui: bool = False
    accent_color: str = "#f5a524"  # hex; brand accent used app-wide (Settings → Accent Color)
    show_coursework: bool = True  # toggled off from Settings to hide the Coursework tab entirely
    show_week_numbers: bool = True  # ISO week number column in the month grid
    # Same per-tab switches the phone has (iOS Settings › Tabs)
    show_workout: bool = True
    show_timer: bool = True
    # Show the assistant's stage-by-stage thinking HUD while a voice command
    # runs (the Mac twin of iOS Settings › Voice › Show assistant thinking).
    # The HUD is its own app — assistant.thinking_hud — and re-reads this.
    show_thinking: bool = True
    # Which screen corner the thinking HUD parks itself in (until you drag it).
    thinking_corner: Literal["bottom-right", "bottom-left", "top-right", "top-left"] = "bottom-right"


class ApiConfig(BaseModel):
    key: Optional[str] = None   # X-API-Key header value; null = no auth required
    # Where the phone API listens. The launcher passes --port; this is what
    # other local processes (the thinking HUD) use to reach it.
    port: int = 8080


class HebrewCalendarConfig(BaseModel):
    # "english" = Gregorian only, "hebrew" = Hebrew (gematria) only, "both" = show both
    display_mode: Literal["english", "hebrew", "both"] = "both"
    show_holidays: bool = True
    # True = Israel holiday schedule (1-day Yom Tov); False = Diaspora (2-day)
    israel_holidays: bool = True


class ObservanceConfig(BaseModel):
    """Where sundown is computed for, and how much room to leave around it.

    Drives workout scheduling only (see assistant/observance.py) — the Hebrew
    date *display* settings live in HebrewCalendarConfig above and are
    deliberately separate: one answers "what is today called?", this one
    answers "may I train, and when?".
    """
    # The master gate observance.is_enabled() reads. This field existing here
    # is what makes the yaml key real: pydantic silently discards unknown
    # keys, so before it was declared, `enabled: false` in config.yaml was
    # dropped on load and only the MACALENDAR_OBSERVANCE env override worked.
    enabled: bool = True
    latitude: float = 31.7683            # Jerusalem
    longitude: float = 35.2137
    timezone: str = "Asia/Jerusalem"
    city: str = "Jerusalem"
    # Solar depression for tzeit hakochavim; 8.5 deg is common Israeli practice.
    tzeit_depression: float = 8.5
    candle_lighting_minutes: int = 18
    # How long before candle lighting a session must be finished.
    erev_buffer_minutes: int = 90
    motzei_buffer_minutes: int = 30
    earliest_hour: int = 5
    latest_evening: str = "22:30"
    # Minor fasts (Tzom Gedalia, 17 Tammuz...) as full rest days rather than
    # pushing the session past nightfall.
    minor_fast_is_rest_day: bool = True
    # Allow motzei Shabbat / motzei chag as a last resort when a chag would
    # otherwise cost a session outright.
    allow_motzei_fallback: bool = True


class NotificationsConfig(BaseModel):
    """Pre-event notifications (see assistant/notify.py for the policy).

    category_leads maps a category name to its lead in minutes; 0 MUTES the
    whole category (Gil's rule), mirroring the event-level 0 = "explicitly
    none". default_lead_minutes 0 means opt-in only: reminders fire only
    where an event or category asked for one."""
    enabled: bool = True

    # THE DAY PANEL (Gil, 2026-09-11): "it's on or off and it shows in a nice
    # manner the event calendar and tasks for today". One summary of the day,
    # not a stream of things about to start — so `daily_digest` is the single
    # switch the iOS app exposes, and `digest_time` is a config knob rather
    # than another control to think about.
    daily_digest: bool = True
    digest_time: str = "07:00"          # local, HH:MM

    # THE LOCK-SCREEN AGENDA CARD, iPhone only (Gil, 2026-09-17). Shared here
    # rather than kept device-local so the two apps cannot disagree about it and
    # the choice survives a reinstall — the same reason `daily_digest` is shared.
    # The Mac draws no Live Activity, so nothing on the Mac READS this; the Mac's
    # settings dialog only offers it, and the phone is what acts on it.
    #
    # The phone also keeps it in UserDefaults (`agendaCardEnabled`), because
    # `LiveActivityManager` has to answer "is this on?" synchronously and with no
    # server in reach. This field is the shared truth; that key is its cache.
    agenda_card: bool = True

    # The PRE-EVENT reminders (a banner N minutes before something starts).
    # Off by default since the day panel replaced them — Gil asked for the
    # panel "and not when something is about to pop up". The machinery below
    # is intact and dormant rather than deleted: `reminder_minutes` is a
    # frozen engine contract and "with a 15 minute reminder" still parses and
    # stores, so turning this back on restores it whole.
    pre_event: bool = False
    default_lead_minutes: int = 0
    category_leads: dict[str, int] = {}

    respect_observance: bool = True
    catch_up_minutes: int = 10          # Mac: fire late if missed by <= this
    sound: bool = True
    speak: bool = False                 # Mac only: read aloud via tts


class NLUConfig(BaseModel):
    # Words that trigger instant fast-path create + background LLM title fix.
    # When a voice command's extracted title matches one of these, the event is
    # created immediately with the keyword as a placeholder title, then the LLM
    # silently patches it with a proper title derived from the full transcript.
    event_keywords: List[str] = ["meeting", "appointment", "activity"]
    # Few-shot personalisation: inject the k most similar past commands
    # (with user corrections) into the LLM prompt. 0 = off — run 7 measured
    # no effect at k=4 (98% vs 97%, and 100% on the only path that reads
    # them), so the engine ships without it; rows 74/76 are the experiments
    # that would justify turning it back on.
    memory_examples: int = 0
    # Record every command + outcome to ~/.assistant_tools/nlu_memory.db
    memory_enabled: bool = True


class EngineConfig(BaseModel):
    """The engine's knobs (DOCUMENTATION/ENGINE.md). Stage behaviour only —
    the routing threshold stays with the rule parser."""
    # Step 1's gate: when the vocabulary doubts a word, ask the speaker to
    # check the transcription before anything executes (clients that declared
    # supports_edit only). Off = proceed with the best guess + tap-a-word.
    confirm_transcript: bool = False
    # Step 4's gate: an interrogative create ("should I add yoga tomorrow?")
    # is offered for confirmation instead of being executed or dropped
    # (clients that declared supports_confirm only). Off = the pre-ruling
    # behaviour, where deep decides on its own.
    confirm_create: bool = True
    # Step 6 on the fast track: cross-check every command, or only ones the
    # rules were less sure about. Decided by loop telemetry, not by taste.
    reconcile: Literal["always", "uncertain"] = "always"
    # Escape hatch: route everything through the foreground deep track.
    fast_track: bool = True
    # The event-or-to-do router (decompose_validate/kind_router.py, Gil
    # 2026-09-24: "basic rules, otherwise model"): off = the tagger's catch-all
    # `event` stands on the items no rule decided.
    kind_router: bool = True
    # Step 0: queued commands are coalesced into one ("…")and("…") input up
    # to this budget; overflow runs sequentially.
    coalesce_max_tokens: int = 300
    # A ceiling on what the engine itself may BUILD for a create_event — never
    # applied to a manual GUI edit, which never reaches this stage. Exceeding
    # it clips end_time back to start_time + this many hours.
    max_event_hours: float = 4.0
    # A window the engine will not place a start or end time in without
    # saying so — a FLAG, not a clip, on ANY engine-built create_event
    # (spoken or defaulted). "HH:MM"; start > end means it spans midnight.
    quiet_hours_start: str = "23:00"
    quiet_hours_end: str = "06:00"


class LabelsConfig(BaseModel):
    """The learned labellers (`assistant/engine/label/`).

    DECLARED, not just documented. pydantic silently DISCARDS a section that is
    not a field — `observance.enabled` was set in config.yaml and ignored for
    weeks because of exactly that, and the fix was declaring it. A flag the user
    can set and the code can never see is worse than no flag.

    Both default OFF. A model deciding an event's category changes what lands on
    the calendar, so it ships behind a switch with the keyword rules as the
    default — the same caution `self_check_apply` carries.
    """

    model_event: bool = False
    model_task: bool = False
    #: MODEL FIRST (Gil, 2026-09-22: "I want the ML models on that instead of
    #: rule based"). Off: the model only fills a row the rules had no opinion
    #: about. On: a confident model answer wins over the rules' guess, and the
    #: rules answer only where the model abstains. Needs `model_event` /
    #: `model_task` on too; a missing or unconfident model still falls back.
    model_first: bool = False
    #: Retrain in the background once this many NEW user CORRECTIONS have
    #: accumulated. Corrections, not items: fifty tasks nobody corrected teach
    #: nothing.
    retrain_every: int = 25
    auto_retrain: bool = False


class JudeConfig(BaseModel):
    """Jude — the Judaic study assistant, integrated but NOT vendored.

    Jude is its own repository (github.com/GilCaplan/JudeTheJudaicChatBot) with
    its own corpus and a ~3 GB vector index; copying it in here would make this
    repo unclonable and would fork a project that is still being worked on. So
    `path` points at a checkout beside this one, and anyone else clones that
    repo themselves — see assistant/jude/ARCHITECTURE.md.

    Not found, or `enabled: false`, means every Jude surface says so politely
    and nothing else changes.
    """
    enabled: bool = False
    # Relative to this repository's root, or absolute. "~" is expanded.
    path: str = "../JudeTheJudaicChatBot"
    port: int = 8000
    # Start Jude's server ourselves when it is not already listening. Off means
    # "I run it myself"; the bridge then only connects.
    autostart: bool = True
    # Which Ollama model Jude's roles use. Empty = whatever `ollama.model` is,
    # so Jude and the assistant share one loaded model rather than making a
    # laptop hold two.
    model: str = ""
    # Jude ships a cloud fallback cascade (Gemini → LLMod → Ollama). This
    # project does not touch the internet — tests/unit/test_offline.py fails
    # the build if that stops being true — so every role is pinned to local
    # Ollama. Setting this true hands Jude back its own .env and its cloud
    # providers; it is then YOUR call, and the traffic is Jude's, not the
    # assistant's. The ollama gate stays in place either way.
    allow_cloud: bool = False
    # Where the arbitrating ollama proxy listens. Jude is pointed at THIS
    # rather than at ollama, so every call it makes passes through
    # model_protocol.hold() like every call this project makes — see
    # assistant/integrations/ollama_gate.py. It must not be ollama's own port.
    gate_port: int = 11435
    # "background" (default) or "live". Background makes Jude YIELD the model
    # to voice commands between calls; live makes it race them, which is the
    # contention the gate exists to remove. See ollama_gate.py for why the
    # asymmetry means "live" is almost never what you want here.
    priority: str = "background"


class CalendarSyncConfig(BaseModel):
    """The brain's periodic sync of connected calendars (ICS links, Outlook,
    Google). Runs in `assistant.api`, so it keeps going with the calendar window
    closed. Nothing is contacted unless a source is actually connected — hosted
    calendar sync is the one documented OPT-IN exception to "never touches the
    internet" (DOCUMENTATION/CALENDAR_SYNC.md)."""
    enabled: bool = True
    interval_minutes: int = 15


class GoogleCalendarConfig(BaseModel):
    """Google Calendar two-way sync. OFF until credentials exist: with no
    Desktop client JSON at `client_secret_path` and no `ios_client_id`, every
    surface reports "set-up needed" and the sync never calls Google.
    See DOCUMENTATION/CALENDAR_SYNC.md for creating both clients."""
    enabled: bool = True
    # The "Desktop app" OAuth client JSON downloaded from Google Cloud. Signing
    # in FROM THE MAC uses it (loopback redirect to 127.0.0.1).
    client_secret_path: str = "~/.assistant_tools/google_client_secret.json"
    # An "iOS" OAuth client (bundle id com.macalendar.app). Signing in FROM THE
    # PHONE uses it; iOS clients have no secret.
    ios_client_id: str = ""
    calendar_id: str = "primary"
    # Push plain local events created after connecting up to Google as well.
    # Off: only events that came FROM Google (or that you mirror one by one)
    # are pushed back.
    mirror_new_events: bool = False


class AppConfig(BaseModel):
    hotkey: HotkeyConfig
    stt_engine: Literal["whisper", "mlx", "google"] = "whisper"
    llm_engine: Literal["ollama", "openai", "gemini", "claude"] = "ollama"
    whisper: WhisperConfig = WhisperConfig()
    mlx_whisper: MlxWhisperConfig = MlxWhisperConfig()
    google_stt: GoogleSTTConfig = GoogleSTTConfig()
    ollama: OllamaConfig = OllamaConfig()
    openai: OpenAIConfig = OpenAIConfig()
    gemini: GeminiConfig = GeminiConfig()
    claude: ClaudeConfig = ClaudeConfig()
    microsoft: Optional[MicrosoftConfig] = None
    calendar_sync: CalendarSyncConfig = CalendarSyncConfig()
    google_calendar: GoogleCalendarConfig = GoogleCalendarConfig()
    confirmation_level: int = 1
    # Background LLM re-check of rule-parser results. OFF by default: across four
    # audit runs it proposed a correction on ~96% of commands and fixed none
    # (2026-08-28: 78 proposed of 81, 0 fixed, 0 broken). It is what turns a
    # 6.7 s answer into a ~21 s settled one, for a second LLM call per command.
    # Set true to bring it back — it still only advises unless self_check_apply.
    verify_fast_path: bool = False
    # Apply the self-check's corrections automatically? The 2026-08-26 audit showed the
    # verifier proposes changes on ~98% of commands and fixes fewer than it breaks, so
    # by default it is ADVISORY: logged + shown in the trace, not applied.
    self_check_apply: bool = False
    labels: LabelsConfig = LabelsConfig()
    audio: AudioConfig = AudioConfig()
    tts: TTSConfig = TTSConfig()
    todo: TodoConfig = TodoConfig()
    api: ApiConfig = ApiConfig()
    nlu: NLUConfig = NLUConfig()
    engine: EngineConfig = EngineConfig()
    theme: Literal["light", "dark"] = "dark"
    ui: UIConfig = UIConfig()
    hebrew_calendar: HebrewCalendarConfig = HebrewCalendarConfig()
    observance: ObservanceConfig = ObservanceConfig()
    notifications: NotificationsConfig = NotificationsConfig()
    jude: JudeConfig = JudeConfig()

    @field_validator("confirmation_level")
    @classmethod
    def validate_confirmation_level(cls, v: int) -> int:
        if not 0 <= v <= 3:
            raise ValueError("confirmation_level must be between 0 and 3")
        return v


def load_config(path: str = "config.yaml") -> AppConfig:
    """Load and validate config from a YAML file.

    Supports environment variable overrides:
      ASSISTANT_OLLAMA_MODEL   → ollama.model
      ASSISTANT_STT_ENGINE     → stt_engine
      ASSISTANT_CONFIRMATION   → confirmation_level
    """
    # MACALENDAR_CONFIG redirects the DEFAULT config, like every other store in
    # this project honours an override. It was the one that did not, and the
    # gap was not theoretical: the moment `jude.enabled` was switched on in the
    # real config.yaml, the test suite read it, found the real checkout beside
    # it, and SPAWNED JUDE'S UVICORN — a 2 GB index load, from a unit test.
    # Before that it was safe only because the flag happened to be false.
    #
    # An explicitly-named file still wins, so `load_config("config.example.yaml")`
    # is unaffected; only "the default config" is redirectable.
    if path == "config.yaml":
        path = os.environ.get("MACALENDAR_CONFIG") or path
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        raise ConfigError(
            f"Config file not found: {path}\n"
            f"Copy config.example.yaml to config.yaml and fill in your values."
        )

    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {path}: {e}") from e

    if data is None:
        raise ConfigError(f"Config file is empty: {path}")

    # Environment variable overrides
    if model := os.environ.get("ASSISTANT_OLLAMA_MODEL"):
        data.setdefault("ollama", {})["model"] = model
    if engine := os.environ.get("ASSISTANT_STT_ENGINE"):
        data["stt_engine"] = engine
    if level := os.environ.get("ASSISTANT_CONFIRMATION"):
        data["confirmation_level"] = int(level)

    try:
        return AppConfig(**data)
    except Exception as e:
        raise ConfigError(f"Configuration error: {e}") from e
