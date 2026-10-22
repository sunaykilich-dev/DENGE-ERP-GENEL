"""İçe aktarma profilleri kaydı.

Yeni bir veri türü eklemek = bir profil dosyası yazıp buraya eklemek.
Arayüz, şablon indirme, karantina raporu ve denetim izi profil listesinden
beslendiği için hiçbirine dokunmak gerekmez.

**Teknik servis profilleri (plan §1.11):** listenin SONUNA eklenir; mobilite
profillerinin sırası ve izinleri değişmez. Paralel paketlerin profil
dosyaları bu dosyayı düzenlemeden kaydolsun diye `_EK_PROFIL_MODULLERI`
sözleşmesi kullanılır: modül `PROFIL: Profil` ve `PROFIL_IZNI: str`
tanımlar; dosya mevcutsa sırasıyla yüklenir (yoksa atlanır, import hatası
GİZLENMEZ).
"""

import importlib
import importlib.util

from app.services.imports.abonelik import AbonelikProfili
from app.services.imports.arac import AracProfili
from app.services.imports.cekirdek import (
    DosyaHatasi,
    Profil,
    SatirSonucu,
    Sutun,
    oku,
    sablon_xlsx,
)
from app.services.imports.cihaz import CihazProfili
from app.services.imports.eslesme import (
    CihazAracProfili,
    CihazHatProfili,
    CihazZimmetProfili,
)
from app.services.imports.hat import HatProfili
from app.services.imports.hesap import HesapProfili
from app.services.imports.tarife import TarifeProfili

# Sıra arayüzdeki sırayı belirler ve aynı zamanda YÜKLEME SIRASIDIR:
# önce varlıklar (hesap → cihaz → hat → araç), sonra aralarındaki tarihli
# eşleştirmeler. Eşleştirme profilleri karşı tarafı bulamazsa satırı
# reddeder, bu yüzden sıra ekrana da bu şekilde yansır.
PROFILLER: dict[str, Profil] = {
    p.kod: p
    for p in (
        HesapProfili(),
        CihazProfili(),
        HatProfili(),
        AracProfili(),
        CihazHatProfili(),
        CihazAracProfili(),
        CihazZimmetProfili(),
        TarifeProfili(),
        AbonelikProfili(),
    )
}

# Profil hangi izni ister — içe aktarma, ilgili modülün YAZMA iznine tabidir.
# Ayrı bir "içe aktarma" izni, cihaz yazamayan birinin Excel'den cihaz
# açabilmesi demekti.
PROFIL_IZINLERI: dict[str, str] = {
    "hesap": "hesap.yaz",
    "cihaz": "cihaz.yaz",
    "hat": "hat.yaz",
    "arac": "arac.yaz",
    # Eşleştirmeler ilgili varlığın yazma iznine tabi: hat eşleştirmesi
    # hat.yaz, montaj isemri.yaz, zimmet cihaz.transfer ister.
    "cihaz_hat": "hat.yaz",
    "cihaz_arac": "isemri.yaz",
    "cihaz_zimmet": "cihaz.transfer",
    "tarife": "hakedis.yaz",
    "abonelik": "abonelik.yaz",
}

# Teknik servis profil modülleri — sıra = arayüz ve göç yükleme sırası (plan
# §5.3: önce personel ve ad eşleme, sonra müşteri eşleştirme, kütük ...).
# Dalga 2 göç profilleri (D2-I) bu listenin sonuna eklenir; sıra plan §5.3
# adım 4'ün zorunlu karar sırasıdır: ad eşleme → müşteri eşleştirme → bakım
# sözleşmesi → servis işi karantinası. Yedek parça açılış stoğu (D2-D,
# TS-134) talep üzerine en sona eklendi.
_EK_PROFIL_MODULLERI = (
    "app.services.imports.personel",
    "app.services.imports.ad_esleme",
    "app.services.imports.musteri_eslestirme",
    "app.services.imports.bakim_sozlesme",
    "app.services.imports.servis_isleri",
    "app.services.imports.parca_acilis",
    # Dalga 3 Göç-2 (D3-G, TS-205): kiralık envanter göç profili.
    "app.services.imports.kiralama_goc",
)


def _ek_profilleri_yukle() -> None:
    for modul_adi in _EK_PROFIL_MODULLERI:
        if importlib.util.find_spec(modul_adi) is None:
            continue
        modul = importlib.import_module(modul_adi)
        profil: Profil = modul.PROFIL
        if profil.kod in PROFILLER:
            raise ValueError(f"İçe aktarma profili iki kez tanımlı: {profil.kod}")
        PROFILLER[profil.kod] = profil
        PROFIL_IZINLERI[profil.kod] = modul.PROFIL_IZNI


_ek_profilleri_yukle()

__all__ = [
    "PROFILLER",
    "PROFIL_IZINLERI",
    "DosyaHatasi",
    "Profil",
    "SatirSonucu",
    "Sutun",
    "oku",
    "sablon_xlsx",
]
