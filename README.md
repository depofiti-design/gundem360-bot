# gundem360 haber botu

`@gundem360haber` Telegram kanalına, ücretsiz RSS kaynaklarından derlenen haberleri
otomatik olarak gönderen bot. GitHub Actions üzerinde çalışır, bu yüzden bilgisayar
kapalıyken de kendiliğinden çalışmaya devam eder.

## Nasıl çalışır

- `.github/workflows/post.yml` saatte bir `bot.py` dosyasını çalıştırır. GitHub'ın ücretsiz
  zamanlayıcısı geç kalabildiği için gerçek aralık 1-6 saat arasında değişir.
- `bot.py`, `SOURCES` listesindeki 22 RSS kaynağını (13 genel, 9 spor) sırayla karıştırarak okur.
- Her haberin makale sayfası açılır: tam metin çıkarılır (yapay zeka ile yeniden yazım yok),
  tarih/künye/sosyal medya gibi gürültü temizlenir.
- Her haber için şablonlu bir kart görseli üretilip gönderilir (aşağıya bakın).
- Paylaşılan haberlerin kimlikleri `seen.json` içinde tutulur ve her çalıştırmadan sonra
  workflow tarafından commit'lenir; böylece aynı haber iki kez gönderilmez.
- İlk çalıştırmada (bootstrap) hiçbir şey gönderilmez, sadece mevcut haberler "görüldü"
  olarak işaretlenir.

## Gönderi formatı

Görsel kart + altında açıklama metni:

1. `SON DAKİKA` satırı (sadece uygunsa)
2. Kategori emojisi + **kalın giriş cümleleri** (haberin can alıcı kısmı)
3. Devamındaki bilgi cümleleri (düz metin, cümle sınırında kesilir)
4. `Kaynak: <site adı>` ve `gundem360 · #Kategori` imzası. Kaynak linki paylaşılmaz.

Kart: üstte net haber fotoğrafı (efektsiz), altta koyu panel; başlık, kategori, kaynak ve
sol üstte `assets/logo.png` (G360 logosu), sağ üstte kanal adresi. Fotoğraf yoksa logolu,
kategori renkli kart üretilir. Kart üretilemezse düz fotoğraf veya düz metin gönderilir.

## Görsel seçimi

Makalenin `og:image` adresi ve RSS görseli indirilir, en büyük olan kullanılır. 500px altı
küçük resimler, afiş gibi aşırı geniş ve aşırı dikey resimler elenir.

## Filtreler ve limitler (`bot.py` üstündeki sabitler)

| Sabit | Değer | Anlamı |
|---|---|---|
| `MAX_POSTS_PER_RUN` | 12 | Bir çalıştırmada en fazla haber |
| `MAX_POSTS_PER_FEED` | 2 | Bir kaynaktan en fazla haber |
| `MAX_SPORTS_PER_RUN` | 4 | Bir çalıştırmada en fazla spor haberi |
| `MAX_ENTRY_AGE_HOURS` | 24 | Daha eski haberler paylaşılmaz, sadece "görüldü" yapılır |
| `BREAKING_MAX_AGE_HOURS` | 3 | "SON DAKİKA" sadece bu süreden yeni haberlere verilir |
| `MIN_PHOTO_WIDTH` | 500 | Kartta kullanılacak en küçük fotoğraf genişliği |
| `MAX_SEEN_KEPT` | 3000 | `seen.json` içinde tutulan kayıt sayısı |

- Aynı haber farklı kaynaklardan gelirse başlık benzerliğiyle (`t:` kayıtları) tekrar paylaşılmaz.
- Spor haberlerinde "kriz", "bomba", "savaş" gibi mecazi kelimeler SON DAKİKA sayılmaz;
  sadece gerçek olaylar (deprem, kaza, vefat vb.) sayılır (`SPORTS_BREAKING_KEYWORDS`).
- Kategori önce başlığa, başlık nötrse haber metninin ilk kısmına göre belirlenir
  (`card.py` içindeki `CATEGORY_RULES`). Bazı kaynaklar kategoriye zorlanmıştır.

## Kaynak eklemek/çıkarmak

`bot.py` içindeki `SOURCES` listesine `(kaynak adı, RSS url, zorunlu kategori veya None)`
şeklinde satır ekleyip push etmek yeterli. Yeni kaynağın eski haberleri 24 saat kuralıyla
kanala dökülmez. Bazı siteler (NTV Spor, Fanatik, Sporx) botlara 403/404 verdiği için listede yok.

## Sıklığı değiştirmek

`.github/workflows/post.yml` içindeki `cron: "0 * * * *"` satırını değiştirin. GitHub'ın
ücretsiz planında aylık 2000 dakika Actions kotası var, çok sık çalıştırmak kotayı tüketip
botu durdurabilir.

## Test etmek

- Canlı çalıştırma: `gh workflow run post.yml`
- Kanala göndermeden deneme: `bot.send_card_to_telegram` fonksiyonunu sahte bir fonksiyonla
  değiştirip `bot.post_entry(...)` çağırın, üretilen kartı ve metni inceleyin.
- `manual_test_post.py` birkaç görülmemiş haberi gerçekten kanala gönderir.
- Windows konsolunda emoji için `PYTHONIOENCODING=utf-8` gerekir.

## Gizli bilgiler

Bot token'ı kod içinde değil, GitHub repo secret'ı olan `TELEGRAM_BOT_TOKEN` içinde tutulur
(Settings → Secrets and variables → Actions).
