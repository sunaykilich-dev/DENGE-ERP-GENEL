"""Servis raporlarının Excel üretimi ve dışa aktarım denetimi (E12-06, E12-09, E12-17).

Maddeler: TS-182, TS-201 (D3-A); TS-198 eğitim etkinlik Excel'i bu yardımcıyı
çağırır (D3-E: `sayfa()` + `disa_aktarim_denetimi()`). Doldurur: D3-A.

**Tek Excel yolu** `services/export.sayfalari_xlsx_async` (ayrı iş parçacığı,
formül enjeksiyonu koruması, sütun şemasından hücre tipi: seri/iş no/telefon
METİN, tarih gerçek tarih — Türkiye saati, ondalık kişi-saat). Sütun şemaları
`rapor_tanimlari.SUTUN_SEMALARI`'ndadır; kişisel sütun ve sayfa
`servis_rapor.personel` yoksa çıktıda HİÇ yer almaz (boş sütun değil).

**Ekran = Excel:** her sayfa ekrandaki uçların AYNI fonksiyonlarından
(`rapor_motoru.ozet/kirilim/trend`, `rapor_hesap.*`) üretilir.

**Denetim:** her indirme aynı transaction'da `audit.log(... action=
"servis_rapor.disaaktar", new_value={rapor, filtreler (ISO), satir_sayisi,
kapsam, kisisel_sayfalar})`; kişisel sayfa varsa `is_personal_data=True`.

**Pivot (TS-201):** openpyxl pivot ÜRETEMEZ; şablon (`templates/excel/
servis_pivot_sablonu.xlsx`, önbelleği boş) hazırlanana kadar özellik bayrağı
`PIVOT_SABLONU_ETKIN=False` ve "tipli tablo yedeği" kullanılır:
`Veri_IsEmirleri` / `Veri_Sureler` adlı Excel Tabloları (Ekle → PivotTable
ile tek tıkla pivot kurulur). Eski sistemin 8 sayfası korunur, ek sayfalar
sona eklenir.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.models import (
    Account,
    Address,
    ServiceOrder,
    ServiceOrderAssignment,
    ServiceOrderSerial,
    ServicePlan,
    ServiceResult,
    User,
)
from app.models.teknik_servis import durum_grubu
from app.permissions import BIRIMLER
from app.services import audit
from app.services import export as export_svc
from app.services.normalize import il_normalize
from app.services.teknik_servis import rapor_hesap as rh
from app.services.teknik_servis import rapor_motoru as rm
from app.services.teknik_servis import rapor_tanimlari as rt
from app.services.teknik_servis.yerel_zaman import yerel_an

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock

PIVOT_SABLONU = (
    Path(__file__).resolve().parents[2] / "templates" / "excel" / "servis_pivot_sablonu.xlsx"
)
PIVOT_SABLONU_ETKIN = False  # şablon Excel 365'te elle doğrulanınca açılır (E12-17)
SABLON_SURUMU = "tablo-yedegi-1"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_PARCA = 5000  # IN listesi parçası (PostgreSQL parametre sınırı)

SURE_DURUMU_ADLARI = {
    "TAM": "Kayıtlı",
    "KISMI": "Kısmi (eksik teknisyen var)",
    "EKSIK": "SÜRE KAYDI YOK",
    "BEKLENMIYOR": "Beklenmiyor",
}


def sayfa(
    ad: str, sema: list[rt.RaporSutunu], satirlar: list[dict[str, Any]], **kw
) -> export_svc.Sayfa:
    """Şemadan tipli sayfa: satır sözlüğünden yalnız şemadaki anahtarlar yazılır."""
    return export_svc.Sayfa(
        ad,
        [export_svc.Sutun(s.baslik, s.tip) for s in sema],
        [[r.get(s.anahtar) for s in sema] for r in satirlar],
        **kw,
    )


async def disa_aktarim_denetimi(
    db: AsyncSession,
    *,
    user: User,
    ip: str | None,
    rapor: str,
    filtreler: dict[str, Any],
    satir_sayisi: int,
    kapsam: str,
    kisisel_sayfalar: list[str],
) -> None:
    """Dışa aktarım denetim satırı (commit ÇAĞIRANIN işi; yanıttan önce)."""
    await audit.log(
        db,
        "servis_rapor",
        "servis_rapor.disaaktar",
        new_value={
            "rapor": rapor,
            "filtreler": filtreler,
            "satir_sayisi": satir_sayisi,
            "kapsam": kapsam,
            "kisisel_sayfalar": kisisel_sayfalar,
        },
        user_id=user.id,
        ip=ip,
        is_personal_data=bool(kisisel_sayfalar),
    )


def dosya_adi(onek: str, f: rm.RaporFiltresi) -> str:
    """ASCII dosya adı (latin-1 `Content-Disposition`, kontrol B16)."""
    return f"{onek}-{f.baslangic:%Y%m%d}-{f.bitis:%Y%m%d}.xlsx"


# --- İş satırları -------------------------------------------------------------------------


def _parcalar(idler: list[int]):
    for i in range(0, len(idler), _PARCA):
        yield idler[i : i + _PARCA]


async def liste_satirlari(
    db: AsyncSession, user: User, f: rm.RaporFiltresi, kategoriler: tuple[str, ...] | None = None
) -> list[dict[str, Any]]:
    """Detay kümesindeki işlerin Excel satırları (`is_listesi` şeması).

    Kişi-saat ve süre durumu E09 `zaman.sure_ozeti_toplu`'dan (tek kaynak);
    kayıt yoksa kişi-saat boş, durum "SÜRE KAYDI YOK"/"Beklenmiyor"."""
    from app.services.teknik_servis import is_emirleri, sonuc, zaman

    stmt = rm.detay_sorgusu(user, f, ServiceOrder)
    if kategoriler:
        stmt = stmt.where(ServiceOrder.kategori.in_(kategoriler))
    isler = list((await db.scalars(stmt.order_by(ServiceOrder.created_at, ServiceOrder.id))).all())
    if not isler:
        return []
    idler = [s.id for s in isler]
    musteriler = dict(
        (
            await db.execute(
                select(Account.id, Account.title).where(
                    Account.id.in_({s.customer_id for s in isler if s.customer_id} or {0})
                )
            )
        ).all()
    )
    adresler = {
        a.id: a
        for a in (
            await db.scalars(
                select(Address).where(
                    Address.id.in_({s.address_id for s in isler if s.address_id} or {0})
                )
            )
        ).all()
    }
    seriler: dict[int, list[str]] = defaultdict(list)
    sefler: dict[int, str] = {}
    teknisyenler: dict[int, list[str]] = defaultdict(list)
    planlar: dict[int, Any] = {}
    kanallar: dict[int, str] = {}
    sureler: dict[int, Any] = {}
    for parca in _parcalar(idler):
        for so_id, seri in (
            await db.execute(
                select(ServiceOrderSerial.service_order_id, ServiceOrderSerial.seri_no)
                .where(
                    ServiceOrderSerial.service_order_id.in_(parca),
                    ServiceOrderSerial.is_active.is_(True),
                )
                .order_by(ServiceOrderSerial.id)
            )
        ).all():
            seriler[so_id].append(seri)
        for so_id, rol, ad in (
            await db.execute(
                select(
                    ServiceOrderAssignment.service_order_id,
                    ServiceOrderAssignment.rol,
                    User.full_name,
                )
                .join(User, User.id == ServiceOrderAssignment.user_id)
                .where(
                    ServiceOrderAssignment.service_order_id.in_(parca),
                    ServiceOrderAssignment.removed_at.is_(None),
                )
                .order_by(ServiceOrderAssignment.is_lead.desc(), ServiceOrderAssignment.id)
            )
        ).all():
            if rol == "SEF":
                sefler.setdefault(so_id, ad)
            else:
                teknisyenler[so_id].append(ad)
        for so_id, gun in (
            await db.execute(
                select(ServicePlan.service_order_id, func.max(ServicePlan.plan_date))
                .where(
                    ServicePlan.service_order_id.in_(parca),
                    ServicePlan.is_active.is_(True),
                    ServicePlan.is_deleted.is_(False),
                )
                .group_by(ServicePlan.service_order_id)
            )
        ).all():
            planlar[so_id] = gun
        for so_id, kanal in (
            await db.execute(
                select(ServiceResult.service_order_id, ServiceResult.cozum_kanali)
                .where(
                    ServiceResult.service_order_id.in_(parca),
                    ServiceResult.gecersiz_at.is_(None),
                )
                .order_by(ServiceResult.id)
            )
        ).all():
            kanallar[so_id] = kanal
        sureler.update(await zaman.sure_ozeti_toplu(db, parca))
    satirlar = []
    for s in isler:
        adres = adresler.get(s.address_id) if s.address_id else None
        sure = sureler.get(s.id)
        satirlar.append(
            {
                "so_no": s.so_no,
                "acilis": s.created_at,
                "birim": BIRIMLER.get(s.birim, s.birim),
                "kategori": is_emirleri.KATEGORI_ADLARI.get(s.kategori, s.kategori),
                "tur": is_emirleri.TUR_ADLARI.get(s.tur, s.tur),
                "oncelik": rm.ONCELIK_ADLARI.get(s.oncelik, s.oncelik),
                "durum": is_emirleri.DURUM_ADLARI.get(s.status, s.status),
                "durum_grubu": rm.DURUM_GRUBU_ADLARI[durum_grubu(s.status)],
                "musteri": musteriler.get(s.customer_id)
                or (f"Eşleştirilmemiş: {s.customer_name_raw}" if s.customer_name_raw else None),
                "proje": s.proje,
                "lokasyon": (adres.site_name or adres.label) if adres else s.location_raw,
                "sehir": (il_normalize(adres.city) or adres.city) if adres else None,
                "ilce": adres.district if adres else None,
                "sistem": s.sistem,
                "seri": ", ".join(seriler.get(s.id, [])) or None,
                "konu": s.konu,
                "sef": sefler.get(s.id),
                "teknisyenler": ", ".join(teknisyenler.get(s.id, [])) or None,
                "plan_tarihi": planlar.get(s.id),
                "tamamlanma": s.completed_at,
                "kapanis": s.closed_at,
                "cozum_kanali": sonuc.KANAL_ADLARI.get(kanallar.get(s.id), kanallar.get(s.id)),
                "kisi_saat": round(sure.kisi_saat_dk / 60.0, 2)
                if sure is not None and sure.kisi_saat_dk is not None
                else None,
                "sure_durumu": SURE_DURUMU_ADLARI.get(sure.sure_durumu) if sure else None,
                "iletisim_ad": s.iletisim_ad,
                "iletisim_telefon": s.iletisim_telefon,
            }
        )
    return satirlar


# --- Kitap ----------------------------------------------------------------------------------


def _bos_tire(deger) -> str:
    return "—" if deger is None else str(deger)


def _tarih(d) -> str:
    return f"{d:%d.%m.%Y}"


def _filtre_metni(f: rm.RaporFiltresi) -> str:
    parcalar = []
    for ad, deger in (
        ("Kategori", f.kategori),
        ("Birim", tuple(BIRIMLER.get(b, b) for b in f.birim)),
        ("Durum grubu", f.durum_grubu),
        ("Tür", f.tur),
        ("Öncelik", f.oncelik),
        ("Müşteri #", f.musteri_id),
        ("Şef #", f.sef_id),
        ("Teknisyen #", f.teknisyen_id),
        ("Şehir", f.sehir),
        ("Tekrar arıza penceresi (gün)", f.tekrar_gun),
    ):
        if deger not in (None, (), ""):
            parcalar.append(
                f"{ad}: {', '.join(map(str, deger)) if isinstance(deger, tuple) else deger}"
            )
    return "; ".join(parcalar) or "Yok (yetkili olduğum tüm kayıtlar)"


def _yonetim_ozeti(oz: dict[str, Any], f: rm.RaporFiltresi, clock: Clock) -> export_svc.Sayfa:
    onceki = oz["onceki_donem"]
    ust = [
        ["Denge Elektronik — Teknik Servis Raporu"],
        ["Dönem", f"{_tarih(f.baslangic)} – {_tarih(f.bitis)}"],
        ["Önceki dönem", f"{_tarih(onceki['baslangic'])} – {_tarih(onceki['bitis'])}"],
        ["Tarih esası (detay sayfaları)", rt.TARIH_ESASLARI[f.tarih_esasi]],
        ["Kapsam", oz["kapsam"]],
        ["Filtreler", _filtre_metni(f)],
        ["Oluşturma", f"{yerel_an(clock.now()):%d.%m.%Y %H:%M}"],
        [],
    ]
    sutunlar = [
        export_svc.Sutun("Gösterge"),
        export_svc.Sutun("Değer", "ondalik"),
        export_svc.Sutun("Önceki Dönem", "ondalik"),
        export_svc.Sutun("Fark", "ondalik"),
        export_svc.Sutun("Ölçü"),
        export_svc.Sutun("Tanım"),
    ]
    satirlar: list[list[Any]] = []
    for k in oz["kpiler"]:
        satirlar.append([k["baslik"], k["deger"], k["onceki"], k["fark"], "adet", k["tanim"]])
    olcu_adlari = {"yuzde": "%", "saat": "saat", "kisi_saat": "kişi-saat"}
    for o in oz["olcumler"]:
        satirlar.append(
            [
                o["baslik"],
                o["deger"],
                o["onceki"],
                o["fark"],
                olcu_adlari.get(o["olcu_birimi"]),
                o["tanim"],
            ]
        )
    t = oz["toplamlar"]
    satirlar += [
        [
            "Toplam iş (tarih esasına göre)",
            t["toplam"],
            None,
            None,
            "adet",
            "Açık + Çözüldü + İptal",
        ],
        ["— Açık", t["acik"], None, None, "adet", None],
        ["— Çözüldü", t["cozuldu"], None, None, "adet", None],
        ["— İptal", t["iptal"], None, None, "adet", None],
    ]
    for k in oz["kategoriler"]:
        satirlar.append(
            [f"{k['ad']}: gelen / çözülen / dönem sonu açık", k["gelen"], None, None, "adet",
             f"çözülen {k['cozulen']}, dönem sonu açık {k['donem_sonu_acik']}"]
        )  # fmt: skip
    satirlar.append([])
    satirlar.append([f"Bu seçimde süre kaydı eksik iş: {oz['eksik_veri_is']}"])
    for not_ in rt.NOTLAR:
        satirlar.append([f"Not: {not_}"])
    if oz["gecmis_degisebilir"]:
        satirlar.append(
            ["Not: Bu seçimde olay geçmişi olmayan göç işi var; geçmiş değerler değişebilir."]
        )
    return export_svc.Sayfa("Yönetim Özeti", sutunlar, satirlar, ust_bilgi=ust)


async def kitap(
    db: AsyncSession, user: User, clock: Clock, f: rm.RaporFiltresi
) -> tuple[bytes, dict[str, Any]]:
    """Çok sayfalı servis kitabı. Dönüş: (xlsx, denetim özeti).

    Satır sınırı `EXCEL_AZAMI_SATIR` aşılırsa `RaporHatasi` (400, "daraltın")."""
    from app.services.teknik_servis import is_emirleri

    azami_satir = await rt.excel_azami_satir(db)
    toplam = await rm.say(db, rm.detay_sorgusu(user, f))
    if toplam > azami_satir:
        raise rm.RaporHatasi(
            f"{toplam} iş var; Excel en çok {azami_satir} satır alır, filtreyi daraltın"
        )
    kisisel = user.has("servis_rapor.personel")
    is_sema = rt.sutunlar("is_listesi", user)
    oz = await rm.ozet(db, user, clock, f)
    tum = await liste_satirlari(db, user, f)
    sayfalar: list[export_svc.Sayfa] = [_yonetim_ozeti(oz, f, clock)]
    for ad, kategoriler in (
        ("Günlük Servis", ("GUNLUK_SERVIS",)),
        ("Planlı Bakım", ("PLANLI_BAKIM",)),
        ("Atölye ve Proje", ("ATOLYE", "PROJE")),
    ):
        adlar = {is_emirleri.KATEGORI_ADLARI[k] for k in kategoriler}
        sayfalar.append(
            sayfa(ad, is_sema, [r for r in tum if r["kategori"] in adlar], otomatik_filtre=True)
        )
    birim_durum = await rm.kirilim(db, user, clock, f, "birim", ikinci="kategori")
    sayfalar.append(
        sayfa(
            "Birim Durum",
            rt.sutunlar("birim_durum", user),
            [{**r, "birim": r["ad"], "kategori": r["ikinci_ad"]} for r in birim_durum["satirlar"]],
            otomatik_filtre=True,
        )
    )
    trend = await rm.trend(db, user, clock, f)
    sayfalar.append(
        sayfa(
            "Aylık Özet",
            rt.sutunlar("aylik_ozet", user),
            [{**r, "ay": r["ay_adi"]} for r in trend["satirlar"]],
        )
    )
    kisisel_sayfalar: list[str] = []
    sure_satirlari: list[dict[str, Any]] = []
    if kisisel:
        personel = await rh.kisi_saat_personel(db, user, f)
        sayfalar.append(
            sayfa("Personel KPI", rt.sutunlar("personel_kpi", user), personel, otomatik_filtre=True)
        )
        sure_satirlari, sure_toplam = await rh.sure_hareketleri(db, user, f, limit=None)
        if sure_toplam > azami_satir:
            raise rm.RaporHatasi(
                f"{sure_toplam} süre kaydı var; Excel en çok {azami_satir} satır alır, "
                "filtreyi daraltın"
            )
        sayfalar.append(
            sayfa(
                "Süre Hareketleri",
                rt.sutunlar("sure_hareketleri", user),
                sure_satirlari,
                otomatik_filtre=True,
            )
        )
        kisisel_sayfalar += ["Personel KPI", "Süre Hareketleri"]
    lokasyon = await rm.kirilim(db, user, clock, f, "lokasyon")
    sayfalar.append(
        sayfa(
            "Müşteri Lokasyon",
            rt.sutunlar("musteri_lokasyon", user),
            [{**r, "lokasyon": r["ad"]} for r in lokasyon["satirlar"]],
            otomatik_filtre=True,
        )
    )
    sayfalar.append(await _sla_sayfasi(db, user, clock, f))
    sayfalar.append(await _tekrar_sayfasi(db, user, clock, f))
    yeniden = await rh.yeniden_acilan_raporu(db, user, clock, f, limit=None)
    sayfalar.append(
        sayfa(
            "Yeniden Açılan",
            rt.sutunlar("yeniden_acilan", user),
            yeniden["olaylar"],
            ust_bilgi=[
                [
                    f"Yeniden açılan iş: {yeniden['yeniden_acilan']} / ilk kez çözülen "
                    f"{yeniden['ilk_cozulen']} (oran %{_bos_tire(yeniden['oran'])}); "
                    f"PB ayrı: {yeniden['yeniden_acilan_pb']}"
                ]
            ],
        )
    )
    sayfalar.append(_tanimlar_sayfasi(user))
    sayfalar.append(sayfa("Veri_IsEmirleri", is_sema, tum, tablo_adi="Veri_IsEmirleri"))
    if kisisel:
        sayfalar.append(
            sayfa(
                "Veri_Sureler",
                rt.sutunlar("sure_hareketleri", user),
                sure_satirlari,
                tablo_adi="Veri_Sureler",
            )
        )
        kisisel_sayfalar.append("Veri_Sureler")
    icerik = await export_svc.sayfalari_xlsx_async(sayfalar)
    return icerik, {
        "satir_sayisi": len(tum),
        "kisisel_sayfalar": kisisel_sayfalar,
        "kapsam": oz["kapsam"],
    }


async def _sla_sayfasi(db, user, clock, f) -> export_svc.Sayfa:
    sla = await rh.sla_raporu(db, user, clock, f)
    satirlar: list[list[Any]] = [["SLA", k["baslik"], k["deger"], None] for k in sla["kpiler"]]
    satirlar.append(["SLA", "Uyum (%)", None, sla["uyum_yuzde"]])
    satirlar.append(["SLA", "Geciken açık iş (rapor anı)", sla["geciken_acik"], None])
    cs = sla["cozum_suresi"]
    satirlar.append(["Çözüm süresi", "Ortalama (saat)", cs["olculen"], cs["ortalama_saat"]])
    satirlar.append(["Çözüm süresi", "Medyan (saat)", cs["olculen"], cs["medyan_saat"]])
    for o in sla["oncelik_kirilimi"]:
        satirlar.append(
            [f"Öncelik: {o['ad']}", "Zamanında / Aşıldı / Ölçülemedi",
             o["zamaninda"] + o["asildi"], o["uyum_yuzde"]]
        )  # fmt: skip
    for g in sla["gecikme_nedenleri"]:
        satirlar.append(["Gecikme nedeni", g["ad"], g["adet"], None])
    for b in sla["bekleme_nedenleri"]:
        satirlar.append(
            [f"İş beklemesi{' (SLA durdurur)' if b['sla_durdurur'] else ''}", b["ad"], b["adet"],
             b["toplam_saat"]]
        )  # fmt: skip
    return export_svc.Sayfa(
        "SLA ve Gecikme",
        [
            export_svc.Sutun("Bölüm"),
            export_svc.Sutun("Kalem"),
            export_svc.Sutun("Adet", "tamsayi"),
            export_svc.Sutun("Oran / Saat", "ondalik"),
        ],
        satirlar,
        ust_bilgi=[
            ["Yalnız günlük servis; ölçülemedi ve damgasız işler uyum paydasında yoktur."],
            [],
        ],
    )


async def _tekrar_sayfasi(db, user, clock, f) -> export_svc.Sayfa:
    rapor = await rh.tekrar_ariza_raporu(db, user, clock, f)
    ust = [[k["baslik"], k["deger"]] for k in rapor["kpiler"]]
    ust += [
        ["Onaylı oran (%)", rapor["onayli_oran"]],
        ["Aday oranı (%) — onaysız", rapor["aday_oran"]],
        ["Pencere (gün)", rapor["gun"]],
        [],
    ]
    return export_svc.Sayfa(
        "Tekrar Arıza",
        [
            export_svc.Sutun("İş Emri No"),
            export_svc.Sutun("Birim"),
            export_svc.Sutun("Kategori"),
            export_svc.Sutun("Çözüm", "zaman"),
            export_svc.Sutun("Durum"),
            export_svc.Sutun("Sonraki İş"),
        ],
        [
            [
                r["so_no"],
                r["birim"],
                r["kategori"],
                r["cozum"],
                r["etiket"],
                ", ".join(r["sonraki_isler"]),
            ]
            for r in rapor["satirlar"]
        ],
        ust_bilgi=ust,
    )


def _tanimlar_sayfasi(user: User) -> export_svc.Sayfa:
    t = rt.tanimlar(user)
    satirlar = [[k["kod"], k["baslik"], k["tanim"]] for k in t["kpiler"]]
    satirlar += [[o["kod"], o["baslik"], o["tanim"]] for o in t["olculer"]]
    satirlar.append([])
    satirlar += [["Not", n, None] for n in t["notlar"]]
    satirlar.append(
        [
            "Pivot",
            "Veri_IsEmirleri (ve yetkiliyse Veri_Sureler) adlı Excel Tablolarından Ekle → "
            "PivotTable ile pivot kurulur. LibreOffice'te pivot yenilemesi garanti değildir.",
            f"Şablon sürümü: {SABLON_SURUMU}",
        ]
    )
    return export_svc.Sayfa(
        "Tanımlar",
        [export_svc.Sutun("Kod"), export_svc.Sutun("Gösterge"), export_svc.Sutun("Tanım")],
        satirlar,
    )


__all__ = ["XLSX", "disa_aktarim_denetimi", "dosya_adi", "kitap", "liste_satirlari", "sayfa"]
