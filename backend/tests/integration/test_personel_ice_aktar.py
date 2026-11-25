"""Personel CSV içe aktarma (`app.seeds.personel_ice_aktar`, KARARLAR 2026-11-25).

Kilitlenen kurallar:
- Kullanıcı `ad.soyad` adıyla, birimi birincil açılır; sicil verilmez (tarih
  bilinmeden sıra bozulur, "Sicil numarala" dağıtır).
- Parola geçicidir: ilk girişte değişim zorunlu; özet dışında saklanmaz.
- Yönetici aynı dosyadaki addan bağlanır (izin onay zinciri).
- Tekrar çalıştırmak çift kayıt üretmez ve parolaya dokunmaz; `parola_yenile`
  var olan kişiye yeni geçici parola verir.
- Hatalı satır hiçbir kaydı açmaz.
"""

import pytest
from sqlalchemy import func, select

from app.models import User
from app.seeds import personel_ice_aktar as ia
from app.services.auth import verify_password

pytestmark = pytest.mark.integration

CSV = """ad_soyad;birim;rol;saha_rolu;unvan;yonetici
Deniz Örnekçi;GUVENLIK;SERVIS_SEF;SEF;Saha ve Operasyon Takım Lideri;
Kemal Ali Şimşekoğlu;GUVENLIK;SERVIS_TEKNISYEN;TEKNISYEN;Saha Teknisyeni;Deniz Örnekçi
Ece Çağlar;GUVENLIK;SERVIS_TEKNISYEN;TEKNISYEN;Saha Teknisyeni;Deniz Örnekçi
"""


async def test_ice_aktar_tekrar_ve_parola(client, db, tmp_path) -> None:
    sonuc = await ia.ice_aktar(db, ia.satirlari_oku(CSV), clock=client.clock)
    await db.commit()
    assert [s.kullanici_adi for s in sonuc] == ["deniz.ornekci", "kemal.simsekoglu", "ece.caglar"]
    assert all(s.parola and s.yeni for s in sonuc)
    assert all(s.sicil_no is None for s in sonuc)

    lider = await db.scalar(select(User).where(User.username == "deniz.ornekci"))
    tek = await db.scalar(select(User).where(User.username == "kemal.simsekoglu"))
    await db.refresh(lider, ["role", "birimler"])
    await db.refresh(tek, ["role", "birimler"])
    assert lider.role.code == "SERVIS_SEF" and lider.saha_rolu == "SEF"
    assert tek.role.code == "SERVIS_TEKNISYEN" and tek.unvan == "Saha Teknisyeni"
    assert [(b.birim, b.is_primary) for b in tek.birimler] == [("GUVENLIK", True)]
    assert tek.yonetici_id == lider.id and lider.yonetici_id is None
    assert tek.giris_acik and tek.parola_degismeli
    assert verify_password(sonuc[1].parola, tek.password_hash)
    assert sonuc[1].parola not in tek.password_hash

    # Geçici parolayla giriş açılır; parola değişimi zorunlu.
    r = await client.post(
        "/api/auth/login", json={"username": "kemal.simsekoglu", "password": sonuc[1].parola}
    )
    assert r.status_code == 200, r.text

    # Tekrar: yeni kayıt yok, parola değişmez.
    eski_ozet = tek.password_hash
    tekrar = await ia.ice_aktar(db, ia.satirlari_oku(CSV), clock=client.clock)
    await db.commit()
    assert all(s.parola is None for s in tekrar)
    sayi = await db.scalar(select(func.count()).select_from(User).where(User.username.like("%.%")))
    assert sayi == 3
    await db.refresh(tek)
    assert tek.password_hash == eski_ozet

    # Parola yenileme: kayıt yine eklenmez, parola değişir ve geçicidir.
    yenile = await ia.ice_aktar(db, ia.satirlari_oku(CSV), clock=client.clock, parola_yenile=True)
    await db.commit()
    assert all(s.parola and not s.yeni for s in yenile)
    await db.refresh(tek)
    assert verify_password(yenile[1].parola, tek.password_hash) and tek.parola_degismeli

    cikti = tmp_path / "parolalar.csv"
    ia.parolalari_yaz(cikti, sonuc)
    metin = cikti.read_text(encoding="utf-8-sig")
    assert "kemal.simsekoglu" in metin and sonuc[1].parola in metin


def test_hatali_satir_reddedilir() -> None:
    with pytest.raises(ia.IceAktarmaHatasi, match="birim"):
        ia.satirlari_oku("ad_soyad;birim;rol;saha_rolu;unvan;yonetici\nA B;YOK;SERVIS_SEF;;;\n")
    with pytest.raises(ia.IceAktarmaHatasi, match="soyad"):
        ia.satirlari_oku(
            "ad_soyad;birim;rol;saha_rolu;unvan;yonetici\nTek;GUVENLIK;SERVIS_SEF;;;\n"
        )
    with pytest.raises(ia.IceAktarmaHatasi, match="eksik"):
        ia.satirlari_oku("ad;birim\nA B;GUVENLIK\n")
