"""Kullanıcı profili: organizasyon listesinden toplu kullanıcı açılışı (2026-11-24).

Personel profilinden (`personel.py`, İK, girişsiz) farkı: rol, şirket üyeliği ve
giriş burada verilir; bu yüzden izni `sistem.kullanici`'dir ve kurallar
`POST /api/kullanicilar` ile aynıdır:

- Rol katalogda olmalı; birim kapsamlı rolde en az bir birim (E13-11).
- **ADMIN rolü içe aktarmayla verilmez** (Excel yönetici üretmenin yan kapısı
  olmamalı); diğer rolde aktör `yetki.rol_atanabilir_mi` sınamasından geçer.
- Şirket: "Hepsi" → bütün şirketler; boşsa birimlerden türetilir
  (`sirketler.varsayilan_uyelik`).
- **Parola dosyada yoktur.** Yeni hesap kimsenin bilmediği rastgele bir parolayla
  ve `parola_degismeli` açılır; kişiye giriş verilirken Kullanıcılar ekranından
  "Geçici parola üret" kullanılır (parola yalnız orada, bir kez görünür).
- Giriş "Kapalı" satır personel kartı olur (tayin, izin, özlük); rol boşsa
  varsayılan personel rolü.
- Yalnız YENİ kullanıcı açılır: kullanıcı adı sistemde varsa satır hatadır
  (güncelleme yok — rol/izin değişikliği Kullanıcılar ekranının işidir).
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import KullaniciSirketi, Role, User, UserUnit
from app.models.rbac import BIRIM_KODLARI
from app.models.user import SAHA_ROLLERI
from app.permissions import BIRIM_KAPSAMLARI, SIRKETLER
from app.services import audit, yetki
from app.services import sirketler as sirket_svc
from app.services.imports.cekirdek import Profil, SatirSonucu, Sutun
from app.services.imports.personel import _birimleri_coz
from app.services.normalize import clean_cell, tr_normkey
from app.services.teknik_servis import personel as personel_svc

HEPSI = {"hepsi", "tumu", "tum sirketler", "tumu sirketler"}
ACIK = {"acik", "evet", "e", "1", "var"}
KAPALI = {"kapali", "hayir", "h", "0", "yok"}

SUTUNLAR = (
    Sutun("ad", ("Ad Soyad", "Adı Soyadı", "Ad"), zorunlu=True, aciklama="Görünen ad."),
    Sutun(
        "kullanici_adi",
        ("Kullanıcı Adı", "Kullanici Adi", "Username"),
        aciklama="Boşsa ad.soyad biçiminde üretilir (Türkçe harfsiz).",
    ),
    Sutun(
        "rol",
        ("Rol", "Rol Kodu"),
        aciklama="Rol kodu (ör. SERVIS_TEKNISYEN). Giriş kapalıysa boş bırakılabilir.",
    ),
    Sutun("birimler", ("Birimler", "Birim"), aciklama=", ".join(BIRIM_KODLARI)),
    Sutun("birincil_birim", ("Birincil Birim",), aciklama="Birden çok birimde zorunlu."),
    Sutun(
        "sirketler",
        ("Şirketler", "Sirketler", "Şirket"),
        aciklama="TELEKOM / ELEKTRONIK / MOBILITE (virgülle) ya da Hepsi; boşsa birimden.",
    ),
    Sutun("unvan", ("Ünvan", "Unvan", "Görev"), aciklama="Serbest ünvan."),
    Sutun("saha_rolu", ("Saha Rolü", "Saha Rolu"), aciklama=", ".join(SAHA_ROLLERI)),
    Sutun("giris", ("Giriş", "Giris"), aciklama="Açık / Kapalı (boş = Açık)."),
    Sutun("eposta", ("E-posta", "Eposta", "Email"), aciklama="İsteğe bağlı."),
)

_TR = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


def kullanici_adi_oner(ad: str) -> str:
    """'Burak Mehmet Şahinbaş' → 'burak.sahinbas' (ilk ad + soyad)."""
    parcalar = [re.sub(r"[^a-z0-9]", "", p.translate(_TR).lower()) for p in ad.split()]
    parcalar = [p for p in parcalar if p]
    if not parcalar:
        return ""
    return ".".join([parcalar[0], parcalar[-1]] if len(parcalar) > 1 else parcalar)[:50]


def _sirket_coz(deger: str) -> list[str] | None:
    """None = birimden türet; [] dönmez (hata ValueError)."""
    if not deger:
        return None
    if tr_normkey(deger) in HEPSI:
        return sorted(SIRKETLER)
    kodlar: list[str] = []
    for parca in deger.replace(";", ",").split(","):
        anahtar = tr_normkey(parca)
        if not anahtar:
            continue
        for kod, ad in SIRKETLER.items():
            if anahtar in (tr_normkey(kod), tr_normkey(ad), tr_normkey(ad.replace("DENGE ", ""))):
                kodlar.append(kod)
                break
        else:
            raise ValueError(f"tanınmayan şirket: {parca.strip()}")
    return sorted(set(kodlar))


class KullaniciProfili(Profil):
    kod = "kullanici"
    ad = "Kullanıcılar"
    aciklama = (
        "Rol, birim, şirket ve giriş durumuyla toplu kullanıcı açılışı. Parola dosyada "
        "yoktur; giriş verilirken Kullanıcılar ekranından geçici parola üretilir."
    )
    sutunlar = SUTUNLAR
    guncelleme_destekli = False

    async def dogrula(self, db: AsyncSession, satirlar: list[dict]) -> list[SatirSonucu]:
        roller = {r.code: r for r in (await db.scalars(select(Role))).all()}
        sonuclar: list[SatirSonucu] = []
        gorulen: dict[str, int] = {}

        for sira, ham in enumerate(satirlar, start=1):
            r = SatirSonucu(satir_no=sira, ham={k: clean_cell(v) for k, v in ham.items()})
            h = {k: clean_cell(v) or "" for k, v in ham.items()}

            ad = h.get("ad", "")
            if len(ad) < 2:
                r.hatalar.append("Ad soyad boş ya da çok kısa")
            r.veri["full_name"] = ad[:100]

            kad = (h.get("kullanici_adi") or kullanici_adi_oner(ad)).lower()
            if not re.fullmatch(r"[a-z0-9_.-]{3,50}", kad or ""):
                r.hatalar.append(f"Kullanıcı adı geçersiz: {kad or '(boş)'}")
            elif kad in gorulen:
                r.hatalar.append(f"Dosya içinde aynı kullanıcı adı (ilk satır: {gorulen[kad]})")
            else:
                gorulen[kad] = sira
            r.veri["username"] = kad

            giris = tr_normkey(h.get("giris", "")) or "acik"
            if giris not in ACIK | KAPALI:
                r.hatalar.append(f"Giriş tanınmadı: {h.get('giris')} (Açık / Kapalı)")
            giris_acik = giris in ACIK
            r.veri["giris_acik"] = giris_acik

            rol_kodu = h.get("rol", "").upper() or (
                "" if giris_acik else personel_svc.VARSAYILAN_PERSONEL_ROLU
            )
            rol = roller.get(rol_kodu)
            if not rol_kodu:
                r.hatalar.append("Rol boş (girişi açık kullanıcıda zorunlu)")
            elif rol is None:
                r.hatalar.append(f"Bilinmeyen rol: {rol_kodu}")
            elif rol.code == "ADMIN":
                r.hatalar.append("ADMIN rolü içe aktarmayla verilmez; Kullanıcılar ekranından")
            r.veri["rol"] = rol_kodu

            kodlar: list[str] = []
            try:
                kodlar, birincil = _birimleri_coz(
                    h.get("birimler", ""), h.get("birincil_birim", "")
                )
            except ValueError as exc:
                r.hatalar.append(f"Birim: {exc}")
                birincil = None
            # Girişsiz personel kartında birim şartı yok (personel profiliyle aynı).
            if giris_acik and rol is not None and rol.scope in BIRIM_KAPSAMLARI and not kodlar:
                r.hatalar.append(f"{rol.code} rolü için en az bir birim yazılmalı")
            r.veri["birimler"] = ",".join(kodlar)
            r.veri["birincil_birim"] = birincil

            try:
                sirket = _sirket_coz(h.get("sirketler", ""))
            except ValueError as exc:
                r.hatalar.append(f"Şirket: {exc}")
                sirket = None
            if sirket is None and rol is not None:
                sirket = await sirket_svc.varsayilan_uyelik(db, rol, kodlar)
            r.veri["sirketler"] = ",".join(sirket or [])

            saha = h.get("saha_rolu", "").upper()
            if saha and saha not in SAHA_ROLLERI:
                r.hatalar.append(f"Saha rolü geçersiz: {saha}")
            r.veri["saha_rolu"] = saha or None
            r.veri["unvan"] = h.get("unvan", "")[:80] or None

            eposta = h.get("eposta", "").lower()
            if eposta and ("@" not in eposta or " " in eposta):
                r.hatalar.append(f"E-posta geçersiz: {eposta}")
            r.veri["email"] = eposta or None
            sonuclar.append(r)

        kadlar = [r.veri["username"] for r in sonuclar if r.gecerli]
        epostalar = [r.veri["email"] for r in sonuclar if r.gecerli and r.veri.get("email")]
        if kadlar:
            var = set(
                (await db.scalars(select(User.username).where(User.username.in_(kadlar)))).all()
            )
            for r in sonuclar:
                if r.veri.get("username") in var:
                    r.hatalar.append(
                        f"Kullanıcı adı {r.veri['username']} sistemde var; farklı bir ad yazın"
                    )
        if epostalar:
            var = set((await db.scalars(select(User.email).where(User.email.in_(epostalar)))).all())
            for r in sonuclar:
                if r.veri.get("email") in var:
                    r.hatalar.append(f"E-posta {r.veri['email']} başka kullanıcıda kayıtlı")
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
        sayac = self.bos_sayac()
        aktor = await db.get(User, user_id) if user_id is not None else None
        roller = {r.code: r for r in (await db.scalars(select(Role))).all()}
        for satir, _ in self.uygulanacaklar(satirlar, kararlar):
            v: dict[str, Any] = satir["veri"]
            rol = roller.get(v["rol"])
            if rol is None or rol.code == "ADMIN":
                continue
            if aktor is None or not yetki.rol_atanabilir_mi(aktor, rol):
                raise PermissionError(f"Bu rolü atayamazsınız: {rol.code}")
            if await db.scalar(select(User.id).where(User.username == v["username"])):
                continue  # önizleme ile uygulama arasında açılmış
            birimler = [b for b in (v.get("birimler") or "").split(",") if b]
            sirketler = [s for s in (v.get("sirketler") or "").split(",") if s]
            giris_acik = str(v.get("giris_acik")).lower() in ("true", "1")
            kisi = User(
                full_name=v["full_name"],
                username=v["username"],
                email=v.get("email") or None,
                password_hash=personel_svc.rastgele_parola_ozeti(),
                parola_degismeli=True,
                role_id=rol.id,
                is_active=True,
                giris_acik=giris_acik,
                unvan=v.get("unvan") or None,
                saha_rolu=v.get("saha_rolu") or None,
            )
            kisi.birimler = [
                UserUnit(birim=b, is_primary=(b == v.get("birincil_birim")), created_by=user_id)
                for b in birimler
            ]
            kisi.sirket_uyelikleri = [
                KullaniciSirketi(sirket_kod=k, created_by=user_id) for k in sirketler
            ]
            db.add(kisi)
            await db.flush()
            await audit.log(
                db,
                "users",
                "olustur.ice_aktar",
                entity_id=kisi.id,
                new_value={
                    "username": kisi.username,
                    "rol": rol.code,
                    "sirketler": sirketler,
                    "birimler": birimler,
                    "giris_acik": giris_acik,
                },
                user_id=user_id,
            )
            sayac["eklendi"] += 1
        sayac["atlandi"] = len(satirlar) - sayac["eklendi"]
        return sayac


PROFIL = KullaniciProfili()
PROFIL_IZNI = "sistem.kullanici"
