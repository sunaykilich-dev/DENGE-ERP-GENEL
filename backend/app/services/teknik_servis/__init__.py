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

# --- Dalga 2+ (D2-S buraya ekler: sla, atolye, kiralama, parca, ...) -------------
