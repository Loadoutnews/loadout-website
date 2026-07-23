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
import datetime

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
    if a.get("editorial_take"):
        body_html += f'''
        <div class="editorial-box">
          <div class="editorial-label mono">🗣️ Einschätzung der Redaktion</div>
          <p>{html.escape(a["editorial_take"])}</p>
        </div>
        '''
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
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/logo-icon-192.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="LOADOUT-NEWS">
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
  <div class="ad-slot ad-header">
    <span class="ad-tag mono">Anzeige</span>
    <ins class="adsbygoogle" data-placement="leaderboard" style="display:block; width:100%; min-height:90px;"></ins>
  </div>

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

        <div class="reaction-bar">
          <button class="reaction-btn" id="likeBtn" onclick="react('like')">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 10v12M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2h0a3.13 3.13 0 0 1 3 3.88Z"/></svg>
            <span id="likeCount">0</span>
          </button>
          <button class="reaction-btn" id="dislikeBtn" onclick="react('dislike')">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 14V2M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L13 22h0a3.13 3.13 0 0 1-3-3.88Z"/></svg>
            <span id="dislikeCount">0</span>
          </button>
        </div>

        <div class="comments-section">
          <h3 class="mono">💬 Was denkst du dazu?</h3>
          <p class="comments-hint">Lass uns gerne wissen, was du zu dieser Meldung meinst — sei dabei fair und respektvoll.</p>
          <div class="comment-form">
            <input type="text" id="commentName" placeholder="Name (optional)" maxlength="40">
            <textarea id="commentText" placeholder="Deine Meinung..." maxlength="500" rows="3"></textarea>
            <input type="text" id="commentWebsite" name="website" class="honeypot" tabindex="-1" autocomplete="off">
            <button class="cookie-btn primary" onclick="submitComment()">Kommentar absenden</button>
          </div>
          <div id="commentsList"></div>
        </div>
      </div>
    </div>

    <aside class="sidebar">
      <div class="ad-slot ad-sidebar"><span class="ad-tag mono">Anzeige</span>Werbeplatz · 300×250</div>
    </aside>
  </div>

  <div class="ad-slot ad-footer">
    <span class="ad-tag mono">Anzeige</span>
    <ins class="adsbygoogle" data-placement="leaderboard" style="display:block; width:100%; min-height:90px;"></ins>
  </div>
</main>

<footer>
  <div class="footer-links mono">
    <a href="../index.html">Zur Startseite</a>
    <a href="../impressum.html">Impressum</a>
    <a href="../datenschutz.html">Datenschutz</a>
    <a href="#" onclick="openCookieSettings(); return false;">Cookie-Einstellungen</a>
    <span>© 2026 LOADOUT-NEWS</span>
  </div>
</footer>

<div class="cookie-banner" id="cookieBanner">
  <div class="cookie-text">
    <b>Wir verwenden Cookies.</b> Notwendige Cookies sind für den Betrieb der Seite
    erforderlich. Mit deiner Einwilligung nutzen wir zusätzlich Cookies für Reichweitenmessung
    und personalisierte Werbung. Mehr dazu in unserer <a href="../datenschutz.html">Datenschutzerklärung</a>.
  </div>
  <div class="cookie-actions">
    <button class="cookie-btn ghost" onclick="setCookieConsent(false)">Nur Notwendige</button>
    <button class="cookie-btn ghost" onclick="showCookieDetails()">Einstellungen</button>
    <button class="cookie-btn primary" onclick="setCookieConsent(true)">Alle akzeptieren</button>
  </div>
</div>

<div id="cookieDetailModal" class="cookie-modal">
  <div class="cookie-modal-box">
    <h3 class="display">Cookie-Einstellungen</h3>
    <div class="cookie-option">
      <div><b>Notwendig</b><span class="cookie-always">Immer aktiv</span></div>
      <p>Erforderlich für Grundfunktionen wie Navigation und Merkliste. Kann nicht deaktiviert werden.</p>
    </div>
    <div class="cookie-option">
      <div><b>Reichweitenmessung</b><label class="switch"><input type="checkbox" id="consentAnalytics"><span class="slider"></span></label></div>
      <p>Hilft zu verstehen, welche Artikel gelesen werden, um das Angebot zu verbessern.</p>
    </div>
    <div class="cookie-option">
      <div><b>Werbung / Personalisierung</b><label class="switch"><input type="checkbox" id="consentMarketing"><span class="slider"></span></label></div>
      <p>Wird für die Anzeigenplätze auf dieser Seite verwendet, sobald diese aktiv geschaltet sind.</p>
    </div>
    <div class="cookie-actions" style="margin-top:18px;">
      <button class="cookie-btn ghost" onclick="closeCookieDetails()">Abbrechen</button>
      <button class="cookie-btn primary" onclick="saveCookieDetails()">Auswahl speichern</button>
    </div>
  </div>
