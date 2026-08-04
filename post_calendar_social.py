"""
LOADOUT-NEWS — Kalender-Social-Media-Posting
================================================
Postet automatisch, wenn ein neuer Release-Kalender-Monat ODER wirklich
NEUE Einträge im Update-Kalender veröffentlicht werden — im selben
Format/Aufbau wie die normalen Artikel-Posts (siehe post_to_social.py):
Intro-Folie mit 2×2-Bildraster, eine Folie pro Eintrag, feste Outro-Folie,
plus Discord/Bluesky/Tumblr/Reddit-Posts.

  - Release-Kalender: releases.json wird jeden Monat komplett neu
    geschrieben. Sobald ein neuer Monat erkannt wird (verglichen mit dem
    zuletzt geposteten Monat), wird EIN Post mit den interessantesten
    Releases (höchster Hype-Wert) erstellt, mit Hinweis auf die Anzahl
    weiterer Releases diesen Monat.

  - Update-Kalender: updates.json wächst laufend (neue Einträge kommen
    dazu, abgelaufene verschwinden automatisch). Hier wird verglichen,
    welche Update-IDs seit dem letzten Lauf WIRKLICH NEU sind — nur die
    werden gepostet, nicht der komplette, weiterhin gültige Bestand.

Merkt sich in calendar-posted.json den zuletzt geposteten Release-Monat
sowie alle bereits geposteten Update-IDs.

Setup: dieselben GitHub Secrets wie post_to_social.py (Discord, Bluesky,
Buffer, Tumblr, Zernio) — dieses Skript nutzt post_to_social.py als Modul
und importiert dessen Hilfsfunktionen, statt sie zu duplizieren.

Ausführen:
    python post_calendar_social.py
"""

import datetime
import json
import os
import sys

import requests

import post_to_social as pts
from push_helper import send_push_notification

SITE_URL = "https://loadout-news.com"
RELEASES_FILE = "releases.json"
UPDATES_FILE = "updates.json"
POSTED_FILE = "calendar-posted.json"

MAX_ITEMS_PER_CALENDAR_POST = 4  # wie viele Releases/Updates max. als eigene Folie gezeigt werden

SLIDE_OUTPUT_DIR = "social-slides"
OUTRO_SLIDE_PATH = "social-assets/outro-slide.jpg"


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def calendar_hashtags(kind):
    extra = ["gamerelease", "newgames", "releasecalendar"] if kind == "release" else ["gameupdate", "patchnotes"]
    return pts.GENERAL_HASHTAGS + extra


# --- Discord ------------------------------------------------------------

