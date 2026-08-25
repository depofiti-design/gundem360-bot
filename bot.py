import html
import json
import os
import random
import re
import sys
import time
from pathlib import Path

import feedparser
import requests
import trafilatura

from card import categorize, generate_card

BASE_DIR = Path(__file__).resolve().parent
SEEN_FILE = BASE_DIR / "seen.json"
MAX_SEEN_KEPT = 1500
MAX_POSTS_PER_RUN = 12
MAX_POSTS_PER_FEED = 2
SUMMARY_MAX_LEN = 800
CAPTION_SUMMARY_MAX_LEN = 650  # Telegram photo captions are capped at 1024 chars total
CARD_CAPTION_SUMMARY_LEN = 450  # shorter, since the card image itself already carries the headline
DELAY_BETWEEN_POSTS = 4  # seconds, stays well under Telegram's rate limits
ARTICLE_FETCH_TIMEOUT = 10
ARTICLE_FETCH_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

CHANNEL = "@gundem360haber"
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

SOURCES = [
    ("AA - Guncel", "https://www.aa.com.tr/tr/rss/default?cat=guncel"),
    ("AA - Dunya", "https://www.aa.com.tr/tr/rss/default?cat=dunya"),
    ("NTV", "https://www.ntv.com.tr/gundem.rss"),
    ("Hurriyet", "https://www.hurriyet.com.tr/rss/anasayfa"),
    ("Sabah", "https://www.sabah.com.tr/rss/anasayfa.xml"),
    ("Milliyet", "https://www.milliyet.com.tr/rss/rssnew/gundemrss.xml"),
    ("CNN Turk", "https://www.cnnturk.com/feed/rss/all/news"),
    ("BBC Turkce", "https://feeds.bbci.co.uk/turkce/rss.xml"),
]

BREAKING_KEYWORDS = [
    "son dakika", "flas", "flaş", "deprem", "savas", "savaş", "saldırı", "saldiri",
    "patlama", "füze", "fuze", "ateşkes", "ateskes", "çatışma", "catisma", "bomba",
    "katliam", "işgal", "isgal", "darbe", "suikast", "ölü sayısı", "olu sayisi",
    "tahliye", "acil durum", "kriz",
]

TAG_RE = re.compile(r"<[^>]+>")
IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)


def strip_html(text: str) -> str:
    text = TAG_RE.sub("", text or "")
    return html.unescape(text).strip()


def load_seen() -> set:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def save_seen(seen_list_ordered):
    trimmed = seen_list_ordered[-MAX_SEEN_KEPT:]
    SEEN_FILE.write_text(json.dumps(trimmed, ensure_ascii=False, indent=0), encoding="utf-8")


def entry_id(entry) -> str:
    return entry.get("id") or entry.get("link") or entry.get("title", "")


def is_breaking(title: str, summary: str) -> bool:
    text = f"{title} {summary}".lower()
    return any(keyword in text for keyword in BREAKING_KEYWORDS)


def find_image(entry) -> str | None:
    for key in ("media_content", "media_thumbnail"):
        media = entry.get(key)
        if media:
            url = media[0].get("url")
            if url:
                return url

    for enc in entry.get("enclosures", []) or []:
        enc_type = enc.get("type", "")
        url = enc.get("href") or enc.get("url")
        if url and (enc_type.startswith("image") or re.search(r"\.(jpg|jpeg|png|webp)(\?|$)", url, re.IGNORECASE)):
            return url

    raw = entry.get("summary", "") or entry.get("description", "")
    match = IMG_SRC_RE.search(raw)
    if match:
        return match.group(1)
    return None


def fetch_full_text(url: str) -> str | None:
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=ARTICLE_FETCH_TIMEOUT, headers=ARTICLE_FETCH_HEADERS)
        resp.raise_for_status()
        return trafilatura.extract(resp.text, url=url, include_comments=False, include_tables=False)
    except Exception as exc:
        print(f"Tam metin alinamadi ({url}): {exc}", file=sys.stderr)
        return None


