import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  DatePicker,
  Descriptions,
  Drawer,
  Input,
  InputNumber,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import { api, type ApiError } from "../api/client";
import Statistic from "../components/Statistic";
import HakEdisPaneli from "./HakEdisPaneli";
import IsEmriFormu from "./IsEmriFormu";
import { useAuth } from "../auth/AuthContext";

interface Satir {
  id: number;
  work_type: string;
  description: string | null;
  unit_price: number;
  quantity: number;
  amount: number;
  price_source: string | null;
  is_deduction: boolean;
  deduction_reason: string | null;
  locked_at: string | null;
}

interface Dokum {
  id: number;
  partner_id: number;
  partner_title: string | null;
  billing_title: string | null;
  belge_tipi: string | null;
  period: string;
  status: string;
  sonraki_durumlar: string[];
  gross_amount: number;
  deduction_amount: number;
  withholding_amount: number;
  stamp_tax_amount: number;
  vat_amount: number;
  net_payable: number;
  tax_snapshot: Record<string, unknown> | null;
  partner_document_no: string | null;
  satir_adedi: number;
  eksik_alanlar: string[];
  satirlar?: Satir[];
  sent_at: string | null;
  paid_at: string | null;
}

const tl = (v: number | null | undefined) =>
  v == null ? "—" : `${Number(v).toLocaleString("tr-TR", { minimumFractionDigits: 2 })} ₺`;

const DURUM_RENGI: Record<string, string> = {
  TASLAK: "default",
  ONAY_BEKLIYOR: "gold",
  ONAYLANDI: "blue",
  ITIRAZDA: "red",
  ODEME_BEKLIYOR: "cyan",
  ODENDI: "green",
};

