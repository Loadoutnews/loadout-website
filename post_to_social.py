"""
LOADOUT-NEWS — Automatisches Social-Media-Posting
=====================================================
Wird ausgelöst, sobald articles.json auf dem main-Branch aktualisiert wird
(also sobald ein News-Update-Pull-Request gemergt wurde). Postet NEUE
Artikel als EINEN gesammelten Post pro Lauf — nicht einen Post pro Artikel:

  - Discord: EIN Post mit mehreren Embeds (bis zu 10 möglich, wir haben
    i. d. R. max. 4 neue Artikel pro Lauf) — erscheint als mehrere
    Artikel-Vorschauen untereinander in derselben Nachricht.
  - Bluesky: EIN Post mit Sammel-Text + bis zu 4 Vorschaubildern
    (Bluesky erlaubt maximal 4 Bilder pro Post).
  - Instagram: EIN Karussell-Post (mehrere Bilder zum Durchwischen in
    einem einzigen Beitrag) mit einer Bildunterschrift, die alle
    Artikel auflistet.
  - Tumblr: EIN Post im "Neuen Post Format" mit Text- und Bild-Blöcken
    pro Artikel, untereinander in einem durchlaufenden Beitrag.
  - Reddit: EIN Galerie-Post im EIGENEN Subreddit (nicht in fremden
    Gaming-Subreddits — dort gilt automatisiertes Posten schnell als
    Spam und riskiert eine Kontosperrung).

Merkt sich in social-posted.json, was schon gepostet wurde, damit nichts
doppelt gepostet wird.

Setup (als GitHub Secrets hinterlegen):
    DISCORD_WEBHOOK_URL
    BLUESKY_HANDLE
    BLUESKY_APP_PASSWORD
    INSTAGRAM_ACCESS_TOKEN
    INSTAGRAM_USER_ID
    TUMBLR_CONSUMER_KEY
    TUMBLR_CONSUMER_SECRET
    TUMBLR_OAUTH_TOKEN
    TUMBLR_OAUTH_TOKEN_SECRET
    TUMBLR_BLOG_NAME
    REDDIT_CLIENT_ID
    REDDIT_CLIENT_SECRET
    REDDIT_USERNAME
    REDDIT_PASSWORD
    REDDIT_SUBREDDIT
    PUSH_SECRET

Ausführen:
    python post_to_social.py
"""

import datetime
import json
import os
import sys

import requests

from push_helper import send_push_notification

SITE_URL = "https://loadout-news.com"
ARTICLES_FILE = "articles.json"
POSTED_FILE = "social-posted.json"

CATS = {"pc": "PC", "konsole": "Konsolen", "hardware": "Hardware", "industrie": "Industrie"}

MAX_BLUESKY_IMAGES = 4       # technisches Limit von Bluesky
MAX_INSTAGRAM_CAROUSEL = 10  # technisches Limit von Instagram (wir haben eh nie mehr als 4)


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# --- Discord ----------------------------------------------------------------
# Ein einziger Post mit mehreren Embeds — Discord zeigt diese als mehrere
# Vorschaukarten untereinander in EINER Nachricht an.

def post_discord_batch(articles):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return False

    embeds = []
    for a in articles:
        cat_label = CATS.get(a.get("cat"), "")
        embed = {
            "title": a["title"][:250],
            "description": a["teaser"][:300],
            "url": f"{SITE_URL}/artikel/{a['id']}.html",
            "color": 0x7C5CFC,
            "footer": {"text": f"LOADOUT-NEWS · {cat_label}"},
        }
        if a.get("image"):
            embed["thumbnail"] = {"url": a["image"]}
        embeds.append(embed)

    payload = {
        "content": f"🎮 **{len(articles)} neue Artikel bei LOADOUT-NEWS!**",
        "embeds": embeds[:10],  # Discord erlaubt maximal 10 Embeds pro Nachricht
    }
    resp = requests.post(webhook_url, json=payload, timeout=10)
    ok = resp.status_code in (200, 204)
    print(f"  Discord: {'✓ 1 Post mit ' + str(len(embeds)) + ' Vorschauen' if ok else '! Fehler ' + str(resp.status_code)}")
    return ok


