import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  DatePicker,
  Descriptions,
  Empty,
  Form,
  Image,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import { api, type ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";

/**
 * Teklife/siparişe bağlı servis işleri (KARARLAR 2026-11-09 S3, S4.1, S4.2).
 *
 * Satışçı işin ayrıntısına değil aşamasına bakar: Planlandı, Yolda, Sahada,
 * Tamamlandı, Askıda (neden ile). Keşif işinde teknisyen raporu, fotoğraflar
 * ve keşif raporu PDF'i buradan açılır. Fiyat/maliyet hiç gösterilmez.
 * Düğmeler yalnız arayüzü kısar; izin ve kural sunucudadır.
 */

export interface BagliIs {
  service_order_id: number;
  so_no: string;
  bag_turu: string;
  bag_adi: string;
  tur: string;
  tur_adi: string;
  birim: string;
  birim_adi: string;
  oncelik: string;
  durum: string;
  durum_adi: string;
  asama: string;
  asama_adi: string;
  askida_nedeni: string | null;
  plan_tarihi: string | null;
  hedef_tarih: string | null;
  tamamlanma: string | null;
}

interface IsSonucu {
  tamamlandi: boolean;
  rapor: string | null;
  sonuc: string | null;
  rapor_tarihi: string | null;
  ekler: { id: number; dosya_adi: string; tur: string; mime_type: string; gorsel: boolean }[];
}

export const ASAMA_RENGI: Record<string, string> = {
  PLANLAMA_BEKLIYOR: "default",
  PLANLANDI: "blue",
  YOLDA: "cyan",
  SAHADA: "geekblue",
  ASKIDA: "orange",
  TAMAMLANDI: "green",
  IPTAL: "default",
};

export const BIRIM_SECENEKLERI = [
  { value: "HABERLESME", label: "Haberleşme" },
  { value: "GUVENLIK", label: "Güvenlik" },
  { value: "BARIYER", label: "Set Bariyer" },
  { value: "POC", label: "POC" },
];

const tarih = (x: string | null | undefined) => (x ? dayjs(x).format("DD.MM.YYYY") : "—");

export function AsamaEtiketi({ is }: { is: BagliIs }) {
  return (
    <Space size={4} wrap>
      <Tag color={ASAMA_RENGI[is.asama]}>{is.asama_adi}</Tag>
      {is.askida_nedeni && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {is.askida_nedeni}
        </Typography.Text>
      )}
    </Space>
  );
}

function KesifSonucu({ teklifId, is }: { teklifId: number; is: BagliIs }) {
  const sonuc = useQuery({
    queryKey: ["satis-is-sonucu", teklifId, is.service_order_id],
    queryFn: () =>
      api.get<IsSonucu>(`/api/satis-takip/teklif/${teklifId}/isler/${is.service_order_id}/sonuc`),
  });
  const s = sonuc.data;
  const ekYolu = (id: number) =>
    `/api/satis-takip/teklif/${teklifId}/isler/${is.service_order_id}/ekler/${id}`;
  if (sonuc.isLoading) return null;
  if (!s) return null;
  return (
    <Space orientation="vertical" size={8} style={{ width: "100%" }}>
      {s.rapor ? (
        <Descriptions bordered size="small" column={1}>
          <Descriptions.Item label="Sonuç">{s.sonuc}</Descriptions.Item>
          <Descriptions.Item label="Teknisyen raporu">
            <span style={{ whiteSpace: "pre-wrap" }}>{s.rapor}</span>
          </Descriptions.Item>
        </Descriptions>
      ) : (
        <Typography.Text type="secondary">Teknisyen raporu henüz girilmedi.</Typography.Text>
      )}
      {s.ekler.some((e) => e.gorsel) && (
        <Image.PreviewGroup>
          <Space wrap>
            {s.ekler
              .filter((e) => e.gorsel && e.mime_type !== "image/heic")
              .map((e) => (
                <Image key={e.id} width={96} height={96} style={{ objectFit: "cover" }} src={ekYolu(e.id)} alt={e.dosya_adi} />
              ))}
          </Space>
        </Image.PreviewGroup>
      )}
      {s.ekler
        .filter((e) => !e.gorsel || e.mime_type === "image/heic")
        .map((e) => (
          <Typography.Link key={e.id} href={ekYolu(e.id)} target="_blank">
            {e.dosya_adi}
          </Typography.Link>
        ))}
      {is.tur === "KESIF" && (
        <Button
          size="small"
          href={`/api/satis-takip/teklif/${teklifId}/isler/${is.service_order_id}/kesif-raporu.pdf`}
          target="_blank"
        >
          Keşif raporu (PDF)
        </Button>
      )}
    </Space>
  );
}

interface Props {
  kaynak: "teklif" | "siparis";
  id: number;
  /** Teklifin birimi (birimli teklif); boşsa birim seçilir. */
  birim?: string | null;
  /** Keşif istenebilir mi (teklif açık durumdaysa). */
  kesifAcik?: boolean;
  /** Kurulum/teslimat işi açılabilir mi (kabul edilmiş teklif / onaylı sipariş). */
  isAcilabilir?: boolean;
  /** Sonuç ve ek uçları teklif kapsamından okunur (siparişte teklif varsa). */
  teklifId?: number | null;
}

