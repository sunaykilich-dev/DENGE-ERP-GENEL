import { useQuery } from "@tanstack/react-query";
import { Skeleton, Table, Tag } from "antd";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import type { AktifIs, AnaPanelYaniti, BekleyenAksiyon } from "../../api/anaPanel";
import { api } from "../../api/client";
import {
  AKSIYON_SUTUNLAR,
  AKTIF_SUTUNLAR,
  AylikBakim,
  BirimKarti,
  BolumGrafigi,
  Bos,
  DurumGrafigi,
  EKIP_RENGI,
  EkipListesi,
  HaftalikPlan,
  Kart,
  KpiKarti,
  PbGrafigi,
  RENK,
  renkli,
} from "./servisParcalari";

/**
 * Ana Panel bileşen ÇİZİM kaydı (KARARLAR 2026-11-09 S8).
 *
 * Hangi bileşenin var olduğu, kime görüneceği (izin) ve varsayılan boyutu
 * SUNUCUDADIR (`backend/app/services/ana_panel_duzeni.py` `BILESENLER`); sunucu
 * katalogu kullanıcının izinleriyle süzülmüş döndürür. Burası yalnız aynı kodla
 * çizer. Sunucuya yeni bileşen eklenince buraya da çizimi eklenir — eksikse
 * `tests/unit/test_ana_panel_bilesenleri.py` kırılır.
 *
 * Sözleşme: `cizim` null dönerse bileşenin bu kullanıcı/süzgeç için gösterecek
 * verisi yoktur (ör. POC kapsamda değil); görünüm kipinde hücre hiç çizilmez.
 *
 * S8.2'de istenen "Kazanma oranı" ve "Satışlarımın durumu" için henüz uç yok
 * (sunucu `PLANLANAN_BILESENLER`); uç gelince sunucu kaydına ve buraya eklenir.
 */

export interface BilesenBaglami {
  /** Servis verisi (`veri: "servis"` bileşenlerinde dolu; yüklenirken çizim çağrılmaz). */
  servis?: AnaPanelYaniti;
  kullaniciId?: number;
  /** Etkin şirketin menü birimleri (POC kartı süzgeci; yoksa süzme yok). */
  menuBirimleri?: ReadonlySet<string> | null;
}

export interface BilesenCizimi {
  /** true: `GET /api/teknik-servis/ana-panel` verisi gerekir (yüklenirken iskelet çizilir). */
  servis: boolean;
  cizim: (b: BilesenBaglami) => ReactNode;
}

function servisli(fn: (v: AnaPanelYaniti, b: BilesenBaglami) => ReactNode): BilesenCizimi {
  return { servis: true, cizim: (b) => (b.servis ? fn(b.servis, b) : null) };
}

/** Sunucu KPI kodu (`kpiler[].kod`) → gösterge. Sunucu kartı döndürmezse çizilmez. */
function gosterge(kpiKodu: string): BilesenCizimi {
  return servisli((servis, { menuBirimleri }) => {
    // Rol testi B-12 / tur 2 §7.17: POC kartı yalnız POC etkin şirketteyse.
    if (kpiKodu === "poc_acik" && menuBirimleri && !menuBirimleri.has("POC")) return null;
    const k = servis.kpiler.find((x) => x.kod === kpiKodu);
    return k ? <KpiKarti k={k} /> : null;
  });
}

function EkipKarti({ v }: { v: AnaPanelYaniti }) {
  const ekip = v.ekip_durumu;
  return (
    <Kart baslik="Canlı Ekip Durumu" sag={ekip.liste_yolu ? <Link to={ekip.liste_yolu}>Tüm Ekipleri Gör</Link> : null}>
      {ekip.gorunur && ekip.satirlar.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 6 }}>
          {ekip.ozet
            .filter((o) => o.adet > 0)
            .map((o) => (
              <span key={o.durum} className="ap-durum-rozet" style={renkli(EKIP_RENGI[o.durum] ?? RENK.gri)}>
                {o.ad} {o.adet}
              </span>
            ))}
        </div>
      )}
      <EkipListesi ekip={ekip} />
    </Kart>
  );
}

function AksiyonKarti({ v }: { v: AnaPanelYaniti }) {
  const b = v.bekleyen_aksiyonlar;
  return (
    <Kart
      baslik="Birimler Arası Bekleyen Aksiyonlar"
      sag={b.toplam > 0 ? <span className="ap-hucre-ince">Toplam {b.toplam}</span> : null}
    >
      {b.ozet.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 6 }}>
          {b.ozet.map((o) => (
            <Tag key={o.hedef_birim} style={{ marginInlineEnd: 0 }}>
              {o.hedef_birim}: {o.adet}
            </Tag>
          ))}
        </div>
      )}
      <Table<BekleyenAksiyon>
        className="ap-tablo"
        rowKey={(r) => `${r.kayit_id}-${r.hedef_birim}`}
        size="small"
        columns={AKSIYON_SUTUNLAR}
        dataSource={b.satirlar}
        pagination={false}
        scroll={{ x: "max-content" }}
        locale={{ emptyText: "Birimler arasında bekleyen iş yok." }}
      />
    </Kart>
  );
}

