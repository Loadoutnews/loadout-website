"""
LOADOUT-NEWS — Automatisches Social-Media-Posting
=====================================================
Wird ausgelöst, sobald articles.json auf dem main-Branch aktualisiert wird
(also sobald ein News-Update-Pull-Request gemergt wurde). Postet NEUE
Artikel als EINEN gesammelten Post pro Lauf — nicht einen Post pro Artikel:

  - Discord: EIN Post mit mehreren Embeds (bis zu 10 möglich, wir haben
    i. d. R. max. 4 neue Artikel pro Lauf) — erscheint als mehrere
    Artikel-Vorschauen untereinander in derselben Nachricht.
  - Bluesky: EIN Post mit kurzer Sammel-Überschrift + bis zu 4
    Vorschaubildern (Bluesky erlaubt maximal 300 Zeichen und 4 Bilder).
    Link und Hashtags sind echte klickbare "Facets", nicht nur Text, und
    bekommen IMMER garantiert Platz — nur die Überschrift wird bei Bedarf
    gekürzt, nie der Link.
  - Instagram: EIN Karussell-Post, über den Drittanbieter Buffer
    (buffer.com) statt direkt über Metas Graph API — Metas eigene
    Entwicklerkonto-Verifizierung war bei uns dauerhaft blockiert, Buffer
    hat dafür bereits eine eigene, freigeschaltete Meta-App. Buffers API
    ist eine GraphQL-Schnittstelle.
  - Tumblr: EIN Post im "Neuen Post Format" mit Text- und Bild-Blöcken
    pro Artikel, mit echtem klickbarem Link. Hashtags landen zusätzlich
    im separaten Tags-Feld (Tumblrs wichtigster Hebel fürs eigene
    Empfehlungssystem).
  - Reddit: EIN Galerie-Post im EIGENEN Subreddit, über den Drittanbieter
    Zernio (zernio.com) — Reddits eigene Entwickler-App-Registrierung war
    bei uns dauerhaft blockiert (siehe frühere Versuche). Zernio hat
    Reddit direkt eingebunden, keine eigene App-Registrierung nötig.
    Titel nennt den gehyptesten Artikel konkret statt nur eine Zahl.

Merkt sich in social-posted.json, was schon gepostet wurde, damit nichts
doppelt gepostet wird.

Setup (als GitHub Secrets hinterlegen):
    DISCORD_WEBHOOK_URL
    BLUESKY_HANDLE
    BLUESKY_APP_PASSWORD
    BUFFER_API_KEY
    BUFFER_INSTAGRAM_CHANNEL_ID
    TUMBLR_CONSUMER_KEY
    TUMBLR_CONSUMER_SECRET
    TUMBLR_OAUTH_TOKEN
    TUMBLR_OAUTH_TOKEN_SECRET
    TUMBLR_BLOG_NAME
    ZERNIO_API_KEY
    ZERNIO_REDDIT_ACCOUNT_ID
    REDDIT_SUBREDDIT
    PUSH_SECRET

Ausführen:
    python post_to_social.py
"""

import datetime
import json
import os
import subprocess
import sys

import requests

from push_helper import send_push_notification

SITE_URL = "https://loadout-news.com"
ARTICLES_FILE = "articles.json"
POSTED_FILE = "social-posted.json"

CATS = {"pc": "PC", "konsole": "Konsolen", "hardware": "Hardware", "industrie": "Industrie"}

MAX_BLUESKY_IMAGES = 4       # technisches Limit von Bluesky
MAX_INSTAGRAM_CAROUSEL = 10  # technisches Limit von Instagram (wir haben eh nie mehr als 4)


def env(name):
    """Liest eine Umgebungsvariable und entfernt automatisch versehentlich
    mitkopierte Leerzeichen/Zeilenumbrüche — häufigste Fehlerursache bei
    manuell eingefügten API-Tokens ("Cannot parse access token")."""
    value = os.environ.get(name)
    return value.strip() if value else value


# --- Hashtags für maximale organische Reichweite -----------------------------
# Mischung aus allgemeinen Gaming-Hashtags (werden viel gesucht, aber auch
# stark umkämpft) und spezifischen Spiel-/Kategorie-Hashtags (weniger
# Konkurrenz, aber gezielteres Publikum) — genau diese Mischung empfehlen
# die Algorithmen der jeweiligen Plattformen für organische Reichweite.
GENERAL_HASHTAGS = ["gaming", "gamingnews", "videogames", "gamer"]

