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
import re
import sys

import news_pipeline as npl

CLASSIFY_MODEL = npl.DEDUP_MODEL  # dasselbe günstige Haiku-Modell wie bei der Duplikat-/Relevanz-Prüfung
WRITE_MODEL = npl.MODEL

ARTICLES_FILE = "articles.json"
ARCHIVE_FILE = "archive.json"
RUMORS_FILE = "rumors.json"  # für die Weiterreichungs-Prüfung, siehe route_to_rumor_tracker_if_resolves()
PENDING_RESOLUTIONS_FILE = "pending-resolutions.json"  # Übergabe an rumor_tracker.py
CHECKED_FILE = "breaking-checked.json"  # Merkliste: welche Feed-Links wurden schon klassifiziert (egal ob Breaking oder nicht)
STATE_FILE = "breaking-state.json"  # Tages-Zähler fürs Limit

MAX_BREAKING_PER_DAY = 2
CHECK_BATCH_SIZE = 40  # wie viele frische Feed-Einträge pro Lauf klassifiziert werden — grosszügig, da diese Prüfung günstig ist

# Wie weit die Duplikat-Prüfung gegen bereits veröffentlichte Artikel
# zurückschaut (siehe recent_titles in main()). 4 Tage sind grosszügig
# bemessen für den gemeldeten Fall "Breaking News von gestern Mittag
# taucht heute Nacht nochmal auf" — ein Thema, das vor mehreren Tagen
# schon lief (egal ob als Breaking News oder als regulärer Artikel), ist
# mit Sicherheit nicht mehr "gerade jetzt" breaking.
RECENT_DEDUP_DAYS = 4

# Wie alt ein RSS-Eintrag laut seinem eigenen Publish-Datum maximal sein
# darf, um überhaupt als Breaking-News-Kandidat infrage zu kommen. Verhindert,
# dass ein Feed-Eintrag, der schon vor Tagen veröffentlicht wurde (z. B. weil
# er erst spät im Feed auftaucht oder von der Quelle erneut hochgeladen
# wurde), fälschlich als "gerade jetzt passiert" eingestuft wird — bisher
# bekam die Klassifikation nur Titel + Kurzbeschreibung zu sehen, nie das
# tatsächliche Publish-Datum des Eintrags.
MAX_ENTRY_AGE_HOURS = 48

GERMAN_MONTHS = {
    "Januar": 1, "Februar": 2, "März": 3, "April": 4, "Mai": 5, "Juni": 6,
    "Juli": 7, "August": 8, "September": 9, "Oktober": 10, "November": 11, "Dezember": 12,
}