interface TeklifOzeti {
  kpi: { kod: string; baslik: string; deger: number }[];
}

/**
 * "Tekliflerim" (S8.2): mevcut `GET /api/teklifler/ozet?hazirlayan_id=<ben>`
 * ucu — izin `teklif.gor` ve teklif kapsamı sunucuda. Teklif listesi bugün
 * KPI/hazırlayan süzgecini adres çubuğundan okumadığı için sayılar tıklanmaz;
 * başlıktaki bağlantı listeyi açar.
 */
function TekliflerimKarti({ kullaniciId }: { kullaniciId?: number }) {
  const ozet = useQuery({
    queryKey: ["teklifler", "ozet", "hazirlayan", kullaniciId],
    queryFn: () => api.get<TeklifOzeti>(`/api/teklifler/ozet?hazirlayan_id=${kullaniciId}`),
    enabled: kullaniciId != null,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  });
  return (
    <Kart baslik="Tekliflerim" sag={<Link to="/teklifler">Teklifleri Aç</Link>}>
      {ozet.isError ? (
        <Bos>Teklif özeti yüklenemedi: {(ozet.error as Error).message}</Bos>
      ) : !ozet.data ? (
        <Skeleton active paragraph={{ rows: 2 }} title={false} />
      ) : (
        <div className="ap-teklif-sayilar">
          {ozet.data.kpi.map((k) => (
            <div key={k.kod} className="ap-teklif-sayi" data-kpi={k.kod}>
              <small>{k.baslik}</small>
              <b>{k.deger.toLocaleString("tr-TR")}</b>
            </div>
          ))}
        </div>
      )}
    </Kart>
  );
}

export const BILESEN_CIZIMLERI: Record<string, BilesenCizimi> = {
  kpi_acik_is: gosterge("acik_is"),
  kpi_planli_bakim: gosterge("planli_bakim"),
  kpi_acil_ariza: gosterge("acil_ariza"),
  kpi_poc_acik: gosterge("poc_acik"),
  kpi_sla_riski: gosterge("sla_riski"),
  kpi_sahadaki_ekip: gosterge("sahadaki_ekip"),
  kpi_askida: gosterge("askida"),
  kpi_bekleyen_onay: gosterge("bekleyen_onay"),
  birim_ozeti: servisli((servis) => (
      <Kart baslik="Canlı Operasyon Özeti">
        {servis.birim_ozeti.length === 0 ? (
          <Bos>Görebileceğiniz bir birim yok. Birim üyeliğiniz için yöneticinize başvurun.</Bos>
        ) : (
          <div className="ap-birimler">
            {servis.birim_ozeti.map((b) => (
              <BirimKarti key={b.birim} b={b} />
            ))}
          </div>
        )}
    </Kart>
  )),
  ekip_durumu: servisli((servis) => <EkipKarti v={servis} />),
  aktif_isler: servisli((servis) => (
      <Kart baslik="Aktif İşler / Kim Ne Yapıyor" sag={<Link to={servis.aktif_isler.liste_yolu}>Tüm İşleri Gör</Link>}>
        <Table<AktifIs>
          className="ap-tablo"
          rowKey="id"
          size="small"
          columns={AKTIF_SUTUNLAR}
          dataSource={servis.aktif_isler.satirlar}
          pagination={false}
          scroll={{ x: 1340 }}
          locale={{ emptyText: "Bu süzgeçle açık iş yok. Süzgeçleri genişletmeyi deneyin." }}
        />
    </Kart>
  )),
  bekleyen_aksiyonlar: servisli((servis) => <AksiyonKarti v={servis} />),
  grafik_durum: servisli((servis) => <DurumGrafigi g={servis.grafikler} />),
  grafik_bolum: servisli((servis) => <BolumGrafigi g={servis.grafikler} />),
  grafik_pb: servisli((servis) => <PbGrafigi g={servis.grafikler} />),
  grafik_haftalik: servisli((servis) => <HaftalikPlan g={servis.grafikler} />),
  grafik_aylik: servisli((servis) => <AylikBakim g={servis.grafikler} />),
  tekliflerim: { servis: false, cizim: ({ kullaniciId }) => <TekliflerimKarti kullaniciId={kullaniciId} /> },
};
