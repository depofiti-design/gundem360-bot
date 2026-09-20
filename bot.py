import html
import json
import os
import random
import re
import io
import sys
import time
from calendar import timegm
from pathlib import Path

import feedparser
import requests
import trafilatura
from PIL import Image

from card import CATEGORY_EMOJI, categorize, generate_card

BASE_DIR = Path(__file__).resolve().parent
SEEN_FILE = BASE_DIR / "seen.json"
MAX_SEEN_KEPT = 3000
MAX_POSTS_PER_RUN = 12
MAX_POSTS_PER_FEED = 2
MAX_SPORTS_PER_RUN = 4
MAX_ENTRY_AGE_HOURS = 24  # older items are marked seen without posting (new feeds start with a backlog)
MIN_PHOTO_WIDTH = 500
BREAKING_MAX_AGE_HOURS = 3
SUMMARY_MAX_LEN = 800
CAPTION_SUMMARY_MAX_LEN = 650  # Telegram photo captions are capped at 1024 chars total
CARD_LEAD_LEN = 260  # bold "hook" sentences at the top of the caption
CARD_DETAIL_LEN = 420  # plain follow-up sentences below the hook
DELAY_BETWEEN_POSTS = 4  # seconds, stays well under Telegram's rate limits
ARTICLE_FETCH_TIMEOUT = 10
ARTICLE_FETCH_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

CHANNEL = "@gundem360haber"
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# (display name, feed url, forced category or None)
SOURCES = [
    ("Anadolu Ajansı", "https://www.aa.com.tr/tr/rss/default?cat=guncel", None),
    ("Anadolu Ajansı", "https://www.aa.com.tr/tr/rss/default?cat=dunya", "DÜNYA"),
    ("NTV", "https://www.ntv.com.tr/gundem.rss", None),
    ("Hürriyet", "https://www.hurriyet.com.tr/rss/anasayfa", None),
    ("Sabah", "https://www.sabah.com.tr/rss/anasayfa.xml", None),
    ("Milliyet", "https://www.milliyet.com.tr/rss/rssnew/gundemrss.xml", None),
    ("CNN Türk", "https://www.cnnturk.com/feed/rss/all/news", None),
    ("BBC Türkçe", "https://feeds.bbci.co.uk/turkce/rss.xml", None),
    ("TRT Haber", "https://www.trthaber.com/manset_articles.rss", None),
    ("Habertürk", "https://www.haberturk.com/rss", None),
    ("TRT Haber", "https://www.trthaber.com/dunya_articles.rss", "DÜNYA"),
    ("TRT Haber", "https://www.trthaber.com/ekonomi_articles.rss", "EKONOMİ"),
    ("Sabah", "https://www.sabah.com.tr/rss/ekonomi.xml", "EKONOMİ"),
    # Sports: many different outlets so the channel doesn't read like a single-source feed
    ("Hürriyet Spor", "https://www.hurriyet.com.tr/rss/spor", "SPOR"),
    ("Sabah Spor", "https://www.sabah.com.tr/rss/spor.xml", "SPOR"),
    ("TRT Spor", "https://www.trthaber.com/spor_articles.rss", "SPOR"),
    ("Fotomaç", "https://www.fotomac.com.tr/rss/anasayfa.xml", "SPOR"),
    ("Habertürk Spor", "https://www.haberturk.com/rss/spor.xml", "SPOR"),
    ("A Spor", "https://www.aspor.com.tr/rss/anasayfa.xml", "SPOR"),
    ("Takvim Spor", "https://www.takvim.com.tr/rss/spor.xml", "SPOR"),
    ("CNN Türk Spor", "https://www.cnnturk.com/feed/rss/spor/news", "SPOR"),
    ("Anadolu Ajansı Spor", "https://www.aa.com.tr/tr/rss/default?cat=spor", "SPOR"),
]

