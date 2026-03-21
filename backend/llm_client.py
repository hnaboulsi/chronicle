import asyncio
import json
import logging
import os
import time
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from google import genai

log = logging.getLogger("vero.llm")

_VALID_PROVIDERS = ("mistral", "gemini", "openai")
_INTERACTIVE_TASKS = {"chat", "activity_summary", "prompt", "recap_feedback", "daily_recap"}

load_dotenv()

_gemini_client = None
try:
    if os.getenv("GEMINI_API_KEY"):
        _gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    else:
        log.warning("GEMINI_API_KEY environment variable not set.")
except Exception as exc:
    _gemini_client = None
    log.error("Failed to initialize Gemini client: %s", exc)

_mistral_api_key: str = (os.getenv("MISTRAL_API_KEY") or "").strip()
if not _mistral_api_key:
    log.warning("MISTRAL_API_KEY environment variable not set.")


def _normalize_provider(provider: str | None, default: str = "auto") -> str:
    cleaned = (provider or "").strip().lower()
    return cleaned if cleaned in {"auto", * _VALID_PROVIDERS} else default


def _configured_provider() -> str:
    return _normalize_provider(os.getenv("VERO_AI_PROVIDER") or os.getenv("LIFE_MANAGER_AI_PROVIDER") or "auto")


def _parse_fallback_providers(raw: str | None) -> list[str]:
    if not raw:
        return ["gemini", "openai"]
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            values = parsed
        else:
            values = []
    except Exception:
        values = [part.strip() for part in str(raw).split(",")]

    normalized: list[str] = []
    for value in values:
        provider = _normalize_provider(str(value), default="")
        if provider in _VALID_PROVIDERS and provider not in normalized:
            normalized.append(provider)
    return normalized


def _routing_mode() -> str:
    mode = (os.getenv("VERO_AI_ROUTING_MODE") or "task_aware").strip().lower()
    return mode if mode in {"task_aware", "aggressive_fallback", "strict_primary"} else "task_aware"


def _provider_available(provider: str) -> bool:
    if provider == "mistral":
        return bool(_mistral_api_key)
    if provider == "gemini":
        return _gemini_client is not None
    if provider == "openai":
        return bool(os.getenv("OPENAI_API_KEY", "").strip())
    return False


def _primary_provider() -> str:
    provider = _configured_provider()
    if provider == "auto":
        for candidate in ("mistral", "gemini", "openai"):
            if _provider_available(candidate):
                return candidate
        return "auto"
    return provider


def _task_allows_fallback(task_type: str) -> bool:
    mode = _routing_mode()
    if mode == "strict_primary":
        return False
    if mode == "aggressive_fallback":
        return True
    return task_type in _INTERACTIVE_TASKS


def _provider_order(task_type: str = "default") -> list[str]:
    primary = _primary_provider()
    fallbacks = _parse_fallback_providers(os.getenv("VERO_AI_FALLBACK_PROVIDERS"))

    candidates: list[str] = []
    if primary in _VALID_PROVIDERS:
        candidates.append(primary)
    elif primary == "auto":
        candidates.extend(_VALID_PROVIDERS)

    if _task_allows_fallback(task_type) or not candidates or not any(_provider_available(p) for p in candidates):
        candidates.extend(fallbacks)

    ordered: list[str] = []
    for provider in candidates:
        if provider in _VALID_PROVIDERS and provider not in ordered and _provider_available(provider):
            ordered.append(provider)
    return ordered


def has_llm_provider(task_type: str = "default") -> bool:
    return bool(_provider_order(task_type=task_type))


def get_routing_status(task_type: str = "default") -> dict:
    available = [provider for provider in _VALID_PROVIDERS if _provider_available(provider)]
    primary = _primary_provider()
    order = _provider_order(task_type=task_type)
    return {
        "configured": bool(available),
        "routing_mode": _routing_mode(),
        "primary_provider": primary,
        "fallback_providers": _parse_fallback_providers(os.getenv("VERO_AI_FALLBACK_PROVIDERS")),
        "available_providers": available,
        "provider_order": order,
        "effective_provider": order[0] if order else None,
        "fallback_enabled": _task_allows_fallback(task_type),
    }


def _gemini_model(task: str) -> str:
    mapping = {
        "default": os.getenv("VERO_GEMINI_MODEL") or os.getenv("LIFE_MANAGER_GEMINI_MODEL", "gemini-2.5-flash"),
        "cheap": os.getenv("VERO_GEMINI_CHEAP_MODEL") or os.getenv("LIFE_MANAGER_GEMINI_CHEAP_MODEL", "gemini-2.5-flash-lite-preview-06-17"),
    }
    return mapping.get(task, mapping["default"])


