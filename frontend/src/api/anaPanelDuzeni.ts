/**
 * Ana Panel düzeni — kişisel ve rol varsayılanı (KARARLAR 2026-11-09 S8).
 *
 * Sunucu: `backend/app/api/ana_panel_duzeni.py`, kural
 * `backend/app/services/ana_panel_duzeni.py` (bileşen kaydı TEK kaynak).
 * Katalog sunucuda kullanıcının izinleriyle süzülür; ön yüz yalnız çizer.
 * Kayıtta `version` iyimser kilittir (ilk kayıtta null); 409 = başka bir
 * sekmede/cihazda değişti.
 */
import { api } from "./client";

const YOL = "/api/ana-panel";

export type Boyut = "DAR" | "GENIS";

export interface DuzenOgesi {
  kod: string;
  boyut: Boyut;
  gorunur: boolean;
}

export interface KatalogOgesi {
  kod: string;
  ad: string;
  aciklama: string;
  grup: string;
  /** "gosterge" (tek sayı) | "kart" (liste/grafik). */
  tur: "gosterge" | "kart";
  varsayilan_boyut: Boyut;
  /** Verinin geldiği uç: "servis" (`/api/teknik-servis/ana-panel`) | "teklif". */
  veri: string;
}

/** KULLANICI = kişisel düzen; ROL = rol varsayılanı; SISTEM = bugünkü panel. */
export type DuzenKaynagi = "KULLANICI" | "ROL" | "SISTEM";

export interface DuzenYaniti {
  kaynak: DuzenKaynagi;
  version: number | null;
  bilesenler: DuzenOgesi[];
  varsayilan: { kaynak: DuzenKaynagi; bilesenler: DuzenOgesi[] };
  katalog: KatalogOgesi[];
  rol_duzenleyebilir: boolean;
}

export interface RolSatiri {
  rol_kodu: string;
  rol_adi: string;
  ozel: boolean;
  version: number | null;
}

export interface RolDuzenYaniti {
  rol_kodu: string;
  rol_adi: string;
  kaynak: "ROL" | "SISTEM";
  version: number | null;
  bilesenler: DuzenOgesi[];
  sistem_varsayilani: DuzenOgesi[];
  katalog: KatalogOgesi[];
}

const surumParam = (v: number | null) => (v == null ? "" : `?version=${v}`);

export const anaPanelDuzeniApi = {
  getir: () => api.get<DuzenYaniti>(`${YOL}/duzen`),
  kaydet: (bilesenler: DuzenOgesi[], version: number | null) =>
    api.put<DuzenYaniti>(`${YOL}/duzen`, { bilesenler, version }),
  /** "Varsayılana dön": kişisel düzen silinir. */
  sifirla: (version: number | null) => api.delete<DuzenYaniti>(`${YOL}/duzen${surumParam(version)}`),

  roller: () => api.get<RolSatiri[]>(`${YOL}/rol-duzenleri`),
  rolGetir: (rol: string) => api.get<RolDuzenYaniti>(`${YOL}/rol-duzenleri/${encodeURIComponent(rol)}`),
  rolKaydet: (rol: string, bilesenler: DuzenOgesi[], version: number | null) =>
    api.put<RolDuzenYaniti>(`${YOL}/rol-duzenleri/${encodeURIComponent(rol)}`, { bilesenler, version }),
  rolSifirla: (rol: string, version: number | null) =>
    api.delete<RolDuzenYaniti>(`${YOL}/rol-duzenleri/${encodeURIComponent(rol)}${surumParam(version)}`),
};

export const DUZEN_SORGU_ANAHTARI = ["ana-panel-duzen"] as const;

// --- Saf düzen işlemleri (düzenleme kipi ve rol penceresi ortak) ----------------------------

export function tasi<T>(liste: T[], kaynak: number, hedef: number): T[] {
  if (kaynak === hedef || kaynak < 0 || hedef < 0 || kaynak >= liste.length || hedef >= liste.length) {
    return liste;
  }
  const yeni = [...liste];
  const [oge] = yeni.splice(kaynak, 1);
  yeni.splice(hedef, 0, oge);
  return yeni;
}

/** Katalogdan ekle: gizliyse görünür yapıp sona alır, yoksa varsayılan boyutla sona ekler. */
export function ekle(liste: DuzenOgesi[], k: KatalogOgesi): DuzenOgesi[] {
  const mevcut = liste.find((o) => o.kod === k.kod);
  const digerleri = liste.filter((o) => o.kod !== k.kod);
  return [...digerleri, { kod: k.kod, boyut: mevcut?.boyut ?? k.varsayilan_boyut, gorunur: true }];
}
