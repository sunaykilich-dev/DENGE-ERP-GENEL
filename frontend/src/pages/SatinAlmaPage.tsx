import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  DatePicker,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import { api, type ApiError } from "../api/client";
import Statistic from "../components/Statistic";
import { useAuth } from "../auth/AuthContext";

interface Kalem {
  id: number;
  product_id: number;
  urun_kodu: string | null;
  /** IMEI | SERI_NO | YOK — YOK ise mal kabul adetle (TS-196). */
  kimlik_turu?: string | null;
  description: string | null;
  qty: number;
  unit_price: number;
  qty_received: number;
  unit_weight_kg: number | null;
}

interface Siparis {
  id: number;
  po_no: string;
  supplier_id: number;
  supplier_title: string | null;
  status: string;
  order_date: string;
  expected_date: string | null;
  currency: string;
  fx_rate: number | null;
  subtotal: number;
  notes: string | null;
  version: number;
  sonraki_durumlar: string[];
  kalemler: Kalem[];
}

interface Ithalat {
  id: number;
  file_no: string;
  purchase_order_id: number | null;
  status: string;
  invoice_no: string | null;
  customs_declaration_no: string | null;
  currency: string;
  goods_value_try: number;
  freight_try: number;
  insurance_try: number;
  customs_duty_try: number;
  other_tax_try: number;
  broker_fee_try: number;
  inland_freight_try: number;
  other_cost_try: number;
  allocation_key: string;
  allocated_at: string | null;
  allocated_device_count: number;
  notes: string | null;
  version: number;
  toplam_masraf: number;
}

interface IthalatCihazi {
  device_id: number;
  kimlik: string | null;
  status: string;
  btk_status: string;
  landed_cost_try: number | null;
}

interface BtkSatiri {
  device_id: number;
  imei: string | null;
  serial_no: string | null;
  urun_kodu: string;
  urun_adi: string;
  ce_belgesi: string | null;
  tse_belgesi: string | null;
  uygunluk_belgesi: string | null;
  ithalat_dosyasi: string | null;
  gumruk_beyanname: string | null;
}

interface Hesap {
  id: number;
  title: string;
}

interface Urun {
  id: number;
  code: string;
  name: string;
}

const tl = (v: number | null | undefined) =>
  v == null ? "—" : `${Number(v).toLocaleString("tr-TR", { minimumFractionDigits: 2 })} ₺`;

const DURUM_RENGI: Record<string, string> = {
  TASLAK: "default",
  SIPARIS_VERILDI: "blue",
  KISMI_TESLIM: "orange",
  TESLIM_ALINDI: "green",
  IPTAL: "red",
};

const MASRAF_ALANLARI: { alan: keyof Ithalat; etiket: string }[] = [
  { alan: "goods_value_try", etiket: "Mal bedeli" },
  { alan: "freight_try", etiket: "Navlun" },
  { alan: "insurance_try", etiket: "Sigorta" },
  { alan: "customs_duty_try", etiket: "Gümrük vergisi" },
  { alan: "other_tax_try", etiket: "İlave vergiler" },
  { alan: "broker_fee_try", etiket: "Gümrük müşaviri" },
  { alan: "inland_freight_try", etiket: "İç nakliye" },
  { alan: "other_cost_try", etiket: "Diğer" },
];