def _openai_model(task: str) -> str:
    mapping = {
        "default": os.getenv("VERO_OPENAI_MODEL") or os.getenv("LIFE_MANAGER_OPENAI_MODEL", "gpt-4o-mini"),
        "cheap": os.getenv("VERO_OPENAI_CHEAP_MODEL") or os.getenv("LIFE_MANAGER_OPENAI_CHEAP_MODEL", "gpt-4o-mini"),
    }
    return mapping.get(task, mapping["default"])


def _mistral_model(task: str) -> str:
    mapping = {
        "default": os.getenv("VERO_MISTRAL_MODEL") or "mistral-small-latest",
        "cheap": os.getenv("VERO_MISTRAL_CHEAP_MODEL") or "mistral-small-latest",
    }
    return mapping.get(task, mapping["default"])


async def _ask_gemini(prompt: str, model_kind: str = "default") -> str:
    if not _gemini_client:
        return ""
    try:
        model = _gemini_model(model_kind)
        response = await asyncio.wait_for(
            asyncio.to_thread(
                _gemini_client.models.generate_content,
                model=model,
                contents=prompt,
            ),
            timeout=60.0,
        )
        return (response.text or "").strip()
    except asyncio.TimeoutError:
        log.error("Gemini request timed out after 60s")
        return ""
    except Exception as exc:
        log.error("Error calling Gemini: %s", exc)
        return ""


