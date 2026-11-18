import { AppstoreOutlined, SearchOutlined } from "@ant-design/icons";
import { AutoComplete, Input, Space, Tag } from "antd";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useSirket } from "../auth/SirketContext";
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
/** Menüden aranabilir öğe (KARARLAR 2026-11-04 §5): "Kurulum" yazınca menü yolu gelir. */
export interface AranabilirMenuOgesi {
  baslik: string;
  yol: string;
  /** "Güvenlik › Teknik Servis" gibi üst yol. */
  ust: string;
}

export default function GlobalSearch({
  otomatikOdak = false,
  onSecildi,
  kimlik,
  menuOgeleri = [],
}: {
  otomatikOdak?: boolean;
  onSecildi?: () => void;
  /** Ctrl+K kısayolunun odaklayacağı giriş kimliği. */
  kimlik?: string;
  /** Kullanıcının görebildiği menü yaprakları (şirket ve izinle süzülmüş). */
  menuOgeleri?: AranabilirMenuOgesi[];
}) {
  const { yetkili } = useAuth();
  // IMEI/plaka/ICCID arayıcıları yalnız DENGE MOBİLİTE'de sonuç verir
  // (`_yalniz_mobilite`); diğer şirketlerde kutu bunları vaat etmesin.
  const mobilite = useSirket().aktif?.kod === "MOBILITE";
  const [secenekler, setSecenekler] = useState<Secenek[]>([]);
  const [deger, setDeger] = useState("");
  const sonIstek = useRef(0);
  const navigate = useNavigate();

  function uygulamaSonuclari(terim: string): Secenek[] {
    const t = kucuk(terim.trim());
    if (!t) return [];
    const menudenler = menuOgeleri
      .filter((m) => kucuk(m.baslik).includes(t) || kucuk(m.ust).includes(t))
      // Aynı yol iki dalda olabilir (Haberleşme › POC ile POC bölümü): bir kez.
      .filter((m, i, d) => d.findIndex((x) => x.yol === m.yol) === i)
      .slice(0, 6);
    const menuYollari = new Set(menudenler.map((m) => m.yol));
    const menuSecenekleri: Secenek[] = menudenler.map((m) => ({
      value: m.yol,
      label: (
        <Space size={6}>
          <AppstoreOutlined style={{ color: "#0a6ed1" }} />
          <span>{m.baslik}</span>
          {m.ust && <span style={{ opacity: 0.6, fontSize: 12 }}>{m.ust}</span>}
        </Space>
      ),
    }));
    // Menü verildiyse (kabuk) yalnız o aranır: menü her sayfayı içerir ve
    // izin + etkin şirketle süzülmüştür (Telekom çalışanı Mobilite'yi bulamaz).
    if (menuOgeleri.length) return menuSecenekleri;
    return [...menuSecenekleri, ...UYGULAMALAR.filter(
      (u) =>
        u.kpi?.tur !== "uyari" &&
        uygulamaYetkili(u, yetkili) &&
        !menuYollari.has(u.yol) &&
        (kucuk(u.baslik).includes(t) || kucuk(u.altBaslik ?? "").includes(t)),
    )
      .slice(0, Math.max(0, 8 - menuSecenekleri.length))
      .map((u) => ({
        value: u.yol,
        label: (
          <Space size={6}>
            <AppstoreOutlined style={{ color: "#0a6ed1" }} />
            <span>{u.baslik}</span>
            {u.altBaslik && <span style={{ opacity: 0.6, fontSize: 12 }}>{u.altBaslik}</span>}
          </Space>
        ),
      }))];
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
        id={kimlik}
        autoFocus={otomatikOdak}
        suffix={<SearchOutlined style={{ color: "#0a6ed1" }} />}
        placeholder={mobilite ? "Menü, IMEI, plaka, firma ara… (Ctrl+K)" : "Menü, iş no, ekipman, firma ara… (Ctrl+K)"}
        aria-label={mobilite ? "Uygulama, IMEI, plaka, ICCID, şase, firma ara" : "Uygulama, servis işi, ekipman, firma ara"}
        title={mobilite ? "Uygulama adı, IMEI, plaka, ICCID, şase ya da firma" : "Uygulama adı, servis iş no, ekipman ya da firma"}
      />
    </AutoComplete>
  );
}
