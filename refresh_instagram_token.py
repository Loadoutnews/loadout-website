"""
LOADOUT-NEWS — Automatische Instagram-Token-Erneuerung
===========================================================
Instagram-Zugriffstoken laufen nach 60 Tagen ab. Dieses Skript erneuert
den Token automatisch VOR dem Ablauf (Instagram erlaubt eine Erneuerung,
sobald der aktuelle Token mindestens 24 Stunden alt ist) und schreibt den
neuen Token direkt als GitHub Secret zurück — ganz ohne manuelles
Eingreifen.

Läuft idealerweise alle 30 Tage (siehe Workflow), damit immer viel
Sicherheitsabstand zum tatsächlichen Ablauf nach 60 Tagen besteht.

Benötigte GitHub Secrets:
    INSTAGRAM_ACCESS_TOKEN   (der aktuelle Token — wird hier automatisch ersetzt)
    GH_PAT_FOR_SECRETS       (GitHub-Zugriffstoken mit Schreibrecht für Secrets, siehe Anleitung)

Ausführen:
    python refresh_instagram_token.py
"""

import base64
import os
import sys

import requests
from nacl import encoding, public


def refresh_instagram_token():
    current_token = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
    if not current_token:
        print("! INSTAGRAM_ACCESS_TOKEN nicht gesetzt.", file=sys.stderr)
        sys.exit(1)

    resp = requests.get(
        "https://graph.instagram.com/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": current_token},
        timeout=15,
    )
    if resp.status_code != 200:
        print(f"! Token-Erneuerung fehlgeschlagen: {resp.status_code} {resp.text}", file=sys.stderr)
        # Häufigster Grund: der Token war schon abgelaufen oder ist jünger
        # als 24 Stunden. In beiden Fällen kann hier nicht automatisch
        # repariert werden — dann muss der Token einmalig manuell wie beim
        # ersten Setup neu generiert werden.
        sys.exit(1)

    data = resp.json()
    new_token = data.get("access_token")
    expires_in = data.get("expires_in")
    if not new_token:
        print("! Keine neue Zugriffstoken in der Antwort enthalten.", file=sys.stderr)
        sys.exit(1)

    days = expires_in // 86400 if expires_in else "?"
    print(f"✓ Neuer Token erhalten, gültig für ca. {days} Tage")
    return new_token


def update_github_secret(new_token):
    pat = os.environ.get("GH_PAT_FOR_SECRETS")
    repo = os.environ.get("GH_REPO")
    if not pat or not repo:
        print("! GH_PAT_FOR_SECRETS oder GH_REPO nicht gesetzt.", file=sys.stderr)
        sys.exit(1)

    headers = {"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"}

    # Öffentlichen Schlüssel des Repos holen, um das Secret genau so zu
    # verschlüsseln, wie GitHub es für "Secrets" verlangt (Ende-zu-Ende,
    # das Secret selbst ist nie unverschlüsselt sichtbar).
    key_resp = requests.get(f"https://api.github.com/repos/{repo}/actions/secrets/public-key", headers=headers, timeout=15)
    key_resp.raise_for_status()
    key_data = key_resp.json()

    public_key = public.PublicKey(key_data["key"].encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(new_token.encode("utf-8"))
    encrypted_b64 = base64.b64encode(encrypted).decode("utf-8")

    put_resp = requests.put(
        f"https://api.github.com/repos/{repo}/actions/secrets/INSTAGRAM_ACCESS_TOKEN",
        headers=headers,
        json={"encrypted_value": encrypted_b64, "key_id": key_data["key_id"]},
        timeout=15,
    )
    if put_resp.status_code in (201, 204):
        print("✓ GitHub Secret INSTAGRAM_ACCESS_TOKEN automatisch aktualisiert")
    else:
        print(f"! Secret-Update fehlgeschlagen: {put_resp.status_code} {put_resp.text}", file=sys.stderr)
        sys.exit(1)


def main():
    new_token = refresh_instagram_token()
    update_github_secret(new_token)


if __name__ == "__main__":
    main()
