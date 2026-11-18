/**
 * Kategori seçici. 2026-11-17 kullanıcı kararı: eski dairesel ikon şeridi
 * (TÜMÜ / ARIZA / BAKIM …) tüm ekranlardan kaldırıldı.
 *
 * - Servis İşleri: tür seçimi zaten sol menüde; şerit tamamen kaldırıldı,
 *   ekran kategori vermez.
 * - Kategorinin tek seçim yolu olduğu ekranlar (depo, birim, yıl, faaliyet…):
 *   aynı seçim "Kayıt Sayısı" satırında küçük bir açılır listeyle yapılır.
 *   Böylece işlev kaybolmaz, ekran sadeleşir (G1.9).
 *
 * API eski şeritle aynıdır (çağıranlar değişmez).
 * - `grup` verilirse her grup ayrı bir açılır liste olur.
 * - İçinde TÜMÜ (`kod: "TUMU"`) olan grup tek seçimlidir; diğer gruplar
 *   (Atölye durum sekmeleri) çok seçimlidir. Çok seçimlide her değişiklik
 *   `onSec(kod)` ile bildirilir (aç/kapa).
 * - `ayar` (görünür sekme seçimi) artık gerekmez: açılır listede yer sorunu
 *   yoktur. Prop geriye dönük uyum için kabul edilir.
 */
import { Select, Space } from "antd";
import { useMemo, type ReactNode } from "react";

import type { KategoriRengi } from "./etiketler";

export interface FioriKategori {
  kod: string;
  /** Kısa etiket (ör. ARIZA). */
  ad: string;
  renk: KategoriRengi;
  /** Eski şeridin ikonu; açılır listede kullanılmaz. */
  ikon?: ReactNode;
  /** Uzun ad / açıklama (ipucu). */
  ipucu?: string;
  /** İsteğe bağlı sayı: seçenekte parantez içinde gösterilir. */
  sayi?: number | null;
  /** Sayı 0 iken de göster ("0" da bilgidir). */
  sifirGoster?: boolean;
  /** Grup adı: her grup ayrı bir açılır liste olur. */
  grup?: string;
}

export interface KategoriAyari {
  kimlik: string;
  varsayilan?: string[];
  sabit?: string[];
}

const TUMU = "TUMU";

/** "ARIZA" → "Arıza" (açılır listede büyük harf bağırmasın). */
function okunur(ad: string): string {
  if (ad !== ad.toLocaleUpperCase("tr-TR")) return ad;
  return ad
    .toLocaleLowerCase("tr-TR")
    .replace(/(^|[\s/(—-])(\p{L})/gu, (_, on: string, h: string) => on + h.toLocaleUpperCase("tr-TR"));
}

function etiket(k: FioriKategori): string {
  const sayiGoster = k.sayi != null && (k.sayi > 0 || k.sifirGoster);
  return okunur(k.ad) + (sayiGoster ? ` (${k.sayi})` : "");
}

export default function KategoriSeridi({
  kategoriler,
  secili,
  onSec,
  baslik,
}: {
  kategoriler: FioriKategori[];
  secili?: string | string[];
  onSec: (kod: string) => void;
  /** Eski şeritle uyum; kullanılmaz. */
  ayar?: KategoriAyari;
  /** Tek gruplu listede yer tutucu (ör. "Depo"). */
  baslik?: string;
}) {
  const seciliKume = useMemo(
    () => new Set(Array.isArray(secili) ? secili : secili ? [secili] : []),
    [secili],
  );
  const gruplar = useMemo(() => {
    const g = new Map<string, FioriKategori[]>();
    for (const k of kategoriler) g.set(k.grup ?? "", [...(g.get(k.grup ?? "") ?? []), k]);
    return [...g.entries()];
  }, [kategoriler]);

  return (
    <Space size={8} wrap className="fl-kategori-secici">
      {gruplar.map(([grup, liste]) => {
        const secenekler = liste.map((k) => ({ value: k.kod, label: etiket(k), title: k.ipucu ?? k.ad }));
        const grupSecili = liste.filter((k) => seciliKume.has(k.kod)).map((k) => k.kod);
        const ad = grup || baslik || "Görünüm";
        const tekSecim = !Array.isArray(secili) || liste.some((k) => k.kod === TUMU) || !grup;
        if (tekSecim) {
          return (
            <Select
              key={grup || "_"}
              size="small"
              aria-label={ad}
              prefix={`${ad}:`}
              style={{ minWidth: 170 }}
              popupMatchSelectWidth={false}
              showSearch={{ optionFilterProp: "label" }}
              options={secenekler}
              value={grupSecili[0]}
              onChange={(kod: string) => onSec(kod)}
            />
          );
        }
        return (
          <Select
            key={grup}
            size="small"
            mode="multiple"
            aria-label={ad}
            prefix={`${ad}:`}
            placeholder="Seçin"
            style={{ minWidth: 190 }}
            maxTagCount="responsive"
            popupMatchSelectWidth={false}
            options={secenekler}
            value={grupSecili}
            onChange={(yeni: string[]) => {
              const yeniKume = new Set(yeni);
              for (const k of liste) {
                if (yeniKume.has(k.kod) !== seciliKume.has(k.kod)) onSec(k.kod);
              }
            }}
          />
        );
      })}
    </Space>
  );
}
