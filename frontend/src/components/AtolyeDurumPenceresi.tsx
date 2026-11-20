/**
 * Atölye durum geçişi penceresi (TS-090/093/094/096/098).
 *
 * Tek uç: `POST /atolye/{so_id}/durum`. Hedef listesi ve engel metni
 * SUNUCUDAN gelir (`sonraki_durumlar`: makine ∩ izin ∩ iş kuralı); istemci
 * kural hesaplamaz, yalnız ekranda gösterir. `beklenen_durum` gönderilir:
 * kayıt başka sekmede değiştiyse sunucu 409 döner.
 *
 * - İptal ve geri alma: gerekçe zorunlu (`servis.kapat`).
 * - Kargoya verildi: kargo firması + takip no.
 * - Teslim edildi: teslim alan adı, teslim tipi ve aksesuarların tek tek
 *   karşılaştırması; iade edilmeyen aksesuar varsa açıklama zorunlu ve
 *   sunucu "eksik aksesuarla teslim" uyarısı döner. Teslim alan adı olay
 *   geçmişine yazılmaz (KVKK, TS-101).
 * - Müşteri onayı (ONAY_BEKLIYOR) servis işini BEKLEMEDE yapar; onay kararı
 *   kaydın "Onay" alanlarından girilir ya da bağlı teklifin KABUL'ü sayılır.
 */
import { useMutation } from "@tanstack/react-query";
import { Alert, App, Checkbox, Col, Form, Input, Modal, Row, Select, Space, Table, Typography } from "antd";
import { useEffect } from "react";

import {
  atolyeApi,
  type AtolyeDetay,
  type FormVerileri,
  type SonrakiDurum,
} from "../api/atolye";
import SeriOkutucu, { seriFarki } from "./SeriOkutucu";

/** Telsiz birimleri: kargo/teslim öncesi seri yeniden okutulur (KARARLAR 2026-11-20 §4). */
const TELSIZ_BIRIMLERI = new Set(["HABERLESME", "POC"]);

interface FormDegeri {
  gerekce?: string;
  kargo_firmasi?: string;
  takip_no?: string;
  teslim_alan?: string;
  teslim_tipi?: string;
  aciklama?: string;
  sure_eksik_onay?: boolean;
  okutulan_seriler?: string[];
  seri_aciklama?: string;
  iade: Record<string, { returned: boolean; not?: string }>;
}

