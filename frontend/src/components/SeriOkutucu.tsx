/**
 * Barkod okuyucuyla seri okutma (KARARLAR 2026-11-20 §2, §4).
 *
 * Klavye gibi çalışan okuyucular okuttuğunu yazıp Enter'a basar; ek sürücü
 * gerekmez. Enter formu GÖNDERMEZ, seriyi listeye ekler. Beklenen liste
 * verilirse okunanlar yeşil, beklenmeyenler kırmızı, eksikler ayrı gösterilir.
 * Karşılaştırma büyük/küçük harf, boşluk ve tireden bağımsızdır (sunucudaki
 * `normalize_seri` ile aynı fikir).
 */
import { BarcodeOutlined } from "@ant-design/icons";
import { Input, Space, Tag, Typography, type InputRef } from "antd";
import { useRef, useState } from "react";

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
}) {
  const [metin, setMetin] = useState("");
  const giris = useRef<InputRef>(null);
  const liste = value ?? [];

  const ekle = () => {
    const seri = metin.trim();
    setMetin("");
    if (!seri) return;
    if (liste.some((x) => seriAnahtari(x) === seriAnahtari(seri))) return; // ikinci okutma
    if (onOkundu?.(seri) === false) return;
    onChange?.([...liste, seri]);
    giris.current?.focus();
  };

  const fark = beklenen ? seriFarki(beklenen, liste) : null;
  const fazlaKume = new Set((fark?.fazla ?? []).map(seriAnahtari));

  return (
    <Space orientation="vertical" style={{ width: "100%" }} size={6}>
      <Input
        ref={giris}
        prefix={<BarcodeOutlined />}
        value={metin}
        placeholder={placeholder}
        onChange={(e) => setMetin(e.target.value)}
        onPressEnter={(e) => {
          e.preventDefault();
          ekle();
        }}
        allowClear
        autoComplete="off"
      />
      {liste.length > 0 && (
        <Space size={[4, 4]} wrap>
          {liste.map((s) => (
            <Tag
              key={s}
              color={fark ? (fazlaKume.has(seriAnahtari(s)) ? "red" : "green") : "blue"}
              closable
              onClose={() => onChange?.(liste.filter((x) => x !== s))}
            >
              {s}
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