async def _ask_openai(prompt: str, model_kind: str = "default") -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return ""
    model = _openai_model(model_kind)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are Vero, a personal productivity AI assistant."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                },
            )
            response.raise_for_status()
        data = response.json()
        return (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
    except Exception as exc:
        log.error("Error calling OpenAI: %s", exc)
        return ""

_MISTRAL_MIN_INTERVAL_SECONDS = float(os.getenv("VERO_MISTRAL_MIN_INTERVAL_SECONDS") or "31")
_MISTRAL_INTERACTIVE_MAX_WAIT_SECONDS = float(os.getenv("VERO_MISTRAL_INTERACTIVE_MAX_WAIT_SECONDS") or "2.0")
_mistral_rate_lock = asyncio.Lock()
_mistral_next_request_at = 0.0


async def _acquire_mistral_slot(task_type: str) -> bool:
    global _mistral_next_request_at

    # Background tasks (not in _INTERACTIVE_TASKS) should wait a long time instead of skipping.
    # User-facing tasks should skip/fallback quickly to keep the UI snappy.
    max_wait = 300.0 if task_type not in _INTERACTIVE_TASKS else _MISTRAL_INTERACTIVE_MAX_WAIT_SECONDS
    async with _mistral_rate_lock:
        wait_seconds = _mistral_next_request_at - time.monotonic()
        if wait_seconds > max_wait:
            log.info("Skipping Mistral for %s; next slot in %.1fs", task_type, wait_seconds)
            return False
        if wait_seconds > 0:
            log.info("Mistral rate limit: waiting %.1fs for %s slot", wait_seconds, task_type)
            await asyncio.sleep(wait_seconds)
        _mistral_next_request_at = time.monotonic() + _MISTRAL_MIN_INTERVAL_SECONDS
        return True


async def _ask_mistral(prompt: str, model_kind: str = "default", task_type: str = "default") -> str:
    if not _mistral_api_key:
        return ""
    if not await _acquire_mistral_slot(task_type):
        return ""
    model = _mistral_model(model_kind)
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {_mistral_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are Vero, a personal productivity AI assistant."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                },
            )
            response.raise_for_status()
        data = response.json()
        return (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
    except Exception as exc:
        log.error("Error calling Mistral: %s", exc)
        return ""


async def ask_llm(
    prompt: str,
    context: Optional[str] = None,
    model_kind: str = "default",
    task_type: str = "default",
) -> str:
    full_prompt = prompt
    if context:
        full_prompt = f"Context:\n{context}\n\nQuery:\n{prompt}"

    for provider in _provider_order(task_type=task_type):
        if provider == "openai":
            text = await _ask_openai(full_prompt, model_kind=model_kind)
        elif provider == "mistral":
            text = await _ask_mistral(full_prompt, model_kind=model_kind, task_type=task_type)
        else:
            text = await _ask_gemini(full_prompt, model_kind=model_kind)
        if text:
            return text
    return ""


def _parse_json_response(text: str) -> dict:
    cleaned = (text or "").strip()
    if not cleaned:
        return {}
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    try:
        return json.loads(cleaned.strip())
    except Exception:
        return {}


async def check_if_vague(app_name: str, window_title: str) -> bool:
    prompt = (
        f"The user is using the app '{app_name}' with the window title '{window_title}'. "
        "Does this describe a specific, productive task, or is it vague or unfocused like generic browsing or passive media? "
        "Answer ONLY with YES if vague, or NO if specific."
    )
    response = await ask_llm(prompt, model_kind="cheap", task_type="classification")
    return "YES" in response.upper()


async def generate_prompt(app_name: str, window_title: str) -> str:
    prompt = (
        f"The user has been on '{app_name}' ({window_title}) for a while. "
        "Write a short, direct check-in question asking whether this is still intentional work. "
        "Under 12 words. No filler."
    )
    return await ask_llm(prompt, model_kind="cheap", task_type="prompt")


async def generate_activity_summary(app_name: str, window_title: str) -> str:
    prompt = (
        "You are a focused productivity assistant. The user clicked a log entry to understand what they were doing. "
        f"App: '{app_name}' | Window/URL: '{window_title}'. "
        "Write 1-2 direct sentences describing what they were likely doing. "
        "If it looks distracting, say so plainly."
    )
    return await ask_llm(prompt, model_kind="default", task_type="activity_summary")


def _safe_confidence(value, default: float = 0.5) -> float:
    try:
        parsed = float(value)
        return min(1.0, max(0.0, parsed))
    except Exception:
        return default


async def generate_activity_summary_structured(entry, context_logs: list) -> dict:
    app_name = (getattr(entry, "app_name", None) or "Unknown App").strip()
    title = (getattr(entry, "window_title", None) or "").strip()
    focus_modes = {"focused", "mixed", "distracted", "unknown"}
    lines = []
    for log in context_logs[:15]:
        ts = getattr(log, "timestamp", None)
        app = getattr(log, "app_name", None) or "Unknown"
        ttl = getattr(log, "window_title", None) or ""
        when = ts.isoformat() if ts else ""
        lines.append(f"- {when} | {app}: {ttl[:100]}")
    context_text = "\n".join(lines) if lines else "- no nearby context"

    prompt = (
        "You are Vero. Generate a concise actionable brief for one activity log.\n\n"
        f"Selected log app: {app_name}\n"
        f"Selected log title: {title}\n"
        f"Nearby context logs:\n{context_text}\n\n"
        "Return JSON only with keys:\n"
        "- summary_text: 1-2 short sentences\n"
        "- focus_assessment: focused|mixed|distracted|unknown\n"
        "- confidence: 0..1\n"
        "- signals: array of 2-4 short evidence strings\n"
        "Keep it direct and useful."
    )
    result = _parse_json_response(await ask_llm(prompt, model_kind="default", task_type="activity_summary"))
    summary_text = str(result.get("summary_text") or "").strip()
    focus_assessment = str(result.get("focus_assessment") or "unknown").strip().lower()
    confidence = _safe_confidence(result.get("confidence"), 0.55)
    raw_signals_value = result.get("signals")
    raw_signals: list[Any] = raw_signals_value if isinstance(raw_signals_value, list) else []
    signals = [str(s).strip() for s in raw_signals if str(s).strip()][:4]
    if focus_assessment not in focus_modes:
        focus_assessment = "unknown"
    if not summary_text:
        return {}
    if not signals:
        signals = [f"app: {app_name}", f"title: {title[:80] or 'n/a'}"]
    return {
        "summary_text": summary_text,
        "focus_assessment": focus_assessment,
        "confidence": confidence,
        "signals": signals,
        "fallback_used": False,
    }


async def classify_activity_context(recent_activities: list, user_self_report: str = "", recent_history: list | None = None, global_context: str = "") -> dict:
    if not recent_activities:
        return {"category": "unknown", "summary": "", "presence_inference": "unknown"}

    lines = []
    for a in recent_activities:
        app = a.get("app_name", "Unknown")
        title = a.get("window_title", "") or ""
        time = a.get("time", "")
        presence = a.get("presence_state", "")
        idle_marker = " ⚠️away" if presence in ("away",) else (" ·idle" if a.get("is_idle") else "")
        prefix = f"[{time}] " if time else ""
        lines.append(f"{prefix}{app}: {title[:80]}{idle_marker}")
    activity_text = "\n".join(lines)

    # Count unique windows — many distinct windows = user was clearly switching tasks
    unique_windows = len(set(
        f"{a.get('app_name')}|{a.get('window_title', '')}" for a in recent_activities
    ))
    away_count = sum(1 for a in recent_activities if a.get("presence_state") == "away")
    total = len(recent_activities)

    presence_note = ""
    if away_count > 0 and unique_windows > 2:
        presence_note = (
            f"\nNote: The system marked {away_count}/{total} captures as 'away' (no mouse movement), "
            f"but {unique_windows} distinct windows were observed — the user was almost certainly present, "
            f"reading or watching without moving the mouse. Do NOT classify as 'idle' based on system away-status alone.\n"
        )
    elif away_count == total and unique_windows <= 1:
        presence_note = "\nNote: System shows user fully away with no window changes — they may genuinely be absent.\n"

    self_report_section = f'\nUser said they are doing: "{user_self_report}"\n' if user_self_report else ""
    history_section = ""
    if recent_history:
        history_lines = []
        for h in recent_history[:20]:
            domain = h.get("domain", "")
            title = h.get("title", "")
            if domain or title:
                history_lines.append(f"  - {domain}: {title[:60]}")
        if history_lines:
            history_section = "\nRecent browser history (last 15 min):\n" + "\n".join(history_lines) + "\n"

    global_section = f'\nUser long-term context/projects:\n{global_context}\n' if global_context else ""

    prompt = (
        "You are analyzing a user's recent Mac activity to understand what they are working on right now.\n\n"
        f"Activity log (oldest to newest):\n{activity_text}\n"
        f"{presence_note}"
        f"{self_report_section}"
        f"{global_section}"
        f"{history_section}\n"
        "Instructions:\n"
        "- Look at the pattern across entries, not just the last one.\n"
        "- If a title is vague, infer from the app and surrounding entries.\n"
        "- If the user told you what they are doing, trust that over the logs.\n"
        "- '⚠️away' means no mouse movement at capture time — this does NOT mean the user left; "
        "they may be reading, watching, or thinking.\n\n"
        "Classify category as one of: studying, working, entertainment, social_media, gaming, creative, break, idle, unknown.\n"
        "Classify presence_inference as one of: active (clearly at computer), likely_active (probably present), away (genuinely absent).\n"
        "Write a specific 5-8 word description.\n\n"
        'Respond ONLY with valid JSON: {"category": "...", "summary": "...", "presence_inference": "..."}'
    )

    result = _parse_json_response(await ask_llm(prompt, model_kind="cheap", task_type="classification"))
    return {
        "category": str(result.get("category", "unknown")).lower(),
        "summary": result.get("summary", ""),
        "presence_inference": str(result.get("presence_inference", "unknown")).lower(),
    }


async def generate_hourly_summary(
    logs: list,
    hour_start: str,
    app_cache: dict | None = None,
    global_context: str = "",
    calendar_events: list | None = None,
    upcoming_events: list | None = None,
    manual_logs: list | None = None,
    idle_pct: int = 0,
    active_pct: int = 100,
    prev_score: float | None = None,
    ios_context: dict | None = None,
    hour_of_day: int = 12,
    day_of_week: str = "Monday",
    intent: str = "",
) -> dict:
    if not logs:
        return {"summary": "No activity recorded this hour.", "productivity_score": None}

    # --- Mac activity lines ---
    lines = []
    for a in logs:
        app = a.get("app_name", "Unknown")
        title = a.get("window_title", "") or ""
        cat = (app_cache or {}).get(app, "")
        annotation = f" [{cat}]" if cat else ""
        idle_tag = " [idle]" if a.get("is_idle") else ""
        lines.append(f"- {app}{annotation}{idle_tag}: {title[:100]}")
    activity_text = "\n".join(lines)

    # --- Manual log entries ---
    manual_section = ""
    if manual_logs:
        ml = "\n".join(f"- {m['label']} ({m['activity_type']}){': ' + m['note'] if m.get('note') else ''}" for m in manual_logs)
        manual_section = f"\nUser self-reported this hour:\n{ml}\n"

    # --- Calendar section ---
    def _fmt_cal_events(events: list, label: str) -> str:
        if not events:
            return ""
        lines = []
        for ev in events:
            try:
                from datetime import datetime as _dt
                s = _dt.fromisoformat(ev["start_at"]).strftime("%I:%M %p")
                e = _dt.fromisoformat(ev["end_at"]).strftime("%I:%M %p")
                cal_name = f" [{ev['calendar_name']}]" if ev.get("calendar_name") else ""
                lines.append(f"- {s}–{e}: {ev['title']}{cal_name}")
            except Exception:
                lines.append(f"- {ev.get('title', 'Event')}")
        return f"\n{label}:\n" + "\n".join(lines) + "\n"

    calendar_section = _fmt_cal_events(calendar_events or [], "Scheduled calendar events this hour")
    upcoming_section = _fmt_cal_events(upcoming_events or [], "Coming up in the next 2 hours")

    # --- iOS / physical context ---
    ios_section = ""
    if ios_context and any(ios_context.values()):
        parts = []
        if ios_context.get("location"):
            parts.append(f"Location: {ios_context['location']}")
        if ios_context.get("activity_type"):
            parts.append(f"Physical activity: {ios_context['activity_type']}")
        if ios_context.get("steps_today") is not None:
            parts.append(f"Steps today so far: {ios_context['steps_today']}")
        ios_section = "\nPhysical context: " + ", ".join(parts) + "\n"

    # --- Previous hour trend ---
    trend_section = ""
    if prev_score is not None:
        trend_section = f"\nPrevious hour productivity score: {prev_score}/10\n"

    # --- Global context ---
    global_section = f"\nUser's ongoing projects / long-term context:\n{global_context}\n" if global_context else ""

    # --- Time context ---
    if 5 <= hour_of_day < 9:
        time_context = "early morning"
    elif 9 <= hour_of_day < 12:
        time_context = "morning (prime work hours)"
    elif 12 <= hour_of_day < 14:
        time_context = "midday / lunch window"
    elif 14 <= hour_of_day < 18:
        time_context = "afternoon (prime work hours)"
    elif 18 <= hour_of_day < 21:
        time_context = "evening"
    elif 21 <= hour_of_day < 24:
        time_context = "late evening"
    else:
        time_context = "late night / early hours"

    # --- Intent context ---
    intent_section = f"\nUSER'S CURRENT INTENT: \"{intent}\"\n" if intent else ""

    prompt = f"""You are Vero, a precise personal productivity analyst. Your goal is to provide a 'smart' and highly contextual summary of the user's hour.

TIME CONTEXT: {day_of_week}, {time_context} ({hour_of_day}:00)
PRESENCE: {active_pct}% active / {idle_pct}% idle or away this hour
{trend_section}{global_section}{intent_section}
MAC ACTIVITY (app [category] [idle if inactive]: window title):
{activity_text}
{manual_section}{calendar_section}{upcoming_section}{ios_section}
APP CATEGORY KEY: [working]=coding/dev tools/work apps, [studying]=learning, [creative]=design/video, [entertainment]=YouTube/Netflix/Reddit, [social_media]=Twitter/Instagram, [gaming]=games, [break]=confirmed rest

SCORING RUBRIC — be strict, do not inflate:
10: Exceptional — pure deep focused work/study for the full hour, zero distractions. Perfectly aligned with intent or calendar.
9:  Strong — deep work with only brief context switches (< 5 min total off-task).
8:  Good — mostly focused work, 1-2 short breaks or minor distractions.
7:  Solid — productive work majority of hour, some unrelated browsing.
6:  Moderate — roughly half productive, half distracted or idle.
5:  Below average — more distraction than work, or mostly idle with some work.
4:  Poor — primarily entertainment/social media with minor work activity.
3:  Very poor — almost entirely off-task during work hours.
2:  Wasted — full hour of entertainment/social media during prime hours.
1:  Inactive — present but not engaging (screen on, no meaningful activity).
0:  Away — no activity at all.

SCORE ADJUSTMENTS:
- Intent Alignment: If the user stated an intent (like "{intent}") and the logs match it, it's a productivity win (+0.5).
- Intent Disconnect: If logs contradict the stated intent or calendar, penalize significantly (-1.5).
- Late night (22:00+) or early morning (before 7:00): shift score up 1 if activity is reasonable.
- Confirmed break: score 5 is neutral/expected.
- High idle% (>50%): cap score at 5 unless idle is during confirmed break.

INSTRUCTIONS:
- Write 2-3 'smart' sentences. Don't just list apps.
- Synthesize: e.g., "Instead of 'Using Cursor and Chrome', say 'You made significant progress on the [Project Name] frontend as planned'."
- Correlate: Explicitly mention how activity aligns with or deviates from the calendar and the user's stated Intent.
- Be direct: Call out distractions or 'doomscrolling' by name if observed.
- productivity_score must be a float to one decimal place, strictly following the rubric.

Respond ONLY with valid JSON: {{"summary": "...", "productivity_score": 7.5}}"""

    result_text = await ask_llm(prompt, model_kind="default", task_type="hourly_summary")
    result = _parse_json_response(result_text)
    
    summary = result.get("summary", "")
    if not summary:
        # Fallback if the LLM output plaintext instead of JSON
        summary = result_text.strip()
        if summary.startswith("```"):
            summary = summary.replace("```json", "").replace("```", "").strip()
        if len(summary) > 500:
            summary = summary[:500] + "..."
            
    if not summary:
        return {
            "summary": "",
            "productivity_score": result.get("productivity_score"),
        }

    return {
        "summary": summary,
        "productivity_score": result.get("productivity_score"),
    }


async def generate_daily_recap(logs_summary: str) -> str:
    prompt = (
        "You are Vero, a personal productivity AI. Based on the following activity logs from today, "
        "provide a concise daily summary and a productivity score out of 10.\n\n"
        f"Logs:\n{logs_summary}"
    )
    return await ask_llm(prompt, model_kind="default", task_type="daily_recap")


async def analyze_calendar_day(events_text: str, now_label: str) -> dict:
    """Classify calendar events by type, generate per-event action notes, and a day insight.

    Returns: {
      "event_types": {"Event Title": "lecture|assignment|...", ...},
      "event_notes": {"Event Title": "Short action note", ...},
      "day_insight": "Short 1-2 sentence overview of the day.",
    }
    """
    prompt = (
        f"You are Vero, a personal productivity AI. Here are today's calendar events (current time: {now_label}):\n\n"
        f"{events_text}\n\n"
        "Respond ONLY with a JSON object with these three keys:\n"
        "1. 'event_types': object mapping each event title to one of these exact types:\n"
        "   - 'lecture': class session, lecture, section, discussion, recitation\n"
        "   - 'assignment': homework due, problem set, pset, mini-vitamin, quiz, assignment due, submission\n"
        "   - 'office_hours': office hours, OH, TA hours, instructor hours\n"
        "   - 'exam': midterm, final, exam, test\n"
        "   - 'meeting': 1:1, standup, interview, sync, call, team meeting\n"
        "   - 'focus': study block, work block, deep work, focus time\n"
        "   - 'personal': gym, lunch, dinner, sleep, break, personal, social\n"
        "   - 'other': anything else\n"
        "2. 'event_notes': object mapping each event title to a SHORT action note (max 8 words) describing what the user needs to DO for it. "
        "Examples: 'Submit on Gradescope', 'Attend lecture in-person', 'Drop-in TA help available', 'Midterm — review notes tonight', "
        "'Team sync on Zoom', 'Deep work block', 'No action needed'. Be specific and use imperative language.\n"
        "3. 'day_insight': 1-2 sentence summary of the day's shape — e.g. 'Two lectures and a pset due — front-load the pset before noon.' "
        "Keep it under 30 words and be actionable."
    )
    text = await ask_llm(prompt, model_kind="cheap", task_type="calendar_day")
    result = _parse_json_response(text)
    return {
        "event_types": result.get("event_types") or {},
        "event_notes": result.get("event_notes") or {},
        "day_insight": result.get("day_insight") or "",
    }


async def generate_calendar_event_briefs(
    events_text: str,
    recent_activity_text: str,
    global_context: str,
    now_label: str,
) -> dict:
    """Generate a one-sentence AI context brief for each calendar event.

    Returns: {"Event Title": "brief sentence.", ...}
    """
    prompt = (
        f"You are Vero, a personal productivity AI. Current time: {now_label}.\n"
        + (f"User context: {global_context}\n" if global_context else "")
        + (f"\nRecent activity (last 2 hours):\n{recent_activity_text}\n" if recent_activity_text else "")
        + f"\nToday's calendar events:\n{events_text}\n\n"
        "For each event write a one-sentence brief (under 20 words) grounded in the user's recent activity. "
        "If no connection is obvious, describe the event's purpose plainly.\n"
        'Respond ONLY with JSON: {"Event Title": "brief sentence.", ...}'
    )
    text = await ask_llm(prompt, model_kind="cheap", task_type="calendar_briefs")
    result = _parse_json_response(text)
    return result if isinstance(result, dict) else {}


async def ask_gemini(prompt: str, context: Optional[str] = None) -> str:
    return await ask_llm(prompt, context=context, model_kind="default", task_type="chat")
