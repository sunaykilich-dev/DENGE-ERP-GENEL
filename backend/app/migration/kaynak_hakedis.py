"""Canlı hak ediş uygulamasının SQLite veritabanını okur.

Salt okunur açılır (`mode=ro`): göç betiği kaynağa ASLA yazmaz — uygulama
geliştirme boyunca çalışmaya devam edecek.
"""

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

VARSAYILAN_YOL = Path.home() / "dengemobil-hakedis" / "server" / "data" / "hakedis.db"


@dataclass
class HakedisKaynagi:
    yol: Path = VARSAYILAN_YOL

    def _baglan(self) -> sqlite3.Connection:
        if not self.yol.exists():
            raise FileNotFoundError(
                f"Hak ediş veritabanı bulunamadı: {self.yol}\n"
                "Canlı sunucudan kopyalayın veya --hakedis-yolu ile başka yol verin."
            )
        conn = sqlite3.connect(f"file:{self.yol}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _hepsi(self, sorgu: str) -> list[sqlite3.Row]:
        with self._baglan() as conn:
            return conn.execute(sorgu).fetchall()

    def montaj_noktalari(self) -> list[sqlite3.Row]:
        return self._hepsi(
            "SELECT ad, yetkili, telefon, ats, obdAts, dashcam, harici, kmBirim "
            "FROM montaj_noktalari ORDER BY ad"
        )

    def firmalar(self) -> list[str]:
        return [r["ad"] for r in self._hepsi("SELECT ad FROM firmalar ORDER BY ad")]

    def cihaz_modelleri(self) -> list[str]:
        return [r["ad"] for r in self._hepsi("SELECT ad FROM cihazlar ORDER BY ad")]

    def is_sayilari(self) -> dict[str, int]:
        """Montaj noktası başına iş adedi — birleştirmede hangi kaydın ana
        kayıt olacağına karar verirken ve raporda kullanılır."""
        return {
            r["montajNoktasi"]: r["adet"]
            for r in self._hepsi(
                "SELECT montajNoktasi, COUNT(*) adet FROM jobs "
                "WHERE silindi='' GROUP BY montajNoktasi"
            )
        }

    def firma_is_sayilari(self) -> dict[str, int]:
        return {
            r["firma"]: r["adet"]
            for r in self._hepsi(
                "SELECT firma, COUNT(*) adet FROM jobs WHERE silindi='' GROUP BY firma"
            )
        }

    def isler(self) -> list[dict]:
        """Silinmemiş tüm iş kayıtları (hak ediş göçünün kaynağı)."""
        return [
            dict(r)
            for r in self._hepsi(
                "SELECT id, ay, tarih, firma, plaka, saseNo, ruhsat, km, cihazModel, imei,"
                " m2mHat, montajNoktasi, servisBedeli, mobilKm, mobilBirim, odemeDurumu,"
                " islemTipi, montajTuru, aciklama, ftNo, faturaKesildi"
                " FROM jobs WHERE silindi='' ORDER BY ay, tarih"
            )
        ]

    def ozet(self) -> dict[str, int]:
        (row,) = self._hepsi(
            "SELECT (SELECT COUNT(*) FROM jobs WHERE silindi='') is_sayisi,"
            " (SELECT COUNT(*) FROM montaj_noktalari) nokta,"
            " (SELECT COUNT(*) FROM firmalar) firma,"
            " (SELECT COUNT(*) FROM cihazlar) cihaz_modeli"
        )
        return dict(row)


@dataclass
class KarantinaSatiri:
    kaynak: str
    ham_deger: str
    neden: str
    hedef: str | None = None
    # "bilgi" = kayıt oluştu ama nasıl türetildiği kayda değer (ör. IMEI başka
    # satırdan kurtarıldı); "uyari" = kayıt oluştu ama eksik; "engel" = kayıt
    # HİÇ oluşmadı, insan kararı gerekiyor.
    seviye: str = "uyari"


@dataclass
class HazirlikSonucu:
    """Önizleme çıktısı — hiçbir şey yazılmadan ne olacağını anlatır."""

    montaj_noktalari: list[dict] = field(default_factory=list)
    musteriler: list[dict] = field(default_factory=list)
    bayiler: list[dict] = field(default_factory=list)
    urunler: list[dict] = field(default_factory=list)
    karantina: list[KarantinaSatiri] = field(default_factory=list)
    birlestirmeler: list[tuple[str, str, int]] = field(default_factory=list)
    # Türkçe karakter farkıyla aynı kayda düşen yazımlar — sessiz
    # birleşme olmasın diye ayrıca raporlanır.
    varyant_birlesmeleri: list[tuple[str, list[str]]] = field(default_factory=list)
    # D2 envanteri
    araclar: list[dict] = field(default_factory=list)
    cihazlar: list[dict] = field(default_factory=list)
    hatlar: list[dict] = field(default_factory=list)
    kurtarilan_imei: int = 0
