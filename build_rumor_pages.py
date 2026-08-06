"""
LOADOUT-NEWS — Leaks & Gerüchte-Tracker: Seiten-Generator
======================================================
Erzeugt aus rumors.json (siehe rumor_tracker.py):

  - /geruechte.html            — Übersichtsseite: aktive Tracker zuerst
                                  (nach letztem Update sortiert), dann
                                  abgeschlossene Tracker in einem eigenen
                                  Bereich darunter (bleiben einsehbar,
                                  wie besprochen).
  - /geruechte/<id>.html       — Eine dauerhafte Detail-Seite pro Gerücht,
                                  mit Glaubwürdigkeits-Anzeige (Kategorie +
                                  Prozentwert) und der kompletten Zeitleiste
                                  (neueste zuerst).

Bewusst als EIGENES, unabhängiges Skript (nicht in build_pages.py
integriert) — rührt die bestehende, bereits getestete Artikel-Seiten-
Generierung nicht an. Ergänzt sitemap.xml eigenständig um die neuen URLs
(liest die bestehende Datei, falls vorhanden, statt sie zu überschreiben).

Ausführen:
    python build_rumor_pages.py
"""

import datetime
import html
import json
import os
import re

SITE_URL = "https://loadout-news.com"
OUTPUT_DIR = "geruechte"
RUMORS_FILE = "rumors.json"
SITEMAP_FILE = "sitemap.xml"

CATS = {"pc": "PC", "konsole": "Konsolen", "hardware": "Hardware", "industrie": "Industrie"}
GAMES = {
    "gta": "GTA", "minecraft": "Minecraft", "fortnite": "Fortnite",
    "cod": "Call of Duty", "valorant": "Valorant / LoL", "fifa": "FIFA / EA Sports FC",
}

CREDIBILITY_META = {
    "unbestaetigt":        {"label": "Unbestätigt",        "color": "#8D90AC"},
    "wahrscheinlich":      {"label": "Wahrscheinlich",      "color": "#FFB74D"},
    "sehr_wahrscheinlich": {"label": "Sehr wahrscheinlich", "color": "#7C5CFC"},
    "bestaetigt":          {"label": "Bestätigt",           "color": "#34D9C9"},
    "dementiert":          {"label": "Dementiert",          "color": "#FF3B30"},
}
RESOLUTION_META = {
    "bestaetigt": {"label": "✓ Bestätigt", "color": "#34D9C9"},
    "dementiert": {"label": "✕ Dementiert", "color": "#FF3B30"},
}

GERMAN_MONTHS = {
    "Januar": 1, "Februar": 2, "März": 3, "April": 4, "Mai": 5, "Juni": 6,
    "Juli": 7, "August": 8, "September": 9, "Oktober": 10, "November": 11, "Dezember": 12,
}


def parse_german_date(date_str):
    if not date_str:
        return None
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


def credibility_badge_html(category, pct, size="normal"):
    meta = CREDIBILITY_META.get(category, CREDIBILITY_META["unbestaetigt"])
    pad = "6px 14px" if size == "normal" else "4px 10px"
    font_size = "13px" if size == "normal" else "11px"
    return (
        f'<span class="rumor-credibility-badge" '
        f'style="display:inline-flex; align-items:center; gap:6px; padding:{pad}; '
        f'border-radius:999px; background:{meta["color"]}22; border:1px solid {meta["color"]}66; '
        f'color:{meta["color"]}; font-weight:700; font-size:{font_size}; white-space:nowrap;">'
        f'<span style="width:7px; height:7px; border-radius:50%; background:{meta["color"]};"></span>'
        f'{html.escape(meta["label"])} · {int(pct)}%'
        f'</span>'
    )