export default function AtolyeDurumPenceresi({
  detay,
  hedef,
  sozluk,
  kapat,
  bitti,
}: {
  detay: AtolyeDetay;
  hedef: SonrakiDurum | null;
  sozluk?: FormVerileri;
  kapat: () => void;
  bitti: (d: AtolyeDetay) => void;
}) {
  const { message, modal } = App.useApp();
  const [form] = Form.useForm<FormDegeri>();
  const iade = Form.useWatch("iade", form);
  const okunan = Form.useWatch("okutulan_seriler", form) ?? [];
  const beklenenSeri = detay.ekipman.seri ? [detay.ekipman.seri] : [];
  const seriOkutulur =
    !!hedef &&
    (hedef.hedef === "KARGOYA_VERILDI" || hedef.hedef === "TESLIM_EDILDI") &&
    TELSIZ_BIRIMLERI.has(detay.birim) &&
    beklenenSeri.length > 0;
  const fark = seriFarki(beklenenSeri, okunan);
  const seriFarkiVar = seriOkutulur && okunan.length > 0 && (fark.eksik.length > 0 || fark.fazla.length > 0);

  useEffect(() => {
    if (hedef) {
      form.resetFields();
      form.setFieldsValue({
        teslim_tipi: detay.delivery_type ?? (hedef.hedef === "KARGOYA_VERILDI" ? "KARGO" : "ELDEN"),
        iade: Object.fromEntries(detay.aksesuarlar.map((a) => [String(a.id), { returned: true }])),
      });
    }
  }, [hedef, detay, form]);

  const gonder = useMutation({
    mutationFn: (v: FormDegeri) => {
      const h = hedef!.hedef;
      const okutma = seriOkutulur
        ? { okutulan_seriler: v.okutulan_seriler ?? [], seri_aciklama: v.seri_aciklama || null }
        : {};
      const teslim =
        h === "KARGOYA_VERILDI"
          ? { teslim_tipi: "KARGO", kargo_firmasi: v.kargo_firmasi, takip_no: v.takip_no, ...okutma }
          : h === "TESLIM_EDILDI"
            ? {
                ...okutma,
                teslim_alan: v.teslim_alan,
                teslim_tipi: v.teslim_tipi,
                aciklama: v.aciklama || null,
                aksesuar_iade: detay.aksesuarlar.map((a) => ({
                  id: a.id,
                  returned: !!v.iade?.[String(a.id)]?.returned,
                  not: v.iade?.[String(a.id)]?.not || null,
                })),
              }
            : null;
      return atolyeApi.durum(detay.so_id, {
        hedef: h,
        gerekce: v.gerekce || null,
        beklenen_durum: detay.status,
        teslim,
        sure_eksik_onay: !!v.sure_eksik_onay,
      });
    },
    onSuccess: (d) => {
      message.success(`Durum: ${hedef?.ad}`);
      if (d.uyarilar?.length) {
        modal.warning({ title: "Uyarı", content: d.uyarilar.join("\n") });
      }
      bitti(d);
    },
    onError: (e: Error) => message.error(e.message),
  });

  if (!hedef) return null;
  const h = hedef.hedef;
  const eksikVar = detay.aksesuarlar.some((a) => iade && !iade[String(a.id)]?.returned);

  return (
    <Modal
      title={`${detay.atolye_no}: ${hedef.ad}`}
      open={!!hedef}
      onCancel={kapat}
      onOk={() => form.submit()}
      okText="Uygula"
      okButtonProps={{ danger: h === "IPTAL" }}
      cancelText="Vazgeç"
      confirmLoading={gonder.isPending}
      width={h === "TESLIM_EDILDI" ? 720 : 520}
      destroyOnHidden
    >
      <Space orientation="vertical" style={{ width: "100%" }}>
        {hedef.engel && <Alert type="warning" showIcon title={hedef.engel} />}
        {hedef.geri_alma && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Geri alma servis işinin durumunu değiştirmez; olay geçmişine gerekçesiyle yazılır.
          </Typography.Text>
        )}
        {h === "ONAY_BEKLIYOR" && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Servis işi "Müşteri onayı" nedeniyle beklemeye alınır. Onay kararını kaydın Onay
            bölümünden girin; bağlı teklifin kabulü de onay sayılır.
          </Typography.Text>
        )}
        <Form<FormDegeri> form={form} layout="vertical" onFinish={(v) => gonder.mutate(v)}>
          {(hedef.gerekce_zorunlu || h === "IPTAL") && (
            <Form.Item
              name="gerekce"
              label="Gerekçe"
              rules={[{ required: true, whitespace: true, message: "Gerekçe zorunlu" }]}
            >
              <Input.TextArea rows={2} maxLength={500} />
            </Form.Item>
          )}
          {h === "KARGOYA_VERILDI" && (
            <Row gutter={8}>
              <Col span={12}>
                <Form.Item name="kargo_firmasi" label="Kargo firması" rules={[{ required: true, whitespace: true }]}>
                  <Input maxLength={60} />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="takip_no" label="Takip no" rules={[{ required: true, whitespace: true }]}>
                  <Input maxLength={60} />
                </Form.Item>
              </Col>
            </Row>
          )}
          {seriOkutulur && (
            <>
              <Form.Item
                name="okutulan_seriler"
                label="Cihaz seri numarasını okutun"
                rules={[{ required: true, type: "array", min: 1, message: "Seri numarası okutulmalı" }]}
              >
                <SeriOkutucu beklenen={beklenenSeri} />
              </Form.Item>
              {seriFarkiVar && (
                <Form.Item
                  name="seri_aciklama"
                  label="Seri tutmuyor: açıklama"
                  rules={[{ required: true, whitespace: true, message: "Yanlış/eksik cihaz için açıklama zorunlu" }]}
                >
                  <Input.TextArea rows={2} maxLength={500} />
                </Form.Item>
              )}
            </>
          )}
          {h === "TESLIM_EDILDI" && (
            <>
              <Row gutter={8}>
                <Col xs={24} md={14}>
                  <Form.Item
                    name="teslim_alan"
                    label="Teslim alan"
                    tooltip="Kişisel veri: olay geçmişine yazılmaz"
                    rules={[{ required: true, whitespace: true, message: "Teslim alan zorunlu" }]}
                  >
                    <Input maxLength={120} />
                  </Form.Item>
                </Col>
                <Col xs={24} md={10}>
                  <Form.Item name="teslim_tipi" label="Teslim tipi" rules={[{ required: true }]}>
                    <Select
                      options={(sozluk?.teslim_tipleri ?? []).map((t) => ({ value: t.kod, label: t.ad }))}
                    />
                  </Form.Item>
                </Col>
              </Row>
              {detay.aksesuarlar.length > 0 && (
                <Table
                  size="small"
                  rowKey="id"
                  pagination={false}
                  dataSource={detay.aksesuarlar}
                  columns={[
                    {
                      title: "Aksesuar",
                      key: "a",
                      render: (_, a) =>
                        `${sozluk?.aksesuar_turleri.find((t) => t.kod === a.kind)?.ad ?? a.kind}${
                          a.description ? ` — ${a.description}` : ""
                        } × ${a.qty}`,
                    },
                    {
                      title: "İade edildi",
                      key: "r",
                      width: 100,
                      render: (_, a) => (
                        <Form.Item name={["iade", String(a.id), "returned"]} valuePropName="checked" noStyle>
                          <Checkbox />
                        </Form.Item>
                      ),
                    },
                    {
                      title: "Not",
                      key: "n",
                      render: (_, a) => (
                        <Form.Item name={["iade", String(a.id), "not"]} noStyle>
                          <Input size="small" maxLength={300} />
                        </Form.Item>
                      ),
                    },
                  ]}
                />
              )}
              {eksikVar && (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginTop: 8 }}
                  title="Kabulde alınan aksesuarlardan biri iade edilmiyor; teslim açıklaması zorunlu"
                />
              )}
              <Form.Item
                name="aciklama"
                label="Teslim açıklaması"
                style={{ marginTop: 8 }}
                rules={[{ required: eksikVar, whitespace: true, message: "Açıklama zorunlu" }]}
              >
                <Input.TextArea rows={2} maxLength={2000} />
              </Form.Item>
              {detay.sure.sure_eksik && (
                <Form.Item name="sure_eksik_onay" valuePropName="checked">
                  <Checkbox>Süre kaydı eksik; yine de teslim et</Checkbox>
                </Form.Item>
              )}
            </>
          )}
        </Form>
      </Space>
    </Modal>
  );
}
