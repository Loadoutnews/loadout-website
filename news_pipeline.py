
"""
LOADOUT News-Pipeline
======================
Ruft Gaming-News aus mehreren RSS-Feeds ab und lässt Claude daraus
eigenständige, deutsche Artikel im Format der LOADOUT-Website schreiben.
 
Setup:
    pip install feedparser anthropic
 
    export ANTHROPIC_API_KEY="dein-api-key"   # macOS/Linux
    setx ANTHROPIC_API_KEY "dein-api-key"      # Windows
 
Ausführen:
    python news_pipeline.py
 
Ergebnis:
    articles.json  -> wird von der Website (index.html) geladen
"""
 
import json
import hashlib
import datetime
import os
import re
import sys
 
import feedparser
import requests
from anthropic import Anthropic
 
# ---------------------------------------------------------------------------
# 1. KONFIGURATION
# ---------------------------------------------------------------------------
 
FEEDS = [
    "https://www.ign.com/rss/articles/feed?tags=games",
    "https://www.pcgamer.com/rss/",
    "https://www.eurogamer.net/feed",
    "https://www.nintendolife.com/feeds/latest",
    "https://kotaku.com/rss",
    # Optionale Feeds speziell für die großen Franchise-Hubs (GTA, Minecraft, ...) —
    # URL vor dem produktiven Einsatz prüfen, RSS-Adressen ändern sich gelegentlich.
    # "https://www.gtaboom.com/feed/",
    # "https://www.minecraft.net/en-us/feeds/community-content-rss",
]
 
MAX_ARTICLES_PER_RUN = 8          # wie viele neue Artikel pro Durchlauf geschrieben werden
MAX_ARTICLES_TOTAL = 30           # wie viele insgesamt in articles.json bleiben (älteste fliegen raus)
OUTPUT_FILE = "articles.json"
MODEL = "claude-sonnet-5"
 
client = Anthropic()  # liest ANTHROPIC_API_KEY automatisch aus der Umgebung
 
 
# ---------------------------------------------------------------------------
# 2. NEWS SAMMELN
# ---------------------------------------------------------------------------
 
def fetch_raw_entries():
    """Holt die neuesten Einträge aus allen konfigurierten Feeds."""
    entries = []
    for feed_url in FEEDS:
        try:
            parsed = feedparser.parse(
                feed_url,
                agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            source_name = parsed.feed.get("title", feed_url)
            for entry in parsed.entries[:6]:  # die letzten 6 pro Feed reichen
                entries.append({
                    "title": entry.get("title", "").strip(),
                    "summary": strip_html(entry.get("summary", "")),
                    "link": entry.get("link", ""),
                    "source": source_name,
                    "image": extract_feed_image(entry),
                })
        except Exception as e:
            print(f"  ! Feed konnte nicht geladen werden ({feed_url}): {e}", file=sys.stderr)
    return entries
 
 
def extract_feed_image(entry):
    """Versucht, das im RSS-Eintrag mitgelieferte Bild der Original-Meldung
    zu finden (media:thumbnail, media:content oder ein Bild-Enclosure).
    Das ist genau das Bild, das der Original-Artikel selbst zeigt — also
    inhaltlich wirklich passend, nicht nur thematisch ähnlich."""
    thumb = entry.get("media_thumbnail")
    if thumb:
        return thumb[0].get("url")
 
    content = entry.get("media_content")
    if content:
        for item in content:
            if item.get("medium") == "image" or "image" in item.get("type", ""):
                return item.get("url")
 
    for enc in entry.get("links", []):
        if enc.get("rel") == "enclosure" and enc.get("type", "").startswith("image"):
            return enc.get("href")
 
    return None
 
 
def fetch_og_image(url, timeout=8):
    """Fallback, falls der Feed selbst kein Bild mitliefert: ruft die
    Original-Seite ab und liest das og:image (bzw. twitter:image) Meta-Tag
    aus — dasselbe Bild, das auch bei Facebook/Twitter-Vorschauen erscheint.
    Löst dabei auch relative Bild-Pfade zu vollständigen URLs auf."""
    from urllib.parse import urljoin
 
    patterns = [
        r'<meta[^>]+property=["\']og:image:secure_url["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+name=["\']twitter:image:src["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
    ]
 
    # Ein Browser-typischer User-Agent statt eines erkennbaren Bot-Namens —
    # viele große Gaming-Seiten (IGN, PC Gamer etc.) blockieren Anfragen,
    # die sich klar als automatisierter Scraper zu erkennen geben.
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    }
 
    try:
        resp = requests.get(url, timeout=timeout, headers=headers)
        if resp.status_code != 200:
            print(f"  ! og:image-Abruf fehlgeschlagen (Status {resp.status_code}) für {url}", file=sys.stderr)
            return None
 
        for pattern in patterns:
            match = re.search(pattern, resp.text, re.I)
            if match:
                image_url = match.group(1)
                # Manche Seiten liefern relative Pfade (z. B. "/img/cover.jpg")
                # statt vollständiger URLs — hier zur echten, ladbaren URL auflösen.
                return urljoin(url, image_url)
 
        print(f"  ! Kein og:image-Tag gefunden auf {url}", file=sys.stderr)
    except Exception as e:
        print(f"  ! Konnte kein og:image laden von {url}: {e}", file=sys.stderr)
    return None
 
 
