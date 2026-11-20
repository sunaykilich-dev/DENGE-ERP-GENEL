import { CheckOutlined, CloseOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Input,
  Modal,
  Result,
  Skeleton,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { api, ApiError } from "../api/client";
import { marka } from "../theme";

/**
 * Müşterinin OTURUMSUZ gördüğü teklif sayfası (brief §4.9 online kabul).
 *
 * Kimlik doğrulaması yok; erişim yalnız bağlantıdaki jetona dayanır. Bu
 * yüzden sayfa ERP kabuğunu (menü, arama, kullanıcı) hiç göstermez —
 * müşteri bir iç sistemin içinde olduğunu hissetmemeli ve yanlışlıkla
 * giriş ekranına düşmemeli.
 */

interface Kalem {
  /** Sunucu kaleme kimlik vermiyor (müşteriye iç id göstermenin anlamı yok);
      tablo anahtarı çizim sırasında eklenir. */
  _sira?: number;
  description: string;
  qty: string;
  unit_price: string;
  discount_pct: string;
  vat_rate: string;
  line_total: string;
}

interface AcikTeklif {
  /** Teklifin şirketi (künye PDF'tekiyle aynı kural). */
  sirket_unvan: string;
  mobilite_logosu: boolean;
  quote_no: string;
  title: string | null;
  musteri: string;
  version_no: number;
  currency: string;
  valid_until: string | null;
  subtotal: string;
  discount_total: string;
  vat_total: string;
  grand_total: string;
  kalemler: Kalem[];
  durum: string;
  karar_verilebilir: boolean;
}

const RED_NEDENLERI = [
  "Fiyat yüksek",
  "Başka tedarikçiyle anlaştık",
  "Şimdilik ihtiyacımız yok",
  "Teknik olarak uygun değil",
];

const para = (v: string | number | null | undefined, birim: string) =>
  v == null ? "—" : `${Number(v).toLocaleString("tr-TR", { minimumFractionDigits: 2 })} ${birim}`;

const DURUM_METNI: Record<string, string> = {
  KABUL: "Bu teklif kabul edildi.",
  RED: "Bu teklif reddedildi.",
  SIPARISE_DONUSTU: "Bu teklif siparişe dönüştürüldü.",
  SURESI_DOLDU: "Bu teklifin geçerlilik süresi doldu.",
};

export default function TeklifPublicPage() {
  const { jeton } = useParams<{ jeton: string }>();
  const { message } = App.useApp();
  const qc = useQueryClient();

  const [redAcik, setRedAcik] = useState(false);
  const [redNedeni, setRedNedeni] = useState("");

  const teklif = useQuery({
    queryKey: ["public-teklif", jeton],
    queryFn: () => api.get<AcikTeklif>(`/api/public/teklif/${jeton}`),
    enabled: !!jeton,
    retry: false,
  });

  const kararVer = useMutation({
    mutationFn: (v: { kabul: boolean; red_nedeni?: string }) =>
      api.post<AcikTeklif>(`/api/public/teklif/${jeton}/karar`, v),
    onSuccess: (yeni) => {
      qc.setQueryData(["public-teklif", jeton], yeni);
      setRedAcik(false);
      message.success(yeni.durum === "KABUL" ? "Teklif kabul edildi." : "Yanıtınız kaydedildi.");
    },
    onError: (e: Error) => void message.error(e.message),
  });

  const t = teklif.data;
  const birim = t?.currency ?? "₺";

  return (
    <div style={{ minHeight: "100vh", background: marka.paper }}>
      <div
        style={{
          background: marka.signal,
          padding: "14px 20px",
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        {t && !t.mobilite_logosu ? (
          <Typography.Text style={{ color: "#fff", fontWeight: 700 }}>{t.sirket_unvan}</Typography.Text>
        ) : t ? (
          <img src="/brand/denge-mobilite-mono.svg" alt="Denge Mobilite" style={{ height: 22 }} />
        ) : null}
        <Typography.Text style={{ color: "#fff", fontWeight: 600, letterSpacing: "-0.02em" }}>
          Fiyat Teklifi
        </Typography.Text>
      </div>

      <div style={{ maxWidth: 880, margin: "0 auto", padding: 20 }}>
        {teklif.isLoading && (
          <Card>
            <Skeleton active paragraph={{ rows: 8 }} />
          </Card>
        )}

        {teklif.isError && (
          <Result
            status={(teklif.error as ApiError)?.status === 404 ? "404" : "error"}
            title="Teklif görüntülenemedi"
            subTitle={
              (teklif.error as ApiError)?.status === 404
                ? "Bağlantı geçersiz ya da teklif kaldırılmış olabilir. Lütfen size ulaşan e-postadaki bağlantıyı kontrol edin."
                : ((teklif.error as Error)?.message ?? "Beklenmeyen bir hata oluştu.")
            }
          />
        )}

        {t && (
          <Space orientation="vertical" size={16} style={{ width: "100%" }}>
            <Card>
              <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                <Typography.Title level={4} style={{ margin: 0 }}>
                  {t.title || "Fiyat teklifi"}
                </Typography.Title>
                <Descriptions size="small" column={{ xs: 1, sm: 2 }}>
                  <Descriptions.Item label="Teklif no">
                    <span className="mono">
                      {t.quote_no} · Revizyon {t.version_no}
                    </span>
                  </Descriptions.Item>
                  <Descriptions.Item label="Firma">{t.musteri}</Descriptions.Item>
                  <Descriptions.Item label="Geçerlilik">
                    {t.valid_until ? (
                      <span className="mono">{dayjs(t.valid_until).format("DD.MM.YYYY")}</span>
                    ) : (
                      "—"
                    )}
                  </Descriptions.Item>
                  <Descriptions.Item label="Durum">
                    <Tag color={t.karar_verilebilir ? "blue" : "default"}>
                      {t.durum.replaceAll("_", " ")}
                    </Tag>
                  </Descriptions.Item>
                </Descriptions>
              </Space>
            </Card>

            <Card title="Kalemler">
              <Table
                rowKey="_sira"
                size="small"
                pagination={false}
                dataSource={t.kalemler.map((k, i) => ({ ...k, _sira: i }))}
                scroll={{ x: 640 }}
                columns={[
                  { title: "Açıklama", dataIndex: "description", ellipsis: true },
                  {
                    title: "Adet",
                    dataIndex: "qty",
                    width: 80,
                    className: "mono",
                    render: (x: string) => Number(x).toLocaleString("tr-TR"),
                  },
                  {
                    title: "Birim fiyat",
                    dataIndex: "unit_price",
                    width: 130,
                    className: "tutar",
                    render: (x: string) => para(x, birim),
                  },
                  {
                    title: "İskonto",
                    dataIndex: "discount_pct",
                    width: 90,
                    className: "tutar",
                    render: (x: string) => (Number(x) ? `%${Number(x)}` : "—"),
                  },
                  {
                    title: "KDV",
                    dataIndex: "vat_rate",
                    width: 80,
                    className: "tutar",
                    // `vat_rate` KESİR olarak saklanır (0.20), `discount_pct` yüzde (5).
                    render: (x: string) => `%${(Number(x) * 100).toFixed(0)}`,
                  },
                  {
                    title: "Tutar",
                    dataIndex: "line_total",
                    width: 140,
                    className: "tutar",
                    render: (x: string) => <strong>{para(x, birim)}</strong>,
                  },
                ]}
                summary={() => (
                  <Table.Summary>
                    <Table.Summary.Row>
                      <Table.Summary.Cell index={0} colSpan={5}>
                        Ara toplam
                      </Table.Summary.Cell>
                      <Table.Summary.Cell index={5} className="tutar">
                        {para(t.subtotal, birim)}
                      </Table.Summary.Cell>
                    </Table.Summary.Row>
                    {Number(t.discount_total) > 0 && (
                      <Table.Summary.Row>
                        <Table.Summary.Cell index={0} colSpan={5}>
                          İskonto
                        </Table.Summary.Cell>
                        <Table.Summary.Cell index={5} className="tutar">
                          −{para(t.discount_total, birim)}
                        </Table.Summary.Cell>
                      </Table.Summary.Row>
                    )}
                    <Table.Summary.Row>
                      <Table.Summary.Cell index={0} colSpan={5}>
                        KDV
                      </Table.Summary.Cell>
                      <Table.Summary.Cell index={5} className="tutar">
                        {para(t.vat_total, birim)}
                      </Table.Summary.Cell>
                    </Table.Summary.Row>
                    <Table.Summary.Row>
                      <Table.Summary.Cell index={0} colSpan={5}>
                        <strong>Genel toplam</strong>
                      </Table.Summary.Cell>
                      <Table.Summary.Cell index={5} className="tutar">
                        <strong style={{ fontSize: 16 }}>{para(t.grand_total, birim)}</strong>
                      </Table.Summary.Cell>
                    </Table.Summary.Row>
                  </Table.Summary>
                )}
              />
            </Card>

            {t.karar_verilebilir ? (
              <Card>
                <Space orientation="vertical" size={12} style={{ width: "100%" }}>
                  <Typography.Text>
                    Teklifi buradan yanıtlayabilirsiniz. Yanıtınız tarih ve saatiyle kaydedilir.
                  </Typography.Text>
                  <Space wrap>
                    <Button
                      type="primary"
                      icon={<CheckOutlined />}
                      loading={kararVer.isPending}
                      onClick={() => kararVer.mutate({ kabul: true })}
                    >
                      Teklifi kabul ediyorum
                    </Button>
                    <Button danger icon={<CloseOutlined />} onClick={() => setRedAcik(true)}>
                      Teklifi reddet
                    </Button>
                  </Space>
                </Space>
              </Card>
            ) : (
              <Alert
                type={t.durum === "KABUL" || t.durum === "SIPARISE_DONUSTU" ? "success" : "info"}
                showIcon
                title={DURUM_METNI[t.durum] ?? "Bu teklif şu anda yanıtlanamıyor."}
                description="Sorularınız için bizimle iletişime geçebilirsiniz."
              />
            )}

            <Typography.Paragraph type="secondary" style={{ textAlign: "center", marginTop: 8 }}>
              {t.sirket_unvan} · Bu bağlantı yalnız size özeldir, paylaşmayınız.
            </Typography.Paragraph>
          </Space>
        )}
      </div>

      <Modal
        open={redAcik}
        title="Teklifi reddet"
        okText="Reddet"
        okButtonProps={{ danger: true, disabled: !redNedeni.trim() }}
        confirmLoading={kararVer.isPending}
        onOk={() => kararVer.mutate({ kabul: false, red_nedeni: redNedeni.trim() })}
        onCancel={() => setRedAcik(false)}
      >
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          <Typography.Text>
            Nedenini paylaşırsanız bir sonraki teklifimizi buna göre hazırlarız.
          </Typography.Text>
          <Space wrap size={[8, 8]}>
            {RED_NEDENLERI.map((n) => (
              <Tag.CheckableTag key={n} checked={redNedeni === n} onChange={() => setRedNedeni(n)}>
                {n}
              </Tag.CheckableTag>
            ))}
          </Space>
          <Input.TextArea
            value={redNedeni}
            onChange={(e) => setRedNedeni(e.target.value)}
            placeholder="Neden (zorunlu)"
            rows={3}
            maxLength={300}
            showCount
          />
        </Space>
      </Modal>
    </div>
  );
}