</div>

<script>
  // --- Cookie-Consent (dieselbe Logik/Speicherung wie auf der Startseite,
  // damit eine einmal getroffene Wahl seitenübergreifend gilt) -----------
  let cookieConsent = null;
  let consentDetails = {{ analytics: false, marketing: false }};
  try {{
    cookieConsent = localStorage.getItem('loadout_cookieConsent');
    const storedDetails = localStorage.getItem('loadout_consentDetails');
    if(storedDetails) consentDetails = JSON.parse(storedDetails);
  }} catch(e) {{}}

  function persistConsent(){{
    try {{
      localStorage.setItem('loadout_cookieConsent', cookieConsent);
      localStorage.setItem('loadout_consentDetails', JSON.stringify(consentDetails));
    }} catch(e) {{}}
  }}

  function initCookieBanner(){{
    if(cookieConsent === null){{
      document.getElementById('cookieBanner').classList.add('visible');
    }} else {{
      applyConsent();
    }}
  }}

  function setCookieConsent(acceptAll){{
    cookieConsent = acceptAll ? 'all' : 'necessary';
    consentDetails = acceptAll ? {{ analytics: true, marketing: true }} : {{ analytics: false, marketing: false }};
    persistConsent();
    document.getElementById('cookieBanner').classList.remove('visible');
    applyConsent();
  }}

  function showCookieDetails(){{
    document.getElementById('consentAnalytics').checked = consentDetails.analytics;
    document.getElementById('consentMarketing').checked = consentDetails.marketing;
    document.getElementById('cookieDetailModal').classList.add('visible');
  }}

  function closeCookieDetails(){{
    document.getElementById('cookieDetailModal').classList.remove('visible');
  }}

  function saveCookieDetails(){{
    const analytics = document.getElementById('consentAnalytics').checked;
    const marketing = document.getElementById('consentMarketing').checked;
    cookieConsent = (analytics || marketing) ? 'custom' : 'necessary';
    consentDetails = {{ analytics, marketing }};
    persistConsent();
    document.getElementById('cookieDetailModal').classList.remove('visible');
    document.getElementById('cookieBanner').classList.remove('visible');
    applyConsent();
  }}

  function openCookieSettings(){{
    showCookieDetails();
  }}

  // --- Google Analytics (GA4) — dieselbe Mess-ID wie in index.html ------
  const GA_MEASUREMENT_ID = 'G-XXXXXXXXXX';
  let analyticsLoaded = false;

  function loadGoogleAnalytics(){{
    if(analyticsLoaded || !GA_MEASUREMENT_ID || GA_MEASUREMENT_ID.includes('XXXX')) return;
    analyticsLoaded = true;
    const script = document.createElement('script');
    script.src = `https://www.googletagmanager.com/gtag/js?id=${{GA_MEASUREMENT_ID}}`;
    script.async = true;
    document.head.appendChild(script);
    window.dataLayer = window.dataLayer || [];
    window.gtag = function(){{ window.dataLayer.push(arguments); }};
    window.gtag('js', new Date());
    window.gtag('config', GA_MEASUREMENT_ID);
  }}

  // --- Google AdSense — dieselben IDs wie in index.html eintragen -------
  const ADSENSE_CLIENT_ID = 'ca-pub-8080055429345245';
  const AD_PLACEMENTS = {{
    leaderboard: {{ slot: 'HIER_SLOT_ID_LEADERBOARD', format: 'horizontal' }},
  }};
  let adsenseLoaded = false;

  function loadAdSense(){{
    if(adsenseLoaded || !ADSENSE_CLIENT_ID || ADSENSE_CLIENT_ID.includes('XXXX')) return;
    adsenseLoaded = true;
    const script = document.createElement('script');
    script.async = true;
    script.src = `https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${{ADSENSE_CLIENT_ID}}`;
    script.crossOrigin = 'anonymous';
    script.onload = initAdSlots;
    document.head.appendChild(script);
  }}

  function initAdSlots(){{
    if(!adsenseLoaded) return;
    document.querySelectorAll('ins.adsbygoogle:not([data-ads-initialized])').forEach(ins => {{
      const config = AD_PLACEMENTS[ins.dataset.placement];
      if(!config || !config.slot || config.slot.includes('HIER_')) return;
      ins.setAttribute('data-ad-client', ADSENSE_CLIENT_ID);
      ins.setAttribute('data-ad-slot', config.slot);
      ins.setAttribute('data-ad-format', config.format);
      ins.setAttribute('data-full-width-responsive', 'true');
      ins.setAttribute('data-ads-initialized', 'true');
      try {{ (window.adsbygoogle = window.adsbygoogle || []).push({{}}); }} catch(e) {{}}
    }});
  }}

  function applyConsent(){{
    if(consentDetails.analytics) loadGoogleAnalytics();
    if(consentDetails.marketing) loadAdSense();
  }}

  initCookieBanner();

  // PWA: Service Worker registrieren (funktioniert von jeder Seite aus,
  // Pfad ist absolut).
  if("serviceWorker" in navigator){{
    window.addEventListener("load", () => {{
      navigator.serviceWorker.register("/sw.js").catch(() => {{}});
    }});
  }}
