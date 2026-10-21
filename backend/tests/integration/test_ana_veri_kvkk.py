"""Ana veri KVKK ve denetim (TS-016, E14-03 revised).

`addresses` ve `account_aliases` yeni kişisel veri taşıyor (bireysel
müşterinin tesisi evidir; eski yazımlar kişi adı içerebilir). Anonimleştirme
bunları kapsamazsa "geri alınamaz imha" bilgi düzeyinde geri alınabilir
kalırdı: maskelenen metnin TÜRETİLMİŞ anahtarı (`site_key`, `alias_key`) ve
denetim izindeki eski değerler adı aynen taşıyordu (E14 B5).
"""

import pytest
from sqlalchemy import select

from app.models import Account, AccountAlias, Address, AuditLog
from app.services import kvkk
from app.services.normalize import tr_normkey

pytestmark = pytest.mark.integration


async def _giris(client, kullanici_ac, username: str = "admin", rol: str = "ADMIN"):
    await kullanici_ac(username, rol)
    r = await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})
    assert r.status_code == 200, r.text


async def _hesap(db, ad: str, **kw) -> Account:
    h = Account(title=ad, title_key=tr_normkey(ad), is_musteri=True, **kw)
    db.add(h)
    await db.commit()
    await db.refresh(h)
    return h


async def _anonimlestir(client, hesap_id: int):
    r = await client.post(
        f"/api/kvkk/hesaplar/{hesap_id}/anonimlestir",
        json={"gerekce": "KVKK-2026-77 silme talebi", "onay": True},
    )
    assert r.status_code == 200, r.text
    return r.json()


class TestAnonimlestirme:
    async def test_tesis_ve_takma_ad_maskelenir_satirlar_kalir(self, client, kullanici_ac, db):
        await _giris(client, kullanici_ac)
        h = await _hesap(db, "MEHMET KARACA")
        merkez = Address(account_id=h.id, line="Karaca Sok. 4 Daire 2", city="Bursa")
        tesis = Address(
            account_id=h.id,
            kind="TESIS",
            site_name="Karaca Villa",
            line="Gizli Yol 9",
            access_note="Anahtar komşuda",
            city="Bursa",
        )
        db.add_all([merkez, tesis])
        await db.flush()
        takma = AccountAlias(account_id=h.id, alias_text="Mehmet Karaca Ev", kaynak="ELLE")
        db.add(takma)
        await db.commit()

        sonuc = await _anonimlestir(client, h.id)
        assert sonuc["lokasyon"] == 2 and sonuc["takma_ad"] == 1

        for nesne in (merkez, tesis, takma):
            await db.refresh(nesne)
        assert kvkk.ANONIM_ISARETI in merkez.line
        assert kvkk.ANONIM_ISARETI in tesis.line and kvkk.ANONIM_ISARETI in tesis.site_name
        assert tesis.access_note is None
        # Türetilmiş anahtarlar maskeli metinden yeniden üretildi.
        assert "karaca" not in (tesis.site_key or "")
        assert "karaca" not in takma.alias_key
        assert kvkk.ANONIM_ISARETI in takma.alias_text
        # Ticari kayıt (lokasyon satırı) durur: servis işleri ona bağlı.
        assert await db.get(Address, tesis.id) is not None

    async def test_ayni_yazimla_yeni_takma_ad_acilabilir(self, client, kullanici_ac, db):
        """Global tekil `alias_key` eski adla kalsaydı yeni kayıt 409 alırdı."""
        await _giris(client, kullanici_ac)
        h = await _hesap(db, "ESKİ SAHİBİ")
        db.add(AccountAlias(account_id=h.id, alias_text="Ortak Yazım AVM", kaynak="ELLE"))
        await db.commit()
        await _anonimlestir(client, h.id)

        yeni = await _hesap(db, "YENİ SAHİBİ")
        r = await client.post(
            "/api/teknik-servis/ana-veri/takma-adlar",
            json={"hesap_id": yeni.id, "metin": "Ortak Yazım AVM"},
        )
        assert r.status_code == 201, r.text

    async def test_tesis_ve_takma_ad_denetim_satirlari_maskelenir(self, client, kullanici_ac, db):
        await _giris(client, kullanici_ac)
        h = await _hesap(db, "DENETİMLİ KİŞİ")
        r = await client.post(
            "/api/lokasyonlar",
            json={
                "hesap_id": h.id,
                "kind": "TESIS",
                "site_name": "Denetimli Ev",
                "line": "Ev Adresi 12",
                "city": "Ankara",
            },
        )
        assert r.status_code == 201, r.text
        t = await client.post(
            "/api/teknik-servis/ana-veri/takma-adlar",
            json={"hesap_id": h.id, "metin": "Denetimli Kişi Takma"},
        )
        assert t.status_code == 201, t.text
        # Silinen takma adın denetim satırı da hesaba bağlı kalmalı.
        assert (
            await client.delete(f"/api/teknik-servis/ana-veri/takma-adlar/{t.json()['id']}")
        ).status_code == 204

        await _anonimlestir(client, h.id)

        satirlar = (
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.entity.in_(("addresses", "account_aliases")),
                    AuditLog.is_personal_data.is_(True),
                )
            )
        ).all()
        assert len(satirlar) >= 3
        for s in satirlar:
            assert "Ev Adresi" not in str(s.new_value) + str(s.old_value)
            assert "Takma" not in str(s.new_value) + str(s.old_value)


