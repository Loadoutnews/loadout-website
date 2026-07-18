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
 
 
def build_html(articles):
    """Baut die E-Mail als Tabellen-Layout mit ausschliesslich Inline-Styles
    — das ist bei E-Mails nötig, da viele Mail-Programme (v. a. Outlook,
    Gmail) externe/interne <style>-Blöcke ignorieren oder herausfiltern."""
    rows = ""
    for a in articles:
        cat_label = CATS.get(a.get("cat"), "")
        rows += f"""
        <tr>
          <td style="padding:18px 0; border-bottom:1px solid #e5e5ea;">
            <span style="display:inline-block; background:#f1edff; color:#7C5CFC; font-size:11px; font-weight:700; padding:3px 8px; border-radius:10px; text-transform:uppercase; letter-spacing:0.04em; font-family:Arial,sans-serif;">{cat_label}</span>
            <h2 style="margin:10px 0 6px; font-size:18px; line-height:1.3; font-family:Arial,sans-serif;">
              <a href="{SITE_URL}/artikel/{a['id']}.html" style="color:#0A0C16; text-decoration:none;">{a['title']}</a>
            </h2>
            <p style="margin:0; font-size:14px; color:#555555; line-height:1.5; font-family:Arial,sans-serif;">{a['teaser']}</p>
            <a href="{SITE_URL}/artikel/{a['id']}.html" style="display:inline-block; margin-top:10px; font-size:13px; font-weight:600; color:#FF4D8D; text-decoration:none; font-family:Arial,sans-serif;">Weiterlesen →</a>
          </td>
        </tr>
        """
 
    today = datetime.date.today().strftime("%d.%m.%Y")
 
    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f7; padding:30px 0;">
      <tr>
        <td align="center">
          <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background:#ffffff; border-radius:12px; overflow:hidden;">
            <tr>
              <td style="background:#0A0C16; padding:24px 30px;">
                <span style="font-size:22px; font-weight:800; color:#ffffff; font-family:Arial,sans-serif;">LOAD<span style="color:#FF4D8D;">OUT</span><span style="font-size:12px; color:#8D90AC; font-weight:600;">-NEWS</span></span>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 30px 0;">
                <p style="font-size:13px; color:#8D90AC; margin:0 0 6px; font-family:Arial,sans-serif;">{today}</p>
                <h1 style="font-size:22px; margin:0 0 20px; font-family:Arial,sans-serif; color:#0A0C16;">Diese Woche bei LOADOUT-NEWS</h1>
              </td>
            </tr>
            <tr>
              <td style="padding:0 30px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                  {rows}
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 30px; text-align:center;">
                <a href="{SITE_URL}/index.html" style="display:inline-block; background:#7C5CFC; color:#ffffff; text-decoration:none; padding:12px 24px; border-radius:8px; font-weight:600; font-size:14px; font-family:Arial,sans-serif;">Alle Artikel ansehen</a>
              </td>
            </tr>
            <tr>
              <td style="padding:20px 30px; background:#f4f4f7; text-align:center; font-size:12px; color:#8D90AC; font-family:Arial,sans-serif;">
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
 
