/**
 * Bakım Formu — dijital planlı bakım formu (TS-064…068).
 *
 * Çekmece (Drawer); dönem cihaz listesinden ve servis işinden açılır.
 * - Her kontrol maddesinde 4 seçenek; Uygunsuz / Kontrol Edilemedi seçilince
 *   not alanı açılır ve zorunludur (sunucu da 400 verir).
 * - "Kontrol edilmeyenleri Uygun işaretle" yalnız BEKLIYOR olanları işaretler.
 * - Taslak Kaydet ziyaret kaydı OLUŞTURMAZ; Formu Tamamla doğrular, ziyaret
 *   yazar; uygunsuz madde varsa iş aksiyonlar kapanana kadar beklemede kalır.
 * - Müşteri onayı (zorunluysa) tamamlamadan önce alınır; "Alınamadı + neden"
 *   de onay kaydıdır (saha bloke olmaz).
 * - Tamamlanmış form salt okunurdur; düzeltme E01 "Yeniden Aç" (`servis.kapat`).
 * - Düğmeler `yetkili()` ile; 409'da yenileme mesajı.
 */
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
  Modal,
  Popconfirm,
  Radio,
  Select,
  Space,
  Table,
  Tag,
  Timeline,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useEffect, useState } from "react";

import {
  AKSIYON_TURLERI,
  BAKIM_SONUCLARI,
  type BakimFormu as BakimFormuVerisi,
  bakimApi,
  CIHAZ_TURLERI,
  hataMetni,
  KAPSAM_DISI_DURUMLARI,
  KAPSAM_DISI_NEDENLERI,
  KONTROL_SONUCLARI,
  ONAY_TURLERI,
  type Uygunsuzluk,
} from "../api/bakim";
import { useAuth } from "../auth/AuthContext";
import ServisParcalari from "../components/ServisParcalari";

const NOT_ZORUNLU = new Set(["UYGUNSUZ", "KONTROL_EDILEMEDI"]);
const KAPALI = new Set(["TAMAMLANDI", "KAPATILDI", "IPTAL"]);

interface Madde {
  sonuc: string;
  not: string | null;
}

