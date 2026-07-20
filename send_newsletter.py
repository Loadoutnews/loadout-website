"""
LOADOUT-NEWS — Wöchentlicher Newsletter-Versand
=================================================
Baut aus den aktuellsten Artikeln in articles.json eine E-Mail-Zusammenfassung
und verschickt sie automatisch über die Brevo-Kampagnen-API an die
Newsletter-Liste (BREVO_LIST_ID).

Setup:
    Als GitHub Secret hinterlegen (Repo → Settings → Secrets and variables
    → Actions):
        BREVO_API_KEY
        BREVO_LIST_ID
    (Das sind dieselben Werte, die auch bei Vercel als Umgebungsvariablen
    hinterlegt sind — hier aber zusätzlich als GitHub Secret, weil dieses
    Skript in GitHub Actions läuft, nicht auf Vercel.)

Ausführen:
    python send_newsletter.py
"""

import json
import os
import re
import sys
import datetime

import requests

ARTICLES_FILE = "articles.json"
ARTICLE_COUNT = 6          # wie viele Artikel pro Ausgabe im Newsletter stehen
SENDER_NAME = "LOADOUT-NEWS"
SENDER_EMAIL = "newsletter@loadout-news.com"
SITE_URL = "https://loadout-news.com"

CATS = {
    "pc": "PC",
    "konsole": "Konsolen",
    "hardware": "Hardware",
    "industrie": "Industrie",
}


def article_image(a):
    """Dieselbe Bild-Logik wie auf der Website: echtes Artikelbild, falls
    vorhanden, sonst ein lizenzfreies Picsum-Stimmungsfoto als Fallback."""
    if a.get("image"):
        return a["image"]
    return f"https://picsum.photos/seed/loadout-{a['id']}/240/180"


