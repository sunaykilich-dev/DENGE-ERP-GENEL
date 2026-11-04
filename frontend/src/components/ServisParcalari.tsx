/**
 * Servis işinin "Kullanılan Parçalar" bölümü — iş detayı, PB formu ve atölye
 * detayında AYNI bileşen (TS-133, E11-04/E11-14, E04-21).
 *
 * - Parça başına NET adet (çıkış − iade − ters kayıt) sunucudan gelir; ön yüz
 *   hesaplamaz.
 * - Maliyet sütunları yalnız sunucu `unit_cost`/`tutar` anahtarını gönderdiyse
 *   (maliyet.gor) gösterilir; anahtar yoksa sütun yoktur (0 gösterilmez).
 * - Çıkış ve parça talebi yalnız AÇIK işte; iade kapalı işte de serbest
 *   (yanlış çıkışın stoğa geri alınması). Ters kayıt `parca.yonet`.
 * - Eski PB "parça raporu" (`maintenance_part_reports`) AÇILMAZ: PB formundaki
 *   parça kullanımı da bu bileşenden, aynı defterden yazılır.
 *
 * Kullanım: `<ServisParcalari soId={so.id} />`.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Collapse,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import {
  type IsParcaHareketi,
  type IsParcaOzeti,
  parcaApi,
  olcuBirimiAdi,
  parcaHatasi,
  TALEP_DURUM_ADLARI,
  type Talep,
} from "../api/yedekParca";
import { useAuth } from "../auth/AuthContext";
import ParcaHareketPenceresi, { type ParcaHareketTuru, ParcaSecici } from "./ParcaHareketPenceresi";

const TALEP_RENGI: Record<string, string> = { ACIK: "gold", KARSILANDI: "green", IPTAL: "default" };
const para = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const zaman = (v: string | null) => (v ? dayjs(v).format("DD.MM.YYYY HH:mm") : "—");

export interface ServisParcalariProps {
  soId: number;
  /** Kart başlığı (gömülü kullanımda değiştirilebilir). */
  baslik?: string;
  /** Yalnız görüntüleme (ör. salt okunur atölye görünümü). */
  saltOkunur?: boolean;
}