def post_discord_calendar(kind_label, emoji, headline, subheadline, items, page_url):
    webhook_url = pts.env("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return False

    embeds = []
    for item in items:
        embed = {
            "title": item["title"][:250],
            "url": page_url,
            "color": 0x7C5CFC,
            "footer": {"text": f"LOADOUT-NEWS · {kind_label}"},
        }
        if item.get("image"):
            embed["thumbnail"] = {"url": item["image"]}
        embeds.append(embed)

    payload = {
        "content": f"{emoji} **{headline}**\n{subheadline}\n👉 {page_url}",
        "embeds": embeds[:10],
    }
    resp = requests.post(webhook_url, json=payload, timeout=10)
    ok = resp.status_code in (200, 204)
    print(f"  Discord: {'✓ 1 Post mit ' + str(len(embeds)) + ' Vorschauen' if ok else '! Fehler ' + str(resp.status_code)}")
    return ok


# --- Bluesky ------------------------------------------------------------

def post_bluesky_calendar(emoji, headline, subheadline, items, page_url):
    handle = pts.env("BLUESKY_HANDLE")
    app_password = pts.env("BLUESKY_APP_PASSWORD")
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
    MAX_CHARS = 300

    # Link bekommt garantiert Platz — wie beim Artikel-Posting wird nur
    # die Überschrift bei Bedarf gekürzt, nie der Link.
    footer = f"👉 {page_url}"
    budget = MAX_CHARS - len(footer) - len(subheadline) - 2
    text_headline = f"{emoji} {headline}"
    if len(text_headline) > budget:
        text_headline = text_headline[:max(budget - 1, 0)].rstrip() + "…"
    text = f"{text_headline}\n{subheadline}\n{footer}"
    if len(text) > MAX_CHARS:
        text = f"{text_headline}\n{footer}"  # Rückfall: Subheadline weglassen, Link bleibt garantiert

    facets = []
    if page_url in text:
        url_char_start = text.rindex(page_url)
        byte_start = len(text[:url_char_start].encode("utf-8"))
        byte_end = byte_start + len(page_url.encode("utf-8"))
        facets.append({
            "index": {"byteStart": byte_start, "byteEnd": byte_end},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": page_url}],
        })

    images = []
    for item in items[:pts.MAX_BLUESKY_IMAGES]:
        if not item.get("image"):
            continue
        try:
            img_resp = requests.get(item["image"], timeout=10)
            if img_resp.status_code == 200:
                upload_resp = requests.post(
                    "https://bsky.social/xrpc/com.atproto.repo.uploadBlob",
                    headers={"Authorization": f"Bearer {access_jwt}", "Content-Type": img_resp.headers.get("Content-Type", "image/jpeg")},
                    data=img_resp.content,
                    timeout=15,
                )
                if upload_resp.status_code == 200:
                    images.append({"image": upload_resp.json()["blob"], "alt": item["title"][:200]})
        except Exception:
            pass

    record = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if facets:
        record["facets"] = facets
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


# --- Instagram (über Buffer) — nutzt dieselben gebrandeten Karussell-
# Folien wie die Artikel-Posts, nur mit Kalender-Inhalten -------------------

def post_instagram_calendar(kind_key, headline, subheadline, items, caption):
    api_key = pts.env("BUFFER_API_KEY")
    channel_id = pts.env("BUFFER_INSTAGRAM_CHANNEL_ID")
    if not api_key or not channel_id:
        return False

    if not os.path.exists(OUTRO_SLIDE_PATH):
        print(f"  Instagram: ! Feste Outro-Folie ({OUTRO_SLIDE_PATH}) fehlt im Repo — übersprungen.", file=sys.stderr)
        return False

    try:
        import generate_instagram_slides as gis
    except ImportError as e:
        print(f"  Instagram: ! generate_instagram_slides.py konnte nicht geladen werden: {e}", file=sys.stderr)
        return False

    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S") + f"-{kind_key}"
    badge_color = gis.CYAN if kind_key == "update" else gis.VIOLET

    try:
        slide_paths = gis.generate_calendar_slides(
            items, SLIDE_OUTPUT_DIR, run_id,
            line1=headline, line2=subheadline, line3="SWIPE FÜR ALLE  →",
            title_fn=lambda it: it["title"], badge_fn=lambda it: it["badge"],
            badge_color=badge_color,
        )
    except Exception as e:
        print(f"  Instagram: ! Folien-Generierung fehlgeschlagen: {e}", file=sys.stderr)
        return False

    all_local_paths = slide_paths + [OUTRO_SLIDE_PATH]

    if not pts.git_commit_and_push(slide_paths, f"Kalender-Karussell-Folien ({kind_key}, {run_id})"):
        return False

    image_urls = [pts.raw_github_url(p) for p in all_local_paths]
    assets = [{"image": {"url": url}} for url in image_urls]

    due_at = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    variables = {
        "input": {
            "text": caption,
            "channelId": channel_id,
            "schedulingType": "automatic",
            "mode": "customScheduled",
            "dueAt": due_at,
            "assets": assets,
            "metadata": {"instagram": {"type": "post", "shouldShareToFeed": True}},
        }
    }

    try:
        resp = requests.post(
            "https://api.buffer.com",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"query": pts.BUFFER_CREATE_POST_QUERY, "variables": variables},
            timeout=30,
        )
    except Exception as e:
        print(f"  Instagram (Buffer): ! Unerwarteter Fehler: {e}", file=sys.stderr)
        return False

    if resp.status_code != 200:
        print(f"  Instagram (Buffer): ! Fehler ({resp.status_code}): {resp.text[:500]}", file=sys.stderr)
        return False

    data = resp.json()
    if data.get("errors"):
        print(f"  Instagram (Buffer): ! GraphQL-Fehler: {data['errors']}", file=sys.stderr)
        return False

    result = (data.get("data") or {}).get("createPost") or {}
    if result.get("message"):
        print(f"  Instagram (Buffer): ! {result['message']}", file=sys.stderr)
        return False

    print(f"  Instagram (Buffer): ✓ 1 Post mit {len(assets)} Bild(ern) eingeplant (in ~2 Min.)")
    return True


# --- Tumblr ---------------------------------------------------------------

