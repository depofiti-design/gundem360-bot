import io
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE_DIR = Path(__file__).resolve().parent
FONTS_DIR = BASE_DIR / "assets" / "fonts"

CARD_SIZE = 1080
MARGIN = 48
PHOTO_H = 620
PANEL_COLOR = (8, 14, 30)
LOGO_PATH = BASE_DIR / "assets" / "logo.png"

CATEGORY_RULES = [
    ("SPOR", ("maç", "gol", "transfer", "lig", "futbol", "basketbol", "voleybol", "şampiyon", "derbi", "milli takım", "teknik direktör")),
    ("EKONOMİ", ("dolar", "euro", "borsa", "enflasyon", " zam", "fiyat", "ekonomi", "faiz", "bütçe", "ihracat", "vergi", "piyasa")),
    ("DÜNYA", ("abd", "rusya", "çin", "avrupa", "ukrayna", "i̇srail", "israil", "gazze", "i̇ran", "iran", "nato", "birleşmiş milletler", "washington", "beyaz saray")),
    ("SAĞLIK", ("hastane", "doktor", "sağlık", "ilaç", "aşı", "ameliyat", "virüs", "salgın")),
    ("TEKNOLOJİ", ("yapay zeka", "teknoloji", "telefon", "uygulama", "yazılım", "elektrikli araç", "uzay", "roket")),
]
DEFAULT_CATEGORY = "GÜNDEM"

CATEGORY_EMOJI = {"SPOR": "⚽", "EKONOMİ": "💰", "DÜNYA": "🌍", "SAĞLIK": "🩺", "TEKNOLOJİ": "💻", "GÜNDEM": "📰"}

CATEGORY_COLORS = {
    "SPOR": (45, 108, 223),
    "EKONOMİ": (31, 138, 112),
    "DÜNYA": (108, 63, 199),
    "SAĞLIK": (214, 51, 108),
    "TEKNOLOJİ": (76, 95, 213),
    "GÜNDEM": (224, 142, 11),
}
BREAKING_RED = (210, 24, 24)


def _match_category(text: str):
    for label, keywords in CATEGORY_RULES:
        for kw in keywords:
            # keyword must start a word ("abd" must not match "Abdullah"); suffixes are allowed
            word = kw.strip()
            # short acronyms/words additionally allow at most a 3-letter suffix ("abd" must not match "abdullah")
            tail = r"(?![a-zçğıöşü]{4})" if len(word) <= 4 else ""
            if re.search(r"(?<!\w)" + re.escape(word) + tail, text):
                return label
    return None


def categorize(title: str, body: str = "") -> str:
    # The headline decides first; the body only breaks the tie when the headline is neutral.
    return _match_category(title.lower()) or _match_category(body.lower()) or DEFAULT_CATEGORY


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
    for size in range(68, 37, -4):
        font = _font("Poppins-ExtraBold.ttf", size)
        lines = _wrap_text(draw, headline, font, max_width)
        line_height = (font.getbbox("Ağİ")[3] - font.getbbox("Ağİ")[1]) + 14
        block_height = line_height * len(lines)
        if len(lines) <= 4 and block_height <= max_height:
            return font, lines, line_height
    # fallback: smallest size, truncate to 4 lines
    font = _font("Poppins-ExtraBold.ttf", 38)
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


def _cover(img: Image.Image, width: int, height: int, focus_y: float = 0.38) -> Image.Image:
    # Scale to cover the box, crop with a slight upward bias (heads/faces sit high in frame).
    w, h = img.size
    scale = max(width / w, height / h)
    new_w, new_h = max(width, round(w * scale)), max(height, round(h * scale))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    if scale > 1.15:
        img = img.filter(ImageFilter.UnsharpMask(radius=1.4, percent=70, threshold=2))
    left = (new_w - width) // 2
    top = int((new_h - height) * focus_y)
    return img.crop((left, top, left + width, top + height))


def _logo(size: int) -> Image.Image:
    return Image.open(LOGO_PATH).convert("RGBA").resize((size, size), Image.LANCZOS)