# --- Bluesky ------------------------------------------------------------------
# Ein einziger Post mit Sammel-Text und bis zu 4 Vorschaubildern.

def post_bluesky_batch(articles):
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

    # Sammel-Text: Aufzählung aller neuen Artikel
    lines = [f"🎮 {len(articles)} neue Artikel bei LOADOUT-NEWS:"]
    for a in articles:
        lines.append(f"• {a['title']}")
    lines.append(f"\n👉 {SITE_URL}")
    text = "\n".join(lines)
    if len(text) > 295:
        text = text[:292] + "..."

    # Bis zu 4 Vorschaubilder hochladen (Bluesky-Limit)
    images = []
    for a in articles[:MAX_BLUESKY_IMAGES]:
        if not a.get("image"):
            continue
        try:
            img_resp = requests.get(a["image"], timeout=10)
            if img_resp.status_code == 200:
                upload_resp = requests.post(
                    "https://bsky.social/xrpc/com.atproto.repo.uploadBlob",
                    headers={"Authorization": f"Bearer {access_jwt}", "Content-Type": img_resp.headers.get("Content-Type", "image/jpeg")},
                    data=img_resp.content,
                    timeout=15,
                )
                if upload_resp.status_code == 200:
                    images.append({"image": upload_resp.json()["blob"], "alt": a["title"][:200]})
        except Exception:
            pass  # einzelnes Bild fehlgeschlagen — Rest des Posts soll trotzdem rausgehen

    record = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": datetime.datetime.utcnow().isoformat() + "Z",
    }
    if images:
        record["embed"] = {"$type": "app.bsky.embed.images", "images": images}

    resp = requests.post(
        "https://bsky.social/xrpc/com.atproto.repo.createRecord",
        headers=headers,
        json={"repo": did, "collection": "app.bsky.feed.post", "record": record},
        timeout=10,
    )
    ok = resp.status_code == 200
    print(f"  Bluesky: {'✓ 1 Post mit ' + str(len(images)) + ' Bildern' if ok else '! Fehler ' + str(resp.status_code) + ' ' + resp.text[:200]}")
    return ok


# --- Instagram ------------------------------------------------------------------
# Ein einziges Karussell (mehrere Bilder zum Durchwischen in einem Post) —
# technisch ein zweistufiger Prozess: erst jedes Bild als "Karussell-Kind"
# anlegen, dann alle zusammen als ein Karussell veröffentlichen.

def post_instagram_carousel(articles):
    access_token = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
    ig_user_id = os.environ.get("INSTAGRAM_USER_ID")
    if not access_token or not ig_user_id:
        return False

    articles_with_images = [a for a in articles if a.get("image")][:MAX_INSTAGRAM_CAROUSEL]
    if not articles_with_images:
        print("  Instagram: ! Keine Artikel mit Bild vorhanden — übersprungen.")
        return False
    if len(articles_with_images) == 1:
        return _post_instagram_single(articles_with_images[0], access_token, ig_user_id)

    try:
        # Schritt 1: für jeden Artikel ein "Karussell-Kind" (einzelnes Bild
        # ohne eigene Bildunterschrift) anlegen.
        child_ids = []
        for a in articles_with_images:
            child_resp = requests.post(
                f"https://graph.facebook.com/v21.0/{ig_user_id}/media",
                data={"image_url": a["image"], "is_carousel_item": "true", "access_token": access_token},
                timeout=15,
            )
            child_resp.raise_for_status()
            child_ids.append(child_resp.json()["id"])

        # Schritt 2: die gesammelte Bildunterschrift für das ganze Karussell
        caption_lines = [f"🎮 {len(articles_with_images)} neue Artikel bei LOADOUT-NEWS!\n"]
        for a in articles_with_images:
            caption_lines.append(f"• {a['title']}")
        caption_lines.append(f"\n👉 Alle Artikel über den Link in unserer Bio: {SITE_URL}\n\n#gaming #gamingnews")
        caption = "\n".join(caption_lines)

        # Schritt 3: Karussell-Container mit allen Kindern anlegen
        carousel_resp = requests.post(
            f"https://graph.facebook.com/v21.0/{ig_user_id}/media",
            data={
                "media_type": "CAROUSEL",
                "children": ",".join(child_ids),
                "caption": caption,
                "access_token": access_token,
            },
            timeout=15,
        )
        carousel_resp.raise_for_status()
        creation_id = carousel_resp.json()["id"]

        # Schritt 4: veröffentlichen
        publish_resp = requests.post(
            f"https://graph.facebook.com/v21.0/{ig_user_id}/media_publish",
            data={"creation_id": creation_id, "access_token": access_token},
            timeout=15,
        )
        ok = publish_resp.status_code == 200
        print(f"  Instagram: {'✓ 1 Karussell-Post mit ' + str(len(child_ids)) + ' Bildern' if ok else '! Fehler ' + str(publish_resp.status_code) + ' ' + publish_resp.text[:200]}")
        return ok
    except Exception as e:
        print(f"  Instagram: ! Fehlgeschlagen: {e}", file=sys.stderr)
        return False


