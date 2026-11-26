/**
 * İnsan Kaynakları › İzin Talepleri (KARARLAR 2026-11-20 §7).
 *
 * - Taleplerim: personel kendi iznini girer. Vekil (izinde yerine bakacak
 *   personel), izinde bulunacağı il ve iletişim numarası zorunlu.
 * - Onayımda: sırası gelen onaycı onaylar ya da gerekçeyle reddeder.
 *   Zincir: birim şefi → teknik müdür → GMY (org şemasındaki yöneticiler).
 *   24 saatte karar verilmezse talep bir üst yöneticiye geçer.
 * - Tüm talepler: İK (`izin.yonet`) hepsini görür, başkası adına girer.
 */
import { CheckOutlined, CloseOutlined, PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Card,
  DatePicker,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Steps,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { IZIN_TURLERI, izinApi, ONAY_DURUM_ADLARI, type IzinTalebi } from "../api/izin";
import { useAuth } from "../auth/AuthContext";

const DURUM_RENGI: Record<string, string> = {
  BEKLIYOR: "orange",
  ONAYLANDI: "green",
  REDDEDILDI: "red",
  IPTAL: "default",
};

const tarih = (x: string) => dayjs(x).format("DD.MM.YYYY");

function Zincir({ t }: { t: IzinTalebi }) {
  return (
    <Steps
      size="small"
      current={t.onaylar.findIndex((o) => o.durum === "BEKLIYOR")}
      items={t.onaylar.map((o) => ({
        title: o.onaylayici ?? "—",
        description: [ONAY_DURUM_ADLARI[o.durum] ?? o.durum, o.karar_at ? dayjs(o.karar_at).format("DD.MM HH:mm") : null, o.aciklama]
          .filter(Boolean)
          .join(" · "),
        status:
          o.durum === "ONAYLANDI"
            ? "finish"
            : o.durum === "REDDEDILDI"
              ? "error"
              : o.durum === "BEKLIYOR"
                ? "process"
                : "wait",
      }))}
    />
  );
}

function TalepTablosu({
  veri,
  yukleniyor,
  eylem,
  personelGoster,
}: {
  veri: IzinTalebi[];
  yukleniyor: boolean;
  eylem?: (t: IzinTalebi) => React.ReactNode;
  personelGoster?: boolean;
}) {
  return (
    <Table<IzinTalebi>
      size="small"
      rowKey="id"
      loading={yukleniyor}
      dataSource={veri}
      scroll={{ x: 800 }}
      pagination={{ pageSize: 30, hideOnSinglePage: true }}
      expandable={{ expandedRowRender: (t) => <Zincir t={t} /> }}
      columns={[
        ...(personelGoster ? [{ title: "Personel", dataIndex: "personel" }] : []),
        { title: "Tür", dataIndex: "tur_adi", width: 120 },
        { title: "Tarih", key: "t", render: (_: unknown, t: IzinTalebi) => `${tarih(t.baslangic)} – ${tarih(t.bitis)}` },
        { title: "Gün", dataIndex: "gun_sayisi", width: 60 },
        { title: "Vekil", dataIndex: "vekil" },
        { title: "İl", dataIndex: "izin_ili", width: 110 },
        {
          title: "Durum",
          key: "d",
          width: 130,
          render: (_: unknown, t: IzinTalebi) => <Tag color={DURUM_RENGI[t.durum]}>{t.durum_adi}</Tag>,
        },
        ...(eylem ? [{ title: "", key: "e", width: 190, render: (_: unknown, t: IzinTalebi) => eylem(t) }] : []),
      ]}
    />
  );
}

interface TalepFormu {
  personel_id?: number;
  tur: string;
  tarih: [Dayjs, Dayjs];
  vekil_id: number;
  izin_ili: string;
  iletisim_tel: string;
  aciklama?: string;
}

function YeniTalepPenceresi({ acik, onKapat, ik }: { acik: boolean; onKapat: () => void; ik: boolean }) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [form] = Form.useForm<TalepFormu>();
  const adaylar = useQuery({ queryKey: ["izin-vekil-adaylari"], queryFn: izinApi.vekilAdaylari, enabled: acik });
  const gonder = useMutation({
    mutationFn: (v: TalepFormu) =>
      izinApi.olustur({
        personel_id: v.personel_id ?? null,
        tur: v.tur,
        baslangic: v.tarih[0].format("YYYY-MM-DD"),
        bitis: v.tarih[1].format("YYYY-MM-DD"),
        vekil_id: v.vekil_id,
        izin_ili: v.izin_ili.trim(),
        iletisim_tel: v.iletisim_tel.trim(),
        aciklama: v.aciklama?.trim() || null,
      }),
    onSuccess: () => {
      message.success("İzin talebi gönderildi; ilk onaycıya iletildi");
      void qc.invalidateQueries({ queryKey: ["izin"] });
      form.resetFields();
      onKapat();
    },
    onError: (e: Error) => void message.error(e.message),
  });
  const kisiler = (adaylar.data ?? []).map((a) => ({ value: a.id, label: a.unvan ? `${a.ad} — ${a.unvan}` : a.ad }));
  return (
    <Modal
      open={acik}
      title="Yeni izin talebi"
      onCancel={onKapat}
      onOk={() => form.submit()}
      okText="Gönder"
      cancelText="Vazgeç"
      confirmLoading={gonder.isPending}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" initialValues={{ tur: "YILLIK" }} onFinish={(v) => gonder.mutate(v)}>
        {ik && (
          <Form.Item name="personel_id" label="Personel (boşsa kendiniz)">
            <Select allowClear showSearch={{ optionFilterProp: "label" }} options={kisiler} />
          </Form.Item>
        )}
        <Form.Item name="tur" label="İzin türü" rules={[{ required: true }]}>
          <Select options={IZIN_TURLERI.map((t) => ({ ...t }))} />
        </Form.Item>
        <Form.Item name="tarih" label="Tarih aralığı" rules={[{ required: true, message: "Tarihleri seçin" }]}>
          <DatePicker.RangePicker format="DD.MM.YYYY" style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item
          name="vekil_id"
          label="Vekil (izindeyken yerinize bakacak kişi)"
          rules={[{ required: true, message: "Vekil seçmek zorunlu" }]}
        >
          <Select showSearch={{ optionFilterProp: "label" }} loading={adaylar.isLoading} options={kisiler} />
        </Form.Item>
        <Form.Item
          name="izin_ili"
          label="İzinde bulunacağınız il"
          rules={[{ required: true, whitespace: true, message: "İl zorunlu" }]}
        >
          <Input maxLength={60} />
        </Form.Item>
        <Form.Item
          name="iletisim_tel"
          label="İzindeyken ulaşılacak telefon"
          rules={[
            { required: true, whitespace: true, message: "Telefon zorunlu" },
            {
              validator: (_, v?: string) =>
                !v || (v.match(/\d/g) ?? []).length >= 10
                  ? Promise.resolve()
                  : Promise.reject(new Error("En az 10 haneli numara girin")),
            },
          ]}
        >
          <Input maxLength={30} inputMode="tel" />
        </Form.Item>
        <Form.Item name="aciklama" label="Açıklama">
          <Input.TextArea rows={2} maxLength={2000} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

export default function IzinTalepleriPage() {
  const { yetkili, kullanici } = useAuth();
  const { message, modal } = App.useApp();
  const qc = useQueryClient();
  const [arama, setArama] = useSearchParams();
  const ik = yetkili("izin.yonet");
  const [yeni, setYeni] = useState(false);
  const sekme = arama.get("sekme") ?? "benim";

  const benim = useQuery({ queryKey: ["izin", "benim"], queryFn: izinApi.benim });
  const onayimda = useQuery({ queryKey: ["izin", "onayimda"], queryFn: () => izinApi.onayimda(true) });
  const tum = useQuery({ queryKey: ["izin", "tum"], queryFn: izinApi.tum, enabled: ik });

  const tazele = () => void qc.invalidateQueries({ queryKey: ["izin"] });
  const iptal = useMutation({
    mutationFn: (id: number) => izinApi.iptal(id),
    onSuccess: () => {
      message.success("Talep iptal edildi");
      tazele();
    },
    onError: (e: Error) => void message.error(e.message),
  });
  const karar = useMutation({
    mutationFn: (g: { onayId: number; karar: "ONAY" | "RED"; aciklama?: string }) =>
      izinApi.karar(g.onayId, g.karar, g.aciklama),
    onSuccess: (_, g) => {
      message.success(g.karar === "ONAY" ? "Onaylandı" : "Reddedildi");
      tazele();
    },
    onError: (e: Error) => void message.error(e.message),
  });

  // Bekleyen basamak bende mi (liste karar verdiklerimi de içerir).
  const benimBasamagim = (t: IzinTalebi) =>
    t.onaylar.find((o) => o.durum === "BEKLIYOR" && o.onaylayici_id === kullanici?.id);

  const reddet = (onayId: number) => {
    let gerekce = "";
    modal.confirm({
      title: "İzin talebini reddet",
      content: (
        <Input.TextArea rows={3} maxLength={500} placeholder="Red gerekçesi (zorunlu)" onChange={(e) => (gerekce = e.target.value)} />
      ),
      okText: "Reddet",
      okButtonProps: { danger: true },
      cancelText: "Vazgeç",
      onOk: () => {
        if (!gerekce.trim()) {
          message.warning("Red gerekçesi zorunlu");
          return Promise.reject(new Error("gerekçe"));
        }
        return karar.mutateAsync({ onayId, karar: "RED", aciklama: gerekce.trim() });
      },
    });
  };

  const bekleyenSayisi = (onayimda.data ?? []).filter((t) => t.durum === "BEKLIYOR" && benimBasamagim(t)).length;

  return (
    <Card
      title="İzin Talepleri"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setYeni(true)}>
          Yeni izin talebi
        </Button>
      }
    >
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        Talep sırasıyla birim şefine, teknik müdüre ve GMY'ye gider. 24 saat içinde karar verilmezse bir üst
        yöneticiye geçer. Son onaydan sonra İnsan Kaynakları'na bildirilir.
      </Typography.Paragraph>
      <Tabs
        activeKey={sekme}
        onChange={(k) => setArama({ sekme: k }, { replace: true })}
        items={[
          {
            key: "benim",
            label: "Taleplerim",
            children: (
              <TalepTablosu
                veri={benim.data ?? []}
                yukleniyor={benim.isLoading}
                eylem={(t) =>
                  t.durum === "BEKLIYOR" && (
                    <Button size="small" onClick={() => iptal.mutate(t.id)} loading={iptal.isPending}>
                      İptal et
                    </Button>
                  )
                }
              />
            ),
          },
          {
            key: "onay",
            label: `Onayımda${bekleyenSayisi ? ` (${bekleyenSayisi})` : ""}`,
            children: (
              <TalepTablosu
                personelGoster
                veri={onayimda.data ?? []}
                yukleniyor={onayimda.isLoading}
                eylem={(t) => {
                  const o = t.durum === "BEKLIYOR" ? benimBasamagim(t) : undefined;
                  return (
                    o && (
                      <Space>
                        <Button
                          size="small"
                          type="primary"
                          icon={<CheckOutlined />}
                          onClick={() => karar.mutate({ onayId: o.id, karar: "ONAY" })}
                        >
                          Onayla
                        </Button>
                        <Button size="small" danger icon={<CloseOutlined />} onClick={() => reddet(o.id)}>
                          Reddet
                        </Button>
                      </Space>
                    )
                  );
                }}
              />
            ),
          },
          ...(ik
            ? [
                {
                  key: "tum",
                  label: "Tüm talepler",
                  children: <TalepTablosu personelGoster veri={tum.data ?? []} yukleniyor={tum.isLoading} />,
                },
              ]
            : []),
        ]}
      />
      <YeniTalepPenceresi acik={yeni} onKapat={() => setYeni(false)} ik={ik} />
    </Card>
  );
}
