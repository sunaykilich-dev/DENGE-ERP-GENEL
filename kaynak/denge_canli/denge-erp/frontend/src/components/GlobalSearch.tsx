import { SearchOutlined } from "@ant-design/icons";
import { AutoComplete, Input, Space, Tag } from "antd";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";

interface Sonuc {
  tur: string;
  id: number;
  baslik: string;
  alt_baslik: string | null;
  etiketler: string[];
  yol: string;
}

const TUR_ADI: Record<string, string> = {
  HESAP: "Hesap",
  URUN: "Ürün",
  CIHAZ: "Cihaz",
  ARAC: "Araç",
  HAT: "Hat",
};

/**
 * Üst bardaki tek arama kutusu — IMEI, plaka, ICCID, şase, firma, ürün.
 * Kabul kriteri 1'in giriş noktası. Modüller geldikçe sunucu tarafında yeni
 * kaynak eklenir; bu bileşen değişmez.
 */
export default function GlobalSearch() {
  const [secenekler, setSecenekler] = useState<{ value: string; label: React.ReactNode }[]>([]);
  const navigate = useNavigate();

  async function ara(terim: string) {
    if (terim.trim().length < 2) {
      setSecenekler([]);
      return;
    }
    try {
      const sonuc = await api.get<Sonuc[]>(`/api/arama?q=${encodeURIComponent(terim)}`);
      setSecenekler(
        sonuc.map((s) => ({
          value: s.yol,
          label: (
            <Space size={6}>
              <Tag style={{ marginInlineEnd: 0 }}>{TUR_ADI[s.tur] ?? s.tur}</Tag>
              <span>{s.baslik}</span>
              {s.alt_baslik && <span className="mono" style={{ opacity: 0.6 }}>{s.alt_baslik}</span>}
            </Space>
          ),
        })),
      );
    } catch {
      setSecenekler([]);
    }
  }

  return (
    <AutoComplete
      options={secenekler}
      onSearch={ara}
      onSelect={(yol: string) => navigate(yol)}
      // Sabit 340 px dar ekranda taşıyordu; kutu mevcut alana uyar.
      style={{ width: "100%", maxWidth: 340, minWidth: 0 }}
      popupMatchSelectWidth={420}
    >
      <Input
        prefix={<SearchOutlined style={{ opacity: 0.5 }} />}
        placeholder="IMEI, plaka, ICCID, şase, firma…"
        allowClear
      />
    </AutoComplete>
  );
}
