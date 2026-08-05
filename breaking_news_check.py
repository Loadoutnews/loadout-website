"""
LOADOUT-NEWS — Breaking-News-Erkennung
==========================================
Läuft HÄUFIG (empfohlen: stündlich, über eine eigene, separate
GitHub-Action-Ausführung) und prüft NUR, ob eine wirklich zeitkritische
Meldung aufgetaucht ist, die nicht bis zum nächsten regulären Tages-Lauf
(19 Uhr, siehe news_pipeline.py) warten sollte — z. B. eine überraschende
Terminverschiebung, ein grosser Leak, eine PSN-Störung.

Bewusst GETRENNT von news_pipeline.py, aus zwei Gründen:
  1. Deutlich günstiger pro Ausführung: In den allermeisten Stunden
     passiert nichts wirklich Breaking-würdiges — dann läuft NUR die
     günstige Haiku-Vorprüfung, der teure Sonnet-Schreib-Aufruf (mit
     Websuche) wird nur ausgeführt, wenn wirklich etwas gefunden wurde.
  2. Eigene Tages-Obergrenze (MAX_BREAKING_PER_DAY), damit "Breaking News"
     als Kategorie besonders und selten bleibt statt inflationär zu werden.

Nutzt news_pipeline.py als Modul (FEEDS, Duplikat-Prüfung, Bild-
Validierung, article_id) — keine Logik wird dupliziert.

Schreibt gefundene Breaking-News-Artikel in DIESELBEN Dateien wie die
reguläre Pipeline (articles.json, archive.json), markiert mit
content_type="breaking". post_to_social.py erkennt das automatisch und
postet mit einem eigenen, dringlichen Design (siehe
generate_instagram_slides.py: generate_breaking_slides) — der bestehende
"Post to Social Media"-Workflow reagiert ja ohnehin schon auf jede
Änderung an articles.json, es braucht dafür keinen weiteren Workflow.

Setup: dieselben Umgebungsvariablen wie news_pipeline.py (ANTHROPIC_API_KEY).

Ausführen:
    python breaking_news_check.py
"""

import datetime
import json
import os
import sys

import news_pipeline as npl

CLASSIFY_MODEL = npl.DEDUP_MODEL  # dasselbe günstige Haiku-Modell wie bei der Duplikat-/Relevanz-Prüfung
WRITE_MODEL = npl.MODEL

ARTICLES_FILE = "articles.json"
ARCHIVE_FILE = "archive.json"
CHECKED_FILE = "breaking-checked.json"    # Merkliste: welche Feed-Links wurden schon klassifiziert (egal ob Breaking oder nicht)
STATE_FILE = "breaking-state.json"        # Tages-Zähler fürs Limit

MAX_BREAKING_PER_DAY = 2
CHECK_BATCH_SIZE = 40  # wie viele frische Feed-Einträge pro Lauf klassifiziert werden — grosszügig, da diese Prüfung günstig ist

BREAKING_CRITERIA = """Eine Meldung gilt als "Breaking News" — zeitkritisch genug, um SOFORT \
gepostet zu werden, statt bis zum nächsten regulären Tages-Lauf zu warten \
— wenn sie MINDESTENS EINES der folgenden Kriterien erfüllt:

1. Eine überraschende Terminverschiebung (verschoben ODER überraschend \
vorgezogen) eines grossen, bereits erwarteten Spiels
2. Ein bedeutender, neuer Leak zu einem grossen, kommenden Spiel (z. B. \
durchgesickerte Screenshots, Gameplay, ein Release-Termin), der noch \
nicht offiziell bestätigt ist, aber von glaubwürdigen Quellen stammt
3. Eine akute, grossflächige Server-/Plattform-Störung (PSN, Xbox Live, \
Steam, ein sehr populäres Online-Spiel), die viele Spieler betrifft
4. Eine überraschende, bedeutende Unternehmensmeldung (plötzliche \
Studio-Schliessung, überraschende Übernahme, plötzlicher Rücktritt einer \
Schlüsselperson)
5. Eine dringende Sicherheitswarnung (Datenleck, Hack, kompromittierte \
Accounts) bei einer grossen Plattform/einem grossen Spiel
6. Eine offizielle Ankündigung, die eine bereits vorher kursierende, \
grosse Erwartungshaltung abrupt bestätigt oder widerlegt

WICHTIG: Eine normale, planmässige Ankündigung (ein regulärer Patch, ein \
angekündigtes DLC, ein normaler Trailer) ist KEINE Breaking News, auch \
wenn das Spiel/Thema an sich relevant ist — es muss ein echtes \
Überraschungs- bzw. Dringlichkeits-Moment vorliegen."""


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_today_state():
    state = load_json(STATE_FILE, {})
    today = datetime.date.today().isoformat()
    if state.get("date") != today:
        state = {"date": today, "count": 0}
    return state


