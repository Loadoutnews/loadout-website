"""
LOADOUT-NEWS — Gemeinsame Hilfsfunktion für Push-Benachrichtigungen
========================================================================
Wird von post_to_social.py (neue Artikel), notify_releases.py und
notify_updates.py (neuer Kalender) genutzt, um Besucher:innen, die Push-
Benachrichtigungen aktiviert haben, zu benachrichtigen.

Ruft dafür die geschützte Vercel-Funktion api/send-push.js auf — die
eigentliche Zustellung an alle Abos übernimmt die Funktion selbst.

NEU: games/categories sind optionale Parameter fürs "Folge nur deinen
Spielen"-Feature — werden sie gesetzt, sendet api/send-push.js die
Benachrichtigung gezielt nur an Abonnent:innen, die eines dieser Spiele/
Kategorien in ihren Präferenzen ausgewählt haben (wer KEINE Präferenzen
gesetzt hat, bekommt weiterhin ausnahmslos alles). Bleiben beide Parameter
leer (Standard), verhält sich die Funktion GENAU wie zuvor — bestehende
Aufrufe aus notify_releases.py/notify_updates.py müssen nicht angepasst
werden.

Benötigtes GitHub Secret: PUSH_SECRET (muss mit der gleichnamigen
Vercel-Umgebungsvariable übereinstimmen).
"""

import os
import sys

import requests

SITE_URL = "https://loadout-news.com"


def send_push_notification(title, body, url="/index.html", games=None, categories=None):
    """games/categories: optionale Listen (z. B. ["gta"] oder ["konsole"])
    für gezieltes Senden — siehe Modul-Beschreibung oben. None/leer =
    Sendung an alle, wie bisher."""
    push_secret = os.environ.get("PUSH_SECRET")
    if not push_secret:
        print("  ℹ PUSH_SECRET nicht gesetzt — Push-Benachrichtigung übersprungen.", file=sys.stderr)
        return False

    payload = {"title": title, "body": body, "url": url}
    if games:
        payload["games"] = games
    if categories:
        payload["categories"] = categories

    try:
        resp = requests.post(
            f"{SITE_URL}/api/send-push",
            headers={"Content-Type": "application/json", "x-push-secret": push_secret},
            json=payload,
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            skipped_note = f", {data.get('skipped', 0)} wegen Präferenzen übersprungen" if data.get("skipped") else ""
            print(f"  ✓ Push verschickt: {data.get('sent', 0)} zugestellt, {data.get('removed', 0)} veraltete Abos entfernt{skipped_note}.")
            return True
        else:
            print(f"  ! Push-Versand fehlgeschlagen: {resp.status_code} {resp.text[:200]}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"  ! Push-Versand fehlgeschlagen: {e}", file=sys.stderr)
        return False
