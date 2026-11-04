/**
 * Fiori gösterim sözlüğü — durum/tür etiketleri ve "tayin" terimleri TEK yerde
 * (analiz/FIORI_TASARIM_REHBERI.md §3, §5).
 *
 * Yalnız GÖRÜNEN metindir: kod sabitleri, API alanları, izin ve olay kodları
 * (ör. `ATAMA`) değişmez. Durum kodları `backend/app/models/teknik_servis.py`
 * `SERVIS_DURUMLARI` kataloğundan; gruplar `DURUM_GRUPLARI` kümeleriyle
 * çakışmayacak biçimde (her kod tek gruba) eşlenmiştir.
 */

/** "Atama" yerine SAP dilindeki "tayin" terimleri (rehber §5). */
export const TAYIN = {
  tayinEt: "Tayin Et",
  tayinEdildi: "Tayin Edildi",
  tayinEdilmemis: "Tayin Edilmemiş",
  tayin: "Tayin",
  topluTayin: "Toplu Tayin",
  tayiniDegistir: "Tayini Değiştir",
  yenidenTayinEt: "Yeniden Tayin Et",
  tayinEdilebilirPersonel: "Tayin edilebilir personel",
  tayinEdilen: "Tayin edilen",
  tayinEdilenEkip: "Tayin edilen ekip",
  tayiniKaldir: "Tayini Kaldır",
  banaTayinEdilenler: "Bana Tayin Edilenler",
  vekilTayini: "Vekil Tayini",
  // Rol testi tur 2 (§7.12): uyarı yalnız yetkinlik değil, "ekipte sonuç
  // girebilecek kimse yok" da olabilir; başlık ikisini de kapsar.
  yetkinlikUyarisiylaTayinEdildi: "Tayin edildi — dikkat edilecekler",
  ekipTayini: "Ekip Tayini",
  planlaVeTayinEt: "Planla + Tayin Et",
} as const;

/** Servis işi durum kodu → SAP tarzı BÜYÜK HARF gösterim etiketi (rehber §5). */
export const SERVIS_DURUM_ETIKETLERI: Record<string, string> = {
  MUSTERI_TALEBI: "YENİ KAYIT",
  TEKRAR_ACILDI: "YENİ KAYIT-TEKRAR AÇILDI",
  PLANLAMADA: "TAYİN BEKLİYOR",
  PLANLANDI: "TAYİN EDİLDİ",
  YOLA_CIKILDI: "İŞLEM-YOLA ÇIKILDI",
  SAHADA: "İŞLEM-SAHADA",
  ISLEMDE: "İŞLEM-BAŞLADI",
  ATOLYEDE: "İŞLEM-ATÖLYEDE",
  // Rol testi B9 (2026-11-04): durum çubuğundaki grup adıyla TEK terim ("ASKIDA").
  BEKLEMEDE: "ASKIDA",
  TAMAMLANDI: "TAMAMLANDI",
  KAPATILDI: "TAMAMLANDI-KAPATILDI",
  IPTAL: "YAPILAMADI-İPTAL",
};

/**
 * Bekleme nedeni kodu → ad. Sunucu kataloğunun (`VARSAYILAN_BEKLEME_NEDENLERI`)
 * ilk hâli; form verisi `bekleme_nedenleri` ekrandan seçilemeyen sistem
 * nedenlerini (BAKIM_UYGUNSUZLUK) döndürmediği için ham kod görünmesin diye
 * yedek olarak kullanılır. Katalogdaki ad her zaman önce gelir.
 */
export const BEKLEME_NEDENI_ADLARI: Record<string, string> = {
  MALZEME: "Malzeme bekleniyor",
  MUSTERI_ONAYI: "Müşteri onayı bekleniyor",
  TEKLIF: "Teklif onayı bekleniyor",
  MUSTERI_ERISIMI: "Müşteri/saha erişimi yok",
  PERSONEL: "Personel bekleniyor",
  BAKIM_UYGUNSUZLUK: "Bakım uygunsuzluğu giderilecek",
  DIS_SERVIS: "Dış servis/üretici bekleniyor",
  DIGER: "Diğer",
};

/** Bekleme nedeni adı: önce verilen katalog, sonra yerel sözlük, en son okunur kod. */
export function beklemeNedeniAdi(
  kod: string | null | undefined,
  katalog?: { kod: string; ad: string }[],
): string | null {
  if (!kod) return null;
  return katalog?.find((n) => n.kod === kod)?.ad ?? BEKLEME_NEDENI_ADLARI[kod] ?? kodOkunur(kod);
}

/** Bilinmeyen sunucu kodu için son çare: alt çizgi yerine boşluk (ham kod gösterilmez). */
export function kodOkunur(kod: string): string {
  return kod.replaceAll("_", " ");
}