def classify_breaking(entries):
    """EIN günstiger Haiku-Aufruf: welche der Kandidaten sind wirklich
    Breaking News? Läuft nur auf frischen, noch nie geprüften Einträgen
    (siehe CHECKED_FILE) — das ist der Normalfall bei fast jedem
    stündlichen Lauf, und bewusst so günstig gehalten, dass häufiges
    Ausführen kein Kostenproblem ist."""
    if not entries:
        return []

    candidates_block = "\n".join(f"{i}: {e['title']}" for i, e in enumerate(entries))
    prompt = f"""{BREAKING_CRITERIA}

Kandidaten (nummeriert, 0-basiert):
{candidates_block}

Antworte AUSSCHLIESSLICH mit einem JSON-Array der Nummern, die WIRKLICH \
Breaking News sind (kann auch eine leere Liste sein: []). Keine \
Erklärung, kein Markdown, nur das JSON-Array."""

    try:
        response = npl.client.messages.create(
            model=CLASSIFY_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text_blocks = [b.text for b in response.content if b.type == "text"]
        if not text_blocks:
            return []
        raw = text_blocks[-1].strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        first_bracket = raw.find("[")
        if first_bracket > 0:
            raw = raw[first_bracket:]
        indices = set(json.loads(raw, strict=False))
    except Exception as e:
        print(f"  ⚠ Breaking-Klassifikation fehlgeschlagen: {e}", file=sys.stderr)
        return []

    return [entries[i] for i in indices if isinstance(i, int) and 0 <= i < len(entries)]


BREAKING_WRITER_SYSTEM_PROMPT = """Du bist Redakteur:in bei LOADOUT, einer deutschsprachigen \
Gaming- und Tech-News-Seite. Du schreibst eine BREAKING-NEWS-Eilmeldung \
zu einer gerade eingetroffenen, zeitkritischen Meldung.

Regeln:
- ABSOLUT ENTSCHEIDEND: Der GESAMTE Artikel muss zu 100 % auf Deutsch \
geschrieben sein, auch wenn die Quelle englisch ist. Verwende KEINE \
englischen Sätze oder Satzteile. Eigennamen bleiben im Original.
- Verifiziere die Meldung aktiv mit der Websuche, bevor du schreibst — \
Breaking News lebt von Schnelligkeit, aber eine falsche Eilmeldung \
schadet der Glaubwürdigkeit mehr als ein paar Minuten Verzögerung.
- Kurz und prägnant: Breaking News lebt von Klarheit, nicht von epischer \
Länge. 2-3 knappe Absätze reichen, kein ausschweifender Kontext.
- Nenne klar, was FAKT ist und was noch UNBESTÄTIGT/GERÜCHT ist — bei \
Leaks und noch nicht offiziell bestätigten Meldungen ehrlich als solche \
kennzeichnen, keine Sicherheit vortäuschen, die nicht da ist.
- Antworte AUSSCHLIESSLICH mit einem validen JSON-Objekt, keine \
Erklärungen, kein Markdown, keine Code-Fences.
- WICHTIG für gültiges JSON: Verwende in allen Textfeldern NIEMALS gerade \
doppelte Anführungszeichen. Verwende KEINE rohen Zeilenumbrüche innerhalb \
eines einzelnen Textfelds/Absatzes.

JSON-Format:
{
  "cat": "pc" | "konsole" | "hardware" | "industrie",
  "game": "gta" | "minecraft" | "fortnite" | "cod" | "valorant" | "fifa" | null,
  "genre": "action" | "adventure" | "rpg" | "strategie" | "simulation" | "shooter" | "sport" | "rennspiel" | "horror" | "puzzle" | null,
  "title": "Deutsche, klare Breaking-News-Schlagzeile (max. 90 Zeichen)",
  "teaser": "1-2 Sätze, die den Kern der Eilmeldung auf den Punkt bringen (max. 200 Zeichen)",
  "body": ["Absatz 1 — die Kernfakten", "Absatz 2 — Einordnung/Kontext, ggf. was noch unklar ist"],
  "hype": <Zahl 0-100>
}

Setze "game" nur bei eindeutigem Bezug zu GTA, Minecraft, Fortnite, Call \
of Duty, Valorant/League of Legends oder FIFA/EA Sports FC, sonst null.
"""


def write_breaking_article(entry):
    user_prompt = f"""Titel: {entry['title']}
Kurzbeschreibung: {entry['summary'][:600]}
Quelle: {entry['source']}
Original-Link: {entry['link']}"""

    response = npl.client.messages.create(
        model=WRITE_MODEL,
        max_tokens=2000,  # kürzer als normale Artikel — Breaking News ist bewusst knapp
        system=BREAKING_WRITER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}],  # etwas mehr als normale Artikel, für Verifizierung
    )

    text_blocks = [block.text for block in response.content if block.type == "text"]
    if not text_blocks:
        print(f"  ! Keine Textantwort für Breaking-News: {entry['title']}", file=sys.stderr)
        return None

    raw_text = text_blocks[-1].strip()
    raw_text = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    first_brace = raw_text.find("{")
    if first_brace > 0:
        raw_text = raw_text[first_brace:]

    try:
        data = json.loads(raw_text, strict=False)
    except json.JSONDecodeError as e:
        error_pos = e.pos
        context_start = max(0, error_pos - 150)
        context_end = min(len(raw_text), error_pos + 150)
        print(f"  ! Konnte Breaking-News nicht parsen: {entry['title']} — {e.msg} (Position {error_pos})", file=sys.stderr)
        print(f"    Kontext: ...{raw_text[context_start:error_pos]}▶▶▶HIER◀◀◀{raw_text[error_pos:context_end]}...", file=sys.stderr)
        return None

    VALID_CATS = {"pc", "konsole", "hardware", "industrie"}
    VALID_GAMES = {"gta", "minecraft", "fortnite", "cod", "valorant", "fifa"}
    VALID_GENRES = {"action", "adventure", "rpg", "strategie", "simulation",
                     "shooter", "sport", "rennspiel", "horror", "puzzle"}

    cat = data.get("cat")
    if cat not in VALID_CATS:
        cat = "industrie"
    game = data.get("game")
    if game is not None and game not in VALID_GAMES:
        game = None
    genre = data.get("genre")
    if genre is not None and genre not in VALID_GENRES:
        genre = None

    # Dieselbe echte Bild-Erreichbarkeitsprüfung wie bei den anderen
    # Artikel-Typen — kaputte Links werden nicht blind übernommen.
    image = entry.get("image")
    if image and not npl.is_valid_image_url(image):
        image = None
    if not image:
        candidate = npl.fetch_og_image(entry["link"])
        image = candidate if candidate and npl.is_valid_image_url(candidate) else None
    if not image:
        import re
        seed = re.sub(r"[^a-zA-Z0-9]", "", entry["title"]) or "breaking"
        image = f"https://picsum.photos/seed/loadout-{seed}/900/500"

    return {
        "id": npl.article_id(entry["link"]),
        "cat": cat,
        "game": game,
        "genre": genre,
        "title": data.get("title", entry["title"]),
        "teaser": data.get("teaser", ""),
        "body": data.get("body", []),
        "editorial_take": "",  # Breaking News hat bewusst keine redaktionelle Einschätzung — dafür ist später Zeit
        "source_title": entry["title"],
        "date": datetime.date.today().strftime("%d. %B %Y"),
        "platform": entry["source"],
        "hype": int(data.get("hype", 70)),
        "source": entry["link"],
        "sourceLabel": entry["source"],
        "image": image,
        "content_type": "breaking",
    }


