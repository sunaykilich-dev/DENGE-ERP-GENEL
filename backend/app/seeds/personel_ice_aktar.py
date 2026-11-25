"""Personeli CSV'den toplu açar ve giriş için geçici parola üretir (KARARLAR 2026-11-25).

Kullanım (backend klasöründe)::

    python -m app.seeds.personel_ice_aktar --dosya kisiler.csv --cikti parolalar.csv

Girdi CSV (UTF-8, `;` ayraçlı, ilk satır başlık)::

    ad_soyad;birim;rol;saha_rolu;unvan;yonetici
    Ayşe Yılmaz;GUVENLIK;SERVIS_SEF;SEF;Saha ve Operasyon Takım Lideri;
    Can Demir;GUVENLIK;SERVIS_TEKNISYEN;TEKNISYEN;Saha Teknisyeni;Ayşe Yılmaz

- `yonetici`: aynı dosyadaki bir kişinin adı ya da var olan kullanıcı adı
  (izin onay zinciri buradan yürür). Boş olabilir.
- Kullanıcı adı `ad.soyad` (Türkçe harfler sadeleşir, ad = ilk ad, soyad =
  son kelime); çakışırsa sonuna sayı eklenir.
- Sicil VERİLMEZ: sicil şirket geçmişine (işe giriş tarihi) göre sıralanır
  (KARARLAR 2026-11-20 §8); tarih bilinmeden numara vermek sırayı bozar. İK
  tarihleri girince Personel › Liste › "Sicil numarala" ile dağıtılır.
- Parola GEÇİCİDİR: ilk girişte değiştirilmesi zorunlu, 72 saat geçerli
  (`auth.gecici_parola_ata`). Parolalar yalnız `--cikti` dosyasına yazılır;
  ekrana basılmaz, veritabanında yalnız özeti durur.
- Tekrar çalıştırmak güvenlidir: aynı ad soyad ve birimle kayıtlı kişi
  atlanır (parolası değişmez). `--parola-yenile` ile var olan kişiye de yeni
  geçici parola verilir ve girişi açılır (rol/unvan değişmez).

Kişi listesi kişisel veridir: depoya konmaz (`.yerel_gizli/` gibi git dışı bir
yerde tutulur).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock, RealClock
from app.db import get_session_factory
from app.models import Role, User, UserUnit
from app.permissions import BIRIMLER, ROLES, SAHA_ROLLERI
from app.services import audit
from app.services.auth import gecici_parola_ata, gecici_parola_uret
from app.services.normalize import tr_normkey

ALANLAR = ("ad_soyad", "birim", "rol", "saha_rolu", "unvan", "yonetici")


class IceAktarmaHatasi(Exception):
    pass


@dataclass
class Satir:
    ad_soyad: str
    birim: str
    rol: str
    saha_rolu: str | None
    unvan: str | None
    yonetici: str | None


@dataclass
class Sonuc:
    ad_soyad: str
    kullanici_adi: str
    parola: str | None  # None: zaten vardı, dokunulmadı
    sicil_no: str | None
    rol: str
    yeni: bool = True


def _bos(x: str | None) -> str | None:
    return (x or "").strip() or None


def satirlari_oku(metin: str) -> list[Satir]:
    okuyucu = csv.DictReader(metin.splitlines(), delimiter=";")
    eksik = [a for a in ALANLAR if a not in (okuyucu.fieldnames or [])]
    if eksik:
        raise IceAktarmaHatasi(f"Başlıkta eksik sütun: {', '.join(eksik)}")
    satirlar: list[Satir] = []
    for no, r in enumerate(okuyucu, start=2):
        ad = re.sub(r"\s+", " ", (r["ad_soyad"] or "").strip())
        if not ad:
            continue
        if len(ad.split(" ")) < 2:
            raise IceAktarmaHatasi(f"{no}. satır: ad ve soyad birlikte yazılmalı ({ad})")
        birim = (r["birim"] or "").strip().upper()
        if birim not in BIRIMLER:
            raise IceAktarmaHatasi(f"{no}. satır: bilinmeyen birim {birim!r}")
        rol = (r["rol"] or "").strip().upper()
        if rol not in ROLES:
            raise IceAktarmaHatasi(f"{no}. satır: bilinmeyen rol {rol!r}")
        saha = _bos(r["saha_rolu"])
        saha = saha.upper() if saha else None
        if saha is not None and saha not in SAHA_ROLLERI:
            raise IceAktarmaHatasi(f"{no}. satır: bilinmeyen saha rolü {saha!r}")
        satirlar.append(Satir(ad, birim, rol, saha, _bos(r["unvan"]), _bos(r["yonetici"])))
    return satirlar


def kullanici_adi_tabani(ad_soyad: str) -> str:
    """`Mehmet Burak Şahinbaş` → `mehmet.sahinbas`."""
    parcalar = [re.sub(r"[^a-z0-9]+", "", tr_normkey(p)) for p in ad_soyad.split(" ")]
    parcalar = [p for p in parcalar if p]
    return f"{parcalar[0]}.{parcalar[-1]}"[:45]


async def _bos_kullanici_adi(db: AsyncSession, taban: str) -> str:
    aday, n = taban, 1
    while await db.scalar(select(User.id).where(User.username == aday).limit(1)) is not None:
        n += 1
        aday = f"{taban}{n}"
    return aday


async def _var_olan(db: AsyncSession, s: Satir) -> User | None:
    return await db.scalar(
        select(User)
        .join(UserUnit, UserUnit.user_id == User.id)
        .where(
            # Tam ad: Postgres lower() Türkçe harfi Python gibi küçültmeyebilir.
            User.full_name == s.ad_soyad,
            UserUnit.birim == s.birim,
            User.ayrilis_tarihi.is_(None),
        )
        .limit(1)
    )


async def ice_aktar(
    db: AsyncSession,
    satirlar: list[Satir],
    *,
    clock: Clock,
    aktor_id: int | None = None,
    parola_yenile: bool = False,
) -> list[Sonuc]:
    roller = {r.code: r for r in (await db.scalars(select(Role))).all()}
    sonuclar: list[Sonuc] = []
    kisiler: dict[str, User] = {}
    for s in satirlar:
        rol = roller.get(s.rol)
        if rol is None:
            raise IceAktarmaHatasi(f"Rol veritabanında yok: {s.rol} (rolleri eşitleyin)")
        var = await _var_olan(db, s)
        if var is not None:
            kisiler[s.ad_soyad.lower()] = var
            yeni_parola = None
            if parola_yenile:
                yeni_parola = gecici_parola_uret()
                gecici_parola_ata(var, yeni_parola, clock)
                var.giris_acik = True
                await audit.log(
                    db,
                    "users",
                    "personel.gecici_parola",
                    entity_id=var.id,
                    new_value={"kullanici_adi": var.username, "kaynak": "ice_aktar"},
                    user_id=aktor_id,
                )
            sonuclar.append(
                Sonuc(s.ad_soyad, var.username, yeni_parola, var.sicil_no, s.rol, yeni=False)
            )
            continue
        parola = gecici_parola_uret()
        kisi = User(
            full_name=s.ad_soyad,
            username=await _bos_kullanici_adi(db, kullanici_adi_tabani(s.ad_soyad)),
            password_hash="",
            role_id=rol.id,
            is_active=True,
            giris_acik=True,
            unvan=s.unvan,
            saha_rolu=s.saha_rolu,
        )
        gecici_parola_ata(kisi, parola, clock)
        db.add(kisi)
        await db.flush()
        db.add(UserUnit(user_id=kisi.id, birim=s.birim, is_primary=True, created_by=aktor_id))
        await db.flush()
        await audit.log(
            db,
            "users",
            "personel.ice_aktar",
            entity_id=kisi.id,
            new_value={
                "ad": kisi.full_name,
                "kullanici_adi": kisi.username,
                "rol": s.rol,
                "birim": s.birim,
                "sicil_no": kisi.sicil_no,
            },
            user_id=aktor_id,
        )
        kisiler[s.ad_soyad.lower()] = kisi
        sonuclar.append(Sonuc(s.ad_soyad, kisi.username, parola, kisi.sicil_no, s.rol))

    # Yöneticiler: önce dosyadaki adlar, sonra var olan kullanıcı adı.
    for s in satirlar:
        if not s.yonetici:
            continue
        kisi = kisiler[s.ad_soyad.lower()]
        yonetici = kisiler.get(s.yonetici.lower()) or await db.scalar(
            select(User).where(User.username == s.yonetici)
        )
        if yonetici is None:
            raise IceAktarmaHatasi(f"{s.ad_soyad}: yönetici bulunamadı ({s.yonetici})")
        if yonetici.id != kisi.id and kisi.yonetici_id is None:
            kisi.yonetici_id = yonetici.id
    await db.flush()
    return sonuclar


def parolalari_yaz(yol: Path, sonuclar: list[Sonuc]) -> None:
    with yol.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["ad_soyad", "kullanici_adi", "gecici_parola", "sicil_no", "rol"])
        for s in sonuclar:
            w.writerow(
                [s.ad_soyad, s.kullanici_adi, s.parola or "(değişmedi)", s.sicil_no or "", s.rol]
            )
    try:
        os.chmod(yol, 0o600)
    except OSError:
        pass


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Personeli CSV'den açar (geçici parolalı)")
    parser.add_argument("--dosya", required=True, type=Path, help="Girdi CSV (; ayraçlı)")
    parser.add_argument(
        "--cikti",
        required=True,
        type=Path,
        help="Kullanıcı adı ve geçici parolaların yazılacağı CSV",
    )
    parser.add_argument(
        "--parola-yenile",
        action="store_true",
        help="Zaten kayıtlı kişilere de yeni geçici parola ver ve girişlerini aç",
    )
    args = parser.parse_args(argv)
    try:
        satirlar = satirlari_oku(args.dosya.read_text(encoding="utf-8-sig"))
    except IceAktarmaHatasi as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 2
    async with get_session_factory()() as db:
        try:
            sonuclar = await ice_aktar(
                db, satirlar, clock=RealClock(), parola_yenile=args.parola_yenile
            )
        except IceAktarmaHatasi as exc:
            await db.rollback()
            print(f"Hata: {exc}", file=sys.stderr)
            return 2
        await db.commit()
    parolalari_yaz(args.cikti, sonuclar)
    yeni = sum(1 for s in sonuclar if s.yeni)
    yenilenen = sum(1 for s in sonuclar if not s.yeni and s.parola)
    print(
        f"{yeni} yeni kullanıcı açıldı, {len(sonuclar) - yeni} zaten vardı "
        f"({yenilenen} kişiye yeni geçici parola)."
    )
    print(f"Kullanıcı adları ve geçici parolalar: {args.cikti}")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
