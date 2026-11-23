/**
 * Yönlendirmeler (KARARLAR 2026-11-20 §5–6).
 *
 * Onaylı satıştan açılan kurulum/teslimat işi ve onaylanan kiralama talebi
 * teknik servis müdürüne düşer. Müdür birimin yöneticisine/şefine yönlendirir;
 * şef bu ekranda kendisine yönlendirilenleri görür. Planlamayı kilitlemez:
 * iş planlanınca ya da kiralama talep aşamasından çıkınca listeden düşer.
 */
import { SendOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Card, Form, Input, Modal, Select, Space, Switch, Table, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { Link } from "react-router-dom";

import { BIRIM_ETIKETLERI } from "../api/personel";
import { yonlendirmeApi, type Yonlendirme } from "../api/yonlendirme";
import { useAuth } from "../auth/AuthContext";

export default function YonlendirmelerPage() {
  const { yetkili } = useAuth();
  const mudur = yetkili("servis.yonlendir");
  const [hepsi, setHepsi] = useState(false);
  const [secili, setSecili] = useState<Yonlendirme | null>(null);
  const liste = useQuery({ queryKey: ["yonlendirmeler", !hepsi], queryFn: () => yonlendirmeApi.liste(!hepsi) });

  return (
    <Card
      title={mudur ? "Yönlendirmeler" : "Bana yönlendirilenler"}
      extra={
        <Space>
          <Typography.Text type="secondary">Planlananları da göster</Typography.Text>
          <Switch size="small" checked={hepsi} onChange={setHepsi} />
        </Space>
      }
    >
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        {mudur
          ? "Satıştan ve onaylanan kiralama taleplerinden gelen işler. Birimin yöneticisine ya da şefine yönlendirin; o kişi planlar."
          : "Teknik servis müdürünün size yönlendirdiği satış ve kiralama işleri."}
      </Typography.Paragraph>
      <Table<Yonlendirme>
        size="small"
        rowKey="id"
        loading={liste.isLoading}
        dataSource={liste.data ?? []}
        scroll={{ x: 900 }}
        pagination={{ pageSize: 50, hideOnSinglePage: true }}
        expandable={{
          rowExpandable: (r) => !!(r.sozlesme_detay || r.talep_notu || r.mudur_notu),
          expandedRowRender: (r) => (
            <Space orientation="vertical" size={4}>
              {r.sozlesme_detay && (
                <Typography.Text>
                  <b>Sözleşme / taahhüt:</b> {r.sozlesme_detay}
                </Typography.Text>
              )}
              {r.talep_notu && (
                <Typography.Text>
                  <b>Talep notu:</b> {r.talep_notu}
                </Typography.Text>
              )}
              {r.mudur_notu && (
                <Typography.Text>
                  <b>Müdür notu:</b> {r.mudur_notu}
                </Typography.Text>
              )}
            </Space>
          ),
        }}
        columns={[
          {
            title: "Kaynak",
            key: "k",
            width: 110,
            render: (_, r) => <Tag color={r.kaynak === "SATIS" ? "blue" : "purple"}>{r.kaynak === "SATIS" ? "Satış" : "Kiralama"}</Tag>,
          },
          {
            title: "Kayıt",
            key: "no",
            render: (_, r) =>
              r.service_order_id ? (
                <Link to={`/servis-isleri/${r.service_order_id}`}>{r.so_no}</Link>
              ) : (
                <Link to={`/kiralamalar/${r.rental_id}`}>{r.rental_no}</Link>
              ),
          },
          { title: "Müşteri", dataIndex: "musteri", ellipsis: true },
          { title: "Konu", dataIndex: "konu", ellipsis: true },
          { title: "Birim", dataIndex: "birim", width: 120, render: (b: string) => BIRIM_ETIKETLERI[b] ?? b },
          {
            title: "Durum",
            key: "d",
            width: 160,
            render: (_, r) =>
              r.planlandi ? (
                <Tag color="green">Planlandı</Tag>
              ) : r.durum === "MUDURDE" ? (
                <Tag color="orange">Müdürde</Tag>
              ) : (
                <Tag color="blue">Birimde: {r.hedef_ad}</Tag>
              ),
          },
          {
            title: "Geliş",
            dataIndex: "created_at",
            width: 120,
            render: (x: string) => dayjs(x).format("DD.MM.YYYY HH:mm"),
          },
          ...(mudur
            ? [
                {
                  title: "",
                  key: "a",
                  width: 120,
                  render: (_: unknown, r: Yonlendirme) =>
                    !r.planlandi && (
                      <Button size="small" icon={<SendOutlined />} onClick={() => setSecili(r)}>
                        {r.durum === "MUDURDE" ? "Yönlendir" : "Değiştir"}
                      </Button>
                    ),
                },
              ]
            : []),
        ]}
      />
      {secili && <YonlendirPenceresi kayit={secili} onKapat={() => setSecili(null)} />}
    </Card>
  );
}

function YonlendirPenceresi({ kayit, onKapat }: { kayit: Yonlendirme; onKapat: () => void }) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [form] = Form.useForm<{ hedef_user_id: number; not?: string }>();
  const adaylar = useQuery({
    queryKey: ["yonlendirme-adaylari", kayit.birim],
    queryFn: () => yonlendirmeApi.adaylar(kayit.birim),
  });
  const gonder = useMutation({
    mutationFn: (v: { hedef_user_id: number; not?: string }) =>
      yonlendirmeApi.yonlendir(kayit.id, { hedef_user_id: v.hedef_user_id, version: kayit.version, not: v.not || null }),
    onSuccess: () => {
      message.success("Yönlendirildi");
      void qc.invalidateQueries({ queryKey: ["yonlendirmeler"] });
      onKapat();
    },
    onError: (e: Error) => void message.error(e.message),
  });
  return (
    <Modal
      open
      title={`${kayit.so_no ?? kayit.rental_no}: birime yönlendir`}
      onCancel={onKapat}
      onOk={() => form.submit()}
      okText="Yönlendir"
      cancelText="Vazgeç"
      confirmLoading={gonder.isPending}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" initialValues={{ hedef_user_id: kayit.hedef_user_id ?? undefined }} onFinish={(v) => gonder.mutate(v)}>
        <Form.Item
          name="hedef_user_id"
          label={`${BIRIM_ETIKETLERI[kayit.birim] ?? kayit.birim} yöneticisi / şefi`}
          rules={[{ required: true, message: "Kişi seçin" }]}
          extra="Birimin üyesi ve planlama yetkisi olan kişiler listelenir."
        >
          <Select
            loading={adaylar.isLoading}
            showSearch={{ optionFilterProp: "label" }}
            options={(adaylar.data ?? []).map((a) => ({ value: a.id, label: a.unvan ? `${a.ad} — ${a.unvan}` : a.ad }))}
          />
        </Form.Item>
        <Form.Item name="not" label="Not (isteğe bağlı)">
          <Input.TextArea rows={2} maxLength={500} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