def status_badge_html(tracker):
    if tracker.get("status") == "abgeschlossen":
        meta = RESOLUTION_META.get(tracker.get("resolution"), {"label": "Abgeschlossen", "color": "#8D90AC"})
        return (
            f'<span style="display:inline-flex; align-items:center; padding:6px 14px; border-radius:999px; '
            f'background:{meta["color"]}22; border:1px solid {meta["color"]}66; color:{meta["color"]}; '
            f'font-weight:700; font-size:13px;">{html.escape(meta["label"])}</span>'
        )
    return (
        '<span style="display:inline-flex; align-items:center; gap:6px; padding:6px 14px; border-radius:999px; '
        'background:rgba(124,92,252,0.15); border:1px solid rgba(124,92,252,0.4); color:#7C5CFC; '
        'font-weight:700; font-size:13px;">'
        '<span class="rumor-live-dot" style="width:7px; height:7px; border-radius:50%; background:#7C5CFC;"></span>'
        'Läuft noch</span>'
    )


def tracker_image(t):
    if t.get("image"):
        return t["image"]
    return f"https://picsum.photos/seed/loadout-rumor-{t['id']}/900/500"


SHARED_HEAD = """<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#0A0C16">
<link rel="manifest" href="__MANIFEST_HREF__">
<link rel="apple-touch-icon" href="__ICON_HREF__">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="LOADOUT-NEWS">
<link rel="stylesheet" href="__STYLES_HREF__">
<style>
  /* Seiten-eigene Ergänzungen für den Gerüchte-Tracker — bewusst hier statt
     in styles.css, um die bestehende, ungetestete Datei nicht anzufassen. */
  .rumor-list-card { display:block; text-decoration:none; color:inherit; background:var(--surface-1, #10131f);
    border:1px solid var(--line, #22263a); border-radius:16px; overflow:hidden; margin-bottom:16px;
    transition:border-color .15s; }
  .rumor-list-card:hover { border-color:#39406b; }
  .rumor-list-art { height:160px; background-size:cover; background-position:center; position:relative; }
  .rumor-list-body { padding:18px 20px; }
  .rumor-list-body h3 { margin:10px 0 6px; font-size:18px; }
  .rumor-list-meta { color:var(--muted, #8D90AC); font-size:12.5px; }
  .rumor-timeline-item { border-left:2px solid rgba(124,92,252,0.35); padding:2px 0 22px 22px; position:relative; }
  .rumor-timeline-item:last-child { padding-bottom:2px; }
  .rumor-timeline-item::before { content:""; position:absolute; left:-7px; top:4px; width:12px; height:12px;
    border-radius:50%; background:#7C5CFC; border:2px solid #0A0C16; }
  .rumor-timeline-date { color:var(--muted, #8D90AC); font-size:12px; margin-bottom:6px; }
  .rumor-timeline-text { color:var(--text, #E9E8F5); font-size:15px; line-height:1.6; margin-bottom:8px; }
  .rumor-timeline-source { font-size:12px; }
  .rumor-timeline-source a { color:#7C5CFC; text-decoration:none; }
  .rumor-section-head { display:flex; align-items:center; gap:10px; margin:36px 0 18px; }
  .rumor-section-head h2 { font-size:15px; letter-spacing:.02em; color:var(--muted, #8D90AC); }
  .rumor-section-head .rule { flex:1; height:1px; background:var(--line, #22263a); }
  .rumor-empty { color:var(--muted, #8D90AC); font-size:14px; padding:24px 0; }
  /* Logo-Wortmarke im eigenen Nav: exakt dieselben Farben wie auf der
     Startseite, aber HART gesetzt (inline, höchste Spezifität) statt sich
     auf ererbte .logo-text-Regeln zu verlassen — auf der Startseite steckt
     das Logo in einem <div onclick=...>, hier (eigene statische Seiten,
     kein SPA-Router) in einem echten <a href>-Link. Ein <a> ohne explizite
     Farbe kann vom Browser/Stylesheet eine eigene Link-Farbe bekommen, die
     sich an Kind-Elemente ohne eigene Farbregel vererbt (z. B. -NEWS) und
     dadurch genau das gemeldete "Logo in anderen Farben" verursacht hat.
     Deshalb hier alles explizit statt implizit. */
  .rumor-logo-link { text-decoration:none; color:var(--text, #E9E8F5); }
</style>"""

