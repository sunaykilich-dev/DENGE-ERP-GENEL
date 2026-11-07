/**
 * Fiori liste raporu (List Report) — rehber §3, fotoğraf 0–6 ve 9.
 *
 * Genel bileşen: kategori ikon şeridi → "Kayıt Sayısı: N" → durum filtre
 * çubuğu (+ gelişmiş süzgeç paneli) → radyo (ya da çoklu) seçimli tablo →
 * altta yapışık eylem çubuğu. Veri, süzgeç ve eylemler çağırandadır; bileşen
 * yalnız düzeni çizer, böylece her liste ekranı aynı görünümü kullanır.
 *
 * Ayrıca launchpad tarzı `KpiKutucugu` (176×176 kutucuk; "sayı = liste":
 * değer sunucudan, tıklama aynı süzgeçli listeye gider).
 */
import { InfoCircleOutlined } from "@ant-design/icons";
import { Pagination, Skeleton, Table, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { Key, ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import AltEylemCubugu, { type FioriEylem } from "./AltEylemCubugu";
import DurumCubugu, { type DurumCubuguProps } from "./DurumCubugu";
import KategoriSeridi, { type FioriKategori, type KategoriAyari } from "./KategoriSeridi";
import "./fiori.css";

export type { FioriEylem } from "./AltEylemCubugu";
export type { FioriKategori, KategoriAyari } from "./KategoriSeridi";

export interface ListeRaporuProps<T extends object> {
  kategoriler?: FioriKategori[];
  /** Tek kod ya da (gruplu şeritte) birden çok seçili sekme. */
  seciliKategori?: string | string[];
  /** Kullanıcının görünecek sekmeleri seçmesi (dişli). */
  kategoriAyari?: KategoriAyari;
  onKategori?: (kod: string) => void;
  /** Sunucunun `X-Toplam-Kayit` değeri. */
  kayitSayisi?: number;
  /** "Kayıt Sayısı" satırının sağı (ör. arama kutusu). */
  ustSag?: ReactNode;
  /** Durum çubuğunun altında bilgi satırı (ör. panel süzgeci etiketi). */
  ustBilgi?: ReactNode;
  durumCubugu?: DurumCubuguProps;
  /** Gelişmiş süzgeç paneli (yalnız `durumCubugu.suzgecAcik` iken çizilir). */
  suzgecPaneli?: ReactNode;

  sutunlar: ColumnsType<T>;
  veri: T[];
  satirAnahtari: keyof T & string;
  yukleniyor?: boolean;
  /** Boş/hata metni; varsayılan "Veri yok". */
  bosMetin?: ReactNode;
  scrollX?: number;
  /** "tek" = radyo (Fiori), "coklu" = onay kutusu, "yok" = seçim yok. */
  secimModu?: "tek" | "coklu" | "yok";
  secili?: Key[];
  onSecim?: (anahtarlar: Key[], satirlar: T[]) => void;
  /** Satır seçimi dışında ayrıntı açma (çift tıklama). */
  onSatirAc?: (satir: T) => void;
  sayfalama?: { sayfa: number; boyut: number; toplam: number; onChange: (s: number) => void };

  eylemler?: FioriEylem[];
  sagEylemler?: FioriEylem[];
  eylemBilgisi?: ReactNode;
}

export default function ListeRaporu<T extends object>({
  kategoriler,
  seciliKategori,
  kategoriAyari,
  onKategori,
  kayitSayisi,
  ustSag,
  ustBilgi,
  durumCubugu,
  suzgecPaneli,
  sutunlar,
  veri,
  satirAnahtari,
  yukleniyor,
  bosMetin = "Veri yok",
  scrollX = 1100,
  secimModu = "tek",
  secili = [],
  onSecim,
  onSatirAc,
  sayfalama,
  eylemler,
  sagEylemler,
  eylemBilgisi,
}: ListeRaporuProps<T>) {
  const sec = (r: T) => {
    if (!onSecim || secimModu === "yok") return;
    const k = r[satirAnahtari] as unknown as Key;
    if (secimModu === "tek") {
      onSecim([k], [r]);
      return;
    }
    const varMi = secili.includes(k);
    const yeni = varMi ? secili.filter((x) => x !== k) : [...secili, k];
    onSecim(
      yeni,
      veri.filter((x) => yeni.includes(x[satirAnahtari] as unknown as Key)),
    );
  };

  return (
    <div className="fl-rapor">
      {kategoriler && kategoriler.length > 0 && onKategori && (
        <KategoriSeridi
          kategoriler={kategoriler}
          secili={seciliKategori}
          onSec={onKategori}
          ayar={kategoriAyari}
        />
      )}
      <div className="fl-ust">
        <span className="fl-kayit-sayisi">
          Kayıt Sayısı: {kayitSayisi === undefined ? "…" : kayitSayisi.toLocaleString("tr-TR")}
        </span>
        {ustSag && <div className="fl-ust-sag">{ustSag}</div>}
      </div>
      {durumCubugu && <DurumCubugu {...durumCubugu} />}
      {durumCubugu?.suzgecAcik && suzgecPaneli && <div className="fl-suzgec-paneli">{suzgecPaneli}</div>}
      {ustBilgi && <div className="fl-ust-bilgi">{ustBilgi}</div>}
      <Table<T>
        className="fl-tablo"
        rowKey={satirAnahtari}
        size="small"
        columns={sutunlar}
        dataSource={veri}
        loading={yukleniyor}
        scroll={{ x: scrollX }}
        pagination={false}
        locale={{ emptyText: bosMetin }}
        rowSelection={
          secimModu === "yok" || !onSecim
            ? undefined
            : {
                type: secimModu === "tek" ? "radio" : "checkbox",
                selectedRowKeys: secili,
                columnWidth: 40,
                onChange: (k, rows) => onSecim(k, rows),
              }
        }
        onRow={(r) => ({
          onClick: (e) => {
            // Bağlantı/düğme tıklaması satırı ayrıca seçmesin (kendi işini yapar).
            const hedef = e.target as HTMLElement;
            if (hedef.closest("button, a, .ant-checkbox-wrapper, .ant-radio-wrapper, input")) return;
            sec(r);
          },
          onDoubleClick: () => onSatirAc?.(r),
          style: { cursor: "pointer" },
        })}
      />
      {sayfalama && sayfalama.toplam > sayfalama.boyut && (
        <div className="fl-sayfalama">
          <Pagination
            size="small"
            current={sayfalama.sayfa}
            pageSize={sayfalama.boyut}
            total={sayfalama.toplam}
            showSizeChanger={false}
            onChange={sayfalama.onChange}
          />
        </div>
      )}
      {!!(eylemler?.length || sagEylemler?.length) && (
        <AltEylemCubugu sol={eylemler ?? []} sag={sagEylemler} orta={eylemBilgisi} />
      )}
    </div>
  );
}

// --- KPI kutucuğu -------------------------------------------------------------

const VURGU: Record<string, string> = { uyari: " uyari", kritik: " kritik" };

export function KpiKutucugu({
  baslik,
  altBaslik,
  tanim,
  deger,
  birim,
  ikon,
  yol,
  vurgu = "normal",
  yukleniyor,
  kod,
}: {
  baslik: string;
  altBaslik?: string;
  tanim?: string;
  /** null = ölçülemedi ("—", 0 DEĞİL). */
  deger?: number | string | null;
  birim?: string;
  ikon?: ReactNode;
  /** Verilmezse kutucuk tıklanmaz (yalnız gösterim). */
  yol?: string;
  vurgu?: "normal" | "uyari" | "kritik";
  yukleniyor?: boolean;
  kod?: string;
}) {
  const git = useNavigate();
  if (yukleniyor) {
    return (
      <div className="fl-kutucuk statik" aria-busy>
        <Skeleton active paragraph={{ rows: 2 }} title={false} />
      </div>
    );
  }
  const olculemedi = deger === null || deger === undefined;
  const ac = () => yol && git(yol);
  return (
    <div
      className={`fl-kutucuk${yol ? "" : " statik"}`}
      data-kpi={kod}
      role={yol ? "link" : undefined}
      tabIndex={yol ? 0 : undefined}
      aria-label={`${baslik}: ${olculemedi ? "ölçülemedi" : deger}`}
      onClick={ac}
      onKeyDown={(e) => {
        if (yol && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          ac();
        }
      }}
    >
      <div>
        <div className="fl-kutucuk-baslik">{baslik}</div>
        {altBaslik && <div className="fl-kutucuk-alt">{altBaslik}</div>}
      </div>
      {tanim && (
        <Tooltip title={tanim}>
          <InfoCircleOutlined
            className="fl-kutucuk-bilgi"
            aria-label={`${baslik} tanımı`}
            onClick={(e) => e.stopPropagation()}
          />
        </Tooltip>
      )}
      <div className="fl-kutucuk-dip">
        {ikon && <span className="fl-kutucuk-ikon">{ikon}</span>}
        <span className={`fl-kutucuk-sayi${olculemedi ? "" : (VURGU[vurgu] ?? "")}`}>
          {olculemedi ? "—" : typeof deger === "number" ? deger.toLocaleString("tr-TR") : deger}
          {!olculemedi && birim && <span className="fl-kutucuk-birim">{birim}</span>}
        </span>
      </div>
    </div>
  );
}