def _post_instagram_single(article, access_token, ig_user_id):
    """Fallback für den (seltenen) Fall, dass nur ein einziger neuer Artikel
    mit Bild vorliegt — Instagram erlaubt kein Karussell mit nur 1 Bild."""
    caption = f"{article['title']}\n\n{article['teaser']}\n\n👉 Den ganzen Artikel gibt's über den Link in unserer Bio: {SITE_URL}\n\n#gaming #gamingnews"
    try:
        container_resp = requests.post(
            f"https://graph.facebook.com/v21.0/{ig_user_id}/media",
            data={"image_url": article["image"], "caption": caption, "access_token": access_token},
            timeout=15,
        )
        container_resp.raise_for_status()
        creation_id = container_resp.json()["id"]
        publish_resp = requests.post(
            f"https://graph.facebook.com/v21.0/{ig_user_id}/media_publish",
            data={"creation_id": creation_id, "access_token": access_token},
            timeout=15,
        )
        ok = publish_resp.status_code == 200
        print(f"  Instagram: {'✓ 1 Post (Einzelbild)' if ok else '! Fehler ' + str(publish_resp.status_code)}")
        return ok
    except Exception as e:
        print(f"  Instagram: ! Fehlgeschlagen: {e}", file=sys.stderr)
        return False


# --- Tumblr -------------------------------------------------------------------
# Ein einziger Post im "Neuen Post Format" (NPF) von Tumblr, der pro Artikel
# einen Text- und einen Bild-Block enthält — erscheint als durchlaufender
# Beitrag mit mehreren Bildern, ähnlich einem Karussell.

def post_tumblr_batch(articles):
    consumer_key = os.environ.get("TUMBLR_CONSUMER_KEY")
    consumer_secret = os.environ.get("TUMBLR_CONSUMER_SECRET")
    oauth_token = os.environ.get("TUMBLR_OAUTH_TOKEN")
    oauth_token_secret = os.environ.get("TUMBLR_OAUTH_TOKEN_SECRET")
    blog_name = os.environ.get("TUMBLR_BLOG_NAME")  # z. B. "loadoutnews.tumblr.com"
    if not all([consumer_key, consumer_secret, oauth_token, oauth_token_secret, blog_name]):
        return False

    try:
        from requests_oauthlib import OAuth1
    except ImportError:
        print("  Tumblr: ! Bibliothek 'requests-oauthlib' fehlt.", file=sys.stderr)
        return False

    auth = OAuth1(consumer_key, consumer_secret, oauth_token, oauth_token_secret)

    content_blocks = [{"type": "text", "text": f"🎮 {len(articles)} neue Artikel bei LOADOUT-NEWS:", "subtype": "heading1"}]
    for a in articles:
        content_blocks.append({"type": "text", "text": f"{a['title']}\n{a['teaser']}"})
        if a.get("image"):
            content_blocks.append({"type": "image", "media": [{"url": a["image"]}]})
    content_blocks.append({"type": "text", "text": f"👉 Alle Artikel: {SITE_URL}"})

    payload = {"content": content_blocks, "tags": "gaming,gamingnews,loadoutnews"}

    resp = requests.post(
        f"https://api.tumblr.com/v2/blog/{blog_name}/posts",
        auth=auth,
        json=payload,
        timeout=15,
    )
    ok = resp.status_code in (200, 201)
    print(f"  Tumblr: {'✓ 1 Post mit ' + str(len(articles)) + ' Artikeln' if ok else '! Fehler ' + str(resp.status_code) + ' ' + resp.text[:200]}")
    return ok