NAV_HTML = """<div class="nav-wrap">
  <nav>
    <a href="{root}index.html" class="logo-lockup rumor-logo-link">
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
      <div>
        <div class="logo-text display">
          <span style="color:var(--text, #E9E8F5);">LOAD</span><span style="color:var(--magenta, #FF4D8D);">OUT</span><small class="mono" style="color:var(--muted, #8D90AC); font-weight:500;">-NEWS</small>
        </div>
      </div>
    </a>
    <div class="nav-right">
      <a href="{root}index.html" class="xp-badge" style="text-decoration:none; color:var(--text);" title="Zurück zum Feed">← Feed</a>
    </div>
  </nav>
</div>"""

FOOTER_HTML = """<footer>
  <div class="footer-links mono">
    <a href="{root}index.html">Startseite</a>
    <a href="{root}archiv.html">Archiv</a>
    <a href="{root}ueber-uns.html">Über uns</a>
    <a href="{root}impressum.html">Impressum</a>
    <a href="{root}datenschutz.html">Datenschutz</a>
    <span>© {year} LOADOUT-NEWS</span>
  </div>
</footer>"""


def page_shell(title, description, canonical, root, body_html, extra_head=""):
    shared_head = (
        SHARED_HEAD
        .replace("__MANIFEST_HREF__", f"{root}manifest.webmanifest")
        .replace("__ICON_HREF__", f"{root}logo-icon-192.png")
        .replace("__STYLES_HREF__", f"{root}styles.css")
    )
    return f"""<!DOCTYPE html>
<html lang="de">
<head>
{shared_head}
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(description)}">
<link rel="canonical" href="{canonical}">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(description)}">
<meta property="og:type" content="website">
<meta property="og:url" content="{canonical}">
<meta name="twitter:card" content="summary_large_image">
{extra_head}
</head>
<body>
{NAV_HTML.format(root=root)}
<main>
<div class="page-layout">
<div class="content-col" style="max-width:820px; margin:0 auto; float:none;">
{body_html}
</div>
</div>
</main>
{FOOTER_HTML.format(root=root, year=datetime.date.today().year)}
</body>
</html>
"""