export default function HakEdisPage() {
  const qc = useQueryClient();
  const { message, modal } = App.useApp();
  const { yetkili } = useAuth();
  const [donem, setDonem] = useState<string | undefined>();
  const [secili, setSecili] = useState<number | null>(null);

  const ozet = useQuery({
    queryKey: ["hakedis-ozet"],
    queryFn: () => api.get<{ donem: string; dokum: number; brut: number; net: number }[]>(
      "/api/hakedis/ozet",
    ),
  });

  const dokumler = useQuery({
    queryKey: ["hakedis", donem],
    queryFn: () => api.get<Dokum[]>(`/api/hakedis${donem ? `?donem=${donem}` : ""}`),
  });

  const detay = useQuery({
    queryKey: ["hakedis-detay", secili],
    queryFn: () => api.get<Dokum>(`/api/hakedis/${secili}`),
    enabled: secili != null,
  });

  const yenile = () => {
    void qc.invalidateQueries({ queryKey: ["hakedis"] });
    void qc.invalidateQueries({ queryKey: ["hakedis-detay"] });
    void qc.invalidateQueries({ queryKey: ["hakedis-ozet"] });
  };

  const durumDegistir = useMutation({
    mutationFn: ({ id, to_status }: { id: number; to_status: string }) =>
      api.post(`/api/hakedis/${id}/durum`, { to_status }),
    onSuccess: () => {
      message.success("Durum güncellendi");
      yenile();
    },
    onError: (e: ApiError) => message.error(e.message),
  });

  const gonder = useMutation({
    mutationFn: (id: number) => api.post(`/api/hakedis/${id}/gonder`),
    onSuccess: () => {
      message.success("Döküm e-posta ile gönderildi");
      yenile();
    },
    onError: (e: ApiError) => message.error(e.message),
  });

  const kesinti = useMutation({
    mutationFn: ({ id, ...v }: { id: number; amount: number; reason: string }) =>
      api.post(`/api/hakedis/${id}/kesinti`, v),
    onSuccess: () => {
      message.success("Kesinti eklendi");
      yenile();
    },
    onError: (e: ApiError) => message.error(e.message),
  });

  const ode = useMutation({
    mutationFn: ({ id, ...v }: { id: number } & Record<string, unknown>) =>
      api.post(`/api/hakedis/${id}/ode`, v),
    onSuccess: () => {
      message.success("Ödeme kaydedildi, dönem kilitlendi");
      yenile();
    },
    onError: (e: ApiError) => message.error(e.message),
  });

  const d = detay.data;

  function kesintiSor(id: number) {
    let tutar = 0;
    let neden = "";
    modal.confirm({
      title: "Kesinti ekle",
      content: (
        <Space orientation="vertical" style={{ width: "100%" }}>
          <InputNumber
            placeholder="Tutar"
            style={{ width: "100%" }}
            min={0.01}
            onChange={(v) => (tutar = Number(v))}
          />
          <Input
            placeholder="Neden (hatalı montaj, eksik fotoğraf…)"
            onChange={(e) => (neden = e.target.value)}
          />
        </Space>
      ),
      okText: "Ekle",
      cancelText: "Vazgeç",
      onOk: () => {
        if (!tutar || neden.length < 3) {
          message.error("Tutar ve neden gerekli");
          return Promise.reject();
        }
        return kesinti.mutateAsync({ id, amount: tutar, reason: neden });
      },
    });
  }

  function odemeSor(dokum: Dokum) {
    let tutar = dokum.net_payable;
    let tarih = dayjs();
    let dekont = "";
    modal.confirm({
      title: `Ödeme kaydet · ${dokum.partner_title}`,
      content: (
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Alert
            type="warning"
            showIcon
            title="Bu işlem dönemi KİLİTLER"
            description="Ödenen dönemin satırları değiştirilemez; düzeltme sonraki döneme devreden ayrı bir satır olarak girilir."
          />
          <InputNumber
            defaultValue={dokum.net_payable}
            style={{ width: "100%" }}
            onChange={(v) => (tutar = Number(v))}
          />
          <DatePicker
            defaultValue={dayjs()}
            style={{ width: "100%" }}
            format="DD.MM.YYYY"
            onChange={(v) => (tarih = v ?? dayjs())}
          />
          <Input placeholder="Dekont no" onChange={(e) => (dekont = e.target.value)} />
        </Space>
      ),
      okText: "Ödendi olarak kaydet",
      cancelText: "Vazgeç",
      onOk: () =>
        ode.mutateAsync({
          id: dokum.id,
          amount: tutar,
          paid_at: tarih.format("YYYY-MM-DD"),
          reference: dekont || null,
        }),
    });
  }

  const dokumEkrani = (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Card title="Dönem Özeti" loading={ozet.isLoading}>
        <Space size={32} wrap>
          {(ozet.data ?? []).map((o) => (
            <Card.Grid
              key={o.donem}
              style={{ width: 200, cursor: "pointer", padding: 14 }}
              onClick={() => setDonem(donem === o.donem ? undefined : o.donem)}
            >
              <Statistic
                title={
                  <Space size={4}>
                    <span className="mono">{o.donem}</span>
                    {donem === o.donem && <Tag color="blue">seçili</Tag>}
                  </Space>
                }
                value={o.net}
                // Ant Design varsayılanı İngilizce ayraç kullanıyor
                // (4,300.00); Türkçe biçim için kendi formatlayıcımız.
                formatter={(v) => tl(Number(v))}
                valueStyle={{ fontSize: 17 }}
              />
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {o.dokum} döküm
              </Typography.Text>
            </Card.Grid>
          ))}
        </Space>
      </Card>

      <Card title={donem ? `Hak Ediş Dökümleri · ${donem}` : "Hak Ediş Dökümleri"}>
        <Table
          rowKey="id"
          size="small"
          loading={dokumler.isLoading}
          dataSource={dokumler.data ?? []}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          onRow={(r) => ({ onClick: () => setSecili(r.id), style: { cursor: "pointer" } })}
          columns={[
            { title: "Dönem", dataIndex: "period", width: 90, className: "mono" },
            { title: "Montaj Noktası", dataIndex: "partner_title" },
            {
              title: "Belge tipi",
              dataIndex: "belge_tipi",
              width: 190,
              render: (v: string | null) =>
                v === "BELIRSIZ" ? (
                  <Tooltip title="Belge tipi belirlenmeden kesintiler hesaplanamaz ve döküm onaya çıkamaz">
                    <Tag color="orange">belirsiz</Tag>
                  </Tooltip>
                ) : (
                  (v ?? "").replaceAll("_", " ")
                ),
            },
            { title: "Satır", dataIndex: "satir_adedi", width: 70, className: "mono" },
            {
              title: "Brüt",
              dataIndex: "gross_amount",
              width: 120,
              className: "tutar",
              render: tl,
            },
            {
              title: "Net",
              dataIndex: "net_payable",
              width: 120,
              className: "tutar",
              render: (v: number) => <strong>{tl(v)}</strong>,
            },
            {
              title: "Durum",
              width: 150,
              render: (_, r: Dokum) => (
                <Space size={4}>
                  <Tag color={DURUM_RENGI[r.status]}>{r.status.replaceAll("_", " ")}</Tag>
                  {r.eksik_alanlar.length > 0 && (
                    <Tooltip title={`Eksik: ${r.eksik_alanlar.join(", ")}`}>
                      <Tag color="orange">eksik</Tag>
                    </Tooltip>
                  )}
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Drawer
        title={d ? `${d.partner_title} · ${d.period}` : "Döküm"}
        open={secili != null}
        size={760}
        onClose={() => setSecili(null)}
        loading={detay.isLoading}
        extra={
          d && (
            <Space>
              <Button href={`/api/hakedis/${d.id}/pdf`} target="_blank">
                PDF
              </Button>
              {yetkili("hakedis.yaz") && (
                <Button
                  onClick={() => gonder.mutate(d.id)}
                  loading={gonder.isPending}
                  disabled={d.eksik_alanlar.includes("e-posta")}
                >
                  E-posta ile gönder
                </Button>
              )}
            </Space>
          )
        }
      >
        {d && (
          <Space orientation="vertical" size={16} style={{ width: "100%" }}>
            {d.eksik_alanlar.length > 0 && (
              <Alert
                type="warning"
                showIcon
                title={`Montaj noktasında eksik bilgi: ${d.eksik_alanlar.join(", ")}`}
                description="Döküm e-posta ile gönderilemez ve ödeme listesinde IBAN boş kalır."
              />
            )}
            {d.belge_tipi === "BELIRSIZ" && (
              <Alert
                type="info"
                showIcon
                title="Belge tipi belirsiz"
                description="Kesintiler (stopaj, damga, KDV) belge tipine göre hesaplanır. Fatura / serbest meslek makbuzu / gider pusulası seçilmeden döküm onaya çıkamaz."
              />
            )}

            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="Brüt">{tl(d.gross_amount)}</Descriptions.Item>
              <Descriptions.Item label="Kesinti">{tl(d.deduction_amount)}</Descriptions.Item>
              <Descriptions.Item label="KDV">{tl(d.vat_amount)}</Descriptions.Item>
              <Descriptions.Item label="Stopaj">{tl(d.withholding_amount)}</Descriptions.Item>
              <Descriptions.Item label="Damga">{tl(d.stamp_tax_amount)}</Descriptions.Item>
              <Descriptions.Item label="Net ödenecek">
                <strong>{tl(d.net_payable)}</strong>
              </Descriptions.Item>
              {d.billing_title && (
                <Descriptions.Item label="Fatura eden" span={2}>
                  {d.billing_title}
                </Descriptions.Item>
              )}
            </Descriptions>

            {d.tax_snapshot && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                Uygulanan oranlar bu dökümde dondurulmuştur:{" "}
                <span className="mono">{JSON.stringify(d.tax_snapshot)}</span>
              </Typography.Text>
            )}

            <Space wrap>
              {yetkili("hakedis.onayla") &&
                d.sonraki_durumlar.map((s) => (
                  <Button
                    key={s}
                    type={s === "ONAYLANDI" ? "primary" : "default"}
                    loading={durumDegistir.isPending}
                    onClick={() => durumDegistir.mutate({ id: d.id, to_status: s })}
                  >
                    {s.replaceAll("_", " ")}
                  </Button>
                ))}
              {yetkili("hakedis.yaz") && d.status !== "ODENDI" && (
                <Button danger onClick={() => kesintiSor(d.id)}>
                  Kesinti ekle
                </Button>
              )}
              {yetkili("hakedis.ode") && d.sonraki_durumlar.includes("ODENDI") && (
                <Button type="primary" onClick={() => odemeSor(d)}>
                  Ödeme kaydet
                </Button>
              )}
            </Space>

            <Table
              rowKey="id"
              size="small"
              dataSource={d.satirlar ?? []}
              pagination={{ pageSize: 15, showSizeChanger: false }}
              rowClassName={(s: Satir) => (s.is_deduction ? "kesinti" : "")}
              columns={[
                {
                  title: "İş tipi",
                  dataIndex: "work_type",
                  width: 170,
                  render: (v: string) => v.replaceAll("_", " "),
                },
                { title: "Açıklama", dataIndex: "description" },
                {
                  title: "Birim",
                  dataIndex: "unit_price",
                  width: 100,
                  className: "tutar",
                  render: tl,
                },
                { title: "Adet", dataIndex: "quantity", width: 70, className: "mono" },
                {
                  title: "Tutar",
                  width: 120,
                  className: "tutar",
                  render: (_, s: Satir) => (
                    <span style={s.is_deduction ? { color: "#de3a11" } : undefined}>
                      {s.is_deduction ? "−" : ""}
                      {tl(s.amount)}
                    </span>
                  ),
                },
                {
                  title: "",
                  width: 40,
                  render: (_, s: Satir) =>
                    s.locked_at ? (
                      <Tooltip title="Ödenmiş dönem — bu satır kilitli">
                        <Tag>🔒</Tag>
                      </Tooltip>
                    ) : null,
                },
              ]}
            />
          </Space>
        )}
      </Drawer>
    </Space>
  );

  return (
    <Tabs
      defaultActiveKey="panel"
      items={[
        // Panel önce geliyor: ay kapanışında ilk bakılacak ekran dökümler
        // değil, dökümleri oluşturmadan önce görülmesi gerekenler.
        { key: "panel", label: "Dönem paneli", children: <HakEdisPaneli /> },
        // Montaj/söküm girişi hem burada hem İş Emirleri'nde: hak ediş
        // ayı kapatan kişi işi girmek için başka ekrana gitmek zorunda
        // kalmasın. Aynı bileşen, ikinci bir kod yolu yok.
        ...(yetkili("isemri.yaz")
          ? [
              {
                key: "yeni",
                label: "Yeni montaj / söküm",
                children: <IsEmriFormu />,
              },
            ]
          : []),
        { key: "dokumler", label: "Dökümler", children: dokumEkrani },
      ]}
    />
  );
}