# --- Reddit --------------------------------------------------------------------
# Ein einziger Galerie-Post im EIGENEN Subreddit (nicht in fremden
# Gaming-Subreddits — dort würde automatisiertes Posten schnell als Spam
# gewertet und riskiert eine Kontosperrung).

def post_reddit_batch(articles):
    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    username = os.environ.get("REDDIT_USERNAME")
    password = os.environ.get("REDDIT_PASSWORD")
    subreddit_name = os.environ.get("REDDIT_SUBREDDIT")  # z. B. "LoadoutNews", ohne "r/"
    if not all([client_id, client_secret, username, password, subreddit_name]):
        return False

    try:
        import praw
    except ImportError:
        print("  Reddit: ! Bibliothek 'praw' fehlt.", file=sys.stderr)
        return False

    articles_with_images = [a for a in articles if a.get("image")]
    if not articles_with_images:
        print("  Reddit: ! Keine Artikel mit Bild vorhanden — übersprungen.")
        return False

    tmp_paths = []
    try:
        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            username=username,
            password=password,
            user_agent="loadout-news-bot/1.0",
        )
        subreddit = reddit.subreddit(subreddit_name)

        # Bilder herunterladen — PRAWs Galerie-Funktion braucht lokale Dateien, keine URLs
        gallery_images = []
        for i, a in enumerate(articles_with_images):
            img_resp = requests.get(a["image"], timeout=10)
            if img_resp.status_code != 200:
                continue
            tmp_path = f"/tmp/reddit_img_{i}.jpg"
            with open(tmp_path, "wb") as f:
                f.write(img_resp.content)
            tmp_paths.append(tmp_path)
            gallery_images.append({"image_path": tmp_path, "caption": a["title"][:180]})

        if not gallery_images:
            print("  Reddit: ! Keine Bilder konnten heruntergeladen werden.")
            return False

        title = f"🎮 {len(articles_with_images)} neue Artikel bei LOADOUT-NEWS"
        if len(gallery_images) == 1:
            # Reddit erlaubt keine Galerie mit nur 1 Bild — normaler Bild-Post stattdessen
            subreddit.submit_image(title=title, image_path=gallery_images[0]["image_path"])
        else:
            subreddit.submit_gallery(title=title, images=gallery_images)

        print(f"  Reddit: ✓ 1 Post mit {len(gallery_images)} Bildern in r/{subreddit_name}")
        return True
    except Exception as e:
        print(f"  Reddit: ! Fehlgeschlagen: {e}", file=sys.stderr)
        return False
    finally:
        for path in tmp_paths:
            try:
                os.remove(path)
            except OSError:
                pass


def main():
    articles = load_json(ARTICLES_FILE, [])
    posted = load_json(POSTED_FILE, [])
    posted_ids = set(posted)

    new_articles = [a for a in articles if a["id"] not in posted_ids]
    if not new_articles:
        print("Keine neuen Artikel seit dem letzten Social-Media-Post.")
        return

    print(f"→ {len(new_articles)} neue Artikel gefunden — poste als EINEN gesammelten Post pro Plattform.")

    post_discord_batch(new_articles)
    post_bluesky_batch(new_articles)
    post_instagram_carousel(new_articles)
    post_tumblr_batch(new_articles)
    post_reddit_batch(new_articles)

    # Push-Benachrichtigung: eine Sammel-Nachricht für alle neuen Artikel.
    if len(new_articles) == 1:
        push_body = new_articles[0]["title"][:120]
        push_url = f"/artikel/{new_articles[0]['id']}.html"
    else:
        push_body = f"{len(new_articles)} neue Artikel sind online — jetzt reinschauen!"
        push_url = "/index.html"
    send_push_notification(
        title="🎮 Neue Artikel bei LOADOUT-NEWS",
        body=push_body,
        url=push_url,
    )

    for a in new_articles:
        posted_ids.add(a["id"])

    save_json(POSTED_FILE, sorted(posted_ids))
    print(f"✓ Fertig. {len(posted_ids)} Artikel insgesamt als gepostet markiert.")


if __name__ == "__main__":
    main()