RUMOR_INDEX_JS = """<script>
const GAMES = {"gta":"GTA","minecraft":"Minecraft","fortnite":"Fortnite","cod":"Call of Duty","valorant":"Valorant / LoL","fifa":"FIFA / EA Sports FC"};
const CATS = {"pc":"PC","konsole":"Konsolen","hardware":"Hardware","industrie":"Industrie"};
const CREDIBILITY_META = {
  "unbestaetigt": {label:"Unbestätigt", color:"#8D90AC"},
  "wahrscheinlich": {label:"Wahrscheinlich", color:"#FFB74D"},
  "sehr_wahrscheinlich": {label:"Sehr wahrscheinlich", color:"#7C5CFC"},
  "bestaetigt": {label:"Bestätigt", color:"#34D9C9"},
  "dementiert": {label:"Dementiert", color:"#FF3B30"}
};
const RESOLUTION_META = {
  "bestaetigt": {label:"✓ Bestätigt", color:"#34D9C9"},
  "dementiert": {label:"✕ Dementiert", color:"#FF3B30"}
};
const GERMAN_MONTHS = {"Januar":0,"Februar":1,"März":2,"April":3,"Mai":4,"Juni":5,"Juli":6,"August":7,"September":8,"Oktober":9,"November":10,"Dezember":11};

const TRACKERS = __TRACKERS_JSON__;

let activeGame = "alle";
let activeCat = "alle";
let activeStatus = "alle";

function parseTrackerDate(dateStr){
  if(!dateStr) return 0;
  const m = dateStr.match(/(\\d{1,2})\\.\\s*([A-Za-zäöüÄÖÜ]+)\\s*(\\d{4})/);
  if(!m) return 0;
  const month = GERMAN_MONTHS[m[2]];
  if(month === undefined) return 0;
  return new Date(Number(m[3]), month, Number(m[1])).getTime();
}

function trackerImageUrl(t){
  return t.image || ("https://picsum.photos/seed/loadout-rumor-" + t.id + "/900/500");
}

function escapeHtml(str){
  const div = document.createElement('div');
  div.textContent = str || '';
  return div.innerHTML;
}

function credibilityBadgeHtml(category, pct){
  const meta = CREDIBILITY_META[category] || CREDIBILITY_META["unbestaetigt"];
  return '<span style="display:inline-flex; align-items:center; gap:6px; padding:4px 10px; border-radius:999px; background:' + meta.color + '22; border:1px solid ' + meta.color + '66; color:' + meta.color + '; font-weight:700; font-size:11px; white-space:nowrap;">' +
    '<span style="width:7px; height:7px; border-radius:50%; background:' + meta.color + ';"></span>' +
    escapeHtml(meta.label) + ' · ' + Number(pct || 0) + '%</span>';
}

function statusBadgeHtml(t){
  if(t.status === "abgeschlossen"){
    const meta = RESOLUTION_META[t.resolution] || {label:"Abgeschlossen", color:"#8D90AC"};
    return '<span style="display:inline-flex; align-items:center; padding:4px 10px; border-radius:999px; background:' + meta.color + '22; border:1px solid ' + meta.color + '66; color:' + meta.color + '; font-weight:700; font-size:11px;">' + escapeHtml(meta.label) + '</span>';
  }
  return '<span style="display:inline-flex; align-items:center; gap:6px; padding:4px 10px; border-radius:999px; background:rgba(124,92,252,0.15); border:1px solid rgba(124,92,252,0.4); color:#7C5CFC; font-weight:700; font-size:11px;">' +
    '<span style="width:7px; height:7px; border-radius:50%; background:#7C5CFC;"></span>Läuft noch</span>';
}

function renderChips(){
  const gameChips = document.getElementById('rumorGameChips');
  const games = [{key:"alle", label:"Alle Spiele"}].concat(Object.keys(GAMES).map(k => ({key:k, label:GAMES[k]})));
  gameChips.innerHTML = games.map(g =>
    '<button class="chip ' + (activeGame===g.key?'active':'') + '" onclick="setRumorGame(\\'' + g.key + '\\')">' + escapeHtml(g.label) + '</button>'
  ).join('');

  const catChips = document.getElementById('rumorCatChips');
  const cats = [{key:"alle", label:"Alle Kategorien"}].concat(Object.keys(CATS).map(k => ({key:k, label:CATS[k]})));
  catChips.innerHTML = cats.map(c =>
    '<button class="chip ' + (activeCat===c.key?'active':'') + '" onclick="setRumorCat(\\'' + c.key + '\\')">' + escapeHtml(c.label) + '</button>'
  ).join('');

  const statusChips = document.getElementById('rumorStatusChips');
  const statuses = [{key:"alle", label:"Alle"}, {key:"aktiv", label:"Läuft noch"}, {key:"abgeschlossen", label:"Abgeschlossen"}];
  statusChips.innerHTML = statuses.map(s =>
    '<button class="chip ' + (activeStatus===s.key?'active':'') + '" onclick="setRumorStatus(\\'' + s.key + '\\')">' + escapeHtml(s.label) + '</button>'
  ).join('');
}

function renderGrid(){
  const filtered = TRACKERS.filter(t =>
    (activeGame === "alle" || t.game === activeGame) &&
    (activeCat === "alle" || t.cat === activeCat) &&
    (activeStatus === "alle" || t.status === activeStatus)
  );

  // Läuft noch zuerst, dann jeweils nach letztem Update absteigend —
  // so bleibt bei "Alle" sofort sichtbar, was gerade aktiv ist, auch
  // wenn abgeschlossene Gerüchte zum selben Spiel mitgelistet werden.
  filtered.sort((a, b) => {
    if(a.status !== b.status) return a.status === "aktiv" ? -1 : 1;
    return parseTrackerDate(b.updated_date) - parseTrackerDate(a.updated_date);
  });

  const grid = document.getElementById('rumorGrid');
  const empty = document.getElementById('rumorEmpty');

  if(filtered.length === 0){
    grid.innerHTML = "";
    empty.style.display = "block";
    return;
  }
  empty.style.display = "none";

  grid.innerHTML = filtered.map(t => {
    const catLabel = CATS[t.cat] || t.cat || "";
    const gameLabel = t.game ? (GAMES[t.game] || "") : "";
    const badgeLine = catLabel + (gameLabel ? " · " + gameLabel : "");
    let excerpt = t.summary || "";
    if(excerpt.length > 160) excerpt = excerpt.slice(0, 157).trimEnd() + "…";
    const entryCount = t.entry_count || 0;
    return '<a href="geruechte/' + t.id + '.html" class="rumor-list-card">' +
      '<div class="rumor-list-art" style="background-image:url(\\'' + trackerImageUrl(t) + '\\');"></div>' +
      '<div class="rumor-list-body">' +
        '<div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">' +
          '<span class="badge ' + t.cat + '">' + escapeHtml(badgeLine) + '</span>' +
          statusBadgeHtml(t) +
          credibilityBadgeHtml(t.credibility_category, t.credibility_pct) +
        '</div>' +
        '<h3>' + escapeHtml(t.title) + '</h3>' +
        '<p style="color:var(--muted); font-size:13.5px; line-height:1.55; margin-bottom:8px;">' + escapeHtml(excerpt) + '</p>' +
        '<div class="rumor-list-meta">Zuletzt aktualisiert: ' + escapeHtml(t.updated_date || '?') + ' · ' + entryCount + (entryCount === 1 ? ' Eintrag' : ' Einträge') + '</div>' +
      '</div></a>';
  }).join('');
}

function updateUrl(){
  const params = new URLSearchParams();
  if(activeGame !== "alle") params.set("game", activeGame);
  if(activeCat !== "alle") params.set("cat", activeCat);
  if(activeStatus !== "alle") params.set("status", activeStatus);
  const qs = params.toString();
  history.replaceState({}, '', qs ? ('?' + qs) : window.location.pathname);
}

function setRumorGame(g){ activeGame = g; renderChips(); renderGrid(); updateUrl(); }
function setRumorCat(c){ activeCat = c; renderChips(); renderGrid(); updateUrl(); }
function setRumorStatus(s){ activeStatus = s; renderChips(); renderGrid(); updateUrl(); }

// Initiale Filter aus der URL übernehmen — z. B. von einem Detail-Seiten-
// Link wie "Alle GTA-Gerüchte ansehen" (geruechte.html?game=gta), damit
// sich der gewünschte Überblick auch direkt verlinken/teilen lässt.
const initParams = new URLSearchParams(window.location.search);
const initGame = initParams.get("game");
const initCat = initParams.get("cat");
const initStatus = initParams.get("status");
if(initGame && GAMES[initGame]) activeGame = initGame;
if(initCat && CATS[initCat]) activeCat = initCat;
if(initStatus === "aktiv" || initStatus === "abgeschlossen") activeStatus = initStatus;

renderChips();
renderGrid();
</script>"""


