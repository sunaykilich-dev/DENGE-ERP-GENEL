/** Elle seri girişinin sabit neden listesi (sunucu: `seri_okutma.ELLE_GEREKCE_ADLARI`). */
import type { OkumaKaynagi } from "./okuyucuAlgilama";

export const ELLE_GEREKCELERI = [
  { kod: "ETIKET_YOK", ad: "Etiket yok / okunmuyor" },
  { kod: "CIHAZ_YANINDA_DEGIL", ad: "Cihaz yanımda değil (telefonla açılan iş)" },
  { kod: "DIGER", ad: "Diğer" },
] as const;

export type ElleGerekce = (typeof ELLE_GEREKCELERI)[number]["kod"];

/** Sunucuya giden okuma (`SeriOkumaIn`). */
export interface SeriOkumasi {
  seri_no: string;
  okuma_kaynagi: OkumaKaynagi;
  elle_gerekce?: ElleGerekce | null;
  elle_aciklama?: string | null;
}

/** Ekranda bir okumanın etiketi: "Okutuldu" / "Elle: <neden>". */
export function okumaEtiketi(o: { okuma_kaynagi?: string | null; elle_gerekce?: string | null; elle_aciklama?: string | null }) {
  if (o.okuma_kaynagi === "OKUTMA") return "Okutuldu";
  if (o.okuma_kaynagi === "ELLE") {
    if (o.elle_gerekce === "DIGER" && o.elle_aciklama) return `Elle: ${o.elle_aciklama}`;
    return `Elle: ${ELLE_GEREKCELERI.find((g) => g.kod === o.elle_gerekce)?.ad ?? "neden yok"}`;
  }
  return null;
}
