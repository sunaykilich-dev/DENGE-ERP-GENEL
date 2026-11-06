"""Altın kayıt testi için canlı veritabanının anonimleştirilmiş kopyasını üretir.

    uv run python tests/fixtures/anonimlestir.py

MASKELENIR (KVKK): plaka, firma unvanı, yetkili adı, telefon, IBAN, IMEI'nin
son 4 hanesi, M2M numarasının son 4 hanesi, şase no, ruhsat no, açıklama.

AYNEN KORUNUR: tarih, `ay`, tutarlar, montaj noktası adı, `odemeDurumu`,
`islemTipi`, `montajTuru`, cihaz modeli. Test tam olarak bunları doğruluyor —
maskelenirse altın rakamlar anlamını kaybeder.
"""

import hashlib
import shutil
import sqlite3
import sys
from pathlib import Path

KAYNAK = Path.home() / "dengemobil-hakedis" / "server" / "data" / "hakedis.db"
HEDEF = Path(__file__).parent / "altin" / "hakedis-anonim.db"


def _sahte(deger: str, onek: str, uzunluk: int = 6) -> str:
    if not deger:
        return ""
    ozet = hashlib.sha1(deger.encode()).hexdigest()[:uzunluk].upper()
    return f"{onek}{ozet}"


def _plaka(deger: str) -> str:
    if not deger:
        return ""
    ozet = hashlib.sha1(deger.encode()).hexdigest()
    il = int(ozet[:2], 16) % 81 + 1
    harf = "".join(chr(65 + int(ozet[2 + i : 3 + i], 16) % 26) for i in range(3))
    sayi = int(ozet[6:10], 16) % 1000
    return f"{il:02d}{harf}{sayi:03d}"


def _numara(deger: str) -> str:
    """Son 4 haneyi maskeler; ön ek korunur (operatör analizi için)."""
    rakam = "".join(ch for ch in deger if ch.isdigit())
    return rakam[:-4] + "0000" if len(rakam) > 4 else rakam


def main() -> int:
    if not KAYNAK.exists():
        print(f"Kaynak bulunamadı: {KAYNAK}", file=sys.stderr)
        return 1
    HEDEF.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(KAYNAK, HEDEF)

    conn = sqlite3.connect(HEDEF)
    conn.row_factory = sqlite3.Row
    isler = conn.execute(
        "SELECT id, plaka, firma, imei, m2mHat, saseNo, ruhsat FROM jobs"
    ).fetchall()
    for j in isler:
        conn.execute(
            "UPDATE jobs SET plaka=?, firma=?, imei=?, m2mHat=?, saseNo=?, ruhsat=?,"
            " yetkili='', telefon='', iban='', aciklama='' WHERE id=?",
            (
                _plaka(j["plaka"]),
                _sahte(j["firma"], "MUSTERI-") if j["firma"] else "",
                _numara(j["imei"] or ""),
                _numara(j["m2mHat"] or ""),
                _sahte(j["saseNo"], "VIN", 14) if j["saseNo"] else "",
                _sahte(j["ruhsat"], "R", 7) if j["ruhsat"] else "",
                j["id"],
            ),
        )
    # firmalar tablosu da maskelenir; iş kayıtlarıyla tutarlı kalsın.
    for (ad,) in conn.execute("SELECT ad FROM firmalar").fetchall():
        conn.execute("UPDATE firmalar SET ad=? WHERE ad=?", (_sahte(ad, "MUSTERI-"), ad))
    # Montaj noktalarının YETKİLİ ve TELEFON'u kişisel veri; adı korunur.
    conn.execute("UPDATE montaj_noktalari SET yetkili='', telefon=''")
    conn.execute("DELETE FROM users")
    conn.execute("DELETE FROM sessions")
    conn.execute("DELETE FROM logs")
    conn.commit()
    conn.execute("VACUUM")
    conn.close()

    boyut = HEDEF.stat().st_size / 1024
    print(f"Anonim kopya yazıldı: {HEDEF} ({boyut:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
