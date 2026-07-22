"""
LOADOUT-NEWS — Automatisches Social-Media-Posting
=====================================================
Wird ausgelöst, sobald articles.json auf dem main-Branch aktualisiert wird
(also sobald ein News-Update-Pull-Request gemergt wurde). Postet neue
Artikel automatisch:
  - Discord: JEDER neue Artikel (eigener Community-Kanal, ruhig ausführlich)
  - Bluesky:  nur der EINE Artikel mit dem höchsten Hype-Wert pro Lauf
  - Instagram: nur der EINE Artikel mit dem höchsten Hype-Wert pro Lauf
    (öffentliche Broadcast-Plattformen — bewusst zurückhaltender, um nicht
    wie Spam zu wirken)

Merkt sich in social-posted.json, was schon gepostet wurde, damit nichts
doppelt gepostet wird.

Setup (als GitHub Secrets hinterlegen):
    DISCORD_WEBHOOK_URL
    BLUESKY_HANDLE
    BLUESKY_APP_PASSWORD
    INSTAGRAM_ACCESS_TOKEN
    INSTAGRAM_USER_ID

Ausführen:
    python post_to_social.py
"""

import json
import os
import sys

import requests

from push_helper import send_push_notification

SITE_URL = "https://loadout-news.com"
ARTICLES_FILE = "articles.json"
POSTED_FILE = "social-posted.json"

CATS = {"pc": "PC", "konsole": "Konsolen", "hardware": "Hardware", "industrie": "Industrie"}


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# --- Discord --------------------------------------------------------------

def post_discord(article):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return False

    url = f"{SITE_URL}/artikel/{article['id']}.html"
    cat_label = CATS.get(article.get("cat"), "")
    embed = {
        "title": article["title"],
        "description": article["teaser"],
        "url": url,
        "color": 0x7C5CFC,
        "footer": {"text": f"LOADOUT-NEWS · {cat_label}"},
    }
    if article.get("image"):
        embed["image"] = {"url": article["image"]}

    payload = {"embeds": [embed]}
    resp = requests.post(webhook_url, json=payload, timeout=10)
    ok = resp.status_code in (200, 204)
    print(f"  Discord: {'✓' if ok else '! Fehler ' + str(resp.status_code)}")
    return ok


# --- Bluesky ----------------------------------------------------------------

def post_bluesky(article):
    handle = os.environ.get("BLUESKY_HANDLE")
    app_password = os.environ.get("BLUESKY_APP_PASSWORD")
    if not handle or not app_password:
        return False

    try:
        session_resp = requests.post(
            "https://bsky.social/xrpc/com.atproto.server.createSession",
            json={"identifier": handle, "password": app_password},
            timeout=10,
        )
        session_resp.raise_for_status()
        session = session_resp.json()
        access_jwt = session["accessJwt"]
        did = session["did"]
    except Exception as e:
        print(f"  Bluesky: ! Login fehlgeschlagen: {e}", file=sys.stderr)
        return False

    headers = {"Authorization": f"Bearer {access_jwt}", "Content-Type": "application/json"}
    url = f"{SITE_URL}/artikel/{article['id']}.html"
    text = f"{article['title']}\n\n{article['teaser']}"
    if len(text) > 290:
        text = text[:287] + "..."

    # Vorschaubild hochladen (optional, verbessert die Link-Karte)
    thumb_blob = None
    if article.get("image"):
        try:
            img_resp = requests.get(article["image"], timeout=10)
            if img_resp.status_code == 200:
                upload_resp = requests.post(
                    "https://bsky.social/xrpc/com.atproto.repo.uploadBlob",
                    headers={"Authorization": f"Bearer {access_jwt}", "Content-Type": img_resp.headers.get("Content-Type", "image/jpeg")},
                    data=img_resp.content,
                    timeout=15,
                )
                if upload_resp.status_code == 200:
                    thumb_blob = upload_resp.json()["blob"]
        except Exception:
            pass  # Vorschaubild ist optional — Post soll trotzdem rausgehen

    embed = {
        "$type": "app.bsky.embed.external",
        "external": {
            "uri": url,
            "title": article["title"],
            "description": article["teaser"],
        },
    }
    if thumb_blob:
        embed["external"]["thumb"] = thumb_blob

    record = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "embed": embed,
    }

    resp = requests.post(
        "https://bsky.social/xrpc/com.atproto.repo.createRecord",
        headers=headers,
        json={"repo": did, "collection": "app.bsky.feed.post", "record": record},
        timeout=10,
    )
    ok = resp.status_code == 200
    print(f"  Bluesky: {'✓' if ok else '! Fehler ' + str(resp.status_code) + ' ' + resp.text[:200]}")
    return ok


