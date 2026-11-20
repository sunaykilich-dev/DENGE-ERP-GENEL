import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Form, InputNumber, Modal, Space, Table, Tag, Tooltip, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";

interface Tarife {
  id: number;
  partner_id: number | null;
  partner_title: string | null;
  work_type: string;
  product_group: string;
  unit_price: number;
  valid_from: string;
  valid_to: string | null;
  notes: string | null;
  genel: boolean;
}

const IS_TIPI_ADI: Record<string, string> = {
  ATS_MONTAJ: "ATS montajı",
  OBD_ATS_MONTAJ: "OBD'li ATS montajı",
  DASHCAM_MONTAJ: "Dashcam montajı",
  HARICI_KAMERA_MONTAJ: "Harici kamera montajı",
  SOKUM: "Söküm",
  SOK_TAK: "Sök-tak",
  DEGISIM: "Değişim",
  ARIZA: "Arıza",
  KESIF: "Keşif",
  YOL_KM: "Yol (km başına)",
};

/**
 * Montaj noktasının iş tipi başına hak ediş fiyatı.
 *
 * Tarife TARİHLİDİR: fiyat değiştirmek satırı düzenlemek değil, yürürlüktekini
 * kapatıp yenisini açmaktır. Hak ediş çözümlemesi işin TAMAMLANMA tarihine
 * bakar, bu yüzden geçmiş aylar yeni fiyattan yeniden hesaplanmaz. Ekran bunu
 * gizlemez — "düzenle" değil "yeni fiyat" der.
 *
 * Noktaya özel fiyat yoksa GENEL tarife uygulanır ve öyle gösterilir; boş bir
 * liste "fiyat yok" izlenimi verirdi, oysa iş fiyatsız kalmıyor.
 */
