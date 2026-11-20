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
    from app.services import sirketler
    from app.services import subscriptions as abonelik_svc

    ozet = UyariOzeti()
    # Şirket ayrımı (KARARLAR 2026-11-04 §1): aşağıdaki mobilite uyarıları
    # (hat, abonelik, tahsilat, hak ediş, montaj noktası) yalnız DENGE MOBİLİTE
    # etkinken sayılır — ekranları başka şirkette 403'tür, sayı da sızıntıdır.
    # Teknik servis uyarıları kapsam.py üzerinden şirketle zaten süzülür.
    mobilite = sirketler.mobilite_acik_mi(user)

    if mobilite and user.has("hat.gor"):
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

    if mobilite and user.has("abonelik.gor"):
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

    if mobilite and user.has("tahsilat.gor"):
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

    if mobilite and user.has("hakedis.gor"):
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

    if mobilite and user.has("hesap.gor"):
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

    # --- Satış (KARARLAR 2026-11-09 S1.4, S2.3, S3.3): süresi yaklaşan ve
    # yanıt bekleyen tekliflerim, keşfi tamamlanan teklifim, onayımı bekleyen
    # iskonto. Kapsam `teklif_kapsami` ile (sayı = sızıntı).
    from app.services import satis_takip

    ozet.uyarilar += [u for u in await satis_takip.uyarilar(db, clock, user) if u.adet > 0]

    # KARARLAR 2026-11-20 §7 ve §5–6: onayımı bekleyen izin, müdüre düşen yönlendirme.
    from app.services import izin

    izin_bekleyen = await izin.bekleyen_sayisi(db, user)
    if izin_bekleyen:
        ozet.uyarilar.append(
            Uyari(
                kod="izin.onay",
                baslik="Onayımı bekleyen izin talebi",
                adet=izin_bekleyen,
                yol="/izin-talepleri?sekme=onay",
                onem="uyari",
                aciklama="24 saat içinde karar verilmezse talep bir üst yöneticiye geçer.",
            )
        )
    if user.has("servis.yonlendir") or user.has("servis.planla"):
        from app.services.teknik_servis import yonlendirme

        bekleyen = [
            y
            for y in await yonlendirme.liste(db, user, yonlendirme.Suzgec(acik=True))
            if (y["durum"] == "MUDURDE") == user.has("servis.yonlendir")
        ]
        if bekleyen:
            ozet.uyarilar.append(
                Uyari(
                    kod="servis.yonlendirme",
                    baslik="Yönlendirme bekleyen satış/kiralama talebi"
                    if user.has("servis.yonlendir")
                    else "Bana yönlendirilen satış/kiralama işi",
                    adet=len(bekleyen),
                    yol="/yonlendirmeler",
                    onem="uyari",
                )
            )

    return ozet