def main():
    checked_links = set(load_json(CHECKED_FILE, []))
    state = get_today_state()

    if state["count"] >= MAX_BREAKING_PER_DAY:
        print(f"→ Tages-Obergrenze für Breaking News bereits erreicht ({state['count']}/{MAX_BREAKING_PER_DAY}) — übersprungen.")
        return

    existing = load_json(ARTICLES_FILE, [])
    archive = load_json(ARCHIVE_FILE, [])
    existing_ids = {a["id"] for a in archive} | {a["id"] for a in existing}

    print("→ Lese RSS-Feeds für Breaking-News-Prüfung...")
    raw_entries = npl.fetch_raw_entries()

    # Nur wirklich neue Einträge prüfen: weder schon als Artikel
    # veröffentlicht, noch schon einmal für Breaking News geprüft (egal
    # mit welchem Ergebnis) — verhindert, dass dieselbe Meldung bei jedem
    # stündlichen Lauf erneut klassifiziert wird.
    fresh_entries = [
        e for e in raw_entries
        if e["link"] not in checked_links and npl.article_id(e["link"]) not in existing_ids
    ][:CHECK_BATCH_SIZE]

    if not fresh_entries:
        print("→ Keine neuen, noch ungeprüften Meldungen gefunden.")
        return

    print(f"→ {len(fresh_entries)} neue Meldung(en) werden auf Breaking-News-Kriterien geprüft...")
    breaking_candidates = classify_breaking(fresh_entries)

    # ALLE geprüften Links merken (unabhängig vom Ergebnis) — verhindert
    # erneutes Prüfen bei künftigen Läufen.
    checked_links |= {e["link"] for e in fresh_entries}
    save_json(CHECKED_FILE, sorted(checked_links))

    if not breaking_candidates:
        print("→ Nichts davon erfüllt die Breaking-News-Kriterien — normaler Fall, nichts zu tun.")
        return

    print(f"  {len(breaking_candidates)} Kandidat(en) erfüllen Breaking-News-Kriterien")

    # Dieselbe zweistufige Duplikat-Prüfung wie bei der regulären Pipeline
    # — nur weil etwas "breaking" wirkt, heisst das nicht, dass es nicht
    # schon anderweitig behandelt wurde.
    recent_titles = [a.get("source_title", a.get("title", "")) for a in (archive[-40:] + existing)]
    breaking_candidates = npl.filter_duplicate_topics(breaking_candidates, recent_titles)
    breaking_candidates = npl.semantic_duplicate_filter(breaking_candidates, recent_titles)

    if not breaking_candidates:
        print("→ Alle Breaking-Kandidaten waren bereits anderweitig abgedeckt — nichts zu tun.")
        return

    written = []
    for entry in breaking_candidates:
        if state["count"] + len(written) >= MAX_BREAKING_PER_DAY:
            print(f"  ⚠ Tages-Obergrenze erreicht — weitere Kandidaten werden heute nicht mehr verarbeitet.")
            break
        print(f"  🚨 Schreibe Breaking-News-Artikel: {entry['title'][:70]}")
        article = write_breaking_article(entry)
        if article:
            written.append(article)
        else:
            print("    ⚠ Schreiben fehlgeschlagen — übersprungen.")

    if not written:
        print("→ Keine Breaking-News-Artikel erfolgreich erstellt.")
        return

    all_articles = written + existing
    all_articles = all_articles[:npl.MAX_ARTICLES_TOTAL]
    save_json(ARTICLES_FILE, all_articles)

    archive = written + archive
    save_json(ARCHIVE_FILE, archive)

    state["count"] += len(written)
    save_json(STATE_FILE, state)

    print(f"✓ {len(written)} Breaking-News-Artikel veröffentlicht "
          f"({state['count']}/{MAX_BREAKING_PER_DAY} für heute).")


if __name__ == "__main__":
    main()
