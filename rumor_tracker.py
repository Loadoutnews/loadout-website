"""
LOADOUT-NEWS — Der lebende Gerüchte-Tracker
================================================
Richtung 3 der Alleinstellungsmerkmale: Statt für jedes neue Detail zu einem
laufenden Leak/Gerücht einen weiteren Einzelartikel zu schreiben, pflegt
dieses Skript EINE dauerhafte, sich aktualisierende Tracker-Seite pro großem,
laufendem Gerücht (z. B. "GTA 6 PC-Version — Stand der Gerüchte"). Neue Infos
werden als Zeitleisten-Einträge an den bestehenden Tracker angehängt statt
einen neuen Artikel zu erzeugen — inklusive Glaubwürdigkeits-Einschätzung
(Kategorie + Prozentwert), die sich mit jedem neuen Eintrag anpassen kann.

Läuft bewusst als EIGENER, periodischer Lauf (empfohlen: alle 3-4 Stunden,
siehe .github/workflows/rumor-tracker.yml) — GETRENNT vom 19-Uhr-Hauptlauf
(news_pipeline.py) und von breaking_news_check.py, aus denselben Gründen wie
bei breaking_news_check.py: günstige Vorprüfung in den meisten Läufen, teurer
Schritt (Sonnet + Websuche) nur wenn wirklich ein passender Kandidat gefunden
wurde. Nutzt news_pipeline.py als Modul (FEEDS, RELEVANCE_CRITERIA, Bild-
Validierung, client) — keine Logik wird dupliziert.

Komplett automatisch (keine manuelle Freigabe nötig, wie besprochen):
- Neue Gerüchte-Kandidaten aus den RSS-Feeds werden erkannt
- Passen sie zu einem bereits laufenden Tracker → Zeitleisten-Eintrag wird
  automatisch angehängt
- Ist es ein komplett neues, relevantes Gerücht → ein neuer Tracker wird
  automatisch eröffnet
- Bestätigt oder dementiert eine neue Meldung ein Gerücht eindeutig, wird der
  Tracker automatisch als "abgeschlossen" markiert (bleibt aber einsehbar)

Schreibt/liest rumors.json (eigene Datei, unabhängig von articles.json/
archive.json) und wird von build_rumor_pages.py zu statischen Seiten unter
/geruechte/<id>.html + der Übersichtsseite geruechte.html verarbeitet.

Ausführen:
    python rumor_tracker.py
"""

import datetime
import hashlib
import json
import os
import re
import sys

import news_pipeline as npl

CLASSIFY_MODEL = npl.DEDUP_MODEL  # günstiges Haiku-Modell für die Vorprüfung/Zuordnung
WRITE_MODEL = npl.MODEL

RUMORS_FILE = "rumors.json"
CHECKED_FILE = "rumor-checked.json"   # Merkliste: welche Feed-Links wurden schon geprüft
STATE_FILE = "rumor-state.json"       # Tages-Zähler fürs Limit neuer Tracker

CHECK_BATCH_SIZE = 40          # wie viele frische Feed-Einträge pro Lauf geprüft werden
MAX_NEW_TRACKERS_PER_RUN = 1   # neue Tracker sind teuer (volle Recherche) — pro Lauf bewusst knapp
MAX_NEW_TRACKERS_PER_DAY = 2   # zusätzliche Tages-Obergrenze, damit die Gerüchte-Seite nicht zuwuchert
MAX_UPDATES_PER_RUN = 3        # wie viele bestehende Tracker pro Lauf maximal ein Update bekommen

# Wie weit zurück die Prüfung gegen bereits veröffentlichte REGULÄRE Artikel
# (news_pipeline.py) schaut, um zu verhindern, dass dasselbe Thema
# gleichzeitig als Gerüchte-Tracker UND als normaler Artikel läuft — siehe
# classify_and_match(covered_article_titles=...) und main() unten. Etwas
# grosszügiger als RECENT_DEDUP_DAYS (breaking_news_check.py), da ein
# Thema, das schon vor einer Woche final als News lief, immer noch klar
# "schon abgedeckt" ist.
ARTICLE_DEDUP_DAYS = 7

VALID_CATS = {"pc", "konsole", "hardware", "industrie"}
VALID_GAMES = {"gta", "minecraft", "fortnite", "cod", "valorant", "fifa"}
VALID_CREDIBILITY = {"unbestaetigt", "wahrscheinlich", "sehr_wahrscheinlich", "bestaetigt", "dementiert"}

