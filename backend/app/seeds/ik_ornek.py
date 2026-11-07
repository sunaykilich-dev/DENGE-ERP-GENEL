"""İK "Bordro ve Belgeler" için ÖRNEK veri — YALNIZ GELİŞTİRME / DENEME.

Kullanıcı isteği (2026-11-06): "bordrolar, formlar vs dummy dokümanları
çalışanlara yükle". Ekranları gerçek veriyle değil kurgusal belgelerle
denemek için:

* ERP'ye girebilen her etkin kişiye bir önceki ayın ÖRNEK bordrosu (tutarlar
  kurgusal, kişi kimliğinden türetilir; TCKN yok),
* dört şablon (İSG talimatı, KVKK aydınlatma metni, elektronik belge kabul
  taahhütnamesi, zimmet formu) ve bunların herkese gönderimi.

Her PDF'in başında "ÖRNEK BELGE — GERÇEK DEĞİLDİR" yazar, her başlık
`[ÖRNEK]` ile başlar. E-posta gönderilmez. Onay/itiraz UYDURULMAZ: imza
kanıtı zincirine sahte imza yazmamak için bütün belgeler "Gönderildi"
durumunda kalır; denemeyi kişi kendisi yapar.

Tekrar çalıştırılabilir: var olan örnek gönderim ve şablon atlanır.

    uv run python -m app.seeds.ik_ornek            # yükle
    uv run python -m app.seeds.ik_ornek --temizle  # örnekleri sil

**Canlıya geçmeden önce `--temizle` ŞART**: geliştirme veritabanı canlıya
taşınıyor (`app.yonetim canliya-hazirla`); örnek bordro gerçek kişiye
"maaş bordrosu" olarak görünmemeli. Olay tablosu UPDATE/DELETE'i reddeder;
temizlik tetikleyiciyi yalnız kendi işlemi içinde kapatır (tablo sahibi
gerekir) ve yalnız `[ÖRNEK]` gönderimlerine dokunur.
"""

import argparse
import asyncio
import random
import sys
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session_factory
from app.models import IkBelge, IkBelgeOlayi, IkBelgeSablonu, IkGonderim, Role, User
from app.services import ik_belge as svc
from app.services import storage

ONEK = "[ÖRNEK]"
UYARI = "ÖRNEK BELGE — GERÇEK DEĞİLDİR (deneme verisi)"

AYLAR = (
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
)  # fmt: skip


# --------------------------------------------------------------------------
# Bağımlılıksız küçük PDF üretici
# --------------------------------------------------------------------------
# WeasyPrint Windows geliştirme makinesinde Pango/Cairo olmadan çalışmıyor
# (`services/pdf.py`). Örnek belge için standart Helvetica yeter. Türkçe
# harfler: WinAnsi kodlamasının cp1254'ten farklı altı kodu `Differences`
# ile Türkçe glif adlarına çevrilir; metin cp1254 ile yazılır.
_TR_FARKLARI = (
    "/Differences [208 /Gbreve 221 /Idotaccent 222 /Scedilla "
    "240 /gbreve 253 /dotlessi 254 /scedilla]"
)


def _pdf_metin(s: str) -> str:
    ham = s.encode("cp1254", errors="replace")
    kacisli = ham.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    return kacisli.decode("latin-1")


def ornek_pdf(baslik: str, satirlar: list[str]) -> bytes:
    """Tek sayfa A4 PDF: kırmızı ÖRNEK uyarısı, başlık, satırlar."""
    akis = ["BT", "/F2 10 Tf", "0.8 0 0 rg", "50 800 Td", f"({_pdf_metin(UYARI)}) Tj", "ET"]
    akis += ["BT", "/F2 15 Tf", "0 0 0 rg", "50 768 Td", f"({_pdf_metin(baslik)}) Tj", "ET"]
    akis += ["BT", "/F1 10.5 Tf", "0 0 0 rg", "14 TL", "50 738 Td"]
    for i, satir in enumerate(satirlar[:48]):
        akis.append(("" if i == 0 else "T* ") + f"({_pdf_metin(satir)}) Tj")
    akis.append("ET")
    icerik = "\n".join(akis).encode("latin-1")

    def font(ad: str) -> bytes:
        return (
            f"<< /Type /Font /Subtype /Type1 /BaseFont /{ad} "
            f"/Encoding << /Type /Encoding /BaseEncoding /WinAnsiEncoding {_TR_FARKLARI} >> >>"
        ).encode()

    nesneler = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>",
        font("Helvetica"),
        font("Helvetica-Bold"),
        b"<< /Length %d >>\nstream\n" % len(icerik) + icerik + b"\nendstream",
    ]
    cikti = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    konumlar = []
    for no, govde in enumerate(nesneler, 1):
        konumlar.append(len(cikti))
        cikti += b"%d 0 obj\n" % no + govde + b"\nendobj\n"
    xref = len(cikti)
    cikti += b"xref\n0 %d\n0000000000 65535 f \n" % (len(nesneler) + 1)
    for k in konumlar:
        cikti += b"%010d 00000 n \n" % k
    cikti += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(nesneler) + 1,
        xref,
    )
    return bytes(cikti)


