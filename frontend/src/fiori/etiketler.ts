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
  yetkinlikUyarisiylaTayinEdildi: "Yetkinlik uyarısıyla tayin edildi",
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
  BEKLEMEDE: "İŞLEM-ARA VERİLDİ",
  TAMAMLANDI: "TAMAMLANDI",
  KAPATILDI: "TAMAMLANDI-KAPATILDI",
  IPTAL: "YAPILAMADI-İPTAL",
};

/**
 * Durum etiketi; beklemedeki iş, bekleme nedeni biliniyorsa "ASKIDA-<NEDEN>"
 * olarak yazılır (fotoğraf 1: "ASKIDA-DİĞER BİRİM İLERLEME").
 */
export function servisDurumEtiketi(kod: string, beklemeNedeni?: string | null): string {
  if (kod === "BEKLEMEDE" && beklemeNedeni) return `ASKIDA-${beklemeNedeni.toLocaleUpperCase("tr")}`;
  return SERVIS_DURUM_ETIKETLERI[kod] ?? kod.replaceAll("_", " ");
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
