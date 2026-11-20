"""Servis durum grupları, uç kısıtı tablosu ve tür kuralları (TS-021, E12-01/04).

Rapor, panel, liste ve uyarı aynı kümeleri kullanır; elle yazılmış ikinci
bir liste "sayı = liste" ilkesini bozardı. Bu testler kümelerin katalogla
uyumunu ve her makine geçişinin bir uca bağlı olduğunu kilitler.
"""

from app.models.teknik_servis import (
    DURUM_GRUPLARI,
    SERVIS_DURUMLARI,
    SERVIS_KATEGORILERI,
    SERVIS_TURLERI,
    durum_grubu,
)
from app.services.statemachine import SERVIS_IS_EMRI
from app.services.teknik_servis import is_emirleri


def test_acik_ve_kapali_katalogu_tam_boler() -> None:
    acik, kapali = DURUM_GRUPLARI["ACIK"], DURUM_GRUPLARI["KAPALI"]
    assert acik | kapali == frozenset(SERVIS_DURUMLARI)
    assert not acik & kapali
    for grup in DURUM_GRUPLARI.values():
        assert grup <= frozenset(SERVIS_DURUMLARI)


def test_rapor_grubu_her_durum_icin_tek() -> None:
    gruplar = {d: durum_grubu(d) for d in SERVIS_DURUMLARI}
    assert gruplar["TAMAMLANDI"] == gruplar["KAPATILDI"] == "COZULDU"
    assert gruplar["IPTAL"] == "IPTAL"
    assert {d for d, g in gruplar.items() if g == "ACIK"} == DURUM_GRUPLARI["ACIK"]


def test_uc_hedefleri_katalogda_ve_makinede() -> None:
    hedefler = set().union(*is_emirleri.UC_HEDEFLERI.values())
    assert hedefler <= set(SERVIS_DURUMLARI)
    assert hedefler <= set(SERVIS_IS_EMRI.durumlar)


def test_her_makine_gecisinin_bir_ucu_var() -> None:
    """Makinede olup hiçbir kaynağın süremediği hedef ölü geçiştir."""
    surulebilir = set().union(*is_emirleri.UC_HEDEFLERI.values())
    for kaynak, hedefler in SERVIS_IS_EMRI.gecisler.items():
        for hedef in hedefler:
            assert hedef in surulebilir, (kaynak, hedef)


def test_kapanis_hedefleri_yalniz_kendi_kaynaklarinda() -> None:
    def kaynaklar(hedef):
        return {k for k, h in is_emirleri.UC_HEDEFLERI.items() if hedef in h}

    assert kaynaklar("TAMAMLANDI") == {"sonuc", "uzaktan", "atolye", "bakim_formu"}
    assert kaynaklar("KAPATILDI") == {"kapat"}
    # yola_cikis_geri_al: yönetici YOLA_CIKILDI → PLANLANDI (KARARLAR 2026-11-04 §7.4).
    # tayin: ekip gelince iş "verildi" sayılır (kullanıcı kararı 2026-11-20).
    assert kaynaklar("PLANLANDI") == {"planla", "sayac", "bekleme", "yola_cikis_geri_al", "tayin"}
    assert "BEKLEMEDE" not in is_emirleri.UC_HEDEFLERI["genel"]


def test_tur_kurallari_tum_turleri_kapsar() -> None:
    assert set(is_emirleri.TUR_KURALLARI) == set(SERVIS_TURLERI)
    for tur, kural in is_emirleri.TUR_KURALLARI.items():
        assert kural.kategori in SERVIS_KATEGORILERI, tur
        assert is_emirleri.tur_kategorisi(tur) == kural.kategori
        assert kural.sla_olculur == (kural.kategori == "GUNLUK_SERVIS"), tur
    assert is_emirleri.tur_kategorisi("PLANSIZ_BAKIM") == "GUNLUK_SERVIS"
    assert is_emirleri.TUR_KURALLARI["PB"].tek_seri
    assert is_emirleri.TUR_KURALLARI["PB"].yalniz_sistem


def test_ad_sozlukleri_tam() -> None:
    assert set(is_emirleri.DURUM_ADLARI) == set(SERVIS_DURUMLARI)
    assert set(is_emirleri.TUR_ADLARI) == set(SERVIS_TURLERI)
    assert set(is_emirleri.KATEGORI_ADLARI) == set(SERVIS_KATEGORILERI)
