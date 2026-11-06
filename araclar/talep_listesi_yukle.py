"""Güvenlik talep takip listesini (ve temsilî Haberleşme / Set Bariyer işlerini) yerel
deneme ERP'sine ROL KULLANICILARIYLA yeni iş olarak yükler (rol testi 1. aşama).

YALNIZ yerel deneme ortamı (http://127.0.0.1:8000). Canlıya ASLA çalıştırma.

- Parolalar `.yerel_gizli/rol_test_kullanicilari.txt` dosyasından okunur; hiçbir çıktıya yazılmaz.
- Kişi adları sisteme/çıktıya aktarılmaz: PERSONEL sütunu test kullanıcılarına eşlenir (eşleme
  yalnız bellekte), NOT sütunundaki ad parçaları maskelenir (PERSONEL sütunundaki ad sözcükleri +
  isteğe bağlı `.yerel_gizli/ad_maskesi.txt`, satır başına bir sözcük). Plaka da yazılmaz.
- İletişim kişisi listede yok: kurgusal "Tesis Teknik Sorumlusu" / "0 555 000 00 00".
- Planlanan tarih ve durum İŞLENMEZ; hedef durum `--cikti` JSON'una yazılır (2. aşama işler).
- Her eylem önce rolün kendi kullanıcısıyla denenir; yetki yetmezse (403) sıradaki yedek kullanıcıyla
  tamamlanır ve olay `yetki_olaylari` listesine yazılır (rapora bulgu).
- Yeniden çalıştırılabilir: `--cikti` dosyasında `anahtar`ı olan kayıt yeniden açılmaz.

Kullanım (denge-erp/backend içinde, httpx + openpyxl gerekir):
    uv run python ..\\..\\araclar\\talep_listesi_yukle.py --bolum hepsi [--kuru]
    --bolum: A | B | TELEKOM | BARIYER | hepsi
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import httpx

KOK = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8000/api"
TS = "/teknik-servis"
TALEP_XLSX = KOK / "kaynak" / "is_analizi_2026-11-04" / "Guvenlik_Talep_Takip_26.10.2026.xlsx"
CIKTI = KOK / "analiz" / "rol_testi" / "acilan_isler.json"
ILETISIM_AD = "Tesis Teknik Sorumlusu"
ILETISIM_TEL = "0 555 000 00 00"
ACIKLAMA = ("Rol testi 1. aşama açılan işler ve ekipmanlar. 'no' olanlar servis işi, 'ekipman_id' olanlar ekipman; "
            "'hedef' = listedeki DURUM+NOT'tan hedef durum (2. aşama uygular); 'plan' işlenmedi. Kişi adı yoktur. "
            "Olaylar: acilan_isler_olaylar.json. Üretici: araclar/talep_listesi_yukle.py")

# --- Oturum -------------------------------------------------------------------------------


def _parola(kullanici: str) -> str:
    dosya = KOK / ".yerel_gizli" / "rol_test_kullanicilari.txt"
    for satir in dosya.read_text(encoding="utf-8").splitlines():
        if not satir.strip() or satir.startswith("#"):
            continue
        p = satir.split("\t")
        if p[0] == kullanici:
            return p[2]
    raise SystemExit(f"{kullanici} parola dosyasında yok")


_OTURUMLAR: dict[tuple[str, str], httpx.Client] = {}


def oturum(kullanici: str, sirket: str) -> httpx.Client:
    anahtar = (kullanici, sirket)
    if anahtar in _OTURUMLAR:
        return _OTURUMLAR[anahtar]
    c = httpx.Client(headers={"X-Requested-With": "fetch"}, timeout=60, base_url=API)
    r = c.post("/auth/login", json={"username": kullanici, "password": _parola(kullanici)})
    if r.status_code >= 400:
        raise SystemExit(f"Giriş başarısız: {kullanici} ({r.status_code})")
    r = c.put("/oturum/aktif-sirket", json={"kod": sirket})
    if r.status_code >= 400:
        raise SystemExit(f"{kullanici} {sirket} şirketini seçemedi: {r.status_code} {r.text[:200]}")
    _OTURUMLAR[anahtar] = c
    return c


YETKI_OLAYLARI: list[dict] = []
UYARILAR: list[dict] = []


def dene(eylem: str, kullanicilar: list[str], sirket: str, cagri):
    """Sırayla kullanıcıları dener; 403'te bir sonrakine geçer. (yanıt, kullanan) döner."""
    son = None
    for i, k in enumerate(kullanicilar):
        r = cagri(oturum(k, sirket))
        if r.status_code == 403 and i + 1 < len(kullanicilar):
            YETKI_OLAYLARI.append(
                {"eylem": eylem, "kullanici": k, "durum": 403, "mesaj": _mesaj(r), "yedek": kullanicilar[i + 1]}
            )
            son = r
            continue
        return r, k
    return son, kullanicilar[-1]


