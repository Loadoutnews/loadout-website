"""
LOADOUT-NEWS — Artikel manuell entfernen
=============================================
Einmal-Werkzeug für den Fall, dass ein fehlerhafter oder doppelter Artikel
manuell aus articles.json UND archive.json entfernt werden muss (z. B.
ein Duplikat, das trotz aller automatischen Prüfungen durchgerutscht ist).

Entfernt den Artikel mit der angegebenen ID sicher aus beiden JSON-Dateien
(kein manuelles Klammern-/Kommazählen nötig) und löscht die zugehörige
statische Artikel-Seite (/artikel/<id>.html), falls vorhanden.

WICHTIG, was dieses Skript NICHT tut:
- Es entfernt den Artikel NICHT aus social-posted.json — das ist
  absichtlich so: der Artikel wurde ja bereits gepostet, das soll auch so
  vermerkt bleiben (sonst würde ihn post_to_social.py beim nächsten Lauf
  fälschlich für "neu" halten).
- Es kann bereits veröffentlichte Social-Media-Posts (Discord, Bluesky,
  Instagram, Tumblr, Reddit) NICHT zurückziehen — das müsstest du manuell
  auf der jeweiligen Plattform machen, falls gewünscht.
- sitemap.xml wird nicht direkt angepasst — die wird beim nächsten Lauf
  von build_pages.py ohnehin komplett neu aus dem (jetzt bereinigten)
  archive.json erzeugt.

Ausführen (im selben Ordner wie articles.json/archive.json):
    python remove_article.py <artikel-id>

Beispiel:
    python remove_article.py bba01d2c68
"""

import json
import os
import sys

ARTICLES_FILE = "articles.json"
ARCHIVE_FILE = "archive.json"
ARTIKEL_DIR = "artikel"


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def remove_from_file(path, article_id):
    """Gibt (gefunden: bool, neuer_titel_falls_gefunden: str|None) zurück."""
    data = load_json(path)
    if data is None:
        print(f"  ℹ {path} nicht gefunden — übersprungen.")
        return False, None

    match = next((a for a in data if a.get("id") == article_id), None)
    if not match:
        print(f"  ℹ Kein Artikel mit ID '{article_id}' in {path} gefunden.")
        return False, None

    new_data = [a for a in data if a.get("id") != article_id]
    save_json(path, new_data)
    print(f"  ✓ Aus {path} entfernt ({len(data)} → {len(new_data)} Artikel): \"{match.get('title', '?')}\"")
    return True, match.get("title")


def main():
    if len(sys.argv) != 2:
        print("Nutzung: python remove_article.py <artikel-id>", file=sys.stderr)
        sys.exit(1)

    article_id = sys.argv[1].strip()
    if not article_id:
        print("! Leere ID übergeben.", file=sys.stderr)
        sys.exit(1)

    print(f"→ Entferne Artikel-ID '{article_id}' ...")

    found_articles, title1 = remove_from_file(ARTICLES_FILE, article_id)
    found_archive, title2 = remove_from_file(ARCHIVE_FILE, article_id)

    if not found_articles and not found_archive:
        print(f"! Artikel-ID '{article_id}' wurde in KEINER der beiden Dateien gefunden — nichts geändert.", file=sys.stderr)
        sys.exit(1)

    page_path = os.path.join(ARTIKEL_DIR, f"{article_id}.html")
    if os.path.exists(page_path):
        os.remove(page_path)
        print(f"  ✓ Statische Seite gelöscht: {page_path}")
    else:
        print(f"  ℹ Statische Seite {page_path} existierte nicht (nichts zu löschen).")

    print(f"\n✓ Fertig. Nicht vergessen: Änderungen committen und pushen, dann einmal")
    print(f"  build_pages.py laufen lassen, damit sitemap.xml den Eintrag auch verliert.")


if __name__ == "__main__":
    main()