BREAKING_KEYWORDS = [
    "son dakika", "flas", "flaş", "deprem", "savas", "savaş", "saldırı", "saldiri",
    "patlama", "füze", "fuze", "ateşkes", "ateskes", "çatışma", "catisma", "bomba",
    "katliam", "işgal", "isgal", "darbe", "suikast", "ölü sayısı", "olu sayisi",
    "tahliye", "acil durum", "kriz", "hayatını kaybetti", "hayatini kaybetti", "yaşamını yitirdi",
    "vefat etti", "öldü", "yangın",
]
# Football gossip uses "kriz", "bomba", "savaş" figuratively - only literal tragedies count as breaking there.
SPORTS_BREAKING_KEYWORDS = [
    "son dakika", "flaş", "deprem", "saldırı", "hayatını kaybetti", "yaşamını yitirdi", "vefat etti", "kazası", "kazada",
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


def is_breaking(title: str, summary: str, category: str = "") -> bool:
    text = f"{title} {summary}".lower()
    keywords = SPORTS_BREAKING_KEYWORDS if category == "SPOR" else BREAKING_KEYWORDS
    return any(keyword in text for keyword in keywords)


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


OG_IMAGE_RES = [
    re.compile(r"""<meta[^>]+(?:property|name)=["'](?:og:image(?::secure_url)?|twitter:image(?::src)?)["'][^>]*content=["']([^"']+)["']""", re.IGNORECASE),
    re.compile(r"""<meta[^>]+content=["']([^"']+)["'][^>]*(?:property|name)=["'](?:og:image(?::secure_url)?|twitter:image(?::src)?)["']""", re.IGNORECASE),
]


def fetch_article(url: str) -> tuple[str | None, str]:
    """Returns (extracted article text, raw page html). Either may be empty on failure."""
    if not url:
        return None, ""
    try:
        resp = requests.get(url, timeout=ARTICLE_FETCH_TIMEOUT, headers=ARTICLE_FETCH_HEADERS)
        resp.raise_for_status()
        page = resp.text
        return trafilatura.extract(page, url=url, include_comments=False, include_tables=False), page
    except Exception as exc:
        print(f"Tam metin alinamadi ({url}): {exc}", file=sys.stderr)
        return None, ""


def og_images(page_html: str, base_url: str) -> list[str]:
    urls = []
    for pattern in OG_IMAGE_RES:
        for match in pattern.findall(page_html or ""):
            url = html.unescape(match).strip()
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = requests.compat.urljoin(base_url, url)
            if url.startswith("http") and url not in urls:
                urls.append(url)
    return urls


def best_photo(candidates: list[str]) -> bytes | None:
    """Downloads candidate images and returns the sharpest (largest) usable one, or None."""
    best_bytes, best_pixels = None, 0
    for url in candidates[:4]:
        try:
            resp = requests.get(url, timeout=ARTICLE_FETCH_TIMEOUT, headers=ARTICLE_FETCH_HEADERS)
            resp.raise_for_status()
            width, height = Image.open(io.BytesIO(resp.content)).size
        except Exception as exc:
            print(f"Gorsel alinamadi ({url}): {exc}", file=sys.stderr)
            continue
        if width < MIN_PHOTO_WIDTH or height < 250 or width / height > 3.2 or height / width > 2.0:
            continue  # thumbnail, banner or odd crop: would look blurry/stretched on the card
        if width * height > best_pixels:
            best_bytes, best_pixels = resp.content, width * height
    return best_bytes


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


AGENCY_BYLINE_RE = re.compile(
    r"[A-ZÇĞİÖŞÜ][\w.]+(?: [A-ZÇĞİÖŞÜ][\w.]+){0,2}\s*•\s*[A-ZÇĞİÖŞÜ]{3,}(?: [A-ZÇĞİÖŞÜ]{3,})?\s+"
)  # "Ceren Aydınonat • İSTANBUL " reporter/dateline prefix


def strip_boilerplate(text: str, title: str = "") -> str:
    text = AGENCY_BYLINE_RE.sub("", text)
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


def get_body_text(entry, full_text: str | None) -> str:
    title = strip_html(entry.get("title", ""))
    if full_text:
        cleaned = strip_boilerplate(full_text, title=title)
        if len(cleaned) > 40:
            return cleaned
    teaser = clean_rss_teaser(entry)
    cleaned = strip_boilerplate(teaser, title=title)
    if cleaned or teaser.casefold() == title.casefold():
        return cleaned
    return teaser


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


def pick_sentences(sentences: list[str], max_len: int) -> tuple[list[str], list[str]]:
    """Takes whole sentences up to max_len (always at least one). Returns (picked, remaining)."""
    picked, total = [], 0
    for index, sentence in enumerate(sentences):
        if picked and total + len(sentence) + 1 > max_len:
            return picked, sentences[index:]
        picked.append(sentence)
        total += len(sentence) + 1
    return picked, []


def build_card_caption(source_name: str, title: str, body_text: str, category: str, breaking: bool) -> str:
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", (body_text or "").replace("\n", " ")) if s.strip()]
    lead_sentences, rest = pick_sentences(sentences, CARD_LEAD_LEN) if sentences else ([], [])
    lead = " ".join(lead_sentences)
    if len(lead) > CARD_LEAD_LEN + 120:
        lead = clean_excerpt(lead, CARD_LEAD_LEN + 120)
    detail_sentences, _ = pick_sentences(rest, CARD_DETAIL_LEN) if rest else ([], [])
    detail = " ".join(detail_sentences)
    if len(detail) > CARD_DETAIL_LEN + 150:
        detail = clean_excerpt(detail, CARD_DETAIL_LEN + 150)

    parts = []
    if breaking:
        parts.append("🚨 <b>SON DAKİKA</b> 🚨")
    emoji = CATEGORY_EMOJI.get(category, "📰")
    parts.append(f"{emoji} <b>{html.escape(lead or title, quote=False)}</b>")
    if detail:
        parts.append(html.escape(detail, quote=False))
    tags = "#" + category.replace("İ", "i").replace("Ü", "ü").capitalize().replace(" ", "")
    if breaking:
        tags += " #SonDakika"
    parts.append(f"Kaynak: {html.escape(source_name, quote=False)}\n<i>gundem360</i> · {tags}")
    return "\n\n".join(parts)


TITLE_STEM_LEN = 5


def title_stems(title: str) -> set:
    text = title.casefold().replace("i̇", "i")
    return {token[:TITLE_STEM_LEN] for token in re.findall(r"\w+", text) if len(token) > 2}


def is_duplicate_story(stems: set, known: list) -> bool:
    if len(stems) < 3:
        return False
    for other in known:
        common = len(stems & other)
        if common >= 3 and common / min(len(stems), len(other)) >= 0.6:
            return True
    return False


def entry_age_hours(entry) -> float | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return (time.time() - timegm(parsed)) / 3600


def post_entry(source_name: str, entry, forced_category: str | None) -> bool:
    link = entry.get("link", "")
    full_text, page_html = fetch_article(link)
    body_text = get_body_text(entry, full_text)
    title = strip_html(entry.get("title", ""))
    category = forced_category or categorize(title, body_text[:250])
    age = entry_age_hours(entry)
    # "Son dakika" only for genuinely fresh items, and judged on the headline + opening lines.
    breaking = (age is None or age <= BREAKING_MAX_AGE_HOURS) and is_breaking(title, body_text[:120], category)

    rss_image = find_image(entry)
    photo_bytes = best_photo(og_images(page_html, link) + ([rss_image] if rss_image else []))
    caption = build_card_caption(source_name, title, body_text, category, breaking)

    try:
        card_bytes = generate_card(photo_bytes, title, category, breaking, source_name)
    except Exception as exc:
        print(f"Kart olusturulamadi ({link}): {exc}", file=sys.stderr)
        card_bytes = None
    if card_bytes and send_card_to_telegram(card_bytes, caption):
        return True

    # Card generation/send failed - fall back to a plain photo or text post.
    if rss_image and send_photo_to_telegram(rss_image, caption):
        return True
    return send_to_telegram(caption)


def fetch_feed(url: str):
    resp = requests.get(url, timeout=20, headers=ARTICLE_FETCH_HEADERS)
    resp.raise_for_status()
    return feedparser.parse(resp.content)


def main():
    seen = load_seen()
    is_bootstrap = len(seen) == 0
    seen_order = list(seen)
    known_stems = [set(item[2:].split()) for item in seen_order if item.startswith("t:")]
    posted = 0
    sports_posted = 0

    sources = list(SOURCES)
    random.shuffle(sources)

    for source_name, url, forced_category in sources:
        is_sports_feed = forced_category == "SPOR"
        if is_sports_feed and sports_posted >= MAX_SPORTS_PER_RUN:
            continue
        try:
            feed = fetch_feed(url)
        except Exception as exc:  # network/parse errors shouldn't kill the whole run
            print(f"Feed okunamadi ({source_name}): {exc}", file=sys.stderr)
            continue

        new_from_feed = 0
        for entry in feed.entries:
            eid = entry_id(entry)
            if not eid or eid in seen:
                continue

            age = entry_age_hours(entry)
            if is_bootstrap or (age is not None and age > MAX_ENTRY_AGE_HOURS):
                # First ever run / stale backlog of a newly added feed: mark as seen without posting.
                seen.add(eid)
                seen_order.append(eid)
                continue

            if new_from_feed >= MAX_POSTS_PER_FEED or posted >= MAX_POSTS_PER_RUN:
                break
            if is_sports_feed and sports_posted >= MAX_SPORTS_PER_RUN:
                break

            stems = title_stems(strip_html(entry.get("title", "")))
            if is_duplicate_story(stems, known_stems):
                seen.add(eid)  # same story already posted from another outlet
                seen_order.append(eid)
                continue

            try:
                sent = post_entry(source_name, entry, forced_category)
            except Exception as exc:  # a single bad entry shouldn't kill the whole run
                print(f"Haber gonderilemedi ({source_name}): {exc}", file=sys.stderr)
                sent = False

            if sent:
                seen.add(eid)
                seen_order.append(eid)
                if len(stems) >= 3:
                    known_stems.append(stems)
                    seen_order.append("t:" + " ".join(sorted(stems)))
                posted += 1
                new_from_feed += 1
                if is_sports_feed:
                    sports_posted += 1
                time.sleep(DELAY_BETWEEN_POSTS)

        if posted >= MAX_POSTS_PER_RUN:
            break

    save_seen(seen_order)
    print(f"Bitti. Yeni gonderilen: {posted} (spor: {sports_posted}). Bootstrap: {is_bootstrap}.")


if __name__ == "__main__":
    main()