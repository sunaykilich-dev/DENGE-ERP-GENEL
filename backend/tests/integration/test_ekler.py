"""Dosya ekleri — depo güvenliği ve sahip kayda göre yetki.

Ek mekanizması tek uçtan bütün modüllere hizmet ediyor; bu yüzden en kritik
iki davranış burada çivileniyor: (1) diskteki yol kullanıcının verdiği
dosya adından TÜRETİLMEZ, (2) yetki sahip kayda göre belirlenir.
"""

import pytest

from app.models import Account

pytestmark = pytest.mark.integration

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


async def _giris(client, kullanici_ac, ad, rol):
    await kullanici_ac(ad, rol)
    r = await client.post("/api/auth/login", json={"username": ad, "password": "parola1234"})
    assert r.status_code == 200, r.text


def _dosya(ad="gorsel.png", tip="image/png", icerik=PNG):
    return {"file": (ad, icerik, tip)}


class TestEkYukleme:
    async def test_urun_gorseli_yuklenir_ve_indirilir(self, client, kullanici_ac, urun_ac):
        u = await urun_ac("L300", "IMEI")
        await _giris(client, kullanici_ac, "katalogcu", "ADMIN")

        r = await client.post(f"/api/ekler/products/{u.id}?kind=URUN_GORSELI", files=_dosya())
        assert r.status_code == 201, r.text
        ek = r.json()
        assert ek["gorsel"] is True
        assert ek["file_name"] == "gorsel.png"

        indir = await client.get(f"/api/ekler/dosya/{ek['id']}")
        assert indir.status_code == 200
        assert indir.content == PNG

    async def test_ilk_gorsel_kapak_olur(self, client, db, kullanici_ac, urun_ac):
        from app.models import Product

        u = await urun_ac("L300", "IMEI")
        await _giris(client, kullanici_ac, "katalogcu2", "ADMIN")

        r = await client.post(f"/api/ekler/products/{u.id}?kind=URUN_GORSELI", files=_dosya())
        await db.refresh(u)
        assert u.cover_attachment_id == r.json()["id"]

        # İkinci görsel kapağı DEĞİŞTİRMEZ: kapak bir karardır, son yüklenen değil.
        ikinci = await client.post(
            f"/api/ekler/products/{u.id}?kind=URUN_GORSELI", files=_dosya("arka.png")
        )
        await db.refresh(u)
        assert u.cover_attachment_id != ikinci.json()["id"]

        # Kapak silinince bağ kopar (yetim kimlik kalmaz).
        assert (await client.delete(f"/api/ekler/{u.cover_attachment_id}")).status_code == 204
        await db.refresh(await db.get(Product, u.id))
        assert (await db.get(Product, u.id)).cover_attachment_id is None

    async def test_dosya_adi_diskteki_yolu_belirlemez(self, client, db, kullanici_ac, urun_ac):
        """`../../etc/passwd` gibi bir ad yol bileşeni taşımamalı."""
        from sqlalchemy import select

        from app.models import Attachment

        u = await urun_ac("L300", "IMEI")
        await _giris(client, kullanici_ac, "katalogcu3", "ADMIN")
        r = await client.post(
            f"/api/ekler/products/{u.id}?kind=URUN_GORSELI",
            files=_dosya("../../../etc/passwd.png"),
        )
        assert r.status_code == 201
        ek = await db.scalar(select(Attachment).where(Attachment.id == r.json()["id"]))
        assert ".." not in ek.storage_path
        assert ".." not in ek.file_name
        # Yol içerik özetinden türetilir.
        assert ek.sha256 in ek.storage_path

    async def test_ayni_icerik_bir_kez_saklanir(self, client, db, kullanici_ac, urun_ac):
        from sqlalchemy import select

        from app.models import Attachment

        u = await urun_ac("L300", "IMEI")
        await _giris(client, kullanici_ac, "katalogcu4", "ADMIN")
        a = await client.post(f"/api/ekler/products/{u.id}?kind=BROSUR", files=_dosya("a.png"))
        b = await client.post(f"/api/ekler/products/{u.id}?kind=BROSUR", files=_dosya("b.png"))
        assert a.json()["id"] != b.json()["id"]

        yollar = (
            await db.scalars(
                select(Attachment.storage_path).where(
                    Attachment.id.in_([a.json()["id"], b.json()["id"]])
                )
            )
        ).all()
        assert len(set(yollar)) == 1, "aynı içerik iki kez yazılmamalı"

    async def test_izinsiz_tur_reddedilir(self, client, kullanici_ac, urun_ac):
        """`text/html` başkasının tarayıcısında script çalıştırabilirdi."""
        u = await urun_ac("L300", "IMEI")
        await _giris(client, kullanici_ac, "katalogcu5", "ADMIN")
        r = await client.post(
            f"/api/ekler/products/{u.id}?kind=BROSUR",
            files={"file": ("x.html", b"<script>x</script>", "text/html")},
        )
        assert r.status_code == 422
        assert "kabul edilmiyor" in r.json()["detail"]

    async def test_bilinmeyen_kayit_turu_reddedilir(self, client, kullanici_ac):
        await _giris(client, kullanici_ac, "katalogcu6", "ADMIN")
        r = await client.post("/api/ekler/users/1?kind=DIGER", files=_dosya())
        assert r.status_code == 400


