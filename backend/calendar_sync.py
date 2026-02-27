"""
calendar_sync.py — Write activity sessions and walks to Apple Calendar.
Apple Calendar auto-syncs to Google Calendar if Google is added in
System Settings > Internet Accounts.
"""

import logging
import subprocess
import datetime

log = logging.getLogger("life_manager.calendar")

CALENDAR_NAME = "Life Manager"


def _run_applescript(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True
    )
    return result.stdout.strip()


def ensure_life_manager_calendar():
    """Create the 'Life Manager' calendar if it doesn't already exist."""
    script = f'''
    tell application "Calendar"
        if not (exists calendar "{CALENDAR_NAME}") then
            make new calendar with properties {{name:"{CALENDAR_NAME}"}}
        end if
    end tell
    '''
    _run_applescript(script)


def create_event(title: str, start_dt: datetime.datetime, end_dt: datetime.datetime, notes: str = ""):
    """Add an event to the Life Manager calendar via AppleScript."""
    fmt = "%A, %B %d, %Y at %I:%M:%S %p"
    start_str = start_dt.strftime(fmt)
    end_str = end_dt.strftime(fmt)

    title_safe = title.replace('"', "'")
    notes_safe = notes.replace('"', "'")

    script = f'''
    tell application "Calendar"
        tell calendar "{CALENDAR_NAME}"
            make new event with properties {{summary:"{title_safe}", start date:date "{start_str}", end date:date "{end_str}", description:"{notes_safe}"}}
        end tell
    end tell
    '''
    try:
        _run_applescript(script)
        log.info("Calendar event created: %s (%s-%s)", title, start_dt.strftime('%H:%M'), end_dt.strftime('%H:%M'))
    except Exception as e:
        log.error("Calendar error: %s", e)


def create_session_event(category: str, summary: str, start_dt: datetime.datetime, end_dt: datetime.datetime):
    """Create a calendar event for a completed work/study/creative session."""
    emoji_map = {
        "studying": "Study",
        "working": "Work",
        "creative": "Creative",
        "entertainment": "Entertainment",
        "social_media": "Social Media",
        "gaming": "Gaming",
        "break": "Break",
    }
    label = emoji_map.get(category, category.replace("_", " ").title())
    duration_min = max(1, int((end_dt - start_dt).total_seconds() / 60))
    display = summary if summary else label
    title = f"{display} ({duration_min} min)"
    notes = f"Auto-logged by Life Manager | Category: {category}"
    create_event(title, start_dt, end_dt, notes)


def create_walk_event(location_from: str, location_to: str, start_dt: datetime.datetime, end_dt: datetime.datetime):
    """Create a calendar event for a detected walk."""
    duration_min = max(1, int((end_dt - start_dt).total_seconds() / 60))
    if location_from and location_to and location_from != location_to:
        title = f"Walk: {location_from} to {location_to} ({duration_min} min)"
    else:
        label = location_from or location_to or "Unknown"
        title = f"Walk near {label} ({duration_min} min)"
    create_event(title, start_dt, end_dt)


def create_location_event(location_label: str, arrival_dt: datetime.datetime, departure_dt: datetime.datetime):
    """Create a calendar event for a location visit."""
    duration_min = max(1, int((departure_dt - arrival_dt).total_seconds() / 60))
    title = f"At {location_label} ({duration_min} min)"
    create_event(title, arrival_dt, departure_dt)


def get_first_event_tomorrow() -> str:
    """Query Apple Calendar for the first event tomorrow (used by alarm logic)."""
    now = datetime.datetime.now()
    tomorrow = now + datetime.timedelta(days=1)
    start_str = tomorrow.strftime("%A, %B %d, %Y at 12:00:00 AM")
    end_str = tomorrow.strftime("%A, %B %d, %Y at 11:59:59 PM")

    applescript = f'''
    set startDate to date "{start_str}"
    set endDate to date "{end_str}"
    set upcomingEvents to {{}}
    tell application "Calendar"
        repeat with aCalendar in calendars
            set theEvents to (every event of aCalendar whose start date >= startDate and start date <= endDate)
            repeat with anEvent in theEvents
                set end of upcomingEvents to {{summary:summary of anEvent, startTime:start date of anEvent}}
            end repeat
        end repeat
    end tell
    set earliestEvent to missing value
    set earliestTime to endDate
    repeat with evt in upcomingEvents
        if startTime of evt < earliestTime then
            set earliestTime to startTime of evt
            set earliestEvent to summary of evt
        end if
    end repeat
    if earliestEvent is not missing value then
        return earliestEvent & " at " & earliestTime
    else
        return "No upcoming events found tomorrow."
    end if
    '''
    try:
        result = subprocess.run(["osascript", "-e", applescript], capture_output=True, text=True, check=True)
        return result.stdout.strip() or "No upcoming events found tomorrow."
    except Exception as e:
        log.error("Error querying Apple Calendar: %s", e)
        return "Error accessing Calendar"