export default function SatinAlmaPage() {
  const qc = useQueryClient();
  const { message, modal } = App.useApp();
  const { yetkili } = useAuth();
  const [secili, setSecili] = useState<number | null>(null);
  const [dosyaSecili, setDosyaSecili] = useState<number | null>(null);
  const [yeniAcik, setYeniAcik] = useState(false);
  const [dosyaAcik, setDosyaAcik] = useState(false);
  const [btkSecim, setBtkSecim] = useState<number[]>([]);
  const [yeniForm] = Form.useForm();
  const [dosyaForm] = Form.useForm();

  const siparisler = useQuery({
    queryKey: ["sa-siparisler"],
    queryFn: () => api.get<Siparis[]>("/api/satinalma/siparisler"),
  });

  const detay = useQuery({
    queryKey: ["sa-siparis", secili],
    queryFn: () => api.get<Siparis>(`/api/satinalma/siparisler/${secili}`),
    enabled: secili != null,
  });

  const dosyalar = useQuery({
    queryKey: ["sa-ithalat"],
    queryFn: () => api.get<Ithalat[]>("/api/satinalma/ithalat"),
  });

  const dosyaCihazlari = useQuery({
    queryKey: ["sa-ithalat-cihaz", dosyaSecili],
    queryFn: () => api.get<IthalatCihazi[]>(`/api/satinalma/ithalat/${dosyaSecili}/cihazlar`),
    enabled: dosyaSecili != null,
  });

  const btk = useQuery({
    queryKey: ["sa-btk"],
    queryFn: () => api.get<BtkSatiri[]>("/api/satinalma/btk/bekleyenler"),
  });

  const tedarikciler = useQuery({
    queryKey: ["hesaplar-tedarikci"],
    queryFn: () => api.get<Hesap[]>("/api/hesaplar?rol=TEDARIKCI&limit=200"),
  });

  const urunler = useQuery({
    queryKey: ["urunler-satinalma"],
    queryFn: () => api.get<Urun[]>("/api/urunler?limit=500"),
  });

  // Serisiz mal kabulün hedef deposu (TS-196): mobilite depoları + (yetkiliyse) servis depoları.
  const mobiliteDepolari = useQuery({
    queryKey: ["stok-depolar"],
    queryFn: () => api.get<{ id: number; code: string; name: string }[]>("/api/stok/depolar"),
  });
  const servisDepolari = useQuery({
    queryKey: ["parca", "depolar", false],
    queryFn: () =>
      api.get<{ id: number; code: string; name: string; is_active: boolean }[]>(
        "/api/teknik-servis/parca/depolar?pasifler=false",
      ),
    enabled: yetkili("parca.gor"),
  });
  const depoSecenekleri = [
    ...(mobiliteDepolari.data ?? []).map((d) => ({
      value: d.id,
      label: `${d.code} · ${d.name}`,
    })),
    ...(servisDepolari.data ?? []).map((d) => ({
      value: d.id,
      label: `Servis · ${d.code} · ${d.name}`,
    })),
  ];

  const yenile = () => {
    for (const k of ["sa-siparisler", "sa-siparis", "sa-ithalat", "sa-ithalat-cihaz", "sa-btk"]) {
      void qc.invalidateQueries({ queryKey: [k] });
    }
  };

  const hata = (e: ApiError) => void message.error(e.message);

  const siparisAc = useMutation({
    mutationFn: (v: Record<string, unknown>) => api.post<Siparis>("/api/satinalma/siparisler", v),
    onSuccess: (s) => {
      message.success(`${s.po_no} oluşturuldu`);
      setYeniAcik(false);
      yeniForm.resetFields();
      setSecili(s.id);
      yenile();
    },
    onError: hata,
  });

  const durumDegistir = useMutation({
    mutationFn: ({ id, durum }: { id: number; durum: string }) =>
      api.post(`/api/satinalma/siparisler/${id}/durum`, { durum }),
    onSuccess: () => {
      message.success("Durum güncellendi");
      yenile();
    },
    onError: hata,
  });

  const malKabul = useMutation({
    mutationFn: ({ id, ...v }: { id: number } & Record<string, unknown>) =>
      api.post<{ fis_no: string; adet: number }>(`/api/satinalma/siparisler/${id}/mal-kabul`, v),
    onSuccess: (r) => {
      message.success(`${r.fis_no} · ${r.adet} adet stoğa alındı`);
      yenile();
    },
    onError: hata,
  });

  const dosyaAc = useMutation({
    mutationFn: (v: Record<string, unknown>) => api.post<Ithalat>("/api/satinalma/ithalat", v),
    onSuccess: (d) => {
      message.success(`${d.file_no} açıldı`);
      setDosyaAcik(false);
      dosyaForm.resetFields();
      setDosyaSecili(d.id);
      yenile();
    },
    onError: hata,
  });

  const landedCost = useMutation({
    mutationFn: (id: number) =>
      api.post<{ cihaz_sayisi: number; birim_ortalama: number }>(
        `/api/satinalma/ithalat/${id}/landed-cost`,
      ),
    onSuccess: (r) => {
      message.success(`${r.cihaz_sayisi} cihaza dağıtıldı · ortalama ${tl(r.birim_ortalama)}`);
      yenile();
    },
    onError: hata,
  });

  const btkKaydet = useMutation({
    mutationFn: (v: { device_ids: number[]; referans?: string }) =>
      api.post<{ kaydedilen: number }>("/api/satinalma/btk/kaydet", v),
    onSuccess: (r) => {
      message.success(`${r.kaydedilen} cihaz BTK'da kayıtlı işaretlendi`);
      setBtkSecim([]);
      yenile();
    },
    onError: hata,
  });

  const s = detay.data;
  const dosya = (dosyalar.data ?? []).find((d) => d.id === dosyaSecili) ?? null;

  function serisizKabulSor(siparis: Siparis, kalem: Kalem) {
    const kalan = Number(kalem.qty) - Number(kalem.qty_received);
    let adet: number | null = kalan > 0 ? kalan : null;
    let depoId: number | undefined;
    modal.confirm({
      title: `Mal kabul (serisiz) · ${kalem.urun_kodu ?? ""}`,
      width: 520,
      content: (
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Typography.Text type="secondary">
            Kalan adet: {kalan}. Servis deposu seçilirse birim maliyet TL'ye çevrilip dondurulur.
          </Typography.Text>
          <InputNumber
            min={1}
            max={kalan > 0 ? kalan : undefined}
            precision={0}
            defaultValue={adet ?? undefined}
            placeholder="Adet"
            style={{ width: "100%" }}
            onChange={(v) => (adet = typeof v === "number" ? v : null)}
          />
          <Select
            allowClear
            placeholder="Depo"
            style={{ width: "100%" }}
            options={depoSecenekleri}
            onChange={(v) => (depoId = v)}
          />
        </Space>
      ),
      okText: "Stoğa al",
      cancelText: "Vazgeç",
      onOk: () => {
        if (!adet || adet <= 0) {
          message.error("Adet girilmeli");
          return Promise.reject();
        }
        return malKabul.mutateAsync({
          id: siparis.id,
          kalem_id: kalem.id,
          adet,
          warehouse_id: depoId,
        });
      },
    });
  }

  function malKabulSor(siparis: Siparis, kalem: Kalem) {
    if (kalem.kimlik_turu === "YOK") {
      serisizKabulSor(siparis, kalem);
      return;
    }
    let kimlikler = "";
    let dosyaId: number | undefined;
    modal.confirm({
      title: `Mal kabul · ${kalem.urun_kodu ?? ""}`,
      width: 560,
      content: (
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Typography.Text type="secondary">
            Kalan adet: {Number(kalem.qty) - Number(kalem.qty_received)}. İthalat dosyası seçilirse
            cihazlar İTHALATTA doğar ve BTK kaydı bekler.
          </Typography.Text>
          <Select
            allowClear
            placeholder="İthalat dosyası (isteğe bağlı)"
            style={{ width: "100%" }}
            options={(dosyalar.data ?? []).map((d) => ({
              value: d.id,
              label: `${d.file_no}${d.invoice_no ? ` · ${d.invoice_no}` : ""}`,
            }))}
            onChange={(v) => (dosyaId = v)}
          />
          <Input.TextArea
            rows={6}
            placeholder={"IMEI / seri no listesi — her satıra bir tane"}
            onChange={(e) => (kimlikler = e.target.value)}
          />
        </Space>
      ),
      okText: "Stoğa al",
      cancelText: "Vazgeç",
      onOk: () => {
        const liste = kimlikler
          .split(/[\n,;\t]/)
          .map((x) => x.trim())
          .filter(Boolean);
        if (liste.length === 0) {
          message.error("Kimlik listesi boş");
          return Promise.reject();
        }
        return malKabul.mutateAsync({
          id: siparis.id,
          kalem_id: kalem.id,
          kimlikler: liste,
          import_file_id: dosyaId,
        });
      },
    });
  }

  function btkKaydetSor() {
    let referans = "";
    modal.confirm({
      title: `${btkSecim.length} cihaz BTK'da kayıtlı işaretlensin mi?`,
      content: (
        <Input
          placeholder="BTK referans / başvuru no"
          onChange={(e) => (referans = e.target.value)}
        />
      ),
      okText: "Kaydet",
      cancelText: "Vazgeç",
      onOk: () =>
        btkKaydet.mutateAsync({
          device_ids: btkSecim,
          referans: referans || undefined,
        }),
    });
  }

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Tabs
        defaultActiveKey="siparisler"
        items={[
          {
            key: "siparisler",
            label: "Satın alma siparişleri",
            children: (
              <Card
                title="Satın alma"
                extra={
                  yetkili("satinalma.yaz") && (
                    <Button type="primary" onClick={() => setYeniAcik(true)}>
                      Yeni sipariş
                    </Button>
                  )
                }
              >
                <Table
                  rowKey="id"
                  size="small"
                  loading={siparisler.isLoading}
                  dataSource={siparisler.data ?? []}
                  pagination={{ pageSize: 20, showSizeChanger: false }}
                  scroll={{ x: 900 }}
                  onRow={(r) => ({
                    onClick: () => setSecili(r.id),
                    style: { cursor: "pointer" },
                  })}
                  columns={[
                    {
                      title: "Sipariş no",
                      dataIndex: "po_no",
                      width: 140,
                      className: "mono",
                    },
                    {
                      title: "Tedarikçi",
                      dataIndex: "supplier_title",
                      width: 240,
                      ellipsis: true,
                    },
                    {
                      title: "Tarih",
                      dataIndex: "order_date",
                      width: 110,
                      className: "mono",
                      render: (x: string) => dayjs(x).format("DD.MM.YYYY"),
                    },
                    {
                      title: "Tutar",
                      width: 150,
                      className: "tutar",
                      render: (_: unknown, r: Siparis) => (
                        <strong>
                          {Number(r.subtotal).toLocaleString("tr-TR", {
                            minimumFractionDigits: 2,
                          })}{" "}
                          {r.currency}
                        </strong>
                      ),
                    },
                    {
                      title: "Durum",
                      dataIndex: "status",
                      width: 150,
                      render: (x: string) => (
                        <Tag color={DURUM_RENGI[x]}>{x.replaceAll("_", " ").toLowerCase()}</Tag>
                      ),
                    },
                  ]}
                />
              </Card>
            ),
          },
          {
            key: "ithalat",
            label: "İthalat dosyaları",
            children: (
              <Space orientation="vertical" size={16} style={{ width: "100%" }}>
                <Card
                  title="İthalat dosyaları"
                  extra={
                    yetkili("satinalma.yaz") && (
                      <Button type="primary" onClick={() => setDosyaAcik(true)}>
                        Yeni dosya
                      </Button>
                    )
                  }
                >
                  <Table
                    rowKey="id"
                    size="small"
                    loading={dosyalar.isLoading}
                    dataSource={dosyalar.data ?? []}
                    pagination={false}
                    locale={{
                      emptyText: <Empty description="İthalat dosyası yok" />,
                    }}
                    onRow={(r) => ({
                      onClick: () => setDosyaSecili(r.id),
                      style: { cursor: "pointer" },
                    })}
                    columns={[
                      {
                        title: "Dosya no",
                        dataIndex: "file_no",
                        width: 140,
                        className: "mono",
                      },
                      {
                        title: "Fatura",
                        dataIndex: "invoice_no",
                        width: 180,
                        ellipsis: true,
                        render: (x: string | null) => x ?? "—",
                      },
                      {
                        title: "Beyanname",
                        dataIndex: "customs_declaration_no",
                        width: 150,
                        className: "mono",
                        render: (x: string | null) => x ?? "—",
                      },
                      {
                        title: "Toplam masraf",
                        dataIndex: "toplam_masraf",
                        width: 160,
                        className: "tutar",
                        render: (x: number) => <strong>{tl(x)}</strong>,
                      },
                      {
                        title: "Dağıtım",
                        width: 170,
                        render: (_: unknown, d: Ithalat) =>
                          d.allocated_at ? (
                            <Tag color="green">
                              {d.allocated_device_count} cihaz · {d.allocation_key.toLowerCase()}
                            </Tag>
                          ) : (
                            <Tag>dağıtılmadı</Tag>
                          ),
                      },
                    ]}
                  />
                </Card>

                {dosya && (
                  <Card
                    title={`${dosya.file_no} · masraf dökümü`}
                    extra={
                      yetkili("satinalma.yaz") && (
                        <Button
                          type="primary"
                          loading={landedCost.isPending}
                          onClick={() => landedCost.mutate(dosya.id)}
                        >
                          Landed cost dağıt
                        </Button>
                      )
                    }
                  >
                    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
                      <Descriptions size="small" bordered column={{ xs: 1, sm: 2, xl: 4 }}>
                        {MASRAF_ALANLARI.map((m) => (
                          <Descriptions.Item key={m.alan} label={m.etiket} className="tutar">
                            {tl(dosya[m.alan] as number)}
                          </Descriptions.Item>
                        ))}
                      </Descriptions>
                      <Space size={40} wrap>
                        <Statistic
                          title="Toplam masraf"
                          value={Number(dosya.toplam_masraf)}
                          formatter={(v) => tl(Number(v))}
                        />
                        <Statistic
                          title="Dağıtım anahtarı"
                          value={dosya.allocation_key.toLowerCase()}
                        />
                        <Statistic title="Cihaz" value={(dosyaCihazlari.data ?? []).length} />
                      </Space>
                      <Alert
                        type="info"
                        title="Yuvarlama artığı kaybolmaz"
                        description="Kuruş farkı son cihaza yazılır; dosya toplamı ile cihaz maliyetleri toplamı daima eşittir."
                      />
                      <Table
                        rowKey="device_id"
                        size="small"
                        loading={dosyaCihazlari.isLoading}
                        dataSource={dosyaCihazlari.data ?? []}
                        pagination={{ pageSize: 15, showSizeChanger: false }}
                        scroll={{ x: 700 }}
                        locale={{
                          emptyText: <Empty description="Dosyaya bağlı cihaz yok" />,
                        }}
                        columns={[
                          {
                            title: "Kimlik",
                            dataIndex: "kimlik",
                            className: "mono",
                          },
                          { title: "Durum", dataIndex: "status", width: 140 },
                          {
                            title: "BTK",
                            dataIndex: "btk_status",
                            width: 120,
                            render: (x: string) => (
                              <Tag color={x === "KAYITLI" ? "green" : "gold"}>
                                {x.toLowerCase()}
                              </Tag>
                            ),
                          },
                          {
                            title: "Birim maliyet",
                            dataIndex: "landed_cost_try",
                            width: 160,
                            className: "tutar",
                            render: (x: number | null) =>
                              x == null ? (
                                <Typography.Text type="secondary">gizli</Typography.Text>
                              ) : (
                                tl(x)
                              ),
                          },
                        ]}
                      />
                    </Space>
                  </Card>
                )}
              </Space>
            ),
          },
          {
            key: "btk",
            label: `BTK${btk.data?.length ? ` (${btk.data.length})` : ""}`,
            children: (
              <Card
                title="BTK IMEI kaydı bekleyenler"
                extra={
                  <Space>
                    {yetkili("rapor.disaaktar") && (
                      <Button
                        onClick={() => window.open("/api/satinalma/btk/bekleyenler.xlsx", "_blank")}
                      >
                        Excel
                      </Button>
                    )}
                    {yetkili("satinalma.yaz") && (
                      <Button
                        type="primary"
                        disabled={btkSecim.length === 0}
                        onClick={btkKaydetSor}
                      >
                        {btkSecim.length} cihazı kayıtlı işaretle
                      </Button>
                    )}
                  </Space>
                }
              >
                <Table
                  rowKey="device_id"
                  size="small"
                  loading={btk.isLoading}
                  dataSource={btk.data ?? []}
                  pagination={{ pageSize: 25, showSizeChanger: false }}
                  locale={{
                    emptyText: <Empty description="BTK kaydı bekleyen cihaz yok" />,
                  }}
                  rowSelection={{
                    selectedRowKeys: btkSecim,
                    onChange: (k) => setBtkSecim(k as number[]),
                  }}
                  columns={[
                    {
                      title: "Kimlik",
                      className: "mono",
                      render: (_: unknown, r: BtkSatiri) => r.imei ?? r.serial_no ?? "—",
                    },
                    {
                      title: "Ürün",
                      dataIndex: "urun_kodu",
                      width: 170,
                      className: "mono",
                    },
                    {
                      title: "CE",
                      dataIndex: "ce_belgesi",
                      width: 140,
                      render: (x: string | null) =>
                        x ?? <Typography.Text type="danger">yok</Typography.Text>,
                    },
                    {
                      title: "TSE",
                      dataIndex: "tse_belgesi",
                      width: 140,
                      render: (x: string | null) => x ?? "—",
                    },
                    {
                      title: "İthalat dosyası",
                      dataIndex: "ithalat_dosyasi",
                      width: 140,
                      className: "mono",
                      render: (x: string | null) => x ?? "—",
                    },
                    {
                      title: "Beyanname",
                      dataIndex: "gumruk_beyanname",
                      width: 140,
                      className: "mono",
                      render: (x: string | null) => x ?? "—",
                    },
                  ]}
                />
              </Card>
            ),
          },
        ]}
      />

      <Drawer
        title={s ? `${s.po_no} · ${s.supplier_title ?? ""}` : "Satın alma siparişi"}
        open={secili != null}
        size={820}
        onClose={() => setSecili(null)}
        loading={detay.isLoading}
        extra={
          s &&
          yetkili("satinalma.yaz") && (
            <Space>
              {s.sonraki_durumlar
                .filter((d) => d === "SIPARIS_VERILDI" || d === "IPTAL")
                .map((d) => (
                  <Button
                    key={d}
                    type={d === "SIPARIS_VERILDI" ? "primary" : "default"}
                    danger={d === "IPTAL"}
                    onClick={() => durumDegistir.mutate({ id: s.id, durum: d })}
                  >
                    {d === "SIPARIS_VERILDI" ? "Sipariş ver" : "İptal"}
                  </Button>
                ))}
            </Space>
          )
        }
      >
        {s && (
          <Space orientation="vertical" size={16} style={{ width: "100%" }}>
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="Durum">
                <Tag color={DURUM_RENGI[s.status]}>{s.status.replaceAll("_", " ")}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Sipariş tarihi">
                {dayjs(s.order_date).format("DD.MM.YYYY")}
              </Descriptions.Item>
              <Descriptions.Item label="Para birimi">
                {s.currency}
                {s.fx_rate ? ` · kur ${s.fx_rate}` : ""}
              </Descriptions.Item>
              <Descriptions.Item label="Tutar" className="tutar">
                <strong>
                  {Number(s.subtotal).toLocaleString("tr-TR", {
                    minimumFractionDigits: 2,
                  })}{" "}
                  {s.currency}
                </strong>
              </Descriptions.Item>
            </Descriptions>

            <Card size="small" title="Kalemler">
              <Table
                rowKey="id"
                size="small"
                dataSource={s.kalemler}
                pagination={false}
                columns={[
                  {
                    title: "Ürün",
                    dataIndex: "urun_kodu",
                    width: 170,
                    className: "mono",
                  },
                  {
                    title: "Adet",
                    dataIndex: "qty",
                    width: 80,
                    className: "mono",
                  },
                  {
                    title: "Birim fiyat",
                    dataIndex: "unit_price",
                    width: 130,
                    className: "tutar",
                    render: (x: number) =>
                      `${Number(x).toLocaleString("tr-TR", { minimumFractionDigits: 2 })} ${
                        s.currency
                      }`,
                  },
                  {
                    title: "Teslim",
                    width: 110,
                    className: "mono",
                    render: (_: unknown, k: Kalem) =>
                      `${Number(k.qty_received)} / ${Number(k.qty)}`,
                  },
                  {
                    title: "",
                    width: 120,
                    render: (_: unknown, k: Kalem) =>
                      yetkili("satinalma.yaz") &&
                      ["SIPARIS_VERILDI", "KISMI_TESLIM"].includes(s.status) &&
                      Number(k.qty_received) < Number(k.qty) ? (
                        <Button size="small" onClick={() => malKabulSor(s, k)}>
                          Mal kabul
                        </Button>
                      ) : null,
                  },
                ]}
              />
            </Card>
          </Space>
        )}
      </Drawer>

      <Drawer
        title="Yeni satın alma siparişi"
        open={yeniAcik}
        size={700}
        onClose={() => setYeniAcik(false)}
        extra={
          <Button type="primary" onClick={() => yeniForm.submit()} loading={siparisAc.isPending}>
            Oluştur
          </Button>
        }
      >
        <Form
          form={yeniForm}
          layout="vertical"
          initialValues={{ currency: "USD" }}
          onFinish={(v) =>
            siparisAc.mutate({
              ...v,
              order_date: v.order_date ? dayjs(v.order_date).format("YYYY-MM-DD") : undefined,
              expected_date: v.expected_date
                ? dayjs(v.expected_date).format("YYYY-MM-DD")
                : undefined,
            })
          }
        >
          <Form.Item
            name="supplier_id"
            label="Tedarikçi"
            rules={[{ required: true, message: "Tedarikçi seçin" }]}
          >
            <Select
              showSearch
              optionFilterProp="label"
              loading={tedarikciler.isLoading}
              options={(tedarikciler.data ?? []).map((t) => ({
                value: t.id,
                label: t.title,
              }))}
            />
          </Form.Item>
          <Space>
            <Form.Item name="currency" label="Para birimi">
              <Select
                style={{ width: 110 }}
                options={["USD", "EUR", "TRY", "CNY"].map((c) => ({
                  value: c,
                  label: c,
                }))}
              />
            </Form.Item>
            <Form.Item name="fx_rate" label="Kur">
              <InputNumber min={0} step={0.01} style={{ width: 130 }} />
            </Form.Item>
            <Form.Item name="order_date" label="Sipariş tarihi">
              <DatePicker format="DD.MM.YYYY" />
            </Form.Item>
            <Form.Item name="expected_date" label="Beklenen">
              <DatePicker format="DD.MM.YYYY" />
            </Form.Item>
          </Space>

          <Typography.Title level={5}>Kalemler</Typography.Title>
          <Form.List name="kalemler">
            {(alanlar, { add, remove }) => (
              <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                {alanlar.map(({ key, name, ...rest }) => (
                  <Space key={key} align="start" wrap>
                    <Form.Item
                      {...rest}
                      name={[name, "product_id"]}
                      noStyle
                      rules={[{ required: true, message: "Ürün seçin" }]}
                    >
                      <Select
                        showSearch
                        placeholder="Ürün"
                        style={{ width: 280 }}
                        optionFilterProp="label"
                        options={(urunler.data ?? []).map((u) => ({
                          value: u.id,
                          label: `${u.code} · ${u.name}`,
                        }))}
                      />
                    </Form.Item>
                    <Form.Item {...rest} name={[name, "qty"]} noStyle initialValue={1}>
                      <InputNumber placeholder="Adet" style={{ width: 90 }} min={0.01} />
                    </Form.Item>
                    <Form.Item {...rest} name={[name, "unit_price"]} noStyle>
                      <InputNumber placeholder="Birim fiyat" style={{ width: 130 }} min={0} />
                    </Form.Item>
                    <Form.Item {...rest} name={[name, "unit_weight_kg"]} noStyle>
                      <InputNumber placeholder="Ağırlık kg" style={{ width: 120 }} min={0} />
                    </Form.Item>
                    <Button danger type="text" onClick={() => remove(name)}>
                      Sil
                    </Button>
                  </Space>
                ))}
                <Button onClick={() => add({ qty: 1 })}>Kalem ekle</Button>
                <Typography.Text type="secondary">
                  Ağırlık yalnız landed cost dağıtımı için; girilmezse ağırlık anahtarı
                  kullanılamaz.
                </Typography.Text>
              </Space>
            )}
          </Form.List>
        </Form>
      </Drawer>

      <Drawer
        title="Yeni ithalat dosyası"
        open={dosyaAcik}
        size={560}
        onClose={() => setDosyaAcik(false)}
        extra={
          <Button type="primary" onClick={() => dosyaForm.submit()} loading={dosyaAc.isPending}>
            Oluştur
          </Button>
        }
      >
        <Form
          form={dosyaForm}
          layout="vertical"
          initialValues={{ allocation_key: "TUTAR", currency: "USD" }}
          onFinish={(v) =>
            dosyaAc.mutate({
              ...v,
              invoice_date: v.invoice_date ? dayjs(v.invoice_date).format("YYYY-MM-DD") : undefined,
            })
          }
        >
          <Form.Item name="purchase_order_id" label="Satın alma siparişi">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              options={(siparisler.data ?? []).map((x) => ({
                value: x.id,
                label: `${x.po_no} · ${x.supplier_title ?? ""}`,
              }))}
            />
          </Form.Item>
          <Space>
            <Form.Item name="invoice_no" label="Fatura no">
              <Input style={{ width: 200 }} />
            </Form.Item>
            <Form.Item name="invoice_date" label="Fatura tarihi">
              <DatePicker format="DD.MM.YYYY" />
            </Form.Item>
            <Form.Item name="incoterm" label="Incoterm">
              <Select
                allowClear
                style={{ width: 110 }}
                options={["FOB", "CIF", "EXW", "DAP", "DDP"].map((c) => ({
                  value: c,
                  label: c,
                }))}
              />
            </Form.Item>
          </Space>
          <Form.Item name="customs_declaration_no" label="Gümrük beyanname no">
            <Input />
          </Form.Item>

          <Typography.Title level={5}>Masraflar (TL)</Typography.Title>
          <Space wrap>
            {MASRAF_ALANLARI.map((m) => (
              <Form.Item key={m.alan} name={m.alan} label={m.etiket} initialValue={0}>
                <InputNumber min={0} style={{ width: 160 }} />
              </Form.Item>
            ))}
          </Space>

          <Form.Item
            name="allocation_key"
            label="Dağıtım anahtarı"
            extra="Navlun ağırlıkla, gümrük vergisi mal bedeliyle, müşavirlik adetle orantılıdır."
          >
            <Select
              style={{ width: 220 }}
              options={[
                { value: "TUTAR", label: "Mal bedeline göre" },
                { value: "ADET", label: "Adete göre" },
                { value: "AGIRLIK", label: "Ağırlığa göre" },
              ]}
            />
          </Form.Item>
          <Form.Item name="notes" label="Not">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Drawer>
    </Space>
  );
}