export default function MontajTarifeleri({ hesapId }: { hesapId: number }) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const { yetkili } = useAuth();
  const [acik, setAcik] = useState<string | null>(null);
  const [form] = Form.useForm();

  const tarifeler = useQuery({
    queryKey: ["tarifeler", hesapId],
    queryFn: () => api.get<Tarife[]>(`/api/tarifeler?montaj_noktasi_id=${hesapId}`),
  });
  const isTipleri = useQuery({
    queryKey: ["tarife-is-tipleri"],
    queryFn: () => api.get<string[]>("/api/tarifeler/is-tipleri"),
  });

  const kaydet = useMutation({
    mutationFn: (v: Record<string, unknown>) => api.post("/api/tarifeler", v),
    onSuccess: () => {
      message.success("Yeni fiyat yürürlüğe girdi");
      setAcik(null);
      form.resetFields();
      qc.invalidateQueries({ queryKey: ["tarifeler", hesapId] });
    },
    onError: (e: Error) => void message.error(e.message),
  });

  const hepsi = tarifeler.data ?? [];
  const yururlukte = hepsi.filter((t) => !t.valid_to);
  const gecmis = hepsi.filter((t) => t.valid_to);

  // İş tipi başına tek satır: noktaya özel varsa o, yoksa genel.
  const satirlar = (isTipleri.data ?? []).map((tip) => {
    const ozel = yururlukte.find((t) => t.work_type === tip && !t.genel);
    const genel = yururlukte.find((t) => t.work_type === tip && t.genel);
    return { tip, gecerli: ozel ?? genel ?? null, ozelMi: Boolean(ozel) };
  });

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        Fiyat değişince geçmiş işler ESKİ fiyattan hesaplanmaya devam eder; hak ediş
        işin tamamlanma tarihindeki tarifeyi kullanır.
      </Typography.Text>

      <Table
        rowKey="tip"
        size="small"
        pagination={false}
        loading={tarifeler.isLoading}
        dataSource={satirlar}
        columns={[
          {
            title: "İş tipi",
            dataIndex: "tip",
            render: (t: string) => IS_TIPI_ADI[t] ?? t.replaceAll("_", " "),
          },
          {
            title: "Birim fiyat",
            align: "right" as const,
            render: (_: unknown, s: (typeof satirlar)[number]) =>
              s.gecerli ? (
                <span className="tutar">
                  {Number(s.gecerli.unit_price).toLocaleString("tr-TR", {
                    minimumFractionDigits: 2,
                  })}{" "}
                  ₺
                </span>
              ) : (
                <Typography.Text type="secondary">tanımsız</Typography.Text>
              ),
          },
          {
            title: "Kaynak",
            render: (_: unknown, s: (typeof satirlar)[number]) =>
              !s.gecerli ? (
                <Tag>—</Tag>
              ) : s.ozelMi ? (
                <Tag color="blue">bu noktaya özel</Tag>
              ) : (
                <Tooltip title="Bu nokta için özel fiyat tanımlı değil; genel tarife uygulanıyor.">
                  <Tag>genel tarife</Tag>
                </Tooltip>
              ),
          },
          {
            title: "Yürürlük",
            render: (_: unknown, s: (typeof satirlar)[number]) =>
              s.gecerli ? (
                <Typography.Text type="secondary" className="mono" style={{ fontSize: 12 }}>
                  {dayjs(s.gecerli.valid_from).format("DD.MM.YYYY")}
                </Typography.Text>
              ) : null,
          },
          ...(yetkili("hakedis.yaz")
            ? [
                {
                  title: "",
                  align: "right" as const,
                  render: (_: unknown, s: (typeof satirlar)[number]) => (
                    <Button
                      size="small"
                      onClick={() => {
                        setAcik(s.tip);
                        form.setFieldsValue({ unit_price: s.gecerli?.unit_price ?? null });
                      }}
                    >
                      Yeni fiyat
                    </Button>
                  ),
                },
              ]
            : []),
        ]}
      />

      {gecmis.length > 0 && (
        <details>
          <summary style={{ cursor: "pointer", fontSize: 12, color: "#68758a" }}>
            Geçmiş fiyatlar ({gecmis.length})
          </summary>
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            style={{ marginTop: 8 }}
            dataSource={gecmis}
            columns={[
              {
                title: "İş tipi",
                dataIndex: "work_type",
                render: (t: string) => IS_TIPI_ADI[t] ?? t.replaceAll("_", " "),
              },
              {
                title: "Fiyat",
                dataIndex: "unit_price",
                align: "right" as const,
                render: (v: number) => <span className="tutar">{Number(v).toFixed(2)} ₺</span>,
              },
              {
                title: "Dönem",
                render: (_: unknown, t: Tarife) => (
                  <span className="mono" style={{ fontSize: 12 }}>
                    {dayjs(t.valid_from).format("DD.MM.YYYY")} –{" "}
                    {t.valid_to ? dayjs(t.valid_to).format("DD.MM.YYYY") : "—"}
                  </span>
                ),
              },
              { title: "Not", dataIndex: "notes" },
            ]}
          />
        </details>
      )}

      <Modal
        open={acik !== null}
        title={`Yeni fiyat · ${acik ? (IS_TIPI_ADI[acik] ?? acik) : ""}`}
        okText="Yürürlüğe al"
        cancelText="Vazgeç"
        confirmLoading={kaydet.isPending}
        onCancel={() => setAcik(null)}
        onOk={() =>
          form.validateFields().then((v) =>
            kaydet.mutate({
              partner_id: hesapId,
              work_type: acik,
              unit_price: v.unit_price,
              notes: v.notes || null,
            }),
          )
        }
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          Yürürlükteki fiyat bugün kapatılır, yenisi bugünden itibaren geçerli olur.
          Bugüne kadar tamamlanmış işler eski fiyattan hesaplanmaya devam eder.
        </Typography.Paragraph>
        <Form form={form} layout="vertical">
          <Form.Item
            name="unit_price"
            label="Birim fiyat (₺)"
            rules={[{ required: true, message: "Fiyat girin" }]}
          >
            <InputNumber min={0} step={50} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="notes" label="Not (isteğe bağlı)">
            <input
              className="ant-input"
              placeholder="Ör. 2026 zammı, sözleşme revizyonu"
              maxLength={300}
            />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  );
}