def build_index_page(trackers):
    # Nur die für Filterung/Kartenanzeige nötigen Felder einbetten (nicht
    # die komplette Zeitleiste) — hält die Seite schlank, auch wenn später
    # viele Tracker mit langer Historie existieren.
    trackers_json_data = [
        {
            "id": t["id"],
            "title": t["title"],
            "cat": t.get("cat"),
            "game": t.get("game"),
            "status": t.get("status"),
            "resolution": t.get("resolution"),
            "credibility_category": t.get("credibility_category", "unbestaetigt"),
            "credibility_pct": t.get("credibility_pct", 0),
            "updated_date": t.get("updated_date"),
            "image": t.get("image"),
            "summary": t.get("summary", ""),
            "entry_count": len(t.get("timeline", [])),
        }
        for t in trackers
    ]
    # "</script>" im JSON (z. B. falls ein Summary-Text das enthält) würde
    # sonst das umschliessende <script>-Tag vorzeitig beenden.
    trackers_json_str = json.dumps(trackers_json_data, ensure_ascii=False).replace("</", "<\\/")
    js_block = RUMOR_INDEX_JS.replace("__TRACKERS_JSON__", trackers_json_str)

    intro = """
<div class="section-head">
  <h2 class="mono">🔍 Der lebende Leaks & Gerüchte-Tracker</h2>
  <div class="rule"></div>
</div>
<p style="color:var(--muted); font-size:14px; line-height:1.65; margin-bottom:8px; max-width:640px;">
  Statt für jedes neue Detail zu einem laufenden Leak einen weiteren Einzelartikel zu schreiben,
  führen wir hier EINE Seite pro großem Gerücht dauerhaft weiter — mit einer eigenen
  Glaubwürdigkeits-Einschätzung, die sich mit jedem neuen Stand anpasst. Nach Spiel, Kategorie
  und Status filterbar — so siehst du z. B. auf einen Blick den kompletten Gerüchte-Stand zu GTA 6.
</p>"""

    body = f"""{intro}
<div class="section-head" style="margin: 24px 0 12px;">
  <h2 class="mono" style="font-size:11px; color:var(--muted);">Spiel</h2>
</div>
<div class="chips" id="rumorGameChips"></div>

<div class="section-head" style="margin: 18px 0 12px;">
  <h2 class="mono" style="font-size:11px; color:var(--muted);">Kategorie</h2>
</div>
<div class="chips" id="rumorCatChips"></div>

<div class="section-head" style="margin: 18px 0 12px;">
  <h2 class="mono" style="font-size:11px; color:var(--muted);">Status</h2>
</div>
<div class="chips" id="rumorStatusChips" style="margin-bottom:22px;"></div>

<div id="rumorGrid"></div>
<p class="rumor-empty" id="rumorEmpty" style="display:none;">Keine Gerüchte zu dieser Auswahl gefunden — versuch's mit einem anderen Filter.</p>

{js_block}"""

    return page_shell(
        title="Leaks & Gerüchte-Tracker — LOADOUT-NEWS",
        description="Alle laufenden Gaming-Gerüchte und Leaks im Überblick, filterbar nach Spiel, Kategorie und Status, mit Glaubwürdigkeits-Einschätzung.",
        canonical=f"{SITE_URL}/geruechte.html",
        root="",
        body_html=body,
    )


