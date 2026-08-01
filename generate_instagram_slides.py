"""
LOADOUT-NEWS — Instagram-Karussell-Folien-Generator
=======================================================
Erzeugt professionell gestaltete, gebrandete Bilder für den Instagram-
Karussell-Post, statt einfach nur die rohen Artikel-Bilder zu verwenden:

  - Folie 1 (Intro):    Fester LOADOUT-Marken-Hintergrund + Logo +
                         dynamischer Text ("X neue Artikel", Top-Artikel)
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
import os
import textwrap

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter

SIZE = 1080  # Instagram-Quadrat-Format

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


def cover_crop(img, size):
    """Skaliert und beschneidet ein Bild mittig auf ein Quadrat
    (entspricht CSS background-size:cover)."""
    w, h = img.size
    scale = max(size / w, size / h)
    new_w, new_h = int(w * scale), int(h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - size) // 2
    top = (new_h - size) // 2
    return img.crop((left, top, left + size, top + size))


# --- Folie 1: Intro ---------------------------------------------------------

def make_intro_slide(article_count, top_title):
    bg = make_brand_background(glow_top_right=True)
    draw = ImageDraw.Draw(bg)

    icon_scale = 1.9
    icon_w = int(120 * icon_scale)
    draw_logo_icon(bg, (SIZE - icon_w) // 2, 190, scale=icon_scale)
    draw_wordmark_centered(bg, 420, size=62)

    draw.line([(SIZE // 2 - 60, 545), (SIZE // 2 + 60, 545)], fill=MAGENTA, width=4)

    f_headline = poppins(72, "Bold")
    draw_centered_text(draw, f"{article_count} NEUE", f_headline, 600, TEXT)
    draw_centered_text(draw, "ARTIKEL", f_headline, 690, MAGENTA)

    f_teaser = poppins(30, "Medium")
    lines = wrap_text_to_width(draw, f"u. a. {top_title}", f_teaser, SIZE - 200)
    ty = 820
    for line in lines[:2]:
        draw_centered_text(draw, line, f_teaser, ty, MUTED)
        ty += 42

    f_swipe = poppins(26, "Bold")
    draw_centered_text(draw, "SWIPE FÜR ALLE ARTIKEL  →", f_swipe, 980, VIOLET)

    return bg


# --- Folie 2..N: Artikel -----------------------------------------------------

def make_article_slide(image_bytes, title, cat, slide_num, total_slides):
    try:
        source = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        bg = cover_crop(source, SIZE)
    except Exception:
        bg = Image.new("RGB", (SIZE, SIZE), BG)

    bg = bg.convert("RGBA")

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

def generate_all_slides(articles, output_dir, run_id):
    """Erzeugt Intro-Folie + eine Folie pro Artikel und speichert sie lokal.
    Die Outro-Folie wird bewusst NICHT hier erzeugt — die ist ein fester,
    einmalig erstellter Bestandteil des Repos (siehe social-assets/), damit
    sie garantiert bei jedem Post exakt identisch bleibt.

    run_id wird Teil jedes Dateinamens — GitHubs Rohdaten-Auslieferung
    (raw.githubusercontent.com) cached Inhalte kurzzeitig. Mit immer
    gleichen Dateinamen könnte Buffer nach einem neuen Push kurzzeitig noch
    ein Bild vom VORHERIGEN Lauf bekommen. Eindeutige Dateinamen pro Lauf
    umgehen dieses Problem zuverlässig."""
    os.makedirs(output_dir, exist_ok=True)
    paths = []

    top_article = max(articles, key=lambda a: a.get("hype", 0))
    intro = make_intro_slide(len(articles), top_article["title"])
    intro_path = os.path.join(output_dir, f"{run_id}-00-intro.jpg")
    intro.save(intro_path, quality=90)
    paths.append(intro_path)

    total = len(articles) + 2  # + Intro + Outro
    for i, a in enumerate(articles, start=1):
        image_bytes = b""
        if a.get("image"):
            try:
                resp = requests.get(a["image"], timeout=15)
                if resp.status_code == 200:
                    image_bytes = resp.content
            except Exception:
                pass
        slide = make_article_slide(image_bytes, a["title"], a.get("cat"), i + 1, total)
        slide_path = os.path.join(output_dir, f"{run_id}-{i:02d}-artikel.jpg")
        slide.save(slide_path, quality=90)
        paths.append(slide_path)

    return paths


if __name__ == "__main__":
    # Manueller Test-/Vorschau-Modus: erzeugt alle Folien-Typen mit
    # Beispieldaten in /tmp, ohne echte Artikel oder Netzwerkzugriff nötig.
    os.makedirs("/tmp/slide-preview", exist_ok=True)
    make_intro_slide(4, "GTA 6 hat jetzt einen Preis").save("/tmp/slide-preview/intro.jpg", quality=92)
    make_outro_slide().save("/tmp/slide-preview/outro.jpg", quality=92)
    print("Vorschau-Folien in /tmp/slide-preview/ gespeichert")
