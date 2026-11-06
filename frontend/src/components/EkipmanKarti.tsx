/**
 * Ekipman Kartı — kart ve birleşik geçmiş (TS-051/052/055/056/057).
 *
 * Sekmeler: Özet · Geçmiş (servis işi, PB, bakım ziyareti, kütük olayları;
 * tek sunucu fonksiyonu) · Değişiklikler (kim, ne zaman, eski → yeni) · Ekler ·
 * Görevler. "Serviste" rozeti sunucuda açık arıza işinden hesaplanır.
 * Süre kaydı olmayan iş "süre eksik" görünür, 0 dakika DEĞİL. Maliyet
 * yalnız sunucu gönderirse (maliyet.gor) gösterilir.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  DatePicker,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Tabs,
  Tag,
  Timeline,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useRef, useState } from "react";

import { BIRIM_ETIKETLERI } from "../api/personel";
import {
  DURUM_ETIKETLERI,
  DURUM_RENKLERI,
  ekipmanApi,
  GARANTI_ETIKETLERI,
  GARANTI_KAYNAKLARI,
  TIP_ETIKETLERI,
  type Degisiklik,
  type EkipmanKarti as Kart,
  type GecmisOlayi,
} from "../api/servisEkipman";
import { useAuth } from "../auth/AuthContext";
import EkYukleyici from "./EkYukleyici";
import KayitGorevleri from "./KayitGorevleri";

const tarih = (d?: string | null) => (d ? dayjs(d).format("DD.MM.YYYY") : "—");

const OLAY_RENKLERI: Record<string, string> = {
  SERVIS_ISI: "red",
  PB: "blue",
  BAKIM: "green",
  KUTUK: "gray",
};

const OLAY_ETIKETLERI: Record<string, string> = {
  SERVIS_ISI: "Servis işi",
  PB: "Planlı bakım",
  BAKIM: "Bakım ziyareti",
  KUTUK: "Kütük",
  PARCA: "Parça",
  ATOLYE: "Atölye",
};

export function GarantiEtiketi({ durum }: { durum: string }) {
  const renk = durum === "GECERLI" ? "green" : durum === "BITTI" ? "red" : "default";
  return <Tag color={renk}>{GARANTI_ETIKETLERI[durum] ?? durum}</Tag>;
}

function deger(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function DegisiklikSatiri({ d }: { d: Degisiklik }) {
  const alanlar = Array.from(new Set([...Object.keys(d.eski ?? {}), ...Object.keys(d.yeni ?? {})])).filter(
    (a) => a !== "kvkk",
  );
  const maskeli = d.yeni && "kvkk" in d.yeni;
  return (
    <Space orientation="vertical" size={0} style={{ width: "100%" }}>
      <span>
        <strong>{d.etiket}</strong>
        {d.kisisel && (
          <Tag color="purple" style={{ marginLeft: 6 }}>
            kişisel veri
          </Tag>
        )}
      </span>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {dayjs(d.zaman).format("DD.MM.YYYY HH:mm")} · {d.kullanici ?? "sistem"}
      </Typography.Text>
      {maskeli ? (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          Değer KVKK kapsamında imha edildi
        </Typography.Text>
      ) : (
        alanlar.map((a) => (
          <Typography.Text key={a} style={{ fontSize: 12, wordBreak: "break-word" }}>
            <span className="mono">{a}</span>: {deger(d.eski?.[a])} → <strong>{deger(d.yeni?.[a])}</strong>
          </Typography.Text>
        ))
      )}
    </Space>
  );
}

function GecmisSatiri({ o }: { o: GecmisOlayi }) {
  return (
    <Space orientation="vertical" size={0}>
      <Space size={6} wrap>
        <Tag color={OLAY_RENKLERI[o.tur]}>{OLAY_ETIKETLERI[o.tur] ?? o.tur}</Tag>
        <span style={{ wordBreak: "break-word" }}>{o.baslik}</span>
        {o.eslesme === "METIN" && (
          <Tag color="gold" title="İş ekipmana bağlı değil; seri numarası metniyle eşleşti">
            seri eşleşmesi
          </Tag>
        )}
      </Space>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {dayjs(o.tarih).format("DD.MM.YYYY HH:mm")}
        {o.durum ? ` · ${o.durum.replaceAll("_", " ")}` : ""}
        {(o.tur === "SERVIS_ISI" || o.tur === "PB") &&
          (o.sure_eksik ? " · süre kaydı eksik" : ` · ${o.sure_dakika} dk`)}
        {"maliyet" in o && o.maliyet != null ? ` · ${o.maliyet.toLocaleString("tr-TR")} TL` : ""}
      </Typography.Text>
    </Space>
  );
}

interface DurumFormu {
  hedef: string;
  gerekce: string;
  tarih?: Dayjs | null;
}

export default function EkipmanKarti({
  ekipmanId,
  onKapat,
  onDuzenle,
  onDegisti,
}: {
  ekipmanId: number | null;
  onKapat: () => void;
  onDuzenle: (k: Kart) => void;
  onDegisti: () => void;
}) {
  const { yetkili } = useAuth();
  const { message, modal } = App.useApp();
  const qc = useQueryClient();
  const yazabilir = yetkili("ekipman.yaz");
  const imhaGerekcesi = useRef("");
  const [durumAcik, setDurumAcik] = useState(false);
  const [aktiflikAcik, setAktiflikAcik] = useState(false);
  const [uyarilar, setUyarilar] = useState<string[]>([]);
  const [durumForm] = Form.useForm<DurumFormu>();
  const [aktiflikForm] = Form.useForm<{ gerekce: string; mukerrer_gerekcesi?: string }>();
  const acik = ekipmanId != null;

  const kart = useQuery({
    queryKey: ["servis-ekipman-kart", ekipmanId],
    queryFn: () => ekipmanApi.getir(ekipmanId!),
    enabled: acik,
  });
  const gecmis = useQuery({
    queryKey: ["servis-ekipman-gecmis", ekipmanId],
    queryFn: () => ekipmanApi.gecmis(ekipmanId!),
    enabled: acik,
  });
  const degisiklikler = useQuery({
    queryKey: ["servis-ekipman-degisiklik", ekipmanId],
    queryFn: () => ekipmanApi.degisiklikler(ekipmanId!),
    enabled: acik,
  });

  // Kayıtlı frekans (Haberleşme; KARARLAR §12): arıza işine buradan kopyalanır.
  const [frekansAcik, setFrekansAcik] = useState(false);
  const [frekansForm] = Form.useForm<Record<string, string>>();
  const frekansKaydet = useMutation({
    mutationFn: (v: Record<string, string>) => {
      const temiz = Object.fromEntries(Object.entries(v).filter(([, d]) => d != null && String(d).trim() !== ""));
      return ekipmanApi.guncelle(ekipmanId!, {
        frekans: Object.keys(temiz).length ? temiz : null,
        version: kart.data!.version,
      });
    },
    onSuccess: () => {
      setFrekansAcik(false);
      message.success("Kayıtlı frekans güncellendi");
      tazele();
    },
    onError: (e) => message.error((e as Error).message),
  });

  const tazele = () => {
    void qc.invalidateQueries({ queryKey: ["servis-ekipman-kart", ekipmanId] });
    void qc.invalidateQueries({ queryKey: ["servis-ekipman-gecmis", ekipmanId] });
    void qc.invalidateQueries({ queryKey: ["servis-ekipman-degisiklik", ekipmanId] });
    onDegisti();
  };

  const durum = useMutation({
    mutationFn: (v: DurumFormu) =>
      ekipmanApi.durum(ekipmanId!, {
        hedef: v.hedef,
        gerekce: v.gerekce,
        tarih: v.tarih ? v.tarih.format("YYYY-MM-DD") : null,
      }),
    onSuccess: (k) => {
      message.success("Durum değişti");
      setUyarilar(k.uyarilar);
      setDurumAcik(false);
      tazele();
    },
    onError: (e: Error) => message.error(e.message),
  });

  const aktiflik = useMutation({
    mutationFn: (v: { gerekce: string; mukerrer_gerekcesi?: string }) =>
      kart.data!.is_active
        ? ekipmanApi.pasif(ekipmanId!, v.gerekce)
        : ekipmanApi.aktif(ekipmanId!, v.gerekce, v.mukerrer_gerekcesi || undefined),
    onSuccess: (k) => {
      message.success(k.is_active ? "Kayıt aktifleştirildi" : "Kayıt pasife alındı");
      setAktiflikAcik(false);
      tazele();
    },
    onError: (e: Error) => message.error(e.message),
  });

  const imha = useMutation({
    mutationFn: (gerekce: string) => ekipmanApi.irtibatImha(ekipmanId!, gerekce),
    onSuccess: () => {
      message.success("İrtibat bilgisi imha edildi");
      imhaGerekcesi.current = "";
      tazele();
    },
    onError: (e: Error) => message.error(e.message),
  });

  const k = kart.data;

  return (
    <Drawer
      title={k ? `${TIP_ETIKETLERI[k.equipment_type] ?? k.equipment_type} · ${k.serial_no ?? `#${k.id}`}` : ""}
      open={acik}
      size={680}
      onClose={() => {
        setUyarilar([]);
        onKapat();
      }}
      destroyOnHidden
      extra={
        k &&
        yazabilir && (
          <Space wrap>
            <Button onClick={() => onDuzenle(k)}>Düzenle</Button>
            <Button
              disabled={k.sonraki_durumlar.length === 0}
              onClick={() => {
                durumForm.resetFields();
                setDurumAcik(true);
              }}
            >
              Durum
            </Button>
            <Button
              danger={k.is_active}
              disabled={!k.is_active && k.merged_into_id != null}
              onClick={() => {
                aktiflikForm.resetFields();
                setAktiflikAcik(true);
              }}
            >
              {k.is_active ? "Pasife al" : "Aktifleştir"}
            </Button>
          </Space>
        )
      }
    >
      {kart.isError && <Alert type="error" showIcon title={(kart.error as Error).message} />}
      {k && (
        <Tabs
          items={[
            {
              key: "ozet",
              label: "Özet",
              children: (
                <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
                  {uyarilar.map((u) => (
                    <Alert key={u} type="warning" showIcon title={u} />
                  ))}
                  <Space wrap>
                    <Tag color={DURUM_RENKLERI[k.lifecycle_status]}>
                      {DURUM_ETIKETLERI[k.lifecycle_status] ?? k.lifecycle_status}
                    </Tag>
                    {k.serviste && <Tag color="volcano">Serviste</Tag>}
                    {!k.is_active && <Tag>Pasif</Tag>}
                    {k.seri_eksik && <Tag color="gold">Seri no eksik</Tag>}
                    {k.merged_into_id != null && <Tag>Birleştirildi → #{k.merged_into_id}</Tag>}
                    <GarantiEtiketi durum={k.garanti_durumu} />
                  </Space>
                  <Descriptions size="small" column={1} bordered>
                    <Descriptions.Item label="Birim">{BIRIM_ETIKETLERI[k.birim] ?? k.birim}</Descriptions.Item>
                    <Descriptions.Item label="Marka / model">
                      {[k.brand, k.model].filter(Boolean).join(" ") || "—"}
                    </Descriptions.Item>
                    <Descriptions.Item label="Seri no">
                      <span className="mono">{k.serial_no ?? "—"}</span>
                    </Descriptions.Item>
                    <Descriptions.Item label="Müşteri">
                      {k.hesap_unvan ?? (k.customer_name_raw ? `${k.customer_name_raw} (eşleşmedi)` : "—")}
                    </Descriptions.Item>
                    <Descriptions.Item label="Lokasyon">
                      {[k.lokasyon_adi, k.il].filter(Boolean).join(" · ") || k.location_raw || "—"}
                    </Descriptions.Item>
                    <Descriptions.Item label="Bölge">{k.zone ?? "—"}</Descriptions.Item>
                    {k.irtibat_adi && (
                      <Descriptions.Item label="İrtibat">
                        {k.irtibat_adi}
                        {yetkili("kvkk.yonet") && (
                          <Button
                            size="small"
                            type="link"
                            danger
                            onClick={() =>
                              modal.confirm({
                                title: "İrtibat bilgisi imha edilsin mi? (KVKK)",
                                content: (
                                  <Input
                                    placeholder="Başvuru referansı / gerekçe"
                                    onChange={(e) => (imhaGerekcesi.current = e.target.value)}
                                  />
                                ),
                                okText: "İmha et",
                                okButtonProps: { danger: true },
                                cancelText: "Vazgeç",
                                onOk: () => imha.mutateAsync(imhaGerekcesi.current),
                              })
                            }
                          >
                            İmha et
                          </Button>
                        )}
                      </Descriptions.Item>
                    )}
                    <Descriptions.Item label="Teslim / kurulum">
                      {k.delivery_date ? tarih(k.delivery_date) : (k.delivery_date_raw ?? "—")} /{" "}
                      {tarih(k.install_date)}
                    </Descriptions.Item>
                    <Descriptions.Item label="Garanti">
                      {tarih(k.warranty_start)} → {tarih(k.warranty_end)}
                      {k.warranty_source ? ` (${GARANTI_KAYNAKLARI[k.warranty_source] ?? k.warranty_source})` : ""}
                    </Descriptions.Item>
                    <Descriptions.Item label="Bakım sözleşmesi">
                      {k.aktif_sozlesmeler.length === 0
                        ? "Bağlı değil"
                        : k.aktif_sozlesmeler.map((s) => (
                            <Tag key={s.kalem_id} color="blue">
                              {s.sozlesme_no}
                            </Tag>
                          ))}
                    </Descriptions.Item>
                    <Descriptions.Item label="Açık servis işi">{k.acik_is_sayisi}</Descriptions.Item>
                    {k.duplicate_ack_reason && (
                      <Descriptions.Item label="Farklı cihaz gerekçesi">{k.duplicate_ack_reason}</Descriptions.Item>
                    )}
                    {k.notes && <Descriptions.Item label="Not">{k.notes}</Descriptions.Item>}
                    {k.birim === "HABERLESME" && (
                      <Descriptions.Item label="Kayıtlı frekans">
                        <Space wrap>
                          {k.frekans?.role_tx ? (
                            <span>
                              TX {k.frekans.role_tx} / RX {k.frekans.role_rx ?? "—"}
                              {k.frekans.calisma_modu ? ` · ${k.frekans.calisma_modu}` : ""}
                            </span>
                          ) : (
                            <Typography.Text type="secondary">Yok — ilk arızada teknisyen girer</Typography.Text>
                          )}
                          {yazabilir && (
                            <Button
                              size="small"
                              onClick={() => {
                                frekansForm.setFieldsValue(k.frekans ?? {});
                                setFrekansAcik(true);
                              }}
                            >
                              Düzenle
                            </Button>
                          )}
                        </Space>
                      </Descriptions.Item>
                    )}
                  </Descriptions>
                </Space>
              ),
            },
            {
              key: "gecmis",
              label: "Geçmiş",
              children:
                (gecmis.data ?? []).length === 0 ? (
                  <Empty description={gecmis.isLoading ? "Yükleniyor…" : "Henüz olay yok"} />
                ) : (
                  <Timeline
                    items={(gecmis.data ?? []).map((o) => ({
                      color: OLAY_RENKLERI[o.tur] ?? "gray",
                      children: <GecmisSatiri o={o} />,
                    }))}
                  />
                ),
            },
            {
              key: "degisiklik",
              label: "Değişiklikler",
              children:
                (degisiklikler.data ?? []).length === 0 ? (
                  <Empty description="Değişiklik yok" />
                ) : (
                  <Timeline
                    items={(degisiklikler.data ?? []).map((d) => ({
                      color: d.kisisel ? "purple" : "gray",
                      children: <DegisiklikSatiri d={d} />,
                    }))}
                  />
                ),
            },
            {
              key: "ekler",
              label: `Ekler (${k.ek_sayisi})`,
              children: (
                <EkYukleyici
                  entity="service_equipment"
                  entityId={k.id}
                  kind="DIGER"
                  yalnizTur={false}
                  baslik="Ekler"
                  aciklama="Cihaz etiketi fotoğrafı, kurulum tutanağı, garanti belgesi."
                  yazabilir={yazabilir}
                />
              ),
            },
            {
              key: "gorevler",
              label: "Görevler",
              children: <KayitGorevleri entity="ekipman" entityId={k.id} />,
            },
          ]}
        />
      )}

      <Modal
        title="Durum değiştir"
        open={durumAcik}
        onCancel={() => setDurumAcik(false)}
        onOk={() => durumForm.submit()}
        okText="Değiştir"
        cancelText="Vazgeç"
        confirmLoading={durum.isPending}
        destroyOnHidden
      >
        <Form form={durumForm} layout="vertical" onFinish={(v) => durum.mutate(v)}>
          <Form.Item name="hedef" label="Yeni durum" rules={[{ required: true }]}>
            <Select
              options={(k?.sonraki_durumlar ?? []).map((d) => ({ value: d, label: DURUM_ETIKETLERI[d] ?? d }))}
            />
          </Form.Item>
          <Form.Item name="gerekce" label="Gerekçe" rules={[{ required: true, whitespace: true, min: 5 }]}>
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
          <Form.Item name="tarih" label="Tarih (kurulumda boşsa bugün)">
            <DatePicker
              format="DD.MM.YYYY"
              style={{ width: "100%" }}
              disabledDate={(d) => d.isAfter(dayjs(), "day")}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={k?.is_active ? "Kaydı pasife al" : "Kaydı aktifleştir"}
        open={aktiflikAcik}
        onCancel={() => setAktiflikAcik(false)}
        onOk={() => aktiflikForm.submit()}
        okText="Onayla"
        cancelText="Vazgeç"
        confirmLoading={aktiflik.isPending}
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          Pasif kayıt hatalı/mükerrer kayıt demektir; cihazın fiziksel durumu "Durum" ile değişir.
        </Typography.Paragraph>
        <Form form={aktiflikForm} layout="vertical" onFinish={(v) => aktiflik.mutate(v)}>
          <Form.Item name="gerekce" label="Gerekçe" rules={[{ required: true, whitespace: true, min: 5 }]}>
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
          {!k?.is_active && (
            <Form.Item
              name="mukerrer_gerekcesi"
              label="Aynı seriyle aktif kayıt varsa: farklı cihaz gerekçesi"
            >
              <Input.TextArea rows={2} maxLength={1000} />
            </Form.Item>
          )}
        </Form>
      </Modal>
      <Modal
        open={frekansAcik}
        title="Kayıtlı frekans"
        okText="Kaydet"
        confirmLoading={frekansKaydet.isPending}
        onCancel={() => setFrekansAcik(false)}
        onOk={() => frekansForm.submit()}
        destroyOnHidden
      >
        <Form form={frekansForm} layout="vertical" onFinish={(v) => frekansKaydet.mutate(v)}>
          <Form.Item name="role_tx" label="Röle TX frekansı (MHz)">
            <Input placeholder="örn. 427.1125" maxLength={12} />
          </Form.Item>
          <Form.Item name="role_rx" label="Röle RX frekansı (MHz)">
            <Input placeholder="örn. 417.1125" maxLength={12} />
          </Form.Item>
          <Form.Item name="calisma_modu" label="Çalışma modu">
            <Select allowClear options={["ANALOG", "DIJITAL", "MIX"].map((m) => ({ value: m, label: m }))} />
          </Form.Item>
          <Typography.Text type="secondary">
            Diğer frekans alanları (ton, CC, slot, simpleks) arıza işindeki cihaz bilgisinden de girilebilir.
          </Typography.Text>
        </Form>
      </Modal>
    </Drawer>
  );
}