def render_timeline_entry(entry):
    source_html = ""
    if entry.get("source_url"):
        source_html = f'<a href="{html.escape(entry["source_url"])}" target="_blank" rel="noopener">Quelle: {html.escape(entry.get("source", "Original"))} →</a>'
    elif entry.get("source"):
        source_html = f'Quelle: {html.escape(entry["source"])}'
    return f"""
<div class="rumor-timeline-item">
  <div class="rumor-timeline-date mono">{html.escape(entry.get('date', ''))}</div>
  {credibility_badge_html(entry.get('credibility_category', 'unbestaetigt'), entry.get('credibility_pct', 0), size='small')}
  <p class="rumor-timeline-text" style="margin-top:8px;">{html.escape(entry.get('text', ''))}</p>
  <div class="rumor-timeline-source">{source_html}</div>
</div>"""


def build_tracker_page(t):
    img = tracker_image(t)
    cat_label = CATS.get(t["cat"], t["cat"])
    game_label = GAMES.get(t.get("game"), "") if t.get("game") else ""
    badge_line = cat_label + (f" · {game_label}" if game_label else "")
    timeline_html = "".join(render_timeline_entry(e) for e in t.get("timeline", []))

    canonical = f"{SITE_URL}/geruechte/{t['id']}.html"
    json_ld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": t["title"],
        "description": t.get("summary", ""),
        "image": [img],
        "author": {"@type": "Organization", "name": "LOADOUT-NEWS Redaktion", "url": SITE_URL},
        "publisher": {"@type": "Organization", "name": "LOADOUT-NEWS",
                      "logo": {"@type": "ImageObject", "url": f"{SITE_URL}/logo-icon-192.png"}},
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
    }
    date_published = parse_german_date(t.get("created_date"))
    date_modified = parse_german_date(t.get("updated_date"))
    if date_published:
        json_ld["datePublished"] = date_published.isoformat()
    if date_modified:
        json_ld["dateModified"] = date_modified.isoformat()

    game_filter_link = ""
    if t.get("game") and t["game"] in GAMES:
        game_filter_link = (
            f'<a href="../geruechte.html?game={t["game"]}" class="chip" '
            f'style="text-decoration:none; display:inline-flex; margin-bottom:18px;">'
            f'Alle Leaks & Gerüchte zu {html.escape(GAMES[t["game"]])} ansehen →</a><br>'
        )

    body = f"""
<a href="../geruechte.html" class="back-btn mono" style="text-decoration:none; display:inline-flex; margin-bottom:12px;">← ZU ALLEN LEAKS & GERÜCHTEN</a><br>
{game_filter_link}
<div class="detail-art" style="background:url('{img}') center/cover; height:280px; border-radius:16px;"></div>
<div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin:18px 0 10px;">
  <span class="badge {t['cat']}">{html.escape(badge_line)}</span>
  {status_badge_html(t)}
</div>
<h1 class="display">{html.escape(t['title'])}</h1>
<div style="margin:14px 0 6px;">{credibility_badge_html(t.get('credibility_category', 'unbestaetigt'), t.get('credibility_pct', 0))}</div>
<p class="mono" style="color:var(--muted); font-size:12px; margin-bottom:20px;">
  Eröffnet am {html.escape(t.get('created_date', '?'))} · Zuletzt aktualisiert am {html.escape(t.get('updated_date', '?'))} ·
  {len(t.get('timeline', []))} {'Eintrag' if len(t.get('timeline', [])) == 1 else 'Einträge'}
</p>
<div class="editorial-box" style="margin-bottom:32px;">
  <div class="editorial-label mono">🗣️ Aktueller Gesamtstand</div>
  <p>{html.escape(t.get('summary', ''))}</p>
</div>
<div class="rumor-section-head" style="margin-top:0;">
  <h2 class="mono">Zeitleiste (neueste zuerst)</h2>
  <div class="rule"></div>
</div>
{timeline_html}
"""

    extra_head = f'<script type="application/ld+json">{json.dumps(json_ld, ensure_ascii=False)}</script>'
    return page_shell(
        title=f"{t['title']} — LOADOUT",
        description=(t.get("summary", "") or t["title"])[:200],
        canonical=canonical,
        root="../",
        body_html=body,
        extra_head=extra_head,
    )


