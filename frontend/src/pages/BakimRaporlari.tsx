/**
 * Planlı Bakım → Raporlar sekmesi (TS-185: E12-12, E04-18, E04-19).
 *
 * - Dönem tamamlama raporu: satır = bakım dönemi, `%oran (tamamlanan/PB) — durum`
 *   (sunucunun tek fonksiyonu `donem_tamamlama`; para alanı yoktur).
 * - KPI kutusuna tıklanınca `?kpi=<kod>` ile buraya gelinir: PB KPI'ları PB
 *   listesini, uyum oranı dönem listesinin PAYDASINI açar. Liste toplamı kutunun
 *   sayısıyla aynı sorgudan gelir ("sayı = liste").
 * - Uygunsuzluk analizi (adım 2): oran, en sık 5 madde, açık aksiyon yaşı,
 *   onaysız kapanış.
 * - Excel yalnız `servis_rapor.disaaktar` sahibine; indirme denetime yazılır.
 * - Süre kaydı yoksa "eksik" yazılır, 0 yazılmaz. 375 px'te tablolar yatay kayar.
 */
import { DownloadOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  bakimApi,
  type DonemTamamlamaSatiri,
  PB_KPILERI,
  type PbRaporSatiri,
  type RaporSuzgeci,
} from "../api/bakim";
import { BIRIM_ETIKETLERI, BIRIM_KODLARI } from "../api/personel";
import { useAuth } from "../auth/AuthContext";

const SAYFA = 25;
const tarih = (v: string | null | undefined) => (v ? dayjs(v).format("DD.MM.YYYY") : "—");
const KPI_ADLARI: Record<string, string> = {
  ACIK_PB: "Açık PB",
  TAMAMLANAN_PB: "Tamamlanan PB cihazı",
  SURE_EKSIK_PB: "Süre kaydı eksik PB",
  BAKIM_YAPILDI_AKSIYON_ACIK: "Bakım yapıldı, aksiyon açık",
  UYGUNSUZLUK_ORANI: "Bakımı yapılmış PB (uygunsuzluk oranı paydası)",
  ONAYSIZ_KAPANIS: "Onaysız kapanış",
  UYUM_ORANI: "Uyum oranı paydası (değerlendirilen dönemler)",
};
const SURE_DURUMU: Record<string, { ad: string; renk: string }> = {
  TAM: { ad: "Tam", renk: "green" },
  KISMI: { ad: "Kısmi", renk: "orange" },
  EKSIK: { ad: "Eksik", renk: "red" },
  BEKLENMIYOR: { ad: "Beklenmiyor", renk: "default" },
};

function dakika(dk: number | null): string {
  if (dk === null) return "eksik";
  const s = Math.floor(dk / 60);
  return s ? `${s} sa ${dk % 60} dk` : `${dk} dk`;
}

export default function BakimRaporlari({ onFormAc }: { onFormAc: (soId: number) => void }) {
  const { yetkili } = useAuth();
  const [params, setParams] = useSearchParams();
  const kpi = params.get("kpi");
  const [aralik, setAralik] = useState<[string | null, string | null]>([null, null]);
  const [birim, setBirim] = useState<string | null>(null);
  const suzgec: RaporSuzgeci = { baslangic: aralik[0], bitis: aralik[1], birim };

  const kpiTemizle = () => {
    const yeni = new URLSearchParams(params);
    yeni.delete("kpi");
    setParams(yeni);
  };

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Space wrap>
        <DatePicker.RangePicker
          format="DD.MM.YYYY"
          placeholder={["Hedef başlangıç", "Hedef bitiş"]}
          onChange={(d) =>
            setAralik([
              d?.[0] ? d[0].format("YYYY-MM-DD") : null,
              d?.[1] ? d[1].format("YYYY-MM-DD") : null,
            ])
          }
        />
        <Select
          allowClear
          placeholder="Birim"
          style={{ width: 170 }}
          value={birim ?? undefined}
          onChange={(v) => setBirim(v ?? null)}
          options={BIRIM_KODLARI.map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] ?? b }))}
        />
        {yetkili("servis_rapor.disaaktar") && (
          <Button
            icon={<DownloadOutlined />}
            onClick={() => window.open(bakimApi.raporExcelAdresi(suzgec), "_blank")}
          >
            Excel
          </Button>
        )}
      </Space>
      <Typography.Text type="secondary">
        Tarih süzgeci dönemin hedef tarihine uygulanır. Süre kaydı olmayan iş “eksik” sayılır;
        tahmini süre yerine konmaz. Raporda ücret/tutar alanı yoktur.
      </Typography.Text>
      {kpi && (
        <Alert
          type="info"
          showIcon
          message={`Süzgeç: ${KPI_ADLARI[kpi] ?? kpi}`}
          action={
            <Button size="small" onClick={kpiTemizle}>
              Kaldır
            </Button>
          }
        />
      )}
      {kpi && (PB_KPILERI as readonly string[]).includes(kpi) ? (
        <PbListesi suzgec={{ ...suzgec, kpi }} onFormAc={onFormAc} />
      ) : (
        <DonemTamamlama suzgec={{ ...suzgec, kpi: kpi === "UYUM_ORANI" ? kpi : null }} />
      )}
      <UygunsuzlukAnalizi suzgec={suzgec} />
    </Space>
  );
}