CAT_HASHTAGS = {
    "pc": ["pcgaming", "pcgamer"],
    "konsole": ["consolegaming", "playstation", "xbox"],
    "hardware": ["gaminghardware", "pcbuild"],
    "industrie": ["gamingindustry"],
}

GAME_HASHTAGS = {
    "gta": ["GTA6", "GTA", "RockstarGames"],
    "minecraft": ["Minecraft", "MinecraftNews"],
    "fortnite": ["Fortnite", "FortniteNews"],
    "cod": ["CallOfDuty", "Warzone"],
    "valorant": ["Valorant", "LeagueOfLegends", "Esports"],
    "fifa": ["EASportsFC", "FIFA"],
}


def generate_hashtags(articles, max_tags=12):
    """Baut eine Hashtag-Liste aus den Themen der aktuellen Artikel-Auswahl —
    spezifische Spiel-/Kategorie-Tags zuerst (gezieltes Publikum, weniger
    Konkurrenz), allgemeine Gaming-Tags als Auffüller (große Reichweite)."""
    tags = []

    def add(t):
        if t.lower() not in [x.lower() for x in tags]:
            tags.append(t)

    for a in articles:
        for t in GAME_HASHTAGS.get(a.get("game"), []):
            add(t)
    for a in articles:
        for t in CAT_HASHTAGS.get(a.get("cat"), []):
            add(t)
    for t in GENERAL_HASHTAGS:
        add(t)

    return tags[:max_tags]


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
    webhook_url = env("DISCORD_WEBHOOK_URL")
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
# Ein einziger Post mit kurzer Sammel-Überschrift und bis zu 4
# Vorschaubildern. Link + Hashtags bekommen IMMER garantiert Platz — nur
# die Überschrift wird bei Bedarf gekürzt, nie der Link.

def post_bluesky_batch(articles):
    handle = env("BLUESKY_HANDLE")
    app_password = env("BLUESKY_APP_PASSWORD")
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

    MAX_BLUESKY_CHARS = 300

    # Nur 3 Hashtags bei Bluesky — der Post ist auf 300 Zeichen begrenzt.
    hashtags = generate_hashtags(articles, max_tags=3)
    hashtag_line = " ".join(f"#{t}" for t in hashtags)

    # Fußzeile (Link + Hashtags) wird ZUERST festgelegt und bekommt garantiert
    # Platz reserviert — die darf niemals wegfallen oder abgeschnitten werden.
    footer = f"👉 {SITE_URL}"
    if hashtag_line:
        footer += f"\n{hashtag_line}"

    # Nur eine grobe Sammel-Überschrift statt einer Liste aller Artikel-Titel
    # — verhindert, dass der Post bei vielen/langen Titeln unkontrolliert
    # mitten im Text (oder sogar vor dem Link) abgeschnitten wird.
    top_article = max(articles, key=lambda a: a.get("hype", 0))
    if len(articles) == 1:
        headline = f"🎮 {top_article['title']}"
    else:
        headline = f"🎮 {len(articles)} neue Artikel bei LOADOUT-NEWS — u. a. {top_article['title']}"

    # Verbleibender Platz fürs Headline = Gesamtlimit minus Fußzeile minus
    # Zeilenumbruch dazwischen. Passt das Headline nicht komplett rein,
    # wird NUR das Headline gekürzt (mit "…") — Link und Hashtags bleiben
    # davon immer unangetastet.
    budget = MAX_BLUESKY_CHARS - len(footer) - 1
    if len(headline) > budget:
        headline = headline[:max(budget - 1, 0)].rstrip() + "…"

    text = f"{headline}\n{footer}"

    # Bluesky macht aus reinem Text-URLs und #Hashtags NICHT automatisch
    # klickbare Links/Tags — dafür braucht es "Facets", die genau angeben,
    # welcher Byte-Bereich im Text ein Link bzw. ein Hashtag ist (Bluesky
    # zählt in UTF-8-Bytes, nicht in Zeichen, wegen Emojis wie 🎮 im Text).
    facets = []
    if SITE_URL in text:
        url_char_start = text.rindex(SITE_URL)
        byte_start = len(text[:url_char_start].encode("utf-8"))
        byte_end = byte_start + len(SITE_URL.encode("utf-8"))
        facets.append({
            "index": {"byteStart": byte_start, "byteEnd": byte_end},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": SITE_URL}],
        })
    for t in hashtags:
        tag_str = f"#{t}"
        if tag_str not in text:
            continue
        char_start = text.rindex(tag_str)
        byte_start = len(text[:char_start].encode("utf-8"))
        byte_end = byte_start + len(tag_str.encode("utf-8"))
        facets.append({
            "index": {"byteStart": byte_start, "byteEnd": byte_end},
            "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": t}],
        })

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


