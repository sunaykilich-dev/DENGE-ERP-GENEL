"""İçe aktarma profilleri kaydı.

Yeni bir veri türü eklemek = bir profil dosyası yazıp buraya eklemek.
Arayüz, şablon indirme, karantina raporu ve denetim izi profil listesinden
beslendiği için hiçbirine dokunmak gerekmez.
"""

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