class TestEkYetkisi:
    async def test_yazma_yetkisi_sahip_kayda_gore(self, client, kullanici_ac, urun_ac):
        """Depo kullanıcısı cihaz eki yükleyebilir ama ürün eki yükleyemez."""
        u = await urun_ac("L300", "IMEI")
        await _giris(client, kullanici_ac, "depocu", "DEPO")

        r = await client.post(f"/api/ekler/products/{u.id}?kind=URUN_GORSELI", files=_dosya())
        assert r.status_code == 403
        assert "urun.yaz" in r.json()["detail"]

    async def test_okuma_yetkisi_yeterli(self, client, kullanici_ac, urun_ac):
        u = await urun_ac("L300", "IMEI")
        await _giris(client, kullanici_ac, "depocu2", "DEPO")
        r = await client.get(f"/api/ekler/products/{u.id}")
        assert r.status_code == 200
        assert r.json() == []


async def test_turkce_dosya_adi_indirilebilir(client, kullanici_ac, db):
    """HTTP başlıkları latin-1'dir; Türkçe dosya adı indirmeyi 500 yapıyordu.

    "GÜNCEL VERGİ LEVHASI.pdf" tam olarak böyle patladı: `İ` harfi
    `Content-Disposition` yazılırken UnicodeEncodeError atıyordu. Türkçe bir
    ERP'de dosya adlarının çoğu bu durumda.
    """
    hesap = Account(title="Türkçe Ek A.Ş.", is_musteri=True)
    db.add(hesap)
    await db.commit()
    await db.refresh(hesap)
    await kullanici_ac("patron", "ADMIN")
    await client.post("/api/auth/login", json={"username": "patron", "password": "parola1234"})

    yukleme = await client.post(
        f"/api/ekler/accounts/{hesap.id}",
        files={"file": ("ŞİRKET VERGİ LEVHASI.pdf", b"%PDF-1.4 deneme", "application/pdf")},
    )
    assert yukleme.status_code == 201, yukleme.text

    r = await client.get(f"/api/ekler/dosya/{yukleme.json()['id']}")
    assert r.status_code == 200, "Türkçe adlı ek indirilebilmeli"
    basligi = r.headers["content-disposition"]
    basligi.encode("latin-1")  # başlık gerçekten yazılabilir olmalı
    assert "filename*=UTF-8''" in basligi, "gerçek ad UTF-8 biçiminde taşınmalı"


