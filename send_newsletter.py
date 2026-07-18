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
import sys
import datetime

import requests

ARTICLES_FILE = "articles.json"
ARTICLE_COUNT = 6          # wie viele Artikel pro Ausgabe im Newsletter stehen
SENDER_NAME = "LOADOUT-NEWS"
SENDER_EMAIL = "loadoutnews@gmail.com"
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


def build_html(articles):
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

    return f"""
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
              </td>
            </tr>

          </table>
        </td>
      </tr>
    </table>
    """


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

    # articles.json ist neueste zuerst sortiert (siehe news_pipeline.py) —
    # die ersten Einträge sind also automatisch die aktuellsten.
    top_articles = articles[:ARTICLE_COUNT]
    html = build_html(top_articles)

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
