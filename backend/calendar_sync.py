import datetime
import os.path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

def _get_credentials():
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists("credentials.json"):
                print("Missing credentials.json. Please follow Google API setup.")
                return None
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return creds

def get_first_event_tomorrow() -> str:
    """Shows basic usage of the Google Calendar API.
    Prints the start and name of the next 10 events on the user's calendar.
    """
    creds = _get_credentials()
    if not creds:
        return "No credentials"

    try:
        service = build("calendar", "v3", credentials=creds)

        # Call the Calendar API
        now = datetime.datetime.utcnow()
        # Get start of tomorrow
        tomorrow = now + datetime.timedelta(days=1)
        start_of_tomorrow = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + "Z"
        end_of_tomorrow = tomorrow.replace(hour=23, minute=59, second=59, microsecond=0).isoformat() + "Z"

        print(f"Getting first event for tomorrow...")
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=start_of_tomorrow,
                timeMax=end_of_tomorrow,
                maxResults=1,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])

        if not events:
            return "No upcoming events found tomorrow."

        event = events[0]
        start = event["start"].get("dateTime", event["start"].get("date"))
        return f"{event['summary']} at {start}"

    except HttpError as error:
        print(f"An error occurred: {error}")
        return f"Error: {error}"

def calculate_alarm_time(event_str: str) -> str:
    # Logic to parse the event string and subtract 1.5 hours buffer time to get ready/commute
    # If no event, maybe default to 8:00 AM
    print(f"Calculating smart alarm for: {event_str}")
    # Mocking return
    return "07:00 AM"

if __name__ == "__main__":
    print(get_first_event_tomorrow())