export default function BakimFormu({
  soId,
  onKapat,
}: {
  soId: number | null;
  onKapat: () => void;
}) {
  const { message, modal } = App.useApp();
  const { yetkili } = useAuth();
  const qc = useQueryClient();
  const [form] = Form.useForm();
  const [maddeler, setMaddeler] = useState<Record<string, Madde>>({});
  const [onayAcik, setOnayAcik] = useState(false);
  const [kdAcik, setKdAcik] = useState(false);
  const [onayForm] = Form.useForm();
  const [kdForm] = Form.useForm();

  const sorgu = useQuery({
    queryKey: ["bakim", "form", soId],
    queryFn: () => bakimApi.form(soId!),
    enabled: soId != null,
  });
  const veri = sorgu.data;

  useEffect(() => {
    if (!veri) return;
    form.setFieldsValue({
      seri_no: veri.form.seri_no,
      zone: veri.form.zone,
      performed_work: veri.form.performed_work,
      technician_note: veri.form.technician_note,
      parts_text: veri.form.parts_text,
      bakim_sonucu: veri.form.bakim_sonucu,
    });
    setMaddeler(Object.fromEntries(veri.maddeler.map((m) => [m.kod, { sonuc: m.sonuc, not: m.not }])));
  }, [veri, form]);

  const yenile = (yeni?: BakimFormuVerisi) => {
    if (yeni) qc.setQueryData(["bakim", "form", soId], yeni);
    qc.invalidateQueries({ queryKey: ["bakim"] });
  };
  const hata = (e: unknown) => message.error(hataMetni(e));

  const girdi = () => ({
    version: veri?.form.version,
    ...form.getFieldsValue(),
    kontroller: Object.entries(maddeler).map(([kod, m]) => ({ kod, sonuc: m.sonuc, not: m.not })),
  });

  const kaydet = useMutation({
    mutationFn: () => bakimApi.formKaydet(soId!, girdi()),
    onSuccess: (v) => {
      message.success("Taslak kaydedildi");
      yenile(v);
    },
    onError: hata,
  });
  const tamamla = useMutation({
    mutationFn: (sureEksikOnay: boolean) =>
      bakimApi.formTamamla(soId!, { ...girdi(), sure_eksik_onay: sureEksikOnay }),
    onSuccess: (v) => {
      message.success(
        v.acilan_uygunsuzluk
          ? `Form tamamlandı; ${v.acilan_uygunsuzluk} uygunsuzluk aksiyonu açıldı`
          : "Form tamamlandı",
      );
      (v.uyarilar ?? []).forEach((u) => message.warning(u));
      yenile(v);
    },
    onError: (e, sureEksikOnay) => {
      // TS-076: süre kaydı eksikse sunucu 409 verir; kullanıcı bilerek onaylarsa tekrar gönderilir.
      if (!sureEksikOnay && e instanceof Error && e.message.startsWith("Süre kaydı eksik")) {
        modal.confirm({
          title: "Süre kaydı eksik",
          content: e.message,
          okText: "Onaylayarak tamamla",
          cancelText: "Vazgeç",
          onOk: () => tamamla.mutate(true),
        });
        return;
      }
      hata(e);
    },
  });
  const onay = useMutation({
    mutationFn: (g: { tur: string; imzalayan_ad?: string; eksik_nedeni?: string }) =>
      bakimApi.onayAl(soId!, g),
    onSuccess: (v) => {
      message.success("Müşteri onayı kaydedildi");
      setOnayAcik(false);
      onayForm.resetFields();
      yenile(v);
    },
    onError: hata,
  });
  const kapsamDisi = useMutation({
    mutationFn: (g: { neden: string; aciklama: string }) =>
      bakimApi.kapsamDisiTalep(soId!, g.neden, g.aciklama),
    onSuccess: (v) => {
      message.success("Kapsam dışı talebi şef onayına gönderildi");
      setKdAcik(false);
      kdForm.resetFields();
      yenile(v);
    },
    onError: hata,
  });
  const karar = useMutation({
    mutationFn: (g: { id: number; onay: boolean }) => bakimApi.kapsamDisiKarar(soId!, g.id, g.onay),
    onSuccess: (v) => {
      message.success("Karar kaydedildi");
      yenile(v);
    },
    onError: hata,
  });

  const formYazabilir =
    veri != null &&
    veri.form.status === "TASLAK" &&
    !KAPALI.has(veri.so.status) &&
    yetkili("servis.yaz");
  const tamamlayabilir = formYazabilir && yetkili("servis.tamamla") && veri?.so.status !== "BEKLEMEDE";
  const bekleyen = Object.values(maddeler).filter((m) => m.sonuc === "BEKLIYOR").length;

  const hepsiniUygun = () =>
    setMaddeler((eski) =>
      Object.fromEntries(
        Object.entries(eski).map(([k, m]) => [k, m.sonuc === "BEKLIYOR" ? { sonuc: "UYGUN", not: m.not } : m]),
      ),
    );

  return (
    <Drawer
      open={soId != null}
      size={680}
      onClose={onKapat}
      loading={sorgu.isLoading}
      title={veri ? `${veri.form.baslik} · ${veri.so.so_no}` : "Bakım Formu"}
      destroyOnHidden
    >
      {sorgu.isError && <Alert type="error" title={hataMetni(sorgu.error)} />}
      {veri && (
        <Space orientation="vertical" style={{ width: "100%" }} size="middle">
          <Descriptions size="small" column={1} bordered>
            <Descriptions.Item label="Müşteri">{veri.so.musteri ?? "—"}</Descriptions.Item>
            <Descriptions.Item label="Tesis">
              {[veri.so.tesis, veri.so.ilce, veri.so.il].filter(Boolean).join(" · ") || "—"}
            </Descriptions.Item>
            {veri.so.adres && <Descriptions.Item label="Adres">{veri.so.adres}</Descriptions.Item>}
            <Descriptions.Item label="Cihaz">
              {CIHAZ_TURLERI[veri.form.template_code] ?? veri.form.template_code}
              {veri.ekipman?.brand ? ` · ${veri.ekipman.brand} ${veri.ekipman.model ?? ""}` : ""}
            </Descriptions.Item>
            <Descriptions.Item label="Sözleşme / dönem">
              <span className="mono">{veri.sozlesme?.contract_no}</span>
              {veri.donem ? ` · hedef ${dayjs(veri.donem.target_date).format("DD.MM.YYYY")}` : ""}
            </Descriptions.Item>
            <Descriptions.Item label="Durum">
              <Tag>{veri.so.status.replaceAll("_", " ")}</Tag>
              <Tag color={veri.form.status === "TAMAMLANDI" ? "green" : "blue"}>
                Form {veri.form.status === "TAMAMLANDI" ? "tamamlandı" : "taslak"}
              </Tag>
              {veri.form.kutuk_fark_durumu === "ACIK" && <Tag color="orange">Kütük farkı</Tag>}
            </Descriptions.Item>
          </Descriptions>

          <Form form={form} layout="vertical" disabled={!formYazabilir}>
            <Form.Item name="seri_no" label="Seri No" rules={[{ required: true }]}>
              <Input className="mono" maxLength={200} />
            </Form.Item>
            <Form.Item name="zone" label="Bölge" rules={[{ required: true }]}>
              <Input maxLength={120} />
            </Form.Item>

            <Card
              size="small"
              title={`Kontrol listesi${bekleyen ? ` (${bekleyen} bekliyor)` : ""}`}
              extra={
                formYazabilir && bekleyen > 0 ? (
                  <Popconfirm
                    title="Kontrol edilmemiş maddeler Uygun işaretlensin mi?"
                    onConfirm={hepsiniUygun}
                    okText="İşaretle"
                    cancelText="Vazgeç"
                  >
                    <Button size="small">Bekleyenleri Uygun işaretle</Button>
                  </Popconfirm>
                ) : null
              }
            >
              {veri.maddeler.map((m) => {
                const secim = maddeler[m.kod] ?? { sonuc: m.sonuc, not: m.not };
                return (
                  <div key={m.kod} style={{ padding: "8px 0", borderBottom: "1px solid #f0f0f0" }}>
                    <Typography.Text>{m.etiket}</Typography.Text>
                    <div>
                      <Radio.Group
                        size="small"
                        value={secim.sonuc}
                        onChange={(e) =>
                          setMaddeler((eski) => ({
                            ...eski,
                            [m.kod]: { ...secim, sonuc: e.target.value },
                          }))
                        }
                        options={Object.entries(KONTROL_SONUCLARI)
                          .filter(([k]) => k !== "BEKLIYOR" || secim.sonuc === "BEKLIYOR")
                          .map(([value, label]) => ({ value, label }))}
                      />
                    </div>
                    {NOT_ZORUNLU.has(secim.sonuc) && (
                      <Input.TextArea
                        rows={2}
                        placeholder="Açıklama (zorunlu)"
                        status={secim.not?.trim() ? undefined : "error"}
                        value={secim.not ?? ""}
                        maxLength={2000}
                        onChange={(e) =>
                          setMaddeler((eski) => ({
                            ...eski,
                            [m.kod]: { ...secim, not: e.target.value },
                          }))
                        }
                      />
                    )}
                  </div>
                );
              })}
            </Card>

            <Form.Item name="performed_work" label="Yapılan İşlem" style={{ marginTop: 12 }}>
              <Input.TextArea rows={2} maxLength={4000} />
            </Form.Item>
            <Form.Item name="parts_text" label="Parça (katalog dışı not)">
              <Input.TextArea rows={1} maxLength={2000} />
            </Form.Item>
            <Form.Item name="technician_note" label="Teknisyen Notu" rules={[{ required: true }]}>
              <Input.TextArea rows={2} maxLength={4000} />
            </Form.Item>
            <Form.Item name="bakim_sonucu" label="Bakım Sonucu" rules={[{ required: true }]}>
              <Select
                options={Object.entries(BAKIM_SONUCLARI).map(([value, label]) => ({ value, label }))}
              />
            </Form.Item>
          </Form>

          <Card size="small" title="Müşteri onayı">
            {veri.onay ? (
              <Typography.Text>
                {ONAY_TURLERI[veri.onay.tur] ?? veri.onay.tur} ·{" "}
                {dayjs(veri.onay.approved_at).format("DD.MM.YYYY HH:mm")}
              </Typography.Text>
            ) : (
              <Typography.Text type={veri.onay_zorunlu ? "danger" : "secondary"}>
                {veri.onay_zorunlu ? "Onay zorunlu; henüz alınmadı" : "Onay alınmadı"}
              </Typography.Text>
            )}
            {formYazabilir && (
              <Button size="small" style={{ marginLeft: 8 }} onClick={() => setOnayAcik(true)}>
                Onay kaydet
              </Button>
            )}
          </Card>

          <Space wrap>
            {formYazabilir && (
              <Button onClick={() => kaydet.mutate()} loading={kaydet.isPending}>
                Taslak Kaydet
              </Button>
            )}
            {tamamlayabilir && (
              <Popconfirm
                title="Form tamamlansın mı?"
                description="Ziyaret kaydı yazılır; uygunsuz madde varsa iş beklemeye alınır."
                onConfirm={() => form.validateFields().then(() => tamamla.mutate(false))}
                okText="Tamamla"
                cancelText="Vazgeç"
              >
                <Button type="primary" loading={tamamla.isPending}>
                  Formu Tamamla
                </Button>
              </Popconfirm>
            )}
            {yetkili("servis.yaz") && !KAPALI.has(veri.so.status) && (
              <Button danger onClick={() => setKdAcik(true)}>
                Kapsam Dışı Talebi
              </Button>
            )}
            {/* M1.7 (Faz A): kapanmış iş yeniden açılmaz; Servis İşleri ayrıntısında
                "Bağlı yeni iş" düğmesiyle bu işe bağlı yeni iş açılır. */}
          </Space>

          {veri.kapsam_disi.length > 0 && (
            <Card size="small" title="Kapsam dışı talepleri">
              {veri.kapsam_disi.map((t) => (
                <div key={t.id} style={{ marginBottom: 8 }}>
                  <Tag>{KAPSAM_DISI_DURUMLARI[t.status] ?? t.status}</Tag> {KAPSAM_DISI_NEDENLERI[t.reason_code] ?? t.reason_code} —{" "}
                  {t.description}
                  {t.status === "TALEP" && yetkili("bakim.onayla") && (
                    <Space style={{ marginLeft: 8 }}>
                      <Button size="small" type="primary" onClick={() => karar.mutate({ id: t.id, onay: true })}>
                        Onayla
                      </Button>
                      <Button size="small" onClick={() => karar.mutate({ id: t.id, onay: false })}>
                        Reddet
                      </Button>
                    </Space>
                  )}
                </div>
              ))}
            </Card>
          )}

          <UygunsuzlukKarti soId={veri.so.id} kayitlar={veri.uygunsuzluklar} onDegisti={yenile} />

          {/* PB'de kullanılan parçalar aynı defterden (TS-133; eski parça raporu açılmaz). */}
          <ServisParcalari soId={veri.so.id} baslik="Bakımda kullanılan parçalar" />

          <Card size="small" title="Ziyaret geçmişi">
            {veri.ziyaretler.length === 0 ? (
              <Empty description="Henüz ziyaret kaydı yok" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <Timeline
                items={veri.ziyaretler.map((z) => ({
                  color: z.tur === "YENIDEN_ACMA" ? "orange" : "green",
                  content: (
                    <>
                      <b>#{z.visit_no}</b> {dayjs(z.visited_at).format("DD.MM.YYYY HH:mm")} ·{" "}
                      {z.tur === "YENIDEN_ACMA" ? "Yeniden açma" : "Tamamlama"}
                      {z.bakim_sonucu ? ` · ${BAKIM_SONUCLARI[z.bakim_sonucu] ?? z.bakim_sonucu}` : ""}
                      {z.gerekce ? ` — ${z.gerekce}` : ""}
                    </>
                  ),
                }))}
              />
            )}
          </Card>
        </Space>
      )}

      <Modal
        title="Müşteri onayı"
        open={onayAcik}
        onCancel={() => setOnayAcik(false)}
        onOk={() => onayForm.submit()}
        confirmLoading={onay.isPending}
        okText="Kaydet"
        cancelText="Vazgeç"
        destroyOnHidden
      >
        <Form form={onayForm} layout="vertical" onFinish={(v) => onay.mutate(v)}>
          <Form.Item name="tur" label="Yöntem" rules={[{ required: true }]} initialValue="SOZLU">
            <Select
              options={Object.entries(ONAY_TURLERI)
                .filter(([k]) => k === "SOZLU" || k === "ALINAMADI")
                .map(([value, label]) => ({ value, label }))}
            />
          </Form.Item>
          <Form.Item noStyle shouldUpdate>
            {({ getFieldValue }) =>
              getFieldValue("tur") === "ALINAMADI" ? (
                <Form.Item name="eksik_nedeni" label="Neden" rules={[{ required: true }]}>
                  <Input maxLength={300} />
                </Form.Item>
              ) : (
                <Form.Item name="imzalayan_ad" label="Onay veren" rules={[{ required: true }]}>
                  <Input maxLength={120} />
                </Form.Item>
              )
            }
          </Form.Item>
          <Typography.Text type="secondary">
            İmzalı/basılı form ekli onay Servis İşleri ekranından alınır.
          </Typography.Text>
        </Form>
      </Modal>

      <Modal
        title="Kapsam dışı talebi"
        open={kdAcik}
        onCancel={() => setKdAcik(false)}
        onOk={() => kdForm.submit()}
        confirmLoading={kapsamDisi.isPending}
        okText="Gönder"
        cancelText="Vazgeç"
        destroyOnHidden
      >
        <Form form={kdForm} layout="vertical" onFinish={(v) => kapsamDisi.mutate(v)}>
          <Form.Item name="neden" label="Neden" rules={[{ required: true }]}>
            <Select
              options={Object.entries(KAPSAM_DISI_NEDENLERI).map(([value, label]) => ({ value, label }))}
            />
          </Form.Item>
          <Form.Item name="aciklama" label="Açıklama" rules={[{ required: true }]}>
            <Input.TextArea rows={3} maxLength={2000} />
          </Form.Item>
        </Form>
      </Modal>

    </Drawer>
  );
}

