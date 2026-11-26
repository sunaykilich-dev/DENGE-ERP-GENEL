/**
 * Barkod okuyucuyla seri okutma (KARARLAR 2026-11-20 §2, §4).
 *
 * Klavye gibi çalışan okuyucular okuttuğunu yazıp Enter'a basar; ek sürücü
 * gerekmez. Enter formu GÖNDERMEZ, seriyi listeye ekler. Beklenen liste
 * verilirse okunanlar yeşil, beklenmeyenler kırmızı, eksikler ayrı gösterilir.
 * Karşılaştırma büyük/küçük harf, boşluk ve tireden bağımsızdır (sunucudaki
 * `normalize_seri` ile aynı fikir).
 *
 * 2026-11-23: kamera düğmesi (telefonla okutma) ve el okuyucu algılama
 * (`barkod/okuyucuAlgilama`): eklenen her serinin nasıl girildiği `onOkuma`
 * ile bildirilir (OKUTMA / ELLE).
 */
import { BarcodeOutlined } from "@ant-design/icons";
import { Input, Space, Tag, Typography, type InputRef } from "antd";
import { useRef, useState } from "react";

import { KameraDugmesi } from "./barkod/KameraOkuyucu";
import { useOkuyucuAlgilama, type OkumaKaynagi } from "./barkod/okuyucuAlgilama";

export function seriAnahtari(s: string): string {
  return s.toLocaleUpperCase("tr-TR").replace(/[\s\-_./]/g, "");
}

export function seriFarki(beklenen: string[], okunan: string[]) {
  const ok = new Set(okunan.map(seriAnahtari));
  const bek = new Set(beklenen.map(seriAnahtari));
  return {
    eksik: beklenen.filter((b) => !ok.has(seriAnahtari(b))),
    fazla: okunan.filter((o) => !bek.has(seriAnahtari(o))),
  };
}

export default function SeriOkutucu({
  value,
  onChange,
  beklenen,
  hedefAdet,
  placeholder = "Barkodu okutun ya da seriyi yazıp Enter'a basın",
  onOkundu,
  onOkuma,
  etiketler,
  disabled,
}: {
  value?: string[];
  onChange?: (v: string[]) => void;
  /** Karşılaştırılacak seriler (verilmezse yalnız liste tutulur). */
  beklenen?: string[];
  /** Seri listesi yerine adet karşılaştırması (hazırlık). */
  hedefAdet?: number;
  placeholder?: string;
  /** Okunan seri listeye eklenmeden önce: false dönerse eklenmez (ör. bulunamadı). */
  onOkundu?: (seri: string) => boolean | void;
  /** Listeye eklenen serinin nasıl girildiği (el okuyucu/kamera = OKUTMA). */
  onOkuma?: (seri: string, kaynak: OkumaKaynagi) => void;
  /** Etiketin yanında küçük not (ör. "Okutuldu" / "Elle"); anahtar `seriAnahtari`. */
  etiketler?: Record<string, string>;
  disabled?: boolean;
}) {
  const [metin, setMetin] = useState("");
  const giris = useRef<InputRef>(null);
  const liste = value ?? [];
  const { olaylar, kaynak } = useOkuyucuAlgilama();

  const ekle = (ham: string, k: OkumaKaynagi) => {
    const seri = ham.trim();
    setMetin("");
    if (!seri) return;
    if (liste.some((x) => seriAnahtari(x) === seriAnahtari(seri))) return; // ikinci okutma
    if (onOkundu?.(seri) === false) return;
    onOkuma?.(seri, k);
    onChange?.([...liste, seri]);
    giris.current?.focus();
  };

  const fark = beklenen ? seriFarki(beklenen, liste) : null;
  const fazlaKume = new Set((fark?.fazla ?? []).map(seriAnahtari));

  return (
    <Space orientation="vertical" style={{ width: "100%" }} size={6}>
      <Space.Compact style={{ width: "100%" }}>
        <Input
          ref={giris}
          prefix={<BarcodeOutlined />}
          value={metin}
          placeholder={placeholder}
          disabled={disabled}
          {...olaylar}
          onChange={(e) => setMetin(e.target.value)}
          onPressEnter={(e) => {
            e.preventDefault();
            ekle(metin, kaynak(metin, e.timeStamp));
          }}
          allowClear
          autoComplete="off"
        />
        <KameraDugmesi disabled={disabled} onOkundu={(m) => ekle(m, "OKUTMA")} />
      </Space.Compact>
      {liste.length > 0 && (
        <Space size={[4, 4]} wrap>
          {liste.map((s) => (
            <Tag
              key={s}
              color={fark ? (fazlaKume.has(seriAnahtari(s)) ? "red" : "green") : "blue"}
              closable={!disabled}
              onClose={() => onChange?.(liste.filter((x) => x !== s))}
            >
              {s}
              {etiketler?.[seriAnahtari(s)] && (
                <span style={{ marginLeft: 4, opacity: 0.7, fontSize: 11 }}>· {etiketler[seriAnahtari(s)]}</span>
              )}
            </Tag>
          ))}
        </Space>
      )}
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        Okunan: {liste.length}
        {hedefAdet != null && ` / istenen: ${hedefAdet}`}
        {beklenen && ` / beklenen: ${beklenen.length}`}
      </Typography.Text>
      {fark && fark.eksik.length > 0 && (
        <Typography.Text type="warning" style={{ fontSize: 12 }}>
          Okutulmayan: {fark.eksik.join(", ")}
        </Typography.Text>
      )}
      {fark && fark.fazla.length > 0 && (
        <Typography.Text type="danger" style={{ fontSize: 12 }}>
          Beklenmeyen: {fark.fazla.join(", ")}
        </Typography.Text>
      )}
      {hedefAdet != null && liste.length !== hedefAdet && liste.length > 0 && (
        <Typography.Text type={liste.length > hedefAdet ? "danger" : "warning"} style={{ fontSize: 12 }}>
          {liste.length > hedefAdet
            ? `İstenenden ${liste.length - hedefAdet} fazla okutuldu`
            : `${hedefAdet - liste.length} cihaz eksik`}
        </Typography.Text>
      )}
    </Space>
  );
}
