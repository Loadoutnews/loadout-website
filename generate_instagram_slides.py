"""
LOADOUT-NEWS — Instagram-Karussell-Folien-Generator
=======================================================
Erzeugt professionell gestaltete, gebrandete Bilder für den Instagram-
Karussell-Post, statt einfach nur die rohen Artikel-Bilder zu verwenden:

  - Folie 1 (Intro):    Obere 75% = Bildraster aus allen neuen Artikelbildern
                         (epische Vorschau, macht Lust auf alle Folien),
                         mit dem LOADOUT-Logo mittig. Bei GENAU 4 Bildern:
                         2×2-Kreuz-Raster (rechteckige Kacheln). Bei jeder
                         anderen Anzahl (typischerweise 3, seit der Original-
                         Artikel einen eigenen Premium-Post bekommt): ein
                         Kuchenstück-/Peace-Zeichen-Raster, das sich im
                         Zentrum trifft — so bleibt nie eine Kachel leer,
                         egal wie viele Artikel es gerade sind. Untere 25%
                         = Text ("X neue Artikel", Top-Artikel-Teaser,
                         Swipe-Hinweis) — exakt wie beim bisherigen Design,
                         nur kompakter.
  - Folie 2..N (Artikel): Artikel-Bild im Hintergrund, dunkler Verlauf für
                         Lesbarkeit, Kategorie-Badge, Artikel-Überschrift
                         in Marken-Typografie im Vordergrund
  - Letzte Folie (Outro): IMMER dasselbe, feste Bild — Werbung für die
                         Seite und alle Social-Media-Kanäle

Nutzt die Schriftart "Poppins" (im Ordner fonts/ mitgeliefert, damit die
Darstellung unabhängig davon ist, welche Schriften auf dem jeweiligen
Rechner/GitHub-Actions-Runner zufällig installiert sind). Bewusst KEINE
Emojis in den generierten Bildern — viele Schriftarten (auch Poppins)
enthalten keine Emoji-Glyphen und würden nur leere Kästchen zeigen;
stattdessen werden Symbole/Akzente selbst gezeichnet (Punkte, Linien).
"""

import io
import math
import os

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter

SIZE = 1080  # Instagram-Quadrat-Format
GRID_HEIGHT = int(SIZE * 0.75)  # obere 75% der Intro-Folie = Bildraster

# --- Marken-Farben — exakt wie in styles.css -------------------------------
BG = (10, 12, 22)          # --bg
VIOLET = (124, 92, 252)    # --violet
MAGENTA = (255, 77, 141)   # --magenta
CYAN = (52, 217, 201)      # --cyan
AMBER = (255, 183, 77)     # --amber
TEXT = (233, 232, 245)     # --text
MUTED = (141, 144, 172)    # --muted

CAT_COLORS = {"pc": VIOLET, "konsole": MAGENTA, "hardware": CYAN, "industrie": AMBER}
CAT_LABELS = {"pc": "PC", "konsole": "KONSOLEN", "hardware": "HARDWARE", "industrie": "INDUSTRIE"}

GRID_FALLBACK_COLORS = [(28, 20, 46), (20, 30, 46), (40, 22, 34), (22, 36, 32), (30, 24, 40), (24, 30, 38)]

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")


def poppins(size, weight="Bold"):
    return ImageFont.truetype(os.path.join(FONT_DIR, f"Poppins-{weight}.ttf"), size)


