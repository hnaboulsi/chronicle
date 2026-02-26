import subprocess

def prompt_user(question_text: str) -> str:
    """
    Displays a native macOS dialog box using AppleScript to ask the user a question.
    Returns the user's typed response or 'Canceled' if they dismissed it.
    """
    # Escaping double quotes in the question
    safe_question = question_text.replace('"', '\\"')
    
    applescript = f'''
    try
        set theResponse to display dialog "{safe_question}" default answer "" buttons {{"Cancel", "Reply"}} default button "Reply" with title "Life Manager Agent"
        return text returned of theResponse
    on error
        return "Canceled"
    end try
    '''
    
    try:
        result = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error showing prompt: {e}")
        return "Error"

def notify(message: str, title: str = "Life Manager Agent"):
    """Shows a non-blocking macOS banner notification."""
    safe_msg = message.replace('"', '\\"')
    safe_title = title.replace('"', '\\"')
    applescript = f'display notification "{safe_msg}" with title "{safe_title}"'
    subprocess.run(["osascript", "-e", applescript])

if __name__ == "__main__":
    # Test
    res = prompt_user("Are you writing on your iPad or did you get distracted?")
    print(f"User replied: {res}")
