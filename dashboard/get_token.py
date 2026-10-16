#!/usr/bin/env python3
"""
One-time helper: run on your Mac to get a Google refresh token for Google Tasks.

  python3 -m venv .venv && .venv/bin/pip install google-auth-oauthlib
  .venv/bin/python dashboard/get_token.py path/to/client_secret.json

A browser window opens; sign in with the account that owns the tasks
(the shared books Gmail) and allow read-only access to Google Tasks.
It prints the three values to save as GitHub secrets.
"""
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/tasks.readonly"]

if len(sys.argv) != 2:
    sys.exit("Usage: get_token.py client_secret.json")

flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
info = json.load(open(sys.argv[1]))
client = info.get("installed") or info.get("web")

print("\nAdd these as GitHub repository secrets:\n")
print(f"GOOGLE_CLIENT_ID      = {client['client_id']}")
print(f"GOOGLE_CLIENT_SECRET  = {client['client_secret']}")
print(f"GOOGLE_REFRESH_TOKEN  = {creds.refresh_token}")
