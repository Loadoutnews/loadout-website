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
    articles.json  -> wird von der Website (loadout-demo.html) geladen
"""

import json
import hashlib
import datetime
import os
import sys

import feedparser
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
            parsed = feedparser.parse(feed_url)
            source_name = parsed.feed.get("title", feed_url)
            for entry in parsed.entries[:6]:  # die letzten 6 pro Feed reichen
                entries.append({
                    "title": entry.get("title", "").strip(),
                    "summary": strip_html(entry.get("summary", "")),
                    "link": entry.get("link", ""),
                    "source": source_name,
                })
        except Exception as e:
            print(f"  ! Feed konnte nicht geladen werden ({feed_url}): {e}", file=sys.stderr)
    return entries


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