# --------------------------------------------------------------------------
# Örnek içerikler
# --------------------------------------------------------------------------
def _tl(x: float) -> str:
    tam, kurus = f"{x:,.2f}".split(".")
    return f"{tam.replace(',', '.')},{kurus} TL"


def bordro_satirlari(kisi: User, donem: str) -> list[str]:
    """Kurgusal bordro: tutarlar kişi kimliğinden türetilir (her çalıştırmada aynı)."""
    yil, ay = (int(p) for p in donem.split("-"))
    r = random.Random(f"{kisi.id}-{donem}")  # noqa: S311 — kurgusal tutar, güvenlik yok
    brut = round(r.uniform(32_000, 95_000), 2)
    sgk = round(brut * 0.14, 2)
    issizlik = round(brut * 0.01, 2)
    gv = round((brut - sgk - issizlik) * 0.15, 2)
    dv = round(brut * 0.00759, 2)
    yemek = round(r.choice([0, 3_300, 4_400]), 2)
    net = round(brut - sgk - issizlik - gv - dv + yemek, 2)
    return [
        f"Dönem          : {AYLAR[ay - 1]} {yil}",
        f"Çalışan        : {kisi.full_name}",
        f"Sicil no       : {kisi.sicil_no or '-'}",
        "",
        "KAZANÇLAR",
        f"  Brüt ücret (30 gün)              {_tl(brut)}",
        f"  Yemek yardımı                    {_tl(yemek)}",
        "",
        "KESİNTİLER",
        f"  SGK işçi payı (%14)              {_tl(sgk)}",
        f"  İşsizlik sigortası (%1)          {_tl(issizlik)}",
        f"  Gelir vergisi                    {_tl(gv)}",
        f"  Damga vergisi                    {_tl(dv)}",
        "",
        f"NET ÖDENEN                         {_tl(net)}",
        "",
        "Bu bordro deneme amacıyla üretilmiştir; tutarlar kurgusaldır ve",
        "hiçbir gerçek ücret bilgisini yansıtmaz.",
    ]


SABLONLAR: list[tuple[str, str, str, list[str]]] = [
    (
        "İş Sağlığı ve Güvenliği Talimatı",
        "TALIMAT",
        "Sahada ve atölyede uyulacak temel İSG kuralları.",
        [
            "1. Sahaya kişisel koruyucu donanım (baret, iş ayakkabısı, yelek) ile çıkılır.",
            "2. Enerji altındaki X-ray ve kapı dedektörlerine kapak açılarak müdahale edilmez.",
            "3. Yüksekte çalışmada emniyet kemeri takılmadan işe başlanmaz.",
            "4. Arıza ve kazalar aynı gün birim şefine ve İSG uzmanına bildirilir.",
            "5. Araç kullanırken telefonla konuşulmaz; hız sınırlarına uyulur.",
            "",
            "Bu talimatı okudum, anladım ve uyacağımı kabul ederim.",
        ],
    ),
    (
        "KVKK Çalışan Aydınlatma Metni",
        "KVKK",
        "6698 sayılı Kanun kapsamında çalışan kişisel verilerinin işlenmesi.",
        [
            "Veri sorumlusu: Denge (örnek metin).",
            "İşlenen veriler: kimlik, iletişim, özlük, bordro, iş sağlığı kayıtları.",
            "Amaç: iş sözleşmesinin kurulması ve ifası, yasal yükümlülükler.",
            "Hukuki sebep: KVKK md. 5/2 (c), (ç) ve (f).",
            "Aktarım: SGK, vergi dairesi, bankalar ve yetkili kamu kurumları.",
            "Haklarınız: KVKK md. 11 kapsamında başvuru hakkına sahipsiniz.",
            "",
            "Aydınlatma metnini okudum ve bilgilendirildim.",
        ],
    ),
    (
        "Elektronik Belge Kabul Taahhütnamesi",
        "TAAHHUTNAME",
        "Bordro ve belgelerin ERP üzerinden elektronik iletilmesine onay.",
        [
            "Ücret bordrolarımın ve işverence iletilecek form, talimat ve",
            "taahhütnamelerin Denge ERP 'Belgelerim' ekranı üzerinden elektronik",
            "olarak iletilmesini kabul ederim.",
            "",
            "Belgeyi ERP parolam ya da doğrulama kodumla onaylamamın, onay tarihi,",
            "IP adresi ve belge özetiyle birlikte kayda alınacağını biliyorum.",
            "",
            "Kağıt nüsha talep etme hakkım saklıdır.",
        ],
    ),
    (
        "Zimmet Teslim Formu",
        "FORM",
        "Personele teslim edilen demirbaş ve ekipman.",
        [
            "Teslim edilen          Adet   Seri no",
            "Dizüstü bilgisayar      1     ORNEK-NB-0001",
            "Cep telefonu            1     ORNEK-TEL-0001",
            "Ölçü aleti (multimetre) 1     ORNEK-OLC-0001",
            "",
            "Yukarıdaki malzemeleri sağlam ve eksiksiz teslim aldım. İşten",
            "ayrılışımda eksiksiz iade etmeyi taahhüt ederim.",
        ],
    ),
]