BREAKING_CRITERIA = """Eine Meldung gilt als "Breaking News" NUR dann, wenn das Warten bis \
zum nächsten regulären Tages-Lauf (heute Abend, 19 Uhr) der Meldung \
WIRKLICH schaden würde — z. B. weil die Information bis dahin veraltet, \
längst überall bekannt oder für Leser:innen nicht mehr handlungsrelevant \
wäre. Das ist eine SEHR HOHE Hürde — die grosse Mehrheit auch von \
wichtigen, relevanten Gaming-News ist KEINE Breaking News.

Nur MINDESTENS eines dieser eng gefassten Kriterien reicht:

1. Eine SOEBEN offiziell bestätigte Terminverschiebung (verschoben ODER \
   überraschend vorgezogen) eines der 6 Haupt-Franchises (GTA, Minecraft, \
   Fortnite, Call of Duty, Valorant/LoL, FIFA) oder eines vergleichbar \
   riesigen AAA-Titels — NICHT: Gerüchte über eine mögliche Verschiebung, \
   NICHT: kleinere Terminänderungen bei mittelgrossen Spielen
2. Eine GERADE JETZT laufende, grossflächige Server-/Plattform-Störung \
   (PSN, Xbox Live, Steam), die zum Zeitpunkt der Meldung noch aktuell ist \
   — NICHT: eine bereits behobene, vergangene Störung
3. Eine SOEBEN bekannt gewordene, wirklich überraschende \
   Unternehmensmeldung (plötzliche Studio-Schliessung, Übernahme eines \
   grossen Publishers, überraschender Rücktritt einer sehr bekannten \
   Führungsperson) — NICHT: übliche Quartalszahlen, NICHT: normale \
   Personalveränderungen
4. Eine akute Sicherheitswarnung (aktiver Hack, laufendes Datenleck) bei \
   einer der grossen Plattformen/einem der Haupt-Franchises, bei der \
   schnelles Handeln für betroffene Nutzer:innen wirklich einen Unterschied \
   macht

Explizit KEINE Breaking News, selbst wenn interessant/relevant/aufsehenerregend:
- Ein neuer Trailer, auch zu einem grossen Spiel
- Ein regulärer, angekündigter Patch oder ein DLC-Release
- Verkaufszahlen, Chart-Platzierungen, Auszeichnungen
- Allgemeine Branchen-Analysen oder Meinungsstücke
- Alles, was schon vor Stunden/Tagen bekannt war und nur neu \
  zusammengefasst wird
- WICHTIG, EXPLIZITER AUSSCHLUSS: JEDER Leak oder JEDES Gerücht, ganz \
  gleich wie aktuell, aufsehenerregend oder mit wie vielen "greifbaren" \
  Details — auch nicht, wenn eine grosse Fachpresse-Quelle darüber \
  berichtet. Ein Leak ist per Definition NICHT offiziell bestätigt, egal \
  wie plausibel er wirkt. Dafür gibt es den eigenen, dauerhaften \
  "Leaks & Gerüchte-Tracker" (siehe rumor_tracker.py) — der begleitet \
  genau solche Themen fortlaufend mit einer eigenen Glaubwürdigkeits- \
  Einschätzung, statt sie als vermeintlich bestätigte Eilmeldung \
  misszuverstehen. Diese Trennung ist bewusst und darf nicht aufgeweicht \
  werden, auch nicht bei einem besonders "sicher wirkenden" Leak."""


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


def _entry_recent_enough(entry, max_age_hours=MAX_ENTRY_AGE_HOURS):
    """Prüft das eigene Publish-Datum des RSS-Eintrags (nicht das der KI-
    Klassifikation, die das Datum bisher gar nicht zu sehen bekam). Ist kein
    Datum vorhanden, wird der Eintrag sicherheitshalber NICHT ausgeschlossen
    — die inhaltliche Prüfung durch die KI (BREAKING_CRITERIA) bleibt dann
    die einzige Bremse, statt einen Kandidaten durch ein technisches
    Feld-Problem zu verlieren."""
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if not published:
        return True
    try:
        published_dt = datetime.datetime(*published[:6])
    except Exception:
        return True
    age = datetime.datetime.utcnow() - published_dt
    return age <= datetime.timedelta(hours=max_age_hours)


def _parse_article_date(article):
    """Wandelt das deutsche Datumsformat der Artikel (z. B. "05. August
    2026") in ein vergleichbares datetime.date um. Gibt None zurück, wenn
    das Format nicht erkannt wird — solche Artikel werden dann
    sicherheitshalber TROTZDEM in die Duplikat-Prüfung aufgenommen (siehe
    recent_titles in main()), statt sie stillschweigend zu ignorieren."""
    date_str = article.get("date", "")
    match = re.match(r"(\d{1,2})\.\s*([A-Za-zäöüÄÖÜ]+)\s*(\d{4})", date_str.strip())
    if not match:
        return None
    day, month_name, year = match.groups()
    month = GERMAN_MONTHS.get(month_name)
    if not month:
        return None
    try:
        return datetime.date(int(year), month, int(day))
    except ValueError:
        return None