export default function ServisParcalari({
  soId,
  baslik = "Kullanılan Parçalar",
  saltOkunur = false,
}: ServisParcalariProps) {
  const { yetkili } = useAuth();
  const { message, modal } = App.useApp();
  const qc = useQueryClient();
  const [pencere, setPencere] = useState<ParcaHareketTuru | null>(null);
  const [talepAcik, setTalepAcik] = useState(false);

  const sorgu = useQuery({
    queryKey: ["parca", "is", soId],
    queryFn: () => parcaApi.isParcalari(soId),
    enabled: yetkili("servis.gor"),
  });

  const tazele = () => qc.invalidateQueries({ queryKey: ["parca"] });

  const talepIptal = useMutation({
    mutationFn: ({ id, neden }: { id: number; neden: string }) => parcaApi.talepIptal(id, neden),
    onSuccess: async () => {
      message.success("Talep iptal edildi");
      await tazele();
    },
    onError: (e) => message.error(parcaHatasi(e).mesaj),
  });

  const tersKayit = useMutation({
    mutationFn: ({ id, gerekce }: { id: number; gerekce: string }) => parcaApi.tersKayit(id, gerekce),
    onSuccess: async () => {
      message.success("Ters kayıt yazıldı");
      await tazele();
    },
    onError: (e) => message.error(parcaHatasi(e).mesaj),
  });

  if (!yetkili("servis.gor")) return null;
  const veri = sorgu.data;
  const maliyetli = (veri?.ozet ?? []).some((o) => "tutar" in o);
  const kullanabilir = !saltOkunur && yetkili("parca.kullan");
  const yonetebilir = !saltOkunur && yetkili("parca.yonet");
  const iadeSecenekleri = (veri?.ozet ?? [])
    .filter((o) => o.net > 0)
    .map((o) => ({ value: o.product_id, label: `${o.kod} — ${o.ad} (net ${o.net} ${olcuBirimiAdi(o.birim)})` }));

  const gerekceSor = (baslikMetni: string, onay: (metin: string) => void) => {
    let metin = "";
    modal.confirm({
      title: baslikMetni,
      content: (
        <Input.TextArea
          rows={2}
          maxLength={300}
          placeholder="Gerekçe (en az 3 karakter)"
          onChange={(e) => {
            metin = e.target.value;
          }}
        />
      ),
      okText: "Onayla",
      cancelText: "Vazgeç",
      onOk: () => {
        if (metin.trim().length < 3) {
          message.error("Gerekçe en az 3 karakter olmalı");
          return Promise.reject(new Error("gerekçe"));
        }
        onay(metin.trim());
        return Promise.resolve();
      },
    });
  };

  const ozetSutunlari = [
    { title: "Kod", dataIndex: "kod", key: "kod" },
    { title: "Parça", dataIndex: "ad", key: "ad" },
    {
      title: "Net adet",
      key: "net",
      align: "right" as const,
      render: (_: unknown, o: IsParcaOzeti) => `${o.net} ${olcuBirimiAdi(o.birim)}`,
    },
    ...(maliyetli
      ? [
          {
            title: "Tutar",
            key: "tutar",
            align: "right" as const,
            render: (_: unknown, o: IsParcaOzeti) => (
              <Space size={4}>
                {para(o.tutar)}
                {o.maliyet_eksik && <Tag color="orange">Maliyet eksik</Tag>}
              </Space>
            ),
          },
        ]
      : []),
  ];

  const hareketSutunlari = [
    { title: "Tarih", key: "t", render: (_: unknown, h: IsParcaHareketi) => zaman(h.created_at) },
    { title: "Tür", dataIndex: "tur_adi", key: "tur" },
    { title: "Parça", key: "p", render: (_: unknown, h: IsParcaHareketi) => `${h.kod} — ${h.ad}` },
    { title: "Depo", dataIndex: "depo_adi", key: "d" },
    {
      title: "Adet",
      key: "a",
      align: "right" as const,
      // Defterde çıkış eksi yazılır; işe göre okunur olsun diye işaret çevrilir.
      render: (_: unknown, h: IsParcaHareketi) => -h.adet,
    },
    ...(maliyetli
      ? [
          {
            title: "Birim maliyet",
            key: "m",
            align: "right" as const,
            render: (_: unknown, h: IsParcaHareketi) => para(h.unit_cost),
          },
        ]
      : []),
    { title: "Kullanıcı", dataIndex: "kullanici", key: "k" },
    ...(yonetebilir
      ? [
          {
            title: "",
            key: "islem",
            render: (_: unknown, h: IsParcaHareketi) =>
              h.tur !== "TERS_KAYIT" && !h.ters_kaydi_var ? (
                <Button
                  size="small"
                  type="link"
                  onClick={() => gerekceSor("Ters kayıt", (g) => tersKayit.mutate({ id: h.id, gerekce: g }))}
                >
                  Ters kayıt
                </Button>
              ) : h.ters_kaydi_var ? (
                <Tag>Ters kaydı var</Tag>
              ) : null,
          },
        ]
      : []),
  ];

  return (
    <Card
      size="small"
      title={baslik}
      loading={sorgu.isLoading}
      extra={
        kullanabilir && veri ? (
          <Space wrap>
            {veri.acik && (
              <Button type="primary" size="small" onClick={() => setPencere("CIKIS")}>
                Parça çıkışı
              </Button>
            )}
            {iadeSecenekleri.length > 0 && (
              <Button size="small" onClick={() => setPencere("IADE")}>
                İade
              </Button>
            )}
            {veri.acik && (
              <Button size="small" onClick={() => setTalepAcik(true)}>
                Parça talebi
              </Button>
            )}
          </Space>
        ) : null
      }
    >
      {sorgu.isError && <Alert type="error" showIcon message={parcaHatasi(sorgu.error).mesaj} />}
      {veri && !veri.acik && kullanabilir && (
        <Typography.Text type="secondary">
          İş kapalı: yeni parça çıkışı ve talep yapılamaz; yanlış çıkış iade ile geri alınabilir.
        </Typography.Text>
      )}
      {veri && (
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          {veri.ozet.length === 0 ? (
            <Empty description="Bu işte kullanılan parça yok" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <Table<IsParcaOzeti>
              size="small"
              rowKey="product_id"
              pagination={false}
              dataSource={veri.ozet}
              columns={ozetSutunlari}
              scroll={{ x: true }}
            />
          )}
          {veri.talepler.length > 0 && (
            <Table<Talep>
              size="small"
              rowKey="id"
              pagination={false}
              dataSource={veri.talepler}
              scroll={{ x: true }}
              title={() => "Parça talepleri"}
              columns={[
                { title: "Parça", key: "p", render: (_, t) => `${t.kod} — ${t.ad}` },
                { title: "Adet", dataIndex: "adet", key: "a", align: "right" },
                {
                  title: "Durum",
                  key: "d",
                  render: (_, t) => (
                    <Space size={4}>
                      <Tag color={TALEP_RENGI[t.durum]}>{TALEP_DURUM_ADLARI[t.durum] ?? t.durum}</Tag>
                      {t.beklemeye_bagli && t.durum === "ACIK" && <Tag color="blue">İş bekliyor</Tag>}
                    </Space>
                  ),
                },
                { title: "Tarih", key: "z", render: (_, t) => zaman(t.created_at) },
                ...(kullanabilir
                  ? [
                      {
                        title: "",
                        key: "i",
                        render: (_: unknown, t: Talep) =>
                          t.durum === "ACIK" ? (
                            <Popconfirm
                              title="Talep iptal edilsin mi?"
                              okText="İptal et"
                              cancelText="Vazgeç"
                              onConfirm={() => talepIptal.mutate({ id: t.id, neden: "Kullanıcı iptal etti" })}
                            >
                              <Button size="small" type="link" danger>
                                İptal
                              </Button>
                            </Popconfirm>
                          ) : (
                            t.iptal_nedeni ?? null
                          ),
                      },
                    ]
                  : []),
              ]}
            />
          )}
          {veri.hareketler.length > 0 && (
            <Collapse
              size="small"
              items={[
                {
                  key: "h",
                  label: `Hareket geçmişi (${veri.hareketler.length})`,
                  children: (
                    <Table<IsParcaHareketi>
                      size="small"
                      rowKey="id"
                      pagination={false}
                      dataSource={veri.hareketler}
                      columns={hareketSutunlari}
                      scroll={{ x: true }}
                    />
                  ),
                },
              ]}
            />
          )}
        </Space>
      )}
      <ParcaHareketPenceresi
        tur={pencere}
        onKapat={() => setPencere(null)}
        soId={soId}
        soNo={veri?.so_no}
        parcaSecenekleri={iadeSecenekleri}
      />
      <TalepPenceresi acik={talepAcik} soId={soId} onKapat={() => setTalepAcik(false)} />
    </Card>
  );
}