# --------------------------------------------------------------------------
# Yükleme
# --------------------------------------------------------------------------
def _onceki_ay(bugun: date) -> str:
    ilk = bugun.replace(day=1) - timedelta(days=1)
    return f"{ilk.year:04d}-{ilk.month:02d}"


async def _yonetici(db: AsyncSession) -> User:
    kisi = await db.scalar(select(User).where(User.username == "admin"))
    if kisi is None:
        kisi = await db.scalar(
            select(User).join(Role, Role.id == User.role_id).where(Role.code == "ADMIN").limit(1)
        )
    if kisi is None:
        raise SystemExit("Gönderen olacak yönetici (ADMIN) hesabı yok.")
    return kisi


async def yukle(db: AsyncSession, *, bugun: date | None = None) -> dict[str, int]:
    """Örnek bordro ve belgeleri gönderir. Var olanı atlar; sayıları döndürür."""
    bugun = bugun or date.today()
    an = datetime.now(UTC)
    istek = svc.Istek(an=an, ip=None, user_agent="app.seeds.ik_ornek (deneme verisi)")
    gonderen = await _yonetici(db)
    kisiler = await svc.alici_adaylari(db)
    sonuc = {"alici": len(kisiler), "bordro": 0, "sablon": 0, "belge_gonderimi": 0}
    if not kisiler:
        return sonuc

    # --- Bordro: bir önceki ay, henüz almamış kişilere ---
    donem = _onceki_ay(bugun)
    yil, ay = (int(p) for p in donem.split("-"))
    alanlar = set(
        (
            await db.scalars(
                select(IkBelge.user_id)
                .join(IkGonderim, IkGonderim.id == IkBelge.gonderim_id)
                .where(
                    IkGonderim.tur == "BORDRO",
                    IkGonderim.donem == donem,
                    IkBelge.durum != "GERI_ALINDI",
                )
            )
        ).all()
    )
    alicilar = []
    for k in kisiler:
        if k.id in alanlar:
            continue
        pdf = ornek_pdf(f"Ücret Bordrosu — {AYLAR[ay - 1]} {yil}", bordro_satirlari(k, donem))
        kayit = storage.yaz(pdf, mime_type="application/pdf")
        alicilar.append(
            svc.Alici(user_id=k.id, dosya=kayit, dosya_adi=f"ORNEK_bordro_{donem}_{k.id}.pdf")
        )
    if alicilar:
        await svc.gonder(
            db,
            tur="BORDRO",
            baslik=f"{ONEK} {AYLAR[ay - 1]} {yil} bordrosu",
            donem=donem,
            aciklama="Deneme verisi: tutarlar kurgusaldır.",
            son_tarih=bugun + timedelta(days=10),
            sablon_id=None,
            alicilar=alicilar,
            gonderen=gonderen,
            istek=istek,
        )
        sonuc["bordro"] = len(alicilar)

    # --- Şablonlar ve herkese gönderim ---
    for ad, tur, aciklama, satirlar in SABLONLAR:
        sablon_adi = f"{ONEK} {ad}"
        s = await db.scalar(select(IkBelgeSablonu).where(IkBelgeSablonu.ad == sablon_adi))
        if s is None:
            kayit = storage.yaz(ornek_pdf(ad, satirlar), mime_type="application/pdf")
            s = IkBelgeSablonu(
                ad=sablon_adi,
                tur=tur,
                aciklama=aciklama,
                aktif=True,
                dosya_adi=f"ORNEK_{tur.lower()}.pdf",
                storage_path=kayit.storage_path,
                mime_type=kayit.mime_type,
                size_bytes=kayit.size_bytes,
                sha256=kayit.sha256,
                created_by=gonderen.id,
                updated_by=gonderen.id,
            )
            db.add(s)
            await db.flush()
            sonuc["sablon"] += 1
        if await db.scalar(select(IkGonderim.id).where(IkGonderim.baslik == sablon_adi)):
            continue
        kayit = storage.Kayit(
            storage_path=s.storage_path,
            sha256=s.sha256,
            size_bytes=s.size_bytes,
            mime_type=s.mime_type,
        )
        await svc.gonder(
            db,
            tur=tur,
            baslik=sablon_adi,
            donem=None,
            aciklama=aciklama,
            son_tarih=bugun + timedelta(days=14),
            sablon_id=s.id,
            alicilar=[svc.Alici(user_id=k.id, dosya=kayit, dosya_adi=s.dosya_adi) for k in kisiler],
            gonderen=gonderen,
            istek=istek,
        )
        sonuc["belge_gonderimi"] += 1
    return sonuc


