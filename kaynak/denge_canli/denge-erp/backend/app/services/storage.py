"""Dosya deposu — ekler, üretilen PDF'ler, içe aktarma raporları.

Dosyalar veritabanında DEĞİL diskte (`FILES_DIR`) durur; veritabanında yalnız
üstveri ve göreli yol vardır. Gerekçe: 5 MB'lık montaj fotoğrafını BYTEA'da
tutmak her yedeği ve her `pg_dump`'ı şişirir, üstelik gerektiğinde S3/MinIO'ya
geçmeyi imkânsızlaştırır. Tüm erişim bu modülün arkasındadır, böylece o geçiş
tek dosyayı değiştirmekle olur.

**Yol dışarıdan gelmez.** Dosya adı yalnız görüntüleme içindir; diskteki ad
içerik özetinden (sha256) türetilir. Kullanıcının verdiği adı yola koymak
`../../etc/passwd` demekti.

**Aynı içerik bir kez saklanır.** İki iş emrine aynı fotoğraf yüklenirse disk
tek kopya tutar; iki `attachments` satırı aynı `storage_path`'i gösterir.
"""

import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import get_config

# Kabul edilen içerik türleri. Beyaz liste, kara liste değil: bir ERP'ye
# yüklenen dosya başkasının tarayıcısında açılacak ve `text/html` ya da
# `image/svg+xml` oradan script çalıştırabilirdi.
IZINLI_TIPLER = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/csv": ".csv",
    "text/plain": ".txt",
}

# Tarayıcılar aynı dosya için farklı MIME söyler: Windows .csv için
# `application/vnd.ms-excel`, macOS ve bazı tarayıcılar .xlsx/.docx/.csv için
# `application/octet-stream` gönderir. Beyan edilen tipe körü körüne bakmak
# muhasebe kullanıcısını "Bu dosya türü kabul edilmiyor" ile bloke ediyordu.
# Bu yüzden UZANTIYA göre bir yedek eşleme var — ama yalnız beyaz listedeki
# türlere çözülür, yeni tür açmaz.
UZANTI_TIPLERI = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".csv": "text/csv",
    ".txt": "text/plain",
}

# Tarayıcının "bilmiyorum" dediği tipler; bunlarda uzantıya bakılır.
BELIRSIZ_TIPLER = {
    "",
    "application/octet-stream",
    "application/vnd.ms-excel",
    "application/x-msexcel",
    "text/x-csv",
    "application/csv",
}


def mime_coz(beyan: str, dosya_adi: str) -> str:
    """Beyan edilen MIME belirsizse uzantıdan çözer.

    Beyan NET ve beyaz listedeyse ona güvenilir; belirsizse uzantı karar
    verir. Uzantı da tanınmazsa beyan olduğu gibi döner ve `yaz()` reddeder.
    """
    beyan = (beyan or "").split(";")[0].strip().lower()
    if beyan in IZINLI_TIPLER:
        return beyan
    if beyan in BELIRSIZ_TIPLER:
        uzanti = Path(dosya_adi or "").suffix.lower()
        if uzanti in UZANTI_TIPLERI:
            return UZANTI_TIPLERI[uzanti]
    return beyan


GORSEL_TIPLERI = {"image/jpeg", "image/png", "image/webp", "image/heic"}

MAKS_BOYUT = 25 * 1024 * 1024  # 25 MB — montaj fotoğrafı ve broşür için yeterli


class DepoHatasi(ValueError):
    """Dosya kabul edilmedi."""


@dataclass(frozen=True)
class Kayit:
    storage_path: str
    sha256: str
    size_bytes: int
    mime_type: str


def _kok() -> Path:
    return Path(get_config().files_dir)


def temiz_ad(ad: str) -> str:
    """Görüntülenecek dosya adı — yol bileşeni taşımaz."""
    ad = Path(ad or "dosya").name
    ad = re.sub(r"[\x00-\x1f\\/:*?\"<>|]", "_", ad).strip() or "dosya"
    return ad[:255]