def _no_photo_area(category: str) -> Image.Image:
    # No usable photo: category-tinted gradient with the big brand logo, so the card still looks intentional.
    base = CATEGORY_COLORS.get(category, CATEGORY_COLORS[DEFAULT_CATEGORY])
    top_color = tuple(int(c * 0.55) for c in base)
    img = Image.new("RGB", (CARD_SIZE, PHOTO_H))
    draw = ImageDraw.Draw(img)
    for y in range(PHOTO_H):
        t = y / PHOTO_H
        row = tuple(int(top_color[i] + (PANEL_COLOR[i] - top_color[i]) * t) for i in range(3))
        draw.line([(0, y), (CARD_SIZE, y)], fill=row)
    logo = _logo(300)
    img.paste(logo, ((CARD_SIZE - 300) // 2, (PHOTO_H - 300) // 2 - 10), logo)
    return img


def _fade_into_panel(card: Image.Image) -> None:
    # Short smooth blend from the (untouched, clear) photo into the dark text panel.
    fade_h = 110
    overlay = Image.new("RGBA", (CARD_SIZE, fade_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(fade_h):
        alpha = int(255 * ((y / (fade_h - 1)) ** 1.6))
        draw.line([(0, y), (CARD_SIZE, y)], fill=PANEL_COLOR + (alpha,))
    region = card.crop((0, PHOTO_H - fade_h, CARD_SIZE, PHOTO_H)).convert("RGBA")
    card.paste(Image.alpha_composite(region, overlay).convert("RGB"), (0, PHOTO_H - fade_h))


def _translucent_pill(card: Image.Image, xy, text, font, alpha=130):
    x, y = xy
    draw = ImageDraw.Draw(card)
    bbox = font.getbbox(text)
    w = int(draw.textlength(text, font=font)) + 36
    h = (bbox[3] - bbox[1]) + 22
    layer = Image.new("RGBA", card.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=(0, 0, 0, alpha))
    merged = Image.alpha_composite(card.convert("RGBA"), layer).convert("RGB")
    card.paste(merged)
    ImageDraw.Draw(card).text((x + 18, y + 11 - bbox[1]), text, font=font, fill="white")
    return w


def generate_card(photo_bytes: bytes | None, headline: str, category: str, breaking: bool, source_label: str = "") -> bytes:
    card = Image.new("RGB", (CARD_SIZE, CARD_SIZE), PANEL_COLOR)
    if photo_bytes:
        photo = _cover(Image.open(io.BytesIO(photo_bytes)).convert("RGB"), CARD_SIZE, PHOTO_H)
        card.paste(photo, (0, 0))
        _fade_into_panel(card)
        # Small logo badge over the photo (white circle reads on any picture).
        logo_size = 96
        shadow = Image.new("RGBA", card.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).ellipse([MARGIN - 4, 34, MARGIN + logo_size + 4, 34 + logo_size + 8], fill=(0, 0, 0, 90))
        shadow = shadow.filter(ImageFilter.GaussianBlur(8))
        card.paste(Image.alpha_composite(card.convert("RGBA"), shadow).convert("RGB"))
        logo = _logo(logo_size)
        card.paste(logo, (MARGIN, 32), logo)
    else:
        card.paste(_no_photo_area(category), (0, 0))

    font_handle = _font("Poppins-Bold.ttf", 22)
    handle = "t.me/gundem360haber"
    handle_w = int(ImageDraw.Draw(card).textlength(handle, font=font_handle)) + 36
    _translucent_pill(card, (CARD_SIZE - MARGIN - handle_w, 46), handle, font_handle)

    draw = ImageDraw.Draw(card)
    font_badge = _font("Poppins-ExtraBold.ttf", 26)
    font_tag = _font("Poppins-Bold.ttf", 24)
    font_source = _font("Poppins-SemiBold.ttf", 22)

    pills_y = PHOTO_H + 4
    x = MARGIN
    if breaking:
        x += _rounded_pill(draw, (x, pills_y), "SON DAKİKA", font_badge, "white", BREAKING_RED) + 14
    tag_color = CATEGORY_COLORS.get(category, CATEGORY_COLORS[DEFAULT_CATEGORY])
    _rounded_pill(draw, (x, pills_y), category, font_tag, "white", tag_color)
    if source_label:
        label = source_label.upper()
        label_w = draw.textlength(label, font=font_source)
        draw.text((CARD_SIZE - MARGIN - label_w, pills_y + 12), label, font=font_source, fill=(150, 162, 190))

    headline_top = pills_y + 50 + 26
    max_height = CARD_SIZE - 44 - headline_top
    font_headline, lines, line_height = _fit_headline(draw, headline, CARD_SIZE - MARGIN * 2, max_height)
    y = headline_top
    for line in lines:
        draw.text((MARGIN, y), line, font=font_headline, fill="white")
        y += line_height

    buf = io.BytesIO()
    card.save(buf, format="JPEG", quality=92, subsampling=0)
    return buf.getvalue()
