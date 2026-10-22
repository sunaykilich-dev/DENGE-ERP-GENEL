"""Yedek parça açılış stoğu içe aktarma profili (TS-134, E11-07).

Eski parça hareketleri göç EDİLMEZ (K22): servis depolarının başlangıç
bakiyesi fiziksel sayımdan bu profille yüklenir. Kurallar:

- **Hepsi-ya-hiç:** tek hatalı satır varsa `yaz()` ValueError atar; canlı
  içe aktarma ucu bunu 409'a çevirir ve transaction'ı geri alır — hiçbir
  hareket yazılmaz, hatalı satır numaraları mesajdadır. `api/imports.py`
  DEĞİŞMEZ (kontrol E11-07 a).
- **Depo kapsamı:** `dogrula()` kullanıcıyı bilmez; `yaz()` `user_id` ile
  kullanıcıyı yükler ve `parca.acilis_yukle` erişilebilir depo kümesini
  denetler (KENDI_BIRIMI kullanıcısı başka birimin deposuna açılış yazamaz).
- (Parça, depo) için önceden hareket varsa satır hatadır; tekillik ayrıca
  `uq_stok_hareket_acilis` ile şemada.

Satırlar tek yazıcıdan (`parca.hareket_yaz`, tür ACILIS) geçer.

Kayıt: `services/imports/__init__.py` `_EK_PROFIL_MODULLERI` listesine
"app.services.imports.parca_acilis" eklenince profil ekranda görünür (dosya
D2-I'de; ekleme talebi raporda).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import Product, StockMovement, User, Warehouse
from app.services.imports.cekirdek import Profil, SatirSonucu, Sutun


def _tam_sayi(ham: str) -> int:
    # Excel sayı hücresi "3.0" olarak gelir; virgül ondalık ayırıcı kabul edilir.
    try:
        deger = Decimal(ham.strip().replace(" ", "").replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("sayı değil") from exc
    if not deger.is_finite():
        raise ValueError("sayı değil")
    if deger != deger.to_integral_value():
        raise ValueError("tam sayı olmalı (ondalık adet girilemez)")
    if deger <= 0:
        raise ValueError("sıfırdan büyük olmalı")
    return int(deger)


def _tutar(ham: str) -> Decimal:
    try:
        deger = Decimal(ham.strip().replace(" ", "").replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("sayı değil") from exc
    if not deger.is_finite() or deger < 0:
        raise ValueError("negatif olamaz")
    return deger


class ParcaAcilisProfili(Profil):
    kod = "parca_acilis"
    ad = "Yedek parça açılış stoğu"
    aciklama = (
        "Servis depolarının başlangıç bakiyesi (fiziksel sayım). Tek hatalı satır varsa "
        "hiçbir satır yazılmaz; bir parça-depo çifti için yalnız bir kez yüklenir."
    )
    guncelleme_destekli = False
    sutunlar = (
        Sutun("parca_kodu", ("Parça Kodu", "Parca Kodu", "Kod", "Ürün Kodu"), zorunlu=True),
        Sutun("depo_kodu", ("Depo Kodu", "Depo"), zorunlu=True),
        Sutun("adet", ("Adet", "Miktar"), zorunlu=True, aciklama="Pozitif tam sayı"),
        Sutun(
            "birim_maliyet",
            ("Birim Maliyet", "Maliyet"),
            aciklama="TL, isteğe bağlı; boşsa maliyet bilinmiyor (0 yazılmaz)",
        ),
        Sutun("not", ("Not", "Açıklama"), aciklama="En çok 300 karakter"),
    )

    async def dogrula(self, db: AsyncSession, satirlar: list[dict]) -> list[SatirSonucu]:
        sonuclar: list[SatirSonucu] = []
        gorulen: dict[tuple[int, int], int] = {}
        for i, ham in enumerate(satirlar, start=1):
            r = SatirSonucu(satir_no=i, ham={k: str(v) for k, v in ham.items()})
            urun = await db.scalar(
                select(Product).where(
                    Product.code == (ham.get("parca_kodu") or "").strip(),
                    Product.is_deleted.is_(False),
                )
            )
            if urun is None:
                r.hatalar.append(f"Parça bulunamadı: {ham.get('parca_kodu')}")
            elif not urun.yedek_parca or urun.identity_kind != "YOK" or not urun.is_active:
                r.hatalar.append(f"{urun.code} aktif bir serisiz yedek parça kartı değil")
            depo = await db.scalar(
                select(Warehouse).where(Warehouse.code == (ham.get("depo_kodu") or "").strip())
            )
            if depo is None or not depo.servis_deposu:
                r.hatalar.append(f"Servis deposu bulunamadı: {ham.get('depo_kodu')}")
            elif not depo.is_active:
                r.hatalar.append(f"Depo pasif: {depo.code}")
            try:
                r.veri["adet"] = _tam_sayi(str(ham.get("adet", "")))
            except ValueError as exc:
                r.hatalar.append(f"Adet: {exc}")
            if ham.get("birim_maliyet"):
                try:
                    r.veri["birim_maliyet"] = str(_tutar(str(ham["birim_maliyet"])))
                except ValueError as exc:
                    r.hatalar.append(f"Birim maliyet: {exc}")
            notu = (ham.get("not") or "").strip()
            if len(notu) > 300:
                r.hatalar.append("Not en çok 300 karakter olabilir")
            r.veri["not"] = notu or None
            if urun is not None and depo is not None:
                r.veri["product_id"] = urun.id
                r.veri["depo_id"] = depo.id
                anahtar = (urun.id, depo.id)
                if anahtar in gorulen:
                    r.hatalar.append(f"Aynı parça ve depo {gorulen[anahtar]}. satırda da var")
                else:
                    gorulen[anahtar] = i
                    onceki = await db.scalar(
                        select(func.count()).where(
                            StockMovement.product_id == urun.id,
                            StockMovement.warehouse_id == depo.id,
                        )
                    )
                    if onceki:
                        r.hatalar.append(
                            "Bu parça ve depo için önceden hareket var; açılış yapılamaz"
                        )
            sonuclar.append(r)
        return sonuclar

    async def yaz(
        self,
        db: AsyncSession,
        satirlar: list[dict],
        *,
        clock: Clock,
        user_id: int | None,
        kararlar: dict[int, str],
    ) -> dict[str, int]:
        from app.services.teknik_servis import parca
        from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi

        hatali = [s["satir_no"] for s in satirlar if s.get("hatalar")]
        if hatali:
            raise ValueError(
                "Hatalı satırlar düzeltilmeden açılış yüklenmez: satır "
                + ", ".join(str(n) for n in hatali)
            )
        kullanici = await db.get(User, user_id) if user_id is not None else None
        if kullanici is None:
            raise ValueError("Açılış stoğu kullanıcı adına yüklenir; kullanıcı bulunamadı.")
        acilis = []
        for s in satirlar:
            veri: dict[str, Any] = s["veri"]
            maliyet = veri.get("birim_maliyet")
            acilis.append(
                parca.AcilisSatiri(
                    satir_no=s["satir_no"],
                    product_id=int(veri["product_id"]) if veri.get("product_id") else None,
                    depo_id=int(veri["depo_id"]) if veri.get("depo_id") else None,
                    adet=int(veri["adet"]),
                    unit_cost=Decimal(maliyet) if maliyet else None,
                    notes=veri.get("not") or None,
                )
            )
        try:
            yazilan = await parca.acilis_yukle(db, acilis, user=kullanici, clock=clock)
        except (ServisHatasi, ServisGirdiHatasi, parca.ParcaBulunamadi) as exc:
            raise ValueError(str(exc)) from exc
        return {"eklendi": len(yazilan), "guncellendi": 0, "atlandi": 0}


# `services/imports/__init__.py` sözleşmesi (plan §1.11).
PROFIL = ParcaAcilisProfili()
PROFIL_IZNI = "parca.yonet"