def update_sitemap(urls_to_add):
    today_iso = datetime.date.today().isoformat()

    if os.path.exists(SITEMAP_FILE):
        with open(SITEMAP_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        existing_urls = set(re.findall(r"<loc>([^<]+)</loc>", content))
        new_entries = [u for u in urls_to_add if u not in existing_urls]
        if new_entries:
            insertion = "\n".join(f"  <url><loc>{u}</loc><lastmod>{today_iso}</lastmod></url>" for u in new_entries)
            content = content.replace("</urlset>", insertion + "\n</urlset>")
            with open(SITEMAP_FILE, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"✓ sitemap.xml um {len(new_entries)} Gerüchte-URL(s) ergänzt")
        else:
            print("✓ sitemap.xml enthält bereits alle Gerüchte-URLs")
    else:
        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for u in urls_to_add:
            lines.append(f"  <url><loc>{u}</loc><lastmod>{today_iso}</lastmod></url>")
        lines.append("</urlset>")
        with open(SITEMAP_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"✓ sitemap.xml neu angelegt mit {len(urls_to_add)} Gerüchte-URL(s) "
              f"(build_pages.py überschreibt sie beim nächsten Lauf mit der vollständigen Liste)")


def build():
    if not os.path.exists(RUMORS_FILE):
        print(f"! {RUMORS_FILE} nicht gefunden — nichts zu bauen (rumor_tracker.py muss vorher mindestens einmal gelaufen sein).")
        return

    with open(RUMORS_FILE, "r", encoding="utf-8") as f:
        trackers = json.load(f)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open("geruechte.html", "w", encoding="utf-8") as f:
        f.write(build_index_page(trackers))

    urls = [f"{SITE_URL}/geruechte.html"]
    for t in trackers:
        page = build_tracker_page(t)
        path = os.path.join(OUTPUT_DIR, f"{t['id']}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(page)
        urls.append(f"{SITE_URL}/geruechte/{t['id']}.html")

    update_sitemap(urls)

    active_n = sum(1 for t in trackers if t.get("status") == "aktiv")
    closed_n = len(trackers) - active_n
    print(f"✓ geruechte.html erzeugt ({active_n} aktiv, {closed_n} abgeschlossen)")
    print(f"✓ {len(trackers)} Detail-Seite(n) in /{OUTPUT_DIR} erzeugt")


if __name__ == "__main__":
    build()