# Deutsche Anzeige-Labels + Marken-Farbe je Glaubwürdigkeits-Kategorie —
# dieselbe Zuordnung wird 1:1 in build_rumor_pages.py für die Anzeige auf
# der Website verwendet, damit Backend und Frontend nie auseinanderlaufen.
CREDIBILITY_META = {
    "unbestaetigt":       {"label": "Unbestätigt",       "color": "#8D90AC"},  # --muted
    "wahrscheinlich":     {"label": "Wahrscheinlich",     "color": "#FFB74D"},  # --amber
    "sehr_wahrscheinlich": {"label": "Sehr wahrscheinlich", "color": "#7C5CFC"},  # --violet
    "bestaetigt":         {"label": "Bestätigt",          "color": "#34D9C9"},  # --cyan
    "dementiert":         {"label": "Dementiert",         "color": "#FF3B30"},  # bewusst kräftiges Rot, klar von der Marken-Magenta unterscheidbar
}


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


GERMAN_MONTHS = {
    "Januar": 1, "Februar": 2, "März": 3, "April": 4, "Mai": 5, "Juni": 6,
    "Juli": 7, "August": 8, "September": 9, "Oktober": 10, "November": 11, "Dezember": 12,
}


def _parse_article_date(article):
    """Wandelt das deutsche Datumsformat der REGULÄREN Artikel (z. B. "05.
    August 2026", siehe news_pipeline.py) in ein vergleichbares
    datetime.date um — für das zeitliche Fenster von ARTICLE_DEDUP_DAYS.
    Gibt None zurück, wenn das Format nicht erkannt wird; solche Artikel
    werden dann sicherheitshalber TROTZDEM in die Cross-Pipeline-Prüfung
    aufgenommen (siehe main()), statt sie stillschweigend zu ignorieren."""
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


def slugify(text):
    """Erzeugt eine lesbare, URL-taugliche ID aus dem Themen-Namen (z. B.
    "GTA 6 PC-Version" → "gta-6-pc-version") statt eines anonymen Hashes —
    so bleiben Tracker-URLs auch für Menschen erkennbar/teilbar."""
    text = (text or "").lower()
    umlaut_map = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}
    for k, v in umlaut_map.items():
        text = text.replace(k, v)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "geruecht"


def unique_tracker_id(topic_name, existing_ids):
    base = slugify(topic_name)
    candidate = base
    suffix = 2
    while candidate in existing_ids:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _clamp_pct(value, default=30):
    try:
        pct = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(100, pct))


def _valid_credibility_category(value, default="unbestaetigt"):
    return value if value in VALID_CREDIBILITY else default


# --- Stufe 1: Vorprüfung + Zuordnung (günstig, EIN Haiku-Aufruf für den ganzen Batch) ---

RUMOR_CRITERIA = f"""Ein RSS-Eintrag zählt als "Gerücht/Leak" NUR, wenn er über eine \
NOCH NICHT offiziell bestätigte Information berichtet — z. B. weil er sich auf \
"Insider", "geleakte Dokumente/Dateien", "Datamining", "Quellen mit Kenntnis der \
Situation" oder unbestätigte Berichte/Spekulation beruft, NICHT auf eine \
offizielle Ankündigung des Studios/Publishers selbst.

Explizit KEIN Gerücht (gehört stattdessen in die normale News-Pipeline, hier \
IMMER "skip"):
- Eine offiziell vom Studio/Publisher bestätigte Ankündigung
- Ein offiziell veröffentlichter Trailer, Patch-Release oder Release-Termin
- Eine offizielle Pressemitteilung, auch wenn sie überraschend kommt
- Reine Meinungsstücke/Spekulation von Journalist:innen ohne jede Quellen-Angabe

Zusätzlich muss das Thema relevant genug für einen eigenen, dauerhaften \
Tracker sein:
{npl.RELEVANCE_CRITERIA}"""


