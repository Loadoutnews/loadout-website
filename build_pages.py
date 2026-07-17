"""
LOADOUT — Statischer Seiten-Generator
======================================
Erzeugt für jeden Artikel in articles.json eine eigene, echte HTML-Seite
unter /artikel/{id}.html — mit korrekten Meta-Tags, Open-Graph-Daten und
schema.org-Strukturdaten. Das ist die Voraussetzung dafür, dass:

  - Google einzelne Artikel indexieren kann (nicht nur die Startseite)
  - Ein Artikel-Link in WhatsApp/Twitter/Discord eine echte Vorschau zeigt
  - Nutzer:innen einen Artikel direkt teilen/verlinken können
  - Der Zurück-Button im Browser korrekt funktioniert

Ausführen:
    python build_pages.py

Voraussetzung: articles.json muss im selben Ordner liegen (wird von
news_pipeline.py erzeugt/aktualisiert).

Ergebnis:
    /artikel/<id>.html   (eine Datei pro Artikel)
    sitemap.xml
    robots.txt
    ads.txt (Platzhalter, siehe README)
"""

import json
import os
import html

SITE_URL = "https://loadout-news.com"  # bereits auf die gewählte Domain eingestellt
OUTPUT_DIR = "artikel"
ARTICLES_FILE = "articles.json"

CATS = {
    "pc": "PC",
    "konsole": "Konsolen",
    "hardware": "Hardware",
    "industrie": "Industrie",
}
GAMES = {
    "gta": "GTA",
    "minecraft": "Minecraft",
    "fortnite": "Fortnite",
    "cod": "Call of Duty",
    "valorant": "Valorant / LoL",
    "fifa": "FIFA / EA Sports FC",
}


def article_image(article):
    if article.get("image"):
        return article["image"]
    return f"https://picsum.photos/seed/loadout-{article['id']}/900/500"


def render_article_page(a):
    cat_label = CATS.get(a["cat"], a["cat"])
    game_label = GAMES.get(a.get("game"), "") if a.get("game") else ""
    badge_label = cat_label + (f" · {game_label}" if game_label else "")
    body_html = "\n".join(f'<p class="body">{html.escape(p)}</p>' for p in a["body"])
    image = article_image(a)
    canonical = f"{SITE_URL}/artikel/{a['id']}.html"
    title = html.escape(a["title"])
    teaser = html.escape(a["teaser"])

    # schema.org NewsArticle — hilft Suchmaschinen, den Artikel korrekt
    # einzuordnen (Autor, Bild, Datum) und kann zu Rich-Snippets führen.
    json_ld = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": a["title"],
        "description": a["teaser"],
        "image": [image],
        "author": {"@type": "Organization", "name": "LOADOUT Redaktion"},
        "publisher": {
            "@type": "Organization",
            "name": "LOADOUT",
            "logo": {"@type": "ImageObject", "url": f"{SITE_URL}/favicon.png"},
        },
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
    }

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — LOADOUT</title>
<meta name="description" content="{teaser}">
<link rel="canonical" href="{canonical}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{teaser}">
<meta property="og:type" content="article">
<meta property="og:image" content="{image}">
<meta property="og:url" content="{canonical}">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#0A0C16">
<link rel="stylesheet" href="../styles.css">
<script type="application/ld+json">{json.dumps(json_ld, ensure_ascii=False)}</script>
</head>
<body>

<div class="nav-wrap">
  <nav>
    <div class="logo-lockup" onclick="location.href='../index.html'">
      <svg class="logo-icon" viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <defs>
          <linearGradient id="navMarkGradient" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#7C5CFC"/>
            <stop offset="100%" stop-color="#FF4D8D"/>
          </linearGradient>
        </defs>
        <rect width="120" height="120" rx="26" fill="#0A0C16"/>
        <rect x="24" y="24" width="14" height="68" rx="6" fill="url(#navMarkGradient)"/>
        <rect x="24" y="80" width="72" height="12" rx="6" fill="url(#navMarkGradient)"/>
        <rect x="44" y="62" width="12" height="18" rx="5" fill="url(#navMarkGradient)"/>
        <rect x="60" y="50" width="12" height="30" rx="5" fill="url(#navMarkGradient)"/>
        <rect x="76" y="36" width="12" height="44" rx="5" fill="url(#navMarkGradient)"/>
      </svg>
      <div class="logo-text display">LOAD<span>OUT</span><small class="mono">-NEWS</small></div>
    </div>
  </nav>
</div>

