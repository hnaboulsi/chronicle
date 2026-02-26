import httpx
from typing import Optional
import json

MISTRAL_URL = "http://localhost:11434/api/generate"

async def ask_mistral(prompt: str, context: Optional[str] = None) -> str:
    """
    Sends a prompt to the local Mistral model via Ollama API.
    """
    full_prompt = prompt
    if context:
        full_prompt = f"Context:\n{context}\n\nQuery:\n{prompt}"
        
    payload = {
        "model": "mistral",
        "prompt": full_prompt,
        "stream": False
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(MISTRAL_URL, json=payload)
            response.raise_for_status()
            data = response.json()
            return data.get("response", "").strip()
    except Exception as e:
        print(f"Error calling Mistral: {e}")
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
    response = await ask_mistral(prompt)
    return "YES" in response.upper()

async def generate_prompt(app_name: str, window_title: str) -> str:
    prompt = (
        f"The user has been using the app '{app_name}' with the window title '{window_title}' for a while. "
        "Generate a short, friendly question asking if they are doing something else (like cooking or cleaning) "
        "or if they got distracted. Keep it under 15 words."
    )
    return await ask_mistral(prompt)

async def generate_daily_recap(logs_summary: str) -> str:
    prompt = (
        "You are a personal life-manager AI. Based on the following activity logs from today, "
        "provide a concise daily summary and a productivity score out of 10. Tell the user where their time went.\n\n"
        f"Logs:\n{logs_summary}"
    )
    return await ask_mistral(prompt)
