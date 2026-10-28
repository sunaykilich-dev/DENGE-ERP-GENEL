"""Rol bazlı erişim yeri kısıtı (G3.8, KARARLAR 2026-10-28 §7 Faz A/8).

"Saha her yerden, muhasebe yalnız ofisten": `roles.yalniz_ofis` işaretli
roldeki kullanıcı yalnız `ofis_ag_listesi` ayarındaki ağlardan giriş yapar ve
istek atar. Kontrol iki yerde: girişte (`api/auth.login`, oturum AÇILMAZ) ve
her kimlikli istekte (`api/deps.current_user`; ofiste açılıp dışarı taşınan
dizüstünün oturumu da dışarıda çalışmaz).

**İstemci IP'si:** `api/deps.client_ip` = `request.client.host`. Ters vekil
arkasındaki gerçek adresi uvicorn `--proxy-headers --forwarded-allow-ips`
ile, YALNIZ güvenilen vekilden gelen başlıkla çözer (docker-compose.yml).
Uygulama X-Forwarded-For'u kendisi OKUMAZ: istemcinin yazdığı başlığa
güvenmek kısıtı tek satırla aşılabilir kılardı.

**Fail-closed:** liste doluyken adres çözülemezse (boş/bozuk) kullanıcı
ofis dışında sayılır. Liste BOŞSA kısıt yoktur (kurulum günü, ağ girilmeden
muhasebe kilitlenmesin).
"""

import ipaddress

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.services import settings as ayar_svc

KOD = "OFIS_DISI_ERISIM"
MESAJ = (
    "Rolünüz yalnız ofis ağından kullanılabilir. Ofis dışından giriş ve işlem "
    "yapılamaz; ofis ağına bağlanıp tekrar deneyin."
)


def ag_icinde_mi(ip: str | None, aglar: list[str]) -> bool:
    """IP verilen ağlardan birinde mi. IPv4'e eşlenmiş IPv6 (::ffff:a.b.c.d) açılır."""
    if not ip:
        return False
    try:
        adres = ipaddress.ip_address(ip.strip())
    except ValueError:
        return False
    if isinstance(adres, ipaddress.IPv6Address) and adres.ipv4_mapped is not None:
        adres = adres.ipv4_mapped
    for ag in aglar:
        try:
            if adres in ipaddress.ip_network(ag, strict=False):
                return True
        except ValueError:
            continue
    return False


async def ofis_disinda_mi(db: AsyncSession, user: User, ip: str | None) -> bool:
    """Kullanıcı rolü ofise bağlıysa ve IP ofis ağlarında değilse True."""
    if not getattr(user.role, "yalniz_ofis", False):
        return False
    aglar = await ayar_svc.get(db, "ofis_ag_listesi") or []
    if not aglar:
        return False
    return not ag_icinde_mi(ip, list(aglar))