def classify_and_match(entries, active_trackers, covered_article_titles=None):
    """EIN günstiger Haiku-Aufruf für den ganzen Batch: welche Kandidaten
    sind wirklich unbestätigte Gerüchte/Leaks zu einem relevanten Thema —
    und falls ja, setzen sie ein bereits laufendes Tracker-Thema fort
    ("update") oder eröffnen ein komplett neues ("new")?

    covered_article_titles: Titel bereits veröffentlichter REGULÄRER
    Artikel (aus news_pipeline.py, zeitlich begrenzt auf die letzten Tage,
    siehe main()) — verhindert, dass ein Thema, das schon als bestätigter
    News-Artikel läuft, zusätzlich (und unnötig) einen eigenen Gerüchte-
    Tracker bekommt. Beide Pipelines laufen unabhängig voneinander und
    teilen sich sonst keine gemeinsame "das haben wir schon"-Liste."""
    if not entries:
        return []

    candidates_block = "\n".join(
        f"{i}: {e['title']} — {(e.get('summary') or '')[:200]}"
        for i, e in enumerate(entries)
    )
    if active_trackers:
        trackers_block = "\n".join(
            f"- id={t['id']}: {t['topic_name']} — {t.get('summary', '')[:200]}"
            for t in active_trackers
        )
    else:
        trackers_block = "(noch keine laufenden Gerüchte-Tracker)"

    covered_article_titles = [t for t in (covered_article_titles or []) if t]
    if covered_article_titles:
        covered_block = "\n".join(f"- {t}" for t in covered_article_titles[-40:])
    else:
        covered_block = "(keine)"

    prompt = f"""{RUMOR_CRITERIA}

Aktuell laufende Gerüchte-Tracker (id + worum es geht):
{trackers_block}

Bereits als REGULÄRER, bestätigter News-Artikel veröffentlichte Themen \
(NICHT Gerüchte-Tracker — diese Themen sind schon als echte News abgedeckt):
{covered_block}

Neue RSS-Kandidaten (nummeriert, 0-basiert):
{candidates_block}

Prüfe JEDEN Kandidaten:
1. Ist es wirklich ein GERÜCHT/LEAK (keine offizielle Bestätigung) zu einem \
relevanten Thema (siehe Kriterien oben)? Falls nein: action "skip".
2. Behandelt der Kandidat inhaltlich dasselbe Thema wie eines der bereits \
als regulärer Artikel veröffentlichten Themen oben? Dann ist es keine \
offene Frage mehr, sondern schon berichtete News — action "skip".
3. Setzt er ein BEREITS LAUFENDES Gerücht aus der Tracker-Liste oben fort \
(gleiches Thema, z. B. neue Details zum selben Leak)? Dann action "update" \
mit der passenden tracker_id aus der Liste oben.
4. Ist es ein komplett NEUES Gerücht ohne bestehenden Tracker UND ohne \
bereits veröffentlichten Artikel dazu: action "new".
5. Behandeln mehrere Kandidaten in dieser Liste dasselbe NEUE Gerücht: nur \
der ERSTE bekommt "new", alle weiteren "skip" (kein Tracker existiert für \
sie noch, aber das erste "new" deckt das Thema bereits ab).

Antworte AUSSCHLIESSLICH mit einem validen JSON-Array, keine Erklärung, \
kein Markdown. Jedes Element:
[{{"index": <Nummer>, "action": "update" | "new" | "skip", "tracker_id": "<nur bei action=update, sonst weglassen>", "reason": "<1 kurzer Satz>"}}]

Beispiel: [{{"index": 2, "action": "new", "reason": "Neuer Leak zu unangekündigtem Switch-2-Port"}}, {{"index": 5, "action": "update", "tracker_id": "gta-6-pc-version", "reason": "Weiteres Detail zum laufenden PC-Port-Gerücht"}}]

Falls kein Kandidat relevant ist: []"""

    try:
        response = npl.client.messages.create(
            model=CLASSIFY_MODEL,
            max_tokens=800,
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
    except Exception as e:
        print(f"  ⚠ Gerüchte-Vorprüfung fehlgeschlagen: {e}", file=sys.stderr)
        return []

    active_ids = {t["id"] for t in active_trackers}
    decisions = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int) or not (0 <= index < len(entries)):
            continue
        action = item.get("action")
        if action == "update":
            tracker_id = item.get("tracker_id")
            if tracker_id not in active_ids:
                # KI hat eine ungültige/erfundene tracker_id geliefert — im
                # Zweifel überspringen statt an einen falschen Tracker zu hängen.
                continue
            decisions.append({"index": index, "action": "update", "tracker_id": tracker_id,
                               "reason": item.get("reason", "")})
        elif action == "new":
            decisions.append({"index": index, "action": "new", "reason": item.get("reason", "")})
        # "skip" und alles andere: ignorieren

    for d in decisions:
        tag = f"→ {d['tracker_id']}" if d["action"] == "update" else "→ NEU"
        print(f"  {entries[d['index']]['title'][:60]}  [{d['action']} {tag}] {d['reason']}")

    return decisions