export default function SatisIsleri({ kaynak, id, birim, kesifAcik, isAcilabilir, teklifId }: Props) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const { yetkili } = useAuth();
  const [form] = Form.useForm();
  const [mod, setMod] = useState<null | "kesif" | "is">(null);

  const anahtar = ["satis-isleri", kaynak, id];
  const isler = useQuery({
    queryKey: anahtar,
    queryFn: () => api.get<BagliIs[]>(`/api/satis-takip/${kaynak}/${id}/isler`),
  });

  const ac = useMutation({
    mutationFn: (govde: Record<string, unknown>) =>
      api.post<{ so_no: string }>(
        `/api/satis-takip/${kaynak}/${id}/${mod === "kesif" ? "kesif" : "is"}`,
        govde,
      ),
    onSuccess: (r) => {
      message.success(
        mod === "is"
          ? `${r.so_no} açıldı; teknik servis müdürüne yönlendirildi`
          : `${r.so_no} açıldı; birim şefinin planlamasına düştü`,
      );
      setMod(null);
      form.resetFields();
      void qc.invalidateQueries({ queryKey: anahtar });
    },
    onError: (e: ApiError) => message.error(e.message),
  });

  const sonucTeklifi = kaynak === "teklif" ? id : (teklifId ?? null);

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Space wrap>
        {kaynak === "teklif" && kesifAcik && yetkili("teklif.kesif_iste") && (
          <Button onClick={() => setMod("kesif")}>Keşif iste</Button>
        )}
        {isAcilabilir && yetkili("teklif.servis_isi_ac") && (
          <Button onClick={() => setMod("is")}>Kurulum / teslimat işi aç</Button>
        )}
      </Space>
      <Table<BagliIs>
        rowKey="service_order_id"
        size="small"
        loading={isler.isLoading}
        dataSource={isler.data ?? []}
        pagination={false}
        locale={{ emptyText: <Empty description="Bağlı servis işi yok" /> }}
        expandable={
          sonucTeklifi
            ? {
                rowExpandable: (r) => r.tur === "KESIF" || r.asama === "TAMAMLANDI",
                expandedRowRender: (r) => <KesifSonucu teklifId={sonucTeklifi} is={r} />,
              }
            : undefined
        }
        columns={[
          { title: "İş", dataIndex: "so_no", className: "mono", width: 150 },
          { title: "Bağ", dataIndex: "bag_adi", width: 110 },
          { title: "Birim", dataIndex: "birim_adi", width: 120 },
          {
            title: "Aşama",
            render: (_: unknown, r: BagliIs) => <AsamaEtiketi is={r} />,
          },
          {
            title: "Plan / hedef",
            width: 170,
            className: "mono",
            render: (_: unknown, r: BagliIs) =>
              r.plan_tarihi ? `Plan ${tarih(r.plan_tarihi)}` : r.hedef_tarih ? `Hedef ${tarih(r.hedef_tarih)}` : "—",
          },
        ]}
      />
      <Modal
        open={mod !== null}
        title={mod === "kesif" ? "Keşif iste" : "Kurulum / teslimat işi aç"}
        okText={mod === "kesif" ? "Keşif iste" : "İşi aç"}
        cancelText="Vazgeç"
        confirmLoading={ac.isPending}
        onCancel={() => setMod(null)}
        onOk={() => form.submit()}
        destroyOnHidden
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          title="İş planlamada başlar; planlamayı birim şefi yapar. Kritik öncelik seçilemez."
        />
        <Form
          form={form}
          layout="vertical"
          initialValues={{ oncelik: "NORMAL", tur: "KURULUM" }}
          onFinish={(v) =>
            ac.mutate({
              ...(mod === "is" ? { tur: v.tur } : {}),
              birim: birim ?? v.birim,
              oncelik: v.oncelik,
              hedef_tarih: v.hedef_tarih ? dayjs(v.hedef_tarih).format("YYYY-MM-DD") : null,
              aciklama: v.aciklama || null,
              ...(mod === "is" ? { sozlesme_detay: v.sozlesme_detay || null } : {}),
            })
          }
        >
          {mod === "is" && (
            <Form.Item name="tur" label="İş türü" rules={[{ required: true }]}>
              <Select
                options={[
                  { value: "KURULUM", label: "Kurulum" },
                  { value: "TESLIMAT", label: "Teslimat" },
                ]}
              />
            </Form.Item>
          )}
          {!birim && (
            <Form.Item name="birim" label="Birim" rules={[{ required: true, message: "Birim seçin" }]}>
              <Select
                options={mod === "kesif" ? BIRIM_SECENEKLERI.slice(0, 2) : BIRIM_SECENEKLERI}
              />
            </Form.Item>
          )}
          <Form.Item name="oncelik" label="Öncelik">
            <Select
              options={[
                { value: "NORMAL", label: "Normal" },
                { value: "YUKSEK", label: "Yüksek" },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="hedef_tarih"
            label="Hedef tarih"
            extra={mod === "kesif" ? "Boş bırakılırsa 5 iş günü (teklif geçerliliği daha erkense o gün)." : undefined}
          >
            <DatePicker format="DD.MM.YYYY" disabledDate={(d) => d.isBefore(dayjs(), "day")} />
          </Form.Item>
          <Form.Item name="aciklama" label="Açıklama">
            <Input.TextArea rows={3} maxLength={1000} />
          </Form.Item>
          {mod === "is" && (
            // KARARLAR 2026-11-20 §5: iş teknik servis müdürüne bu ayrıntılarla düşer.
            <Form.Item
              name="sozlesme_detay"
              label="Sözleşme / taahhüt ayrıntıları"
              extra="Sevkiyat, kurulum, garanti ve bakım taahhüdü gibi teknik servisin bilmesi gerekenler."
            >
              <Input.TextArea rows={3} maxLength={4000} />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </Space>
  );
}
