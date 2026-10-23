"""Personel profili: girişsiz saha personelinin toplu ve TEKRARLANABİLİR yüklenmesi (TS-010).

E13-04 (M13-D01 özü): **gerçek personel listesi depoya GİRMEZ.** Eski
sistemde isimler koda gömülüydü; burada liste, depo dışındaki bir Excel'den
canlı İçe Aktarma çerçevesiyle (önizleme → karar → uygula → karantina)
yüklenir. Migration'lar ve seed personel üretmez; test dosyası sahte adlıdır.

Kurallar:

- **Eşleşme anahtarı sırayla sicil no, sonra kullanıcı adı.** Eşleşen kayıt
  ÇAKIŞMA olarak işaretlenir; varsayılan ATLAMAKTIR (çerçeve kuralı).
  Böylece aynı dosya ikinci kez uygulandığında 0 yeni satır açılır.
- **Yeni kayıt girişsizdir:** `giris_acik=false`, rol `SERVIS_TEKNISYEN`,
  parola özeti kimsenin bilmediği rastgele bir sırrın argon2 özeti ("!" gibi
  geçersiz özet 500 doğururdu). Giriş, kullanıcı yönetiminden ayrıca açılır.
- **Tahmin yazılmaz:** birim ve saha rolü yalnız açık sütundan okunur; ünvandan
  saha rolü türetilmez (E13-07 kontrol: rol kodundan/ünvandan türetme RET).
- **Güncelleme yalnız personel alanlarına** dokunur — rol, izin, parola ve
  giriş bu profille DEĞİŞMEZ. Üst yetkili (ADMIN / yüksek yetkili izinli)
  kullanıcıyla eşleşen satır HATA olur: Excel, İK'ya yöneticinin kartını
  değiştirmenin yan kapısı olmamalı.
- Parti iptali fiziksel silme yapmaz (çerçeve yalnız durum değiştirir);
  kullanıcı satırı hiçbir koşulda silinmez (denetim FK'si ve E13-12).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import Role, User, UserUnit
from app.models.rbac import BIRIM_KODLARI
from app.models.user import SAHA_ROLLERI
from app.services import audit, yetki
from app.services import auth as auth_service
from app.services.imports.cekirdek import Profil, SatirSonucu, Sutun
from app.services.imports.ortak import tarih_coz
from app.services.normalize import clean_cell, tr_normkey
from app.services.teknik_servis import personel as personel_svc

SUTUNLAR = (
    Sutun(
        "ad",
        ("Ad Soyad", "Adı Soyadı", "Personel", "Ad"),
        zorunlu=True,
        aciklama="Personelin adı soyadı (ekranlarda ve raporlarda görünen ad).",
    ),
    Sutun(
        "sicil",
        ("Sicil No", "Sicil", "Personel No"),
        aciklama="Eşleşme anahtarı. Aynı sicil sistemde varsa satır güncelleme adayıdır.",
    ),
    Sutun(
        "kullanici_adi",
        ("Kullanıcı Adı", "Kullanici Adi", "Username"),
        aciklama=(
            "Sicil yoksa eşleşme anahtarı. Boş bırakılırsa yeni kayıt için "
            "p.<sicil> biçiminde üretilir."
        ),
    ),
    Sutun("unvan", ("Ünvan", "Unvan", "Görev"), aciklama="Serbest ünvan; yetkiye etkisi yok."),
    Sutun(
        "saha_rolu",
        ("Saha Rolü", "Saha Rolu"),
        aciklama="SEF, TEKNISYEN, STAJYER, OFIS veya YOK. Boşsa girilmez (tahmin edilmez).",
    ),
    Sutun(
        "birimler",
        ("Birimler", "Birim"),
        aciklama=(
            "Virgülle ayrılmış birim kodları: " + ", ".join(BIRIM_KODLARI) + ". "
            "Boşsa birim yazılmaz."
        ),
    ),
    Sutun(
        "birincil_birim",
        ("Birincil Birim",),
        aciklama="Birimlerden biri. Tek birim yazıldıysa boş bırakılabilir.",
    ),
    Sutun("ise_giris", ("İşe Giriş", "Ise Giris", "İşe Giriş Tarihi"), aciklama="GG.AA.YYYY."),
)

_ALANLAR = ("full_name", "sicil_no", "unvan", "saha_rolu", "ise_giris_tarihi")


def _birimleri_coz(ham: str, birincil_ham: str) -> tuple[list[str], str | None]:
    """'GUVENLIK, POC' → (['GUVENLIK','POC'], birincil). Hata ValueError."""
    kodlar: list[str] = []
    for parca in ham.replace(";", ",").split(","):
        kod = tr_normkey(parca).upper().replace(" ", "_")
        if not kod:
            continue
        if kod not in BIRIM_KODLARI:
            raise ValueError(f"bilinmeyen birim: {parca.strip()}")
        if kod in kodlar:
            raise ValueError(f"birim iki kez yazılmış: {kod}")
        kodlar.append(kod)
    birincil = tr_normkey(birincil_ham).upper().replace(" ", "_") or None
    if birincil and birincil not in kodlar:
        raise ValueError(f"birincil birim birimler arasında değil: {birincil_ham}")
    if kodlar and birincil is None:
        if len(kodlar) > 1:
            raise ValueError("birden çok birim var; birincil birim yazılmalı")
        birincil = kodlar[0]
    return kodlar, birincil


class PersonelProfili(Profil):
    kod = "personel"
    ad = "Personel"
    aciklama = (
        "Girişsiz saha personeli (giriş hesabı açılmaz). Sicil no, yoksa kullanıcı "
        "adı ile eşleşir; aynı dosya ikinci kez yüklenirse yeni kayıt açılmaz."
    )
    sutunlar = SUTUNLAR

    async def dogrula(self, db: AsyncSession, satirlar: list[dict]) -> list[SatirSonucu]:
        sonuclar: list[SatirSonucu] = []
        gorulen_sicil: dict[str, int] = {}
        gorulen_kad: dict[str, int] = {}

        for sira, ham in enumerate(satirlar, start=1):
            r = SatirSonucu(satir_no=sira, ham={k: clean_cell(v) for k, v in ham.items()})

            ad = clean_cell(ham.get("ad"))
            if len(ad) < 2:
                r.hatalar.append("Ad soyad boş ya da çok kısa")
            else:
                r.veri["full_name"] = ad[:100]

            sicil = clean_cell(ham.get("sicil"))
            if sicil:
                if len(sicil) > 30:
                    r.hatalar.append("Sicil no 30 karakteri aşamaz")
                else:
                    r.veri["sicil_no"] = sicil
                    if sicil in gorulen_sicil:
                        r.hatalar.append(
                            f"Dosya içinde mükerrer sicil (ilk satır: {gorulen_sicil[sicil]})"
                        )
                    else:
                        gorulen_sicil[sicil] = sira

            kad = clean_cell(ham.get("kullanici_adi")).lower()
            if kad:
                if len(kad) > 50 or not all(c.isalnum() or c in "_.-" for c in kad):
                    r.hatalar.append(f"Kullanıcı adı geçersiz: {kad}")
                else:
                    r.veri["username"] = kad
                    if kad in gorulen_kad:
                        r.hatalar.append(
                            f"Dosya içinde mükerrer kullanıcı adı (ilk satır: {gorulen_kad[kad]})"
                        )
                    else:
                        gorulen_kad[kad] = sira

            unvan = clean_cell(ham.get("unvan"))
            if unvan:
                r.veri["unvan"] = unvan[:80]

            saha = clean_cell(ham.get("saha_rolu")).upper()
            if saha:
                if saha not in SAHA_ROLLERI:
                    r.hatalar.append(
                        f"Saha rolü geçersiz: {saha} (geçerli: {', '.join(SAHA_ROLLERI)})"
                    )
                else:
                    r.veri["saha_rolu"] = saha
            else:
                r.uyarilar.append("Saha rolü boş — kişi tayin listelerinde görünmez")

            birim_ham = clean_cell(ham.get("birimler"))
            if birim_ham:
                try:
                    kodlar, birincil = _birimleri_coz(
                        birim_ham, clean_cell(ham.get("birincil_birim"))
                    )
                except ValueError as exc:
                    r.hatalar.append(f"Birim: {exc}")
                else:
                    r.veri["birimler"] = ",".join(kodlar)
                    r.veri["birincil_birim"] = birincil
            elif clean_cell(ham.get("birincil_birim")):
                r.hatalar.append("Birincil birim yazılmış ama birimler boş")

            giris = ham.get("ise_giris")
            if clean_cell(giris):
                try:
                    r.veri["ise_giris_tarihi"] = tarih_coz(giris).isoformat()
                except ValueError as exc:
                    r.hatalar.append(f"İşe giriş: {exc}")

            sonuclar.append(r)

        await self._mevcutlari_isaretle(db, sonuclar)
        return sonuclar

    async def _mevcutlari_isaretle(self, db: AsyncSession, sonuclar: list[SatirSonucu]) -> None:
        siciller = [r.veri["sicil_no"] for r in sonuclar if r.gecerli and r.veri.get("sicil_no")]
        kadlar = [r.veri["username"] for r in sonuclar if r.gecerli and r.veri.get("username")]
        if not siciller and not kadlar:
            return
        kosul = []
        if siciller:
            kosul.append(User.sicil_no.in_(siciller))
        if kadlar:
            kosul.append(User.username.in_(kadlar))
        mevcutlar = (await db.scalars(select(User).where(or_(*kosul)))).all()
        sicile_gore = {u.sicil_no: u for u in mevcutlar if u.sicil_no}
        kada_gore = {u.username: u for u in mevcutlar}

        for r in sonuclar:
            if not r.gecerli:
                continue
            sicil = r.veri.get("sicil_no")
            kad = r.veri.get("username")
            # Sicil önce: sicil varsa eşleşme YALNIZ sicille yapılır; aynı
            # kullanıcı adının başka bir sicilde olması ayrı bir çakışmadır.
            mevcut = sicile_gore.get(sicil) if sicil else kada_gore.get(kad)
            if mevcut is None:
                if kad and kad in kada_gore:
                    r.hatalar.append(
                        f"Kullanıcı adı {kad} başka bir sicilde/kişide kayıtlı; eşleşme belirsiz"
                    )
                continue
            if yetki.ust_yetkili_mi(mevcut):
                r.hatalar.append(
                    "Eşleşen kullanıcı üst yetkili (yönetici); içe aktarmayla güncellenemez"
                )
                continue
            if sicil and mevcut.sicil_no == sicil and kad and mevcut.username != kad:
                r.uyarilar.append(
                    f"Sicil {sicil} sistemde {mevcut.username} kullanıcı adıyla kayıtlı; "
                    "kullanıcı adı değiştirilmez"
                )
            r.cakisma = {
                "tip": "mevcut",
                "kayit_id": mevcut.id,
                "aciklama": (
                    f"{mevcut.full_name} zaten kayıtlı (eşleşme: "
                    f"{'sicil no' if sicil else 'kullanıcı adı'}). Güncellenirse dosyada dolu "
                    "olan personel alanları yazılır; rol, izin, parola ve giriş DEĞİŞMEZ."
                ),
            }

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
        rol = await db.scalar(
            select(Role).where(Role.code == personel_svc.VARSAYILAN_PERSONEL_ROLU)
        )
        if rol is None:
            raise ValueError(
                f"Varsayılan personel rolü ({personel_svc.VARSAYILAN_PERSONEL_ROLU}) tanımlı değil."
            )

        for satir, _karar in self.uygulanacaklar(satirlar, kararlar):
            veri: dict[str, Any] = satir["veri"]
            alanlar = _alanlara_cevir(veri)
            cakisma = satir.get("cakisma")

            if cakisma:
                kisi = await db.get(User, cakisma["kayit_id"])
                if kisi is None or yetki.ust_yetkili_mi(kisi):
                    continue
                for alan, deger in alanlar.items():
                    setattr(kisi, alan, deger)
                await audit.log_change(
                    db, kisi, "personel.ice_aktar", user_id=user_id, is_personal_data=True
                )
                if veri.get("birimler"):
                    await _birimleri_esitle(db, kisi, veri, user_id=user_id)
                sayac["guncellendi"] += 1
                continue

            sicil = alanlar.get("sicil_no")
            kisi = User(
                username=veri.get("username") or await personel_svc.kullanici_adi_uret(db, sicil),
                password_hash=personel_svc.rastgele_parola_ozeti(),
                role_id=rol.id,
                is_active=True,
                giris_acik=False,
                **alanlar,
            )
            db.add(kisi)
            await db.flush()
            await db.refresh(kisi, ["birimler"])
            await audit.log(
                db,
                "users",
                "personel.ice_aktar",
                entity_id=kisi.id,
                new_value={"ad": kisi.full_name, "sicil_no": kisi.sicil_no, "giris_acik": False},
                user_id=user_id,
                is_personal_data=True,
            )
            if veri.get("birimler"):
                await _birimleri_esitle(db, kisi, veri, user_id=user_id, yeni=True)
            sayac["eklendi"] += 1

        await db.flush()
        sayac["atlandi"] = len(satirlar) - sayac["eklendi"] - sayac["guncellendi"]
        return sayac


# `services/imports/__init__.py` sözleşmesi: profil ve izni buradan okunur
# (plan §1.11 — `PROFIL_IZINLERI['personel'] = 'personel.yaz'`).
PROFIL = PersonelProfili()
PROFIL_IZNI = "personel.yaz"


def _alanlara_cevir(veri: dict[str, Any]) -> dict[str, Any]:
    from datetime import date

    alanlar: dict[str, Any] = {}
    for alan in _ALANLAR:
        deger = veri.get(alan)
        if deger in (None, "", "None"):
            continue
        alanlar[alan] = date.fromisoformat(deger) if alan == "ise_giris_tarihi" else deger
    return alanlar


async def _birimleri_esitle(
    db: AsyncSession, kisi: User, veri: dict[str, Any], *, user_id: int | None, yeni: bool = False
) -> None:
    """Dosyadaki birim listesini kişiye eşitler (denetim + oturum düşürme).

    `personel.birimleri_yaz` aktör nesnesi ister (kapsam ve kendi-birimi
    kuralları); içe aktarma çerçevesi yalnız `user_id` verdiği için kural
    burada tekrarlanır: profil `personel.yaz` ister ve o izin yalnız
    kapsamı TUMU olan rollerde (IK, SERVIS_YONETICI, ADMIN).
    """
    if user_id is not None and kisi.id == user_id:
        return  # kendi birimini değiştiremez — sessizce dokunulmaz
    kodlar = [k for k in str(veri["birimler"]).split(",") if k]
    birincil = veri.get("birincil_birim")
    await db.refresh(kisi, ["birimler"])
    eski = sorted((u.birim, u.is_primary) for u in kisi.birimler)
    hedef = sorted((k, k == birincil) for k in kodlar)
    if eski == hedef:
        return
    for u in list(kisi.birimler):
        if u.is_primary:
            u.is_primary = False
    await db.flush()
    for u in list(kisi.birimler):
        if u.birim not in kodlar:
            kisi.birimler.remove(u)
    await db.flush()
    var = {u.birim: u for u in kisi.birimler}
    for k in kodlar:
        if k in var:
            var[k].is_primary = k == birincil
            var[k].updated_by = user_id
        else:
            kisi.birimler.append(
                UserUnit(
                    user_id=kisi.id,
                    birim=k,
                    is_primary=k == birincil,
                    created_by=user_id,
                    updated_by=user_id,
                )
            )
    await db.flush()
    if not yeni:
        await auth_service.revoke_all_sessions(db, kisi.id)
    await audit.log(
        db,
        "users",
        "birim.degistir",
        entity_id=kisi.id,
        old_value={"birimler": [{"birim": b, "birincil": p} for b, p in eski]},
        new_value={"birimler": [{"birim": b, "birincil": p} for b, p in hedef]},
        user_id=user_id,
        is_personal_data=True,
    )
