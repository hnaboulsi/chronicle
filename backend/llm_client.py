import logging
from typing import Optional
import os
import json
from dotenv import load_dotenv
from google import genai

log = logging.getLogger("life_manager.llm")

# Load environment variables (e.g., GEMINI_API_KEY) from .env file
load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    log.warning("GEMINI_API_KEY environment variable not set.")

# Initialize the Gemini client (it automatically uses GEMINI_API_KEY from the env)
try:
    client = genai.Client()
except Exception as e:
    client = None
    log.error("Failed to initialize Gemini client: %s", e)

async def ask_gemini(prompt: str, context: Optional[str] = None) -> str:
    """
    Sends a prompt to the Gemini API using gemini-2.5-flash.
    """
    if not client:
        return "Error: Gemini client not initialized."
        
    full_prompt = prompt
    if context:
        full_prompt = f"Context:\n{context}\n\nQuery:\n{prompt}"
        
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=full_prompt,
        )
        return response.text.strip()
    except Exception as e:
        log.error("Error calling Gemini: %s", e)
        return ""

async def check_if_vague(app_name: str, window_title: str) -> bool:
    """
    Asks the LLM if the current activity is 'vague' and warrants a prompt.
    """
    prompt = (
        f"The user is using the app '{app_name}' with the window title '{window_title}'. "
        "Does this describe a specific, productive task, or is it vague/unfocused (like generic web browsing or watching videos)? "
        "Answer ONLY with YES (if vague) or NO (if specific)."
    )
    response = await ask_gemini(prompt)
    return "YES" in response.upper()

async def generate_prompt(app_name: str, window_title: str) -> str:
    prompt = (
        f"The user has been on '{app_name}' ({window_title}) for a while. "
        "Write a short, direct check-in question — are they still working or did they step away? "
        "Under 12 words. No jokes. Professional tone."
    )
    return await ask_gemini(prompt)

async def generate_activity_summary(app_name: str, window_title: str) -> str:
    prompt = (
        "You are a focused productivity assistant. The user clicked a log entry to understand what they were doing. "
        f"App: '{app_name}' | Window/URL: '{window_title}'. "
        "Write 1-2 sentences describing what they were likely working on. "
        "Be direct and work-focused. No jokes, no filler. If it looks like a break or distraction, say so plainly."
    )
    return await ask_gemini(prompt)

async def classify_activity_context(recent_activities: list, user_self_report: str = "", recent_history: list = None) -> dict:
    """
    Classifies what the user is doing based on a list of recent app/tab entries.
    Uses gemini-2.5-flash-lite to conserve API quota.
    Returns: {"category": "studying", "summary": "CS 70 problem sets"}
    """
    if not recent_activities or not client:
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
        f"Activity log (oldest → newest):\n{activity_text}\n"
        f"{self_report_section}"
        f"{history_section}\n"
        "Instructions:\n"
        "- Look at the PATTERN across all entries, not just the most recent one\n"
        "- If a window title is vague ('Untitled', 'New Tab'), infer from the app and surrounding entries\n"
        "- A Google Doc titled 'Untitled' next to a course website = studying\n"
        "- A Google Doc titled 'Untitled' next to Figma = creative work\n"
        "- If the user told you what they're doing, trust that over the logs\n\n"
        "Classify as ONE of: studying, working, entertainment, social_media, gaming, creative, break, idle, unknown\n\n"
        "- studying: course sites, textbooks, homework helpers, Canvas/Gradescope, lecture notes\n"
        "- working: code editor, Notion, email, Slack, terminal, professional tasks, AI tools (Claude, Gemini, ChatGPT, Copilot)\n"
        "- entertainment: YouTube, Netflix, Reddit, sports, music, general browsing\n"
        "- social_media: Instagram, Twitter/X, TikTok, Snapchat, messaging\n"
        "- gaming: any game\n"
        "- creative: design, video editing, writing for fun\n"
        "- break: brief idle, settings, nothing meaningful\n"
        "- idle: Mac was idle or locked\n\n"
        "Write a specific 5-8 word description of what they appear to be doing.\n\n"
        'Respond ONLY with valid JSON: {"category": "...", "summary": "..."}'
    )

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash-lite-preview-06-17',
            contents=prompt,
        )
        text = response.text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text)
        return {
            "category": result.get("category", "unknown"),
            "summary": result.get("summary", "")
        }
    except Exception as e:
        log.error("Error classifying activity: %s", e)
        return {"category": "unknown", "summary": ""}


async def generate_hourly_summary(logs: list, hour_start: str) -> dict:
    """
    Generates a narrative summary of the past hour's activity.
    Uses gemini-2.5-flash for better reasoning quality.
    Returns: {"summary": "...", "productivity_score": 7.5}
    """
    if not logs or not client:
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
        "Write a 2-3 sentence summary: what they worked on, how focused they were, and whether time was well spent. "
        "Be direct and professional — no jokes or filler phrases. "
        "Then give a productivity score 0-10 (10 = fully focused on meaningful work, 0 = completely off-task).\n\n"
        'Respond ONLY with valid JSON, no markdown: {"summary": "...", "productivity_score": 7.5}'
    )

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text)
        return {
            "summary": result.get("summary", ""),
            "productivity_score": result.get("productivity_score")
        }
    except Exception as e:
        log.error("Error generating hourly summary: %s", e)
        return {"summary": "Could not generate summary.", "productivity_score": None}


async def generate_daily_recap(logs_summary: str) -> str:
    prompt = (
        "You are a personal life-manager AI. Based on the following activity logs from today, "
        "provide a concise daily summary and a productivity score out of 10. Tell the user where their time went.\n\n"
        f"Logs:\n{logs_summary}"
    )
    return await ask_gemini(prompt)