async def sinirli_oku(dosya) -> bytes:
    """Yüklenen dosyayı parça parça okur ve sınırı AŞTIĞI ANDA durur.

    `await file.read()` gövdenin tamamını önce belleğe alıp sonra boyuta
    bakıyordu: 500 MB gönderen bir kullanıcı 500 MB RAM harcatıyordu, dosya
    reddedilse bile. Üretimde Caddy 32 MB'da kesiyor ama uygulamaya doğrudan
    ulaşan bir istekte (sunucunun kendisi, yanlış yapılandırma) sınır yoktu.
    """
    parcalar: list[bytes] = []
    toplam = 0
    while parca := await dosya.read(1024 * 1024):
        toplam += len(parca)
        if toplam > MAKS_BOYUT:
            raise DepoHatasi(f"Dosya {MAKS_BOYUT // (1024 * 1024)} MB'ı aşamaz")
        parcalar.append(parca)
    return b"".join(parcalar)


def yaz(icerik: bytes, *, mime_type: str) -> Kayit:
    """İçeriği diske yazar ve üstverisini döndürür."""
    if not icerik:
        raise DepoHatasi("Dosya boş")
    if len(icerik) > MAKS_BOYUT:
        raise DepoHatasi(f"Dosya {MAKS_BOYUT // (1024 * 1024)} MB'ı aşamaz")
    uzanti = IZINLI_TIPLER.get(mime_type)
    if uzanti is None:
        raise DepoHatasi(f"Bu dosya türü kabul edilmiyor: {mime_type}")

    ozet = hashlib.sha256(icerik).hexdigest()
    # İki kademeli dizin: tek dizinde on binlerce dosya listeleme işlemlerini
    # yavaşlatır ve bazı dosya sistemlerinde sınıra çarpar.
    goreli = f"{ozet[:2]}/{ozet[2:4]}/{ozet}{uzanti}"
    hedef = _kok() / goreli
    hedef.parent.mkdir(parents=True, exist_ok=True)
    # Dosya varsa da YENİDEN YAZILIR. "Varsa atla" ucuz görünüyordu ama
    # eşzamanlı bir silme dosyayı tam o anda kaldırdığında yeni ek 201
    # dönüyor ve indirilemiyordu — sessiz belge kaybı. İçerik sha256 ile
    # aynı olduğu için yeniden yazmak zararsız, üstelik dosya bir şekilde
    # kaybolmuşsa kendini onarır.
    hedef.write_bytes(icerik)
    return Kayit(storage_path=goreli, sha256=ozet, size_bytes=len(icerik), mime_type=mime_type)


def yol(storage_path: str) -> Path:
    """Göreli yolu mutlak yola çevirir ve depo dışına çıkılmadığını doğrular."""
    kok = _kok().resolve()
    tam = (kok / storage_path).resolve()
    if not tam.is_relative_to(kok):
        raise DepoHatasi("Geçersiz dosya yolu")
    if not tam.is_file():
        raise DepoHatasi("Dosya bulunamadı")
    return tam


def yetim_dosyalar(kullanilan: set[str]) -> list[Path]:
    """Hiçbir ek kaydının işaret etmediği dosyalar.

    Dosyalar ek silinirken ANINDA kaldırılmaz: silme ile eşzamanlı bir
    yükleme aynı içeriği paylaşıyorsa, referans sayımı yeni (henüz
    commit edilmemiş) satırı göremez ve dosyayı silerdi. İçerik adresli
    depoda doğru desen, silmeyi çöp toplamaya bırakmaktır.
    """
    kok = _kok()
    if not kok.is_dir():
        return []
    return [y for y in kok.rglob("*") if y.is_file() and str(y.relative_to(kok)) not in kullanilan]


def yetimleri_temizle(kullanilan: set[str], *, en_az_yas_saat: int = 24) -> int:
    """Yeterince eskimiş yetim dosyaları siler; silinen sayısını döner.

    Yaş eşiği zorunlu: yüklemesi süren ya da transaction'ı henüz kapanmamış
    bir dosya yetim görünür. Taze dosyaya dokunmak, veriyi kaybetmenin
    başka bir yolu olurdu.
    """
    sinir = time.time() - en_az_yas_saat * 3600
    silinen = 0
    for y in yetim_dosyalar(kullanilan):
        try:
            if y.stat().st_mtime < sinir:
                y.unlink()
                silinen += 1
        except OSError:
            continue
    return silinen
