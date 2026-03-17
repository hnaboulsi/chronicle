import asyncio
import json
import logging
import os
from typing import Optional

import httpx
from dotenv import load_dotenv
from google import genai

log = logging.getLogger("vero.llm")

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


def _configured_provider() -> str:
    provider = (os.getenv("VERO_AI_PROVIDER") or os.getenv("LIFE_MANAGER_AI_PROVIDER") or "auto").strip().lower()
    if provider not in {"auto", "gemini", "openai"}:
        provider = "auto"
    return provider


def _provider_order() -> list[str]:
    provider = _configured_provider()
    if provider == "gemini":
        return ["gemini", "openai"]
    if provider == "openai":
        return ["openai", "gemini"]
    if os.getenv("OPENAI_API_KEY"):
        return ["openai", "gemini"]
    return ["gemini", "openai"]


def has_llm_provider() -> bool:
    return bool(_gemini_client or os.getenv("OPENAI_API_KEY", "").strip())


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


async def ask_llm(prompt: str, context: Optional[str] = None, model_kind: str = "default") -> str:
    full_prompt = prompt
    if context:
        full_prompt = f"Context:\n{context}\n\nQuery:\n{prompt}"

    for provider in _provider_order():
        if provider == "openai":
            text = await _ask_openai(full_prompt, model_kind=model_kind)
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
    response = await ask_llm(prompt, model_kind="cheap")
    return "YES" in response.upper()


async def generate_prompt(app_name: str, window_title: str) -> str:
    prompt = (
        f"The user has been on '{app_name}' ({window_title}) for a while. "
        "Write a short, direct check-in question asking whether this is still intentional work. "
        "Under 12 words. No filler."
    )
    return await ask_llm(prompt, model_kind="cheap")


async def generate_activity_summary(app_name: str, window_title: str) -> str:
    prompt = (
        "You are a focused productivity assistant. The user clicked a log entry to understand what they were doing. "
        f"App: '{app_name}' | Window/URL: '{window_title}'. "
        "Write 1-2 direct sentences describing what they were likely doing. "
        "If it looks distracting, say so plainly."
    )
    return await ask_llm(prompt, model_kind="default")


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
    result = _parse_json_response(await ask_llm(prompt, model_kind="default"))
    summary_text = str(result.get("summary_text") or "").strip()
    focus_assessment = str(result.get("focus_assessment") or "unknown").strip().lower()
    confidence = _safe_confidence(result.get("confidence"), 0.55)
    signals = result.get("signals") if isinstance(result.get("signals"), list) else []
    signals = [str(s).strip() for s in signals if str(s).strip()][:4]
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


async def classify_activity_context(recent_activities: list, user_self_report: str = "", recent_history: list = None, global_context: str = "") -> dict:
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

    result = _parse_json_response(await ask_llm(prompt, model_kind="cheap"))
    return {
        "category": str(result.get("category", "unknown")).lower(),
        "summary": result.get("summary", ""),
        "presence_inference": str(result.get("presence_inference", "unknown")).lower(),
    }


