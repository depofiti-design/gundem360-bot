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

BASE_DIR = Path(__file__).resolve().parent
SEEN_FILE = BASE_DIR / "seen.json"
MAX_SEEN_KEPT = 1500
MAX_POSTS_PER_RUN = 12
MAX_POSTS_PER_FEED = 2
SUMMARY_MAX_LEN = 280
CAPTION_SUMMARY_MAX_LEN = 180  # Telegram photo captions are capped at 1024 chars
DELAY_BETWEEN_POSTS = 4  # seconds, stays well under Telegram's rate limits

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
    ("BBC World", "http://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
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


def build_message(source_name: str, entry, summary_max_len: int = SUMMARY_MAX_LEN) -> str:
    raw_title = strip_html(entry.get("title", ""))
    raw_summary = strip_html(entry.get("summary", "") or entry.get("description", ""))

    summary = raw_summary
    if len(summary) > summary_max_len:
        summary = summary[:summary_max_len].rsplit(" ", 1)[0] + "..."

    parts = []
    if is_breaking(raw_title, raw_summary):
        parts.append("🚨 <b>SON DAKİKA</b> 🚨")
    parts.append(f"<b>{html.escape(raw_title)}</b>")
    if summary:
        parts.append(html.escape(summary))
    parts.append(f"Kaynak: {html.escape(source_name)}")
    parts.append("<i>gundem360</i>")
    return "\n\n".join(parts)


def send_to_telegram(text: str) -> bool:
    if not BOT_TOKEN:
        print("HATA: TELEGRAM_BOT_TOKEN ortam degiskeni bulunamadi.", file=sys.stderr)
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        data={
            "chat_id": CHANNEL,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=15,
    )
    if resp.status_code != 200:
        print(f"Telegram hatasi ({resp.status_code}): {resp.text}", file=sys.stderr)
        return False
    return True


def send_photo_to_telegram(image_url: str, caption: str) -> bool:
    if not BOT_TOKEN:
        print("HATA: TELEGRAM_BOT_TOKEN ortam degiskeni bulunamadi.", file=sys.stderr)
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    resp = requests.post(
        url,
        data={
            "chat_id": CHANNEL,
            "photo": image_url,
            "caption": caption,
            "parse_mode": "HTML",
        },
        timeout=20,
    )
    if resp.status_code != 200:
        print(f"Telegram foto hatasi ({resp.status_code}): {resp.text}", file=sys.stderr)
        return False
    return True


def post_entry(source_name: str, entry) -> bool:
    image_url = find_image(entry)
    if image_url:
        caption = build_message(source_name, entry, summary_max_len=CAPTION_SUMMARY_MAX_LEN)
        if send_photo_to_telegram(image_url, caption):
            return True
        # Image failed to send (bad url, hotlink block, wrong format) - fall back to text.
    return send_to_telegram(build_message(source_name, entry))


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

            if post_entry(source_name, entry):
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