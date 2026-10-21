"""Parametrik durum makinesi.

ERP'de yedi ayrı durum akışı var (cihaz, iş emri, teklif, sipariş, hak ediş,
abonelik, RMA). Hepsi aynı sınıfı kullanır; kural tablosu tek yerde durur.

DİSİPLİN: durum alanına hiçbir yerde DOĞRUDAN atama yapılmaz. Her geçiş
`gecis()` üzerinden gider ki kural kontrolü, geçmiş kaydı ve denetim izi
atlanamasın. Bu kuralı bozan bir satır, "HURDA'dan AKTIF'e" gibi imkânsız
geçişleri sessizce mümkün kılar.
"""

from dataclasses import dataclass


class IzinsizGecis(Exception):
    """Kurallara aykırı durum geçişi."""

    def __init__(self, makine: str, mevcut: str, hedef: str, izinliler: frozenset[str]) -> None:
        izin_metni = ", ".join(sorted(izinliler)) if izinliler else "yok (terminal durum)"
        super().__init__(
            f"{makine}: '{mevcut}' durumundan '{hedef}' durumuna geçiş kurallara aykırı. "
            f"İzin verilenler: {izin_metni}"
        )
        self.makine, self.mevcut, self.hedef = makine, mevcut, hedef


@dataclass(frozen=True)
class StateMachine:
    ad: str
    gecisler: dict[str, frozenset[str]]
    # Kaydın DOĞDUĞU durum(lar). Hiçbir geçişin hedefi olmadıkları için
    # "ulaşılamayan durum" meta-testi bunları hariç tutar; listeyi teste
    # gömmek, yeni bir makine eklendiğinde testi yalancı kırmaya iterdi.
    baslangiclar: frozenset[str] = frozenset()

    @property
    def durumlar(self) -> frozenset[str]:
        hepsi = set(self.gecisler)
        for hedefler in self.gecisler.values():
            hepsi |= hedefler
        return frozenset(hepsi)

    @property
    def terminaller(self) -> frozenset[str]:
        return frozenset(d for d, h in self.gecisler.items() if not h)

    def izinli_mi(self, mevcut: str, hedef: str) -> bool:
        return hedef in self.gecisler.get(mevcut, frozenset())

    def dogrula(self, mevcut: str, hedef: str) -> None:
        if mevcut == hedef:
            raise IzinsizGecis(self.ad, mevcut, hedef, self.gecisler.get(mevcut, frozenset()))
        if not self.izinli_mi(mevcut, hedef):
            raise IzinsizGecis(self.ad, mevcut, hedef, self.gecisler.get(mevcut, frozenset()))

    def sonraki(self, mevcut: str) -> frozenset[str]:
        """Arayüze yalnız geçerli seçenekleri sunmak için (prototipin iyi
        kararı: kullanıcıya imkânsız seçenek gösterilmez)."""
        return self.gecisler.get(mevcut, frozenset())

    def yol(self, mevcut: str, hedef: str) -> tuple[str, ...]:
        """`mevcut`tan `hedef`e EN KISA geçiş zinciri; yoksa boş.

        İçe aktarma için var: sahada takılı bir cihaz dosyadan gelirken
        STOKTA görünüyorsa AKTIF'e doğrudan geçemez. Zinciri burada
        üretip adım adım yürümek, durum geçmişini dürüst bırakır —
        alana doğrudan atama yapmak geçmişi büsbütün uydururdu.
        """
        if mevcut == hedef:
            return ()
        kuyruk: list[tuple[str, tuple[str, ...]]] = [(mevcut, ())]
        gorulen = {mevcut}
        while kuyruk:
            durum, izlek = kuyruk.pop(0)
            for sonraki in sorted(self.gecisler.get(durum, frozenset())):
                if sonraki in gorulen:
                    continue
                yeni_izlek = (*izlek, sonraki)
                if sonraki == hedef:
                    return yeni_izlek
                gorulen.add(sonraki)
                kuyruk.append((sonraki, yeni_izlek))
        return ()


def _m(**kwargs: tuple[str, ...]) -> dict[str, frozenset[str]]:
    return {durum: frozenset(hedefler) for durum, hedefler in kwargs.items()}