async def generate_hourly_summary(
    logs: list,
    hour_start: str,
    app_cache: dict = None,
    global_context: str = "",
    calendar_events: list = None,
    upcoming_events: list = None,
    manual_logs: list = None,
    idle_pct: int = 0,
    active_pct: int = 100,
    prev_score: float | None = None,
    ios_context: dict = None,
    hour_of_day: int = 12,
    day_of_week: str = "Monday",
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

    prompt = f"""You are Vero, a precise personal productivity analyst. Analyze this hour of activity and return a JSON object.

TIME CONTEXT: {day_of_week}, {time_context} ({hour_of_day}:00)
PRESENCE: {active_pct}% active / {idle_pct}% idle or away this hour
{trend_section}{global_section}
MAC ACTIVITY (app [category] [idle if inactive]: window title):
{activity_text}
{manual_section}{calendar_section}{upcoming_section}{ios_section}
APP CATEGORY KEY: [working]=coding/dev tools/work apps, [studying]=learning, [creative]=design/video, [entertainment]=YouTube/Netflix/Reddit, [social_media]=Twitter/Instagram, [gaming]=games, [break]=confirmed rest

SCORING RUBRIC — be strict, do not inflate:
10: Exceptional — pure deep focused work/study for the full hour, zero distractions
9:  Strong — deep work with only brief context switches (< 5 min total off-task)
8:  Good — mostly focused work, 1-2 short breaks or minor distractions
7:  Solid — productive work majority of hour, some unrelated browsing
6:  Moderate — roughly half productive, half distracted or idle
5:  Below average — more distraction than work, or mostly idle with some work
4:  Poor — primarily entertainment/social media with minor work activity
3:  Very poor — almost entirely off-task during work hours
2:  Wasted — full hour of entertainment/social media during prime hours
1:  Inactive — present but not engaging (screen on, no meaningful activity)
0:  Away — no activity at all

SCORE ADJUSTMENTS:
- Late night (22:00+) or early morning (before 7:00): lower expectations, shift score up 1 if activity is reasonable for the time
- Confirmed break (manual log or calendar block): score 5 is neutral/expected, not penalized
- Calendar mismatch (calendar says meeting but Mac shows unrelated browsing): note it, penalize 1-2 points
- Calendar match (working on what calendar says): bonus +0.5
- High idle% (>50%): cap score at 5 unless idle is during confirmed break

INSTRUCTIONS:
- Write 2-3 sentences: what specifically they did, how focused, and one concrete observation (pattern, concern, or positive)
- If calendar events exist, explicitly state whether Mac activity matches or contradicts them
- Do NOT start with a time range — just describe the activity directly
- Be specific about app names and what they suggest (e.g. "Cursor suggests active coding" not just "used coding tools")
- productivity_score must be a float to one decimal place, strictly following the rubric above

Respond ONLY with valid JSON: {{"summary": "...", "productivity_score": 7.5}}"""

    result_text = await ask_llm(prompt, model_kind="default")
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
    return await ask_llm(prompt, model_kind="default")


async def analyze_calendar_day(events_text: str, now_label: str) -> dict:
    """Classify calendar events by type and generate a one-sentence day insight.

    Returns: {
      "event_types": {"Event Title": "meeting|focus|class|deadline|personal|other", ...},
      "day_insight": "Short 1-2 sentence overview of the day.",
    }
    """
    prompt = (
        f"You are Vero, a personal productivity AI. Here are today's calendar events (current time: {now_label}):\n\n"
        f"{events_text}\n\n"
        "Respond ONLY with a JSON object:\n"
        "1. 'event_types': object mapping each event title to one of these exact types:\n"
        "   - 'lecture': class session, lecture, section, discussion, recitation\n"
        "   - 'assignment': homework due, problem set, pset, mini-vitamin, quiz, assignment due, submission\n"
        "   - 'office_hours': office hours, OH, TA hours, instructor hours\n"
        "   - 'exam': midterm, final, exam, test\n"
        "   - 'meeting': 1:1, standup, interview, sync, call, team meeting\n"
        "   - 'focus': study block, work block, deep work, focus time\n"
        "   - 'personal': gym, lunch, dinner, sleep, break, personal, social\n"
        "   - 'other': anything else\n"
        "2. 'day_insight': 1-2 sentence summary of the day's shape — e.g. 'Two lectures and a pset due — front-load the pset before noon.' "
        "Keep it under 30 words and be actionable."
    )
    text = await ask_llm(prompt, model_kind="cheap")
    result = _parse_json_response(text)
    return {
        "event_types": result.get("event_types") or {},
        "day_insight": result.get("day_insight") or "",
    }


async def ask_gemini(prompt: str, context: Optional[str] = None) -> str:
    return await ask_llm(prompt, context=context, model_kind="default")