def wrap_text_to_width(draw, text, font, max_width):
    """Bricht Text zeilenweise um, sodass jede Zeile in max_width passt."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        if draw.textlength(test, font=font) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def truncate_to_width(draw, text, font, max_width):
    """Kürzt eine einzelne Textzeile mit '…', bis sie in max_width passt."""
    if draw.textlength(text, font=font) <= max_width:
        return text
    while len(text) > 1 and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1].rstrip()
    return text + "…"


def draw_centered_text(draw, text, font, y, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    draw.text(((SIZE - w) / 2, y), text, font=font, fill=fill)
    return w


def make_brand_background(glow_top_right=True):
    """Der dunkle Verlaufs-Hintergrund im LOADOUT-Stil — zwei weiche,
    farbige "Glow"-Flecken auf dunklem Grund, wie der Website-Hero."""
    if glow_top_right:
        pos1, pos2 = ([-200, -300, 700, 400], [600, 700, 1400, 1400])
    else:
        pos1, pos2 = ([200, -350, 1100, 350], [-200, 750, 500, 1450])

    glow1 = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(glow1).ellipse(pos1, fill=(*VIOLET, 95))
    glow1 = glow1.filter(ImageFilter.GaussianBlur(180))

    glow2 = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(glow2).ellipse(pos2, fill=(*MAGENTA, 75))
    glow2 = glow2.filter(ImageFilter.GaussianBlur(180))

    base = Image.new("RGBA", (SIZE, SIZE), (*BG, 255))
    base = Image.alpha_composite(base, glow1)
    base = Image.alpha_composite(base, glow2)
    return base.convert("RGB")


def draw_logo_icon(canvas, x, y, scale=1.0):
    """Das 'aufsteigende Balken'-Icon im Verlauf violett→magenta, exakt wie
    das SVG-Logo auf der Website."""
    icon_size = int(120 * scale)
    icon = Image.new("RGBA", (icon_size, icon_size), (0, 0, 0, 0))
    d = ImageDraw.Draw(icon)
    d.rounded_rectangle([0, 0, icon_size, icon_size], radius=int(26 * scale), fill=(*BG, 245))
    bars = [(24, 24, 38, 92), (44, 62, 56, 80), (60, 50, 72, 80), (76, 36, 88, 80)]
    n = len(bars)
    for i, (bx0, by0, bx1, by1) in enumerate(bars):
        t = i / (n - 1)
        color = tuple(int(VIOLET[c] + (MAGENTA[c] - VIOLET[c]) * t) for c in range(3))
        sx0, sy0, sx1, sy1 = [int(v * scale) for v in (bx0, by0, bx1, by1)]
        d.rounded_rectangle([sx0, sy0, sx1, sy1], radius=int(6 * scale), fill=(*color, 255))
    d.rounded_rectangle([int(24 * scale), int(80 * scale), int(96 * scale), int(92 * scale)],
                         radius=int(6 * scale), fill=(*MAGENTA, 255))
    canvas.paste(icon, (x, y), icon)


def draw_wordmark_centered(canvas, cy, size=64):
    """LOAD (weiß) OUT (magenta) -NEWS (klein, gedämpft), horizontal zentriert."""
    draw = ImageDraw.Draw(canvas)
    f_main = poppins(size, "Bold")
    f_small = poppins(int(size * 0.32), "Medium")
    w_load = draw.textlength("LOAD", font=f_main)
    w_out = draw.textlength("OUT", font=f_main)
    w_small = draw.textlength("-NEWS", font=f_small)
    total_w = w_load + w_out + 8 + w_small
    x = (SIZE - total_w) / 2
    draw.text((x, cy), "LOAD", font=f_main, fill=TEXT)
    x += w_load
    draw.text((x, cy), "OUT", font=f_main, fill=MAGENTA)
    x += w_out
    small_y = cy + size - int(size * 0.32) - 6
    draw.text((x + 8, small_y), "-NEWS", font=f_small, fill=MUTED)


def cover_crop(img, w, h):
    """Skaliert und beschneidet ein Bild mittig auf eine feste Zielgröße
    (entspricht CSS background-size:cover)."""
    iw, ih = img.size
    scale = max(w / iw, h / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    return img.crop((left, top, left + w, top + h))


def _decode_image(image_bytes, w, h, fallback_color):
    if image_bytes:
        try:
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            return cover_crop(img, w, h)
        except Exception:
            pass
    return Image.new("RGB", (w, h), fallback_color)


# --- Gemeinsame Bildraster-Logik für Intro-Folien (Artikel- & Kalender-Posts) --
#
# Bei GENAU 4 Bildern: bewährtes 2×2-Kreuz-Raster (rechteckige Kacheln,
# Trennlinien im Kreuz). Bei JEDER ANDEREN Anzahl (1, 2, 3, 5, 6 …): ein
# Kuchenstück-Raster, bei dem sich alle Sektoren im Zentrum treffen — wie
# die Speichen eines Peace-Zeichens. Das verhindert die leere, kaputt
# aussehende Kachel, die entstand, als der Batch-Post von 4 auf 3 Artikel
# (1 Original + 3 News → Original bekam einen eigenen Post) reduziert wurde.

def _make_wedge_mask(cx, cy, radius, angle_start_deg, angle_end_deg, size):
    """Graustufen-Maske für ein 'Kuchenstück' (Kreissektor) von
    angle_start_deg bis angle_end_deg (0° = nach oben, im Uhrzeigersinn),
    mit Mittelpunkt (cx, cy). Der Bogen wird durch ausreichend viele
    Punkte angenähert, damit die Kante glatt wirkt."""
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    steps = max(8, int((angle_end_deg - angle_start_deg) / 3))
    points = [(cx, cy)]
    for i in range(steps + 1):
        angle = math.radians(angle_start_deg + (angle_end_deg - angle_start_deg) * i / steps - 90)
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    draw.polygon(points, fill=255)
    return mask


def _compose_grid(canvas, image_bytes_list, grid_w=SIZE, grid_h=GRID_HEIGHT, grid_y_offset=0):
    """Füllt eine Rasterfläche (Breite grid_w, Höhe grid_h, ab grid_y_offset
    von oben) mit den übergebenen Bildern und zeichnet das LOADOUT-Logo
    mittig in einem runden Plättchen darüber. Wählt automatisch das
    passende Muster je nach Bildanzahl:

    - genau 4 Bilder → 2×2-Kreuz-Raster (rechteckige Kacheln)
    - jede andere Anzahl (>= 1) → Kuchenstück-Raster, alle Sektoren treffen
      sich im Zentrum — keine leere Kachel, egal wie viele Bilder es sind
    """
    count = max(1, len(image_bytes_list))
    cx, cy = grid_w // 2, grid_y_offset + grid_h // 2

    if len(image_bytes_list) == 4:
        cell_w, cell_h = grid_w // 2, grid_h // 2
        positions = [
            (0, grid_y_offset), (cell_w, grid_y_offset),
            (0, grid_y_offset + cell_h), (cell_w, grid_y_offset + cell_h),
        ]
        for i, pos in enumerate(positions):
            image_bytes = image_bytes_list[i] if i < len(image_bytes_list) else None
            tile = _decode_image(image_bytes, cell_w, cell_h, GRID_FALLBACK_COLORS[i % len(GRID_FALLBACK_COLORS)])
            dark_overlay = Image.new("RGB", (cell_w, cell_h), BG)
            tile = Image.blend(tile, dark_overlay, 0.28)
            canvas.paste(tile, pos)

        draw = ImageDraw.Draw(canvas)
        line_w = 6
        draw.rectangle([cx - line_w // 2, grid_y_offset, cx + line_w // 2, grid_y_offset + grid_h], fill=BG)
        draw.rectangle([0, cy - line_w // 2, grid_w, cy + line_w // 2], fill=BG)
    else:
        # Kuchenstück-Raster: jedes Bild deckt die komplette Rasterfläche
        # ab und wird dann per Sektor-Maske auf sein "Tortenstück" beschnitten.
        radius = int(math.hypot(grid_w / 2, grid_h / 2)) + 20
        wedge_angle = 360 / count
        for i in range(count):
            image_bytes = image_bytes_list[i] if i < len(image_bytes_list) else None
            tile = _decode_image(image_bytes, grid_w, grid_h, GRID_FALLBACK_COLORS[i % len(GRID_FALLBACK_COLORS)])
            dark_overlay = Image.new("RGB", (grid_w, grid_h), BG)
            tile = Image.blend(tile, dark_overlay, 0.28)

            mask_local = _make_wedge_mask(grid_w // 2, grid_h // 2, radius, i * wedge_angle, (i + 1) * wedge_angle,
                                           size=(grid_w, grid_h))
            canvas.paste(tile, (0, grid_y_offset), mask_local)

        if count > 1:
            # Dünne, dunkle Speichen vom Zentrum zum Rand — wie bei einem
            # Peace-Zeichen — für klare, saubere Kanten zwischen den Sektoren.
            draw = ImageDraw.Draw(canvas)
            for i in range(count):
                angle = math.radians(i * wedge_angle - 90)
                end_x = cx + radius * math.cos(angle)
                end_y = cy + radius * math.sin(angle)
                draw.line([(cx, cy), (end_x, end_y)], fill=BG, width=6)

    # Weicher Verlauf am unteren Rand des Rasters — sanfter Übergang zur
    # Textzone statt einer harten Kante
    fade_h = 90
    fade = Image.new("L", (1, fade_h))
    for y in range(fade_h):
        fade.putpixel((0, y), int(255 * (y / fade_h)))
    fade = fade.resize((grid_w, fade_h))
    dark_strip = Image.new("RGB", (grid_w, fade_h), BG)
    fade_top = grid_y_offset + grid_h - fade_h
    region = canvas.crop((0, fade_top, grid_w, grid_y_offset + grid_h))
    region = Image.composite(dark_strip, region, fade)
    canvas.paste(region, (0, fade_top))

    # LOADOUT-Logo mittig — mit einem dunklen, runden Hintergrund-Plättchen,
    # damit es über jedem beliebigen Bild-Motiv gut lesbar bleibt, egal
    # welches Muster (Kreuz oder Kuchenstücke) gerade verwendet wird.
    logo_scale = 1.35
    logo_icon_w = int(120 * logo_scale)
    badge_pad = 22
    badge_size = logo_icon_w + badge_pad * 2
    badge = Image.new("RGBA", (badge_size, badge_size), (0, 0, 0, 0))
    ImageDraw.Draw(badge).ellipse([0, 0, badge_size, badge_size], fill=(*BG, 235))
    canvas.paste(badge, (cx - badge_size // 2, cy - badge_size // 2), badge)
    draw_logo_icon(canvas, cx - logo_icon_w // 2, cy - logo_icon_w // 2, scale=logo_scale)


# --- Folie 1: Intro — Bildraster (Kreuz bei 4, sonst Kuchenstücke) + Logo ---
# + Text unten ---------------------------------------------------------------

def make_intro_slide(image_bytes_list, article_count, top_title):
    """image_bytes_list: Liste der rohen Bild-Bytes der neuen Artikel, in
    Anzeige-Reihenfolge. Bei genau 4 Bildern entsteht das bewährte
    2×2-Kreuz-Raster; bei jeder anderen Anzahl (typischerweise 3, siehe
    Moduldoku oben) ein Kuchenstück-Raster ohne leere Kachel. Fehlt ein
    einzelnes Bild, wird die jeweilige Kachel mit einer dezenten
    Marken-Ersatzfarbe gefüllt, damit das Raster nie kaputt aussieht."""
    canvas = Image.new("RGB", (SIZE, SIZE), BG)
    _compose_grid(canvas, image_bytes_list)

    # --- Untere 25%: Text — "X neue Artikel", Top-Artikel-Teaser, Swipe-Hinweis ---
    draw = ImageDraw.Draw(canvas)
    ty = GRID_HEIGHT + 24

    f_headline = poppins(46, "Bold")
    draw_centered_text(draw, f"{article_count} NEUE ARTIKEL", f_headline, ty, TEXT)
    ty += 60

    f_teaser = poppins(24, "Medium")
    teaser = truncate_to_width(draw, f"u. a. {top_title}", f_teaser, SIZE - 140)
    draw_centered_text(draw, teaser, f_teaser, ty, MUTED)
    ty += 48

    f_swipe = poppins(22, "Bold")
    draw_centered_text(draw, "SWIPE FÜR ALLE ARTIKEL  →", f_swipe, ty, VIOLET)

    return canvas


# --- Folie 2..N: Artikel -----------------------------------------------------

def make_article_slide(image_bytes, title, cat, slide_num, total_slides):
    bg = _decode_image(image_bytes, SIZE, SIZE, BG).convert("RGBA")

    # Dunkler Verlauf von oben (dezent) nach unten (stark) für Lesbarkeit
    gradient = Image.new("L", (1, SIZE))
    for y in range(SIZE):
        t = y / SIZE
        gradient.putpixel((0, y), min(int(90 + t * 165), 255))
    gradient = gradient.resize((SIZE, SIZE))
    dark_layer = Image.new("RGBA", (SIZE, SIZE), (*BG, 255))
    bg = Image.composite(dark_layer, bg, gradient)

    # Zusätzlicher, dezenter Verlauf ganz oben für Badge & Logo-Wasserzeichen
    top_shade = Image.new("L", (1, 260))
    for y in range(260):
        top_shade.putpixel((0, y), int(120 * (1 - y / 260)))
    top_shade = top_shade.resize((SIZE, 260))
    top_dark = Image.new("RGBA", (SIZE, 260), (*BG, 255))
    top_region = Image.composite(top_dark, bg.crop((0, 0, SIZE, 260)), top_shade)
    bg.paste(top_region, (0, 0))

    draw = ImageDraw.Draw(bg)

    # Kategorie-Badge oben links
    cat_color = CAT_COLORS.get(cat, VIOLET)
    f_badge = poppins(24, "Bold")
    badge_text = CAT_LABELS.get(cat, (cat or "").upper())
    bbox = draw.textbbox((0, 0), badge_text, font=f_badge)
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 20, 12
    badge_bg = Image.new("RGBA", (bw + pad_x * 2, bh + pad_y * 2), (0, 0, 0, 0))
    ImageDraw.Draw(badge_bg).rounded_rectangle(
        [0, 0, bw + pad_x * 2, bh + pad_y * 2], radius=(bh + pad_y * 2) // 2, fill=(*cat_color, 235)
    )
    bg.paste(badge_bg, (60, 60), badge_bg)
    draw.text((60 + pad_x, 60 + pad_y - bbox[1]), badge_text, font=f_badge, fill=BG)

    # Kleines Logo-Wasserzeichen oben rechts + Folien-Zähler darunter
    draw_logo_icon(bg, SIZE - 60 - 64, 60, scale=0.53)
    f_counter = poppins(22, "Medium")
    counter_text = f"{slide_num} / {total_slides}"
    cbbox = draw.textbbox((0, 0), counter_text, font=f_counter)
    draw.text((SIZE - 60 - (cbbox[2] - cbbox[0]), 145), counter_text, font=f_counter, fill=MUTED)

    # Artikel-Titel unten, groß und fett — schrumpft automatisch, falls zu lang
    f_title = poppins(56, "Bold")
    max_text_width = SIZE - 120
    lines = wrap_text_to_width(draw, title, f_title, max_text_width)
    while len(lines) > 4 and f_title.size > 36:
        f_title = poppins(f_title.size - 4, "Bold")
        lines = wrap_text_to_width(draw, title, f_title, max_text_width)

    line_height = int(f_title.size * 1.18)
    total_text_h = line_height * len(lines)
    y_start = SIZE - 100 - total_text_h
    y = y_start
    for line in lines:
        draw.text((60, y), line, font=f_title, fill=TEXT)
        y += line_height

    draw.rounded_rectangle([60, y_start - 26, 110, y_start - 18], radius=4, fill=MAGENTA)

    return bg.convert("RGB")


# --- Letzte Folie: Outro (fest, immer identisch) -----------------------------

def make_outro_slide():
    bg = make_brand_background(glow_top_right=False)
    draw = ImageDraw.Draw(bg)

    icon_scale = 1.9
    icon_w = int(120 * icon_scale)
    draw_logo_icon(bg, (SIZE - icon_w) // 2, 140, scale=icon_scale)
    draw_wordmark_centered(bg, 370, size=58)

    draw.line([(SIZE // 2 - 60, 495), (SIZE // 2 + 60, 495)], fill=MAGENTA, width=4)

    f_headline = poppins(58, "Bold")
    draw_centered_text(draw, "KEINE GAMING-NEWS", f_headline, 550, TEXT)
    draw_centered_text(draw, "MEHR VERPASSEN?", f_headline, 618, TEXT)

    f_sub = poppins(28, "Medium")
    draw_centered_text(draw, "Folge uns auf all unseren Kanälen", f_sub, 700, MUTED)

    def draw_platform_pill(cx, y, label, color):
        f = poppins(30, "Bold")
        bbox = draw.textbbox((0, 0), label, font=f)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        dot_r, dot_gap, pad_x, pad_y = 8, 16, 30, 16
        pill_w, pill_h = dot_r * 2 + dot_gap + tw + pad_x * 2, th + pad_y * 2 + 14
        pill = Image.new("RGBA", (pill_w, pill_h), (0, 0, 0, 0))
        pd = ImageDraw.Draw(pill)
        pd.rounded_rectangle([0, 0, pill_w, pill_h], radius=pill_h // 2, outline=(*color, 255), width=3, fill=(*color, 28))
        pd.ellipse([pad_x - dot_r, pill_h // 2 - dot_r, pad_x + dot_r, pill_h // 2 + dot_r], fill=(*color, 255))
        bg.paste(pill, (int(cx - pill_w / 2), y), pill)
        text_x = cx - pill_w / 2 + pad_x + dot_r * 2 + dot_gap
        draw.text((text_x, y + pad_y - bbox[1] + 5), label, font=f, fill=TEXT)
        return pill_w

    y1 = 775
    rows = [[("Discord", VIOLET), ("Bluesky", CYAN)], [("Tumblr", MAGENTA), ("Reddit", VIOLET)]]
    for row_i, row in enumerate(rows):
        f = poppins(30, "Bold")
        widths = [draw.textbbox((0, 0), label, font=f)[2] + 16 + 76 for label, _ in row]
        gap = 24
        start_x = (SIZE - (sum(widths) + gap)) / 2
        cx = start_x
        for (label, color), w in zip(row, widths):
            draw_platform_pill(cx + w / 2, y1 + row_i * 92, label, color)
            cx += w + gap

    f_cta = poppins(34, "Bold")
    draw_centered_text(draw, "loadout-news.com", f_cta, 970, TEXT)

    return bg


# --- Orchestrierung: alle Folien für einen Post erzeugen ---------------------

def _download_image(url):
    if not url:
        return b""
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            return resp.content
    except Exception:
        pass
    return b""


def generate_all_slides(articles, output_dir, run_id):
    """Erzeugt Intro-Folie (mit Bildraster aller Artikel) + eine Folie pro
    Artikel und speichert sie lokal. Die Outro-Folie wird bewusst NICHT
    hier erzeugt — die ist ein fester, einmalig erstellter Bestandteil des
    Repos (siehe social-assets/), damit sie garantiert bei jedem Post exakt
    identisch bleibt.

    run_id wird Teil jedes Dateinamens — GitHubs Rohdaten-Auslieferung
    (raw.githubusercontent.com) cached Inhalte kurzzeitig. Mit immer
    gleichen Dateinamen könnte Buffer nach einem neuen Push kurzzeitig noch
    ein Bild vom VORHERIGEN Lauf bekommen. Eindeutige Dateinamen pro Lauf
    umgehen dieses Problem zuverlässig."""
    os.makedirs(output_dir, exist_ok=True)
    paths = []

    # Jedes Artikel-Bild wird nur EINMAL heruntergeladen und sowohl fürs
    # Intro-Raster als auch für die eigene Artikel-Folie wiederverwendet.
    image_bytes_by_article = [_download_image(a.get("image")) for a in articles]

    top_article = max(articles, key=lambda a: a.get("hype", 0))
    intro = make_intro_slide(image_bytes_by_article, len(articles), top_article["title"])
    intro_path = os.path.join(output_dir, f"{run_id}-00-intro.jpg")
    intro.save(intro_path, quality=90)
    paths.append(intro_path)

    total = len(articles) + 2  # + Intro + Outro
    for i, (a, image_bytes) in enumerate(zip(articles, image_bytes_by_article), start=1):
        slide = make_article_slide(image_bytes, a["title"], a.get("cat"), i + 1, total)
        slide_path = os.path.join(output_dir, f"{run_id}-{i:02d}-artikel.jpg")
        slide.save(slide_path, quality=90)
        paths.append(slide_path)

    return paths


# --- Kalender-Posts (Release-/Update-Kalender) ------------------------------
# Dasselbe visuelle Grundprinzip wie bei den Artikel-Folien (Bildraster +
# Logo mittig auf der Intro-Folie, dann eine Folie pro Eintrag, feste
# Outro-Folie) — aber mit frei wählbarem Text statt der festen
# "X neue Artikel"-Formel, damit dieselbe Optik auch für Release-/Update-
# Meldungen funktioniert. Bewusst als EIGENE Funktionen statt die
# bestehenden make_intro_slide/make_article_slide zu verändern — so bleibt
# das bereits laufende Artikel-Karussell garantiert unangetastet.

def make_calendar_intro_slide(image_bytes_list, line1, line2, line3):
    """Generalisierte Intro-Folie für Kalender-Posts: dasselbe Bildraster-
    Verhalten wie make_intro_slide (2×2-Kreuz bei genau 4 Einträgen, sonst
    Kuchenstücke ohne leere Kachel) + Logo mittig, aber mit 3 frei
    wählbaren Textzeilen statt der festen Artikel-Anzahl-Formel — z. B.
    für den Update-Kalender: ("3 NEUE UPDATES", "u. a. GTA 6 Season 5",
    "SWIPE FÜR ALLE UPDATES →"), oder für den Release-Kalender:
    ("TOP-RELEASES AUGUST", "+8 weitere Releases diesen Monat",
    "SWIPE FÜR ALLE RELEASES →")."""
    canvas = Image.new("RGB", (SIZE, SIZE), BG)
    _compose_grid(canvas, image_bytes_list)

    draw = ImageDraw.Draw(canvas)
    ty = GRID_HEIGHT + 24

    f_headline = poppins(42, "Bold")
    headline = truncate_to_width(draw, line1, f_headline, SIZE - 100)
    draw_centered_text(draw, headline, f_headline, ty, TEXT)
    ty += 56

    f_sub = poppins(24, "Medium")
    sub = truncate_to_width(draw, line2, f_sub, SIZE - 140)
    draw_centered_text(draw, sub, f_sub, ty, MUTED)
    ty += 48

    f_swipe = poppins(22, "Bold")
    draw_centered_text(draw, line3, f_swipe, ty, VIOLET)

    return canvas


def make_calendar_item_slide(image_bytes, title, badge_text, badge_color, slide_num, total_slides):
    """Generalisierte Item-Folie für Kalender-Posts: identischer Aufbau wie
    make_article_slide (Bild-Hintergrund, dunkler Verlauf, Titel groß im
    Vordergrund, Logo-Wasserzeichen, Folien-Zähler), aber mit frei
    wählbarem Badge-Text/-Farbe statt einer festen Kategorie aus CAT_LABELS
    — z. B. dem Genre eines Release-Titels oder dem Spielnamen bei einem
    Update."""
    bg = _decode_image(image_bytes, SIZE, SIZE, BG).convert("RGBA")

    gradient = Image.new("L", (1, SIZE))
    for y in range(SIZE):
        t = y / SIZE
        gradient.putpixel((0, y), min(int(90 + t * 165), 255))
    gradient = gradient.resize((SIZE, SIZE))
    dark_layer = Image.new("RGBA", (SIZE, SIZE), (*BG, 255))
    bg = Image.composite(dark_layer, bg, gradient)

    top_shade = Image.new("L", (1, 260))
    for y in range(260):
        top_shade.putpixel((0, y), int(120 * (1 - y / 260)))
    top_shade = top_shade.resize((SIZE, 260))
    top_dark = Image.new("RGBA", (SIZE, 260), (*BG, 255))
    top_region = Image.composite(top_dark, bg.crop((0, 0, SIZE, 260)), top_shade)
    bg.paste(top_region, (0, 0))

    draw = ImageDraw.Draw(bg)

    f_badge = poppins(24, "Bold")
    badge_text = (badge_text or "").upper()
    bbox = draw.textbbox((0, 0), badge_text, font=f_badge)
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 20, 12
    badge_bg = Image.new("RGBA", (bw + pad_x * 2, bh + pad_y * 2), (0, 0, 0, 0))
    ImageDraw.Draw(badge_bg).rounded_rectangle(
        [0, 0, bw + pad_x * 2, bh + pad_y * 2], radius=(bh + pad_y * 2) // 2, fill=(*badge_color, 235)
    )
    bg.paste(badge_bg, (60, 60), badge_bg)
    draw.text((60 + pad_x, 60 + pad_y - bbox[1]), badge_text, font=f_badge, fill=BG)

    draw_logo_icon(bg, SIZE - 60 - 64, 60, scale=0.53)
    f_counter = poppins(22, "Medium")
    counter_text = f"{slide_num} / {total_slides}"
    cbbox = draw.textbbox((0, 0), counter_text, font=f_counter)
    draw.text((SIZE - 60 - (cbbox[2] - cbbox[0]), 145), counter_text, font=f_counter, fill=MUTED)

    f_title = poppins(56, "Bold")
    max_text_width = SIZE - 120
    lines = wrap_text_to_width(draw, title, f_title, max_text_width)
    while len(lines) > 4 and f_title.size > 36:
        f_title = poppins(f_title.size - 4, "Bold")
        lines = wrap_text_to_width(draw, title, f_title, max_text_width)

    line_height = int(f_title.size * 1.18)
    total_text_h = line_height * len(lines)
    y_start = SIZE - 100 - total_text_h
    y = y_start
    for line in lines:
        draw.text((60, y), line, font=f_title, fill=TEXT)
        y += line_height

    draw.rounded_rectangle([60, y_start - 26, 110, y_start - 18], radius=4, fill=MAGENTA)

    return bg.convert("RGB")


def generate_calendar_slides(items, output_dir, run_id, line1, line2, line3,
                              title_fn, badge_fn, badge_color=VIOLET, image_fn=None):
    """Orchestriert eine komplette Kalender-Karussell-Folienserie (Intro +
    eine Folie pro Eintrag), analog zu generate_all_slides() für Artikel.

    items: Liste der anzuzeigenden Release-/Update-Einträge (bereits von
    der aufrufenden Stelle auf die gewünschte Auswahl reduziert, z. B. die
    Top 4 nach Hype).
    title_fn/badge_fn: Funktionen, die aus einem Eintrag den Anzeige-Titel
    bzw. Badge-Text ableiten (unterschiedlich für Releases vs. Updates).
    image_fn: optionale Funktion zur Bild-URL-Ermittlung, Standard ist
    einfach item.get('image')."""
    os.makedirs(output_dir, exist_ok=True)
    paths = []
    image_fn = image_fn or (lambda item: item.get("image"))

    image_bytes_by_item = [_download_image(image_fn(item)) for item in items]

    intro = make_calendar_intro_slide(image_bytes_by_item, line1, line2, line3)
    intro_path = os.path.join(output_dir, f"{run_id}-00-intro.jpg")
    intro.save(intro_path, quality=90)
    paths.append(intro_path)

    total = len(items) + 2  # + Intro + Outro
    for i, (item, image_bytes) in enumerate(zip(items, image_bytes_by_item), start=1):
        slide = make_calendar_item_slide(
            image_bytes, title_fn(item), badge_fn(item), badge_color, i + 1, total
        )
        slide_path = os.path.join(output_dir, f"{run_id}-{i:02d}-kalender.jpg")
        slide.save(slide_path, quality=90)
        paths.append(slide_path)

    return paths


# --- LOADOUT-Original: eigenständiges Premium-Design ------------------------
# Der LOADOUT-Original-Artikel bekommt einen KOMPLETT eigenen, deutlich
# aufwendigeren Instagram-Post statt im gemeinsamen Artikel-Karussell
# mitzulaufen — soll wie eine "richtige" Enthüllung/Analyse wirken, nicht
# wie eine weitere Meldung unter vielen. Aufbau (bewusst als eigenständige
# Funktionen, rühren die bestehenden Artikel-/Kalender-Folien nicht an):
#
#   1. Cover-Folie   — Artikelbild grossflächig, dramatischer Verlauf,
#                       "LOADOUT ORIGINAL"-Siegel (Verlauf-Rand statt
#                       flacher Kategorie-Pille), grosse Schlagzeile
#   2. Hook-Folie     — Teaser als grosses, zentriertes Statement auf
#                       Marken-Hintergrund, baut Spannung auf
#   3. Insight-Folien — "Countdown"-Nummern (01, 02 …) im Verlaufsstil +
#                       je eine Kernaussage aus dem Artikeltext — das
#                       Muster, das Leser:innen zum Weiterwischen animiert
#   4. Einschätzungs-Folie — die redaktionelle Meinung, zitatartig
#                       inszeniert, vermittelt eigene Expertise
#   5. Feste Outro-Folie — dieselbe wie bei allen anderen Posts (Wieder-
#                       erkennung + "Folge uns"), wird vom aufrufenden
#                       Code wie gehabt separat angehängt

def _original_brand_background():
    """Etwas dezenterer Marken-Hintergrund als make_brand_background() —
    für die reinen Text-Folien (Hook/Insight/Einschätzung) des Original-
    Posts, damit der Text im Vordergrund klar dominiert."""
    glow1 = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(glow1).ellipse([-200, -300, 700, 400], fill=(*VIOLET, 80))
    glow1 = glow1.filter(ImageFilter.GaussianBlur(180))
    glow2 = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(glow2).ellipse([500, 650, 1300, 1350], fill=(*MAGENTA, 60))
    glow2 = glow2.filter(ImageFilter.GaussianBlur(180))
    base = Image.new("RGBA", (SIZE, SIZE), (*BG, 255))
    base = Image.alpha_composite(base, glow1)
    base = Image.alpha_composite(base, glow2)
    return base.convert("RGB")


def _draw_gradient_seal(canvas, cx, y, text, font):
    """Verlauf-umrandete Pille fürs 'LOADOUT ORIGINAL'-Siegel — bewusst
    edler als die flachen, einfarbigen Kategorie-Badges der normalen
    Artikel-Folien, um den Original-Post visuell klar als "besonders"
    abzuheben. Nutzt einen selbst gezeichneten Diamant-Akzent statt eines
    Emojis (Poppins enthält keine Emoji-Glyphen, siehe frühere Tests)."""
    draw = ImageDraw.Draw(canvas)
    pad_x, pad_y = 22, 12
    accent_w = 16
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pill_w, pill_h = tw + accent_w + 10 + pad_x * 2, th + pad_y * 2
    pill_x = cx - pill_w // 2

    border = 2
    outer = Image.new("RGBA", (pill_w, pill_h), (0, 0, 0, 0))
    od = ImageDraw.Draw(outer)
    for i in range(pill_w):
        t = i / pill_w
        c = tuple(int(VIOLET[k] + (MAGENTA[k] - VIOLET[k]) * t) for k in range(3))
        od.line([(i, 0), (i, pill_h)], fill=(*c, 255))
    mask = Image.new("L", (pill_w, pill_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, pill_w, pill_h], radius=pill_h // 2, fill=255)
    outer.putalpha(mask)
    canvas.paste(outer, (pill_x, y), outer)

    inner = Image.new("RGBA", (pill_w - border * 2, pill_h - border * 2), (0, 0, 0, 0))
    ImageDraw.Draw(inner).rounded_rectangle(
        [0, 0, pill_w - border * 2, pill_h - border * 2], radius=(pill_h - border * 2) // 2, fill=(*BG, 255)
    )
    canvas.paste(inner, (pill_x + border, y + border), inner)

    diamond_cy = y + pill_h // 2
    diamond_cx = pill_x + pad_x + accent_w // 2
    r = 6
    draw.polygon(
        [(diamond_cx, diamond_cy - r), (diamond_cx + r, diamond_cy),
         (diamond_cx, diamond_cy + r), (diamond_cx - r, diamond_cy)],
        fill=MAGENTA,
    )

    tx = pill_x + pad_x + accent_w + 10
    ty = y + (pill_h - th) / 2 - bbox[1]
    draw.text((tx, ty), text, font=font, fill=TEXT)
    return pill_h


def _draw_gradient_line(canvas, cx, y, width=90, height=4):
    grad_line = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad_line)
    for i in range(width):
        t = i / width
        c = tuple(int(VIOLET[k] + (MAGENTA[k] - VIOLET[k]) * t) for k in range(3))
        gd.line([(i, 0), (i, height)], fill=(*c, 255))
    canvas.paste(grad_line, (cx - width // 2, y), grad_line)


def make_original_cover_slide(image_bytes, title):
    """Folie 1: Artikelbild grossflächig mit dramatischem Magazin-Verlauf
    (dunkler oben fürs Siegel und unten für die Schlagzeile, dazwischen
    dezenter, damit das Bild selbst erkennbar bleibt), plus Siegel und
    grosser Schlagzeile."""
    bg = _decode_image(image_bytes, SIZE, SIZE, BG).convert("RGBA")

    gradient = Image.new("L", (1, SIZE))
    for y in range(SIZE):
        t = y / SIZE
        if t < 0.15:
            alpha = int(150 - (t / 0.15) * 90)
        elif t < 0.55:
            alpha = int(60 + ((t - 0.15) / 0.4) * 15)
        else:
            alpha = int(75 + ((t - 0.55) / 0.45) * 180)
        gradient.putpixel((0, y), min(alpha, 255))
    gradient = gradient.resize((SIZE, SIZE))
    dark_layer = Image.new("RGBA", (SIZE, SIZE), (*BG, 255))
    bg = Image.composite(dark_layer, bg, gradient)

    draw = ImageDraw.Draw(bg)
    f_seal = poppins(24, "Bold")
    seal_h = _draw_gradient_seal(bg, SIZE // 2, 64, "LOADOUT ORIGINAL", f_seal)

    line_y = 64 + seal_h + 24
    _draw_gradient_line(bg, SIZE // 2, line_y)

    f_title = poppins(64, "Bold")
    max_w = SIZE - 120
    lines = wrap_text_to_width(draw, title, f_title, max_w)
    while len(lines) > 4 and f_title.size > 42:
        f_title = poppins(f_title.size - 4, "Bold")
        lines = wrap_text_to_width(draw, title, f_title, max_w)
    line_height = int(f_title.size * 1.15)
    total_h = line_height * len(lines)
    y_start = SIZE - 110 - total_h
    y = y_start
    for line in lines:
        draw.text((60, y), line, font=f_title, fill=TEXT)
        y += line_height

    f_hint = poppins(22, "Medium")
    draw.text((60, SIZE - 62), "Eigene Recherche & Analyse von LOADOUT", font=f_hint, fill=MUTED)

    return bg.convert("RGB")


def make_original_hook_slide(teaser):
    """Folie 2: Der Teaser als grosses, zentriertes Statement — baut
    Spannung auf, bevor die Insight-Folien die konkreten Fakten liefern."""
    canvas = _original_brand_background()
    draw = ImageDraw.Draw(canvas)

    f_quote_mark = poppins(120, "Bold")
    draw_centered_text(draw, '"', f_quote_mark, 130, VIOLET)

    f_teaser = poppins(46, "Bold")
    max_w = SIZE - 160
    lines = wrap_text_to_width(draw, teaser, f_teaser, max_w)
    while len(lines) > 6 and f_teaser.size > 32:
        f_teaser = poppins(f_teaser.size - 4, "Bold")
        lines = wrap_text_to_width(draw, teaser, f_teaser, max_w)
    line_height = int(f_teaser.size * 1.3)
    total_h = line_height * len(lines)
    y = (SIZE - total_h) / 2
    for line in lines:
        draw_centered_text(draw, line, f_teaser, y, TEXT)
        y += line_height

    f_hint = poppins(24, "Bold")
    draw_centered_text(draw, "DIE FAKTEN  →", f_hint, SIZE - 100, VIOLET)
    return canvas


def make_original_insight_slide(text, index, total):
    """Folie 3..N: grosse Verlaufs-Nummer ("01", "02" …) + eine konkrete
    Kernaussage — das "Countdown"-Muster, das Leser:innen zum
    Weiterwischen bis zum Ende animiert, statt alles auf einmal zu zeigen."""
    canvas = _original_brand_background()
    draw = ImageDraw.Draw(canvas)

    num_text = f"{index:02d}"
    f_num = poppins(140, "Bold")
    bbox = draw.textbbox((0, 0), num_text, font=f_num)
    nw, nh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    num_img = Image.new("RGBA", (nw + 20, nh + 40), (0, 0, 0, 0))
    nd = ImageDraw.Draw(num_img)
    nd.text((0, -bbox[1]), num_text, font=f_num, fill=(255, 255, 255, 255))
    grad = Image.new("RGBA", num_img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for x in range(num_img.width):
        t = x / num_img.width
        c = tuple(int(VIOLET[k] + (MAGENTA[k] - VIOLET[k]) * t) for k in range(3))
        gd.line([(x, 0), (x, num_img.height)], fill=(*c, 255))
    grad.putalpha(num_img.split()[3])
    canvas.paste(grad, (60, 90), grad)

    f_total = poppins(24, "Medium")
    canvas_draw = ImageDraw.Draw(canvas)
    canvas_draw.text((64, 90 + nh + 50), f"ERKENNTNIS {index} VON {total}", font=f_total, fill=MUTED)

    f_body = poppins(44, "Bold")
    max_w = SIZE - 130
    lines = wrap_text_to_width(canvas_draw, text, f_body, max_w)
    while len(lines) > 6 and f_body.size > 30:
        f_body = poppins(f_body.size - 3, "Bold")
        lines = wrap_text_to_width(canvas_draw, text, f_body, max_w)
    line_height = int(f_body.size * 1.35)
    y = 90 + nh + 120
    for line in lines:
        canvas_draw.text((64, y), line, font=f_body, fill=TEXT)
        y += line_height

    return canvas


def make_original_editorial_slide(editorial_take):
    """Letzte Inhalts-Folie: die redaktionelle Einschätzung, zitatartig
    und prominent inszeniert — vermittelt, dass hier eine eigene
    Expertise/Meinung steckt, nicht nur eine Zusammenfassung von Fakten."""
    canvas = _original_brand_background()
    draw = ImageDraw.Draw(canvas)

    f_label = poppins(26, "Bold")
    draw_centered_text(draw, "LOADOUT-EINSCHÄTZUNG", f_label, 130, VIOLET)
    _draw_gradient_line(canvas, SIZE // 2, 180, width=60)

    f_take = poppins(40, "Medium")
    max_w = SIZE - 160
    lines = wrap_text_to_width(draw, editorial_take, f_take, max_w)
    while len(lines) > 8 and f_take.size > 28:
        f_take = poppins(f_take.size - 3, "Medium")
        lines = wrap_text_to_width(draw, editorial_take, f_take, max_w)
    line_height = int(f_take.size * 1.4)
    total_h = line_height * len(lines)
    y = (SIZE - total_h) / 2 + 40
    for line in lines:
        draw_centered_text(draw, line, f_take, y, TEXT)
        y += line_height

    return canvas


def generate_original_slides(article, output_dir, run_id, max_insights=2):
    """Orchestriert die komplette Premium-Folienserie für den LOADOUT-
    Original-Artikel: Cover, Hook, bis zu max_insights Insight-Folien,
    Einschätzung. Die feste Outro-Folie wird — wie beim normalen Artikel-
    Karussell auch — NICHT hier erzeugt, sondern vom aufrufenden Code
    separat angehängt (siehe social-assets/outro-slide.jpg)."""
    os.makedirs(output_dir, exist_ok=True)
    paths = []

    image_bytes = _download_image(article.get("image"))

    cover = make_original_cover_slide(image_bytes, article["title"])
    cover_path = os.path.join(output_dir, f"{run_id}-00-cover.jpg")
    cover.save(cover_path, quality=90)
    paths.append(cover_path)

    hook = make_original_hook_slide(article.get("teaser", ""))
    hook_path = os.path.join(output_dir, f"{run_id}-01-hook.jpg")
    hook.save(hook_path, quality=90)
    paths.append(hook_path)

    body = [p for p in article.get("body", []) if p and len(p) > 20][:max_insights]
    for i, paragraph in enumerate(body, start=1):
        insight = make_original_insight_slide(paragraph, i, len(body))
        insight_path = os.path.join(output_dir, f"{run_id}-{i+1:02d}-insight.jpg")
        insight.save(insight_path, quality=90)
        paths.append(insight_path)

    if article.get("editorial_take"):
        editorial = make_original_editorial_slide(article["editorial_take"])
        editorial_path = os.path.join(output_dir, f"{run_id}-{len(paths):02d}-einschaetzung.jpg")
        editorial.save(editorial_path, quality=90)
        paths.append(editorial_path)

    return paths


# --- Breaking News: eigenständiges, alarmierendes Design --------------------
# Bewusst NICHT die normalen Violett/Magenta-Markenfarben, sondern
# Rot/Amber — signalisiert auf den ersten Blick "hier passiert gerade
# etwas Dringendes", klar unterscheidbar von den normalen Artikel- und
# Original-Posts. Kurz gehalten (2 Inhalts-Folien statt 4-5) — bei
# Breaking News zählt Schnelligkeit und Klarheit, nicht epische Länge.

BREAKING_RED = (255, 59, 48)
BREAKING_AMBER = (255, 149, 0)


def _breaking_background():
    glow1 = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(glow1).ellipse([-250, -350, 650, 350], fill=(*BREAKING_RED, 70))
    glow1 = glow1.filter(ImageFilter.GaussianBlur(190))
    glow2 = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(glow2).ellipse([500, 700, 1300, 1400], fill=(*BREAKING_AMBER, 55))
    glow2 = glow2.filter(ImageFilter.GaussianBlur(190))
    base = Image.new("RGBA", (SIZE, SIZE), (*BG, 255))
    base = Image.alpha_composite(base, glow1)
    base = Image.alpha_composite(base, glow2)
    return base.convert("RGB")


def _draw_warning_triangle(draw, cx, cy, size, color):
    """Selbst gezeichnetes Warndreieck statt Emoji — zuverlässig in jeder
    Umgebung darstellbar (siehe frühere Emoji-Darstellungsprobleme)."""
    h = size * 0.87
    p1 = (cx, cy - h * 2 / 3)
    p2 = (cx - size / 2, cy + h / 3)
    p3 = (cx + size / 2, cy + h / 3)
    draw.polygon([p1, p2, p3], outline=color, width=4)
    draw.line([(cx, cy - h / 6), (cx, cy + h / 10)], fill=color, width=4)
    draw.ellipse([cx - 3, cy + h / 6 - 3, cx + 3, cy + h / 6 + 3], fill=color)


def make_breaking_cover_slide(image_bytes, headline):
    """Folie 1: Artikelbild mit rötlich getöntem Alarm-Verlauf, blockiges
    'BREAKING'-Badge (volltonrot statt der sonst üblichen Verlauf-Pillen),
    grosse Schlagzeile."""
    bg = _decode_image(image_bytes, SIZE, SIZE, BG).convert("RGBA")

    gradient = Image.new("L", (1, SIZE))
    for y in range(SIZE):
        t = y / SIZE
        if t < 0.22:
            alpha = int(160 - (t / 0.22) * 70)
        elif t < 0.55:
            alpha = int(90 + ((t - 0.22) / 0.33) * 10)
        else:
            alpha = int(100 + ((t - 0.55) / 0.45) * 155)
        gradient.putpixel((0, y), min(alpha, 255))
    gradient = gradient.resize((SIZE, SIZE))
    dark_layer = Image.new("RGBA", (SIZE, SIZE), (*BG, 255))
    bg = Image.composite(dark_layer, bg, gradient)

    # Roter Tönungsschleier übers ganze Bild — verstärkt den Alarm-Charakter
    red_tint = Image.new("RGBA", (SIZE, SIZE), (*BREAKING_RED, 28))
    bg = Image.alpha_composite(bg, red_tint)

    draw = ImageDraw.Draw(bg)

    f_badge = poppins(30, "Bold")
    badge_text = "BREAKING"
    bbox = draw.textbbox((0, 0), badge_text, font=f_badge)
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 26, 14
    badge_w, badge_h = bw + pad_x * 2, bh + pad_y * 2
    badge_x = (SIZE - badge_w) // 2
    badge_y = 56
    draw.rectangle([badge_x, badge_y, badge_x + badge_w, badge_y + badge_h], fill=BREAKING_RED)
    draw.text((badge_x + pad_x, badge_y + pad_y - bbox[1]), badge_text, font=f_badge, fill=(255, 255, 255))

    f_sub = poppins(22, "Medium")
    draw_centered_text(draw, "LOADOUT-NEWS EILMELDUNG", f_sub, badge_y + badge_h + 16, MUTED)

    f_title = poppins(60, "Bold")
    max_w = SIZE - 120
    lines = wrap_text_to_width(draw, headline, f_title, max_w)
    while len(lines) > 4 and f_title.size > 40:
        f_title = poppins(f_title.size - 4, "Bold")
        lines = wrap_text_to_width(draw, headline, f_title, max_w)
    line_height = int(f_title.size * 1.15)
    total_h = line_height * len(lines)
    y_start = SIZE - 100 - total_h
    y = y_start
    for line in lines:
        draw.text((60, y), line, font=f_title, fill=TEXT)
        y += line_height

    return bg.convert("RGB")


def make_breaking_fact_slide(fact_text, label="WAS BISHER BEKANNT IST"):
    """Folie 2: Warndreieck + die konkrete Kernaussage — klar, knapp,
    ohne Ablenkung."""
    canvas = _breaking_background()
    draw = ImageDraw.Draw(canvas)

    _draw_warning_triangle(draw, SIZE // 2, 170, 90, BREAKING_RED)

    f_label = poppins(26, "Bold")
    draw_centered_text(draw, label, f_label, 250, BREAKING_AMBER)

    f_fact = poppins(46, "Bold")
    max_w = SIZE - 150
    lines = wrap_text_to_width(draw, fact_text, f_fact, max_w)
    while len(lines) > 7 and f_fact.size > 30:
        f_fact = poppins(f_fact.size - 3, "Bold")
        lines = wrap_text_to_width(draw, fact_text, f_fact, max_w)
    line_height = int(f_fact.size * 1.35)
    total_h = line_height * len(lines)
    y = (SIZE - total_h) / 2 + 60
    for line in lines:
        draw_centered_text(draw, line, f_fact, y, TEXT)
        y += line_height

    f_hint = poppins(22, "Medium")
    draw_centered_text(draw, "Wir halten euch auf dem Laufenden", f_hint, SIZE - 90, MUTED)

    return canvas


def generate_breaking_slides(article, output_dir, run_id):
    """Orchestriert die Breaking-News-Folienserie: Cover + 1 Fakt-Folie.
    Bewusst kurz (2 Inhalts-Folien statt 4-5 wie beim Original-Post) —
    bei Breaking News zählt Tempo. Die feste Outro-Folie wird wie überall
    vom aufrufenden Code separat angehängt."""
    os.makedirs(output_dir, exist_ok=True)
    paths = []

    image_bytes = _download_image(article.get("image"))

    cover = make_breaking_cover_slide(image_bytes, article["title"])
    cover_path = os.path.join(output_dir, f"{run_id}-00-cover.jpg")
    cover.save(cover_path, quality=90)
    paths.append(cover_path)

    fact_source = article.get("teaser") or (article.get("body") or [""])[0]
    if fact_source:
        fact = make_breaking_fact_slide(fact_source)
        fact_path = os.path.join(output_dir, f"{run_id}-01-fakt.jpg")
        fact.save(fact_path, quality=90)
        paths.append(fact_path)

    return paths


if __name__ == "__main__":
    # Manueller Test-/Vorschau-Modus: erzeugt alle Folien-Typen mit
    # Beispieldaten in /tmp, ohne echte Artikel oder Netzwerkzugriff nötig.
    os.makedirs("/tmp/slide-preview", exist_ok=True)
    make_intro_slide([], 4, "GTA 6 hat jetzt einen Preis").save("/tmp/slide-preview/intro.jpg", quality=92)
    make_outro_slide().save("/tmp/slide-preview/outro.jpg", quality=92)
    print("Vorschau-Folien in /tmp/slide-preview/ gespeichert")