class TestVeriBulma:
    async def test_adres_ve_takma_adda_arar(self, client, kullanici_ac, db):
        await _giris(client, kullanici_ac)
        h = await _hesap(db, "İLGİSİZ UNVAN")
        db.add(Address(account_id=h.id, line="Çınaraltı Sok. Özgür Apt.", city="İzmir"))
        db.add(AccountAlias(account_id=h.id, alias_text="Fatma Şahin Market", kaynak="ELLE"))
        await db.commit()

        r = await client.get("/api/kvkk/veri-bul", params={"arama": "ÖZGÜR APT"})
        assert r.status_code == 200, r.text
        assert r.json()["ozet"]["lokasyonlar"] == 1

        r = await client.get("/api/kvkk/veri-bul", params={"arama": "fatma şahin"})
        assert r.json()["ozet"]["takma_adlar"] == 1

    async def test_xlsx_dokumu_lokasyon_ve_takma_adi_icerir(self, client, kullanici_ac, db):
        """Talep sahibine verilen döküm JSON yanıtla aynı kayıtları taşımalı."""
        from io import BytesIO

        from openpyxl import load_workbook

        await _giris(client, kullanici_ac)
        h = await _hesap(db, "İLGİSİZ UNVAN")
        db.add(Address(account_id=h.id, kind="TESIS", site_name="Kervan Deposu", city="İzmir"))
        db.add(AccountAlias(account_id=h.id, alias_text="Kervan Takma", kaynak="ELLE"))
        await db.commit()

        r = await client.get("/api/kvkk/veri-bul.xlsx", params={"arama": "kervan"})
        assert r.status_code == 200, r.text
        sayfa = load_workbook(BytesIO(r.content)).active
        tipler = [satir[0] for satir in sayfa.iter_rows(values_only=True)]
        assert "Lokasyon" in tipler and "Takma ad" in tipler


class TestDenetim:
    async def test_denetim_izi_degistirilemez(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        assert (await client.put("/api/denetim", json={})).status_code == 405
        assert (await client.delete("/api/denetim")).status_code == 405

    async def test_hizli_ekleme_denetim_satiri_uretir(self, client, kullanici_ac, db):
        await _giris(client, kullanici_ac)
        r = await client.post(
            "/api/teknik-servis/ana-veri/hizli-musteri",
            json={"unvan": "Denetim Firması", "il": "Ankara", "tesis_adi": "Denetim Deposu"},
        )
        assert r.status_code == 201, r.text
        eylemler = set(
            (await db.scalars(select(AuditLog.action).where(AuditLog.user_id.is_not(None)))).all()
        )
        assert {"hesap.hizli_olustur", "lokasyon.olustur"} <= eylemler


class TestKayitDefterleri:
    def test_cekirdek_kayitlar(self):
        assert kvkk._tesisleri_anonimlestir in kvkk.ANONIMLESTIRME_KANCALARI
        assert {"addresses", "account_aliases"} <= set(kvkk.DENETIM_MASKE_VARLIKLARI)
        assert {"lokasyonlar", "takma_adlar"} <= set(kvkk.VERI_BUL_KANCALARI)
        assert {"addresses", "account_aliases"} <= set(kvkk.KISISEL_VARLIKLAR)

    def test_cekirdek_anahtar_ezilemez(self):
        async def _bos(db, arama):
            return []

        with pytest.raises(ValueError):
            kvkk.veri_bul_kaydet("hesaplar", _bos)