function DonemTamamlama({ suzgec }: { suzgec: RaporSuzgeci }) {
  const [sayfa, setSayfa] = useState(1);
  const liste = useQuery({
    queryKey: ["bakim", "rapor", "donem-tamamlama", suzgec, sayfa],
    queryFn: () =>
      bakimApi.donemTamamlama({ ...suzgec, limit: SAYFA, offset: (sayfa - 1) * SAYFA }),
  });
  return (
    <Card size="small" title="Planlı bakım tamamlama (sözleşme dönemi)">
      {liste.isError && <Alert type="error" message={(liste.error as Error).message} />}
      <Table<DonemTamamlamaSatiri>
        rowKey="donem_id"
        size="small"
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar}
        scroll={{ x: 860 }}
        pagination={{
          current: sayfa,
          pageSize: SAYFA,
          total: liste.data?.toplam,
          onChange: setSayfa,
          showTotal: (t) => `${t} dönem`,
        }}
        columns={[
          { title: "Sözleşme", dataIndex: "contract_no", className: "mono", width: 120 },
          { title: "Müşteri", dataIndex: "musteri", render: (v) => v ?? "—" },
          { title: "Birim", dataIndex: "birim", render: (v: string) => BIRIM_ETIKETLERI[v] ?? v },
          { title: "Hedef", dataIndex: "target_date", render: tarih, width: 110 },
          {
            title: "Tamamlama",
            dataIndex: "oran_metni",
            render: (v: string, r) => (
              <Space size={4}>
                <span>{v}</span>
                {r.gecikmis && <Tag color="red">Gecikmiş</Tag>}
              </Space>
            ),
          },
          { title: "Açık", dataIndex: "pb_acik", width: 70 },
          { title: "İptal", dataIndex: "pb_iptal", width: 70 },
          {
            title: "Kapanış",
            dataIndex: "tamamlanma_tarihi",
            render: (v: string | null, r) =>
              v ? (
                <>
                  {tarih(v)} {r.uyumlu ? <Tag color="green">Uyumlu</Tag> : <Tag>Geç</Tag>}
                </>
              ) : (
                "—"
              ),
          },
        ]}
      />
    </Card>
  );
}

