/**
 * Bakım fişi / onarım fişi "PDF indir" düğmesi (KARARLAR 2026-11-09 S6).
 *
 * Bakım fişi PB ve plansız bakım işinde, onarım fişi arıza ve atölye işinde
 * görünür (sunucu başka türde 409 döner). Fiyatlı seçenek yalnız tutar
 * görebilene (`teklif.gor` / `maliyet.gor`) sunulur; sunucu da aynı kuralı
 * uygular ve yetkisizde fiyatsız basar.
 */
import { FilePdfOutlined } from "@ant-design/icons";
import { Button, Dropdown } from "antd";

import { teknikServisApi } from "../api/teknikServis";

export type FisTuru = "bakim" | "onarim";

export function fisTuru(tur: string | null | undefined): FisTuru | null {
  if (tur === "PB" || tur === "PLANSIZ_BAKIM") return "bakim";
  // 2026-11-24: onarım fişi (cihaz tablosuyla) bakım dışındaki her işte.
  return tur ? "onarim" : null;
}

interface Props {
  id: number;
  tur: FisTuru;
  fiyatli: boolean;
  etiket?: boolean;
}

export default function ServisFisiDugmesi({ id, tur, fiyatli, etiket = true }: Props) {
  const yol = (f: boolean) =>
    tur === "bakim" ? teknikServisApi.bakimFisiYolu(id, f) : teknikServisApi.onarimFisiYolu(id, f);
  const ad = tur === "bakim" ? "Bakım fişi" : "Onarım fişi";
  if (!fiyatli) {
    return (
      <Button icon={<FilePdfOutlined />} href={yol(false)} target="_blank" aria-label={ad}>
        {etiket ? ad : ""}
      </Button>
    );
  }
  return (
    <Dropdown
      menu={{
        items: [
          { key: "f", label: `${ad} (fiyatsız)` },
          { key: "p", label: `${ad} (fiyatlı)` },
        ],
        onClick: ({ key }) => window.open(yol(key === "p"), "_blank"),
      }}
    >
      <Button icon={<FilePdfOutlined />} aria-label={ad}>
        {etiket ? ad : ""}
      </Button>
    </Dropdown>
  );
}