/**
 * Durum etiketi; beklemedeki iş, bekleme nedeni biliniyorsa "ASKIDA-<NEDEN>"
 * olarak yazılır (fotoğraf 1: "ASKIDA-DİĞER BİRİM İLERLEME"). Neden kod ya da
 * ad olarak gelebilir; kod ise ada çevrilir.
 */
export function servisDurumEtiketi(kod: string, beklemeNedeni?: string | null): string {
  if (kod === "BEKLEMEDE" && beklemeNedeni) {
    const ad = BEKLEME_NEDENI_ADLARI[beklemeNedeni] ?? kodOkunur(beklemeNedeni);
    return `ASKIDA-${ad.toLocaleUpperCase("tr")}`;
  }
  return SERVIS_DURUM_ETIKETLERI[kod] ?? kodOkunur(kod);
}

export interface FioriDurumGrubu {
  kod: string;
  /** Durum çubuğundaki BÜYÜK HARF kısa ad. */
  ad: string;
  /** Liste süzgecinin `durum` değerleri (sunucu kodları). */
  durumlar: string[];
}

/** Durum filtre çubuğu: YENİ · TAYİN · İŞLEM · ASKIDA · TAMAMLANDI · YAPILAMADI. */
export const SERVIS_DURUM_GRUPLARI: FioriDurumGrubu[] = [
  { kod: "YENI", ad: "YENİ", durumlar: ["MUSTERI_TALEBI", "TEKRAR_ACILDI"] },
  { kod: "TAYIN", ad: "TAYİN", durumlar: ["PLANLAMADA", "PLANLANDI"] },
  { kod: "ISLEM", ad: "İŞLEM", durumlar: ["YOLA_CIKILDI", "SAHADA", "ISLEMDE", "ATOLYEDE"] },
  { kod: "ASKIDA", ad: "ASKIDA", durumlar: ["BEKLEMEDE"] },
  { kod: "TAMAMLANDI", ad: "TAMAMLANDI", durumlar: ["TAMAMLANDI", "KAPATILDI"] },
  { kod: "YAPILAMADI", ad: "YAPILAMADI", durumlar: ["IPTAL"] },
];

/** Planlı bakım çubuğu (fotoğraf 9: ASKIDA yok). */
export const BAKIM_DURUM_GRUPLARI: FioriDurumGrubu[] = SERVIS_DURUM_GRUPLARI.filter(
  (g) => g.kod !== "ASKIDA",
);

/** Seçili `durum` listesine birebir uyan grubun kodu (yoksa undefined). */
export function durumGrubuBul(
  gruplar: FioriDurumGrubu[],
  durumlar: string[] | undefined,
): string | undefined {
  if (!durumlar?.length) return undefined;
  const k = [...durumlar].sort().join(",");
  return gruplar.find((g) => [...g.durumlar].sort().join(",") === k)?.kod;
}

export type KategoriRengi = "kirmizi" | "yesil" | "mavi";

/** Servis türü → kategori şeridi etiketi ve rengi (arıza/plansız kırmızı, planlı yeşil). */
export const SERVIS_TUR_ETIKETLERI: Record<string, { ad: string; renk: KategoriRengi }> = {
  ARIZA: { ad: "ARIZA", renk: "kirmizi" },
  PLANSIZ_BAKIM: { ad: "BAKIM", renk: "kirmizi" },
  DESTEK: { ad: "DESTEK", renk: "kirmizi" },
  KURULUM: { ad: "KURULUM", renk: "yesil" },
  KESIF: { ad: "KEŞİF", renk: "yesil" },
  TOPLAMA: { ad: "TOPLAMA", renk: "yesil" },
  DEMONTAJ: { ad: "DEMONTAJ", renk: "yesil" },
  ATOLYE: { ad: "ATÖLYE", renk: "yesil" },
  // KARARLAR 2026-11-04 §2: Set Bariyer taşıma işi (yeni tür kodu).
  TASIMA: { ad: "TAŞIMA", renk: "yesil" },
  PB: { ad: "PLANLI BAKIM", renk: "yesil" },
};

/** Servis İşleri kategori sırası (PB ayrı ekranda: Planlı Bakım). */
export const SERVIS_KATEGORI_SIRASI = [
  "ARIZA",
  "PLANSIZ_BAKIM",
  "DESTEK",
  "KURULUM",
  "KESIF",
  "TOPLAMA",
  "DEMONTAJ",
  "TASIMA",
  "ATOLYE",
] as const;

/** Öncelik rozet metni (NORMAL gösterilmez). */
export const ONCELIK_ETIKETLERI: Record<string, string> = {
  KRITIK: "KRİTİK",
  YUKSEK: "YÜKSEK",
};
