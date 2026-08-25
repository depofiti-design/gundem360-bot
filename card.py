import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

BASE_DIR = Path(__file__).resolve().parent
FONTS_DIR = BASE_DIR / "assets" / "fonts"

CARD_SIZE = 1080
MARGIN = 56

CATEGORY_RULES = [
    ("SPOR", ("maç", "gol", "transfer", "lig", "futbol", "basketbol", "voleybol", "şampiyon", "derbi", "milli takım", "teknik direktör")),
    ("EKONOMİ", ("dolar", "euro", "borsa", "enflasyon", " zam", "fiyat", "ekonomi", "faiz", "bütçe", "ihracat", "vergi", "piyasa")),
    ("DÜNYA", ("abd", "rusya", "çin", "avrupa", "ukrayna", "i̇srail", "israil", "gazze", "i̇ran", "iran", "nato", "birleşmiş milletler", "washington", "beyaz saray")),
    ("SAĞLIK", ("hastane", "doktor", "sağlık", "ilaç", "aşı", "ameliyat", "virüs", "salgın")),
    ("TEKNOLOJİ", ("yapay zeka", "teknoloji", "telefon", "uygulama", "yazılım", "elektrikli araç", "uzay", "roket")),
]
DEFAULT_CATEGORY = "GÜNDEM"

CATEGORY_COLORS = {
    "SPOR": (45, 108, 223),
    "EKONOMİ": (31, 138, 112),
    "DÜNYA": (108, 63, 199),
    "SAĞLIK": (214, 51, 108),
    "TEKNOLOJİ": (76, 95, 213),
    "GÜNDEM": (224, 142, 11),
}
BREAKING_RED = (210, 24, 24)


def categorize(*texts: str) -> str:
    joined = " ".join(texts).lower()
    for label, keywords in CATEGORY_RULES:
        if any(kw in joined for kw in keywords):
            return label
    return DEFAULT_CATEGORY


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS_DIR / name), size)


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit_headline(draw, headline: str, max_width: int, max_height: int):
    for size in range(72, 39, -4):
        font = _font("Poppins-ExtraBold.ttf", size)
        lines = _wrap_text(draw, headline, font, max_width)
        line_height = (font.getbbox("Ağİ")[3] - font.getbbox("Ağİ")[1]) + 14
        block_height = line_height * len(lines)
        if len(lines) <= 4 and block_height <= max_height:
            return font, lines, line_height
    # fallback: smallest size, truncate to 4 lines
    font = _font("Poppins-ExtraBold.ttf", 40)
    lines = _wrap_text(draw, headline, font, max_width)[:4]
    line_height = (font.getbbox("Ağİ")[3] - font.getbbox("Ağİ")[1]) + 14
    return font, lines, line_height


def _rounded_pill(draw, xy, text, font, fg, bg, pad_x=22, pad_y=12):
    x, y = xy
    text_w = draw.textlength(text, font=font)
    bbox = font.getbbox(text)
    text_h = bbox[3] - bbox[1]
    box = [x, y, x + text_w + pad_x * 2, y + text_h + pad_y * 2]
    draw.rounded_rectangle(box, radius=(box[3] - box[1]) // 2, fill=bg)
    draw.text((x + pad_x, y + pad_y - bbox[1]), text, font=font, fill=fg)
    return box[2] - box[0]  # width consumed


def _fit_cover(img: Image.Image) -> Image.Image:
    w, h = img.size
    scale = CARD_SIZE / min(w, h)
    img = img.resize((max(CARD_SIZE, round(w * scale)), max(CARD_SIZE, round(h * scale))), Image.LANCZOS)
    w, h = img.size
    left, top = (w - CARD_SIZE) // 2, (h - CARD_SIZE) // 2
    return img.crop((left, top, left + CARD_SIZE, top + CARD_SIZE))


def _solid_background(category: str) -> Image.Image:
    # Used only when the article has no photo, so every post still gets a branded card.
    base = CATEGORY_COLORS.get(category, CATEGORY_COLORS[DEFAULT_CATEGORY])
    top_color = (20, 21, 26)
    bottom_color = tuple(int(c * 0.4) for c in base)
    img = Image.new("RGB", (CARD_SIZE, CARD_SIZE))
    draw = ImageDraw.Draw(img)
    for y in range(CARD_SIZE):
        t = y / CARD_SIZE
        row = tuple(int(top_color[i] + (bottom_color[i] - top_color[i]) * t) for i in range(3))
        draw.line([(0, y), (CARD_SIZE, y)], fill=row)
    return img


def _legibility_overlay(size: int) -> Image.Image:
    # A single smooth fade: fully clear over the photo, darkening only behind the
    # text block at the bottom. No flat wash, so photos stay bright and sharp.
    # A short, gentle top band keeps the brand/handle text readable over bright skies.
    overlay = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    top_band = int(size * 0.12)
    top_max_alpha = 80
    fade_start = 0.42
    max_alpha = 190
    for y in range(size):
        if y < top_band:
            alpha = int(top_max_alpha * (1 - y / top_band))
            draw.line([(0, y), (size, y)], fill=(0, 0, 0, alpha))
            continue
        f = y / size
        if f <= fade_start:
            continue
        t = (f - fade_start) / (1 - fade_start)
        draw.line([(0, y), (size, y)], fill=(0, 0, 0, int(max_alpha * (t ** 1.5))))
    return overlay


def generate_card(photo_bytes: bytes | None, headline: str, category: str, breaking: bool) -> bytes:
    if photo_bytes:
        img = _fit_cover(Image.open(io.BytesIO(photo_bytes)).convert("RGB"))
    else:
        img = _solid_background(category)

    img = Image.alpha_composite(img.convert("RGBA"), _legibility_overlay(CARD_SIZE)).convert("RGB")

    draw = ImageDraw.Draw(img)

    font_brand = _font("Poppins-ExtraBold.ttf", 30)
    font_handle = _font("Poppins-Bold.ttf", 20)
    font_badge = _font("Poppins-ExtraBold.ttf", 28)
    font_tag = _font("Poppins-Bold.ttf", 24)

    draw.text((MARGIN, MARGIN), "GÜNDEM360", font=font_brand, fill="white")
    handle_text = "TELEGRAM: GUNDEM360HABER"
    handle_w = draw.textlength(handle_text, font=font_handle)
    draw.text((CARD_SIZE - MARGIN - handle_w, MARGIN + 6), handle_text, font=font_handle, fill="white")

    content_width = CARD_SIZE - MARGIN * 2
    tag_y = CARD_SIZE - MARGIN - 54
    max_headline_height = int(CARD_SIZE * 0.34)
    headline_area_bottom = tag_y - 26

    font_headline, lines, line_height = _fit_headline(draw, headline, content_width, max_headline_height)
    block_height = line_height * len(lines)
    headline_top = headline_area_bottom - block_height
    badge_bottom = headline_top - 22

    y = headline_top
    for line in lines:
        draw.text((MARGIN, y), line, font=font_headline, fill="white")
        y += line_height

    if breaking:
        badge_h_est = font_badge.getbbox("SON DAKİKA")[3] + 24
        _rounded_pill(draw, (MARGIN, badge_bottom - badge_h_est), "SON DAKİKA", font_badge, "white", BREAKING_RED)

    tag_color = CATEGORY_COLORS.get(category, CATEGORY_COLORS[DEFAULT_CATEGORY])
    _rounded_pill(draw, (MARGIN, tag_y), category, font_tag, "white", tag_color)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()