# --- Stufe 2a: Neuen Tracker eröffnen (teuer, Sonnet + Websuche) -----------

CREATE_TRACKER_SYSTEM_PROMPT = """Du bist Redakteur:in bei LOADOUT, einer deutschsprachigen \
Gaming- und Tech-News-Seite. Du eröffnest einen NEUEN "lebenden Gerüchte- \
Tracker" — eine dauerhafte Seite, die ein einzelnes, laufendes Gerücht über \
Wochen/Monate hinweg begleitet und bei neuen Infos weitergeführt wird, statt \
für jedes Detail einen eigenen Artikel zu schreiben.

Regeln:
- ABSOLUT ENTSCHEIDEND: Alle Textfelder zu 100 % auf Deutsch, auch wenn die \
Quelle englisch ist. Keine englischen Sätze/Satzteile. Eigennamen bleiben \
im Original.
- Recherchiere aktiv mit der Websuche, was zu diesem Gerücht bereits \
kursiert (mehrere Quellen wenn möglich) — nicht nur die eine Ausgangsmeldung.
- Sei explizit und ehrlich in der Glaubwürdigkeits-Einschätzung: Woher \
stammt die Info, wie seriös/verlässlich war diese Quelle bisher, gibt es \
mehrere unabhängige Bestätigungen oder nur eine einzelne Behauptung?
- "credibility_category" UND "credibility_pct" müssen zueinander passen \
(z. B. "unbestaetigt" i. d. R. unter 35, "sehr_wahrscheinlich" i. d. R. \
70-89). "bestaetigt"/"dementiert" nur, wenn es dafür bereits eine \
offizielle oder eindeutige Bestätigung/Widerlegung gibt — ist das der \
Fall, sollte es eigentlich KEIN neuer Gerüchte-Tracker mehr sein, sondern \
ein normaler Artikel. Bei echtem Zweifel: eher konservativ (niedrigere \
Kategorie) einschätzen.
- Antworte AUSSCHLIESSLICH mit einem validen JSON-Objekt, keine \
Erklärungen, kein Markdown, keine Code-Fences.
- WICHTIG für gültiges JSON: NIEMALS gerade doppelte Anführungszeichen \
innerhalb der Textfelder, keine rohen Zeilenumbrüche innerhalb eines Feldes.
- Suche aktiv nach einem thematisch passenden Bild (offizielles Artwork, \
Screenshot, Pressebild) und trage die direkte Bild-URL in "image_url" ein \
— findest du keines, setze "image_url" auf null.

JSON-Format:
{
  "topic_name": "Kurzer, prägnanter Name des Gerüchts-Themas (max. 60 Zeichen), OHNE den Zusatz '— Stand der Gerüchte' — der wird automatisch angehängt. Beispiel: 'GTA 6 PC-Version'",
  "cat": "pc" | "konsole" | "hardware" | "industrie",
  "game": "gta" | "minecraft" | "fortnite" | "cod" | "valorant" | "fifa" | null,
  "summary": "2-4 Sätze: worum es bei diesem Gerücht insgesamt geht und was aktuell der Gesamtstand ist — wird bei jedem künftigen Update überschrieben, muss also für sich stehen können.",
  "entry_text": "2-4 Sätze: was genau ist JETZT neu aufgetaucht — der allererste Zeitleisten-Eintrag dieses Trackers.",
  "credibility_category": "unbestaetigt" | "wahrscheinlich" | "sehr_wahrscheinlich" | "bestaetigt" | "dementiert",
  "credibility_pct": <Zahl 0-100>,
  "image_url": "<direkte Bild-URL oder null>"
}

Setze "game" nur bei eindeutigem Bezug zu GTA, Minecraft, Fortnite, Call of \
Duty, Valorant/League of Legends oder FIFA/EA Sports FC, sonst null.
"""


