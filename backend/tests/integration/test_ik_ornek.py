"""İK örnek veri komutu (`app.seeds.ik_ornek`).

Kilitlenen kurallar:
- Girişi açık her kişiye bir önceki ayın örnek bordrosu ve dört şablon belgesi gider.
- Tekrar çalıştırmak çift kayıt üretmez.
- Onay/itiraz uydurulmaz: bütün belgeler GONDERILDI'de kalır.
- Üretilen PDF geçerli başlıkla başlar ve personel ekranından açılır.
- `temizle` yalnız [ÖRNEK] kayıtlarını siler; olay tetikleyicisi yeniden açık kalır.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import func, select, text

from app.models import IkBelge, IkBelgeOlayi, IkGonderim
from app.seeds import ik_ornek

pytestmark = pytest.mark.integration


def test_pdf_turkce_harfleri_tasir():
    p = ik_ornek.ornek_pdf("Şablon", ["ğüşıöç ĞÜŞİÖÇ (parantez) \\"])
    assert p.startswith(b"%PDF-1.4") and p.rstrip().endswith(b"%%EOF")
    # cp1254: ğ=0xF0, ı=0xFD, ş=0xFE, İ=0xDD; parantez kaçışlı.
    assert b"\xf0\xfc\xfe\xfd\xf6\xe7" in p and b"\\(parantez\\)" in p


async def test_yukle_tekrar_temizle(client, db, kullanici_ac):
    await kullanici_ac("admin", "ADMIN")
    ali = await kullanici_ac("ali", "SERVIS_TEKNISYEN")
    kapali = await kullanici_ac("kapali", "SERVIS_TEKNISYEN")
    kapali.giris_acik = False
    await db.commit()

    # Sabit tarih son_tarih (bugün+14) kontrolünü zamanla geçmişe düşürüyordu.
    bugun = date.today()
    onceki = (bugun.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    s = await ik_ornek.yukle(db, bugun=bugun)
    await db.commit()
    assert s["alici"] == 2  # admin + ali; girişi kapalı kişi dışarıda
    assert (s["bordro"], s["sablon"], s["belge_gonderimi"]) == (2, 4, 4)

    g = await db.scalar(select(IkGonderim).where(IkGonderim.tur == "BORDRO"))
    assert g.donem == onceki and g.baslik.startswith("[ÖRNEK]")
    assert set((await db.scalars(select(IkBelge.durum))).all()) == {"GONDERILDI"}
    assert (
        await db.scalar(
            select(func.count()).select_from(IkBelge).where(IkBelge.user_id == kapali.id)
        )
        == 0
    )

    # Tekrar: hiçbir şey eklenmez.
    s2 = await ik_ornek.yukle(db, bugun=bugun)
    await db.commit()
    assert (s2["bordro"], s2["sablon"], s2["belge_gonderimi"]) == (0, 0, 0)
    assert await db.scalar(select(func.count()).select_from(IkBelge)) == 10

    # Personel kendi örnek bordrosunu açabilir.
    await client.post("/api/auth/login", json={"username": "ali", "password": "parola1234"})
    belgelerim = (await client.get("/api/ik/belgelerim")).json()
    assert len(belgelerim) == 5
    bordro = next(b for b in belgelerim if b["tur"] == "BORDRO")
    r = await client.get(f"/api/ik/belgelerim/{bordro['id']}/dosya")
    assert r.status_code == 200 and r.content.startswith(b"%PDF-")

    # Temizlik: örnek dışı gönderim korunur.
    gercek = IkGonderim(tur="FORM", baslik="Gerçek form", created_by=ali.id, updated_by=ali.id)
    db.add(gercek)
    await db.commit()
    t = await ik_ornek.temizle(db)
    await db.commit()
    assert t == {"gonderim": 5, "belge": 10, "sablon": 4}
    assert await db.scalar(select(func.count()).select_from(IkBelgeOlayi)) == 0
    assert (await db.scalars(select(IkGonderim.baslik))).all() == ["Gerçek form"]

    # Tetikleyici yeniden açık ("O" = origin modunda etkin).
    tetik = await db.scalar(
        text("select tgenabled from pg_trigger where tgname = 'trg_ik_belge_olayi_degismez'")
    )
    assert tetik == "O"