</script>

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

<script>
  // --- Reaktionen (Like/Dislike) -----------------------------------------
  const ARTICLE_ID = '{a['id']}';
  let myReactions = {{}};
  try {{ myReactions = JSON.parse(localStorage.getItem('loadout_reactions') || '{{}}'); }} catch(e) {{}}

  function updateReactionButtons(){{
    const mine = myReactions[ARTICLE_ID];
    document.getElementById('likeBtn').classList.toggle('active', mine === 'like');
    document.getElementById('dislikeBtn').classList.toggle('active', mine === 'dislike');
  }}

  fetch(`/api/react?articleId=${{encodeURIComponent(ARTICLE_ID)}}`)
    .then(res => res.json())
    .then(data => {{
      document.getElementById('likeCount').textContent = data.likes || 0;
      document.getElementById('dislikeCount').textContent = data.dislikes || 0;
      updateReactionButtons();
    }})
    .catch(() => {{}});

  function react(type){{
    if(myReactions[ARTICLE_ID]) return;
    fetch('/api/react', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ articleId: ARTICLE_ID, type }})
    }})
      .then(res => res.json())
      .then(data => {{
        document.getElementById(type === 'like' ? 'likeCount' : 'dislikeCount').textContent = data.count;
        myReactions[ARTICLE_ID] = type;
        try {{ localStorage.setItem('loadout_reactions', JSON.stringify(myReactions)); }} catch(e) {{}}
        updateReactionButtons();
      }})
      .catch(() => {{}});
  }}

  // --- Kommentare -----------------------------------------------------------
  function loadComments(){{
    fetch(`/api/comments?articleId=${{encodeURIComponent(ARTICLE_ID)}}`)
      .then(res => res.json())
      .then(data => renderComments(data.comments || []))
      .catch(() => {{ document.getElementById('commentsList').innerHTML = '<p class="comments-empty">Kommentare konnten nicht geladen werden.</p>'; }});
  }}

  function renderComments(comments){{
    const list = document.getElementById('commentsList');
    if(!comments.length){{
      list.innerHTML = '<p class="comments-empty">Noch keine Kommentare — sei die/der Erste!</p>';
      return;
    }}
    const sorted = [...comments].reverse();
    list.innerHTML = '';
    sorted.forEach(c => {{
      const item = document.createElement('div');
      item.className = 'comment-item';
      const head = document.createElement('div');
      head.className = 'comment-head';
      const name = document.createElement('span');
      name.className = 'comment-name';
      name.textContent = c.name || 'Anonym';
      const date = document.createElement('span');
      date.className = 'comment-date mono';
      try {{
        const d = new Date(c.timestamp);
        date.textContent = d.toLocaleDateString('de-CH', {{ day: '2-digit', month: '2-digit', year: 'numeric' }}) + ' · ' + d.toLocaleTimeString('de-CH', {{ hour: '2-digit', minute: '2-digit' }});
      }} catch(e) {{}}
      head.appendChild(name);
      head.appendChild(date);
      const text = document.createElement('div');
      text.className = 'comment-text';
      text.textContent = c.text || '';
      item.appendChild(head);
      item.appendChild(text);
      list.appendChild(item);
    }});
  }}

  function submitComment(){{
    const nameEl = document.getElementById('commentName');
    const textEl = document.getElementById('commentText');
    const websiteEl = document.getElementById('commentWebsite');
    const text = textEl.value.trim();
    if(!text) return;

    fetch('/api/comments', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ articleId: ARTICLE_ID, name: nameEl.value.trim(), text, website: websiteEl.value }})
    }})
      .then(res => res.ok ? res.json() : null)
      .then(data => {{
        if(!data) return;
        textEl.value = '';
        loadComments();
      }})
      .catch(() => {{}});
  }}

  loadComments();