def post_tumblr_calendar(kind_key, emoji, headline, subheadline, items, page_url):
    consumer_key = pts.env("TUMBLR_CONSUMER_KEY")
    consumer_secret = pts.env("TUMBLR_CONSUMER_SECRET")
    oauth_token = pts.env("TUMBLR_OAUTH_TOKEN")
    oauth_token_secret = pts.env("TUMBLR_OAUTH_TOKEN_SECRET")
    blog_name = pts.env("TUMBLR_BLOG_NAME")
    if not all([consumer_key, consumer_secret, oauth_token, oauth_token_secret, blog_name]):
        return False

    try:
        from requests_oauthlib import OAuth1
    except ImportError:
        print("  Tumblr: ! Bibliothek 'requests-oauthlib' fehlt.", file=sys.stderr)
        return False

    auth = OAuth1(consumer_key, consumer_secret, oauth_token, oauth_token_secret)

    content_blocks = [{"type": "text", "text": f"{emoji} {headline}", "subtype": "heading1"}]
    content_blocks.append({"type": "text", "text": subheadline})
    for item in items:
        content_blocks.append({"type": "text", "text": item["title"]})
        if item.get("image"):
            content_blocks.append({"type": "image", "media": [{"url": item["image"]}]})

    link_line = f"👉 Alles ansehen: {page_url}"
    url_start = link_line.index(page_url)
    url_end = url_start + len(page_url)
    content_blocks.append({
        "type": "text",
        "text": link_line,
        "formatting": [{"start": url_start, "end": url_end, "type": "link", "url": page_url}],
    })

    tags = ",".join(calendar_hashtags(kind_key) + ["loadoutnews"])
    payload = {"content": content_blocks, "tags": tags}

    resp = requests.post(
        f"https://api.tumblr.com/v2/blog/{blog_name}/posts",
        auth=auth,
        json=payload,
        timeout=15,
    )
    ok = resp.status_code in (200, 201)
    print(f"  Tumblr: {'✓ 1 Post mit ' + str(len(items)) + ' Einträgen' if ok else '! Fehler ' + str(resp.status_code) + ' ' + resp.text[:200]}")
    return ok


# --- Reddit (über Zernio) --------------------------------------------------

