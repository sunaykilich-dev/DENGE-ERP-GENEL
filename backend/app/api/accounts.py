"""Hesaplar: müşteri, bayi, montaj noktası, tedarikçi."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import (
    TOPLAM_BASLIGI,
    ClockDep,
    DbDep,
    client_ip,
    require_permission,
    sayfala,
    scope_filter,
)
from app.models import Account, InstallationPartner, User
from app.schemas.accounts import HesapIn, HesapOut, HesapPatch, MukerrerAday
from app.services import accounts as svc
from app.services import audit
from app.services.normalize import normalize_msisdn
from app.services.teknik_servis import ana_veri

router = APIRouter(prefix="/api/hesaplar", tags=["hesaplar"])

Okuyucu = Annotated[User, Depends(require_permission("hesap.gor"))]
Yazici = Annotated[User, Depends(require_permission("hesap.yaz"))]
# Hızlı açılan müşteriyi doğrulamak birleştirme yetkisidir (E14 K7): doğrulayan
# kişi aynı zamanda "bu kayıt mükerrer mi" sorusunu cevaplayan kişidir.
Dogrulayici = Annotated[User, Depends(require_permission("hesap.gor", "hesap.birlestir"))]

# Gövdede gelen ama ORM'e GİTMEMESİ gereken alanlar. `Account(**veri)` bilinmeyen
# anahtarda TypeError (500) verirdi; PATCH döngüsü ise sessizce setattr ederdi.
_ORM_DISI = {"partner", "vkn_cakisma_onayi", "vkn_cakisma_gerekce"}


async def _vkn_kontrolu(
    db,
    user: User,
    tax_no: str | None,
    *,
    haric_id: int | None,
    onay: bool,
    gerekce: str | None,
) -> list[Account]:
    """Aynı VKN'li başka aktif hesap varsa 409; onay + gerekçe ile geçilir.

    Tekil indeks yok (aynı VKN'li şube/bayi çiftleri meşru, E14 K6); kontrol
    yalnız VKN YENİ girildiğinde ya da DEĞİŞTİĞİNDE çağrılır. Ön yüz düzenlemede
    formun tamamını gönderiyor: her PATCH'te kontrol etmek, aynı VKN'li çiftte
    telefon değiştirmeyi bile onaya bağlardı (E14 B1).

    409 gövdesi kapsam dışı hesabın unvanını göstermez, yalnız sayısını verir:
    satış temsilcisi VKN yazarak başkasının portföyünü taramasın.
    """
    cakisanlar = await ana_veri.vkn_cakismasi(db, tax_no, haric_id=haric_id)
    if not cakisanlar:
        return []
    if onay:
        if not gerekce or len(gerekce.strip()) < 5:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Aynı VKN'li kayıt onayı için gerekçe zorunlu (en az 5 karakter).",
            )
        return cakisanlar
    gorunen = [h for h in cakisanlar if not await svc.kapsam_disinda_mi(db, user, h.id)]
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        {
            "kod": "VKN_CAKISMASI",
            "mesaj": "Bu VKN başka aktif hesapta kayıtlı. Aynı firma değilse gerekçeyle onaylayın.",
            "mevcut": [{"id": h.id, "title": h.title} for h in gorunen],
            "kapsam_disi": len(cakisanlar) - len(gorunen),
        },
    )


async def _vkn_onayini_yaz(
    db, request: Request, user: User, hesap_id: int, cakisanlar: list[Account], gerekce
) -> None:
    if cakisanlar:
        await audit.log(
            db,
            "accounts",
            "vkn.cakisma.onay",
            entity_id=hesap_id,
            new_value={"cakisan_hesaplar": [h.id for h in cakisanlar], "gerekce": gerekce},
            user_id=user.id,
            ip=client_ip(request),
            is_personal_data=True,
        )


async def _kapsamli_hesap(db, hesap_id: int, user: User) -> Account:
    """Hesabı KAPSAM FİLTRESİ UYGULANARAK getirir; yoksa 404.

    `db.get()` kapsamı atlar. Yazma uçlarında bu fark ölümcüldü: satış
    temsilcisi kendi portföyü dışındaki hesabı PATCH'lediğinde kayıt
    DEĞİŞİYOR, cevap ise 404 dönüyordu — çünkü kapsam yalnız en sondaki
    `getir()` çağrısında, yani `commit()`ten SONRA uygulanıyordu. Ne kullanıcı
    ne denetçi yazmanın geçtiğini görebiliyordu.

    Kural: hesap kaydına id ile ulaşan her uç bu yardımcıdan geçer.
    """
    stmt = (
        select(Account)
        .where(Account.id == hesap_id, Account.is_deleted.is_(False))
        .options(selectinload(Account.partner), selectinload(Account.parent_dealer))
    )
    hesap = await db.scalar(svc.kapsam_uygula(stmt, user))
    if hesap is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hesap bulunamadı")
    return hesap


def _cikti(hesap: Account) -> HesapOut:
    out = HesapOut.model_validate(hesap)
    out.roller = hesap.roller
    out.eksik_alanlar = svc.eksik_alanlar(hesap)
    out.parent_dealer_title = hesap.parent_dealer.title if hesap.parent_dealer else None
    return out


@router.get("", response_model=list[HesapOut])
async def listele(
    db: DbDep,
    user: Okuyucu,
    q: str | None = None,
    rol: str | None = Query(
        default=None, description="MUSTERI | BAYI | MONTAJ_NOKTASI | TEDARIKCI"
    ),
    eksigi_olanlar: bool = False,
    dogrulanmamis: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    response: Response = None,  # type: ignore[assignment]
) -> list[HesapOut]:
    stmt = (
        select(Account)
        .where(Account.is_deleted.is_(False))
        .options(selectinload(Account.partner), selectinload(Account.parent_dealer))
        .order_by(Account.title)
    )
    stmt = svc.kapsam_uygula(stmt, user)
    if q:
        stmt = svc.arama_filtresi(stmt, q)
    if rol:
        sutun = {
            "MUSTERI": Account.is_musteri,
            "BAYI": Account.is_bayi,
            "MONTAJ_NOKTASI": Account.is_montaj_noktasi,
            "TEDARIKCI": Account.is_tedarikci,
        }.get(rol)
        if sutun is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen rol: {rol}")
        stmt = stmt.where(sutun.is_(True))
    if dogrulanmamis:
        stmt = stmt.where(Account.is_verified.is_(False))

    if eksigi_olanlar:
        # "Eksik bilgisi olanlar" SQL'de değil çıktıda hesaplanıyor; sayfalama
        # uygulansa toplam yanlış olurdu (filtre sonrası değil öncesi sayılırdı).
        # Hesap sayısı birkaç yüz olduğu için tamamı okunup sonra süzülür.
        tumu = [_cikti(h) for h in (await db.scalars(stmt)).all()]
        cikti = [h for h in tumu if h.eksik_alanlar]
        response.headers[TOPLAM_BASLIGI] = str(len(cikti))
        return cikti[offset : offset + limit]

    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return [_cikti(h) for (h,) in satirlar]


@router.get("/{hesap_id}", response_model=HesapOut)
async def getir(hesap_id: int, db: DbDep, user: Okuyucu) -> HesapOut:
    return _cikti(await _kapsamli_hesap(db, hesap_id, user))


class KisiIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    title: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=16)
    email: str | None = Field(default=None, max_length=160)
    is_primary: bool = False
    notes: str | None = None


def _kisi_cikti(k) -> dict:
    return {
        "id": k.id,
        "ad": k.full_name,
        "gorev": k.title,
        "telefon": k.phone,
        "eposta": k.email,
        "birincil": k.is_primary,
    }


async def _tek_birincil(db: DbDep, account_id: int, kisi_id: int) -> None:
    """Birincil yetkili tektir: yenisi işaretlenince eskisi düşer."""
    from app.models import Contact

    for digeri in (
        await db.scalars(
            select(Contact).where(
                Contact.account_id == account_id,
                Contact.id != kisi_id,
                Contact.is_primary.is_(True),
            )
        )
    ).all():
        digeri.is_primary = False


@router.post("/{hesap_id}/kisiler", status_code=status.HTTP_201_CREATED)
async def kisi_ekle(
    hesap_id: int, payload: KisiIn, request: Request, db: DbDep, user: Yazici
) -> dict:
    """Hesabın yetkili kişisi — hak ediş ve teklif yazışması buradan gider."""
    from app.models import Contact

    await _kapsamli_hesap(db, hesap_id, user)

    veri = payload.model_dump()
    try:
        if veri.get("phone"):
            veri["phone"] = normalize_msisdn(veri["phone"])
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    kisi = Contact(account_id=hesap_id, **veri)
    db.add(kisi)
    await db.flush()
    if kisi.is_primary:
        await _tek_birincil(db, hesap_id, kisi.id)
    await audit.log(
        db,
        "contacts",
        "olustur",
        entity_id=kisi.id,
        new_value={"hesap": hesap_id, "ad": kisi.full_name},
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=True,
    )
    await db.commit()
    return _kisi_cikti(kisi)


@router.patch("/kisiler/{kisi_id}")
async def kisi_guncelle(
    kisi_id: int, payload: KisiIn, request: Request, db: DbDep, user: Yazici
) -> dict:
    from app.models import Contact

    kisi = await db.get(Contact, kisi_id)
    if kisi is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kişi bulunamadı")
    # Kişi kaydı hesaba aittir; kapsam hesabın üzerinden çözülür. Yol
    # `hesap_id` taşımadığı için kontrol unutulmuştu: herhangi bir hesabın
    # yetkilisinin adı/telefonu/e-postası (KVKK kapsamında kişisel veri)
    # kapsam dışından değiştirilebiliyor ve silinebiliyordu.
    await _kapsamli_hesap(db, kisi.account_id, user)

    eski = _kisi_cikti(kisi)
    veri = payload.model_dump()
    try:
        if veri.get("phone"):
            veri["phone"] = normalize_msisdn(veri["phone"])
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    for alan, deger in veri.items():
        setattr(kisi, alan, deger)
    await db.flush()
    if kisi.is_primary:
        await _tek_birincil(db, kisi.account_id, kisi.id)
    await audit.log(
        db,
        "contacts",
        "guncelle",
        entity_id=kisi.id,
        old_value=eski,
        new_value=_kisi_cikti(kisi),
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=True,
    )
    await db.commit()
    return _kisi_cikti(kisi)


@router.delete("/kisiler/{kisi_id}", status_code=status.HTTP_204_NO_CONTENT)
async def kisi_sil(kisi_id: int, request: Request, db: DbDep, user: Yazici) -> None:
    from app.models import Contact

    kisi = await db.get(Contact, kisi_id)
    if kisi is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kişi bulunamadı")
    await _kapsamli_hesap(db, kisi.account_id, user)
    eski = _kisi_cikti(kisi)
    hesap_id = kisi.account_id
    await db.delete(kisi)
    await audit.log(
        db,
        "contacts",
        "sil",
        entity_id=kisi_id,
        old_value={**eski, "hesap": hesap_id},
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=True,
    )
    await db.commit()


@router.get("/{hesap_id}/kart")
async def kart(hesap_id: int, db: DbDep, user: Okuyucu) -> dict:
    """Hesap kartı: yetkili kişiler, cihazlar, araçlar, siparişler, abonelikler.

    Tek çağrı: müşterinin üzerine tıklayan kişi "bu firmada neler var"
    sorusunun cevabını parça parça dört ekrandan toplamak zorunda kalmasın.
    """
    from app.models import Contact, Device, Order, Product, Subscription, Vehicle

    hesap = await _kapsamli_hesap(db, hesap_id, user)

    kisiler = (
        await db.scalars(
            select(Contact)
            .where(Contact.account_id == hesap_id)
            .order_by(Contact.is_primary.desc(), Contact.full_name)
        )
    ).all()

    siparisler = (
        (
            await db.execute(
                select(Order)
                .where(Order.customer_id == hesap_id, Order.is_deleted.is_(False))
                .order_by(Order.order_date.desc(), Order.id.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )

    cihazlar = (
        await db.execute(
            select(Device, Product.name, Vehicle.plate)
            .join(Product, Product.id == Device.product_id)
            .outerjoin(Vehicle, Vehicle.id == Device.current_vehicle_id)
            .where(Device.current_customer_id == hesap_id, Device.is_deleted.is_(False))
            .order_by(Device.id.desc())
            .limit(500)
        )
    ).all()

    araclar = (
        await db.scalars(
            select(Vehicle)
            .where(Vehicle.customer_id == hesap_id, Vehicle.is_deleted.is_(False))
            .order_by(Vehicle.plate)
            .limit(500)
        )
    ).all()

    # Liste 500'de kesiliyor; SAYI ayrıca sorulur. Aksi halde kart 3.458 cihazlı
    # müşteride "Cihazlar (500)" yazıp yanlış bilgi veriyor.
    cihaz_sayisi = int(
        await db.scalar(
            select(func.count())
            .select_from(Device)
            .where(Device.current_customer_id == hesap_id, Device.is_deleted.is_(False))
        )
        or 0
    )
    arac_sayisi = int(
        await db.scalar(
            select(func.count())
            .select_from(Vehicle)
            .where(Vehicle.customer_id == hesap_id, Vehicle.is_deleted.is_(False))
        )
        or 0
    )

    abonelikler = (
        await db.scalars(
            select(Subscription)
            .where(Subscription.customer_id == hesap_id, Subscription.is_deleted.is_(False))
            .order_by(Subscription.id.desc())
            .limit(50)
        )
    ).all()

    return {
        "account_id": hesap.id,
        "kisiler": [_kisi_cikti(k) for k in kisiler],
        "siparisler": [
            {
                "id": o.id,
                "order_no": o.order_no,
                "order_date": o.order_date,
                "status": o.status,
                "currency": o.currency,
                "grand_total": o.grand_total,
            }
            for o in siparisler
        ],
        "cihazlar": [
            {
                "device_id": c.id,
                "kimlik": c.imei or c.serial_no,
                "urun": urun,
                "status": c.status,
                "plaka": plaka,
            }
            for c, urun, plaka in cihazlar
        ],
        "cihaz_sayisi": cihaz_sayisi,
        "arac_sayisi": arac_sayisi,
        "araclar": [
            {"id": a.id, "plaka": a.plate, "sase": a.chassis_no, "marka": a.brand, "model": a.model}
            for a in araclar
        ],
        "abonelikler": [
            {
                "id": s.id,
                "subscription_no": s.subscription_no,
                "status": s.status,
                "start_date": s.start_date,
                "end_date": s.end_date,
            }
            for s in abonelikler
        ],
    }


@router.get("/{hesap_id}/mukerrer-adaylari", response_model=list[MukerrerAday])
async def mukerrer_adaylari(hesap_id: int, db: DbDep, user: Okuyucu) -> list[MukerrerAday]:
    """Olası mükerrer kayıtlar. Birleştirme kararını insan verir — benzerlik
    tek başına ölçüt değil (kaynak veride farklı firmalar aynı telefonu
    taşıyor)."""
    hesap = await _kapsamli_hesap(db, hesap_id, user)
    return [
        MukerrerAday(
            id=a.id,
            title=a.title,
            benzerlik=round(b, 3),
            roller=a.roller,
            tax_no=a.tax_no,
            phone=a.phone,
        )
        for a, b in await svc.mukerrer_adaylari(db, hesap)
    ]


@router.post("", response_model=HesapOut, status_code=status.HTTP_201_CREATED)
async def olustur(payload: HesapIn, request: Request, db: DbDep, user: Yazici) -> HesapOut:
    if not any(
        (payload.is_musteri, payload.is_bayi, payload.is_montaj_noktasi, payload.is_tedarikci)
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Hesabın en az bir rolü olmalı (müşteri, bayi, montaj noktası veya tedarikçi)",
        )

    cakisanlar = await _vkn_kontrolu(
        db,
        user,
        payload.tax_no,
        haric_id=None,
        onay=payload.vkn_cakisma_onayi,
        gerekce=payload.vkn_cakisma_gerekce,
    )

    veri = payload.model_dump(exclude=_ORM_DISI)
    hesap = Account(**veri, created_by=user.id)
    db.add(hesap)
    await db.flush()
    await _vkn_onayini_yaz(db, request, user, hesap.id, cakisanlar, payload.vkn_cakisma_gerekce)

    if payload.is_montaj_noktasi:
        # Montaj noktası kaydı hak edişin ön koşulu; rol işaretliyse hep açılır.
        db.add(
            InstallationPartner(
                account_id=hesap.id,
                **(payload.partner.model_dump() if payload.partner else {}),
            )
        )
        await db.flush()

    await audit.log(
        db,
        "accounts",
        "olustur",
        entity_id=hesap.id,
        new_value={"title": hesap.title, "roller": hesap.roller},
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=True,  # unvan, iletişim, VKN → KVKK kapsamında
    )
    await db.commit()
    return await getir(hesap.id, db, user)


@router.patch("/{hesap_id}", response_model=HesapOut)
async def guncelle(
    hesap_id: int, payload: HesapPatch, request: Request, db: DbDep, user: Yazici
) -> HesapOut:
    hesap = await _kapsamli_hesap(db, hesap_id, user)
    if payload.version is not None and payload.version != hesap.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu kaydı siz görüntülerken başka biri değiştirdi. Sayfayı yenileyip tekrar deneyin.",
        )

    # VKN kontrolü yalnız VKN gövdede VAR ve eskisinden FARKLI ise (E14 B1).
    cakisanlar: list[Account] = []
    if "tax_no" in payload.model_fields_set and payload.tax_no and payload.tax_no != hesap.tax_no:
        cakisanlar = await _vkn_kontrolu(
            db,
            user,
            payload.tax_no,
            haric_id=hesap.id,
            onay=payload.vkn_cakisma_onayi,
            gerekce=payload.vkn_cakisma_gerekce,
        )

    veri = payload.model_dump(exclude_unset=True, exclude=_ORM_DISI | {"version"})
    # Kapsamı olan kullanıcı temsilciyi değiştiremez: hesabı kendine atayıp
    # kapsamını tek istekte genişletmek mümkündü.
    if "sales_rep_id" in veri and scope_filter(user) is not None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Satış temsilcisi ataması bu rolde değiştirilemez.",
        )
    for alan, deger in veri.items():
        setattr(hesap, alan, deger)
    hesap.updated_by = user.id

    if payload.partner is not None:
        ortak = await db.get(InstallationPartner, hesap_id)
        if ortak is None:
            db.add(InstallationPartner(account_id=hesap_id, **payload.partner.model_dump()))
        else:
            for alan, deger in payload.partner.model_dump().items():
                setattr(ortak, alan, deger)

    await audit.log_change(
        db, hesap, "guncelle", user_id=user.id, ip=client_ip(request), is_personal_data=True
    )
    await _vkn_onayini_yaz(db, request, user, hesap.id, cakisanlar, payload.vkn_cakisma_gerekce)
    await db.commit()
    return await getir(hesap_id, db, user)


@router.post("/{hesap_id}/dogrula", response_model=HesapOut)
async def dogrula(
    hesap_id: int, request: Request, db: DbDep, clock: ClockDep, user: Dogrulayici
) -> HesapOut:
    """Servis ekranından hızlı açılan müşteriyi doğrular (TS-014).

    `is_verified/verified_at/verified_by` YALNIZ bu uçla yazılır; HesapIn/Patch
    bu alanları taşımaz (E14 B2) — `hesap.yaz` sahibi doğrulamayı atlatamaz.
    Zaten doğrulanmış kayıt 409: ikinci doğrulama, ilk doğrulayanı ezerdi.
    """
    hesap = await _kapsamli_hesap(db, hesap_id, user)
    if hesap.is_verified:
        raise HTTPException(status.HTTP_409_CONFLICT, "Hesap zaten doğrulanmış.")
    hesap.is_verified = True
    hesap.verified_at = clock.now()
    hesap.verified_by = user.id
    hesap.updated_by = user.id
    await audit.log(
        db,
        "accounts",
        "hesap.dogrula",
        entity_id=hesap.id,
        new_value={"is_verified": True},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await getir(hesap_id, db, user)
