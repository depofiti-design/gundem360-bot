import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

import feedparser

import bot

TARGET_TOTAL = 3
MAX_PER_SOURCE = 2


def main():
    seen = bot.load_seen()
    posted = 0

    for source_name, url in bot.SOURCES:
        if posted >= TARGET_TOTAL:
            break
        feed = feedparser.parse(url)
        posted_from_source = 0
        for entry in feed.entries:
            if posted >= TARGET_TOTAL or posted_from_source >= MAX_PER_SOURCE:
                break
            eid = bot.entry_id(entry)
            if not eid or eid in seen:
                continue
            ok = bot.post_entry(source_name, entry)
            has_img = bool(bot.find_image(entry))
            print(f"[{'OK' if ok else 'HATA'}] (img={has_img}) {source_name}: {entry.get('title', '')[:60]}")
            if ok:
                seen.add(bot.entry_id(entry))
                posted += 1
                posted_from_source += 1
                time.sleep(4)

    bot.save_seen(list(seen))
    print(f"Toplam gonderilen: {posted}")


if __name__ == "__main__":
    main()