</script>

</body>
</html>
"""


ARCHIVE_FILE = "archive.json"     # unbegrenztes Archiv, siehe news_pipeline.py


def build():
    # Seiten werden aus dem KOMPLETTEN Archiv erzeugt (nicht nur aus der für
    # die Startseite gekürzten articles.json) — so bleibt jeder je
    # geschriebene Artikel über seine eigene URL erreichbar und in der
    # Sitemap gelistet, auch wenn er von der Startseite verschwunden ist.
    source_file = ARCHIVE_FILE if os.path.exists(ARCHIVE_FILE) else ARTICLES_FILE
    if not os.path.exists(source_file):
        print(f"! Weder {ARCHIVE_FILE} noch {ARTICLES_FILE} gefunden — nichts zu bauen.")
        return

    with open(source_file, "r", encoding="utf-8") as f:
        articles = json.load(f)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    urls = [f"{SITE_URL}/index.html", f"{SITE_URL}/archiv.html",
            f"{SITE_URL}/impressum.html", f"{SITE_URL}/datenschutz.html", f"{SITE_URL}/app.html", f"{SITE_URL}/nutzungsbedingungen.html"]

    # Release- und Update-Kalender nur eintragen, wenn sie schon existieren
    # (beim allerersten Lauf, bevor die jeweiligen Skripte einmal gelaufen
    # sind, gäbe es sonst einen toten Link in der Sitemap).
    for optional_page in ["releases.html", "updates.html"]:
        if os.path.exists(optional_page):
            urls.append(f"{SITE_URL}/{optional_page}")

    for a in articles:
        page = render_article_page(a)
        path = os.path.join(OUTPUT_DIR, f"{a['id']}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(page)
        urls.append(f"{SITE_URL}/artikel/{a['id']}.html")

    # sitemap.xml — mit Aktualisierungsdatum (lastmod), damit Google
    # erkennen kann, dass die Sitemap bei jedem Pipeline-Lauf frisch ist,
    # was erneutes, zügigeres Crawlen begünstigt.
    today_iso = datetime.date.today().isoformat()
    sitemap = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        sitemap.append(f"  <url><loc>{u}</loc><lastmod>{today_iso}</lastmod></url>")
    sitemap.append("</urlset>")
    with open("sitemap.xml", "w", encoding="utf-8") as f:
        f.write("\n".join(sitemap))

    # archiv-index.json — eine schlanke Version des Archivs (ohne den
    # vollständigen Artikeltext) für die durchsuchbare Archiv-Seite, damit
    # sie auch bei tausenden Artikeln noch schnell lädt.
    archive_index = [
        {
            "id": a["id"], "title": a["title"], "teaser": a["teaser"],
            "cat": a["cat"], "game": a.get("game"), "genre": a.get("genre"), "date": a["date"],
            "hype": a.get("hype", 0),
        }
        for a in articles
    ]
    with open("archiv-index.json", "w", encoding="utf-8") as f:
        json.dump(archive_index, f, ensure_ascii=False, indent=2)

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
