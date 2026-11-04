/**
 * Oturumlu uygulamanın çerçevesi.
 *
 * KARARLAR 2026-11-04 §2: Logo CRM kurgusu — `fiori/Kabuk` koyu üst çubuk
 * (şirket seçici, arama, hızlı oluştur) ve sol akordeon menü (`fiori/menu.ts`).
 * Etkin şirket (`SirketProvider`) kabuğun ve bütün sayfaların üstündedir;
 * menü ve sayfalar `useSirket()` ile okur.
 *
 * `MENU` ve `acilisYolu` geriye uyumluluk için buradan da dışa verilir.
 */
import type { ReactNode } from "react";
import { createElement } from "react";

import { SirketProvider } from "../auth/SirketContext";
import Kabuk from "../fiori/Kabuk";
import { SAYFALAR } from "../fiori/uygulamalar";

export { acilisGrubu, acilisYolu } from "../fiori/uygulamalar";

export interface MenuKalemi {
  key: string;
  label: string;
  icon: ReactNode;
  /** Tek izin ya da "bunlardan herhangi biri" listesi. */
  izin: string | string[];
  grup?: string;
}

/** Eski sol menünün karşılığı: katalogdaki sayfa kutucukları (yol + izin aynı). */
export const MENU: MenuKalemi[] = SAYFALAR.map((u) => ({
  key: u.yol,
  label: u.baslik,
  icon: createElement(u.ikon),
  izin: u.izin,
  grup: u.grup,
}));

export default function AppLayout() {
  return (
    <SirketProvider>
      <Kabuk />
    </SirketProvider>
  );
}