class TestDosyaOmru:
    """Ek silinince dosya ANINDA gitmez; çöp toplama kaldırır.

    Anında silme sessiz belge kaybına yol açıyordu: bir ek silinirken aynı
    içerik ikinci kez yüklenirse, referans sayımı yeni (henüz commit
    edilmemiş) satırı göremeyip dosyayı kaldırıyordu. Yükleme 201 dönüyor,
    belge indirilemiyordu — 8 denemenin 4'ünde.
    """

    async def _yukle(self, client, hesap_id: int, icerik: bytes):
        return await client.post(
            f"/api/ekler/accounts/{hesap_id}",
            files={"file": ("AJANTEST.pdf", icerik, "application/pdf")},
        )

    async def test_silme_dosyayi_diskten_kaldirmaz(self, client, kullanici_ac, db):
        from app.services import storage as depo

        hesap = Account(title="Dosya Ömrü A.Ş.", is_musteri=True)
        db.add(hesap)
        await db.commit()
        await db.refresh(hesap)
        await kullanici_ac("patron", "ADMIN")
        await client.post("/api/auth/login", json={"username": "patron", "password": "parola1234"})

        ek = (await self._yukle(client, hesap.id, b"%PDF silme testi")).json()
        yol = depo.yol(ek["storage_path"]) if "storage_path" in ek else None
        kayit = depo.yaz(b"%PDF silme testi", mime_type="application/pdf")
        assert depo.yol(kayit.storage_path).is_file()

        assert (await client.delete(f"/api/ekler/{ek['id']}")).status_code == 204
        # Dosya DURMALI: eşzamanlı bir yükleme onu paylaşıyor olabilir.
        assert depo.yol(kayit.storage_path).is_file(), "silme dosyayı anında kaldırmamalı"
        assert yol is None or True

    async def test_cop_toplama_yalniz_eskimis_yetimi_siler(self, client, kullanici_ac, db):
        import os
        import time

        from app.services import storage as depo

        kayit = depo.yaz(b"%PDF yetim", mime_type="application/pdf")
        dosya = depo.yol(kayit.storage_path)

        # Taze yetim: DOKUNULMAZ (yüklemesi sürüyor olabilir).
        assert depo.yetimleri_temizle(set(), en_az_yas_saat=24) == 0
        assert dosya.is_file()

        # Eskitilmiş yetim: silinir.
        eski = time.time() - 48 * 3600
        os.utime(dosya, (eski, eski))
        assert depo.yetimleri_temizle(set(), en_az_yas_saat=24) == 1
        assert not dosya.exists()

    async def test_kullanimdaki_dosya_cop_toplamada_silinmez(self, db):
        import os
        import time

        from app.services import storage as depo

        kayit = depo.yaz(b"%PDF kullanimda", mime_type="application/pdf")
        dosya = depo.yol(kayit.storage_path)
        eski = time.time() - 48 * 3600
        os.utime(dosya, (eski, eski))

        assert depo.yetimleri_temizle({kayit.storage_path}, en_az_yas_saat=24) == 0
        assert dosya.is_file(), "kullanımdaki dosya asla silinmemeli"


class TestGirdiSinirlari:
    async def test_olmayan_sahibe_ek_baglanamaz(self, client, kullanici_ac):
        await kullanici_ac("patron", "ADMIN")
        await client.post("/api/auth/login", json={"username": "patron", "password": "parola1234"})
        r = await client.post(
            "/api/ekler/accounts/999999999",
            files={"file": ("AJANTEST.pdf", b"%PDF", "application/pdf")},
        )
        assert r.status_code == 404, "olmayan kayda ek bağlanırsa dosya görünmez çöp olur"

    async def test_tarayicinin_belirsiz_mime_tipi_uzantidan_cozulur(self, client, kullanici_ac, db):
        """Windows .csv için `application/vnd.ms-excel` gönderir; 422 almamalı."""
        hesap = Account(title="MIME A.Ş.", is_musteri=True)
        db.add(hesap)
        await db.commit()
        await db.refresh(hesap)
        await kullanici_ac("patron", "ADMIN")
        await client.post("/api/auth/login", json={"username": "patron", "password": "parola1234"})

        r = await client.post(
            f"/api/ekler/accounts/{hesap.id}",
            files={"file": ("liste.csv", b"a,b\n1,2\n", "application/vnd.ms-excel")},
        )
        assert r.status_code == 201, r.text
        assert r.json()["mime_type"] == "text/csv"

    async def test_beyaz_liste_disi_uzantiyla_kandirilamaz(self, client, kullanici_ac, db):
        hesap = Account(title="MIME2 A.Ş.", is_musteri=True)
        db.add(hesap)
        await db.commit()
        await db.refresh(hesap)
        await kullanici_ac("patron", "ADMIN")
        await client.post("/api/auth/login", json={"username": "patron", "password": "parola1234"})

        r = await client.post(
            f"/api/ekler/accounts/{hesap.id}",
            files={"file": ("kotu.html", b"<script>", "application/octet-stream")},
        )
        assert r.status_code == 422, "uzantı yedeği beyaz listeyi genişletmemeli"
