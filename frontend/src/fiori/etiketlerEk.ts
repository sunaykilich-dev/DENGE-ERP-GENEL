/**
 * Fiori gösterim sözlüğü — teknik servisin diğer liste ekranları (Paket D).
 *
 * `etiketler.ts` servis işleri içindir; burada atölye, kiralama, ekipman,
 * yedek parça, eğitim, personel ve operasyon ekranlarının kategori şeridi ve
 * durum çubuğu eşlemeleri durur. Yalnız GÖRÜNEN metin: kodlar sunucunun
 * kataloglarıyla birebir aynıdır, gruplama süzgeç değerlerini değiştirmez.
 */
import type { FioriDurumGrubu, KategoriRengi } from "./etiketler";

// --- Atölye (ATOLYE_DURUMLARI, ATOLYE_SERVIS_TURLERI) -------------------------

/** Atölye durum çubuğu: YENİ · İŞLEM · ASKIDA · TAMAMLANDI · YAPILAMADI. */
export const ATOLYE_DURUM_GRUPLARI: FioriDurumGrubu[] = [
  { kod: "YENI", ad: "YENİ", durumlar: ["KABUL_EDILDI"] },
  { kod: "ISLEM", ad: "İŞLEM", durumlar: ["TESHISTE", "ONARIMDA", "TEST_KONTROL"] },
  { kod: "ASKIDA", ad: "ASKIDA", durumlar: ["ONAY_BEKLIYOR", "PARCA_BEKLIYOR", "DIS_SERVISTE"] },
  { kod: "TAMAMLANDI", ad: "TAMAMLANDI", durumlar: ["TESLIME_HAZIR", "KARGOYA_VERILDI", "TESLIM_EDILDI"] },
  { kod: "YAPILAMADI", ad: "YAPILAMADI", durumlar: ["ONARILMADAN_IADE", "IPTAL"] },
];

/** Atölye durum kodu → SAP tarzı etiket (sunucu adı yoksa). */
export const ATOLYE_DURUM_ETIKETLERI: Record<string, string> = {
  KABUL_EDILDI: "YENİ KAYIT",
  TESHISTE: "İŞLEM-TEŞHİS",
  ONAY_BEKLIYOR: "ASKIDA-ONAY BEKLİYOR",
  ONARIMDA: "İŞLEM-BAŞLADI",
  PARCA_BEKLIYOR: "ASKIDA-PARÇA BEKLİYOR",
  DIS_SERVISTE: "ASKIDA-DIŞ SERVİS",
  TEST_KONTROL: "İŞLEM-TEST",
  TESLIME_HAZIR: "TAMAMLANDI-TESLİME HAZIR",
  ONARILMADAN_IADE: "YAPILAMADI-İADE",
  KARGOYA_VERILDI: "TAMAMLANDI-KARGODA",
  TESLIM_EDILDI: "TAMAMLANDI-TESLİM EDİLDİ",
  IPTAL: "YAPILAMADI-İPTAL",
};

export const ATOLYE_TUR_RENGI: Record<string, KategoriRengi> = {
  ARIZA_ONARIMI: "kirmizi",
  GARANTI_ONARIMI: "kirmizi",
  DIS_SERVIS: "kirmizi",
  YAZILIM_FREKANS: "yesil",
  KIRALAMA_TAKIP: "yesil",
};

// --- Kiralama (KIRALAMA_DURUMLARI; sunucu tek `durum` alır) --------------------

/** Kiralama durumu → durum çubuğu kısa adı (her düğme tek durum). */
export const KIRALAMA_DURUM_KISA: Record<string, string> = {
  TALEP: "YENİ",
  PLANLANDI: "TAYİN",
  HAZIRLANIYOR: "HAZIRLIK",
  SEVK_EDILDI: "SEVK",
  KURULUM_YAPILDI: "KURULUM",
  DEVREYE_ALINDI: "DEVREDE",
  TOPLANDI: "TOPLANDI",
  DEPOYA_ALINDI: "DEPODA",
  KAPANDI: "TAMAMLANDI",
  IPTAL: "YAPILAMADI",
};

/** Kiralama durum hücresi etiketi. */
export const KIRALAMA_DURUM_ETIKETLERI: Record<string, string> = {
  TALEP: "YENİ KAYIT",
  PLANLANDI: "TAYİN EDİLDİ",
  HAZIRLANIYOR: "İŞLEM-HAZIRLANIYOR",
  SEVK_EDILDI: "İŞLEM-SEVK EDİLDİ",
  KURULUM_YAPILDI: "İŞLEM-KURULUM YAPILDI",
  DEVREYE_ALINDI: "İŞLEM-DEVREDE",
  TOPLANDI: "İŞLEM-TOPLANDI",
  DEPOYA_ALINDI: "İŞLEM-DEPOYA ALINDI",
  KAPANDI: "TAMAMLANDI",
  IPTAL: "YAPILAMADI-İPTAL",
};

/** Ortak "yeni/aktif/pasif" türü kısa adları için yardımcı. */
export function tekliGrup(kod: string, ad: string): FioriDurumGrubu {
  return { kod, ad, durumlar: [kod] };
}