def strip_html(text):
    """Sehr einfache HTML-Bereinigung für RSS-Summaries."""
    import re
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()
 
 
def article_id(link):
    """Stabile, kurze ID aus dem Original-Link ableiten (verhindert Duplikate)."""
    return hashlib.sha1(link.encode("utf-8")).hexdigest()[:10]
 
 
# ---------------------------------------------------------------------------
# 3. ARTIKEL MIT CLAUDE SCHREIBEN
# ---------------------------------------------------------------------------
 
WRITER_SYSTEM_PROMPT = """Du bist Redakteur:in bei LOADOUT, einer deutschsprachigen Gaming- \
und Tech-News-Seite. Du bekommst Titel, Kurzbeschreibung und Quelle einer \
englischsprachigen News-Meldung und schreibst daraus einen eigenständigen, \
spannend geschriebenen deutschen Artikel.
 
Regeln:
- Schreibe komplett in eigenen Worten. Übersetze NICHT wörtlich, formuliere neu.
- Keine wörtlichen Zitate aus der Quelle übernehmen.
- Ton: informativ, aber lebendig und für Gaming-Fans geschrieben, nicht trocken.
- Ordne die Meldung ein (Warum ist das relevant? Was bedeutet es für Spieler:innen?).
- Antworte AUSSCHLIESSLICH mit einem validen JSON-Objekt, keine Erklärungen, \
kein Markdown, keine Code-Fences.
 
JSON-Format:
{
  "cat": "pc" | "konsole" | "hardware" | "industrie",
  "game": "gta" | "minecraft" | "fortnite" | "cod" | "valorant" | "fifa" | null,
  "title": "Deutscher, knackiger Titel (max. 90 Zeichen)",
  "teaser": "1-2 Sätze Anreißer (max. 200 Zeichen)",
  "body": ["Absatz 1", "Absatz 2", "Absatz 3"],
  "hype": <Zahl 0-100, wie aufregend/relevant die News für Gaming-Fans ist>
}
 
Setze "game" nur, wenn die Meldung eindeutig zu einem dieser sechs großen \
Franchises gehört (GTA, Minecraft, Fortnite, Call of Duty, Valorant/League of \
Legends, FIFA/EA Sports FC). Bei allen anderen Themen: null.
"""
 
 
def write_article(entry):
    user_prompt = f"""Titel: {entry['title']}
Kurzbeschreibung: {entry['summary'][:600]}
Quelle: {entry['source']}
Original-Link: {entry['link']}"""
 
    response = client.messages.create(
        model=MODEL,
        max_tokens=1200,
        system=WRITER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
 
    # content[0] ist nicht immer der Text-Block — manche Modelle liefern
    # zuerst einen internen "Thinking"-Block. Deshalb gezielt den Block
    # mit type == "text" heraussuchen statt content[0] anzunehmen.
    text_blocks = [block.text for block in response.content if block.type == "text"]
    if not text_blocks:
        print(f"  ! Keine Textantwort erhalten für: {entry['title']}", file=sys.stderr)
        return None
    raw_text = text_blocks[0].strip()
    raw_text = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
 
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        print(f"  ! Konnte Antwort nicht parsen für: {entry['title']}", file=sys.stderr)
        return None
 
    return {
        "id": article_id(entry["link"]),
        "cat": data.get("cat", "industrie"),
        "game": data.get("game"),
        "title": data.get("title", entry["title"]),
        "teaser": data.get("teaser", ""),
        "body": data.get("body", []),
        "date": datetime.date.today().strftime("%d. %B %Y"),
        "platform": entry["source"],
        "hype": int(data.get("hype", 50)),
        "source": entry["link"],
        "sourceLabel": entry["source"],
        "image": entry.get("image"),
    }
 
 
# ---------------------------------------------------------------------------
# 4. HAUPTABLAUF
# ---------------------------------------------------------------------------
 
def load_existing_articles():
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []
 
 
def main():
    print("→ Sammle Feeds …")
    raw_entries = fetch_raw_entries()
    print(f"  {len(raw_entries)} Roheinträge gefunden")
 
    existing = load_existing_articles()
    existing_ids = {a["id"] for a in existing}
 
    new_entries = [e for e in raw_entries if article_id(e["link"]) not in existing_ids]
    new_entries = new_entries[:MAX_ARTICLES_PER_RUN]
    print(f"  {len(new_entries)} davon sind neu und werden geschrieben")
 
    # Für Einträge ohne Bild aus dem Feed: og:image von der Original-Seite holen
    for entry in new_entries:
        if not entry.get("image"):
            entry["image"] = fetch_og_image(entry["link"])
 
    written = []
    for entry in new_entries:
        print(f"  ✎ Schreibe: {entry['title'][:70]}")
        article = write_article(entry)
        if article:
            written.append(article)
 
    all_articles = written + existing
    all_articles = all_articles[:MAX_ARTICLES_TOTAL]
 
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_articles, f, ensure_ascii=False, indent=2)
 
    print(f"✓ {len(written)} neue Artikel geschrieben, {len(all_articles)} insgesamt in {OUTPUT_FILE}")
 
 
if __name__ == "__main__":
    main()
 
