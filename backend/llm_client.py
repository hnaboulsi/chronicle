import json
import logging
import os
from typing import Optional

import httpx
from dotenv import load_dotenv
from google import genai

log = logging.getLogger("life_manager.llm")

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
    provider = (os.getenv("LIFE_MANAGER_AI_PROVIDER") or "auto").strip().lower()
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


def _gemini_model(task: str) -> str:
    mapping = {
        "default": os.getenv("LIFE_MANAGER_GEMINI_MODEL", "gemini-2.5-flash"),
        "cheap": os.getenv("LIFE_MANAGER_GEMINI_CHEAP_MODEL", "gemini-2.5-flash-lite-preview-06-17"),
    }
    return mapping.get(task, mapping["default"])


def _openai_model(task: str) -> str:
    mapping = {
        "default": os.getenv("LIFE_MANAGER_OPENAI_MODEL", "gpt-4o-mini"),
        "cheap": os.getenv("LIFE_MANAGER_OPENAI_CHEAP_MODEL", "gpt-4o-mini"),
    }
    return mapping.get(task, mapping["default"])


async def _ask_gemini(prompt: str, model_kind: str = "default") -> str:
    if not _gemini_client:
        return ""
    try:
        response = _gemini_client.models.generate_content(
            model=_gemini_model(model_kind),
            contents=prompt,
        )
        return (response.text or "").strip()
    except Exception as exc:
        log.error("Error calling Gemini: %s", exc)
        return ""


async def _ask_openai(prompt: str, model_kind: str = "default") -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return ""
    model = _openai_model(model_kind)
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
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


async def classify_activity_context(recent_activities: list, user_self_report: str = "", recent_history: list = None) -> dict:
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

    prompt = (
        "You are analyzing a user's recent Mac activity to understand what they are working on right now.\n\n"
        f"Activity log (oldest to newest):\n{activity_text}\n"
        f"{self_report_section}"
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
        "category": result.get("category", "unknown"),
        "summary": result.get("summary", ""),
    }


async def generate_hourly_summary(logs: list, hour_start: str) -> dict:
    if not logs:
        return {"summary": "No activity recorded this hour.", "productivity_score": None}

    lines = []
    for a in logs:
        app = a.get("app_name", "Unknown")
        title = a.get("window_title", "") or ""
        lines.append(f"- {app}: {title[:80]}")
    activity_text = "\n".join(lines)

    prompt = (
        f"You are a productivity analyst. Here is what the user did on their Mac during the hour starting at {hour_start}:\n\n"
        f"{activity_text}\n\n"
        "Write a 2-3 sentence summary of what they worked on, how focused they were, and whether time was well spent. "
        "Then give a productivity score 0-10.\n\n"
        'Respond ONLY with valid JSON: {"summary": "...", "productivity_score": 7.5}'
    )

    result = _parse_json_response(await ask_llm(prompt, model_kind="default"))
    return {
        "summary": result.get("summary", "") or "Could not generate summary.",
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
