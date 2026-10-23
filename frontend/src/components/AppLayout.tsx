/**
 * Oturumlu uygulamanın çerçevesi.
 *
 * Sol kenar menüsü KALDIRILDI (SAP Fiori görünümü, rehber §1): çerçeve artık
 * `fiori/Kabuk` (shell bar) ve gezinme Başlangıç sayfası (launchpad) ile
 * başlıktaki açılır menüden yapılır. Eski menüdeki her sayfa
 * `fiori/uygulamalar.ts` kataloğunda aynı yol ve izinle bir kutucuktur.
 *
 * `MENU` ve `acilisYolu` geriye uyumluluk için buradan da dışa verilir.
 */
import type { ReactNode } from "react";
import { createElement } from "react";

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
  return <Kabuk />;
}