TR_MONTHS = "Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık"
DATE_LINE_RE = re.compile(
    rf"\d{{1,2}}\s+(?:{TR_MONTHS})\s+\d{{4}}(\s*G[uü]ncelleme:\s*\d{{1,2}}\s+(?:{TR_MONTHS})\s+\d{{4}})?",
    re.IGNORECASE,
)
NUMERIC_DATE_RE = re.compile(r"\d{1,2}\.\d{1,2}\.\d{4}(\s+\d{1,2}:\d{2})?")
UPDATE_LABEL_RE = re.compile(r"(Son\s+)?G[uü]ncelleme(\s*Tarihi)?\s*:?", re.IGNORECASE)
SOCIAL_NOISE_LINE_RE = re.compile(
    r"^(#\S+"
    r"|[—-]\s*.+\(@\w+\).*"
    r"|(B[uü]y[uü]kl[uü]k|Yer|Tarih|Saat|Enlem|Boylam|Derinlik|Detay)\s*:.*"
    r")$",
    re.IGNORECASE,
)


def strip_boilerplate(text: str, title: str = "") -> str:
    text = UPDATE_LABEL_RE.sub("", text)
    text = DATE_LINE_RE.sub("", text)
    text = NUMERIC_DATE_RE.sub("", text)

    title_norm = title.strip().casefold()
    lines = [
        line.strip()
        for line in text.split("\n")
        if line.strip() and not SOCIAL_NOISE_LINE_RE.match(line.strip())
    ]
    while lines:
        first = lines[0]
        first_norm = first.casefold()
        is_title_dup = title_norm and (
            first_norm == title_norm or (len(title_norm) > 20 and first_norm.startswith(title_norm[:40]))
        )
        if is_title_dup:
            lines.pop(0)
            continue
        looks_like_prose = len(first) > 80 or re.search(r"[.!?]", first)
        if looks_like_prose:
            break
        lines.pop(0)
    return "\n".join(lines).strip()


def clean_rss_teaser(entry) -> str:
    raw = strip_html(entry.get("summary", "") or entry.get("description", ""))
    raw = re.sub(r"devam\w*\s+i[cç]in\s+t[ıi]klay[ıi]n[ıi]z\.?", "", raw, flags=re.IGNORECASE)
    return raw.strip()


def get_body_text(entry) -> str:
    full_text = fetch_full_text(entry.get("link", ""))
    if full_text:
        full_text = strip_boilerplate(full_text, title=strip_html(entry.get("title", "")))
        if len(full_text) > 40:
            return full_text
    return clean_rss_teaser(entry)


def clean_excerpt(text: str, max_len: int) -> str:
    text = (text or "").strip()
    if not text or len(text) <= max_len:
        return text

    sentences = re.split(r"(?<=[.!?])\s+", text)
    picked = []
    total = 0
    for sentence in sentences:
        if picked and total + len(sentence) + 1 > max_len:
            break
        picked.append(sentence)
        total += len(sentence) + 1

    excerpt = " ".join(picked).strip()
    if not excerpt:
        excerpt = text[:max_len].rsplit(" ", 1)[0].strip()
    if len(excerpt) < len(text):
        excerpt = excerpt.rstrip(".") + "..."
    return excerpt


def build_message(source_name: str, entry, body_text: str, summary_max_len: int = SUMMARY_MAX_LEN) -> str:
    raw_title = strip_html(entry.get("title", ""))
    summary = clean_excerpt(body_text, summary_max_len)

    parts = []
    if is_breaking(raw_title, body_text[:300]):
        parts.append("🚨 <b>SON DAKİKA</b> 🚨")
    parts.append(f"<b>{html.escape(raw_title)}</b>")
    if summary:
        parts.append(html.escape(summary))
    parts.append(f"Kaynak: {html.escape(source_name)}")
    parts.append("<i>gundem360</i>")
    return "\n\n".join(parts)


TELEGRAM_RETRIES = 3
TELEGRAM_RETRY_DELAY = 5  # seconds


def telegram_post(method: str, data: dict, timeout: int, files: dict | None = None) -> bool:
    if not BOT_TOKEN:
        print("HATA: TELEGRAM_BOT_TOKEN ortam degiskeni bulunamadi.", file=sys.stderr)
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    for attempt in range(1, TELEGRAM_RETRIES + 1):
        try:
            resp = requests.post(url, data=data, timeout=timeout, files=files)
        except requests.exceptions.RequestException as exc:
            print(f"Telegram istegi basarisiz (deneme {attempt}/{TELEGRAM_RETRIES}): {exc}", file=sys.stderr)
        else:
            if resp.status_code == 200:
                return True
            print(f"Telegram hatasi ({resp.status_code}, deneme {attempt}/{TELEGRAM_RETRIES}): {resp.text}", file=sys.stderr)
            if resp.status_code < 500 and resp.status_code != 429:
                return False  # client-side error (bad request etc.) - retrying won't help
        if attempt < TELEGRAM_RETRIES:
            time.sleep(TELEGRAM_RETRY_DELAY)
    return False