# --- Cihaz yaşam döngüsü (brief §4.2) ---------------------------------------
# "Kurala aykırı geçişler engellenir (örn. HURDA → AKTIF olmaz)."
CIHAZ = StateMachine(
    ad="Cihaz",
    baslangiclar=frozenset({"ITHALATTA", "STOKTA"}),
    gecisler=_m(
        ITHALATTA=("STOKTA", "KAYIP_CALINTI"),
        STOKTA=("TEST_EDILDI", "REZERVE", "SEVK_EDILDI", "ARIZALI", "KAYIP_CALINTI", "HURDA"),
        TEST_EDILDI=("STOKTA", "REZERVE", "SEVK_EDILDI", "ARIZALI", "KAYIP_CALINTI"),
        REZERVE=("STOKTA", "SEVK_EDILDI", "KAYIP_CALINTI"),
        SEVK_EDILDI=("MONTAJ_BEKLIYOR", "AKTIF", "STOKTA", "KAYIP_CALINTI"),
        MONTAJ_BEKLIYOR=("AKTIF", "SEVK_EDILDI", "ARIZALI", "KAYIP_CALINTI"),
        AKTIF=("SOKULDU", "ARIZALI", "KAYIP_CALINTI"),
        SOKULDU=("TEST_EDILDI", "ARIZALI", "YENIDEN_STOKTA", "AKTIF", "HURDA"),
        ARIZALI=("RMA", "HURDA"),
        RMA=("TAMIRDE", "HURDA"),
        TAMIRDE=("YENIDEN_STOKTA", "HURDA"),
        YENIDEN_STOKTA=("STOKTA", "REZERVE", "SEVK_EDILDI"),
        HURDA=(),
        KAYIP_CALINTI=("STOKTA",),  # cihaz bulunursa
    ),
)

# --- Hat (brief §4.4) --------------------------------------------------------
HAT = StateMachine(
    ad="Hat",
    baslangiclar=frozenset({"STOKTA"}),
    gecisler=_m(
        STOKTA=("TEST", "AKTIF", "IPTAL"),
        TEST=("AKTIF", "STOKTA", "IPTAL"),
        AKTIF=("ASKIDA", "IPTAL"),
        ASKIDA=("AKTIF", "IPTAL"),
        IPTAL=(),
    ),
)

# --- Sipariş (brief §4.10) ---------------------------------------------------
# REZERVE ayrı bir durum: "IMEI'ler ayrıldı ama daha sevk edilmedi" aşaması
# depo için görünür olmalı. ONAYLANDI'ya dönüş rezervasyonun iptalidir.
SIPARIS = StateMachine(
    ad="Sipariş",
    baslangiclar=frozenset({"TASLAK"}),
    gecisler=_m(
        TASLAK=("ONAYLANDI", "IPTAL"),
        ONAYLANDI=("REZERVE", "KISMI_SEVK", "SEVK_EDILDI", "IPTAL"),
        REZERVE=("ONAYLANDI", "KISMI_SEVK", "SEVK_EDILDI", "IPTAL"),
        KISMI_SEVK=("SEVK_EDILDI", "IPTAL"),
        SEVK_EDILDI=("TAMAMLANDI",),
        TAMAMLANDI=(),
        IPTAL=(),
    ),
)

# --- Abonelik (brief §4.11) --------------------------------------------------
# SONA_ERDI terminal DEĞİL: geri dönen müşteri (win-back) churn analizinde
# ayrı bir olaydır ve yeni sözleşme açmak geçmişi koparırdı.
ABONELIK = StateMachine(
    ad="Abonelik",
    baslangiclar=frozenset({"TASLAK"}),
    gecisler=_m(
        TASLAK=("AKTIF", "IPTAL"),
        AKTIF=("ASKIDA", "IPTAL", "SONA_ERDI"),
        ASKIDA=("AKTIF", "IPTAL", "SONA_ERDI"),
        SONA_ERDI=("AKTIF",),
        IPTAL=(),
    ),
)

# --- RMA / teknik servis (brief §4.12) ---------------------------------------
# COZULDU'dan geri dönüş var: kapanmadan önce çözümün yanlış olduğu
# anlaşılabilir. KAPANDI terminaldir — kapanan kayıt yeniden açılmaz,
# yeni arıza yeni kayıttır.
RMA = StateMachine(
    ad="RMA",
    baslangiclar=frozenset({"ACIK"}),
    gecisler=_m(
        ACIK=("INCELEMEDE", "IPTAL"),
        INCELEMEDE=("TAMIRDE", "TEDARIKCIDE", "COZULDU", "IPTAL"),
        TAMIRDE=("COZULDU", "TEDARIKCIDE", "IPTAL"),
        TEDARIKCIDE=("TAMIRDE", "COZULDU", "IPTAL"),
        COZULDU=("KAPANDI", "INCELEMEDE"),
        KAPANDI=(),
        IPTAL=(),
    ),
)

# --- Satın alma siparişi (brief §4.13) ---------------------------------------
SATINALMA = StateMachine(
    ad="Satın Alma",
    baslangiclar=frozenset({"TASLAK"}),
    gecisler=_m(
        TASLAK=("SIPARIS_VERILDI", "IPTAL"),
        SIPARIS_VERILDI=("KISMI_TESLIM", "TESLIM_ALINDI", "IPTAL"),
        KISMI_TESLIM=("TESLIM_ALINDI", "IPTAL"),
        TESLIM_ALINDI=(),
        IPTAL=(),
    ),
)