# --- Instagram ----------------------------------------------------------------

def post_instagram(article):
    access_token = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
    ig_user_id = os.environ.get("INSTAGRAM_USER_ID")
    if not access_token or not ig_user_id:
        return False
    if not article.get("image"):
        print("  Instagram: ! Kein Bild vorhanden, Instagram erfordert immer ein Bild — übersprungen.")
        return False

    caption = f"{article['title']}\n\n{article['teaser']}\n\n👉 Den ganzen Artikel gibt's über den Link in unserer Bio: {SITE_URL}\n\n#gaming #gamingnews #{article.get('cat','')}"

    try:
        # Schritt 1: Medien-Container erstellen
        container_resp = requests.post(
            f"https://graph.facebook.com/v21.0/{ig_user_id}/media",
            data={"image_url": article["image"], "caption": caption, "access_token": access_token},
            timeout=15,
        )
        container_resp.raise_for_status()
        creation_id = container_resp.json()["id"]

        # Schritt 2: Veröffentlichen
        publish_resp = requests.post(
            f"https://graph.facebook.com/v21.0/{ig_user_id}/media_publish",
            data={"creation_id": creation_id, "access_token": access_token},
            timeout=15,
        )
        ok = publish_resp.status_code == 200
        print(f"  Instagram: {'✓' if ok else '! Fehler ' + str(publish_resp.status_code) + ' ' + publish_resp.text[:200]}")
        return ok
    except Exception as e:
        print(f"  Instagram: ! Fehlgeschlagen: {e}", file=sys.stderr)
        return False


def main():
    articles = load_json(ARTICLES_FILE, [])
    posted = load_json(POSTED_FILE, [])
    posted_ids = set(posted)

    new_articles = [a for a in articles if a["id"] not in posted_ids]
    if not new_articles:
        print("Keine neuen Artikel seit dem letzten Social-Media-Post.")
        return

    print(f"→ {len(new_articles)} neue Artikel gefunden.")

    # Discord: jeden neuen Artikel einzeln posten
    for a in new_articles:
        print(f"Discord-Post: {a['title'][:60]}")
        post_discord(a)
        posted_ids.add(a["id"])

    # Bluesky & Instagram: nur den einen mit dem höchsten Hype-Wert
    top_article = max(new_articles, key=lambda a: a.get("hype", 0))
    print(f"Bluesky/Instagram-Post (höchster Hype): {top_article['title'][:60]}")
    post_bluesky(top_article)
    post_instagram(top_article)

    # Push-Benachrichtigung: ebenfalls nur der gehypteste neue Artikel, um
    # Nutzer:innen nicht mit zu vielen Benachrichtigungen zu nerven.
    send_push_notification(
        title="🎮 Neuer Artikel bei LOADOUT-NEWS",
        body=top_article["title"][:120],
        url=f"/artikel/{top_article['id']}.html",
    )

    save_json(POSTED_FILE, sorted(posted_ids))
    print(f"✓ Fertig. {len(posted_ids)} Artikel insgesamt als gepostet markiert.")


if __name__ == "__main__":
    main()
