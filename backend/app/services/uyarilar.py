"""Uyarı merkezi — zamana bağlı uyarıların tek toplayıcısı.

**Neden var:** worker gecede bir "taahhüdü bitecek hat=12" diye log'a yazıyordu
ve orada kalıyordu. Uyarının değeri BİRİNE ULAŞMASINDA: hat taahhüdü bitince
aynı hattın aylık maliyeti 14,43 ₺'den 131,16 ₺'ye çıkıyor (plan §2 #15) ve
bunu ayın sonunda faturadan öğrenmek pahalı. Ekranı kimse açmazsa uyarı hiç
görülmüyordu.

**Saklanmaz, HESAPLANIR.** Ayrı bir `notifications` tablosu, "okundu mu",
"hâlâ geçerli mi" ve "iki kez üretildi mi" sorularını beraberinde getirirdi.
Uyarıların hepsi zaten tarihli veriden türüyor; kaynak değişince uyarı
kendiliğinden kayboluyor. Sayılar küçük (onlarca), sorgular zaten var.

**İZNE TABİ.** Kullanıcı göremeyeceği bir modülün uyarısını da görmez;
aksi halde uyarı sayısı bir yetki sızıntısı olurdu (kaç abonelik yenileniyor,
kaç hesap ödemede gecikti).
"""

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import Account, InstallationPartner, User, WorkOrderItem


@dataclass
class Uyari:
    kod: str
    baslik: str
    adet: int
    yol: str  # arayüzde gidilecek ekran
    onem: str = "bilgi"  # bilgi | uyari | kritik
    aciklama: str = ""


@dataclass
class UyariOzeti:
    uyarilar: list[Uyari] = field(default_factory=list)

    @property
    def toplam(self) -> int:
        return sum(u.adet for u in self.uyarilar)


async def topla(db: AsyncSession, clock: Clock, user: User) -> UyariOzeti:
    """Kullanıcının GÖREBİLECEĞİ uyarıları toplar."""
    from app.services import payments as tahsilat_svc
    from app.services import sims as hat_svc
    from app.services import subscriptions as abonelik_svc

    ozet = UyariOzeti()

    if user.has("hat.gor"):
        taahhut = await hat_svc.taahhudu_bitenler(db, clock)
        if taahhut:
            ozet.uyarilar.append(
                Uyari(
                    kod="hat.taahhut",
                    baslik="Taahhüdü bitecek hat",
                    adet=len(taahhut),
                    yol="/hatlar?taahhut=1",
                    onem="kritik",
                    aciklama="Taahhüt bitince aynı hattın aylık maliyeti kat kat artar.",
                )
            )
        # ICCID'den kurulan eşleşmelerin başlangıcı kaynakta yoktu. Uydurulmuş
        # tarih yazmak yerine NULL bırakıldı; ekip gerçek tarihi girene kadar
        # bu sayı görünür kalsın, yoksa "eksik" olduğu unutulur.
        from app.models import SimDeviceHistory

        tarihsiz = await db.scalar(
            select(func.count())
            .select_from(SimDeviceHistory)
            .where(SimDeviceHistory.valid_from.is_(None))
        )
        if tarihsiz:
            ozet.uyarilar.append(
                Uyari(
                    kod="hat.tarihsiz_eslesme",
                    baslik="Başlangıcı bilinmeyen cihaz–hat eşleşmesi",
                    adet=int(tarihsiz),
                    yol="/hatlar",
                    onem="bilgi",
                    aciklama="Eşleşme biliniyor, ne zaman başladığı bilinmiyor.",
                )
            )

        kota = await hat_svc.kota_uyarilari(db)
        if kota:
            ozet.uyarilar.append(
                Uyari(
                    kod="hat.kota",
                    baslik="Kota eşiğini aşan hat",
                    adet=len(kota),
                    yol="/hatlar",
                    onem="uyari",
                )
            )

    if user.has("abonelik.gor"):
        yenilenecek = await abonelik_svc.yenilenecekler(db, clock)
        if yenilenecek:
            ozet.uyarilar.append(
                Uyari(
                    kod="abonelik.yenileme",
                    baslik="Yenilenecek abonelik",
                    adet=len(yenilenecek),
                    yol="/abonelikler",
                    onem="uyari",
                )
            )

    if user.has("tahsilat.gor"):
        geciken = await tahsilat_svc.gecikenler(db, clock)
        if geciken:
            ozet.uyarilar.append(
                Uyari(
                    kod="tahsilat.gecikme",
                    baslik="Ödemesi geciken hesap",
                    adet=len(geciken),
                    yol="/tahsilat",
                    onem="uyari",
                )
            )

    if user.has("hakedis.gor"):
        # Karar verilmeyen kalem döküme HİÇ girmez; montaj noktası parasını
        # alamaz ve kimse fark etmez.
        bekleyen = await db.scalar(
            select(func.count())
            .select_from(WorkOrderItem)
            .where(WorkOrderItem.payability == "KARAR_BEKLIYOR")
        )
        if bekleyen:
            ozet.uyarilar.append(
                Uyari(
                    kod="hakedis.karar",
                    baslik="Karar bekleyen iş emri kalemi",
                    adet=int(bekleyen),
                    yol="/hakedis",
                    onem="kritik",
                    aciklama="Ödenecek mi işaretlenmeden hak ediş dökümüne girmez.",
                )
            )

        # Belge tipi belirsizse stopaj/damga hesaplanamaz ve döküm ONAYLANAMAZ.
        belirsiz = await db.scalar(
            select(func.count())
            .select_from(InstallationPartner)
            .where(InstallationPartner.document_type == "BELIRSIZ")
        )
        if belirsiz:
            ozet.uyarilar.append(
                Uyari(
                    kod="hakedis.belge_tipi",
                    baslik="Belge tipi belirlenmemiş montaj noktası",
                    adet=int(belirsiz),
                    yol="/hesaplar?rol=MONTAJ_NOKTASI",
                    onem="kritik",
                    aciklama="Belge tipi seçilmeden hak ediş dökümü onaylanamaz.",
                )
            )

    if user.has("hesap.gor"):
        # E-postası/IBAN'ı olmayan montaj noktasına döküm gönderilemez ve
        # ödeme listesi çıkarılamaz (plan §8 madde 2).
        eksikli = 0
        hesaplar = (
            await db.scalars(
                select(Account).where(
                    Account.is_deleted.is_(False), Account.is_montaj_noktasi.is_(True)
                )
            )
        ).all()
        from app.services.accounts import eksik_alanlar

        eksikli = sum(1 for h in hesaplar if eksik_alanlar(h))
        if eksikli:
            ozet.uyarilar.append(
                Uyari(
                    kod="hesap.eksik",
                    baslik="Eksik bilgisi olan montaj noktası",
                    adet=eksikli,
                    yol="/hesaplar?eksik=1",
                    onem="uyari",
                    aciklama="E-posta ya da IBAN yoksa hak ediş dökümü gönderilemez.",
                )
            )

    # --- Teknik servis (plan §1.11) — TEK blok. Modül uyarıları kendi
    # dosyalarından `services/teknik_servis/uyarilar.py` kayıt defterine
    # kaydolur; her biri kendi iznini ve birim kapsamını uygular (sayı =
    # sızıntı). Mobilite uyarıları yukarıda olduğu gibi kalır.
    from app.services.teknik_servis import uyarilar as ts_uyarilar

    ozet.uyarilar += await ts_uyarilar.topla(db, user, clock)

    return ozet