function UygunsuzlukKarti({
  soId,
  kayitlar,
  onDegisti,
}: {
  soId: number;
  kayitlar: Uygunsuzluk[];
  onDegisti: (v?: BakimFormuVerisi) => void;
}) {
  const { message } = App.useApp();
  const { yetkili } = useAuth();
  const [kapatilan, setKapatilan] = useState<Uygunsuzluk | null>(null);
  const [kapatForm] = Form.useForm();
  const yonetebilir = yetkili("bakim.onayla");
  const hata = (e: unknown) => message.error(hataMetni(e));

  const duzenle = useMutation({
    mutationFn: (g: { kayit: Uygunsuzluk; action_type?: string; due_date?: string | null }) =>
      bakimApi.uygunsuzlukDuzenle(soId, g.kayit.id, {
        version: g.kayit.version,
        action_type: g.action_type ?? g.kayit.action_type,
        due_date: g.due_date === undefined ? g.kayit.due_date : g.due_date,
      }),
    onSuccess: (v) => onDegisti(v),
    onError: hata,
  });
  const ariza = useMutation({
    mutationFn: (id: number) => bakimApi.uygunsuzlukArizaIsi(soId, id),
    onSuccess: (v) => {
      message.success(`Arıza işi açıldı: ${v.ariza_isi?.so_no ?? ""}`);
      onDegisti(v);
    },
    onError: hata,
  });
  const kapat = useMutation({
    mutationFn: (g: { id: number; not: string }) => bakimApi.uygunsuzlukKapat(soId, g.id, g.not),
    onSuccess: (v) => {
      message.success("Aksiyon kapatıldı");
      setKapatilan(null);
      kapatForm.resetFields();
      onDegisti(v);
    },
    onError: hata,
  });

  if (kayitlar.length === 0) return null;
  return (
    <Card size="small" title="Uygunsuzluk aksiyonları">
      <Table
        size="small"
        rowKey="id"
        pagination={false}
        dataSource={kayitlar}
        scroll={{ x: 560 }}
        columns={[
          { title: "Madde", dataIndex: "check_label", ellipsis: true },
          { title: "Not", dataIndex: "description", ellipsis: true },
          {
            title: "Aksiyon",
            dataIndex: "action_type",
            width: 170,
            render: (v: string | null, r: Uygunsuzluk) =>
              yonetebilir && r.status === "ACIK" ? (
                <Select
                  size="small"
                  style={{ width: 160 }}
                  value={v ?? undefined}
                  placeholder="Seçin"
                  onChange={(t) => duzenle.mutate({ kayit: r, action_type: t })}
                  options={Object.entries(AKSIYON_TURLERI)
                    .filter(([k]) => k !== "ARIZA_IS_EMRI")
                    .map(([value, label]) => ({ value, label, disabled: value === "TEKLIF" }))}
                />
              ) : (
                (v && AKSIYON_TURLERI[v]) ?? "—"
              ),
          },
          {
            title: "Hedef",
            dataIndex: "due_date",
            width: 130,
            render: (v: string | null, r: Uygunsuzluk) =>
              yonetebilir && r.status === "ACIK" ? (
                <DatePicker
                  size="small"
                  format="DD.MM.YYYY"
                  value={v ? dayjs(v) : null}
                  onChange={(d) => duzenle.mutate({ kayit: r, due_date: d ? d.format("YYYY-MM-DD") : null })}
                />
              ) : v ? (
                dayjs(v).format("DD.MM.YYYY")
              ) : (
                "—"
              ),
          },
          {
            title: "",
            width: 170,
            render: (_: unknown, r: Uygunsuzluk) =>
              r.status === "ACIK" ? (
                yonetebilir ? (
                  <Space size={4}>
                    {r.linked_service_order_id == null && yetkili("servis.yaz") && (
                      <Button size="small" onClick={() => ariza.mutate(r.id)}>
                        Arıza işi
                      </Button>
                    )}
                    <Button size="small" type="primary" onClick={() => setKapatilan(r)}>
                      Kapat
                    </Button>
                  </Space>
                ) : (
                  <Tag color="orange">Açık</Tag>
                )
              ) : (
                <Tag color="green">Kapalı</Tag>
              ),
          },
        ]}
      />
      <Modal
        title="Aksiyonu kapat"
        open={kapatilan != null}
        onCancel={() => setKapatilan(null)}
        onOk={() => kapatForm.submit()}
        confirmLoading={kapat.isPending}
        okText="Kapat"
        cancelText="Vazgeç"
        destroyOnHidden
      >
        <Form
          form={kapatForm}
          layout="vertical"
          onFinish={(v) => kapatilan && kapat.mutate({ id: kapatilan.id, not: v.not })}
        >
          <Form.Item name="not" label="Kapanış notu" rules={[{ required: true }]}>
            <Input.TextArea rows={3} maxLength={2000} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
