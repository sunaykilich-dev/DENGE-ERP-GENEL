/**
 * Fiori kategori ikon şeridi (rehber §3.1, fotoğraf 0–6 ve 9): dairesel ikon
 * düğmeler + BÜYÜK HARF kısa etiket. Kırmızı = arıza/plansız, yeşil = planlı.
 * Seçili kategori dolu daire ve altında 3 px renkli çizgiyle gösterilir.
 */
import { ToolOutlined } from "@ant-design/icons";
import type { ReactNode } from "react";

import type { KategoriRengi } from "./etiketler";
import "./fiori.css";

export interface FioriKategori {
  kod: string;
  /** BÜYÜK HARF kısa etiket (ör. ARIZA). */
  ad: string;
  renk: KategoriRengi;
  /** Varsayılan anahtar ikonu. */
  ikon?: ReactNode;
  /** Uzun ad / açıklama (ipucu). */
  ipucu?: string;
  /** İsteğe bağlı sayı rozeti. */
  sayi?: number | null;
}

export default function KategoriSeridi({
  kategoriler,
  secili,
  onSec,
}: {
  kategoriler: FioriKategori[];
  secili?: string;
  onSec: (kod: string) => void;
}) {
  return (
    <div className="fl-kategori-seridi" role="tablist" aria-label="Kategoriler">
      {kategoriler.map((k) => {
        const s = k.kod === secili;
        return (
          <button
            key={k.kod}
            type="button"
            role="tab"
            aria-selected={s}
            title={k.ipucu ?? k.ad}
            className={`fl-kategori ${k.renk}${s ? " secili" : ""}`}
            onClick={() => onSec(k.kod)}
          >
            <span className="fl-kategori-daire">{k.ikon ?? <ToolOutlined />}</span>
            <span className="fl-kategori-ad">{k.ad}</span>
            {k.sayi != null && k.sayi > 0 && <span className="fl-kategori-sayi">{k.sayi}</span>}
          </button>
        );
      })}
    </div>
  );
}