def create_tracker(entry, existing_ids):
    user_prompt = f"""Ausgangsmeldung für den neuen Gerüchte-Tracker:
Titel: {entry['title']}
Kurzbeschreibung: {entry['summary'][:600]}
Quelle: {entry['source']}
Original-Link: {entry['link']}"""

    response = npl.client.messages.create(
        model=WRITE_MODEL,
        max_tokens=2200,
        system=CREATE_TRACKER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
    )

    text_blocks = [block.text for block in response.content if block.type == "text"]
    if not text_blocks:
        print(f"  ! Keine Textantwort für neuen Tracker: {entry['title']}", file=sys.stderr)
        return None

    raw_text = text_blocks[-1].strip()
    raw_text = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    first_brace = raw_text.find("{")
    if first_brace > 0:
        raw_text = raw_text[first_brace:]

    try:
        data = json.loads(raw_text, strict=False)
    except json.JSONDecodeError as e:
        print(f"  ! Konnte neuen Tracker nicht parsen: {entry['title']} — {e.msg}", file=sys.stderr)
        return None

    topic_name = (data.get("topic_name") or entry["title"]).strip()
    entry_text = (data.get("entry_text") or "").strip()
    if not entry_text:
        print(f"  ! Modell lieferte leeren Zeitleisten-Text für neuen Tracker: {topic_name} — verworfen.", file=sys.stderr)
        return None

    cat = data.get("cat")
    if cat not in VALID_CATS:
        cat = "industrie"
    game = data.get("game")
    if game is not None and game not in VALID_GAMES:
        game = None

    credibility_category = _valid_credibility_category(data.get("credibility_category"))
    credibility_pct = _clamp_pct(data.get("credibility_pct"))

    image = data.get("image_url")
    if not image or not npl.is_valid_image_url(image):
        candidate = npl.fetch_og_image(entry["link"])
        image = candidate if candidate and npl.is_valid_image_url(candidate) else None
    if not image:
        seed = re.sub(r"[^a-zA-Z0-9]", "", topic_name) or "geruecht"
        image = f"https://picsum.photos/seed/loadout-rumor-{seed}/900/500"

    tracker_id = unique_tracker_id(topic_name, existing_ids)
    today_str = datetime.date.today().strftime("%d. %B %Y")

    return {
        "id": tracker_id,
        "topic_name": topic_name,
        "title": f"{topic_name} — Stand der Gerüchte",
        "cat": cat,
        "game": game,
        "summary": (data.get("summary") or "").strip(),
        "status": "aktiv",
        "resolution": None,
        "credibility_category": credibility_category,
        "credibility_pct": credibility_pct,
        "image": image,
        "created_date": today_str,
        "updated_date": today_str,
        "timeline": [
            {
                "date": today_str,
                "text": entry_text,
                "credibility_category": credibility_category,
                "credibility_pct": credibility_pct,
                "source": entry["source"],
                "source_url": entry["link"],
            }
        ],
    }


# --- Stufe 2b: Bestehenden Tracker mit neuem Eintrag fortführen -----------

UPDATE_TRACKER_SYSTEM_PROMPT = """Du bist Redakteur:in bei LOADOUT. Du führst einen bereits \
laufenden "Gerüchte-Tracker" mit einer neuen Meldung fort — ergänzt die \
Zeitleiste um einen weiteren Eintrag, statt einen neuen Artikel zu schreiben.

Bisheriger Gesamtstand des Trackers "{topic_name}":
{summary}

Bisherige Zeitleiste (neueste zuerst):
{recent_entries_block}

Regeln:
- ABSOLUT ENTSCHEIDEND: Alle Textfelder zu 100 % auf Deutsch. Keine \
englischen Sätze/Satzteile. Eigennamen im Original.
- Recherchiere aktiv mit der Websuche, was die neue Meldung wirklich \
bestätigt/ergänzt/widerlegt — nicht nur die eine gegebene Quelle.
- "entry_text" ist NUR der neue Zeitleisten-Eintrag (was ist JETZT neu),
  "updated_summary" ist der KOMPLETTE, aktualisierte Gesamtstand (ersetzt \
den bisherigen summary-Text vollständig, muss also für sich allein stehen).
- Passe "credibility_category"/"credibility_pct" an den NEUEN Gesamtstand \
an — kann rauf UND runter gehen, je nachdem ob die neue Info das Gerücht \
stützt oder in Zweifel zieht.
- Setze "resolved" NUR auf true, wenn diese neue Meldung das Gerücht \
EINDEUTIG offiziell bestätigt ODER eindeutig offiziell dementiert (nicht \
schon bei einer weiteren, nur etwas glaubwürdigeren Spekulation). Ist es \
bestätigt: "resolution": "bestaetigt", credibility_category ebenfalls \
"bestaetigt". Ist es dementiert: "resolution": "dementiert", \
credibility_category ebenfalls "dementiert". Sonst "resolved": false und \
"resolution": null.
- Antworte AUSSCHLIESSLICH mit einem validen JSON-Objekt, keine \
Erklärungen, kein Markdown, keine Code-Fences.
- WICHTIG für gültiges JSON: NIEMALS gerade doppelte Anführungszeichen \
innerhalb der Textfelder, keine rohen Zeilenumbrüche innerhalb eines Feldes.

JSON-Format:
{{
  "updated_summary": "...",
  "entry_text": "...",
  "credibility_category": "unbestaetigt" | "wahrscheinlich" | "sehr_wahrscheinlich" | "bestaetigt" | "dementiert",
  "credibility_pct": <Zahl 0-100>,
  "resolved": true | false,
  "resolution": "bestaetigt" | "dementiert" | null
}}
"""