def _mesaj(r: httpx.Response) -> str:
    try:
        d = r.json().get("detail")
    except Exception:
        return r.text[:200]
    if isinstance(d, dict):
        return d.get("mesaj") or json.dumps(d, ensure_ascii=False)[:200]
    return str(d)[:300]


# --- Metin yardımcıları ------------------------------------------------------------------------


def tr_upper(s: str) -> str:
    return s.replace("i", "İ").replace("ı", "I").upper()


def temiz(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def ad_sozcukleri(personel_sutunu: list[str]) -> set[str]:
    sozcuk: set[str] = set()
    for p in personel_sutunu:
        for t in re.split(r"[^\wÇĞİÖŞÜçğıöşü]+", tr_upper(p or "")):
            if len(t) >= 3:
                sozcuk.add(t)
    ek = KOK / ".yerel_gizli" / "ad_maskesi.txt"
    if ek.exists():
        sozcuk |= {tr_upper(x.strip()) for x in ek.read_text(encoding="utf-8").splitlines() if x.strip()}
    return sozcuk


def maskele(metin: str, adlar: set[str]) -> str:
    def degis(m):
        return "" if tr_upper(m.group(0)) in adlar else m.group(0)

    s = re.sub(r"[\wÇĞİÖŞÜçğıöşü]+", degis, metin)
    s = re.sub(r"\s*[-–]\s*(?=[-–\s]*($|[.,]))", " ", s)  # kalan "- -" ayraçları
    s = re.sub(r"\s{2,}", " ", s).strip(" -–,")
    return s


def kisiler(personel: str) -> list[str]:
    return [tr_upper(x.strip()) for x in re.split(r"[,/&\n]|\s-\s|-(?=[A-ZÇĞİÖŞÜ])", personel or "") if x.strip()]


class TeknisyenEsleme:
    """Gerçek ad → test kullanıcısı; yalnız bellekte (dosyaya yazılmaz)."""

    def __init__(self, havuz: list[str]):
        self.havuz = havuz
        self.esleme: dict[str, str] = {}

    def esle(self, personel: str) -> list[str]:
        sonuc = []
        for ad in kisiler(personel):
            if ad not in self.esleme:
                self.esleme[ad] = self.havuz[len(self.esleme) % len(self.havuz)]
            if self.esleme[ad] not in sonuc:
                sonuc.append(self.esleme[ad])
        return sonuc


# --- İl çıkarımı -----------------------------------------------------------------------------

IL_IPUCU = {
    "BALÇOVA": "İzmir", "GAZİEMİR": "İzmir", "TORBALI": "İzmir", "İZMİR": "İzmir", "ÇANAKKALE": "Çanakkale",
    "DERİNCE": "Kocaeli", "DİLOVASI": "Kocaeli", "KOCAELİ": "Kocaeli", "GÖLCÜK": "Kocaeli", "EDREMİT": "Balıkesir",
    "BALIKESİR": "Balıkesir", "BALYA": "Balıkesir", "KUŞADASI": "Aydın", "AYDIN": "Aydın", "KEŞAN": "Edirne",
    "ZONGULDAK": "Zonguldak", "ŞANLIURFA": "Şanlıurfa", "ANKARA": "Ankara", "POLATLI": "Ankara",
    "ESKİŞEHİR": "Eskişehir", "KAYSERİ": "Kayseri", "ADANA": "Adana", "ANTALYA": "Antalya", "ÇORLU": "Tekirdağ",
    "İSTANBUL": "İstanbul", "ŞİŞLİ": "İstanbul", "MALTEPE": "İstanbul", "SARIYER": "İstanbul", "KARTAL": "İstanbul",
    "LEVENT": "İstanbul", "SANCAKTEPE": "İstanbul", "ATAŞEHİR": "İstanbul", "MASLAK": "İstanbul",
    "ARNAVUTKÖY": "İstanbul", "BAKIRKÖY": "İstanbul", "KAĞITHANE": "İstanbul", "BEYLİKDÜZÜ": "İstanbul",
    "SAKARYA": "Sakarya", "BURSA": "Bursa", "GAZİANTEP": "Gaziantep", "KIRIKKALE": "Kırıkkale",
    "ERZİNCAN": "Erzincan", "ESENLER": "İstanbul", "MECİDİYEKÖY": "İstanbul", "PENDİK": "İstanbul",
}
YURT_DISI = ("KIBRIS", "NİJERYA")


def il_bul(*metinler: str) -> tuple[str, str | None]:
    """(il, not). Yurt dışı/bilinmeyen → İstanbul yer tutucu + not (ERP yurt dışı ili tutamıyor)."""
    birlesik = tr_upper(" ".join(m for m in metinler if m))
    for yd in YURT_DISI:
        if yd in birlesik:
            return "İstanbul", f"YURT DIŞI ({yd}): ERP il listesi yurt dışını tutmuyor; il yer tutucu"
    for ipucu, il in IL_IPUCU.items():
        if ipucu in birlesik:
            return il, None
    return "İstanbul", "İl listede yok; İstanbul varsayıldı"


def musteri_ayir(firma: str, lokasyon: str) -> tuple[str, str]:
    """'İSKİ / KAĞITHANE / NURTEPE' → ('İSKİ', 'KAĞITHANE / NURTEPE'). Tesis yoksa LOKASYON."""
    f = temiz(firma)
    f = re.sub(r"\s+BAKIMLARI$", "", f)
    parca = re.split(r"\s*[–/]\s*|\s+-\s+", f, maxsplit=1)
    unvan = parca[0].strip()
    tesis = parca[1].strip() if len(parca) > 1 else ""
    if not tesis:
        tesis = temiz(lokasyon) or "Merkez"
    return unvan, tesis[:200]


def unvan_anahtar(unvan: str) -> str:
    u = tr_upper(unvan).replace("İ", "I")
    return re.sub(r"[^A-Z0-9ÇĞÖŞÜ]", "", u)


# --- Sınıflama ---------------------------------------------------------------------------------

EYLEM_RE = re.compile(
    r"BAKIM|ARIZA|KURULUM|TESL[İI]M|TAM[İI]R|DE[ĞG][İI][ŞS]|E[ĞG][İI]T[İI]M|TESP[İI]T|MONTAJ|DEVREYE|SANDIK|SEVK[İI]YAT|KAL[İI]BRASYON|HAZIRLAN|KLAVYE"
)
CIHAZ_RE = re.compile(r"(?<![\d\-])\b(\d{1,2})\s+(?:ADET\s+)?(?:[A-ZÇĞİÖŞÜ0-9\-&\. ]{0,30}?)(X[\s-]?RAY|KAPI|KMD|DEDEKT)")


def cihaz_sayisi(detay: str) -> tuple[int, int, int]:
    """(toplam, xray, kapı) — yalnız cihaz sözcüğüne bağlı adetler (parça adetleri sayılmaz)."""
    x = k = 0
    for m in CIHAZ_RE.finditer(detay):
        n = int(m.group(1))
        if m.group(2).startswith("X"):
            x += n
        else:
            k += n
    if x + k == 0:
        # "SC-5030A MODEL 6 ADET CİHAZIN BAKIMI"
        m = re.search(r"\b(\d{1,2})\s+ADET\s+C[İI]HAZ", detay)
        if m:
            x = int(m.group(1))
    return max(x + k, 1), x, k


def a_turleri(detay: str) -> list[tuple[str, str]]:
    """Satırdan (tür, alt_tür) listesi; bir satır birden çok iş üretebilir (bakım + arıza, kurulum + eğitim)."""
    d = detay
    turler: list[tuple[str, str]] = []
    if re.search(r"SANDIK|SEVK[İI]YATA", d):
        return [("DESTEK", "depo")]
    if re.search(r"BAKIM|KAL[İI]BRASYON", d):
        turler.append(("PLANSIZ_BAKIM", "bakim"))
        if re.search(r"DE[ĞG][İI][ŞS]T[İI]R", d):
            turler.append(("ARIZA", "onarim"))
    elif re.search(r"KONVEY", d):
        turler.append(("KURULUM", "teslim"))
    elif re.search(r"TESL[İI]M ALIN", d) and not re.search(r"KURULUM", d):
        if re.search(r"TESL[İI]M[İI] SA[ĞG]LANACAK", d):
            turler += [("KURULUM", "teslim"), ("TOPLAMA", "ikame_alma")]
        else:
            turler.append(("TASIMA", "teslim_alma"))
    elif re.search(r"KURULUM|DEVREYE|TESL[İI]M ED", d):
        turler.append(("KURULUM", "kurulum"))
    elif re.search(r"ARIZA|TESP[İI]T|TAM[İI]R|DE[ĞG][İI][ŞS]|MONTAJ|KLAVYE|JENERAT", d):
        turler.append(("ARIZA", "ariza"))
    if re.search(r"E[ĞG][İI]T[İI]M", d):
        if re.search(r"ARIZA", d) and not turler:
            turler.append(("ARIZA", "ariza"))
        if re.search(r"KAPI DEDEKT[ÖO]R[ÜU]NDE ARIZA", d) and ("ARIZA", "ariza") not in turler:
            turler.append(("ARIZA", "ariza"))
        turler.append(("DESTEK", "egitim"))
    return turler or [("DESTEK", "diger")]


def hedef_durum(durum: str, notu: str, tur: str) -> dict:
    """Listedeki DURUM + NOT → 2. aşamanın uygulayacağı hedef (IS_ANALIZI_OZETI §7.5)."""
    d = tr_upper(temiz(durum))
    n = tr_upper(notu or "")
    if d.startswith("TAMAMLAND"):
        sonuc = "COZULDU"
        if tur == "ARIZA" and re.search(r"TESP[İI]T[İI] YAPILDI", n) and not re.search(r"DE[ĞG][İI][ŞS]|MONTAJ", n):
            sonuc = "TEKLIF_SUNULACAK"
        h = {"durum": "TAMAMLANDI", "sonuc": sonuc, "cozum_kanali": "YERINDE", "sure_kaydi": "eksik"}
        if re.search(r"LEKE|ATLAMA|DONMA", n):
            h["bulgu"] = "Sonuç notunda yeni arıza bulgusu var → bağlı iş (BAKIM_BULGUSU) önerilir"
        return h
    if d.startswith("PLANLAND"):
        return {"durum": "PLANLANDI"}
    if d.startswith("DEVAM"):
        if re.search(r"TEM[İI]N|PAR[ÇC]A|KARGO|ARIZALI", n):
            return {"durum": "BEKLEMEDE", "neden": "MALZEME"}
        if re.search(r"ELEKTR[İI]K|YER", n):
            return {"durum": "BEKLEMEDE", "neden": "MUSTERI_ERISIMI"}
        return {"durum": "ISLEMDE"}
    if d.startswith("BEKLEMEDE"):
        if re.search(r"KARGO", n):
            return {"durum": "BEKLEMEDE", "neden": "DIS_SERVIS", "aciklama": "Kargo/müşteri dönüşü bekleniyor"}
        return {"durum": "BEKLEMEDE", "neden": "DIGER", "aciklama": "Listede BEKLEMEDE; neden belirtilmemiş"}
    if d.startswith("ERTELEND"):
        return {"durum": "PLANLAMADA", "plan_degisim_nedeni": "ERTELEME"}
    return {"durum": "MUSTERI_TALEBI"}


def plan_bilgisi(deger) -> dict | None:
    if deger is None or temiz(deger) == "":
        return None
    if isinstance(deger, (dt.datetime, dt.date)):
        return {"plan_tarihi": deger.strftime("%Y-%m-%d")}
    s = temiz(deger)
    m = re.match(r"(\d{1,2})\s*-\s*(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
    if m:
        bas = dt.date(int(m.group(4)), int(m.group(3)), int(m.group(1)))
        bit = dt.date(int(m.group(4)), int(m.group(3)), int(m.group(2)))
        return {"plan_tarihi": bas.isoformat(), "plan_bitis": bit.isoformat(), "not": "Listede tarih aralığı"}
    return {"plan_tarihi": None, "not": f"Listede: {s}"}


def ulasim(arac) -> str | None:
    a = tr_upper(temiz(arac))
    if not a:
        return None
    if "HAVA" in a:
        return "HAVA_YOLU (ulaşım türü; ERP'de araç değil)"
    return "PLAKALI_ARAC (plaka rapora yazılmaz)"


# --- Ana veri (müşteri / tesis) --------------------------------------------------------------


class AnaVeri:
    def __init__(self, sirket: str, rol: str, musteri_yedek: list[str], tesis_yedek: list[str]):
        self.sirket, self.rol = sirket, rol
        self.musteri_yedek, self.tesis_yedek = musteri_yedek, tesis_yedek
        self.hesap: dict[str, int] = {}
        self.tesis: dict[tuple[int, str], int] = {}

    def musteri(self, unvan: str, il: str, tesis: str) -> tuple[int, int]:
        anahtar = unvan_anahtar(unvan)
        c = oturum(self.rol, self.sirket)
        if anahtar not in self.hesap:
            bulunan = None
            r = c.get(f"{TS}/ana-veri/musteri-ara", params={"q": unvan[:40]})
            if r.status_code == 200:
                for s in r.json():
                    if unvan_anahtar(s["unvan"]) == anahtar:
                        bulunan = s["id"]
                        break
            if bulunan is None:
                govde = {"unvan": unvan, "il": il, "tesis_adi": tesis}
                r, kim = dene(
                    f"hızlı müşteri ({unvan})",
                    [self.rol, *self.musteri_yedek],
                    self.sirket,
                    lambda s: s.post(f"{TS}/ana-veri/hizli-musteri", json=govde),
                )
                if r.status_code == 409:
                    d = r.json().get("detail", {})
                    UYARILAR.append({"tur": "BENZER_MUSTERI", "unvan": unvan, "mesaj": json.dumps(d, ensure_ascii=False)[:300]})
                    r = oturum(kim, self.sirket).post(f"{TS}/ana-veri/hizli-musteri", json={**govde, "onay_benzer": True})
                if r.status_code >= 400:
                    raise SystemExit(f"Müşteri açılamadı {unvan}: {r.status_code} {r.text[:300]}")
                j = r.json()
                bulunan = j["hesap"]["id"]
                if j.get("lokasyon"):
                    self.tesis[(bulunan, tr_upper(tesis))] = j["lokasyon"]["id"]
            self.hesap[anahtar] = bulunan
        hid = self.hesap[anahtar]
        tk = (hid, tr_upper(tesis))
        if tk not in self.tesis:
            r = c.get(f"{TS}/ana-veri/lokasyon-ara", params={"hesap_id": hid})
            for s in r.json() if r.status_code == 200 else []:
                if tr_upper(s.get("tesis_adi") or "") == tr_upper(tesis):
                    self.tesis[tk] = s["id"]
            if tk not in self.tesis:
                govde = {"hesap_id": hid, "kind": "TESIS", "site_name": tesis, "city": il}
                r, _ = dene(
                    f"tesis ekle ({unvan} / {tesis})",
                    [self.rol, *self.tesis_yedek],
                    self.sirket,
                    lambda s: s.post("/lokasyonlar", json=govde),
                )
                if r.status_code == 409:
                    self.tesis[tk] = r.json()["detail"]["mevcut"]["id"]
                elif r.status_code >= 400:
                    raise SystemExit(f"Tesis açılamadı {unvan}/{tesis}: {r.status_code} {r.text[:300]}")
                else:
                    self.tesis[tk] = r.json()["id"]
        return hid, self.tesis[tk]


# --- İş açma -----------------------------------------------------------------------------------


def is_ac(kullanicilar: list[str], sirket: str, govde: dict) -> tuple[dict, str]:
    govde = {
        "talep_kanali": "DIGER",
        "iletisim_ad": ILETISIM_AD,
        "iletisim_telefon": ILETISIM_TEL,
        "oncelik": "NORMAL",
        **govde,
    }
    r, kim = dene(f"iş aç ({govde['birim']}/{govde['tur']})", kullanicilar, sirket, lambda s: s.post(f"{TS}/isler", json=govde))
    if r.status_code == 409:
        UYARILAR.append({"tur": "MUKERRER_409", "konu": govde["konu"], "mesaj": _mesaj(r)})
        r = oturum(kim, sirket).post(f"{TS}/isler", json={**govde, "mukerrer_gec": True})
    if r.status_code >= 400:
        raise SystemExit(f"İş açılamadı: {r.status_code} {r.text[:400]} — {govde['konu']}")
    j = r.json()
    for u in j.get("uyarilar") or []:
        UYARILAR.append({"tur": u.get("kod"), "so_no": j.get("so_no"), "mesaj": str(u)[:250]})
    return j, kim


def kayit(liste: list[dict], **alan) -> None:
    liste.append(alan)
    CIKTI.write_text(json.dumps({"aciklama": ACIKLAMA, "isler": liste}, ensure_ascii=False, indent=1), encoding="utf-8")


# --- Bölüm A / B ---------------------------------------------------------------------------------


def talep_satirlari():
    import openpyxl

    ws = openpyxl.load_workbook(TALEP_XLSX, data_only=True).active
    satirlar = []
    for i, r in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not any(r):
            continue
        satirlar.append({
            "satir": i, "talep": r[0], "firma": temiz(r[1]), "lokasyon": temiz(r[2]), "arac": r[3],
            "personel": temiz(r[4]), "detay": temiz(tr_upper(str(r[5] or ""))), "plan": r[8],
            "durum": temiz(r[9]), "not": temiz(r[10]),
        })
    return satirlar


def bolum(s: dict) -> str:
    return "A" if (s["talep"] or EYLEM_RE.search(s["detay"])) else "B"


def yukle_a(satirlar, adlar, esleme, mevcut, liste, kuru):
    av = AnaVeri("ELEKTRONIK", "t_ops_guv", ["t_sdestek_guv", "t_yon_guv"], ["t_yon_guv"])
    for s in satirlar:
        if bolum(s) != "A":
            continue
        unvan, tesis = musteri_ayir(s["firma"], s["lokasyon"])
        if "KÖPA" in unvan:
            tesis = s["lokasyon"]
        il, il_notu = il_bul(s["lokasyon"], s["firma"])
        toplam, _, _ = cihaz_sayisi(s["detay"])
        not_m = maskele(s["not"], adlar)
        teknisyen = esleme.esle(s["personel"])
        for tur, alt in a_turleri(s["detay"]):
            adet = toplam if tur in ("PLANSIZ_BAKIM", "ARIZA") and alt != "onarim" else 1
            for n in range(1, adet + 1):
                anahtar = f"A:{s['satir']}:{tur}:{alt}:{n}"
                if anahtar in mevcut:
                    continue
                ek = f" (cihaz {n}/{adet})" if adet > 1 else ""
                konu = f"{unvan} {tesis} — {s['detay'][:120]}"[:190 - len(ek)] + ek
                aciklama = "\n".join(x for x in [
                    f"Talep listesi 26.10.2026, satır {s['satir']} ({alt}).",
                    f"Talep tarihi: {s['talep']:%d.%m.%Y}" if isinstance(s["talep"], dt.datetime) else "Talep tarihi: listede yok",
                    f"Talep detayı: {s['detay']}",
                    "Seri no bilinmiyor (seri bekleniyor)." if tur in ("PLANSIZ_BAKIM", "ARIZA") else None,
                    il_notu,
                ] if x)
                if kuru:
                    print("A", anahtar, tur, il, "|", konu)
                    continue
                hid, lok = av.musteri(unvan, il, tesis)
                j, kim = is_ac(["t_ops_guv"], "ELEKTRONIK", {
                    "birim": "GUVENLIK", "tur": tur, "konu": konu, "customer_id": hid, "address_id": lok,
                    "aciklama": aciklama,
                })
                kayit(liste, anahtar=anahtar, no=j["so_no"], id=j["id"], sirket="ELEKTRONIK", birim="GUVENLIK",
                      tur=tur, alt_tur=alt, konu=konu, musteri=unvan, musteri_id=hid, lokasyon_id=lok,
                      acan=kim, kaynak=f"Guvenlik_Talep_Takip satır {s['satir']} (A)",
                      kaynak_durum=s["durum"] or None, kaynak_not=not_m or None,
                      hedef=hedef_durum(s["durum"], s["not"], tur), plan=plan_bilgisi(s["plan"]),
                      ulasim=ulasim(s["arac"]), eslenen_teknisyen=teknisyen,
                      seri="yok (bilinmiyor)", cihaz_sira=f"{n}/{adet}")
                print(j["so_no"], tur, konu[:80])


KALEM_RE = re.compile(r"(\d+)\s*ADET\s+([^;]+)")


def kalemler(detay: str):
    for parca in detay.split(";"):
        m = KALEM_RE.search(parca)
        if not m:
            continue
        n, ad = int(m.group(1)), temiz(m.group(2))
        if re.search(r"X[\s-]?RAY", ad):
            tip = "XRAY"
        elif re.search(r"EL DEDEKT", ad):
            tip = "EL_DEDEKTORU"
        elif re.search(r"DEDEKT|KMD", ad):
            tip = "KAPI_DEDEKTORU"
        else:
            tip = None  # roller / sehpa / kılıf: aksesuar (ERP'de ürün kalemi takibi yok)
        yield n, ad, tip


def yukle_b(satirlar, adlar, esleme, mevcut, liste, kuru):
    av = AnaVeri("ELEKTRONIK", "t_sdestek_guv", ["t_yon_guv"], ["t_ops_guv", "t_yon_guv"])
    for s in satirlar:
        if bolum(s) != "B":
            continue
        unvan, tesis = musteri_ayir(s["firma"], s["lokasyon"])
        il, il_notu = il_bul(s["lokasyon"], s["firma"])
        aksesuar = [f"{n} x {ad}" for n, ad, tip in kalemler(s["detay"]) if tip is None]
        ekipmanlar = []
        hid = lok = None
        for n, ad, tip in kalemler(s["detay"]):
            if tip is None:
                continue
            for i in range(1, n + 1):
                anahtar = f"B:{s['satir']}:EKIPMAN:{tip}:{ad[:30]}:{i}"
                if anahtar in mevcut:
                    ekipmanlar.append(mevcut[anahtar].get("ekipman_id") or mevcut[anahtar].get("id"))
                    continue
                if kuru:
                    print("B ekipman", anahtar)
                    continue
                if hid is None:
                    hid, lok = av.musteri(unvan, il, tesis)
                govde = {
                    "birim": "GUVENLIK", "equipment_type": tip, "account_id": hid, "address_id": lok,
                    "model": ad[:80], "lifecycle_status": "KURULUM_BEKLIYOR",
                    "notes": f"Satış kalemi (talep listesi satır {s['satir']}); seri bilinmiyor."
                    + (f" Aksesuar: {', '.join(aksesuar)}" if aksesuar else ""),
                }
                r, kim = dene(f"ekipman aç ({tip})", ["t_sdestek_guv", "t_yon_guv"], "ELEKTRONIK",
                              lambda c: c.post(f"{TS}/ekipman", json=govde))
                if r.status_code == 409:
                    UYARILAR.append({"tur": "EKIPMAN_409", "mesaj": _mesaj(r)})
                    r = oturum(kim, "ELEKTRONIK").post(f"{TS}/ekipman", json={**govde, "duplicate_ack_reason": "Seri bilinmiyor; satış kalemi"})
                if r.status_code >= 400:
                    raise SystemExit(f"Ekipman açılamadı: {r.status_code} {r.text[:300]}")
                e = r.json()
                ekipmanlar.append(e["id"])
                mevcut[anahtar] = {"id": e["id"]}
                kayit(liste, anahtar=anahtar, ekipman_id=e["id"], tip=tip, model=ad[:80], musteri=unvan,
                      musteri_id=hid, lokasyon_id=lok, acan=kim, kaynak=f"Guvenlik_Talep_Takip satır {s['satir']} (B)")
        durum = tr_upper(s["durum"])
        yurt_disi = il_notu and il_notu.startswith("YURT")
        if not (durum.startswith("TAMAMLAND") or durum.startswith("PLANLAND")) or yurt_disi:
            continue
        tur = "TASIMA" if "KARGO" in s["detay"] else "KURULUM"
        anahtar = f"B:{s['satir']}:{tur}"
        if anahtar in mevcut or kuru:
            if kuru and anahtar not in mevcut:
                print("B iş", anahtar, unvan)
            continue
        if hid is None:
            hid, lok = av.musteri(unvan, il, tesis)
        konu = f"{unvan} — satılan cihaz {('sevki' if tur == 'TASIMA' else 'kurulumu')}: {s['detay'][:110]}"[:200]
        j, kim = is_ac(["t_sdestek_guv", "t_ops_guv"], "ELEKTRONIK", {
            "birim": "GUVENLIK", "tur": tur, "konu": konu, "customer_id": hid, "address_id": lok,
            "aciklama": f"Talep listesi B bölümü satır {s['satir']}. Kalemler: {s['detay']}\n"
                        f"İlgili ekipman kayıtları (KURULUM_BEKLIYOR): {ekipmanlar}",
        })
        kayit(liste, anahtar=anahtar, no=j["so_no"], id=j["id"], sirket="ELEKTRONIK", birim="GUVENLIK", tur=tur,
              konu=konu, musteri=unvan, musteri_id=hid, lokasyon_id=lok, acan=kim,
              kaynak=f"Guvenlik_Talep_Takip satır {s['satir']} (B)", kaynak_durum=s["durum"],
              kaynak_not=maskele(s["not"], adlar) or None, hedef=hedef_durum(s["durum"], s["not"], tur),
              plan=plan_bilgisi(s["plan"]), eslenen_teknisyen=esleme.esle(s["personel"]),
              ekipman_idler=ekipmanlar, ekipman_hedef_durum="KURULU" if durum.startswith("TAMAMLAND") else "KURULUM_BEKLIYOR")
        print(j["so_no"], tur, konu[:80])


# --- Temsilî Haberleşme ve Set Bariyer işleri (iş planı Excel'i 2025–2026, firma adları) ---------

TELEKOM_ISLER = [
    # (kaynak tarih, firma, tesis, il, tür, konu, adet, hedef, teknisyen)
    ("2026-07-13", "İGDAŞ", "Fatih Şebeke", "İstanbul", "ARIZA", "Araç telsizi arızası (Fatih şebeke)", 2, "PLANLANDI", ["t_tek_hab"]),
    ("2026-06-16", "RÖNESANS TSK PROJESİ", "Ankara Şantiye", "Ankara", "ARIZA", "Telsiz sistemi arızasına müdahale ve onarım", 1, "ISLEMDE", ["t_tek_hab", "t_sef_hab"]),
    ("2026-07-07", "HISTORIA AVM", "Mecidiyeköy", "İstanbul", "ARIZA", "Telsiz sistemi arıza keşfi", 1, "PLANLANDI", ["t_tek_hab"]),
    ("2026-10-13", "TP-OTC FİLYOS PROJESİ", "Filyos", "Zonguldak", "ARIZA", "Kurulu telsiz sisteminde arıza tespiti ve onarım", 1, "PLANLANDI", ["t_tek_hab", "t_sef_hab"]),
    ("2026-07-14", "ÜSTAY İNŞAAT", "Aliağa Şantiye", "İzmir", "ARIZA", "RD625 röle laboratuvar onarımı (arızalı röle iade alındı, yedek teslim edildi)", 1, "BEKLEMEDE:DIS_SERVIS", ["t_tek_hab"]),
    ("2026-08-21", "MAKİNE VE KİMYA ENDÜSTRİSİ", "Kırıkkale Tesisi", "Kırıkkale", "KESIF", "Telsiz sistemi kurulum keşfi", 1, "PLANLANDI", ["t_sef_hab"]),
    ("2026-10-02", "REC", "Cerrahpaşa Hastanesi", "İstanbul", "KESIF", "OKTH sistem keşfi", 1, "MUSTERI_TALEBI", ["t_sef_hab"]),
    ("2026-10-01", "HALKBANKASI", "Gaziantep", "Gaziantep", "PLANSIZ_BAKIM", "Telsiz sistemleri yıllık bakımı (Gaziantep)", 1, "PLANLANDI", ["t_tek_hab"]),
    ("2026-09-16", "HALKBANKASI", "İstanbul Finans Merkezi", "İstanbul", "PLANSIZ_BAKIM", "Telsiz sistemleri yıllık bakımı ve IP yapılandırması", 1, "TAMAMLANDI", ["t_tek_hab"]),
    ("2026-07-21", "ESENLER BELEDİYESİ", "Esenler", "İstanbul", "PLANSIZ_BAKIM", "Telsiz sistemi aylık bakımı", 1, "PLANLANDI", ["t_tek_hab"]),
    ("2026-10-15", "BUSKİ", "Bursa", "Bursa", "KURULUM", "Satışı yapılan araç telsizi sisteminin teslimi ve kurulumu", 1, "PLANLANDI", ["t_tek_hab", "t_sef_hab"]),
    ("2026-10-17", "ZİRAAT BANKASI", "İstanbul Finans Merkezi", "İstanbul", "KURULUM", "İlave telsiz sistemi kurulumu ve devreye alma", 1, "PLANLANDI", ["t_tek_hab"]),
    ("2026-07-10", "ENERYA", "Erzincan", "Erzincan", "DEMONTAJ", "Röle ve anten demontajı", 1, "PLANLANDI", ["t_tek_hab", "t_sef_hab"]),
    ("2026-06-29", "İBB İTFAİYE", "Florya İtfaiye Merkezi", "İstanbul", "KURULUM", "Telsiz sistemleri anten montajı", 1, "TAMAMLANDI", ["t_tek_hab"]),
]
BARIYER_ISLER = [
    ("2026-09-12", "FİRSTGATE ORGANİZASYON", "Toyota Fabrikası", "Sakarya", "KURULUM", "650 m kiralık polis bariyeri + 60 tekno bariyer teslimi ve kurulumu", 1, "PLANLANDI", ["t_sef_bar"]),
    ("2026-09-12", "FİRSTGATE ORGANİZASYON", "Toyota Fabrikası", "Sakarya", "TOPLAMA", "650 m polis bariyeri + 60 tekno bariyer toplama/iade alma", 1, "MUSTERI_TALEBI", ["t_sef_bar"]),
    ("2026-06-19", "ZEUS MEDYA", "İstanbul Park Kurtköy", "İstanbul", "TASIMA", "24 kiralık akordiyon bariyerin İstanbul Park'a taşınması", 1, "PLANLANDI", ["t_sef_bar"]),
]


def yukle_temsili(isler, sirket, birim, rol, musteri_yedek, mevcut, liste, kuru):
    av = AnaVeri(sirket, rol, musteri_yedek, musteri_yedek)
    for tarih, firma, tesis, il, tur, konu, adet, hedef, tek in isler:
        for n in range(1, adet + 1):
            anahtar = f"{birim}:{tarih}:{firma}:{tur}:{n}"
            if anahtar in mevcut:
                continue
            ek = f" (cihaz {n}/{adet})" if adet > 1 else ""
            k = f"{firma} {tesis} — {konu}{ek}"[:200]
            if kuru:
                print(birim, anahtar, k)
                continue
            hid, lok = av.musteri(firma, il, tesis)
            j, kim = is_ac([rol], sirket, {
                "birim": birim, "tur": tur, "konu": k, "customer_id": hid, "address_id": lok, "talep_kanali": "TELEFON",
                "aciklama": f"Temsilî iş: Denge_Is_Plani_Analizi 'Tüm İşler' {tarih} satırından türetildi.",
            })
            hd, _, neden = hedef.partition(":")
            kayit(liste, anahtar=anahtar, no=j["so_no"], id=j["id"], sirket=sirket, birim=birim, tur=tur, konu=k,
                  musteri=firma, musteri_id=hid, lokasyon_id=lok, acan=kim, kaynak=f"Denge_Is_Plani_Analizi {tarih}",
                  hedef={"durum": hd, **({"neden": neden} if neden else {})}, plan=None,
                  eslenen_teknisyen=tek, cihaz_sira=f"{n}/{adet}")
            print(j["so_no"], birim, tur, k[:80])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bolum", default="hepsi", choices=["A", "B", "TELEKOM", "BARIYER", "hepsi"])
    ap.add_argument("--kuru", action="store_true", help="Yalnız planı yazdır, API'ye yazma")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    liste = json.loads(CIKTI.read_text(encoding="utf-8"))["isler"] if CIKTI.exists() else []
    mevcut = {x["anahtar"]: x for x in liste}
    satirlar = talep_satirlari()
    adlar = ad_sozcukleri([s["personel"] for s in satirlar])
    esleme = TeknisyenEsleme(["t_tek_guv1", "t_tek_guv2", "t_sef_guv"])
    for s in satirlar:  # eşleme sırası satır sırasından bağımsız olsun (tekrar çalıştırmada aynı)
        esleme.esle(s["personel"])

    if a.bolum in ("A", "hepsi"):
        yukle_a(satirlar, adlar, esleme, mevcut, liste, a.kuru)
    if a.bolum in ("B", "hepsi"):
        yukle_b(satirlar, adlar, esleme, mevcut, liste, a.kuru)
    if a.bolum in ("TELEKOM", "hepsi"):
        yukle_temsili(TELEKOM_ISLER, "TELEKOM", "HABERLESME", "t_ops_hab", ["t_yon_hab"], mevcut, liste, a.kuru)
    if a.bolum in ("BARIYER", "hepsi"):
        yukle_temsili(BARIYER_ISLER, "ELEKTRONIK", "BARIYER", "t_sef_bar", ["t_yon_guv"], mevcut, liste, a.kuru)

    if not a.kuru:
        veri = {"aciklama": ACIKLAMA, "isler": liste}
        olay = CIKTI.with_name("acilan_isler_olaylar.json")
        onceki = json.loads(olay.read_text(encoding="utf-8")) if olay.exists() else {"yetki_olaylari": [], "uyarilar": []}
        onceki["yetki_olaylari"] += YETKI_OLAYLARI
        onceki["uyarilar"] += UYARILAR
        olay.write_text(json.dumps(onceki, ensure_ascii=False, indent=1), encoding="utf-8")
        CIKTI.write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Yetki olayı: {len(YETKI_OLAYLARI)}, uyarı: {len(UYARILAR)}")


if __name__ == "__main__":
    main()