/** Parça talebi penceresi (iş ayrıntısı ve mobil sonuç akışı). */
export function TalepPenceresi({ acik, soId, onKapat }: { acik: boolean; soId: number; onKapat: () => void }) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [form] = Form.useForm<{ product_id: number; adet: number; notes?: string; isi_beklet?: boolean }>();
  const [hata, setHata] = useState<string | null>(null);
  const kaydet = useMutation({
    mutationFn: (d: { product_id: number; adet: number; notes?: string; isi_beklet?: boolean }) =>
      parcaApi.talepAc({ service_order_id: soId, ...d, notes: d.notes?.trim() || null }),
    onSuccess: async () => {
      message.success("Parça talebi açıldı");
      await qc.invalidateQueries({ queryKey: ["parca"] });
      // MALZEME beklemesi açılmış olabilir: iş detayı da tazelensin.
      for (const k of ["servis-is", "servis-is-gecmis", "servis-is-bekleme"]) {
        await qc.invalidateQueries({ queryKey: [k, soId] });
      }
      form.resetFields();
      onKapat();
    },
    onError: (e) => setHata(parcaHatasi(e).mesaj),
  });
  return (
    <Modal
      open={acik}
      title="Parça talebi"
      onCancel={() => {
        setHata(null);
        onKapat();
      }}
      onOk={() => form.submit()}
      okText="Talep aç"
      cancelText="Vazgeç"
      confirmLoading={kaydet.isPending}
      destroyOnHidden
    >
      {hata && <Alert type="error" showIcon message={hata} style={{ marginBottom: 12 }} />}
      <Form form={form} layout="vertical" initialValues={{ adet: 1 }} onFinish={(d) => kaydet.mutate(d)}>
        <Form.Item name="product_id" label="Parça" rules={[{ required: true, message: "Parça seçin" }]}>
          <ParcaSecici />
        </Form.Item>
        <Form.Item name="adet" label="Adet" rules={[{ required: true }]}>
          <InputNumber min={1} max={1_000_000} precision={0} />
        </Form.Item>
        <Form.Item name="notes" label="Not" rules={[{ max: 500 }]}>
          <Input.TextArea rows={2} maxLength={500} />
        </Form.Item>
        <Form.Item name="isi_beklet" valuePropName="checked">
          <Checkbox>İşi "Malzeme bekleniyor" durumuna al (parça gelince bekleme kendiliğinden biter)</Checkbox>
        </Form.Item>
      </Form>
    </Modal>
  );
}
