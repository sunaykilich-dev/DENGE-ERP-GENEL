"""Göç-1 testlerinin ortak kurulumu: örnek döküm + eşleştirilecek ana veri.

Döküm `tests/fixtures/goc_v1/*.csv` SAHTE verilerdir (gerçek müşteri/personel
yok). Kurulum: iki müşteri hesabı (biri "Depo Girişi" tesisiyle), bir
teknisyen ("Ali Veli") ve onun üç kaynak alandaki ONAYLI ad eşlemesi.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from app.models import Account, Address, PersonnelNameMap, Role, User
from app.services.teknik_servis import ad_esleme
from app.services.teknik_servis import personel as personel_svc

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "goc_v1"


@dataclass
class GocOrtami:
    akyaka: Account
    lojistik: Account
    depo: Address
    ali: User


async def kisi_ac(db, ad: str, kullanici_adi: str) -> User:
    rol = await db.scalar(select(Role).where(Role.code == "SERVIS_TEKNISYEN"))
    kisi = User(
        full_name=ad,
        username=kullanici_adi,
        password_hash=personel_svc.rastgele_parola_ozeti(),
        role_id=rol.id,
        giris_acik=False,
        saha_rolu="TEKNISYEN",
    )
    db.add(kisi)
    await db.flush()
    return kisi


async def goc_ortami(db, *, ad_onayla: bool = True) -> GocOrtami:
    akyaka = Account(title="Akyaka Park AVM", is_musteri=True)
    lojistik = Account(title="Örnek Lojistik", is_musteri=True)
    db.add_all([akyaka, lojistik])
    await db.flush()
    depo = Address(account_id=lojistik.id, kind="TESIS", label="Tesis", site_name="Depo Girişi")
    db.add(depo)
    ali = await kisi_ac(db, "Ali Veli", "ali.veli")
    if ad_onayla:
        for alan in ad_esleme.KAYNAK_ALANLARI:
            db.add(
                PersonnelNameMap(
                    kaynak_sistem=ad_esleme.KAYNAK_SISTEM,
                    kaynak_alan=alan,
                    kaynak_ad="Ali Veli",
                    normal_ad=ad_esleme.normal_ad("Ali Veli"),
                    durum="ONAYLANDI",
                    onaylanan_user_id=ali.id,
                )
            )
    await db.commit()
    return GocOrtami(akyaka=akyaka, lojistik=lojistik, depo=depo, ali=ali)