def apply_update(tracker, entry):
    recent_entries = tracker.get("timeline", [])[:3]  # neueste zuerst gespeichert, siehe apply_update-Aufrufer
    recent_block = "\n".join(
        f"- ({t.get('date', '?')}, {CREDIBILITY_META.get(t.get('credibility_category'), {}).get('label', '?')} {t.get('credibility_pct', '?')}%): {t.get('text', '')}"
        for t in recent_entries
    ) or "(noch kein früherer Eintrag)"

    system_prompt = UPDATE_TRACKER_SYSTEM_PROMPT.format(
        topic_name=tracker["topic_name"],
        summary=tracker.get("summary", ""),
        recent_entries_block=recent_block,
    )
    user_prompt = f"""Neue Meldung:
Titel: {entry['title']}
Kurzbeschreibung: {entry['summary'][:600]}
Quelle: {entry['source']}
Original-Link: {entry['link']}"""

    response = npl.client.messages.create(
        model=WRITE_MODEL,
        max_tokens=1800,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}],
    )

    text_blocks = [block.text for block in response.content if block.type == "text"]
    if not text_blocks:
        print(f"  ! Keine Textantwort für Tracker-Update: {tracker['topic_name']}", file=sys.stderr)
        return False

    raw_text = text_blocks[-1].strip()
    raw_text = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    first_brace = raw_text.find("{")
    if first_brace > 0:
        raw_text = raw_text[first_brace:]

    try:
        data = json.loads(raw_text, strict=False)
    except json.JSONDecodeError as e:
        print(f"  ! Konnte Tracker-Update nicht parsen: {tracker['topic_name']} — {e.msg}", file=sys.stderr)
        return False

    entry_text = (data.get("entry_text") or "").strip()
    if not entry_text:
        print(f"  ! Modell lieferte leeren Zeitleisten-Text für Update: {tracker['topic_name']} — verworfen.", file=sys.stderr)
        return False

    credibility_category = _valid_credibility_category(data.get("credibility_category"), tracker.get("credibility_category", "unbestaetigt"))
    credibility_pct = _clamp_pct(data.get("credibility_pct"), tracker.get("credibility_pct", 30))
    today_str = datetime.date.today().strftime("%d. %B %Y")

    new_timeline_entry = {
        "date": today_str,
        "text": entry_text,
        "credibility_category": credibility_category,
        "credibility_pct": credibility_pct,
        "source": entry["source"],
        "source_url": entry["link"],
    }
    # Neueste zuerst speichern (praktisch für Anzeige & für recent_entries oben)
    tracker["timeline"].insert(0, new_timeline_entry)
    tracker["summary"] = (data.get("updated_summary") or tracker.get("summary", "")).strip()
    tracker["credibility_category"] = credibility_category
    tracker["credibility_pct"] = credibility_pct
    tracker["updated_date"] = today_str

    resolved = bool(data.get("resolved"))
    resolution = data.get("resolution")
    if resolved and resolution in {"bestaetigt", "dementiert"}:
        tracker["status"] = "abgeschlossen"
        tracker["resolution"] = resolution
        print(f"  ✓ Tracker '{tracker['topic_name']}' als ABGESCHLOSSEN markiert ({resolution}).")

    return True