async def temizle(db: AsyncSession) -> dict[str, int]:
    """`[ÖRNEK]` gönderim ve şablonlarını siler (dosyalar depoda yetim kalır,
    `yetimleri_temizle` toplar). Olay tetikleyicisi yalnız bu işlemde kapanır."""
    gonderimler = list(
        (await db.scalars(select(IkGonderim.id).where(IkGonderim.baslik.startswith(ONEK)))).all()
    )
    belgeler = list(
        (await db.scalars(select(IkBelge.id).where(IkBelge.gonderim_id.in_(gonderimler)))).all()
    )
    if belgeler:
        await db.execute(
            text("ALTER TABLE ik_belge_olaylari DISABLE TRIGGER trg_ik_belge_olayi_degismez")
        )
        await db.execute(delete(IkBelgeOlayi).where(IkBelgeOlayi.belge_id.in_(belgeler)))
        await db.execute(
            text("ALTER TABLE ik_belge_olaylari ENABLE TRIGGER trg_ik_belge_olayi_degismez")
        )
        await db.execute(delete(IkBelge).where(IkBelge.id.in_(belgeler)))
    if gonderimler:
        await db.execute(delete(IkGonderim).where(IkGonderim.id.in_(gonderimler)))
    sablon = await db.execute(delete(IkBelgeSablonu).where(IkBelgeSablonu.ad.startswith(ONEK)))
    return {"gonderim": len(gonderimler), "belge": len(belgeler), "sablon": sablon.rowcount or 0}


async def main(argv: list[str] | None = None) -> int:
    from app.config import get_config

    parser = argparse.ArgumentParser(
        description="İK Bordro ve Belgeler örnek verisi (YALNIZ GELİŞTİRME)"
    )
    parser.add_argument("--temizle", action="store_true", help="[ÖRNEK] kayıtlarını sil")
    args = parser.parse_args(argv)
    if not get_config().is_dev:
        print("Yalnız ENV=dev ortamında çalışır.", file=sys.stderr)
        return 2

    async with get_session_factory()() as db:
        if args.temizle:
            s = await temizle(db)
            print(
                f"Silindi: {s['gonderim']} gönderim, {s['belge']} kişi belgesi, "
                f"{s['sablon']} şablon"
            )
        else:
            s = await yukle(db)
            print(
                f"Alıcı: {s['alici']} kişi | bordro: {s['bordro']} | yeni şablon: {s['sablon']} | "
                f"belge gönderimi: {s['belge_gonderimi']} (e-posta gönderilmedi)"
            )
        await db.commit()
    return 0


if __name__ == "__main__":
    # Windows: psycopg async varsayılan ProactorEventLoop ile çalışmaz.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