# --- Teknik servis işi (plan §1.7) -------------------------------------------
# Mobilite iş emrinin aksine (kayıt doğrudan TAMAMLANDI doğar) servis işi
# gerçek bir yaşam döngüsüdür. KARGODA/TEST_KONTROL YOK: atölye ayrıntısı
# atölye kaydındadır (KD-13). PB ve kiralama kurulum/toplama işleri
# PLANLAMADA doğar. Makine "hangi geçiş var"ı söyler; "hangi uç hangi
# hedefe gidebilir" kısıtı (`UC_HEDEFLERI`) ve kancalar
# `services/teknik_servis/is_emirleri.durum_degistir`'dedir. IPTAL terminal:
# yeni arıza yeni iştir (bağlı iş ilişkisiyle).
SERVIS_IS_EMRI = StateMachine(
    ad="Servis İşi",
    baslangiclar=frozenset({"MUSTERI_TALEBI", "PLANLAMADA"}),
    gecisler=_m(
        MUSTERI_TALEBI=(
            "PLANLAMADA",
            "PLANLANDI",
            "ISLEMDE",
            "ATOLYEDE",
            "BEKLEMEDE",
            "TAMAMLANDI",
            "IPTAL",
        ),
        PLANLAMADA=("PLANLANDI", "ISLEMDE", "ATOLYEDE", "BEKLEMEDE", "TAMAMLANDI", "IPTAL"),
        PLANLANDI=(
            "PLANLAMADA",  # plan geri alma
            "YOLA_CIKILDI",
            "SAHADA",
            "ISLEMDE",
            "ATOLYEDE",
            "BEKLEMEDE",
            "TAMAMLANDI",
            "IPTAL",
        ),
        # PLANLANDI'ya dönüş: yanlış "Yola Çıktım" basışının geri alınması.
        YOLA_CIKILDI=("PLANLANDI", "SAHADA", "BEKLEMEDE", "TAMAMLANDI"),
        SAHADA=("ISLEMDE", "ATOLYEDE", "BEKLEMEDE", "TAMAMLANDI"),
        ISLEMDE=("SAHADA", "ATOLYEDE", "BEKLEMEDE", "TAMAMLANDI"),
        ATOLYEDE=("BEKLEMEDE", "TAMAMLANDI", "IPTAL"),
        # Beklemeden çıkış yalnız `beklemeyi_bitir` ile önceki duruma döner.
        BEKLEMEDE=(
            "MUSTERI_TALEBI",
            "PLANLAMADA",
            "PLANLANDI",
            "SAHADA",
            "ISLEMDE",
            "ATOLYEDE",
            "TEKRAR_ACILDI",
            "IPTAL",
        ),
        TAMAMLANDI=("KAPATILDI", "TEKRAR_ACILDI"),
        KAPATILDI=("TEKRAR_ACILDI",),
        TEKRAR_ACILDI=(
            "PLANLAMADA",
            "PLANLANDI",
            "SAHADA",
            "ISLEMDE",
            "ATOLYEDE",
            "BEKLEMEDE",
            "TAMAMLANDI",
            "IPTAL",
        ),
        IPTAL=(),
    ),
)

# --- Servis ekipmanı yaşam döngüsü (E03-09) ------------------------------------
# "Serviste" bir durum DEĞİL (açık arıza işinden hesaplanır). HURDA terminal
# değil: yanlış hurdaya ayırma gerekçeyle geri alınabilir (denetim M03-04).
SERVIS_EKIPMANI = StateMachine(
    ad="Servis Ekipmanı",
    baslangiclar=frozenset({"BILINMIYOR", "KURULUM_BEKLIYOR", "KURULU"}),
    gecisler=_m(
        BILINMIYOR=("KURULUM_BEKLIYOR", "KURULU", "DEVRE_DISI", "HURDA"),
        KURULUM_BEKLIYOR=("KURULU", "DEVRE_DISI", "HURDA"),
        KURULU=("DEVRE_DISI", "KURULUM_BEKLIYOR"),
        DEVRE_DISI=("KURULU", "HURDA"),
        HURDA=("DEVRE_DISI",),
    ),
)

# --- Bakım sözleşmesi (E04) ------------------------------------------------------
# "Süresi doldu" saklanmaz (valid_to'dan hesaplanır); PASIF geri açılabilir.
BAKIM_SOZLESMESI = StateMachine(
    ad="Bakım Sözleşmesi",
    baslangiclar=frozenset({"TASLAK", "TEYIT_BEKLIYOR"}),
    gecisler=_m(
        TASLAK=("AKTIF", "PASIF"),
        TEYIT_BEKLIYOR=("AKTIF", "PASIF"),
        AKTIF=("PASIF",),
        PASIF=("AKTIF",),
    ),
)

MAKINELER = {
    "cihaz": CIHAZ,
    "hat": HAT,
    "siparis": SIPARIS,
    "abonelik": ABONELIK,
    "rma": RMA,
    "satinalma": SATINALMA,
    "servis_is_emri": SERVIS_IS_EMRI,
    "servis_ekipmani": SERVIS_EKIPMANI,
    "bakim_sozlesmesi": BAKIM_SOZLESMESI,
}