# --- Instagram (über Buffer) --------------------------------------------------
# Metas eigene Graph API scheiterte bei uns dauerhaft an einer blockierten
# Entwicklerkonto-Verifizierung (bekanntes, weitverbreitetes Meta-Problem,
# kein Fehler in unserem Code). Buffer (buffer.com) hat dafür bereits eine
# eigene, freigeschaltete Meta-App: Wir verbinden unser Instagram-Konto
# einmalig über Buffers eigene Weboberfläche, und posten danach über
# Buffers GraphQL-API.
#
# Die Karussell-Folien sind NICHT mehr die rohen Artikel-Bilder, sondern
# eigens gebrandete Bilder (siehe generate_instagram_slides.py): eine feste
# Intro-Folie mit Logo, eine Folie pro Artikel mit Titel-Überlagerung im
# LOADOUT-Stil, und eine IMMER identische Werbe-Folie am Ende.

SLIDE_OUTPUT_DIR = "social-slides"
OUTRO_SLIDE_PATH = "social-assets/outro-slide.jpg"


def git_commit_and_push(paths, commit_message):
    """Committet die übergebenen Dateien und pusht sie — nötig, damit die
    frisch erzeugten Karussell-Folien über eine echte, öffentliche
    raw.githubusercontent.com-URL abrufbar sind, BEVOR wir Buffer bitten,
    sie zu laden. Nutzt dieselben Git-Zugriffsrechte, die der Workflow
    ohnehin schon hat (siehe Push von social-posted.json am Skript-Ende)."""
    try:
        subprocess.run(["git", "config", "user.name", "github-actions"], check=True)
        subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
        subprocess.run(["git", "add"] + paths, check=True)
        commit_result = subprocess.run(["git", "commit", "-m", commit_message], capture_output=True, text=True)
        if commit_result.returncode != 0 and "nothing to commit" not in commit_result.stdout:
            print(f"  Instagram: ! Git-Commit fehlgeschlagen: {commit_result.stdout}{commit_result.stderr}", file=sys.stderr)
            return False
        subprocess.run(["git", "push"], check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"  Instagram: ! Git-Push fehlgeschlagen: {e}", file=sys.stderr)
        return False


def raw_github_url(path):
    """Baut die öffentliche 'Rohdaten'-URL einer Datei im Repo — GITHUB_REPOSITORY
    wird von GitHub Actions automatisch gesetzt (Format 'Besitzer/Repo-Name')."""
    repo = os.environ.get("GITHUB_REPOSITORY", "Loadoutnews/loadout-website")
    return f"https://raw.githubusercontent.com/{repo}/main/{path}"