def send_to_telegram(text: str) -> bool:
    return telegram_post("sendMessage", {
        "chat_id": CHANNEL,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }, timeout=15)


def send_photo_to_telegram(image_url: str, caption: str) -> bool:
    return telegram_post("sendPhoto", {
        "chat_id": CHANNEL,
        "photo": image_url,
        "caption": caption,
        "parse_mode": "HTML",
    }, timeout=20)


def send_card_to_telegram(image_bytes: bytes, caption: str) -> bool:
    return telegram_post(
        "sendPhoto",
        {"chat_id": CHANNEL, "caption": caption, "parse_mode": "HTML"},
        timeout=25,
        files={"photo": ("gundem360.jpg", image_bytes, "image/jpeg")},
    )


def build_card_caption(source_name: str, body_text: str) -> str:
    summary = clean_excerpt(body_text, CARD_CAPTION_SUMMARY_LEN)
    parts = []
    if summary:
        parts.append(f"<b>{html.escape(summary)}</b>")
    parts.append(f"Kaynak: {html.escape(source_name)}")
    parts.append("<i>gundem360</i>")
    return "\n\n".join(parts)


def try_post_card(source_name: str, raw_title: str, body_text: str, image_url: str | None, breaking: bool) -> bool:
    try:
        photo_bytes = None
        if image_url:
            resp = requests.get(image_url, timeout=ARTICLE_FETCH_TIMEOUT, headers=ARTICLE_FETCH_HEADERS)
            resp.raise_for_status()
            photo_bytes = resp.content
        category = categorize(source_name, raw_title, body_text[:500])
        card_bytes = generate_card(photo_bytes, raw_title, category, breaking)
    except Exception as exc:
        print(f"Kart olusturulamadi ({image_url}): {exc}", file=sys.stderr)
        return False

    caption = build_card_caption(source_name, body_text)
    return send_card_to_telegram(card_bytes, caption)


def post_entry(source_name: str, entry) -> bool:
    body_text = get_body_text(entry)
    raw_title = strip_html(entry.get("title", ""))
    breaking = is_breaking(raw_title, body_text[:300])
    image_url = find_image(entry)

    if try_post_card(source_name, raw_title, body_text, image_url, breaking):
        return True

    # Card generation/send failed - fall back to a plain photo or text post.
    if image_url:
        caption = build_message(source_name, entry, body_text, summary_max_len=CAPTION_SUMMARY_MAX_LEN)
        if send_photo_to_telegram(image_url, caption):
            return True
    return send_to_telegram(build_message(source_name, entry, body_text, summary_max_len=SUMMARY_MAX_LEN))


def main():
    seen = load_seen()
    is_bootstrap = len(seen) == 0
    seen_order = list(seen)
    posted = 0

    sources = list(SOURCES)
    random.shuffle(sources)

    for source_name, url in sources:
        try:
            feed = feedparser.parse(url)
        except Exception as exc:  # network/parse errors shouldn't kill the whole run
            print(f"Feed okunamadi ({source_name}): {exc}", file=sys.stderr)
            continue

        new_from_feed = 0
        for entry in feed.entries:
            eid = entry_id(entry)
            if not eid or eid in seen:
                continue

            if is_bootstrap:
                # First ever run: seed the seen-list without posting, so we don't
                # dump the whole backlog into the channel at once.
                seen.add(eid)
                seen_order.append(eid)
                continue

            if new_from_feed >= MAX_POSTS_PER_FEED or posted >= MAX_POSTS_PER_RUN:
                break

            try:
                sent = post_entry(source_name, entry)
            except Exception as exc:  # a single bad entry shouldn't kill the whole run
                print(f"Haber gonderilemedi ({source_name}): {exc}", file=sys.stderr)
                sent = False

            if sent:
                seen.add(eid)
                seen_order.append(eid)
                posted += 1
                new_from_feed += 1
                time.sleep(DELAY_BETWEEN_POSTS)

        if posted >= MAX_POSTS_PER_RUN:
            break

    save_seen(seen_order)
    print(f"Bitti. Yeni gonderilen: {posted}. Bootstrap: {is_bootstrap}.")


if __name__ == "__main__":
    main()