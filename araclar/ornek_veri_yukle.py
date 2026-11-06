"""Yerel deneme veritabanına örnek teknik servis verisi yükler (yalnız geliştirme).

Çalışan API üzerinden (http://127.0.0.1:8000) yönetici hesabıyla gider; böylece
yükleme de uçların gerçekten çalıştığını sınar. Yönetici parolası
.yerel_gizli/deneme_admin.txt dosyasından okunur.

Kullanım (denge-erp-deneme/backend içinde):  uv run python ..\\..\\araclar\\ornek_veri_yukle.py
"""

import datetime as dt
import sys
from pathlib import Path

import httpx

KOK = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8000/api"
TS = f"{API}/teknik-servis"


def parola() -> str:
    for satir in (KOK / ".yerel_gizli" / "deneme_admin.txt").read_text(encoding="utf-8").splitlines():
        if satir.startswith("sifre="):
            return satir.split("=", 1)[1].strip()
    raise SystemExit("deneme_admin.txt içinde parola yok")


def kontrol(r: httpx.Response, ne: str):
    if r.status_code >= 400:
        print(f"HATA {ne}: {r.status_code} {r.text[:600]}")
        sys.exit(1)
    return r.json() if r.content else None


def main() -> None:
    c = httpx.Client(headers={"X-Requested-With": "fetch"}, timeout=60)
    eski = parola()
    kontrol(c.post(f"{API}/auth/login", json={"username": "admin", "password": eski}), "giriş")
    # İlk girişte parola değişimi zorunlu (TS-212); yeni parola dosyaya yazılır.
    if c.get(f"{API}/auth/me").json().get("parola_degismeli"):
        import secrets

        yeni = "Dn-" + secrets.token_urlsafe(14)
        kontrol(c.post(f"{API}/auth/parola", json={"mevcut": eski, "yeni": yeni}), "parola değiştir")
        dosya = KOK / ".yerel_gizli" / "deneme_admin.txt"
        dosya.write_text(dosya.read_text(encoding="utf-8").replace(eski, yeni), encoding="utf-8")
        kontrol(c.post(f"{API}/auth/login", json={"username": "admin", "password": yeni}), "yeniden giriş")

    kullanicilar = kontrol(c.get(f"{API}/kullanicilar", params={"limit": 200}), "kullanıcılar")
    if isinstance(kullanicilar, dict):
        kullanicilar = kullanicilar.get("items") or kullanicilar.get("kayitlar") or []
    kim = {k["username"]: k["id"] for k in kullanicilar}
    sef, tek = kim["servis_sef"], kim["servis_teknisyen"]

    musteriler = [
        ("AKYAKA AVM YÖNETİMİ", "İstanbul", "Akyaka AVM", "Bayrampaşa", "Abdi İpekçi Cd. No:1", 3, 2),
        ("EGE LİMAN İŞLETMESİ A.Ş.", "İzmir", "Alsancak Yolcu Salonu", "Konak", "Liman Cd. No:12", 2, 2),
        ("BAŞKENT ADLİYE SARAYI", "Ankara", "Ana Bina Girişi", "Sıhhiye", "Adliye Sk. No:3", 1, 3),
    ]
    sonuc: list[dict] = []
    # Yalnız işleri yükle: ORNEK_ISLER="hesap:lokasyon,hesap:lokasyon,hesap:lokasyon"
    import os

    if os.getenv("ORNEK_ISLER"):
        for parca in os.environ["ORNEK_ISLER"].split(","):
            h, lok = (int(x) for x in parca.split(":"))
            sonuc.append({"unvan": "?", "hesap_id": h, "lok_id": lok})
        musteriler = []
    for unvan, il, tesis, ilce, adres, xray, kapi in musteriler:
        m = kontrol(
            c.post(f"{TS}/ana-veri/hizli-musteri", json={"unvan": unvan, "il": il, "tesis_adi": tesis, "onay_benzer": True}),
            f"müşteri {unvan}",
        )
        hesap_id = m.get("hesap_id") or m.get("id") or m["hesap"]["id"]
        lok_id = m.get("lokasyon_id") or (m.get("lokasyon") or {}).get("id") or m.get("address_id")
        if lok_id:
            surum = kontrol(c.get(f"{API}/lokasyonlar/{lok_id}"), "lokasyon oku")["version"]
            kontrol(c.patch(f"{API}/lokasyonlar/{lok_id}", json={"version": surum, "line": adres, "district": ilce, "city": il, "access_note": "Güvenlik amirliğine haber verilecek; otopark B2."}), "lokasyon adres")
            kontrol(c.post(f"{API}/lokasyonlar/{lok_id}/kisiler", json={"full_name": f"{tesis} Teknik Sorumlusu", "title": "Teknik Sorumlu", "phone": "0 555 000 00 00", "lokasyon_birincil": True}), "irtibat")
        ekip: dict[str, list[int]] = {"XRAY": [], "KAPI_DEDEKTORU": []}
        for tip, adet, marka, model, onek in (("XRAY", xray, "Smiths Detection", "HI-SCAN 6040", "XR"), ("KAPI_DEDEKTORU", kapi, "CEIA", "HI-PE Plus", "MD")):
            for i in range(1, adet + 1):
                e = kontrol(
                    c.post(f"{TS}/ekipman", json={
                        "birim": "GUVENLIK", "equipment_type": tip, "account_id": hesap_id, "address_id": lok_id,
                        "brand": marka, "model": model, "serial_no": f"{onek}-{hesap_id:03d}-{i:02d}",
                        "zone": f"Giriş {i}", "install_date": "2024-03-01", "warranty_start": "2024-03-01",
                        "warranty_end": "2026-03-01", "lifecycle_status": "KURULU",
                    }),
                    f"ekipman {tip}",
                )
                ekip[tip].append(e["id"])
        sonuc.append({"unvan": unvan, "hesap_id": hesap_id, "lok_id": lok_id, "ekip": ekip})

    # Bakım sözleşmesi: ilk iki müşteri, yılda 2 bakım, tüm cihazlar eşleşik.
    for s in [x for x in sonuc[:2] if "ekip" in x]:
        soz = kontrol(c.post(f"{TS}/bakim/sozlesmeler", json={
            "birim": "GUVENLIK", "account_id": s["hesap_id"], "address_id": s["lok_id"],
            "baslangic": "2026-01-01", "bitis": "2027-01-01", "annual_frequency": 2,
            "kapsam": {t: len(v) for t, v in s["ekip"].items()},
        }), "sözleşme")
        kontrol(c.post(f"{TS}/bakim/sozlesmeler/{soz['id']}/durum", json={"hedef": "AKTIF"}), "sözleşme aktif")
        es = kontrol(c.get(f"{TS}/bakim/sozlesmeler/{soz['id']}/eslestirme"), "eşleştirme oku")
        havuz = {t: list(v) for t, v in s["ekip"].items()}
        satirlar = [{"kalem_id": k["kalem_id"], "equipment_id": havuz[k["equipment_type"]].pop(0)}
                    for k in es["kalemler"] if k["equipment_id"] is None and havuz.get(k["equipment_type"])]
        kontrol(c.put(f"{TS}/bakim/sozlesmeler/{soz['id']}/eslestirme", json={"eslesmeler": satirlar}), "eşleştir")
        s["sozlesme_id"] = soz["id"]
    if not os.getenv("ORNEK_ISLER"):
        r = c.post(f"{TS}/bakim/uretim")
        print("PB üretimi:", r.status_code, r.text[:300])

    # Servis işleri.
    bugun = dt.date.today()
    isler = [
        (sonuc[0], "ARIZA", "KRITIK", "Giriş 1 X-Ray bant durdu", ["XR-%03d-01" % sonuc[0]["hesap_id"]], bugun),
        (sonuc[1], "ARIZA", "YUKSEK", "Kapı dedektörü sürekli alarm veriyor", ["MD-%03d-02" % sonuc[1]["hesap_id"]], bugun + dt.timedelta(days=1)),
        (sonuc[2], "ARIZA", "NORMAL", "X-Ray monitörde görüntü kayması", ["XR-%03d-01" % sonuc[2]["hesap_id"]], None),
        (sonuc[2], "KESIF", "NORMAL", "Yeni kapı dedektörü yerleşimi için keşif", [], None),
    ]
    for s, tur, onc, konu, seriler, plan in isler:
        j = kontrol(c.post(f"{TS}/isler", json={
            "birim": "GUVENLIK", "tur": tur, "oncelik": onc, "konu": konu, "customer_id": s["hesap_id"],
            "address_id": s["lok_id"], "talep_kanali": "TELEFON", "seriler": seriler, "mukerrer_gec": True,
            "iletisim_ad": "Tesis Teknik Sorumlusu", "iletisim_telefon": "0 555 000 00 00",
        }), f"iş {konu}")
        if plan:
            kontrol(c.put(f"{TS}/planlama/isler/{j['id']}/plan", json={
                "plan_tarihi": plan.isoformat(), "baslangic_saati": "10:00", "sure_dk": 120,
                "ekip": {"sef_idler": [sef], "teknisyen_idler": [tek], "sorumlu_id": tek},
                "plan_notu": "Örnek veri", "cakisma_gerekcesi": "Örnek veri",
            }), f"plan {konu}")
        print("İş:", j.get("no") or j.get("so_no") or j["id"], konu, "planlandı" if plan else "havuzda")
    print("Tamam:", [(s["unvan"], s["hesap_id"]) for s in sonuc])


if __name__ == "__main__":
    main()
