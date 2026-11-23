/**
 * Tek değerli seri/IMEI alanı: el okuyucu (tuş zamanlamasıyla algılanır) +
 * kamera düğmesi. Okuyucunun gönderdiği Enter formu GÖNDERMEZ. Kamera okuması
 * alana el okuyucu yazmış gibi girer.
 *
 * `OkumaliSeriAlani`: aynı alan + okuma kaynağı; elle girişte sabit listeden
 * neden (DIGER'de açıklama) sorulur. Form değeri `SeriOkumasi`.
 */
import { BarcodeOutlined } from "@ant-design/icons";
import { Input, Select, Space, Tag } from "antd";
import type React from "react";

import { ELLE_GEREKCELERI, type SeriOkumasi } from "./elleGerekce";
import { KameraDugmesi } from "./KameraOkuyucu";
import { useOkuyucuAlgilama, type OkumaKaynagi } from "./okuyucuAlgilama";

export default function SeriAlani({
  value,
  onChange,
  onKaynak,
  onEnter,
  onGiris,
  placeholder = "Barkodu okutun ya da yazın",
  maxLength = 200,
  disabled,
  buyuk,
  style,
  id,
}: {
  value?: string;
  onChange?: (v: string) => void;
  /** Her değişiklikte: yazma/yapıştırma ELLE, okuyucu Enter'ı ya da kamera OKUTMA. */
  onKaynak?: (k: OkumaKaynagi) => void;
  /** Enter'a basıldı (okuyucu ya da klavye). */
  onEnter?: (deger: string, k: OkumaKaynagi) => void;
  /** Değer ve kaynak birlikte (yazma ELLE; Enter hesaplanır; kamera OKUTMA). */
  onGiris?: (deger: string, k: OkumaKaynagi) => void;
  placeholder?: string;
  maxLength?: number;
  disabled?: boolean;
  buyuk?: boolean;
  style?: React.CSSProperties;
  id?: string;
}) {
  const { olaylar, kaynak } = useOkuyucuAlgilama();
  return (
    <Space.Compact style={{ width: "100%", ...style }}>
      <Input
        id={id}
        value={value}
        size={buyuk ? "large" : undefined}
        style={buyuk ? { minHeight: 44 } : undefined}
        prefix={<BarcodeOutlined />}
        className="mono"
        placeholder={placeholder}
        maxLength={maxLength}
        disabled={disabled}
        autoComplete="off"
        {...olaylar}
        onChange={(e) => {
          onChange?.(e.target.value);
          onKaynak?.("ELLE");
          onGiris?.(e.target.value, "ELLE");
        }}
        onPressEnter={(e) => {
          e.preventDefault();
          const deger = e.currentTarget.value;
          const k = kaynak(deger, e.timeStamp);
          onKaynak?.(k);
          onGiris?.(deger, k);
          onEnter?.(deger, k);
        }}
      />
      <KameraDugmesi
        disabled={disabled}
        buyuk={buyuk}
        onOkundu={(m) => {
          onChange?.(m);
          onKaynak?.("OKUTMA");
          onGiris?.(m, "OKUTMA");
          onEnter?.(m, "OKUTMA");
        }}
      />
    </Space.Compact>
  );
}

/** `OkumaliSeriAlani` doğrulaması (Form.Item `rules` içinde kullanılır). */
export function okumaDogrula(v: Partial<SeriOkumasi> | undefined, zorunlu: boolean): Promise<void> {
  if (!v?.seri_no?.trim()) {
    return zorunlu ? Promise.reject(new Error("Cihazın seri numarasını okutun")) : Promise.resolve();
  }
  if (v.okuma_kaynagi === "ELLE" && !v.elle_gerekce) {
    return Promise.reject(new Error("Elle girilen seri için neden seçin"));
  }
  if (v.okuma_kaynagi === "ELLE" && v.elle_gerekce === "DIGER" && !v.elle_aciklama?.trim()) {
    return Promise.reject(new Error("Neden 'Diğer' ise açıklama yazın"));
  }
  return Promise.resolve();
}

/** Seri + kaynak + (elle ise) neden. Kaynağı bilinmeyen değer ELLE sayılır. */
export function OkumaliSeriAlani({
  value,
  onChange,
  buyuk,
  disabled,
  placeholder,
}: {
  value?: Partial<SeriOkumasi>;
  onChange?: (v: Partial<SeriOkumasi>) => void;
  buyuk?: boolean;
  disabled?: boolean;
  placeholder?: string;
}) {
  const v = value ?? {};
  const kaynak = v.seri_no?.trim() ? (v.okuma_kaynagi ?? "ELLE") : undefined;
  const degistir = (p: Partial<SeriOkumasi>) => onChange?.({ ...v, okuma_kaynagi: kaynak, ...p });
  return (
    <Space orientation="vertical" style={{ width: "100%" }} size={6}>
      <SeriAlani
        value={v.seri_no}
        buyuk={buyuk}
        disabled={disabled}
        placeholder={placeholder}
        onGiris={(seri_no, okuma_kaynagi) => degistir({ seri_no, okuma_kaynagi })}
      />
      {kaynak === "OKUTMA" && <Tag color="green">Okutuldu</Tag>}
      {kaynak === "ELLE" && (
        <>
          <Select
            size={buyuk ? "large" : undefined}
            placeholder="Elle girildi: neden?"
            value={v.elle_gerekce ?? undefined}
            disabled={disabled}
            onChange={(elle_gerekce) => degistir({ elle_gerekce })}
            options={ELLE_GEREKCELERI.map((g) => ({ value: g.kod, label: g.ad }))}
          />
          {v.elle_gerekce === "DIGER" && (
            <Input
              size={buyuk ? "large" : undefined}
              maxLength={200}
              placeholder="Açıklama"
              value={v.elle_aciklama ?? ""}
              disabled={disabled}
              onChange={(e) => degistir({ elle_aciklama: e.target.value })}
            />
          )}
        </>
      )}
    </Space>
  );
}

/** Formdaki okumayı sunucu gövdesine çevirir (boşsa null). */
export function okumaGovdesi(v: Partial<SeriOkumasi> | undefined): SeriOkumasi | null {
  const seri = v?.seri_no?.trim();
  if (!seri) return null;
  const elle = (v?.okuma_kaynagi ?? "ELLE") === "ELLE";
  return {
    seri_no: seri,
    okuma_kaynagi: elle ? "ELLE" : "OKUTMA",
    elle_gerekce: elle ? (v?.elle_gerekce ?? null) : null,
    elle_aciklama: elle ? v?.elle_aciklama?.trim() || null : null,
  };
}
