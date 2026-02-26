# Comprehensive Setup Guide: iOS Shortcuts & API Keys

Welcome to the step-by-step setup guide for your Life-Manager AI Agent. Because we are using macOS native APIs (AppleScript), there is **no need** for complex Google Cloud or OAuth setups for the calendar! 

*Note: The first time the backend tries to synchronize your Calendar, macOS will present a native pop-up asking: "Terminal would like to access your Calendar." Simply click **OK**.*

---

## Part 1: Setting up iOS Webhooks (Apple Shortcuts)

To track location and motion without needing to install or compile a custom app, we use Apple's built-in **Shortcuts** automations. 

We will create a specific automation for "Study Mode" when you arrive at the Library. You can repeat these steps for going to sleep (trigger: "Charger Is Connected") or walking (trigger: "Workout").

1. **Open the Shortcuts App** on your iPhone.
2. Tap on the **Automation** tab at the bottom center.
3. Tap the **+ (plus)** icon in the top right corner.
4. Scroll down and choose the **Arrive** trigger.
5. Tap **Choose** next to Location. Search for your "Library" or campus, adjust the radius if needed, and tap Done.
6. Make sure it says **Run Immediately** (so it doesn't prompt you every time) and turn off "Notify When Run". Click Next.
7. Tap **New Blank Automation**.
8. Tap **Add Action** and search for **"Get Contents of URL"**. Tap it.
9. In the URL bar, type: `http://10.44.178.44:8000/api/ios-telemetry` 
   *(This is the local IP address of your MacBook. Ensure your iPhone is on the same Wi-Fi network).*
10. Tap the small **blue arrow** next to the URL field to expand the options.
    - Change **Method** to `POST`.
    - Click **Request Body** and change it from "JSON" to **"JSON"** (if it isn't already).
    - Under the JSON body, click **Add new field** -> **Text**.
    - For the Key, type `location_label`. For the Text, type `Library`.
    - Click **Add new field** -> **Text**.
    - For the Key, type `activity_type`. For the Text, type `Stationary`.
11. Tap **Done** in the top right corner.

That's it! Now whenever you physically walk into the library, your iPhone will secretly dispatch a JSON webhook to your backend, enabling "Study Mode."

---

## Part 2: Gemini API Key (Temporary Testing)

You requested to test this with the Gemini API before moving exclusively to a local LLM. 

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Click **Create API Key**.
3. Create a **`.env`** file in the `backend/` directory of this repo.
4. Put the following exact text in it:
   `GEMINI_API_KEY="AIzaSyYourGeneratedKeyHere..."`

(*Your AI assistant can do this last step for you if you provide the key in the chat!*)