def classify_breaking(entries):
    """EIN günstiger Haiku-Aufruf: welche der Kandidaten sind wirklich
    Breaking News? Läuft nur auf frischen, noch nie geprüften Einträgen
    (siehe CHECKED_FILE) — das ist der Normalfall bei fast jedem
    stündlichen Lauf, und bewusst so günstig gehalten, dass häufiges
    Ausführen kein Kostenproblem ist.

    Bekommt bewusst TITEL + Kurzbeschreibung (nicht nur den Titel) — eine
    reine Überschrift lässt oft nicht erkennen, ob wirklich ein neues,
    dringendes Ereignis vorliegt oder nur eine Zusammenfassung von etwas
    längst Bekanntem. Verlangt ausserdem eine kurze Begründung pro
    gefundenem Kandidaten (nicht nur eine blanke Nummer) — das zwingt das
    Modell zu genauerer Prüfung, statt vorschnell "ja" zu antworten."""
    if not entries:
        return []

    candidates_block = "\n".join(
        f"{i}: {e['title']} — {(e.get('summary') or '')[:200]}"
        for i, e in enumerate(entries)
    )

    prompt = f"""{BREAKING_CRITERIA}

Kandidaten (nummeriert, 0-basiert, mit Kurzbeschreibung):
{candidates_block}

Prüfe JEDEN Kandidaten kritisch gegen die Kriterien oben. Im Zweifel: \
NICHT als Breaking News einstufen — die Hürde ist bewusst hoch.

Antworte AUSSCHLIESSLICH mit einem validen JSON-Array, keine Erklärung \
ausserhalb des JSON, kein Markdown. Jedes Element (nur für WIRKLICH als \
Breaking eingestufte Kandidaten) im Format:
[{{"index": <Nummer>, "reason": "<1 kurzer Satz, warum genau JETZT, nicht bis heute Abend warten>"}}]

Beispiel: [{{"index": 3, "reason": "Rockstar bestätigt soeben offiziell die Verschiebung von GTA 6"}}]

Falls kein Kandidat wirklich Breaking News ist: []"""

    try:
        response = npl.client.messages.create(
            model=CLASSIFY_MODEL,
            max_tokens=500,
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
        parsed = json.loads(raw, strict=False)

        indices = set()
        for item in parsed:
            if isinstance(item, dict) and "index" in item:
                indices.add(item["index"])
                print(f"  → Kandidat {item['index']} als Breaking eingestuft: {item.get('reason', '')}")
            elif isinstance(item, int):  # Rückfall, falls das Modell doch nur Zahlen liefert
                indices.add(item)
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

    # Absicherung: eine Breaking-News-Eilmeldung ohne echten Fließtext ist
    # nutzlos und würde als leere Artikelseite landen — lieber gar nicht
    # veröffentlichen als das.
    body = data.get("body") or []
    if not body:
        print(f"  ! Modell lieferte leeren Fließtext für Breaking-News: {entry['title']} — verworfen.", file=sys.stderr)
        return None

    # Dieselbe echte Bild-Erreichbarkeitsprüfung wie bei den anderen
    # Artikel-Typen — kaputte Links werden nicht blind übernommen.
    image = entry.get("image")
    if image and not npl.is_valid_image_url(image):
        image = None
    if not image:
        candidate = npl.fetch_og_image(entry["link"])
        image = candidate if candidate and npl.is_valid_image_url(candidate) else None
    if not image:
        seed = re.sub(r"[^a-zA-Z0-9]", "", entry["title"]) or "breaking"
        image = f"https://picsum.photos/seed/loadout-{seed}/900/500"

    return {
        "id": npl.article_id(entry["link"]),
        "cat": cat,
        "game": game,
        "genre": genre,
        "title": data.get("title", entry["title"]),
        "teaser": data.get("teaser", ""),
        "body": body,
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


def filter_breaking_duplicates_strict(candidates, recent_titles):
    """Wie news_pipeline.filter_candidates_combined (Duplikat- UND
    Relevanz-Prüfung in einem KI-Aufruf), aber mit einem entscheidenden
    Unterschied bei Fehlern: Schlägt der API-Aufruf aus irgendeinem Grund
    fehl (Netzwerk-Hänger, Rate-Limit, unparsebare Antwort), werden ALLE
    Kandidaten dieses Laufs verworfen — NICHT wie im Rest der Pipeline
    unverändert durchgelassen.

    Grund für die bewusst andere Philosophie: Bei der regulären Pipeline
    (news_pipeline.py: filter_candidates_combined) ist "im Zweifel nicht
    zu streng filtern" richtig, weil ein verpasster Filter-Fehlschlag dort
    höchstens einen einzelnen weniger relevanten Artikel unter vielen
    bedeutet. Bei Breaking News ist das Risiko-Verhältnis umgekehrt: ein
    durch einen API-Fehler nicht erkanntes Duplikat wird SOFORT und
    prominent als Eilmeldung gepostet — das kostet Glaubwürdigkeit. Ein
    fälschlich übersprungenes, echtes Breaking-Thema kostet dagegen nur
    ein paar Stunden Vorsprung, da es ganz normal über die reguläre
    19-Uhr-Pipeline nachgeliefert wird."""
    if not candidates:
        return []

    recent = [t for t in recent_titles if t][-40:]
    candidates_block = "\n".join(f"{i}: {e['title']}" for i, e in enumerate(candidates))
    recent_block = "\n".join(f"- {t}" for t in recent) if recent else "(keine)"

    prompt = f"""Bereits kürzlich veröffentlichte Themen (inkl. heutiger Breaking-News):
{recent_block}

Neue Breaking-News-Kandidaten (nummeriert, 0-basiert):
{candidates_block}

Prüfe JEDEN Kandidaten auf ZWEI unabhängige Kriterien:

(A) DUPLIKAT: Behandelt der Kandidat inhaltlich dasselbe Thema wie eines
der bereits veröffentlichten Themen oben (auch bei komplett
unterschiedlichem Wortlaut — es zählt der inhaltliche Kern)?

(B) IRRELEVANT: Erfüllt der Kandidat KEINES der folgenden Relevanz-
Kriterien (schon eines reicht, um NICHT irrelevant zu sein)?
{npl.RELEVANCE_CRITERIA}

Bei Breaking News ist absolute Vorsicht wichtiger als Vollständigkeit —
sei im Zweifelsfall EHER zu streng als zu lax.

Antworte AUSSCHLIESSLICH mit einem validen JSON-Objekt, keine Erklärung,
kein Markdown:
{{"duplicates": [<Nummern>], "irrelevant": [<Nummern>]}}

Beispiel: {{"duplicates": [1], "irrelevant": []}}. Falls beide Listen leer sind: {{"duplicates": [], "irrelevant": []}}."""

    try:
        response = npl.client.messages.create(
            model=CLASSIFY_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text_blocks = [b.text for b in response.content if b.type == "text"]
        if not text_blocks:
            print("  ⚠ Breaking-Duplikat-Prüfung: keine Antwort erhalten — sicherheitshalber ALLE Kandidaten dieses Laufs verworfen.", file=sys.stderr)
            return []
        raw = text_blocks[-1].strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        first_brace = raw.find("{")
        if first_brace > 0:
            raw = raw[first_brace:]
        data = json.loads(raw, strict=False)
        reject_indices = set(data.get("duplicates", [])) | set(data.get("irrelevant", []))
    except Exception as e:
        print(f"  ⚠ Breaking-Duplikat-Prüfung fehlgeschlagen ({e}) — sicherheitshalber ALLE Kandidaten dieses Laufs verworfen "
              f"(kein Risiko für doppelte Breaking-News, lieber eine Stunde später über die reguläre Pipeline).", file=sys.stderr)
        return []

    kept = [c for i, c in enumerate(candidates) if i not in reject_indices]
    removed = len(candidates) - len(kept)
    if removed:
        print(f"  {removed} Breaking-Kandidat(en) als Duplikat/irrelevant erkannt und verworfen.")
    return kept


def route_to_rumor_tracker_if_resolves(candidates, active_trackers):
    """Wie news_pipeline.py: route_to_rumor_tracker_if_resolves() —
    verhindert, dass die offizielle Bestätigung/das offizielle Dementi
    eines laufenden Leaks & Gerüchte-Trackers als EIGENE Breaking-News-
    Eilmeldung erscheint, während der zugehörige Tracker fälschlich offen
    bleibt. Passende Kandidaten werden stattdessen über
    pending-resolutions.json an rumor_tracker.py übergeben, das die
    Auflösung recherchiert und den Tracker korrekt schliesst.

    Fail-closed-Charakter wie bei filter_breaking_duplicates_strict: bei
    einem Fehlschlag wird NICHTS geroutet, die Kandidaten bleiben normal
    im Pool und werden ganz regulär als Breaking News behandelt — ein
    verpasstes Routing bedeutet höchstens ein etwas später schliessendes
    Tracker, kein Duplikat-Risiko."""
    if not candidates or not active_trackers:
        return candidates, []

    trackers_block = "\n".join(
        f"- id={t['id']}: {t['topic_name']} — {t.get('summary', '')[:200]}"
        for t in active_trackers
    )
    candidates_block = "\n".join(f"{i}: {e['title']}" for i, e in enumerate(candidates))

    prompt = f"""Aktuell laufende Leaks & Gerüchte-Tracker (id + worum es geht):
{trackers_block}

Neue Breaking-News-Kandidaten (nummeriert, 0-basiert):
{candidates_block}

Welche Kandidaten behandeln inhaltlich DASSELBE Thema wie einer der oben
genannten laufenden Tracker (auch bei komplett unterschiedlichem
Wortlaut)? Das gilt unabhängig davon, ob der Kandidat das jeweilige
Gerücht bestätigt oder dementiert.

Antworte AUSSCHLIESSLICH mit einem validen JSON-Array von Objekten, keine
Erklärung, kein Markdown:
[{{"index": <Nummer>, "tracker_id": "<passende id von oben>"}}]

Beispiel: [{{"index": 0, "tracker_id": "gta-6-pc-version"}}]. Falls keine
Überschneidung: []."""

    try:
        response = npl.client.messages.create(
            model=CLASSIFY_MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text_blocks = [b.text for b in response.content if b.type == "text"]
        if not text_blocks:
            print("  ⚠ Gerüchte-Tracker-Überschneidungsprüfung: keine Antwort — kein Routing.", file=sys.stderr)
            return candidates, []
        raw = text_blocks[-1].strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        first_bracket = raw.find("[")
        if first_bracket > 0:
            raw = raw[first_bracket:]
        matches = json.loads(raw, strict=False)
    except Exception as e:
        print(f"  ⚠ Gerüchte-Tracker-Überschneidungsprüfung fehlgeschlagen ({e}) — kein Routing.", file=sys.stderr)
        return candidates, []

    active_ids = {t["id"] for t in active_trackers}
    matched_indices = set()
    routed = []
    for m in matches:
        if not isinstance(m, dict):
            continue
        idx = m.get("index")
        tracker_id = m.get("tracker_id")
        if not isinstance(idx, int) or not (0 <= idx < len(candidates)) or tracker_id not in active_ids:
            continue
        matched_indices.add(idx)
        routed.append({"tracker_id": tracker_id, "entry": candidates[idx]})

    remaining = [c for i, c in enumerate(candidates) if i not in matched_indices]
    if routed:
        print(f"  {len(routed)} Kandidat(en) an den Leaks & Gerüchte-Tracker weitergereicht statt als Breaking News zu erscheinen.")
    return remaining, routed


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
    candidate_pool = [
        e for e in raw_entries
        if e["link"] not in checked_links and npl.article_id(e["link"]) not in existing_ids
    ][:CHECK_BATCH_SIZE]

    # Kandidaten, deren RSS-Eintrag laut eigenem Publish-Datum schon zu alt
    # ist, werden gar nicht erst zur Klassifikation geschickt — aber
    # trotzdem als "geprüft" markiert, damit sie nicht bei jedem
    # stündlichen Lauf erneut in Betracht gezogen werden.
    fresh_entries = [e for e in candidate_pool if _entry_recent_enough(e)]
    too_old_entries = [e for e in candidate_pool if not _entry_recent_enough(e)]
    if too_old_entries:
        print(f"→ {len(too_old_entries)} Eintrag/Einträge wegen Alter (> {MAX_ENTRY_AGE_HOURS}h) übersprungen.")
        checked_links |= {e["link"] for e in too_old_entries}

    if not fresh_entries:
        print("→ Keine neuen, noch ungeprüften Meldungen gefunden.")
        save_json(CHECKED_FILE, sorted(checked_links))
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

    # Dieselbe kombinierte Duplikat- UND Relevanz-Prüfung wie bei der
    # regulären Pipeline (siehe news_pipeline.py: filter_candidates_combined)
    # — WICHTIG: nur weil etwas zeitlich dringend wirkt, heisst das nicht,
    # dass es auch inhaltlich relevant genug ist (grosses Studio/Franchise/
    # Community, siehe RELEVANCE_CRITERIA) oder nicht längst anderweitig
    # abgedeckt wurde.
    #
    # KORREKTUR (siehe RECENT_DEDUP_DAYS oben): archive.json wird per
    # "archive = written + archive" immer VORNE ergänzt (neueste zuerst).
    # Ein archive[-40:] holte deshalb bisher fälschlich die 40 ÄLTESTEN
    # statt die 40 neuesten Einträge — ein Thema von vor ein paar Tagen
    # konnte so komplett aus der Duplikat-Prüfung herausfallen, sobald es
    # auch aus "existing" (articles.json, laufend rotierend) verschwunden
    # war. Jetzt wird stattdessen zeitbasiert nach echtem Artikel-Datum
    # gefiltert — robust unabhängig davon, wie viele reguläre Artikel
    # zwischenzeitlich veröffentlicht wurden.
    cutoff = datetime.date.today() - datetime.timedelta(days=RECENT_DEDUP_DAYS)
    recent_from_archive = [
        a for a in archive
        if (_parse_article_date(a) is None) or (_parse_article_date(a) >= cutoff)
    ]
    recent_titles = [a.get("source_title", a.get("title", "")) for a in (recent_from_archive + existing)]

    breaking_candidates = npl.filter_duplicate_topics(breaking_candidates, recent_titles)  # günstige Textprüfung zuerst
    breaking_candidates = filter_breaking_duplicates_strict(breaking_candidates, recent_titles)  # fail-closed statt fail-open, siehe Funktionsdoku oben

    # NEU: Kandidaten, die inhaltlich einen AKTIVEN Leaks & Gerüchte-
    # Tracker bestätigen/dementieren, werden NICHT als eigene Breaking-
    # News-Eilmeldung veröffentlicht, sondern an rumor_tracker.py
    # weitergereicht — siehe route_to_rumor_tracker_if_resolves() oben.
    active_trackers_full = []
    if os.path.exists(RUMORS_FILE):
        with open(RUMORS_FILE, "r", encoding="utf-8") as f:
            rumor_trackers = json.load(f)
        active_trackers_full = [t for t in rumor_trackers if t.get("status") == "aktiv"]

    breaking_candidates, routed_to_tracker = route_to_rumor_tracker_if_resolves(breaking_candidates, active_trackers_full)
    if routed_to_tracker:
        pending = []
        if os.path.exists(PENDING_RESOLUTIONS_FILE):
            with open(PENDING_RESOLUTIONS_FILE, "r", encoding="utf-8") as f:
                pending = json.load(f)
        for item in routed_to_tracker:
            pending.append({
                "tracker_id": item["tracker_id"],
                "entry": item["entry"],
                "flagged_by": "breaking_news_check",
                "flagged_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            })
        with open(PENDING_RESOLUTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(pending, f, ensure_ascii=False, indent=2)

    if not breaking_candidates:
        print("→ Alle Breaking-Kandidaten waren entweder bereits abgedeckt, an den Gerüchte-Tracker weitergereicht oder nicht relevant genug — nichts zu tun.")
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
            print("  ⚠ Schreiben fehlgeschlagen — übersprungen.")

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
