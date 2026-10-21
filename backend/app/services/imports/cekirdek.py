"""Toplu içe aktarmanın ortak çekirdeği: okuma, doğrulama iskeleti, şablon.

Akış üç adım: **oku → doğrula (önizleme) → uygula.** Dosya yüklemek hiçbir
şey yazmaz; kullanıcı neyin gireceğini, neyin hata verdiğini ve neyin zaten
kayıtlı olduğunu görmeden onaylayamaz.

Tek amaçlı bir içe aktarıcı yerine **profil** mimarisi var: cihaz, hat, araç,
hesap, tarife, abonelik aynı çerçeveyi kullanır. Yeni bir veri türü eklemek
bir profil dosyası yazmak demek; arayüz, denetim izi ve karantina raporu
kendiliğinden çalışır.

**Başlık satırı sayfanın herhangi bir yerinde olabilir** — HYTERA bayi
listesinde 9. satırda. Sabit "ilk satır başlıktır" varsayımı bu dosyayı
sessizce boş okurdu.

**Başlık eşlemesi `tr_normkey` ile yapılır.** `"Cihaz Imei No".lower()`
Türkçe yerelde `"cihaz ımei no"` verir ve hiçbir `imei` deseni tutmaz;
canlı uygulamada IMEI sütununun hiç okunmamasına yol açan gerçek hata buydu.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.services.normalize import clean_cell, tr_normkey

# Başlık bu kadar satır içinde aranır; bulunamazsa dosya reddedilir.
BASLIK_ARAMA_DERINLIGI = 25
MAKS_SATIR = 20_000


@dataclass(frozen=True)
class Sutun:
    """Bir profilin beklediği sütun.

    `basliklar` kabul edilen yazımlar; hepsi `tr_normkey`'den geçirilerek
    karşılaştırılır, yani "Cihaz IMEI No" ile "cihaz imei no" aynı şeydir.
    """

    alan: str
    basliklar: tuple[str, ...]
    zorunlu: bool = False
    aciklama: str = ""
    # Dolgu filtresi ("x", "yok", "?", "istenmedi" → boş) bu sütunda UYGULANMAZ.
    # Veri sütunlarında filtre doğru; EVET/HAYIR ve değer kümesi sütunlarında
    # yıkıcı: ekip kutuyu çarpıyla işaretlediğinde "x" boşa çevriliyor, alan
    # hiç gelmemiş sayılıp varsayılan uygulanıyordu. Ölçülen iki sonuç:
    # "Bayi mi = X" olan hesap MÜŞTERİ olarak, "Yenileme = YOK" olan sözleşme
    # OTOMATİK yenilemeli olarak giriyordu. İkisi de hatasız, uyarısız.
    ham: bool = False

    @property
    def baslik(self) -> str:
        """Şablonda basılacak birincil yazım."""
        return self.basliklar[0]


@dataclass
class SatirSonucu:
    satir_no: int  # dosyadaki satır (başlık hariç, 1'den)
    veri: dict[str, Any] = field(default_factory=dict)
    hatalar: list[str] = field(default_factory=list)
    uyarilar: list[str] = field(default_factory=list)
    # Karar isteyen durum: {"tip": ..., "kayit_id": ..., "aciklama": ...}
    cakisma: dict[str, Any] | None = None
    ham: dict[str, str] = field(default_factory=dict)

    @property
    def gecerli(self) -> bool:
        return not self.hatalar

    def sozluk(self) -> dict[str, Any]:
        return {
            "satir_no": self.satir_no,
            "veri": {k: (str(v) if v is not None else None) for k, v in self.veri.items()},
            "hatalar": self.hatalar,
            "uyarilar": self.uyarilar,
            "cakisma": self.cakisma,
            "ham": self.ham,
        }


class Profil:
    """İçe aktarma profili. Alt sınıflar `dogrula` ve `yaz` uygular."""

    kod: str = ""
    ad: str = ""
    aciklama: str = ""
    sutunlar: tuple[Sutun, ...] = ()
    # Var olan kaydı güncelleme seçeneği sunulsun mu (çakışma çözümü).
    guncelleme_destekli: bool = True

    async def dogrula(self, db: AsyncSession, satirlar: list[dict]) -> list[SatirSonucu]:
        raise NotImplementedError

    async def yaz(
        self,
        db: AsyncSession,
        satirlar: list[dict],
        *,
        clock: Clock,
        user_id: int | None,
        kararlar: dict[int, str],
    ) -> dict[str, int]:
        raise NotImplementedError

    # --- Alt sınıflar için ortak yardımcılar ---------------------------------

    def bos_sayac(self) -> dict[str, int]:
        return {"eklendi": 0, "guncellendi": 0, "atlandi": 0}

    def uygulanacaklar(
        self, satirlar: list[dict], kararlar: dict[int, str]
    ) -> list[tuple[dict, str]]:
        """Yazılacak satırları ve her birinin kararını döner.

        Hatalı satır hiçbir koşulda yazılmaz. Çakışmalı satır yalnız
        kullanıcı 'guncelle' dediyse yazılır — varsayılan atlamaktır, çünkü
        sessizce üzerine yazmak içe aktarmanın en pahalı hatasıdır.
        """
        sonuc: list[tuple[dict, str]] = []
        for s in satirlar:
            if s.get("hatalar"):
                continue
            karar = kararlar.get(s["satir_no"], "atla")
            if s.get("cakisma") and karar != "guncelle":
                continue
            sonuc.append((s, karar))
        return sonuc


# --- Dosya okuma --------------------------------------------------------------


class DosyaHatasi(ValueError):
    """Dosya okunamadı veya beklenen sütunları taşımıyor."""


def _hucreler(satir: Any) -> list[str]:
    """Hücreleri HAM metne çevirir.

    Dolgu filtresi burada UYGULANMAZ; sütunun hangi anlama geldiğini yalnız
    profil bilir (bkz. `Sutun.ham`). Filtreyi burada uygulamak, profilin
    göremediği bir yerde veriyi siliyordu.
    """
    return [_metin(h) for h in satir]


def _metin(hucre: Any) -> str:
    if hucre is None:
        return ""
    return str(hucre).strip() if not isinstance(hucre, str) else hucre.strip()


def _baslik_indeksi(basliklar: list[str], sutunlar: tuple[Sutun, ...]) -> dict[str, int]:
    """Başlık satırından alan → sütun indeksi çıkarır."""
    normalize = {tr_normkey(b): i for i, b in enumerate(basliklar) if b}
    indeks: dict[str, int] = {}
    for s in sutunlar:
        for yazim in s.basliklar:
            i = normalize.get(tr_normkey(yazim))
            if i is not None:
                indeks[s.alan] = i
                break
    return indeks


def _baslik_satirini_bul(
    satirlar: list[list[str]], sutunlar: tuple[Sutun, ...]
) -> tuple[int, dict[str, int]]:
    """Başlık satırını ve alan eşlemesini bulur.

    En çok zorunlu sütunu eşleyen satır seçilir; başlığı ilk satır varsaymak
    HYTERA dosyasını (başlık 9. satırda) okuyamazdı.
    """
    zorunlular = {s.alan for s in sutunlar if s.zorunlu}
    en_iyi: tuple[int, dict[str, int]] = (-1, {})
    en_iyi_puan = 0

    for i, satir in enumerate(satirlar[:BASLIK_ARAMA_DERINLIGI]):
        indeks = _baslik_indeksi(satir, sutunlar)
        puan = len(zorunlular & set(indeks)) * 10 + len(indeks)
        if puan > en_iyi_puan:
            en_iyi_puan, en_iyi = puan, (i, indeks)

    satir_no, indeks = en_iyi
    if satir_no < 0:
        raise DosyaHatasi("Dosyada tanınan bir başlık satırı bulunamadı.")
    eksik = sorted(zorunlular - set(indeks))
    if eksik:
        adlar = {s.alan: s.baslik for s in sutunlar}
        raise DosyaHatasi("Zorunlu sütunlar bulunamadı: " + ", ".join(adlar[a] for a in eksik))
    return satir_no, indeks


def _xlsx_satirlari(icerik: bytes, sayfa: str | None) -> list[list[str]]:
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(icerik), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl çeşitli hata tipleri atıyor
        raise DosyaHatasi(f"Excel dosyası okunamadı: {exc}") from exc
    ws = wb[sayfa] if sayfa and sayfa in wb.sheetnames else wb.worksheets[0]
    satirlar = [_hucreler(s) for s in ws.iter_rows(values_only=True)]
    wb.close()
    return satirlar


def _csv_satirlari(icerik: bytes) -> list[list[str]]:
    # Türkçe Excel CSV'leri çoğunlukla cp1254; modern dışa aktarımlar UTF-8.
    metin: str | None = None
    for kodlama in ("utf-8-sig", "utf-8"):
        try:
            metin = icerik.decode(kodlama)
            break
        except UnicodeDecodeError:
            continue
    if metin is None:
        metin = icerik.decode("cp1254", errors="replace")

    ornek = metin[:4096]
    ayrac = ";" if ornek.count(";") >= ornek.count(",") else ","
    try:
        return [
            [_metin(h) for h in satir] for satir in csv.reader(io.StringIO(metin), delimiter=ayrac)
        ]
    except csv.Error as exc:
        # Uzantısı .csv ama içeriği xlsx olan dosya (Windows'ta sık) burada
        # ham `_csv.Error` atıp 500 veriyordu.
        raise DosyaHatasi(f"CSV dosyası okunamadı: {exc}") from exc


@dataclass(frozen=True)
class Okuma:
    """`oku()` sonucu.

    `atilan`, dosyada bir şey yazan ama hiçbir tanınan sütuna düşmeyen
    satırların sayısıdır (başlığın ÜSTÜNDE kalanlar dahil). Önceden bu
    satırlar sayılmadan atılıyordu: kullanıcı 5 satırlık dosya yükleyip
    "2 satır okundu" görüyor, eksiğin nerede olduğunu çapraz kontrol
    edemiyordu. "Hiçbir satır sessizce atılmaz" kuralının karşılığı.
    """

    satirlar: list[dict]
    atilan: int = 0


def oku(dosya_adi: str, icerik: bytes, profil: Profil, *, sayfa: str | None = None) -> Okuma:
    """Dosyayı profilin alan adlarıyla sözlük listesine çevirir."""
    ad = (dosya_adi or "").lower()
    if ad.endswith((".xlsx", ".xlsm")):
        ham = _xlsx_satirlari(icerik, sayfa)
    elif ad.endswith(".csv"):
        ham = _csv_satirlari(icerik)
    else:
        raise DosyaHatasi("Yalnız .xlsx ve .csv dosyaları kabul edilir.")

    if not ham:
        raise DosyaHatasi("Dosya boş.")

    baslik_no, indeks = _baslik_satirini_bul(ham, profil.sutunlar)
    ters = {i: alan for alan, i in indeks.items()}
    # Dolgu filtresi sütun bazında: profil "ham" dediyse hücre olduğu gibi gelir.
    hamlar = {s.alan for s in profil.sutunlar if s.ham}

    sonuc: list[dict] = []
    atilan = 0
    # Başlığın ÜSTÜNDE kalan dolu satırlar da veri olabilir (yanlış hizalanmış
    # dosya); sayılmadan atılırlarsa kullanıcı farkı göremez.
    atilan += sum(1 for satir in ham[:baslik_no] if any(h.strip() for h in satir))

    for satir in ham[baslik_no + 1 :]:
        kayit: dict[str, str] = {}
        for i, alan in ters.items():
            if i >= len(satir):
                continue
            deger = satir[i] if alan in hamlar else clean_cell(satir[i])
            if deger:
                kayit[alan] = deger
        if not kayit:
            if any(h.strip() for h in satir):
                atilan += 1
            continue
        sonuc.append(kayit)
        if len(sonuc) >= MAKS_SATIR:
            raise DosyaHatasi(f"Dosya {MAKS_SATIR} satırdan uzun; parçalara bölüp yükleyin.")
    return Okuma(satirlar=sonuc, atilan=atilan)


def _sayfa_adi(ad: str) -> str:
    """Excel sayfa adı: / \\ * ? : [ ] yasak, en çok 31 karakter."""
    return re.sub(r"[\\/*?:\[\]]", "-", ad)[:31]


def sablon_xlsx(profil: Profil) -> bytes:
    """Profilin beklediği başlıkları taşıyan boş şablon.

    Ekibin kendi Excel'ini ERP'nin beklediği sütunlara çevirmeye çalışması,
    içe aktarmanın en çok zaman kaybettiren adımıydı; şablon indirilip
    doldurulunca bu adım yok oluyor.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = _sayfa_adi(profil.ad)
    ws.append([s.baslik for s in profil.sutunlar])

    for hucre in ws[1]:
        hucre.fill = PatternFill("solid", fgColor="E8E4DB")
        hucre.font = Font(bold=True, color="3C4657")
    for i, s in enumerate(profil.sutunlar, start=1):
        ws.column_dimensions[get_column_letter(i)].width = min(max(len(s.baslik) + 4, 16), 38)
    ws.freeze_panes = "A2"

    # Açıklamalar AYRI SAYFADA: veri sayfasına açıklama satırı koymak, dosya
    # geri yüklendiğinde o satırın veri sanılması demekti.
    yardim = wb.create_sheet("Açıklama")
    yardim.append(["Sütun", "Zorunlu mu", "Açıklama"])
    for hucre in yardim[1]:
        hucre.fill = PatternFill("solid", fgColor="E8E4DB")
        hucre.font = Font(bold=True, color="3C4657")
    for s in profil.sutunlar:
        yardim.append([s.baslik, "Evet" if s.zorunlu else "Hayır", s.aciklama])
    yardim.column_dimensions["A"].width = 26
    yardim.column_dimensions["B"].width = 12
    yardim.column_dimensions["C"].width = 70
    for satir in yardim.iter_rows(min_row=2):
        satir[2].alignment = Alignment(wrap_text=True, vertical="top")

    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue()
