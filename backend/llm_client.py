from typing import Optional
import os
from dotenv import load_dotenv
from google import genai

# Load environment variables (e.g., GEMINI_API_KEY) from .env file
load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("WARNING: GEMINI_API_KEY environment variable not set. Please provide it in a .env file or environment.")

# Initialize the Gemini client (it automatically uses GEMINI_API_KEY from the env)
try:
    client = genai.Client()
except Exception as e:
    client = None
    print(f"Failed to initialize Gemini client: {e}")

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
        print(f"Error calling Gemini: {e}")
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
        f"The user has been using the app '{app_name}' with the window title '{window_title}' for a while. "
        "Generate a short, friendly question asking if they are doing something else (like cooking or cleaning) "
        "or if they got distracted. Keep it under 15 words."
    )
    return await ask_gemini(prompt)

async def generate_daily_recap(logs_summary: str) -> str:
    prompt = (
        "You are a personal life-manager AI. Based on the following activity logs from today, "
        "provide a concise daily summary and a productivity score out of 10. Tell the user where their time went.\n\n"
        f"Logs:\n{logs_summary}"
    )
    return await ask_gemini(prompt)
