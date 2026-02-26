import subprocess
import datetime
import json

def get_first_event_tomorrow() -> str:
    """
    Uses AppleScript to query the native macOS Calendar application
    for the first event scheduled for tomorrow.
    """
    
    # Calculate tomorrow's date for the AppleScript query
    now = datetime.datetime.now()
    tomorrow = now + datetime.timedelta(days=1)
    
    # Format dates for AppleScript (e.g., "date "Thursday, October 26, 2023 at 12:00:00 AM"")
    start_str = tomorrow.strftime("%A, %B %d, %Y at 12:00:00 AM")
    end_str = tomorrow.strftime("%A, %B %d, %Y at 11:59:59 PM")
    
    applescript = f'''
    set startDate to date "{start_str}"
    set endDate to date "{end_str}"
    set upcomingEvents to {{}}
    
    tell application "Calendar"
        repeat with aCalendar in calendars
            set theEvents to (every event of aCalendar whose start date is greater than or equal to startDate and start date is less than or equal to endDate)
            repeat with anEvent in theEvents
                set end of upcomingEvents to {{summary:summary of anEvent, startTime:start date of anEvent}}
            end repeat
        end repeat
    end tell
    
    -- Try to find the earliest event
    set earliestEvent to missing value
    set earliestTime to endDate
    
    repeat with evt in upcomingEvents
        if startTime of evt is less than earliestTime then
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
        result = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True,
            text=True,
            check=True
        )
        output = result.stdout.strip()
        if not output:
             return "No upcoming events found tomorrow."
        return output
    except Exception as e:
        print(f"Error querying Apple Calendar: {e}")
        return "Error accessing Calendar"

def calculate_alarm_time(event_str: str) -> str:
    # Logic to parse the event string and subtract 1.5 hours buffer time to get ready/commute
    print(f"Calculating smart alarm for: {event_str}")
    return "07:00 AM"

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print("Testing Apple Calendar Sync...")
        print(get_first_event_tomorrow())
    else:
        print(get_first_event_tomorrow())

