"""
LOADOUT-NEWS — Ankündigungs-Mail bei neuem Release-Kalender
==============================================================
Wird automatisch ausgelöst, sobald releases.json auf dem main-Branch
aktualisiert wird — also genau dann, wenn der monatliche
Release-Kalender-Pull-Request geprüft und gemergt wurde und die neuen
Daten wirklich live auf der Website stehen. Verschickt eine kurze,
eigenständige Ankündigungs-Mail an die Newsletter-Liste — getrennt vom
wöchentlichen Wochenrückblick (send_newsletter.py).

Setup: dieselben GitHub Secrets wie send_newsletter.py
    BREVO_API_KEY
    BREVO_LIST_ID

Ausführen:
    python notify_releases.py
"""

import json
import os
import sys

import requests

from push_helper import send_push_notification

SITE_URL = "https://loadout-news.com"
SENDER_NAME = "LOADOUT-NEWS"
SENDER_EMAIL = "newsletter@loadout-news.com"


def build_html(month, releases):
    top = sorted(releases, key=lambda r: r.get("hype", 0), reverse=True)[:3]
    top_list_html = "".join(f"""
        <li style="margin-bottom:8px; font-family:Arial,sans-serif; color:#E9E8F5; font-size:14px;">
          <b>{r.get('title','')}</b> <span style="color:#8D90AC;">— {r.get('release_date','')}</span>
        </li>
    """ for r in top)

    image = (top[0].get("image") if top else None) or "https://picsum.photos/seed/loadout-releases/900/500"

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Neuer Release-Kalender — LOADOUT-NEWS</title>
</head>
<body style="margin:0; padding:0; background:#05060B;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#05060B; padding:32px 0;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background:#0A0C16; border-radius:16px; overflow:hidden; border:1px solid #1E2340;">
        <tr>
          <td style="background:#0A0C16; padding:24px 30px; border-bottom:1px solid #1E2340;">
            <span style="font-size:20px; font-weight:800; color:#ffffff; font-family:Arial,sans-serif;">LOAD<span style="color:#FF4D8D;">OUT</span><span style="font-size:11px; color:#8D90AC; font-weight:700;">-NEWS</span></span>
          </td>
        </tr>
        <tr>
          <td>
            <div style="height:200px; background:linear-gradient(160deg, rgba(124,92,252,0.35), rgba(15,19,48,0.9)), url('{image}') center/cover;"></div>
          </td>
        </tr>
        <tr>
          <td style="padding:28px 30px;">
            <p style="font-size:11px; letter-spacing:0.08em; text-transform:uppercase; color:#7C5CFC; margin:0 0 8px; font-family:Arial,sans-serif; font-weight:700;">📅 Neu online</p>
            <h1 style="font-size:22px; margin:0 0 14px; color:#ffffff; font-family:Arial,sans-serif;">Der Release-Kalender für {month} ist da!</h1>
            <p style="font-size:14px; color:#9A9DB8; font-family:Arial,sans-serif; line-height:1.6; margin:0 0 18px;">
              {len(releases)} grosse Spiele-Releases stehen diesen Monat an. Die meisterwarteten:
            </p>
            <ul style="padding-left:20px; margin:0 0 24px;">{top_list_html}</ul>
            <a href="{SITE_URL}/releases.html" style="display:inline-block; background:#7C5CFC; color:#ffffff; text-decoration:none; padding:13px 28px; border-radius:10px; font-weight:700; font-size:14px; font-family:Arial,sans-serif;">Kompletten Kalender ansehen →</a>
          </td>
        </tr>
        <tr>
          <td style="padding:20px 30px; background:#080911; text-align:center; font-size:11.5px; color:#5C5F7A; font-family:Arial,sans-serif; border-top:1px solid #1E2340;">
            Du erhältst diese E-Mail, weil du dich für den LOADOUT-NEWS-Newsletter angemeldet hast.<br>
            <a href="{{{{ unsubscribe }}}}" style="color:#8D90AC;">Newsletter abbestellen</a>
            <p style="margin:12px 0 0; color:#4A4D66;">LOADOUT-NEWS · Marcel Mader · Meiershofstrasse 9 · 8600 Dübendorf · Schweiz</p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""


def main():
    api_key = os.environ.get("BREVO_API_KEY")
    list_id = os.environ.get("BREVO_LIST_ID")
    if not api_key or not list_id:
        print("! BREVO_API_KEY oder BREVO_LIST_ID fehlt.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists("releases.json"):
        print("! releases.json nicht gefunden.", file=sys.stderr)
        sys.exit(1)

    with open("releases.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    releases = data.get("releases", [])
    month = data.get("month", "")
    if not releases:
        print("Keine Releases vorhanden — keine Ankündigung verschickt.")
        return

    html = build_html(month, releases)
    headers = {"Content-Type": "application/json", "api-key": api_key}
    payload = {
        "name": f"Release-Kalender-Hinweis {month}",
        "subject": f"📅 Neu: Der Release-Kalender für {month} ist online!",
        "sender": {"name": SENDER_NAME, "email": SENDER_EMAIL},
        "type": "classic",
        "htmlContent": html,
        "recipients": {"listIds": [int(list_id)]},
    }

    print("→ Erstelle Ankündigungs-Kampagne bei Brevo …")
    resp = requests.post("https://api.brevo.com/v3/emailCampaigns", headers=headers, json=payload)
    if resp.status_code not in (200, 201):
        print(f"! Kampagne konnte nicht erstellt werden: {resp.status_code} {resp.text}", file=sys.stderr)
        sys.exit(1)

    campaign_id = resp.json().get("id")
    send_resp = requests.post(f"https://api.brevo.com/v3/emailCampaigns/{campaign_id}/sendNow", headers=headers)
    if send_resp.status_code in (200, 201, 204):
        print(f"✓ Ankündigung verschickt (Kampagne #{campaign_id})")
    else:
        print(f"! Versand fehlgeschlagen: {send_resp.status_code} {send_resp.text}", file=sys.stderr)
        sys.exit(1)

    send_push_notification(
        title="📅 Neuer Release-Kalender ist online!",
        body=f"{len(releases)} grosse Releases für {month} — jetzt reinschauen.",
        url="/releases.html",
    )


if __name__ == "__main__":
    main()