def main():
    trackers = load_json(RUMORS_FILE, [])
    checked_links = set(load_json(CHECKED_FILE, []))
    state = get_today_state()

    active_trackers = [t for t in trackers if t.get("status") == "aktiv"]
    all_tracker_ids = {t["id"] for t in trackers}

    # Cross-Pipeline-Dedup (siehe classify_and_match: covered_article_titles):
    # lädt die zeitlich jüngsten Titel bereits veröffentlichter REGULÄRER
    # Artikel (articles.json + archive.json, dieselben Dateien wie
    # news_pipeline.py) — verhindert, dass ein Thema gleichzeitig als
    # Gerüchte-Tracker UND als normaler, bestätigter Artikel läuft. Beide
    # Pipelines laufen sonst komplett unabhängig voneinander.
    regular_articles = load_json(npl.ARTICLES_FILE, [])
    regular_archive = load_json(npl.ARCHIVE_FILE, [])
    cutoff = datetime.date.today() - datetime.timedelta(days=ARTICLE_DEDUP_DAYS)
    covered_article_titles = [
        a.get("source_title", a.get("title", ""))
        for a in (regular_articles + regular_archive)
        if (_parse_article_date(a) is None) or (_parse_article_date(a) >= cutoff)
    ]

    print("→ Lese RSS-Feeds für Gerüchte-Prüfung...")
    raw_entries = npl.fetch_raw_entries()

    candidate_pool = [e for e in raw_entries if e["link"] not in checked_links][:CHECK_BATCH_SIZE]
    if not candidate_pool:
        print("→ Keine neuen, noch ungeprüften Meldungen gefunden.")
        return

    print(f"→ {len(candidate_pool)} neue Meldung(en) werden auf Gerüchte-Relevanz geprüft "
          f"(gegen {len(active_trackers)} laufende Tracker, {len(covered_article_titles)} "
          f"kürzlich veröffentlichte reguläre Artikel)...")
    decisions = classify_and_match(candidate_pool, active_trackers, covered_article_titles)

    checked_links |= {e["link"] for e in candidate_pool}
    save_json(CHECKED_FILE, sorted(checked_links))

    if not decisions:
        print("→ Nichts davon ist ein relevantes, neues Gerücht — normaler Fall, nichts zu tun.")
        return

    updates_done = 0
    new_created = 0
    changed = False

    for decision in decisions:
        entry = candidate_pool[decision["index"]]

        if decision["action"] == "update":
            if updates_done >= MAX_UPDATES_PER_RUN:
                continue
            tracker = next((t for t in trackers if t["id"] == decision["tracker_id"]), None)
            if not tracker:
                continue
            print(f"  ↻ Aktualisiere Tracker '{tracker['topic_name']}' mit: {entry['title'][:60]}")
            if apply_update(tracker, entry):
                updates_done += 1
                changed = True

        elif decision["action"] == "new":
            if new_created >= MAX_NEW_TRACKERS_PER_RUN or state["count"] >= MAX_NEW_TRACKERS_PER_DAY:
                print(f"  ⚠ Obergrenze für neue Tracker erreicht (Lauf: {new_created}/{MAX_NEW_TRACKERS_PER_RUN}, "
                      f"heute: {state['count']}/{MAX_NEW_TRACKERS_PER_DAY}) — '{entry['title'][:60]}' übersprungen.")
                continue
            print(f"  ★ Eröffne neuen Tracker für: {entry['title'][:60]}")
            new_tracker = create_tracker(entry, all_tracker_ids)
            if new_tracker:
                trackers.insert(0, new_tracker)
                all_tracker_ids.add(new_tracker["id"])
                new_created += 1
                state["count"] += 1
                changed = True
            else:
                print("    ⚠ Eröffnen fehlgeschlagen — übersprungen.")

    if not changed:
        print("→ Keine Änderungen an rumors.json (alle Kandidaten übersprungen/fehlgeschlagen).")
        return

    save_json(RUMORS_FILE, trackers)
    save_json(STATE_FILE, state)

    print(f"✓ {new_created} neue(r) Tracker eröffnet, {updates_done} bestehende(r) Tracker aktualisiert. "
          f"{len(trackers)} Tracker insgesamt in {RUMORS_FILE}.")


if __name__ == "__main__":
    main()