function PbListesi({
  suzgec,
  onFormAc,
}: {
  suzgec: RaporSuzgeci;
  onFormAc: (soId: number) => void;
}) {
  const [sayfa, setSayfa] = useState(1);
  const liste = useQuery({
    queryKey: ["bakim", "rapor", "pb", suzgec, sayfa],
    queryFn: () => bakimApi.pbIsleri({ ...suzgec, limit: SAYFA, offset: (sayfa - 1) * SAYFA }),
  });
  return (
    <Card size="small" title="Planlı bakım işleri">
      {liste.isError && <Alert type="error" message={(liste.error as Error).message} />}
      <Table<PbRaporSatiri>
        rowKey="so_id"
        size="small"
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar}
        scroll={{ x: 900 }}
        onRow={(r) => ({ onClick: () => onFormAc(r.so_id), style: { cursor: "pointer" } })}
        pagination={{
          current: sayfa,
          pageSize: SAYFA,
          total: liste.data?.toplam,
          onChange: setSayfa,
          showTotal: (t) => `${t} iş`,
        }}
        columns={[
          { title: "PB No", dataIndex: "so_no", className: "mono", width: 160 },
          { title: "Sözleşme", dataIndex: "contract_no", className: "mono", width: 120 },
          { title: "Müşteri", dataIndex: "musteri", render: (v) => v ?? "—" },
          { title: "Hedef", dataIndex: "target_date", render: tarih, width: 110 },
          { title: "Durum", dataIndex: "status", render: (v: string) => <Tag>{v}</Tag> },
          {
            title: "Kişi-saat",
            dataIndex: "kisi_saat_dk",
            render: (v: number | null, r) => (
              <Space size={4}>
                <span>{dakika(v)}</span>
                {r.sure_durumu && (
                  <Tag color={SURE_DURUMU[r.sure_durumu]?.renk}>
                    {SURE_DURUMU[r.sure_durumu]?.ad ?? r.sure_durumu}
                  </Tag>
                )}
              </Space>
            ),
          },
          {
            title: "Uygunsuzluk",
            dataIndex: "uygunsuzluk_var",
            render: (v: boolean) => (v ? <Tag color="orange">Var</Tag> : "—"),
          },
          {
            title: "Müşteri onayı",
            dataIndex: "onay_var",
            render: (v: boolean) => (v ? <Tag color="green">Var</Tag> : <Tag color="red">Yok</Tag>),
          },
        ]}
      />
    </Card>
  );
}

function UygunsuzlukAnalizi({ suzgec }: { suzgec: RaporSuzgeci }) {
  const veri = useQuery({
    queryKey: ["bakim", "rapor", "uygunsuzluk", suzgec],
    queryFn: () => bakimApi.uygunsuzlukAnalizi(suzgec),
  });
  const d = veri.data;
  return (
    <Card size="small" title="Uygunsuzluk analizi" loading={veri.isLoading}>
      {veri.isError && <Alert type="error" message={(veri.error as Error).message} />}
      {d && (
        <Row gutter={[16, 16]}>
          <Col xs={24} md={10}>
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="Uygunsuzluk oranı">
                {d.uygunsuzluk_orani.deger === null
                  ? "veri yok"
                  : `%${d.uygunsuzluk_orani.deger.toLocaleString("tr-TR")} (${d.uygunsuzluk_orani.pay}/${d.uygunsuzluk_orani.payda})`}
              </Descriptions.Item>
              <Descriptions.Item label="Onaysız kapanış">{d.onaysiz_kapanis}</Descriptions.Item>
              <Descriptions.Item label="Açık aksiyon">{d.aksiyon_yasi.adet}</Descriptions.Item>
              <Descriptions.Item label="Ortalama yaş (gün)">
                {d.aksiyon_yasi.ortalama_gun ?? "—"}
              </Descriptions.Item>
              <Descriptions.Item label="En eski (gün)">
                {d.aksiyon_yasi.en_eski_gun ?? "—"}
              </Descriptions.Item>
              {d.aksiyon_yasi.kovalar.map((k) => (
                <Descriptions.Item key={k.kova} label={`${k.kova} gün`}>
                  {k.adet}
                </Descriptions.Item>
              ))}
            </Descriptions>
          </Col>
          <Col xs={24} md={14}>
            <Table
              rowKey="check_code"
              size="small"
              pagination={false}
              dataSource={d.en_sik}
              scroll={{ x: 420 }}
              title={() => "En sık 5 uygunsuz madde"}
              columns={[
                { title: "Madde", dataIndex: "madde" },
                { title: "Adet", dataIndex: "adet", width: 70 },
                { title: "Açık", dataIndex: "acik", width: 70 },
              ]}
            />
          </Col>
        </Row>
      )}
    </Card>
  );
}
