/**
 * Saha / Zaman Takibi yönetim ekranı (TS-189, E09-14/15).
 *
 * - Üstte tıklanabilir KPI kutuları (`KpiKutusu`): kutudaki sayı sunucunun
 *   `deger`idir; tıklanınca `?kpi=` ile alttaki ayrıntı tablosu süzülür ve
 *   tablo toplamı (`X-Toplam-Kayit`) kutudaki adetle aynıdır.
 * - "Şu an çalışanlar": açık sayaçlar; uzun sayaç kırmızı; yönetici
 *   (`servis.planla`) gerçek bitişle kapatır ya da iptal eder (E09-06).
 * - Personel dağılımı ve veri disiplini sütunları, kişi süzgeci ve Excel
 *   "Personel" sayfası yalnız `servis_rapor.personel` ile (sunucu anahtarı
 *   hiç göndermez; ekran yalnız yansıtır).
 * - Kayıt yoksa süre "Kayıt eksik" görünür, "0" yazılmaz; tahmini (plan)
 *   süre bu ekranda yoktur.
 * - Menü izni `servis_rapor.gor` (KD-06); izni olmayan Benim İşlerim'e döner.
 */
import { DownloadOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  DatePicker,
  Empty,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useMemo, useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";

import type { ApiError } from "../api/client";
import { BIRIM_ETIKETLERI, BIRIM_KODLARI } from "../api/personel";
import {
  type Bolum,
  FAALIYET_ADLARI,
  type Faaliyet,
  type PersonelSatiri,
  SURE_DURUMU_ADLARI,
  type ZamanIsi,
  type ZamanKaydi,
  type ZamanSuzgeci,
  ZAMAN_SORGULARI,
  servisZaman,
  sureMetni,
  zamanTakibi,
} from "../api/servisZaman";
import { useAuth } from "../auth/AuthContext";
import KpiKutusu from "../components/KpiKutusu";

const ISO = "YYYY-MM-DD";
const SAYFA = 50;
const IS_KPI = new Set(["farkli_is", "sure_eksik"]);

const KAYNAK_ADLARI: Record<string, string> = {
  CANLI: "Canlı",
  MANUEL: "Manuel",
  KULLANICI_DUZELTMESI: "Kullanıcı düzeltmesi",
  YONETICI_DUZELTMESI: "Yönetici düzeltmesi",
};

function sure(dk: number | null | undefined) {
  const m = sureMetni(dk);
  return m ?? <Tag color="orange">Kayıt eksik</Tag>;
}

function an(t: string | null) {
  return t ? dayjs(t).format("DD.MM.YYYY HH:mm") : "—";
}

export default function ZamanTakibiPage() {
  const { yetkili, kullanici } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const personelGorur = yetkili("servis_rapor.personel");
  const yonetici = yetkili("servis.planla");

  const [aralik, setAralik] = useState<[Dayjs, Dayjs] | null>(null);
  const [birim, setBirim] = useState<string | undefined>(
    kullanici?.birimler?.length === 1 ? kullanici.birimler[0] : undefined,
  );
  const [kisi, setKisi] = useState<number | undefined>();
  const [faaliyet, setFaaliyet] = useState<string | undefined>();
  const [sayfa, setSayfa] = useState(1);
  const [kapatilan, setKapatilan] = useState<ZamanKaydi | null>(null);
  const [kapatForm] = Form.useForm<{ gercek_bitis?: Dayjs; gerekce: string }>();

  const kpiKodu = params.get("kpi") ?? undefined;
  const suzgec: ZamanSuzgeci = {
    bas: aralik?.[0].format(ISO),
    bit: aralik?.[1].format(ISO),
    birim,
    kullanici_id: kisi,
    faaliyet,
  };
  const suzgecAnahtari = [suzgec.bas, suzgec.bit, birim, kisi, faaliyet];

  const ozet = useQuery({
    queryKey: ["zaman-ozet", ...suzgecAnahtari],
    queryFn: () => zamanTakibi.ozet(suzgec),
    enabled: yetkili("servis_rapor.gor"),
  });
  const aktif = useQuery({
    queryKey: ["zaman-aktif", birim, kisi],
    queryFn: () => zamanTakibi.aktif({ birim, kullanici_id: kisi }),
    enabled: yetkili("servis_rapor.gor"),
    refetchInterval: 60_000,
  });
  const isListesi = !!kpiKodu && IS_KPI.has(kpiKodu);
  const kayitlar = useQuery({
    queryKey: ["zaman-kayitlar", kpiKodu, sayfa, ...suzgecAnahtari],
    queryFn: () => zamanTakibi.kayitlar({ ...suzgec, kpi: kpiKodu }, SAYFA, (sayfa - 1) * SAYFA),
    enabled: yetkili("servis_rapor.gor") && !isListesi,
  });
  const isler = useQuery({
    queryKey: ["zaman-isler", kpiKodu, sayfa, ...suzgecAnahtari],
    queryFn: () => zamanTakibi.isler({ ...suzgec, kpi: kpiKodu! }, SAYFA, (sayfa - 1) * SAYFA),
    enabled: yetkili("servis_rapor.gor") && isListesi,
  });

  const kapat = useMutation({
    mutationFn: (v: { gercek_bitis?: Dayjs; gerekce: string }) =>
      servisZaman.yoneticiKapat(
        kapatilan as unknown as Bolum,
        v.gerekce,
        v.gercek_bitis ? v.gercek_bitis.toISOString() : undefined,
      ),
    onSuccess: () => {
      message.success("Sayaç kapatıldı");
      setKapatilan(null);
      for (const k of [["zaman-ozet"], ["zaman-aktif"], ["zaman-kayitlar"], ...ZAMAN_SORGULARI]) {
        void qc.invalidateQueries({ queryKey: k });
      }
    },
    onError: (e: ApiError) =>
      message.error(e.cakisma ? `${e.message} Gerekirse sayfayı yenileyin.` : e.message),
  });

  const kisiSecenekleri = useMemo(
    () =>
      (ozet.data?.personel ?? [])
        .filter((p) => p.user_id != null)
        .map((p) => ({ value: p.user_id as number, label: p.ad })),
    [ozet.data],
  );

  if (!yetkili("servis_rapor.gor")) return <Navigate to="/benim-islerim" replace />;

  const filtreDegisti = <T,>(f: (v: T) => void) => (v: T) => {
    f(v);
    setSayfa(1);
  };

  const birimSecenekleri = [
    { value: "", label: "Tüm birimler" },
    ...BIRIM_KODLARI.filter(
      (b) => kullanici?.role.scope === "TUMU" || !kullanici?.birimler?.length || kullanici.birimler.includes(b),
    ).map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] })),
  ];

  const kpiBasligi = ozet.data?.kpi.find((k) => k.kod === kpiKodu)?.baslik;
  const kpiSec = (kod?: string) => {
    if (kod) params.set("kpi", kod);
    else params.delete("kpi");
    setParams(params, { replace: true });
    setSayfa(1);
  };

  const kayitSutunlari = [
    { title: "İş No", dataIndex: "so_no", className: "mono" },
    ...(personelGorur ? [{ title: "Personel", dataIndex: "kisi_adi", ellipsis: true }] : []),
    {
      title: "Faaliyet",
      dataIndex: "faaliyet",
      render: (f: Faaliyet) => FAALIYET_ADLARI[f] ?? f,
    },
    { title: "Başlangıç", dataIndex: "started_at", render: an },
    { title: "Bitiş", dataIndex: "ended_at", render: (t: string | null) => (t ? an(t) : <Tag color="blue">Açık</Tag>) },
    {
      title: "Süre",
      dataIndex: "sure_dk",
      render: (d: number | null, r: ZamanKaydi) => (r.ended_at ? sure(d) : "—"),
    },
    {
      title: "Kaynak",
      dataIndex: "kaynak",
      render: (k: string, r: ZamanKaydi) => (
        <Space size={2} wrap>
          {KAYNAK_ADLARI[k] ?? k}
          {r.gecikmeli && <Tag color="orange">Gecikmeli</Tag>}
        </Space>
      ),
    },
    { title: "Birim", dataIndex: "birim", render: (b: string | null) => (b ? BIRIM_ETIKETLERI[b] ?? b : "—") },
  ];

  const aktifSutunlari = [
    ...(personelGorur ? [{ title: "Personel", dataIndex: "kisi_adi" }] : []),
    { title: "İş No", dataIndex: "so_no", className: "mono" },
    { title: "Faaliyet", dataIndex: "faaliyet", render: (f: Faaliyet) => FAALIYET_ADLARI[f] ?? f },
    { title: "Başlangıç", dataIndex: "started_at", render: an },
    {
      title: "Geçen",
      dataIndex: "gecen_dk",
      render: (d: number | null, r: ZamanKaydi) => (
        <Typography.Text type={r.uzun ? "danger" : undefined} strong={r.uzun}>
          {sureMetni(d) ?? "—"}
          {r.uzun ? " (uzun)" : ""}
        </Typography.Text>
      ),
    },
    ...(yonetici
      ? [
          {
            title: "",
            key: "islem",
            render: (_: unknown, r: ZamanKaydi) => (
              <Button
                size="small"
                danger={r.uzun}
                onClick={() => {
                  kapatForm.resetFields();
                  setKapatilan(r);
                }}
              >
                Kapat / Düzelt
              </Button>
            ),
          },
        ]
      : []),
  ];

  const personelSutunlari = [
    { title: "Personel", dataIndex: "ad", fixed: "left" as const },
    { title: "Kişi-saat", dataIndex: "kisi_saat_dk", render: sure },
    { title: "Yol", dataIndex: "yol_dk", render: (d: number | null) => sureMetni(d) ?? "—" },
    { title: "Saha", dataIndex: "saha_dk", render: (d: number | null) => sureMetni(d) ?? "—" },
    { title: "Bekleme", dataIndex: "bekleme_dk", render: (d: number | null) => sureMetni(d) ?? "—" },
    { title: "Mola (hariç)", dataIndex: "mola_dk", render: (d: number | null) => sureMetni(d) ?? "—" },
    { title: "İş", dataIndex: "is_sayisi" },
    {
      title: "Canlı oranı",
      dataIndex: "canli_orani",
      render: (o: number | null) => (o == null ? "—" : `%${o.toLocaleString("tr-TR")}`),
    },
    { title: "Manuel", dataIndex: "manuel_sayisi" },
    { title: "Gecikmeli manuel", dataIndex: "gecikmeli_manuel_sayisi" },
    { title: "Düzeltilen", dataIndex: "duzeltilen_sayisi" },
    { title: "İptal", dataIndex: "iptal_sayisi" },
    { title: "Geri alınan", dataIndex: "geri_alinan_sayisi" },
  ];

  const isSutunlari = [
    { title: "İş No", dataIndex: "so_no", className: "mono" },
    { title: "Konu", dataIndex: "konu", ellipsis: true },
    { title: "Birim", dataIndex: "birim", render: (b: string) => BIRIM_ETIKETLERI[b] ?? b },
    { title: "Tamamlanma", dataIndex: "completed_at", render: an },
    { title: "Kişi-saat", dataIndex: "kisi_saat_dk", render: sure },
    {
      title: "Süre kaydı",
      dataIndex: "sure_durumu",
      render: (d: string | null) => (d ? SURE_DURUMU_ADLARI[d] ?? d : "—"),
    },
  ];

  const ayrinti = isListesi ? isler : kayitlar;
  const suzgecMetni = ozet.data
    ? `${dayjs(ozet.data.suzgec.bas).format("DD.MM.YYYY")} – ${dayjs(ozet.data.suzgec.bit).format("DD.MM.YYYY")}`
    : "";

  return (
    <Card
      title="Saha / Zaman Takibi"
      extra={
        yetkili("servis_rapor.disaaktar") && (
          <Button
            icon={<DownloadOutlined />}
            onClick={() => window.open(zamanTakibi.excelYolu({ ...suzgec, kpi: isListesi ? undefined : kpiKodu }), "_blank")}
          >
            Excel
          </Button>
        )
      }
    >
      <Space wrap style={{ marginBottom: 12 }}>
        <DatePicker.RangePicker
          format="DD.MM.YYYY"
          value={aralik}
          onChange={filtreDegisti((v) => setAralik(v && v[0] && v[1] ? [v[0], v[1]] : null))}
          placeholder={["Son 31 gün", ""]}
          allowClear
        />
        <Select
          style={{ width: 170 }}
          value={birim ?? ""}
          options={birimSecenekleri}
          onChange={filtreDegisti((v: string) => setBirim(v || undefined))}
        />
        {personelGorur && (
          <Select
            style={{ width: 190 }}
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="Personel"
            value={kisi}
            options={kisiSecenekleri}
            onChange={filtreDegisti((v: number | undefined) => setKisi(v))}
          />
        )}
        <Select
          style={{ width: 150 }}
          allowClear
          placeholder="Faaliyet"
          value={faaliyet}
          options={Object.entries(FAALIYET_ADLARI).map(([value, label]) => ({ value, label }))}
          onChange={filtreDegisti((v: string | undefined) => setFaaliyet(v))}
        />
        <Typography.Text type="secondary">{suzgecMetni}</Typography.Text>
      </Space>

      {ozet.isError && <Alert type="error" showIcon message={(ozet.error as ApiError).message} style={{ marginBottom: 12 }} />}

      <Row gutter={[8, 8]} style={{ marginBottom: 16 }}>
        {(ozet.data?.kpi ?? []).map((k) => (
          <Col key={k.kod} xs={12} sm={8} md={6} xl={4}>
            <KpiKutusu
              kod={k.kod}
              baslik={k.baslik}
              tanim={k.tanim}
              deger={k.deger}
              vurgu={
                (k.kod === "uzun_sayac" || k.kod === "sure_eksik") && (k.deger ?? 0) > 0 ? "uyari" : "normal"
              }
              yol={k.liste ? `/zaman-takibi?kpi=${k.kod}` : "/zaman-takibi"}
              yukleniyor={ozet.isLoading}
            />
          </Col>
        ))}
      </Row>

      <Card size="small" title={`Şu an çalışanlar (${aktif.data?.sayaclar.length ?? 0})`} style={{ marginBottom: 16 }}>
        <Table
          size="small"
          rowKey="id"
          loading={aktif.isLoading}
          dataSource={aktif.data?.sayaclar ?? []}
          columns={aktifSutunlari}
          pagination={false}
          scroll={{ x: 560 }}
          locale={{ emptyText: <Empty description="Açık sayaç yok" /> }}
          onRow={(r) => (r.uzun ? { style: { background: "#fff1f0" } } : {})}
        />
      </Card>

      {ozet.data?.personel && (
        <Card size="small" title="Personel dağılımı ve veri disiplini" style={{ marginBottom: 16 }}>
          <Table<PersonelSatiri>
            size="small"
            rowKey={(r) => String(r.user_id ?? r.ad)}
            dataSource={ozet.data.personel}
            columns={personelSutunlari}
            pagination={false}
            scroll={{ x: 1100 }}
          />
        </Card>
      )}

      <Card
        size="small"
        title={
          <Space wrap>
            <span>Ayrıntı</span>
            {kpiKodu && (
              <Tag closable onClose={() => kpiSec(undefined)} color="blue">
                {kpiBasligi ?? kpiKodu}
              </Tag>
            )}
            <Typography.Text type="secondary">{ayrinti.data ? `${ayrinti.data.toplam} kayıt` : ""}</Typography.Text>
          </Space>
        }
      >
        {ayrinti.isError ? (
          <Empty description={(ayrinti.error as ApiError).message} />
        ) : isListesi ? (
          <Table<ZamanIsi>
            size="small"
            rowKey="id"
            loading={isler.isLoading}
            dataSource={isler.data?.kayitlar ?? []}
            columns={isSutunlari}
            scroll={{ x: 640 }}
            pagination={{
              current: sayfa,
              pageSize: SAYFA,
              total: isler.data?.toplam ?? 0,
              onChange: setSayfa,
              showSizeChanger: false,
              showTotal: (t) => `${t} iş`,
            }}
          />
        ) : (
          <Table<ZamanKaydi>
            size="small"
            rowKey="id"
            loading={kayitlar.isLoading}
            dataSource={kayitlar.data?.kayitlar ?? []}
            columns={kayitSutunlari}
            scroll={{ x: 760 }}
            pagination={{
              current: sayfa,
              pageSize: SAYFA,
              total: kayitlar.data?.toplam ?? 0,
              onChange: setSayfa,
              showSizeChanger: false,
              showTotal: (t) => `${t} kayıt`,
            }}
          />
        )}
      </Card>

      <Modal
        open={kapatilan !== null}
        title={`Sayacı kapat / düzelt — ${kapatilan?.so_no ?? ""}`}
        okText="Kaydet"
        cancelText="Vazgeç"
        confirmLoading={kapat.isPending}
        onCancel={() => setKapatilan(null)}
        onOk={() => void kapatForm.validateFields().then((v) => kapat.mutate(v))}
      >
        <Typography.Paragraph type="secondary">
          Gerçek bitiş girilirse bölüm o saatte kapanır (yönetici düzeltmesi). Boş bırakılırsa sayaç
          İPTAL edilir ve kişi-saate girmez.
        </Typography.Paragraph>
        <Form form={kapatForm} layout="vertical">
          <Form.Item name="gercek_bitis" label="Gerçek bitiş (isteğe bağlı)">
            <DatePicker
              showTime={{ format: "HH:mm" }}
              format="DD.MM.YYYY HH:mm"
              style={{ width: "100%" }}
              disabledDate={(d) =>
                d.isAfter(dayjs(), "day") || (!!kapatilan && d.isBefore(dayjs(kapatilan.started_at), "day"))
              }
            />
          </Form.Item>
          <Form.Item name="gerekce" label="Gerekçe" rules={[{ required: true, whitespace: true, message: "Gerekçe zorunlu" }]}>
            <Input.TextArea maxLength={300} autoSize={{ minRows: 2, maxRows: 4 }} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