def post_reddit_calendar(emoji, headline, subheadline, items, page_url):
    api_key = pts.env("ZERNIO_API_KEY")
    account_id = pts.env("ZERNIO_REDDIT_ACCOUNT_ID")
    subreddit_name = pts.env("REDDIT_SUBREDDIT")
    if not api_key or not account_id or not subreddit_name:
        return False

    items_with_images = [it for it in items if it.get("image")]
    if not items_with_images:
        print("  Reddit: ! Keine Einträge mit Bild vorhanden — übersprungen.")
        return False

    title = f"{emoji} {headline}"[:290]
    body_lines = [it["title"] for it in items_with_images]
    body_lines.append(f"\n{subheadline}")
    body_lines.append(f"Alles ansehen: {page_url}")
    content = title + "\n\n" + "\n".join(body_lines)

    media_items = [{"type": "image", "url": it["image"]} for it in items_with_images]

    payload = {
        "content": content,
        "mediaItems": media_items,
        "platforms": [{
            "platform": "reddit",
            "accountId": account_id,
            "platformSpecificData": {"subreddit": subreddit_name},
        }],
        "publishNow": True,
    }

    try:
        resp = requests.post(
            pts.ZERNIO_CREATE_POST_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
    except Exception as e:
        print(f"  Reddit (Zernio): ! Unerwarteter Fehler: {e}", file=sys.stderr)
        return False

    ok = resp.status_code in (200, 201)
    if ok:
        print(f"  Reddit (Zernio): ✓ 1 Post mit {len(media_items)} Bild(ern) in r/{subreddit_name}")
    else:
        print(f"  Reddit (Zernio): ! Fehler ({resp.status_code}): {resp.text[:500]}", file=sys.stderr)
    return ok


# --- Auswahl-Logik ----------------------------------------------------------

def select_top_releases(releases, n=MAX_ITEMS_PER_CALENDAR_POST):
    """Wählt die N interessantesten Releases nach Hype-Wert aus — der Rest
    wird nicht als eigene Folie gezeigt, sondern nur als Anzahl-Hinweis
    ('+X weitere Releases diesen Monat') im Intro erwähnt."""
    sorted_releases = sorted(releases, key=lambda r: r.get("hype", 0), reverse=True)
    return sorted_releases[:n], max(0, len(releases) - n)


def build_release_items(releases):
    return [{
        "title": r.get("title", ""),
        "image": r.get("image"),
        "hype": r.get("hype", 0),
        "badge": r.get("genre") or "Release",
    } for r in releases]


def build_update_items(updates):
    return [{
        "title": f"{u.get('game','')}: {u.get('update_title','')}",
        "image": u.get("image"),
        "hype": u.get("hype", 0),
        "badge": u.get("game") or "Update",
    } for u in updates]


def run_release_post(posted_state):
    data = load_json(RELEASES_FILE, None)
    if not data or not data.get("releases"):
        print("→ Release-Kalender: keine Daten vorhanden — übersprungen.")
        return False

    month_label = data.get("month", "")
    if posted_state.get("posted_release_month") == month_label:
        print(f"→ Release-Kalender: Monat '{month_label}' wurde bereits gepostet — übersprungen.")
        return False

    all_releases = data["releases"]
    top, remaining = select_top_releases(all_releases)
    if not top:
        return False
    items = build_release_items(top)

    headline = f"TOP-RELEASES {month_label.upper()}"
    subheadline = f"+{remaining} weitere Releases diesen Monat" if remaining > 0 else "Alle Releases diesen Monat"
    page_url = f"{SITE_URL}/releases.html"

    print(f"→ Poste Release-Kalender-Update: {len(top)} Top-Releases ausgewählt, {remaining} weitere ({month_label})")

    caption_lines = [f"📅 {headline}\n"]
    for it in items:
        caption_lines.append(f"• {it['title']}")
    caption_lines.append(f"\n{subheadline}")
    caption_lines.append(f"\n👉 Alle Releases über den Link in unserer Bio: {page_url}\n")
    caption_lines.append(" ".join(f"#{t}" for t in calendar_hashtags("release")))
    caption = "\n".join(caption_lines)
    if len(caption) > 2200:
        caption = caption[:2197] + "..."

    post_discord_calendar("Release-Kalender", "📅", headline, subheadline, items, page_url)
    post_bluesky_calendar("📅", headline, subheadline, items, page_url)
    post_instagram_calendar("release", headline, subheadline, items, caption)
    post_tumblr_calendar("release", "📅", headline, subheadline, items, page_url)
    post_reddit_calendar("📅", headline, subheadline, items, page_url)

    posted_state["posted_release_month"] = month_label
    return True


def run_update_post(posted_state):
    all_updates = load_json(UPDATES_FILE, [])
    if not all_updates:
        print("→ Update-Kalender: keine Daten vorhanden — übersprungen.")
        return False

    already_posted_ids = set(posted_state.get("posted_update_ids", []))
    new_updates = [u for u in all_updates if u.get("id") and u["id"] not in already_posted_ids]

    if not new_updates:
        print("→ Update-Kalender: keine wirklich neuen Updates seit dem letzten Post — übersprungen.")
        return False

    new_updates_sorted = sorted(new_updates, key=lambda u: u.get("hype", 0), reverse=True)
    shown = new_updates_sorted[:MAX_ITEMS_PER_CALENDAR_POST]
    remaining = max(0, len(new_updates_sorted) - len(shown))
    items = build_update_items(shown)

    headline = f"{len(new_updates_sorted)} NEUE UPDATES" if len(new_updates_sorted) != 1 else "1 NEUES UPDATE"
    top_item_title = items[0]["title"] if items else ""
    subheadline = f"u. a. {top_item_title}" + (f" (+{remaining} weitere)" if remaining > 0 else "")
    page_url = f"{SITE_URL}/updates.html"

    print(f"→ Poste Update-Kalender-Update: {len(new_updates_sorted)} wirklich neue(s) Update(s) gefunden")

    caption_lines = [f"🛠️ {headline}\n"]
    for it in items:
        caption_lines.append(f"• {it['title']}")
    caption_lines.append(f"\n👉 Alle Updates über den Link in unserer Bio: {page_url}\n")
    caption_lines.append(" ".join(f"#{t}" for t in calendar_hashtags("update")))
    caption = "\n".join(caption_lines)
    if len(caption) > 2200:
        caption = caption[:2197] + "..."

    post_discord_calendar("Update-Kalender", "🛠️", headline, subheadline, items, page_url)
    post_bluesky_calendar("🛠️", headline, subheadline, items, page_url)
    post_instagram_calendar("update", headline, subheadline, items, caption)
    post_tumblr_calendar("update", "🛠️", headline, subheadline, items, page_url)
    post_reddit_calendar("🛠️", headline, subheadline, items, page_url)

    # ALLE neuen IDs merken (auch jene, die wegen MAX_ITEMS_PER_CALENDAR_POST
    # nicht in den Folien gezeigt wurden) — sonst würden sie beim nächsten
    # Lauf fälschlich nochmal als "neu" gelten und erneut gepostet werden.
    posted_state.setdefault("posted_update_ids", [])
    posted_state["posted_update_ids"] = list(
        set(posted_state["posted_update_ids"]) | {u["id"] for u in new_updates if u.get("id")}
    )
    return True


def main():
    posted_state = load_json(POSTED_FILE, {"posted_release_month": None, "posted_update_ids": []})

    release_posted = run_release_post(posted_state)
    update_posted = run_update_post(posted_state)

    if release_posted or update_posted:
        save_json(POSTED_FILE, posted_state)

        if release_posted and update_posted:
            push_body = "Neuer Release-Kalender und neue Updates sind online!"
        elif release_posted:
            push_body = "Der Release-Kalender wurde aktualisiert!"
        else:
            push_body = "Neue Updates wurden angekündigt!"
        send_push_notification(
            title="📅 LOADOUT-NEWS Kalender-Update",
            body=push_body,
            url="/updates.html" if update_posted and not release_posted else "/releases.html",
        )
        print("✓ Kalender-Status aktualisiert.")
    else:
        print("✓ Nichts Neues zu posten.")


if __name__ == "__main__":
    main()
