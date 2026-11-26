/**
 * Kişisel ekran kutucuk düzeni (2026-11-18). Sunucu: `backend/app/api/ekran_duzeni.py`.
 * `kutular: null` = kişisel düzen yok (ekran varsayılan sırayla çizer).
 */
import { api } from "./client";

export interface EkranKutusu {
  kod: string;
  gizli: boolean;
  boyut: "DAR" | "GENIS";
}

export interface EkranDuzeni {
  ekran: string;
  kutular: EkranKutusu[] | null;
}

const yol = (ekran: string) => `/api/ekran-duzeni/${ekran}`;

export const ekranDuzeniApi = {
  oku: (ekran: string) => api.get<EkranDuzeni>(yol(ekran)),
  kaydet: (ekran: string, kutular: EkranKutusu[]) => api.put<EkranDuzeni>(yol(ekran), { kutular }),
  sifirla: (ekran: string) => api.delete<EkranDuzeni>(yol(ekran)),
};
