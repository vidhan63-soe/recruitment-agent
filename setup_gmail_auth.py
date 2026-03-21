"""
One-time Gmail OAuth2 setup.
Run this ONCE to authorize RecruitAI to send emails from your Gmail.

Steps:
  1. Go to https://console.cloud.google.com/
  2. Create a new project (or use existing)
  3. Enable "Gmail API"  (APIs & Services → Enable APIs → search Gmail API)
  4. Create OAuth2 credentials:
       APIs & Services → Credentials → Create Credentials → OAuth client ID
       Application type: Desktop app
       Download the JSON → save as "gmail_credentials.json" in this folder
  5. Run:  python setup_gmail_auth.py
  6. A browser window opens → log in with vidhanchandraray.jnu@gmail.com
  7. Done — gmail_token.json is saved. Emails will work automatically.

You only need to run this once. The token auto-refreshes forever.
"""

import json
from pathlib import Path

CREDENTIALS_FILE = Path("gmail_credentials.json")
TOKEN_FILE = Path("gmail_token.json")
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def main():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        print("\n[ERROR] Google libraries not installed.")
        print("Run:  pip install google-auth google-auth-oauthlib google-api-python-client\n")
        return

    if not CREDENTIALS_FILE.exists():
        print(f"\n[ERROR] '{CREDENTIALS_FILE}' not found.")
        print("\nSteps to get it:")
        print("  1. Go to https://console.cloud.google.com/")
        print("  2. Create/select a project")
        print("  3. APIs & Services → Enable APIs → search 'Gmail API' → Enable")
        print("  4. APIs & Services → Credentials → Create Credentials → OAuth client ID")
        print("  5. Application type: Desktop app → Download JSON")
        print(f"  6. Rename/save it as '{CREDENTIALS_FILE}' in this folder\n")
        return

    creds = None

    # Check if token already exists
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE) as f:
            creds = Credentials.from_authorized_user_info(json.load(f), SCOPES)

    # If no valid token, run the browser auth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing existing token...")
            creds.refresh(Request())
        else:
            print("\nOpening browser for Gmail authorization...")
            print("Log in with:  vidhanchandraray.jnu@gmail.com\n")
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)

        # Save the token
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    print(f"\n✓ Success! Token saved to '{TOKEN_FILE}'")
    print("  RecruitAI can now send emails from your Gmail account.")
    print("  You don't need to run this script again.\n")


if __name__ == "__main__":
    main()
