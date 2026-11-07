/**
 * Fiori kategori ikon şeridi (rehber §3.1, fotoğraf 0–6 ve 9): dairesel ikon
 * düğmeler + BÜYÜK HARF kısa etiket. Kırmızı = arıza/plansız, yeşil = planlı.
 * Seçili kategori dolu daire ve altında 3 px renkli çizgiyle gösterilir.
 *
 * Gruplu şerit (2026-11-06, atölye): `grup` değişince araya ince ayraç girer;
 * birden çok sekme aynı anda seçili olabilir (`secili` dizi: tür + durum).
 * `ayar` verilirse şeridin sonunda dişli çıkar: kullanıcı hangi sekmeleri
 * göreceğini seçer; tercih tarayıcıda kullanıcı başına saklanır (`yerelDepo`,
 * KARARLAR 2026-11-04 §5 — kolaylık verisi). Seçili sekme gizlense de görünür
 * kalır (süzgeç sessizce kaybolmasın).
 */
import { SettingOutlined, ToolOutlined } from "@ant-design/icons";
import { Button, Checkbox, Divider, Popover, Space, Typography } from "antd";
import { useMemo, useState, type ReactNode } from "react";

import { useAuth } from "../auth/AuthContext";
import type { KategoriRengi } from "./etiketler";
import { yerelOku, yerelYaz } from "./yerelDepo";
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
  /** Sayı 0 iken de rozet göster (durum sekmeleri: "0" de bilgidir). */
  sifirGoster?: boolean;
  /** Grup adı: değişince araya ayraç girer; sekme ayarında başlık olur. */
  grup?: string;
}

export interface KategoriAyari {
  /** Tercih anahtarı (sayfa başına tekil, ör. "atolye-sekmeleri"). */
  kimlik: string;
  /** Tercih yokken görünecek sekmeler; verilmezse hepsi. */
  varsayilan?: string[];
  /** Gizlenemeyen sekmeler (ör. TÜMÜ). */
  sabit?: string[];
}

export default function KategoriSeridi({
  kategoriler,
  secili,
  onSec,
  ayar,
}: {
  kategoriler: FioriKategori[];
  secili?: string | string[];
  onSec: (kod: string) => void;
  ayar?: KategoriAyari;
}) {
  const { kullanici } = useAuth();
  const seciliKume = useMemo(
    () => new Set(Array.isArray(secili) ? secili : secili ? [secili] : []),
    [secili],
  );
  const [tercih, setTercih] = useState<string[] | null>(() =>
    ayar ? yerelOku<string[] | null>(kullanici?.id, ayar.kimlik, null) : null,
  );
  const [ayarAcik, setAyarAcik] = useState(false);

  const sabit = useMemo(() => new Set(ayar?.sabit ?? []), [ayar?.sabit]);
  const gorunurKume = useMemo(() => {
    if (!ayar) return null;
    const liste = tercih ?? ayar.varsayilan ?? kategoriler.map((k) => k.kod);
    return new Set([...liste, ...sabit]);
  }, [ayar, tercih, kategoriler, sabit]);

  const gorunenler = gorunurKume
    ? kategoriler.filter((k) => gorunurKume.has(k.kod) || seciliKume.has(k.kod))
    : kategoriler;

  const kaydet = (liste: string[] | null) => {
    setTercih(liste);
    if (ayar) yerelYaz(kullanici?.id, ayar.kimlik, liste);
  };

  const gruplar = useMemo(() => {
    const g = new Map<string, FioriKategori[]>();
    for (const k of kategoriler) g.set(k.grup ?? "", [...(g.get(k.grup ?? "") ?? []), k]);
    return [...g.entries()];
  }, [kategoriler]);

  const ayarPaneli = ayar && gorunurKume && (
    <div style={{ width: 280, maxHeight: 420, overflowY: "auto" }}>
      {gruplar.map(([grup, liste], i) => (
        <div key={grup || i}>
          {i > 0 && <Divider style={{ margin: "8px 0" }} />}
          {grup && (
            <Typography.Text strong style={{ display: "block", marginBottom: 4 }}>
              {grup}
            </Typography.Text>
          )}
          <Space orientation="vertical" size={2}>
            {liste.map((k) => (
              <Checkbox
                key={k.kod}
                checked={gorunurKume.has(k.kod)}
                disabled={sabit.has(k.kod)}
                onChange={(e) => {
                  const yeni = new Set(gorunurKume);
                  if (e.target.checked) yeni.add(k.kod);
                  else yeni.delete(k.kod);
                  // Şerit sırası korunur.
                  kaydet(kategoriler.map((x) => x.kod).filter((kod) => yeni.has(kod)));
                }}
              >
                {k.ad}
              </Checkbox>
            ))}
          </Space>
        </div>
      ))}
      <Divider style={{ margin: "8px 0" }} />
      <Space>
        <Button size="small" onClick={() => kaydet(kategoriler.map((k) => k.kod))}>
          Hepsini göster
        </Button>
        <Button size="small" type="link" onClick={() => kaydet(null)}>
          Varsayılana dön
        </Button>
      </Space>
    </div>
  );

  return (
    <div className="fl-kategori-seridi" role="tablist" aria-label="Kategoriler">
      {gorunenler.map((k, i) => {
        const s = seciliKume.has(k.kod);
        const ayrac = i > 0 && (gorunenler[i - 1].grup ?? "") !== (k.grup ?? "");
        const sayiGoster = k.sayi != null && (k.sayi > 0 || k.sifirGoster);
        return (
          <span key={k.kod} style={{ display: "contents" }}>
            {ayrac && <span className="fl-kategori-ayrac" aria-hidden />}
            <button
              type="button"
              role="tab"
              aria-selected={s}
              title={k.ipucu ?? k.ad}
              className={`fl-kategori ${k.renk}${s ? " secili" : ""}`}
              onClick={() => onSec(k.kod)}
            >
              <span className="fl-kategori-daire">{k.ikon ?? <ToolOutlined />}</span>
              <span className="fl-kategori-ad">{k.ad}</span>
              {sayiGoster && (
                <span className={`fl-kategori-sayi${k.sayi === 0 ? " sifir" : ""}`}>{k.sayi}</span>
              )}
            </button>
          </span>
        );
      })}
      {ayar && (
        <Popover
          trigger="click"
          placement="bottomRight"
          title="Görünecek sekmeler"
          open={ayarAcik}
          onOpenChange={setAyarAcik}
          content={ayarPaneli}
        >
          <button
            type="button"
            className="fl-kategori fl-kategori-ayar"
            title="Sekmeleri düzenle"
            aria-label="Sekmeleri düzenle"
          >
            <span className="fl-kategori-daire">
              <SettingOutlined />
            </span>
            <span className="fl-kategori-ad">Sekmeler</span>
          </button>
        </Popover>
      )}
    </div>
  );
}
