import { AppstoreOutlined, SearchOutlined } from "@ant-design/icons";
import { AutoComplete, Input, Space, Tag } from "antd";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { UYGULAMALAR, uygulamaYetkili } from "../fiori/uygulamalar";

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

type Secenek = { value: string; label: React.ReactNode };

const kucuk = (s: string) => s.toLocaleLowerCase("tr");

/**
 * Kabuktaki tek arama kutusu (Fiori "Arama yeri: Uygulamalar").
 *
 * Önce kullanıcının YETKİLİ olduğu uygulamalar adlarıyla eşleşir (Fiori
 * launchpad araması gibi), ardından sunucu araması gelir — IMEI, plaka,
 * ICCID, şase, firma, ürün (kabul kriteri 1). Modüller geldikçe sunucu
 * tarafında yeni kaynak eklenir; bu bileşen değişmez.
 */
export default function GlobalSearch({
  otomatikOdak = false,
  onSecildi,
}: {
  otomatikOdak?: boolean;
  onSecildi?: () => void;
}) {
  const { yetkili } = useAuth();
  const [secenekler, setSecenekler] = useState<Secenek[]>([]);
  const [deger, setDeger] = useState("");
  const sonIstek = useRef(0);
  const navigate = useNavigate();

  function uygulamaSonuclari(terim: string): Secenek[] {
    const t = kucuk(terim.trim());
    if (!t) return [];
    return UYGULAMALAR.filter(
      (u) =>
        u.kpi?.tur !== "uyari" &&
        uygulamaYetkili(u, yetkili) &&
        (kucuk(u.baslik).includes(t) || kucuk(u.altBaslik ?? "").includes(t)),
    )
      .slice(0, 6)
      .map((u) => ({
        value: u.yol,
        label: (
          <Space size={6}>
            <AppstoreOutlined style={{ color: "#0a6ed1" }} />
            <span>{u.baslik}</span>
            {u.altBaslik && <span style={{ opacity: 0.6, fontSize: 12 }}>{u.altBaslik}</span>}
          </Space>
        ),
      }));
  }

  async function ara(terim: string) {
    setDeger(terim);
    const uygulamalar = uygulamaSonuclari(terim);
    setSecenekler(uygulamalar);
    const istek = ++sonIstek.current;
    if (terim.trim().length < 2) return;
    try {
      const sonuc = await api.get<Sonuc[]>(`/api/arama?q=${encodeURIComponent(terim)}`);
      if (istek !== sonIstek.current) return;
      setSecenekler([
        ...uygulamalar,
        ...sonuc.map((s) => ({
          value: s.yol,
          label: (
            <Space size={6}>
              <Tag style={{ marginInlineEnd: 0 }}>{TUR_ADI[s.tur] ?? s.tur}</Tag>
              <span>{s.baslik}</span>
              {s.alt_baslik && <span className="mono" style={{ opacity: 0.6 }}>{s.alt_baslik}</span>}
            </Space>
          ),
        })),
      ]);
    } catch {
      /* sunucu araması düşerse uygulama eşleşmeleri kalır */
    }
  }

  return (
    <AutoComplete
      className="fiori-arama"
      value={deger}
      options={secenekler}
      onSearch={(t) => void ara(t)}
      onSelect={(yol: string) => {
        setDeger("");
        setSecenekler([]);
        navigate(yol);
        onSecildi?.();
      }}
      style={{ width: "100%", minWidth: 0 }}
      popupMatchSelectWidth={420}
    >
      <Input
        autoFocus={otomatikOdak}
        suffix={<SearchOutlined style={{ color: "#0a6ed1" }} />}
        placeholder='Arama yeri: "Uygulamalar"'
        aria-label="Uygulama, IMEI, plaka, ICCID, şase, firma ara"
        title="Uygulama adı, IMEI, plaka, ICCID, şase ya da firma"
      />
    </AutoComplete>
  );
}
