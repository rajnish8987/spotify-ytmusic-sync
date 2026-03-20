"""
Custom YouTube Music OAuth setup script.
Uses the EXACT same URLs and grant types as ytmusicapi internally,
but bypasses the bug in RefreshingToken.__init__() caused by Google's
new 'refresh_token_expires_in' field.

Usage:
    python setup_ytmusic.py
"""
import json
import time
import requests
import webbrowser

import os

CLIENT_ID = os.getenv("YT_CLIENT_ID", "YOUR_CLIENT_ID_HERE")
CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE")

# Use the EXACT same URLs that ytmusicapi uses internally
OAUTH_CODE_URL = "https://www.youtube.com/o/oauth2/device/code"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
OAUTH_SCOPE = "https://www.googleapis.com/auth/youtube"
OAUTH_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:88.0) Gecko/20100101 Firefox/88.0 Cobalt/Version"

OUTPUT_FILE = "oauth.json"

print("=== YouTube Music OAuth Setup ===\n")

# Step 1: Get device code (using YouTube's device code endpoint, not Google's)
print("Requesting device code from YouTube...")
r = requests.post(
    OAUTH_CODE_URL,
    data={"client_id": CLIENT_ID, "scope": OAUTH_SCOPE},
    headers={"User-Agent": OAUTH_USER_AGENT}
)
code_data = r.json()

if "error" in code_data:
    print(f"ERROR: {code_data['error']}: {code_data.get('error_description', '')}")
    exit(1)

device_code = code_data["device_code"]
user_code = code_data["user_code"]
verification_url = code_data["verification_url"]

url = f"{verification_url}?user_code={user_code}"
print(f"\nOpening browser to: {url}")
print(f"User code: {user_code}")
webbrowser.open(url)

input("\nSign into your YouTube Music Google account, authorize the app, then press Enter here...\n")

# Step 2: Exchange using the EXACT grant type ytmusicapi uses
print("Exchanging code for token...")
r = requests.post(
    OAUTH_TOKEN_URL,
    data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": device_code,
        "grant_type": "http://oauth.net/grant_type/device/1.0",  # ytmusicapi's exact grant type
    },
    headers={"User-Agent": OAUTH_USER_AGENT}
)
token_data = r.json()

if "error" in token_data:
    print(f"\nERROR: {token_data['error']}: {token_data.get('error_description', '')}")
    print("\nMake sure you authorized the app in your browser before pressing Enter!")
    exit(1)

# Step 3: Save only the fields ytmusicapi's Token dataclass expects
expires_in = token_data.get("expires_in", 3600)
oauth_json = {
    "access_token": token_data["access_token"],
    "refresh_token": token_data.get("refresh_token", ""),
    "scope": token_data.get("scope", OAUTH_SCOPE),
    "token_type": token_data.get("token_type", "Bearer"),
    "expires_at": int(time.time()) + expires_in,
    "expires_in": expires_in,
}

with open(OUTPUT_FILE, "w") as f:
    json.dump(oauth_json, f, indent=2)

print(f"\n✅ SUCCESS! oauth.json saved.")
print("Go back to the app and click 'I have authenticated ✓'")