def load_releases_preview():
    """Lädt den aktuellen Release-Kalender, falls vorhanden, und bereitet
    eine kompakte Vorschau für den Newsletter auf."""
    if not os.path.exists("releases.json"):
        return None
    try:
        with open("releases.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        releases = data.get("releases", [])
        if not releases:
            return None
        top = max(releases, key=lambda r: r.get("hype", 0))
        return {
            "month": data.get("month", ""),
            "count": len(releases),
            "top_title": top.get("title", ""),
            "image": top.get("image") or "https://picsum.photos/seed/loadout-releases/300/200",
        }
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def load_updates_preview():
    """Lädt den aktuellen Update-Kalender, falls vorhanden, und bereitet
    eine kompakte Vorschau für den Newsletter auf."""
    if not os.path.exists("updates.json"):
        return None
    try:
        with open("updates.json", "r", encoding="utf-8") as f:
            updates = json.load(f)
        if not updates:
            return None
        next_update = min(updates, key=lambda u: u.get("update_date", "9999-99-99"))
        return {
            "count": len(updates),
            "next_game": next_update.get("game", ""),
            "next_title": next_update.get("update_title", ""),
            "next_date": next_update.get("update_date", ""),
            "image": next_update.get("image") or "https://picsum.photos/seed/loadout-updates/300/200",
        }
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def build_calendar_teasers_html(releases_preview, updates_preview):
    """Baut die zwei kompakten Vorschau-Kacheln für Release- und
    Update-Kalender — jede verlinkt direkt auf die jeweilige Kalender-Seite."""
    if not releases_preview and not updates_preview:
        return ""

    def teaser_cell(icon, label, title, subtitle, image, href):
        return f"""
        <td width="50%" valign="top" style="padding:4px;">
          <a href="{href}" style="display:block; text-decoration:none; background:#12162A; border-radius:12px; overflow:hidden; border:1px solid #1E2340;">
            <div style="height:70px; background:linear-gradient(160deg, rgba(52,217,201,0.25), rgba(15,19,48,0.9)), url('{image}') center/cover;"></div>
            <div style="padding:12px 14px;">
              <span style="font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:0.05em; color:#34D9C9; font-family:Arial,sans-serif;">{icon} {label}</span>
              <p style="margin:6px 0 2px; font-size:13px; font-weight:700; color:#ffffff; font-family:Arial,sans-serif; line-height:1.3;">{title}</p>
              <p style="margin:0; font-size:11.5px; color:#8D90AC; font-family:Arial,sans-serif; line-height:1.4;">{subtitle}</p>
            </div>
          </a>
        </td>
        """

    releases_cell = teaser_cell(
        "📅", "Release-Kalender",
        f"{releases_preview['count']} Releases im {releases_preview['month']}" if releases_preview else "",
        f"U. a. {releases_preview['top_title']}" if releases_preview else "",
        releases_preview["image"] if releases_preview else "",
        f"{SITE_URL}/releases.html",
    ) if releases_preview else '<td width="50%"></td>'

    updates_cell = teaser_cell(
        "🛠️", "Update-Kalender",
        f"{updates_preview['count']} angekündigte Updates" if updates_preview else "",
        f"Als Nächstes: {updates_preview['next_game']} — {updates_preview['next_title']}" if updates_preview else "",
        updates_preview["image"] if updates_preview else "",
        f"{SITE_URL}/updates.html",
    ) if updates_preview else '<td width="50%"></td>'

    return f"""
    <tr>
      <td style="padding:6px 26px 4px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
          <tr>
            {releases_cell}
            {updates_cell}
          </tr>
        </table>
      </td>
    </tr>
    """


def build_html(articles, releases_preview=None, updates_preview=None):
    """Baut die E-Mail als Tabellen-Layout mit ausschliesslich Inline-Styles
    — das ist bei E-Mails nötig, da viele Mail-Programme (v. a. Outlook,
    Gmail) externe/interne <style>-Blöcke, CSS-Verläufe und Hintergrundbilder
    ignorieren oder herausfiltern. Bilder werden deshalb als echte <img>-Tags
    eingebunden, nicht als CSS-Hintergrund."""
    rows = ""
    for a in articles:
        cat_label = CATS.get(a.get("cat"), "")
        img = article_image(a)
        rows += f"""
        <tr>
          <td style="padding:16px; background:#12162A; border-radius:12px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td width="96" valign="top" style="padding-right:16px;">
                  <a href="{SITE_URL}/artikel/{a['id']}.html">
                    <img src="{img}" width="96" height="96" alt=""
                         style="display:block; width:96px; height:96px; border-radius:10px; object-fit:cover; background:#1A1F38;">
                  </a>
                </td>
                <td valign="top">
                  <span style="display:inline-block; background:rgba(124,92,252,0.18); color:#B9A6FF; font-size:10.5px; font-weight:700; padding:3px 8px; border-radius:10px; text-transform:uppercase; letter-spacing:0.04em; font-family:Arial,sans-serif;">{cat_label}</span>
                  <h2 style="margin:8px 0 6px; font-size:16px; line-height:1.35; font-family:Arial,sans-serif;">
                    <a href="{SITE_URL}/artikel/{a['id']}.html" style="color:#ffffff; text-decoration:none;">{a['title']}</a>
                  </h2>
                  <p style="margin:0; font-size:13px; color:#9A9DB8; line-height:1.5; font-family:Arial,sans-serif;">{a['teaser']}</p>
                  <a href="{SITE_URL}/artikel/{a['id']}.html" style="display:inline-block; margin-top:8px; font-size:12.5px; font-weight:700; color:#FF4D8D; text-decoration:none; font-family:Arial,sans-serif;">Weiterlesen →</a>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        <tr><td style="height:14px; line-height:14px; font-size:0;">&nbsp;</td></tr>
        """

    today = datetime.date.today().strftime("%d.%m.%Y")

    return f"""<!DOCTYPE html>
<html lang="de" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<title>LOADOUT-NEWS Wochenrückblick</title>
</head>
<body style="margin:0; padding:0; background:#05060B;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#05060B; padding:32px 0;">
      <tr>
        <td align="center">
          <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background:#0A0C16; border-radius:16px; overflow:hidden; border:1px solid #1E2340;">

            <!-- Kopfbereich mit echtem Logo-Bild -->
            <tr>
              <td style="background:#0A0C16; padding:28px 30px 20px; border-bottom:1px solid #1E2340;">
                <table role="presentation" cellpadding="0" cellspacing="0">
                  <tr>
                    <td style="padding-right:10px;">
                      <img src="{SITE_URL}/logo-icon-512.png" width="36" height="36" alt="LOADOUT-NEWS"
                           style="display:block; width:36px; height:36px; border-radius:8px;">
                    </td>
                    <td style="font-family:Arial,sans-serif; font-size:20px; font-weight:800; color:#ffffff; vertical-align:middle;">
                      LOAD<span style="color:#FF4D8D;">OUT</span><span style="font-size:11px; color:#8D90AC; font-weight:700;">-NEWS</span>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- Titelzeile -->
            <tr>
              <td style="padding:26px 30px 6px;">
                <p style="font-size:11px; letter-spacing:0.08em; text-transform:uppercase; color:#7C5CFC; margin:0 0 8px; font-family:Arial,sans-serif; font-weight:700;">Wochenrückblick · {today}</p>
                <h1 style="font-size:23px; margin:0 0 22px; font-family:Arial,sans-serif; color:#ffffff; line-height:1.3;">Diese Woche bei LOADOUT-NEWS</h1>
              </td>
            </tr>

            <!-- Artikel-Karten -->
            <tr>
              <td style="padding:0 30px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                  {rows}
                </table>
              </td>
            </tr>

            <!-- Release- & Update-Kalender-Vorschau -->
            {build_calendar_teasers_html(releases_preview, updates_preview)}

            <!-- Call-to-Action -->
            <tr>
              <td style="padding:14px 30px 30px; text-align:center;">
                <a href="{SITE_URL}/index.html" style="display:inline-block; background:#7C5CFC; color:#ffffff; text-decoration:none; padding:13px 28px; border-radius:10px; font-weight:700; font-size:14px; font-family:Arial,sans-serif;">Alle Artikel ansehen →</a>
              </td>
            </tr>

            <!-- Footer -->
            <tr>
              <td style="padding:22px 30px; background:#080911; text-align:center; font-size:11.5px; color:#5C5F7A; font-family:Arial,sans-serif; border-top:1px solid #1E2340;">
                Du erhältst diese E-Mail, weil du dich für den LOADOUT-NEWS-Newsletter angemeldet hast.<br>
                <a href="{{{{ unsubscribe }}}}" style="color:#8D90AC;">Newsletter abbestellen</a>
                <p style="margin:12px 0 0; color:#4A4D66;">LOADOUT-NEWS · Marcel Mader · Meiershofstrasse 9 · 8600 Dübendorf · Schweiz</p>
              </td>
            </tr>

          </table>
        </td>
      </tr>
    </table>
</body>
</html>
"""


GERMAN_MONTHS = {
    "Januar": 1, "Februar": 2, "März": 3, "April": 4, "Mai": 5, "Juni": 6,
    "Juli": 7, "August": 8, "September": 9, "Oktober": 10, "November": 11, "Dezember": 12,
}


def parse_article_date(date_str):
    """Wandelt das deutsche Anzeigedatum (z. B. '17. Juli 2026') in ein
    echtes datetime.date um, damit sich Artikel nach Zeitraum filtern lassen."""
    match = re.match(r"(\d{1,2})\.\s*([A-Za-zäöüÄÖÜ]+)\s*(\d{4})", date_str or "")
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


def select_weekly_highlights(articles):
    """Wählt die gehyptesten Artikel der vergangenen 7 Tage aus — nicht
    einfach nur die neuesten, wie zuvor."""
    today = datetime.date.today()
    week_ago = today - datetime.timedelta(days=7)

    this_week = [a for a in articles if (d := parse_article_date(a.get("date"))) and week_ago <= d <= today]

    # Sicherheitsnetz: falls in einer ruhigen Woche zu wenige Artikel
    # erschienen sind, mit den nächstneuesten auffüllen, statt einen fast
    # leeren Newsletter zu verschicken.
    if len(this_week) < ARTICLE_COUNT:
        already_included = {a["id"] for a in this_week}
        fill_ups = [a for a in articles if a["id"] not in already_included]
        this_week += fill_ups[: ARTICLE_COUNT - len(this_week)]

    this_week.sort(key=lambda a: a.get("hype", 0), reverse=True)
    return this_week[:ARTICLE_COUNT]


def main():
    api_key = os.environ.get("BREVO_API_KEY")
    list_id = os.environ.get("BREVO_LIST_ID")

    if not api_key or not list_id:
        print("! BREVO_API_KEY oder BREVO_LIST_ID fehlt — Newsletter-Versand übersprungen.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(ARTICLES_FILE):
        print(f"! {ARTICLES_FILE} nicht gefunden.", file=sys.stderr)
        sys.exit(1)

    with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
        articles = json.load(f)

    if not articles:
        print("Keine Artikel vorhanden — kein Newsletter verschickt.")
        return

    # Statt einfach nur der neuesten Artikel: die gehyptesten Artikel der
    # vergangenen 7 Tage, wie gewünscht (echter "Wochenrückblick").
    top_articles = select_weekly_highlights(articles)
    releases_preview = load_releases_preview()
    updates_preview = load_updates_preview()
    html = build_html(top_articles, releases_preview, updates_preview)

    today_str = datetime.date.today().strftime("%d.%m.%Y")
    campaign_name = f"LOADOUT-NEWS Wochenrückblick {today_str}"
    subject = f"🎮 Diese Woche bei LOADOUT-NEWS ({today_str})"

    headers = {"Content-Type": "application/json", "api-key": api_key}

    create_payload = {
        "name": campaign_name,
        "subject": subject,
        "sender": {"name": SENDER_NAME, "email": SENDER_EMAIL},
        "type": "classic",
        "htmlContent": html,
        "recipients": {"listIds": [int(list_id)]},
    }

    print("→ Erstelle Kampagne bei Brevo …")
    resp = requests.post("https://api.brevo.com/v3/emailCampaigns", headers=headers, json=create_payload)

    if resp.status_code not in (200, 201):
        print(f"! Kampagne konnte nicht erstellt werden: {resp.status_code} {resp.text}", file=sys.stderr)
        sys.exit(1)

    campaign_id = resp.json().get("id")
    print(f"  Kampagne #{campaign_id} erstellt ({len(top_articles)} Artikel)")

    print("→ Sende Kampagne …")
    send_resp = requests.post(
        f"https://api.brevo.com/v3/emailCampaigns/{campaign_id}/sendNow",
        headers=headers,
    )

    if send_resp.status_code in (200, 201, 204):
        print(f"✓ Newsletter verschickt (Kampagne #{campaign_id})")
    else:
        print(f"! Versand fehlgeschlagen: {send_resp.status_code} {send_resp.text}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
