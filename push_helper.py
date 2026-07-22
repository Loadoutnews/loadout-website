"""
LOADOUT-NEWS — Gemeinsame Hilfsfunktion für Push-Benachrichtigungen
========================================================================
Wird von post_to_social.py (neue Artikel), notify_releases.py und
notify_updates.py (neuer Kalender) genutzt, um Besucher:innen, die Push-
Benachrichtigungen aktiviert haben, zu benachrichtigen.

Ruft dafür die geschützte Vercel-Funktion api/send-push.js auf — die
eigentliche Zustellung an alle Abos übernimmt die Funktion selbst.

Benötigtes GitHub Secret: PUSH_SECRET (muss mit der gleichnamigen
Vercel-Umgebungsvariable übereinstimmen).
"""

import os
import sys

import requests

SITE_URL = "https://loadout-news.com"


def send_push_notification(title, body, url="/index.html"):
    push_secret = os.environ.get("PUSH_SECRET")
    if not push_secret:
        print("  ℹ PUSH_SECRET nicht gesetzt — Push-Benachrichtigung übersprungen.", file=sys.stderr)
        return False

    try:
        resp = requests.post(
            f"{SITE_URL}/api/send-push",
            headers={"Content-Type": "application/json", "x-push-secret": push_secret},
            json={"title": title, "body": body, "url": url},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            print(f"  ✓ Push verschickt: {data.get('sent', 0)} zugestellt, {data.get('removed', 0)} veraltete Abos entfernt.")
            return True
        else:
            print(f"  ! Push-Versand fehlgeschlagen: {resp.status_code} {resp.text[:200]}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"  ! Push-Versand fehlgeschlagen: {e}", file=sys.stderr)
        return False