<main>
  <div class="ad-slot ad-header"><span class="ad-tag mono">Anzeige</span>Werbeplatz · 728×90</div>

  <div class="page-layout">
    <div class="content-col">
      <div class="detail active" style="display:block;">
        <a href="../index.html" class="back-btn mono" style="text-decoration:none; display:inline-flex;">← ZURÜCK ZUM FEED</a>
        <div class="detail-art" style="background:url('{image}') center/cover;"></div>
        <span class="badge {a['cat']}">{badge_label}</span>
        <h1 class="display">{title}</h1>
        <div class="byline">
          <div class="avatar"></div>
          <span>Redaktion LOADOUT · KI-unterstützt recherchiert, Fakten gegengeprüft</span>
        </div>
        <div class="detail-meta">
          <div class="hype">
            <span class="hype-label mono">Hype-Meter</span>
            <div class="hype-bar"><div class="hype-fill" style="width:{a['hype']}%"></div></div>
            <span class="hype-pct mono">{a['hype']}%</span>
          </div>
          <span class="mono" style="color:var(--muted); font-size:12px;">{html.escape(a['date'])} · {html.escape(a['platform'])} · <span id="viewCount"></span></span>
        </div>
        {body_html}
        <a href="{a['source']}" class="source-link" target="_blank" rel="noopener">Zur Originalquelle ({html.escape(a['sourceLabel'])}) →</a>
      </div>
    </div>

    <aside class="sidebar">
      <div class="ad-slot ad-sidebar"><span class="ad-tag mono">Anzeige</span>Werbeplatz · 300×250</div>
    </aside>
  </div>

  <div class="ad-slot ad-footer"><span class="ad-tag mono">Anzeige</span>Werbeplatz · 728×90</div>
</main>

<footer>
  <div class="footer-links mono">
    <a href="../index.html">Zur Startseite</a>
    <a href="../impressum.html">Impressum</a>
    <a href="../datenschutz.html">Datenschutz</a>
    <span>© 2026 LOADOUT</span>
  </div>
</footer>

<script>
  // Zählt einen echten Seitenaufruf für diesen Artikel — auch wenn jemand
  // direkt über einen geteilten Link oder eine Google-Suche hierher kommt,
  // nicht nur über die Startseite.
  fetch('/api/track-view', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ articleId: '{a['id']}' }})
  }})
    .then(res => res.json())
    .then(data => {{
      const el = document.getElementById('viewCount');
      if(el && data.views) el.textContent = '👁 ' + data.views.toLocaleString('de-CH') + (data.views === 1 ? ' Aufruf' : ' Aufrufe');
    }})
    .catch(() => {{}});
</script>

</body>
</html>
"""


def build():
    if not os.path.exists(ARTICLES_FILE):
        print(f"! {ARTICLES_FILE} nicht gefunden — nichts zu bauen.")
        return

    with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
        articles = json.load(f)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    urls = [f"{SITE_URL}/index.html"]
    for a in articles:
        page = render_article_page(a)
        path = os.path.join(OUTPUT_DIR, f"{a['id']}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(page)
        urls.append(f"{SITE_URL}/artikel/{a['id']}.html")

    # sitemap.xml
    sitemap = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        sitemap.append(f"  <url><loc>{u}</loc></url>")
    sitemap.append("</urlset>")
    with open("sitemap.xml", "w", encoding="utf-8") as f:
        f.write("\n".join(sitemap))

    # robots.txt
    robots = f"""User-agent: *
Allow: /

Sitemap: {SITE_URL}/sitemap.xml
"""
    with open("robots.txt", "w", encoding="utf-8") as f:
        f.write(robots)

    # ads.txt — Platzhalter; die echte Zeile bekommst du von deinem
    # Anzeigennetzwerk (z. B. Google AdSense) nach der Kontoeröffnung.
    if not os.path.exists("ads.txt"):
        with open("ads.txt", "w", encoding="utf-8") as f:
            f.write(
                "# Trage hier die Zeile ein, die dir dein Anzeigennetzwerk gibt, z. B.:\n"
                "# google.com, pub-0000000000000000, DIRECT, f08c47fec0942fa0\n"
            )

    print(f"✓ {len(articles)} Artikel-Seiten in /{OUTPUT_DIR} erzeugt")
    print(f"✓ sitemap.xml mit {len(urls)} URLs erzeugt")
    print("✓ robots.txt erzeugt")
    print("✓ ads.txt geprüft (Platzhalter, falls noch keine vorhanden war)")


if __name__ == "__main__":
    build()
