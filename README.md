# gundem360 haber botu

`@gundem360haber` Telegram kanalina, ücretsiz RSS kaynaklarindan derlenen haberleri
otomatik olarak gönderen bot. GitHub Actions üzerinde çalışır, bu yüzden bilgisayar
kapalıyken de her 30 dakikada bir kendiliğinden çalışmaya devam eder.

## Nasıl çalışır

- `.github/workflows/post.yml` her 30 dakikada bir `bot.py` dosyasını çalıştırır.
- `bot.py`, `SOURCES` listesindeki RSS kaynaklarını okur, daha önce paylaşılmamış
  haberleri bulur ve kanala gönderir.
- Her haber şu formatta paylaşılır: başlık, kısa özet, `Kaynak: <site adı>` ve
  altta küçük bir `gundem360` imzası. Kaynak linki paylaşılmaz.
- Paylaşılan haberlerin kimlikleri `seen.json` içinde tutulur ve her çalıştırmadan
  sonra otomatik olarak commit'lenir; böylece aynı haber iki kez gönderilmez.
- İlk çalıştırmada (bootstrap) hiçbir şey gönderilmez, sadece mevcut haberler
  "görüldü" olarak işaretlenir — bu sayede kurulum anında kanala eski haber yığını
  düşmez.

## Kaynak eklemek/çıkarmak

`bot.py` içindeki `SOURCES` listesine `(kaynak adı, RSS url)` şeklinde satır
ekleyip repo'ya push etmek yeterli.

## Sıklığı değiştirmek

`.github/workflows/post.yml` içindeki `cron: "*/30 * * * *"` satırını
değiştirin (ör. her 15 dakikada bir için `*/15 * * * *`).

## Gizli bilgiler

Bot token'ı kod içinde değil, GitHub repo secret'ı olan `TELEGRAM_BOT_TOKEN`
içinde tutulur (Settings → Secrets and variables → Actions).