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
        return {"category": "unknown", "summary": ""}

    lines = []
    for a in recent_activities:
        app = a.get("app_name", "Unknown")
        title = a.get("window_title", "") or ""
        time = a.get("time", "")
        prefix = f"[{time}] " if time else ""
        lines.append(f"{prefix}{app}: {title[:80]}")
    activity_text = "\n".join(lines)

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
        f"{self_report_section}"
        f"{global_section}"
        f"{history_section}\n"
        "Instructions:\n"
        "- Look at the pattern across entries, not just the last one.\n"
        "- If a title is vague, infer from the app and surrounding entries.\n"
        "- If the user told you what they are doing, trust that over the logs.\n\n"
        "Classify as one of: studying, working, entertainment, social_media, gaming, creative, break, idle, unknown.\n"
        "Write a specific 5-8 word description.\n\n"
        'Respond ONLY with valid JSON: {"category": "...", "summary": "..."}'
    )

    result = _parse_json_response(await ask_llm(prompt, model_kind="cheap"))
    return {
        "category": str(result.get("category", "unknown")).lower(),
        "summary": result.get("summary", ""),
    }


async def generate_hourly_summary(logs: list, hour_start: str, app_cache: dict = None, global_context: str = "", calendar_events: list = None) -> dict:
    if not logs:
        return {"summary": "No activity recorded this hour.", "productivity_score": None}

    lines = []
    for a in logs:
        app = a.get("app_name", "Unknown")
        title = a.get("window_title", "") or ""
        cat = (app_cache or {}).get(app, "")
        annotation = f" ({cat})" if cat else ""
        lines.append(f"- {app}{annotation}: {title[:80]}")
    activity_text = "\n".join(lines)

    global_section = f"User long-term context/projects: {global_context}\n\n" if global_context else ""

    calendar_section = ""
    if calendar_events:
        cal_lines = []
        for ev in calendar_events:
            try:
                from datetime import datetime as _dt
                s = _dt.fromisoformat(ev["start_at"]).strftime("%I:%M %p")
                e = _dt.fromisoformat(ev["end_at"]).strftime("%I:%M %p")
                cal_name = f" [{ev['calendar_name']}]" if ev.get("calendar_name") else ""
                cal_lines.append(f"- {s}–{e}: {ev['title']}{cal_name}")
            except Exception:
                cal_lines.append(f"- {ev.get('title', 'Event')}")
        calendar_section = "Calendar events scheduled during this hour:\n" + "\n".join(cal_lines) + "\n\n"

    prompt = (
        f"You are a productivity analyst. Here is what the user did on their Mac during {hour_start}:\n\n"
        f"{activity_text}\n\n"
        "CONTEXT: App names in parentheses show the category (working/studying/creative/entertainment/etc). "
        "'Cursor' is an AI code editor for coding. 'Antigravity' is a productivity app. "
        "'Vero' and 'LifeManager' are personal productivity tracking apps (NOT social media).\n"
        f"{global_section}"
        f"{calendar_section}"
        "Write a 2-3 sentence summary of what they worked on, how focused they were, and whether time was well spent. "
        "Do NOT begin the summary with a time range — the time is shown separately. "
        + ("If calendar events are listed, note whether Mac activity appears to match or contradict them. " if calendar_section else "")
        + "Then give a productivity score 0-10.\n\n"
        'Respond ONLY with valid JSON: {"summary": "...", "productivity_score": 7.5}'
    )

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


async def ask_gemini(prompt: str, context: Optional[str] = None) -> str:
    return await ask_llm(prompt, context=context, model_kind="default")