BUFFER_CREATE_POST_QUERY = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess {
      post {
        id
        text
      }
    }
    ... on MutationError {
      message
    }
  }
}
"""


def post_instagram_carousel(articles):
    api_key = env("BUFFER_API_KEY")
    channel_id = env("BUFFER_INSTAGRAM_CHANNEL_ID")
    if not api_key or not channel_id:
        return False

    # 2 Plätze im Karussell sind für Intro- und Outro-Folie reserviert
    articles_with_images = [a for a in articles if a.get("image")][:MAX_INSTAGRAM_CAROUSEL - 2]
    if not articles_with_images:
        print("  Instagram: ! Keine Artikel mit Bild vorhanden — übersprungen.")
        return False

    if not os.path.exists(OUTRO_SLIDE_PATH):
        print(f"  Instagram: ! Feste Outro-Folie ({OUTRO_SLIDE_PATH}) fehlt im Repo — übersprungen.", file=sys.stderr)
        return False

    try:
        import generate_instagram_slides as gis
    except ImportError as e:
        print(f"  Instagram: ! generate_instagram_slides.py konnte nicht geladen werden: {e}", file=sys.stderr)
        return False

    # Eindeutige Kennung pro Lauf — verhindert, dass GitHubs Rohdaten-Cache
    # (raw.githubusercontent.com) Buffer versehentlich noch Bilder vom
    # VORHERIGEN Lauf ausliefert, falls Dateinamen sich wiederholen würden.
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")

    try:
        slide_paths = gis.generate_all_slides(articles_with_images, SLIDE_OUTPUT_DIR, run_id)
    except Exception as e:
        print(f"  Instagram: ! Folien-Generierung fehlgeschlagen: {e}", file=sys.stderr)
        return False

    all_local_paths = slide_paths + [OUTRO_SLIDE_PATH]

    if not git_commit_and_push(slide_paths, f"Instagram-Karussell-Folien ({len(articles_with_images)} Artikel, {run_id})"):
        return False

    image_urls = [raw_github_url(p) for p in all_local_paths]

    hashtags = generate_hashtags(articles_with_images, max_tags=15)
    hashtag_block = " ".join(f"#{t}" for t in hashtags)
    caption_lines = [f"🎮 {len(articles_with_images)} neue Artikel bei LOADOUT-NEWS!\n"]
    for a in articles_with_images:
        caption_lines.append(f"• {a['title']}")
    caption_lines.append(f"\n👉 Alle Artikel über den Link in unserer Bio: {SITE_URL}\n\n{hashtag_block}")
    caption = "\n".join(caption_lines)
    if len(caption) > 2200:  # dokumentiertes Instagram-Limit für Bildunterschriften
        caption = caption[:2197] + "..."

    # Buffer nimmt mehrere Bilder als "assets"-Liste entgegen — bei
    # Instagram wird daraus automatisch ein Karussell (mehrere Bilder).
    # Reihenfolge: Intro-Folie, dann eine Folie pro Artikel, dann die feste
    # Outro-Werbefolie ganz am Ende.
    assets = [{"image": {"url": url}} for url in image_urls]

    # "customScheduled" mit einer Zielzeit von 2 Minuten in der Zukunft
    # statt "addToQueue" — Letzteres würde sich nach Buffers eigenem,
    # bei uns nicht kontrolliertem Warteschlangen-Zeitplan richten
    # (könnte Stunden dauern). So posten wir zuverlässig zeitnah, ohne
    # von Buffers Konto-Einstellungen abhängig zu sein.
    due_at = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    variables = {
        "input": {
            "text": caption,
            "channelId": channel_id,
            "schedulingType": "automatic",
            "mode": "customScheduled",
            "dueAt": due_at,
            "assets": assets,
            # Buffer verlangt für Instagram zusätzlich explizit, ob der Post
            # im normalen Feed erscheinen soll — ohne dieses Feld schlägt
            # der Aufruf mit "Field shouldShareToFeed... was not provided"
            # fehl. Wir wollen immer im Feed erscheinen (kein reiner
            # Story-only-Post).
            "metadata": {
                "instagram": {
                    "type": "post",
                    "shouldShareToFeed": True,
                },
            },
        }
    }

    try:
        resp = requests.post(
            "https://api.buffer.com",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"query": BUFFER_CREATE_POST_QUERY, "variables": variables},
            timeout=30,
        )
    except Exception as e:
        print(f"  Instagram (Buffer): ! Unerwarteter Fehler: {e}", file=sys.stderr)
        return False

    if resp.status_code != 200:
        print(f"  Instagram (Buffer): ! Fehler ({resp.status_code}): {resp.text[:500]}", file=sys.stderr)
        return False

    data = resp.json()

    # Klassische GraphQL-Fehler (z. B. falscher API-Schlüssel, falsche Syntax)
    if data.get("errors"):
        print(f"  Instagram (Buffer): ! GraphQL-Fehler: {data['errors']}", file=sys.stderr)
        return False

    result = (data.get("data") or {}).get("createPost") or {}
    # Buffers eigene "MutationError"-Antwortform (z. B. ungültige Kanal-ID)
    if result.get("message"):
        print(f"  Instagram (Buffer): ! {result['message']}", file=sys.stderr)
        return False

    print(f"  Instagram (Buffer): ✓ 1 Post mit {len(assets)} Bild(ern) eingeplant (in ~2 Min.)")
    return True


# --- Tumblr -------------------------------------------------------------------
# Ein einziger Post im "Neuen Post Format" (NPF) von Tumblr, der pro Artikel
# einen Text- und einen Bild-Block enthält — erscheint als durchlaufender
# Beitrag mit mehreren Bildern, ähnlich einem Karussell.

def post_tumblr_batch(articles):
    consumer_key = env("TUMBLR_CONSUMER_KEY")
    consumer_secret = env("TUMBLR_CONSUMER_SECRET")
    oauth_token = env("TUMBLR_OAUTH_TOKEN")
    oauth_token_secret = env("TUMBLR_OAUTH_TOKEN_SECRET")
    blog_name = env("TUMBLR_BLOG_NAME")  # z. B. "loadout-news.tumblr.com"
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

    # Tumblrs "Neues Post Format" verlangt eine explizite Formatierungs-
    # Angabe, um aus reinem Text einen echten klickbaren Link zu machen —
    # sonst bleibt die URL einfach unverlinkter Text.
    link_line = f"👉 Alle Artikel: {SITE_URL}"
    url_start = link_line.index(SITE_URL)
    url_end = url_start + len(SITE_URL)
    content_blocks.append({
        "type": "text",
        "text": link_line,
        "formatting": [{"start": url_start, "end": url_end, "type": "link", "url": SITE_URL}],
    })

    # Bei Tumblr zählt fürs hauseigene Empfehlungs-/Suchsystem VOR ALLEM
    # das separate "tags"-Feld — nicht (nur) Hashtags im Fließtext. Bis zu
    # 30 Tags sind erlaubt; wir nutzen eine themenspezifische Mischung plus
    # den Marken-Tag.
    hashtags = generate_hashtags(articles, max_tags=20)
    tags = ",".join(hashtags + ["loadoutnews"])
    payload = {"content": content_blocks, "tags": tags}

    resp = requests.post(
        f"https://api.tumblr.com/v2/blog/{blog_name}/posts",
        auth=auth,
        json=payload,
        timeout=15,
    )
    ok = resp.status_code in (200, 201)
    print(f"  Tumblr: {'✓ 1 Post mit ' + str(len(articles)) + ' Artikeln' if ok else '! Fehler ' + str(resp.status_code) + ' ' + resp.text[:200]}")
    return ok


# --- Reddit (über Zernio) -------------------------------------------------------
# Reddits eigene Entwickler-App-Registrierung blockierte bei uns dauerhaft
# ("you must also register to use the API"-Fehler, nie erfolgreich
# abgeschlossen). Zernio (zernio.com) hat Reddit bereits direkt
# eingebunden — keine eigene App-Registrierung bei Reddit nötig, einfach
# das Konto über Zernios eigene Oberfläche verbinden und über deren
# API posten.
#
# Ein einziger Galerie-Post im EIGENEN Subreddit (nicht in fremden
# Gaming-Subreddits — dort würde automatisiertes Posten schnell als Spam
# gewertet und riskiert eine Kontosperrung).
#
# Ehrlicher Hinweis: Laut Zernios eigener Dokumentation hat Reddit dort
# plattformweit eine auffällig hohe Fehlerquote (Reddits eigene, strenge
# Anti-Spam-Regeln pro Subreddit) — das liegt an Reddit selbst, nicht an
# unserem Code. Ein gelegentlicher Fehlschlag ist also nicht unbedingt
# ein Zeichen für ein Konfigurationsproblem.

ZERNIO_CREATE_POST_URL = "https://zernio.com/api/v1/posts"


def post_reddit_batch(articles):
    api_key = env("ZERNIO_API_KEY")
    account_id = env("ZERNIO_REDDIT_ACCOUNT_ID")
    subreddit_name = env("REDDIT_SUBREDDIT")  # z. B. "LoadoutNews", ohne "r/"
    if not api_key or not account_id or not subreddit_name:
        return False

    articles_with_images = [a for a in articles if a.get("image")]
    if not articles_with_images:
        print("  Reddit: ! Keine Artikel mit Bild vorhanden — übersprungen.")
        return False

    # Ein konkreter, neugierig machender Titel performt auf Reddit
    # erfahrungsgemäß deutlich besser als eine reine Zahlenangabe — daher
    # wird der gehypteste Artikel der Auswahl im Titel genannt. Bei Zernio
    # wird die ERSTE ZEILE des "content"-Felds automatisch zum Reddit-Titel,
    # der Rest zum Beitragstext.
    top_article = max(articles_with_images, key=lambda a: a.get("hype", 0))
    if len(articles_with_images) == 1:
        title = f"🎮 {top_article['title']}"
    else:
        title = f"🎮 {top_article['title']} (+{len(articles_with_images) - 1} weitere News)"
    title = title[:290]  # Reddit-Titel-Limit liegt bei 300 Zeichen, etwas Puffer lassen

    body_lines = [a["title"] for a in articles_with_images]
    body_lines.append(f"\nAlle Artikel: {SITE_URL}")
    content = title + "\n\n" + "\n".join(body_lines)

    media_items = [{"type": "image", "url": a["image"]} for a in articles_with_images]

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
            ZERNIO_CREATE_POST_URL,
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
