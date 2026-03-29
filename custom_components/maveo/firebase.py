"""Firebase Installations + Remote Config client for the Maveo app project."""

from dataclasses import dataclass

import requests

# Firebase project: p2168-maveo-app (project number 448702651802)
# Source: resources.arsc in the APK (google-services.json values)
FIREBASE_API_KEY = "AIzaSyCMf8dvTS800zmF5YRQ9UaSkQCShx6LsT4"
FIREBASE_APP_ID = "1:448702651802:android:ab65c496ebe5a3785eee23"
FIREBASE_PROJECT_ID = "p2168-maveo-app"
FIREBASE_PROJECT_NUMBER = "448702651802"

_INSTALLATIONS_URL = (
    f"https://firebaseinstallations.googleapis.com/v1"
    f"/projects/{FIREBASE_PROJECT_ID}/installations"
)
_REMOTE_CONFIG_URL = (
    f"https://firebaseremoteconfig.googleapis.com/v1"
    f"/projects/{FIREBASE_PROJECT_NUMBER}/namespaces/firebase:fetch"
)


class FirebaseError(Exception):
    pass


@dataclass
class FirebaseToken:
    fid: str               # Firebase Installation ID
    refresh_token: str
    auth_token: str        # JWT (valid 7 days)
    expires_in: str        # e.g. "604800s"


def get_installation_token() -> FirebaseToken:
    """
    Register a new Firebase Installation and obtain a short-lived auth token.
    Uses the Maveo Android app's Firebase project credentials.
    Returns a FirebaseToken (valid 7 days).
    """
    resp = requests.post(
        _INSTALLATIONS_URL,
        headers={
            "x-goog-api-key": FIREBASE_API_KEY,
            "Content-Type": "application/json",
            "x-firebase-client": "android-target-sdk/34 fire-installations/17.2.0",
        },
        json={
            "appId": FIREBASE_APP_ID,
            "authVersion": "FIS_v2",
            "sdkVersion": "a:17.2.0",
        },
        timeout=10,
    )
    if not resp.ok:
        raise FirebaseError(f"Installations API error {resp.status_code}: {resp.text}")
    data = resp.json()
    auth = data.get("authToken", {})
    return FirebaseToken(
        fid=data["fid"],
        refresh_token=data["refreshToken"],
        auth_token=auth["token"],
        expires_in=auth.get("expiresIn", "?"),
    )


def fetch_remote_config(fis_token: FirebaseToken) -> dict:
    """
    Fetch Firebase Remote Config for the Maveo app project using a FIS auth token.
    Returns the raw response dict.  May return {"state": "NO_TEMPLATE"} if no
    Remote Config template is configured for this project.
    """
    resp = requests.post(
        _REMOTE_CONFIG_URL,
        headers={
            "x-goog-api-key": FIREBASE_API_KEY,
            "Content-Type": "application/json",
            "x-firebase-app-instance-id": fis_token.fid,
            "x-firebase-app-instance-id-token": fis_token.auth_token,
        },
        json={
            "appId": FIREBASE_APP_ID,
            "appInstanceId": fis_token.fid,
            "appInstanceIdToken": fis_token.auth_token,
            "languageCode": "en_US",
            "platformVersion": "34",
            "timeZone": "Europe/Berlin",
            "packageName": "com.marantec.maveoapp2",
            "sdkVersion": "21.6.0",
        },
        timeout=10,
    )
    if not resp.ok:
        raise FirebaseError(f"Remote Config error {resp.status_code}: {resp.text}")
    return resp.json()
