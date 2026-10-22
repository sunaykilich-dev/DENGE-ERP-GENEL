# ruff: noqa: I001  (import sırası kanca çağrı sırasıdır, alfabetik sıralanmaz)
"""Teknik servis servis katmanı (alt paket; emsal `services/imports/`).

Mimari (plan §1.1, 00 §6.2): teknik servis canlının KATMAN bazlı yapısına
gömülüdür — modeller `models/`, iş kuralı burada, uçlar `api/`. Bu paket
`work_orders` / `work_order_items` / `settlements` tablolarına HİÇBİR ŞEY
YAZMAZ (KD-01).

**İmport sırası SABİTTİR ve anlamlıdır:** modüller kanca kayıtlarını
(`kancalar.kaydet`) dosyalarının en altında yapar; kancalar kayıt sırasıyla
çağrılır. Bu dosya kanca kaydeden modülleri her ortamda aynı sırayla yükler
ki "SLA kaydı atölyeden önce mi" gibi sıra farkları ortaya çıkmasın. Yeni
modül listenin SONUNA eklenir (sıra değişikliği şema paketinin işidir).
Ortak yardımcılar (`kapsam`, `ana_veri`, `personel`, `ek_kapsam`,
`uyarilar`) kanca kaydetmez; kullanıldıkları yerde import edilir.
"""

from app.services.teknik_servis import kancalar  # noqa: F401  (önce kayıt defteri)

# --- Dalga 1: servis işi çekirdeği (D1-B / D1-C) -------------------------------
from app.services.teknik_servis import is_emirleri  # noqa: F401
from app.services.teknik_servis import gecmis  # noqa: F401
from app.services.teknik_servis import bekletme  # noqa: F401
from app.services.teknik_servis import sonuc  # noqa: F401
from app.services.teknik_servis import atama  # noqa: F401
from app.services.teknik_servis import onay  # noqa: F401
from app.services.teknik_servis import panel  # noqa: F401

# --- Dalga 1: planlama (D1-D) ---------------------------------------------------
from app.services.teknik_servis import planlama  # noqa: F401
from app.services.teknik_servis import takvim  # noqa: F401
from app.services.teknik_servis import cakisma  # noqa: F401

# --- Dalga 1: ekipman (D1-E) ----------------------------------------------------
from app.services.teknik_servis import ekipman  # noqa: F401

# --- Dalga 1: planlı bakım (D1-F) ------------------------------------------------
from app.services.teknik_servis import bakim  # noqa: F401
from app.services.teknik_servis import bakim_sablonlari  # noqa: F401
from app.services.teknik_servis import bakim_uretim  # noqa: F401
from app.services.teknik_servis import bakim_formu  # noqa: F401

# --- Dalga 1: saha / zaman ve mobil (D1-G) ---------------------------------------
from app.services.teknik_servis import zaman  # noqa: F401
from app.services.teknik_servis import mobil  # noqa: F401

# --- Dalga 2 (D2-S sıraladı; plan §1.8 çağrı sırası) ------------------------------
# durum_degisti: bekletme → bakim_formu → sla → parca → kiralama
# is_olusturuldu: sla → tekrar_ariza ; durum_dogrula: ... → atolye
# SLA / operasyon (D2-G)
from app.services.teknik_servis import sla  # noqa: F401
from app.services.teknik_servis import sla_takvim  # noqa: F401
from app.services.teknik_servis import tekrar_ariza  # noqa: F401
from app.services.teknik_servis import operasyon  # noqa: F401
from app.services.teknik_servis import uyari_uretimi  # noqa: F401

# Atölye (D2-B)
from app.services.teknik_servis import atolye  # noqa: F401
from app.services.teknik_servis import atolye_rapor  # noqa: F401

# Yedek parça (D2-D) — kiralamadan ÖNCE (durum_degisti sırası)
from app.services.teknik_servis import parca  # noqa: F401

# Kiralama (D2-C)
from app.services.teknik_servis import kiralama  # noqa: F401
from app.services.teknik_servis import kiralama_tahsis  # noqa: F401
from app.services.teknik_servis import kiralik_envanter  # noqa: F401
from app.services.teknik_servis import kiralama_raporlar  # noqa: F401

# Teklif / maliyet (D2-E)
from app.services.teknik_servis import maliyet  # noqa: F401

# Eğitim (D2-F)
from app.services.teknik_servis import egitim  # noqa: F401
from app.services.teknik_servis import egitim_gozlem  # noqa: F401
from app.services.teknik_servis import egitim_yetkinlik  # noqa: F401
from app.services.teknik_servis import egitim_rapor  # noqa: F401

# Göç-1 / veri kalitesi (D2-I)
from app.services.teknik_servis import ad_esleme  # noqa: F401
from app.services.teknik_servis import veri_kalitesi  # noqa: F401

# --- Dalga 3 (D3-S sıraladı) ------------------------------------------------------------
# Rapor/KPI kayıt defteri önce (D3-A); diğer paketlerin KPI kayıtları
# (bakım, eğitim — D3-E) kendi modüllerinden bu defterin arayüzüyle yapılır.
from app.services.teknik_servis import rapor_tanimlari  # noqa: F401
from app.services.teknik_servis import rapor_motoru  # noqa: F401
from app.services.teknik_servis import rapor_hesap  # noqa: F401
from app.services.teknik_servis import rapor_excel  # noqa: F401
from app.services.teknik_servis import rapor_kalite  # noqa: F401

# E-posta bildirimi (D3-F)
from app.services.teknik_servis import eposta  # noqa: F401

# Bakım/fatura devri raporları ve kiralık sayım (D3-E / D3-D; bütünleştirme):
# bakım KPI'ları rapor motoruna API yüklenmeden de (worker, servis bağlamı) kaydolsun.
from app.services.teknik_servis import bakim_raporlari  # noqa: F401
from app.services.teknik_servis import fatura_devri  # noqa: F401
from app.services.teknik_servis import kiralik_sayim  # noqa: F401

# --- Dalga 4+ (D4-S buraya ekler) ---------------------------------------------------
