/**
 * Planlı Bakım — sözleşme, dönem, eşleştirme, PB üretimi, uygunsuzluk ve
 * kapsam dışı talepleri (TS-060…069).
 *
 * - Fiori görünümü (rehber §3, fotoğraf 9): ilk sekme "Bakım Bildirimleri"
 *   servis işi liste raporudur (`ServisIsListesi`); kategori şeridi PLANSIZ
 *   (kırmızı) / PLANLI (yeşil) mantığıyla tür ve bakım KPI'larını süzer.
 *   Parametresiz `/bakim` bu sekmeyi açar; eski bağlantılar (`?durum=…`,
 *   `?suresi_doluyor=1`) sözleşmelere gitmeye devam eder.
 * - Üstte tıklanabilir Fiori KPI kutucukları (`KpiKutucugu`): sayı sunucudan,
 *   tıklama aynı süzgeçle sekmeye gider ("sayı = liste").
 * - Sözleşme: tek pencere hem yeni hem düzenleme; kapsam tür+adet; ücret
 *   alanları yalnız `maliyet.gor` sahibine görünür ve ayrı uçtan yazılır.
 *   Tesis çakışması 409'da onay + gerekçe sorulur.
 * - Eşleştirme: sistem önerir (tek aday), şef onaylar; oran ekranda.
 *   Otomatik PB üretimi %100 olmadan açılamaz.
 * - Dönem: cihaz PB tablosu, seçilenleri toplu planla (E02 `PlanPenceresi`),
 *   eksik PB tamamlama, gerekçeli hedef tarih.
 * - Raporlar sekmesi (TS-185): dönem tamamlama, KPI listeleri, uygunsuzluk
 *   analizi ve Excel (`BakimRaporlari`).
 * - Liste sorguları sunucu sayfalamasıyla; düğmeler `yetkili()` ile; 409'da
 *   yenileme mesajı. 375 px'te tablolar yatay kaydırılır, sayfa kaymaz.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Progress,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  bakimApi,
  BakimHatasi,
  CIHAZ_TURLERI,
  type Donem,
  type DonemCihazi,
  type EslestirmeKalemi,
  hataMetni,
  KAPSAM_DISI_NEDENLERI,
  type KapsamDisiTalebi,
  type Onizleme,
  SOZLESME_DURUMLARI,
  type Sozlesme,
  type SozlesmeGirdisi,
  type Uygunsuzluk,
  type UretimKaydi,
} from "../api/bakim";
import { CalendarOutlined, FieldTimeOutlined, ToolOutlined, WarningOutlined } from "@ant-design/icons";

import { BIRIM_ETIKETLERI, BIRIM_KODLARI } from "../api/personel";
import { useAuth } from "../auth/AuthContext";
import EkYukleyici from "../components/EkYukleyici";
import KayitGorevleri from "../components/KayitGorevleri";
import MusteriLokasyonSecici, { type MusteriLokasyonSecimi } from "../components/MusteriLokasyonSecici";
import PlanPenceresi from "../components/PlanPenceresi";
import { BAKIM_DURUM_GRUPLARI, TAYIN } from "../fiori/etiketler";
import { KpiKutucugu } from "../fiori/ListeRaporu";
import BakimFormu from "./BakimFormu";
import BakimRaporlari from "./BakimRaporlari";
import { ServisIsListesi, type ServisKategorisi } from "./ServisIsleriPage";

/** Fotoğraf 9: PLANSIZ (kırmızı) / PLANLI (yeşil) kategori şeridi. */
const BAKIM_KATEGORILERI: ServisKategorisi[] = [
  {
    kod: "PLANSIZ",
    ad: "PLANSIZ BAKIM",
    renk: "kirmizi",
    ipucu: "Plansız bakım işleri",
    suzgec: { tur: "PLANSIZ_BAKIM" },
  },
  { kod: "PLANLI", ad: "PLANLI BAKIM", renk: "yesil", ipucu: "Planlı bakım (PB) işleri", suzgec: { tur: "PB" } },
  {
    kod: "PLANLI_AY",
    ad: "PLANLI BU AY",
    renk: "yesil",
    ikon: <CalendarOutlined />,
    ipucu: "Aktif planı bu aya düşen PB işleri",
    suzgec: { kpi: "bakim_bu_ay_planli" },
  },
  {
    kod: "PLANLI_GECIKEN",
    ad: "PLANLI GECİKEN",
    renk: "yesil",
    ikon: <FieldTimeOutlined />,
    ipucu: "Bakım döneminin hedef tarihi geçmiş açık PB işleri",
    suzgec: { kpi: "bakim_geciken" },
  },
];

/** Bakım bildirimleri sekmesi: ayrıntı Drawer'ı sayfa içinde (rota değişmez). */
function BakimBildirimleri() {
  const [detay, setDetay] = useState<number | null>(null);
  return (
    <ServisIsListesi
      kategoriler={BAKIM_KATEGORILERI}
      varsayilanKategori="PLANLI"
      durumGruplari={BAKIM_DURUM_GRUPLARI}
      detayId={detay}
      detayAc={setDetay}
      sabitParametreler={{ sekme: "bildirimler" }}
      noRozeti={false}
      yeniKayit={false}
    />
  );
}

const KUTUCUK_IKONU = (kod: string) =>
  /gecik|doldu|suresi/i.test(kod) ? <WarningOutlined /> : /donem|vade|ay/i.test(kod) ? <CalendarOutlined /> : <ToolOutlined />;

const SAYFA = 25;
const tarih = (v: string | null | undefined) => (v ? dayjs(v).format("DD.MM.YYYY") : "—");
const DURUM_RENGI: Record<string, string> = {
  TASLAK: "default",
  TEYIT_BEKLIYOR: "gold",
  AKTIF: "green",
  PASIF: "red",
};
const KAPANIS: Record<string, string> = {
  TAMAMLANDI: "Tamamlandı",
  KISMI: "Kısmi",
  YAPILAMADI: "Yapılamadı",
  GOC_BASLANGIC: "Göç başlangıcı",
};

export default function BakimPage() {
  const { yetkili } = useAuth();
  const [params, setParams] = useSearchParams();
  // Parametresiz giriş Fiori liste raporunu açar; parametreli eski bağlantılar
  // (sekmesiz `?durum=…`) sözleşmelere gider.
  const sekme = params.get("sekme") ?? (params.toString() ? "sozlesmeler" : "bildirimler");
  const [formSo, setFormSo] = useState<number | null>(null);

  const ozet = useQuery({ queryKey: ["bakim", "ozet"], queryFn: bakimApi.ozet });

  const sekmeDegistir = (k: string) => {
    const yeni = new URLSearchParams();
    yeni.set("sekme", k);
    setParams(yeni);
  };

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <div className="fl-kutucuklar">
        {ozet.isLoading
          ? Array.from({ length: 4 }, (_, i) => <KpiKutucugu key={i} baslik="" yukleniyor />)
          : (ozet.data?.kutular ?? []).map((k) => (
              <KpiKutucugu
                key={k.kod}
                kod={k.kod}
                baslik={k.baslik}
                tanim={
                  k.birim === "yuzde" && k.payda !== undefined
                    ? `${k.tanim} — ${k.pay ?? 0}/${k.payda}`
                    : k.tanim
                }
                deger={k.deger}
                birim={k.birim === "yuzde" ? "%" : undefined}
                ikon={KUTUCUK_IKONU(k.kod)}
                yol={k.yol}
              />
            ))}
      </div>
      <Card styles={{ body: { paddingTop: 4 } }}>
        <Tabs
          activeKey={sekme}
          onChange={sekmeDegistir}
          items={[
            { key: "bildirimler", label: "Bakım Bildirimleri", children: <BakimBildirimleri /> },
            { key: "sozlesmeler", label: "Sözleşmeler", children: <SozlesmelerSekmesi /> },
            {
              key: "donemler",
              label: "Bakım Dönemleri",
              children: <DonemlerSekmesi onFormAc={setFormSo} />,
            },
            {
              key: "uygunsuzluklar",
              label: "Uygunsuzluklar",
              children: <UygunsuzluklarSekmesi onFormAc={setFormSo} />,
            },
            {
              key: "kapsam-disi",
              label: "Kapsam Dışı Talepleri",
              children: <KapsamDisiSekmesi onFormAc={setFormSo} />,
            },
            ...(yetkili("bakim.yaz") || yetkili("bakim.gor")
              ? [{ key: "uretim", label: "PB Üretimi", children: <UretimSekmesi /> }]
              : []),
            {
              key: "raporlar",
              label: "Raporlar",
              children: <BakimRaporlari onFormAc={setFormSo} />,
            },
          ]}
        />
      </Card>
      <BakimFormu soId={formSo} onKapat={() => setFormSo(null)} />
    </Space>
  );
}

// =============================================================================
// Sözleşmeler
// =============================================================================

function SozlesmelerSekmesi() {
  const { yetkili } = useAuth();
  const [params, setParams] = useSearchParams();
  const [sayfa, setSayfa] = useState(1);
  const [q, setQ] = useState("");
  const durum = params.get("durum") ?? undefined;
  const suresiDoluyor = params.get("suresi_doluyor") === "1";
  const secili = params.get("sozlesme") ? Number(params.get("sozlesme")) : null;
  const [pencere, setPencere] = useState<Sozlesme | "yeni" | null>(null);

  const liste = useQuery({
    queryKey: ["bakim", "sozlesmeler", durum, suresiDoluyor, q, sayfa],
    queryFn: () =>
      bakimApi.sozlesmeler({
        durum,
        suresi_doluyor: suresiDoluyor,
        q,
        limit: SAYFA,
        offset: (sayfa - 1) * SAYFA,
      }),
  });

  const parametre = (ad: string, deger: string | null) => {
    const yeni = new URLSearchParams(params);
    if (deger) yeni.set(ad, deger);
    else yeni.delete(ad);
    setParams(yeni);
    setSayfa(1);
  };

  return (
    <>
      <Space wrap style={{ marginBottom: 12 }}>
        <Input.Search
          placeholder="Sözleşme no / müşteri"
          allowClear
          onSearch={(v) => {
            setQ(v);
            setSayfa(1);
          }}
          style={{ width: 240 }}
        />
        <Select
          allowClear
          placeholder="Durum"
          style={{ width: 170 }}
          value={durum}
          onChange={(v) => parametre("durum", v ?? null)}
          options={Object.entries(SOZLESME_DURUMLARI).map(([value, label]) => ({ value, label }))}
        />
        <Switch
          checked={suresiDoluyor}
          onChange={(v) => parametre("suresi_doluyor", v ? "1" : null)}
          checkedChildren="Bitişi yaklaşan"
          unCheckedChildren="Bitişi yaklaşan"
        />
        {yetkili("bakim.yaz") && (
          <Button type="primary" onClick={() => setPencere("yeni")}>
            Yeni sözleşme
          </Button>
        )}
      </Space>
      <Table<Sozlesme>
        rowKey="id"
        size="small"
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar}
        scroll={{ x: 900 }}
        onRow={(r) => ({ onClick: () => parametre("sozlesme", String(r.id)), style: { cursor: "pointer" } })}
        pagination={{
          current: sayfa,
          pageSize: SAYFA,
          total: liste.data?.toplam,
          onChange: setSayfa,
          showTotal: (t) => `${t} sözleşme`,
        }}
        columns={[
          { title: "No", dataIndex: "contract_no", className: "mono", width: 120 },
          {
            title: "Müşteri / tesis",
            render: (_, r) => (
              <>
                {r.musteri ?? "—"}
                <br />
                <Typography.Text type="secondary">{[r.tesis, r.il].filter(Boolean).join(" · ")}</Typography.Text>
              </>
            ),
          },
          {
            title: "Kapsam",
            render: (_, r) =>
              Object.entries(r.kapsam)
                .map(([t, n]) => `${n} ${CIHAZ_TURLERI[t] ?? t}`)
                .join(" + ") || "—",
          },
          { title: "Dönem", render: (_, r) => `${tarih(r.baslangic)} – ${tarih(r.bitis)}` },
          {
            title: "Yapılan",
            render: (_, r) => (r.sayac.frekans ? `${r.sayac.yapilan}/${r.sayac.frekans}` : "—"),
          },
          {
            title: "Eşleşme",
            render: (_, r) =>
              r.toplam_kalem ? (
                <Tag color={r.eslesen_kalem === r.toplam_kalem ? "green" : "orange"}>
                  {r.eslesen_kalem}/{r.toplam_kalem}
                </Tag>
              ) : (
                "—"
              ),
          },
          {
            title: "Durum",
            dataIndex: "status",
            render: (v: string, r) => (
              <>
                <Tag color={DURUM_RENGI[v]}>{SOZLESME_DURUMLARI[v] ?? v}</Tag>
                {r.suresi_doldu && <Tag color="red">Süresi doldu</Tag>}
              </>
            ),
          },
        ]}
      />
      <SozlesmeDetayi
        id={secili}
        onKapat={() => parametre("sozlesme", null)}
        onDuzenle={(s) => setPencere(s)}
      />
      <SozlesmePenceresi kayit={pencere} onKapat={() => setPencere(null)} />
    </>
  );
}

function SozlesmePenceresi({
  kayit,
  onKapat,
}: {
  kayit: Sozlesme | "yeni" | null;
  onKapat: () => void;
}) {
  const { message, modal } = App.useApp();
  const qc = useQueryClient();
  const [form] = Form.useForm();
  const yeni = kayit === "yeni";
  const mevcut = kayit && kayit !== "yeni" ? kayit : null;

  const kaydet = useMutation({
    mutationFn: (g: SozlesmeGirdisi) =>
      mevcut ? bakimApi.sozlesmeDuzenle(mevcut.id, { ...g, version: mevcut.version }) : bakimApi.sozlesmeEkle(g),
    onSuccess: () => {
      message.success("Sözleşme kaydedildi");
      qc.invalidateQueries({ queryKey: ["bakim"] });
      onKapat();
    },
    onError: (e, g) => {
      if (e instanceof BakimHatasi && e.kod === "DONEM_CAKISMA") {
        cakismaSor(modal, e, (gerekce) =>
          kaydet.mutate({ ...g, cakisma_onayi: true, cakisma_gerekcesi: gerekce }),
        );
        return;
      }
      message.error(hataMetni(e));
    },
  });

  const gonder = (v: Record<string, unknown>) => {
    const secim = v.musteri as MusteriLokasyonSecimi | undefined;
    const [bas, bit] = (v.donem as [dayjs.Dayjs, dayjs.Dayjs] | undefined) ?? [];
    const g: SozlesmeGirdisi = {
      birim: v.birim as string,
      account_id: secim?.musteriId ?? null,
      address_id: secim?.lokasyonId ?? null,
      baslangic: bas ? bas.format("YYYY-MM-DD") : null,
      bitis: bit ? bit.format("YYYY-MM-DD") : null,
      annual_frequency: (v.annual_frequency as number) ?? null,
      fixed_months: (v.fixed_months as number[] | undefined)?.length ? (v.fixed_months as number[]) : null,
      notes: (v.notes as string) || null,
    };
    if (yeni) g.kapsam = { XRAY: (v.xray as number) ?? 0, KAPI_DEDEKTORU: (v.kapi as number) ?? 0 };
    kaydet.mutate(g);
  };

  return (
    <Modal
      title={yeni ? "Yeni bakım sözleşmesi" : `Sözleşme ${mevcut?.contract_no ?? ""}`}
      open={kayit != null}
      onCancel={onKapat}
      onOk={() => form.submit()}
      confirmLoading={kaydet.isPending}
      okText="Kaydet"
      cancelText="Vazgeç"
      destroyOnHidden
      width={640}
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={gonder}
        initialValues={
          mevcut
            ? {
                birim: mevcut.birim,
                musteri: {
                  musteriId: mevcut.account_id,
                  musteriAdi: mevcut.musteri,
                  lokasyonId: mevcut.address_id,
                },
                donem:
                  mevcut.baslangic && mevcut.bitis ? [dayjs(mevcut.baslangic), dayjs(mevcut.bitis)] : undefined,
                annual_frequency: mevcut.annual_frequency,
                fixed_months: mevcut.fixed_months ?? [],
                notes: mevcut.notes,
              }
            : { birim: "GUVENLIK", annual_frequency: 2, xray: 0, kapi: 0 }
        }
      >
        <Form.Item name="birim" label="Birim" rules={[{ required: true }]}>
          <Select options={BIRIM_KODLARI.map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] }))} />
        </Form.Item>
        <Form.Item
          name="musteri"
          label="Sözleşme tarafı (cari) ve tesis"
          rules={[{ validator: (_, v) => (v?.musteriId ? Promise.resolve() : Promise.reject(new Error("Müşteri seçin"))) }]}
        >
          <MusteriLokasyonSecici />
        </Form.Item>
        <Form.Item name="donem" label="Sözleşme dönemi (başlangıç – bitiş)">
          <DatePicker.RangePicker format="DD.MM.YYYY" style={{ width: "100%" }} />
        </Form.Item>
        <Row gutter={12}>
          <Col xs={24} sm={8}>
            <Form.Item name="annual_frequency" label="Yıllık bakım adedi">
              <InputNumber min={1} max={12} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col xs={24} sm={16}>
            <Form.Item name="fixed_months" label="Sabit aylar (isteğe bağlı)">
              <Select
                mode="multiple"
                allowClear
                options={Array.from({ length: 12 }, (_, i) => ({
                  value: i + 1,
                  label: dayjs().month(i).format("MMMM"),
                }))}
              />
            </Form.Item>
          </Col>
        </Row>
        {yeni && (
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="xray" label="X-Ray adedi">
                <InputNumber min={0} max={200} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="kapi" label="Kapı dedektörü adedi">
                <InputNumber min={0} max={200} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>
        )}
        <Form.Item name="notes" label="Not">
          <Input.TextArea rows={2} maxLength={4000} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

function cakismaSor(
  modal: ReturnType<typeof App.useApp>["modal"],
  e: BakimHatasi,
  devam: (gerekce: string) => void,
) {
  const cakisanlar = (e.veri.cakisanlar as { contract_no: string }[] | undefined) ?? [];
  let gerekce = "";
  modal.confirm({
    title: "Aynı tesiste dönemi çakışan sözleşme var",
    content: (
      <>
        <p>{cakisanlar.map((c) => c.contract_no).join(", ")}</p>
        <p>Bilinçli istisnaysa gerekçe yazarak onaylayın (denetime yazılır).</p>
        <Input.TextArea rows={2} maxLength={500} onChange={(ev) => (gerekce = ev.target.value)} />
      </>
    ),
    okText: "Onayla ve kaydet",
    cancelText: "Vazgeç",
    onOk: () => devam(gerekce),
  });
}

function SozlesmeDetayi({
  id,
  onKapat,
  onDuzenle,
}: {
  id: number | null;
  onKapat: () => void;
  onDuzenle: (s: Sozlesme) => void;
}) {
  const { yetkili } = useAuth();
  const { message, modal } = App.useApp();
  const qc = useQueryClient();
  const detay = useQuery({
    queryKey: ["bakim", "sozlesme", id],
    queryFn: () => bakimApi.sozlesme(id!),
    enabled: id != null,
  });
  const s = detay.data;
  const yenile = () => qc.invalidateQueries({ queryKey: ["bakim"] });

  const durum = useMutation({
    mutationFn: (g: { hedef: string; gerekce?: string }) =>
      bakimApi.durum(id!, g.hedef, g.gerekce ? { onay: true, gerekce: g.gerekce } : undefined),
    onSuccess: (v) => {
      message.success("Durum değişti");
      if (v.acik_pb_isleri?.length) {
        message.warning(`Açık PB işleri: ${v.acik_pb_isleri.join(", ")}`);
      }
      yenile();
    },
    onError: (e, g) => {
      if (e instanceof BakimHatasi && e.kod === "DONEM_CAKISMA") {
        cakismaSor(modal, e, (gerekce) => durum.mutate({ hedef: g.hedef, gerekce }));
        return;
      }
      message.error(hataMetni(e));
    },
  });

  return (
    <Drawer
      open={id != null}
      size={820}
      onClose={onKapat}
      loading={detay.isLoading}
      title={s ? `${s.contract_no} · ${s.musteri ?? ""}` : "Sözleşme"}
      extra={
        s &&
        yetkili("bakim.yaz") && (
          <Space wrap>
            <Button onClick={() => onDuzenle(s)}>Düzenle</Button>
            {s.sonraki_durumlar.map((h) => (
              <Popconfirm
                key={h}
                title={`Sözleşme ${SOZLESME_DURUMLARI[h]?.toLowerCase()} yapılsın mı?`}
                onConfirm={() => durum.mutate({ hedef: h })}
                okText="Evet"
                cancelText="Vazgeç"
              >
                <Button type={h === "AKTIF" ? "primary" : "default"} danger={h === "PASIF"}>
                  {h === "AKTIF" ? "Aktifleştir" : "Pasifleştir"}
                </Button>
              </Popconfirm>
            ))}
          </Space>
        )
      }
    >
      {s && (
        <Tabs
          items={[
            {
              key: "ozet",
              label: "Özet",
              children: (
                <Space orientation="vertical" style={{ width: "100%" }}>
                  <Descriptions size="small" column={1} bordered>
                    <Descriptions.Item label="Durum">
                      <Tag color={DURUM_RENGI[s.status]}>{SOZLESME_DURUMLARI[s.status]}</Tag>
                      {s.suresi_doldu && <Tag color="red">Süresi doldu</Tag>}
                    </Descriptions.Item>
                    <Descriptions.Item label="Birim">{BIRIM_ETIKETLERI[s.birim] ?? s.birim}</Descriptions.Item>
                    <Descriptions.Item label="Sözleşme tarafı (cari)">{s.musteri ?? "—"}</Descriptions.Item>
                    <Descriptions.Item label="Tesis">
                      {[s.tesis, s.il].filter(Boolean).join(" · ") || "—"}
                    </Descriptions.Item>
                    <Descriptions.Item label="Dönem">
                      {tarih(s.baslangic)} – {tarih(s.bitis)}
                    </Descriptions.Item>
                    <Descriptions.Item label="Sıklık">
                      {s.annual_frequency ? `Yılda ${s.annual_frequency}` : "—"}
                      {s.fixed_months?.length
                        ? ` (aylar: ${s.fixed_months.map((a) => dayjs().month(a - 1).format("MMMM")).join(", ")})`
                        : ""}
                    </Descriptions.Item>
                    <Descriptions.Item label="Yapılan dönem">
                      {s.sayac.frekans ? `${s.sayac.yapilan}/${s.sayac.frekans}` : "—"}
                      {s.sayac.sonraki_hedef ? ` · sonraki hedef ${tarih(s.sayac.sonraki_hedef)}` : ""}
                    </Descriptions.Item>
                    <Descriptions.Item label="PB işleri">
                      {s.acik_pb ?? 0} açık / {s.toplam_pb ?? 0} toplam
                    </Descriptions.Item>
                    {s.teyit_gerekcesi && (
                      <Descriptions.Item label="Teyit gerekçesi">{s.teyit_gerekcesi}</Descriptions.Item>
                    )}
                    {s.notes && <Descriptions.Item label="Not">{s.notes}</Descriptions.Item>}
                  </Descriptions>
                  <KapsamKarti sozlesme={s} />
                  {yetkili("maliyet.gor") && <UcretKarti sozlesme={s} />}
                  <EkYukleyici
                    entity="maintenance_contracts"
                    entityId={s.id}
                    kind="SOZLESME"
                    baslik="Sözleşme belgeleri"
                    yazabilir={yetkili("bakim.yaz")}
                  />
                  <KayitGorevleri entity="bakim_sozlesme" entityId={s.id} />
                </Space>
              ),
            },
            { key: "eslestirme", label: "Eşleştirme", children: <EslestirmeKarti sozlesmeId={s.id} /> },
            { key: "donemler", label: "Dönemler", children: <SozlesmeDonemleri sozlesmeId={s.id} /> },
          ]}
        />
      )}
    </Drawer>
  );
}

function KapsamKarti({ sozlesme }: { sozlesme: Sozlesme }) {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [duzen, setDuzen] = useState<Record<string, number> | null>(null);
  const kaydet = useMutation({
    mutationFn: (k: Record<string, number>) => bakimApi.kapsam(sozlesme.id, k),
    onSuccess: () => {
      message.success("Kapsam güncellendi");
      setDuzen(null);
      qc.invalidateQueries({ queryKey: ["bakim"] });
    },
    onError: (e) => {
      const isler = e instanceof BakimHatasi ? (e.veri.isler as string[] | undefined) : undefined;
      message.error(isler?.length ? `${hataMetni(e)} (${isler.join(", ")})` : hataMetni(e));
    },
  });
  return (
    <Card
      size="small"
      title="Kapsam (tür + adet)"
      extra={
        yetkili("bakim.yaz") &&
        (duzen ? (
          <Space>
            <Button size="small" onClick={() => setDuzen(null)}>
              Vazgeç
            </Button>
            <Button size="small" type="primary" loading={kaydet.isPending} onClick={() => kaydet.mutate(duzen)}>
              Kaydet
            </Button>
          </Space>
        ) : (
          <Button size="small" onClick={() => setDuzen({ XRAY: 0, KAPI_DEDEKTORU: 0, ...sozlesme.kapsam })}>
            Değiştir
          </Button>
        ))
      }
    >
      {Object.keys(CIHAZ_TURLERI).map((t) => (
        <div key={t} style={{ marginBottom: 6 }}>
          <span style={{ display: "inline-block", width: 140 }}>{CIHAZ_TURLERI[t]}</span>
          {duzen ? (
            <InputNumber
              min={0}
              max={200}
              size="small"
              value={duzen[t] ?? 0}
              onChange={(v) => setDuzen({ ...duzen, [t]: Number(v ?? 0) })}
            />
          ) : (
            <b>{sozlesme.kapsam[t] ?? 0}</b>
          )}
        </div>
      ))}
      <Typography.Text type="secondary">
        Adet azaltma kalemi silmez, kapsam bitişi yazar; açık PB işi olan cihaz çıkarılamaz.
      </Typography.Text>
    </Card>
  );
}

function UcretKarti({ sozlesme }: { sozlesme: Sozlesme }) {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [form] = Form.useForm();
  const kaydet = useMutation({
    mutationFn: (v: { fee_per_visit?: number | null; contract_total?: number | null }) =>
      bakimApi.ucret(sozlesme.id, {
        fee_per_visit: v.fee_per_visit != null ? String(v.fee_per_visit) : null,
        contract_total: v.contract_total != null ? String(v.contract_total) : null,
        currency: "TRY",
      }),
    onSuccess: () => {
      message.success("Ücret kaydedildi");
      qc.invalidateQueries({ queryKey: ["bakim"] });
    },
    onError: (e) => message.error(hataMetni(e)),
  });
  const yazabilir = yetkili("bakim.yaz", "maliyet.gor");
  return (
    <Card size="small" title="Ücret">
      <Form
        form={form}
        layout="inline"
        disabled={!yazabilir}
        onFinish={kaydet.mutate}
        initialValues={{
          fee_per_visit: sozlesme.fee_per_visit != null ? Number(sozlesme.fee_per_visit) : null,
          contract_total: sozlesme.contract_total != null ? Number(sozlesme.contract_total) : null,
        }}
      >
        <Form.Item name="fee_per_visit" label="Ziyaret başı ₺">
          <InputNumber min={0} className="tutar" />
        </Form.Item>
        <Form.Item name="contract_total" label="Toplam ₺">
          <InputNumber min={0} className="tutar" />
        </Form.Item>
        {yazabilir && (
          <Button htmlType="submit" size="small" loading={kaydet.isPending}>
            Kaydet
          </Button>
        )}
      </Form>
    </Card>
  );
}

function EslestirmeKarti({ sozlesmeId }: { sozlesmeId: number }) {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [secim, setSecim] = useState<Record<number, number | null>>({});
  const veri = useQuery({
    queryKey: ["bakim", "eslestirme", sozlesmeId],
    queryFn: () => bakimApi.eslestirme(sozlesmeId),
  });
  const onayla = useMutation({
    mutationFn: () =>
      bakimApi.eslestir(
        sozlesmeId,
        Object.entries(secim).map(([k, v]) => ({ kalem_id: Number(k), equipment_id: v })),
      ),
    onSuccess: () => {
      message.success("Eşleştirme kaydedildi");
      setSecim({});
      qc.invalidateQueries({ queryKey: ["bakim"] });
    },
    onError: (e) => message.error(hataMetni(e)),
  });
  const onerileriAl = () => {
    const yeni: Record<number, number | null> = { ...secim };
    for (const k of veri.data?.kalemler ?? []) if (k.oneri_id && !k.equipment_id) yeni[k.kalem_id] = k.oneri_id;
    setSecim(yeni);
  };
  const yazabilir = yetkili("bakim.yaz");
  const oran = veri.data?.oran;
  return (
    <Space orientation="vertical" style={{ width: "100%" }}>
      {oran && (
        <Card size="small">
          <Typography.Text>
            Eşleştirme: {oran.eslesen}/{oran.toplam}
          </Typography.Text>
          <Progress percent={oran.yuzde} status={oran.yuzde === 100 ? "success" : "active"} />
        </Card>
      )}
      {yazabilir && (
        <Space wrap>
          <Button onClick={onerileriAl}>Tek adaylı önerileri al</Button>
          <Button type="primary" disabled={!Object.keys(secim).length} loading={onayla.isPending} onClick={() => onayla.mutate()}>
            Seçimleri onayla
          </Button>
        </Space>
      )}
      <Table<EslestirmeKalemi>
        rowKey="kalem_id"
        size="small"
        loading={veri.isLoading}
        dataSource={veri.data?.kalemler}
        pagination={false}
        scroll={{ x: 620 }}
        columns={[
          {
            title: "Kalem",
            render: (_, k) => `${CIHAZ_TURLERI[k.equipment_type] ?? k.equipment_type} #${k.sira}`,
            width: 160,
          },
          {
            title: "Ekipman",
            render: (_, k) => {
              if (k.equipment_id && !(k.kalem_id in secim)) {
                return (
                  <span className="mono">
                    {k.ekipman?.serial_no ?? `#${k.equipment_id}`} {k.ekipman?.zone ? `· ${k.ekipman.zone}` : ""}
                  </span>
                );
              }
              if (!yazabilir) return <Tag color="orange">Eşleşmedi</Tag>;
              return (
                <Select
                  allowClear
                  style={{ width: "100%", minWidth: 220 }}
                  placeholder={k.adaylar.length ? `${k.adaylar.length} aday` : "Aday yok"}
                  value={secim[k.kalem_id] ?? undefined}
                  onChange={(v) => setSecim({ ...secim, [k.kalem_id]: v ?? null })}
                  options={k.adaylar.map((a) => ({
                    value: a.id,
                    label: `${a.serial_no ?? "seri yok"}${a.brand ? ` · ${a.brand}` : ""}${a.zone ? ` · ${a.zone}` : ""}${a.id === k.oneri_id ? " (öneri)" : ""}`,
                  }))}
                />
              );
            },
          },
          {
            title: "",
            width: 90,
            render: (_, k) =>
              k.equipment_id && yazabilir && !(k.kalem_id in secim) ? (
                <Button size="small" onClick={() => setSecim({ ...secim, [k.kalem_id]: null })}>
                  Değiştir
                </Button>
              ) : null,
          },
        ]}
      />
    </Space>
  );
}

// =============================================================================
// Dönemler
// =============================================================================

function donemKolonlari(onSec: (d: Donem) => void) {
  return [
    {
      title: "Sözleşme",
      render: (_: unknown, d: Donem) => (
        <>
          <span className="mono">{d.contract_no}</span>
          <br />
          <Typography.Text type="secondary">{d.musteri}</Typography.Text>
        </>
      ),
    },
    {
      title: "Dönem",
      render: (_: unknown, d: Donem) => `${dayjs(d.dongu_baslangici).year()} · ${d.sequence_no}/${d.frekans ?? "?"}`,
    },
    {
      title: "Hedef",
      render: (_: unknown, d: Donem) => (
        <>
          {tarih(d.target_date)} {d.target_manual && <Tag>elle</Tag>}
          {d.gecikmis && <Tag color="red">Gecikmiş</Tag>}
        </>
      ),
    },
    {
      title: "PB",
      render: (_: unknown, d: Donem) =>
        d.pb_toplam ? `${d.pb_tamamlanan} tamam / ${d.pb_acik} açık${d.pb_iptal ? ` / ${d.pb_iptal} iptal` : ""}` : "—",
    },
    {
      title: "Kapanış",
      render: (_: unknown, d: Donem) => (d.closing_kind ? KAPANIS[d.closing_kind] ?? d.closing_kind : "Açık"),
    },
    {
      title: "",
      width: 80,
      render: (_: unknown, d: Donem) => (
        <Button size="small" onClick={() => onSec(d)}>
          Cihazlar
        </Button>
      ),
    },
  ];
}

function DonemlerSekmesi({ onFormAc }: { onFormAc: (soId: number) => void }) {
  const [params, setParams] = useSearchParams();
  const [sayfa, setSayfa] = useState(1);
  const [secili, setSecili] = useState<Donem | null>(null);
  const gecikmis = params.get("gecikmis") === "1";
  const vadesiGelen = params.get("vadesi_gelen") === "1";
  const ay = params.get("ay") ?? undefined;
  const liste = useQuery({
    queryKey: ["bakim", "donemler", gecikmis, vadesiGelen, ay, sayfa],
    queryFn: () =>
      bakimApi.donemler({
        gecikmis,
        vadesi_gelen: vadesiGelen,
        ay,
        acik: !gecikmis && !vadesiGelen && !ay,
        limit: SAYFA,
        offset: (sayfa - 1) * SAYFA,
      }),
  });
  const ayarla = (ad: string, v: string | null) => {
    const yeni = new URLSearchParams(params);
    if (v) yeni.set(ad, v);
    else yeni.delete(ad);
    setParams(yeni);
    setSayfa(1);
  };
  return (
    <>
      <Space wrap style={{ marginBottom: 12 }}>
        <Switch
          checked={gecikmis}
          onChange={(v) => ayarla("gecikmis", v ? "1" : null)}
          checkedChildren="Gecikmiş"
          unCheckedChildren="Gecikmiş"
        />
        <Switch
          checked={vadesiGelen}
          onChange={(v) => ayarla("vadesi_gelen", v ? "1" : null)}
          checkedChildren="Vadesi gelen"
          unCheckedChildren="Vadesi gelen"
        />
        <DatePicker
          picker="month"
          format="MM.YYYY"
          placeholder="Hedef ayı"
          value={ay ? dayjs(`${ay}-01`) : null}
          onChange={(d) => ayarla("ay", d ? d.format("YYYY-MM") : null)}
        />
      </Space>
      <Table<Donem>
        rowKey="id"
        size="small"
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar}
        scroll={{ x: 760 }}
        columns={donemKolonlari(setSecili)}
        pagination={{
          current: sayfa,
          pageSize: SAYFA,
          total: liste.data?.toplam,
          onChange: setSayfa,
          showTotal: (t) => `${t} dönem`,
        }}
      />
      <DonemCekmecesi donem={secili} onKapat={() => setSecili(null)} onFormAc={onFormAc} />
    </>
  );
}

function SozlesmeDonemleri({ sozlesmeId }: { sozlesmeId: number }) {
  const [secili, setSecili] = useState<Donem | null>(null);
  const [formSo, setFormSo] = useState<number | null>(null);
  const liste = useQuery({
    queryKey: ["bakim", "sozlesme-donemleri", sozlesmeId],
    queryFn: () => bakimApi.sozlesmeDonemleri(sozlesmeId),
  });
  return (
    <>
      <Table<Donem>
        rowKey="id"
        size="small"
        loading={liste.isLoading}
        dataSource={liste.data}
        pagination={false}
        scroll={{ x: 760 }}
        columns={donemKolonlari(setSecili)}
      />
      <DonemCekmecesi donem={secili} onKapat={() => setSecili(null)} onFormAc={setFormSo} />
      <BakimFormu soId={formSo} onKapat={() => setFormSo(null)} />
    </>
  );
}

function DonemCekmecesi({
  donem,
  onKapat,
  onFormAc,
}: {
  donem: Donem | null;
  onKapat: () => void;
  onFormAc: (soId: number) => void;
}) {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [secilen, setSecilen] = useState<number[]>([]);
  const [planAcik, setPlanAcik] = useState(false);
  const [hedefAcik, setHedefAcik] = useState(false);
  const [hedefForm] = Form.useForm();
  const cihazlar = useQuery({
    queryKey: ["bakim", "donem-cihazlari", donem?.id],
    queryFn: () => bakimApi.donemCihazlari(donem!.contract_id, donem!.id),
    enabled: donem != null,
  });
  const yenile = () => qc.invalidateQueries({ queryKey: ["bakim"] });
  const eksik = useMutation({
    mutationFn: () => bakimApi.eksikPb(donem!.contract_id, donem!.id),
    onSuccess: (v) => {
      message.success(`${v.generated} eksik PB oluşturuldu`);
      v.skipped.forEach((a) => message.warning(`${a.contract_no}: ${a.neden}`));
      yenile();
    },
    onError: (e) => message.error(hataMetni(e)),
  });
  const hedef = useMutation({
    mutationFn: (v: { hedef_tarih: dayjs.Dayjs; gerekce: string }) =>
      bakimApi.hedefTarih(donem!.contract_id, donem!.id, v.hedef_tarih.format("YYYY-MM-DD"), v.gerekce),
    onSuccess: () => {
      message.success("Hedef tarih değişti");
      setHedefAcik(false);
      yenile();
    },
    onError: (e) => message.error(hataMetni(e)),
  });
  const veriler = cihazlar.data ?? [];
  const seciliAdres = veriler.find((c) => secilen.includes(c.so_id))?.address_id;

  return (
    <Drawer
      open={donem != null}
      size={760}
      onClose={() => {
        setSecilen([]);
        onKapat();
      }}
      title={donem ? `${donem.contract_no} · hedef ${tarih(donem.target_date)}` : "Dönem"}
      extra={
        donem &&
        yetkili("bakim.yaz") && (
          <Space wrap>
            <Button onClick={() => eksik.mutate()} loading={eksik.isPending}>
              Eksik PB'leri Oluştur
            </Button>
            <Button onClick={() => setHedefAcik(true)} disabled={donem.closed_at != null}>
              Hedef Tarihi Değiştir
            </Button>
          </Space>
        )
      }
    >
      {yetkili("servis.planla") && (
        <Space style={{ marginBottom: 12 }}>
          <Button type="primary" disabled={!secilen.length} onClick={() => setPlanAcik(true)}>
            Seçilenleri {TAYIN.planlaVeTayinEt} ({secilen.length})
          </Button>
        </Space>
      )}
      <Table<DonemCihazi>
        rowKey="so_id"
        size="small"
        loading={cihazlar.isLoading}
        dataSource={veriler}
        pagination={false}
        scroll={{ x: 640 }}
        rowSelection={
          yetkili("servis.planla")
            ? {
                selectedRowKeys: secilen,
                onChange: (k) => setSecilen(k as number[]),
                getCheckboxProps: (c) => ({
                  // Kapalı satır ve farklı lokasyon seçilemez (toplu plan tek ziyaret).
                  disabled: c.kapali || (seciliAdres !== undefined && c.address_id !== seciliAdres),
                }),
              }
            : undefined
        }
        columns={[
          { title: "PB No", dataIndex: "so_no", className: "mono" },
          {
            title: "Cihaz",
            render: (_, c) => `${CIHAZ_TURLERI[c.equipment_type] ?? c.equipment_type} #${c.sira}`,
          },
          { title: "Seri", dataIndex: "serial_no", className: "mono" },
          { title: "Bölge", dataIndex: "zone" },
          {
            title: "Durum",
            render: (_, c) => (
              <>
                <Tag>{c.status.replaceAll("_", " ")}</Tag>
                {c.kapsam_disi_talebi && <Tag color="orange">Kapsam dışı talebi</Tag>}
              </>
            ),
          },
          {
            title: "",
            render: (_, c) => (
              <Button size="small" onClick={() => onFormAc(c.so_id)}>
                {c.form_durumu === "TAMAMLANDI" ? "Formu Gör" : "Bakım Formu"}
              </Button>
            ),
          },
        ]}
      />
      {donem && (
        <PlanPenceresi
          acik={planAcik}
          mod="toplu"
          isIdler={secilen}
          birim={donem.birim}
          baslik={`${donem.contract_no} · ${secilen.length} PB`}
          onKapat={() => setPlanAcik(false)}
          onKaydedildi={() => {
            setPlanAcik(false);
            setSecilen([]);
            yenile();
          }}
        />
      )}
      <Modal
        title="Hedef tarihi değiştir"
        open={hedefAcik}
        onCancel={() => setHedefAcik(false)}
        onOk={() => hedefForm.submit()}
        confirmLoading={hedef.isPending}
        okText="Kaydet"
        cancelText="Vazgeç"
        destroyOnHidden
      >
        <Form form={hedefForm} layout="vertical" onFinish={hedef.mutate}>
          <Form.Item name="hedef_tarih" label="Yeni hedef" rules={[{ required: true }]}>
            <DatePicker format="DD.MM.YYYY" />
          </Form.Item>
          <Form.Item name="gerekce" label="Gerekçe" rules={[{ required: true }]}>
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
    </Drawer>
  );
}

// =============================================================================
// Uygunsuzluk ve kapsam dışı
// =============================================================================

function UygunsuzluklarSekmesi({ onFormAc }: { onFormAc: (soId: number) => void }) {
  const [params, setParams] = useSearchParams();
  const [sayfa, setSayfa] = useState(1);
  const durum = params.get("durum") ?? "ACIK";
  const liste = useQuery({
    queryKey: ["bakim", "uygunsuzluklar", durum, sayfa],
    queryFn: () => bakimApi.uygunsuzluklar({ durum, limit: SAYFA, offset: (sayfa - 1) * SAYFA }),
  });
  return (
    <>
      <Select
        style={{ width: 160, marginBottom: 12 }}
        value={durum}
        onChange={(v) => {
          const yeni = new URLSearchParams(params);
          yeni.set("durum", v);
          setParams(yeni);
          setSayfa(1);
        }}
        options={[
          { value: "ACIK", label: "Açık" },
          { value: "KAPALI", label: "Kapalı" },
        ]}
      />
      <Table<Uygunsuzluk>
        rowKey="id"
        size="small"
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar}
        scroll={{ x: 760 }}
        pagination={{
          current: sayfa,
          pageSize: SAYFA,
          total: liste.data?.toplam,
          onChange: setSayfa,
          showTotal: (t) => `${t} aksiyon`,
        }}
        columns={[
          { title: "PB", dataIndex: "so_no", className: "mono" },
          { title: "Madde", dataIndex: "check_label", ellipsis: true },
          { title: "Not", dataIndex: "description", ellipsis: true },
          { title: "Yaş (gün)", dataIndex: "yas_gun", width: 90 },
          { title: "Hedef", dataIndex: "due_date", render: (v) => tarih(v) },
          { title: "Arıza işi", dataIndex: "linked_so_no", className: "mono" },
          {
            title: "",
            render: (_, r) => (
              <Button size="small" onClick={() => r.so_id && onFormAc(r.so_id)}>
                Formu aç
              </Button>
            ),
          },
        ]}
      />
    </>
  );
}

function KapsamDisiSekmesi({ onFormAc }: { onFormAc: (soId: number) => void }) {
  const [params, setParams] = useSearchParams();
  const [sayfa, setSayfa] = useState(1);
  const durum = params.get("durum") ?? "TALEP";
  const liste = useQuery({
    queryKey: ["bakim", "kapsam-disi", durum, sayfa],
    queryFn: () => bakimApi.kapsamDisiTalepleri({ durum, limit: SAYFA, offset: (sayfa - 1) * SAYFA }),
  });
  return (
    <>
      <Select
        style={{ width: 160, marginBottom: 12 }}
        value={durum}
        onChange={(v) => {
          const yeni = new URLSearchParams(params);
          yeni.set("durum", v);
          setParams(yeni);
          setSayfa(1);
        }}
        options={[
          { value: "TALEP", label: "Karar bekleyen" },
          { value: "ONAYLANDI", label: "Onaylanan" },
          { value: "REDDEDILDI", label: "Reddedilen" },
        ]}
      />
      <Table<KapsamDisiTalebi>
        rowKey="id"
        size="small"
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar}
        scroll={{ x: 700 }}
        pagination={{
          current: sayfa,
          pageSize: SAYFA,
          total: liste.data?.toplam,
          onChange: setSayfa,
          showTotal: (t) => `${t} talep`,
        }}
        columns={[
          { title: "PB", dataIndex: "so_no", className: "mono" },
          { title: "Neden", dataIndex: "reason_code", render: (v: string) => KAPSAM_DISI_NEDENLERI[v] ?? v },
          { title: "Açıklama", dataIndex: "description", ellipsis: true },
          {
            title: "Talep eden",
            render: (_, t) => (
              <>
                {t.talep_eden} {t.kendi_talebi && <Tag>siz</Tag>}
              </>
            ),
          },
          { title: "Tarih", dataIndex: "created_at", render: (v) => tarih(v) },
          {
            title: "",
            render: (_, t) => (
              <Button size="small" onClick={() => t.so_id && onFormAc(t.so_id)}>
                Formu aç
              </Button>
            ),
          },
        ]}
      />
    </>
  );
}

// =============================================================================
// PB üretimi
// =============================================================================

function UretimSekmesi() {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [onizleme, setOnizleme] = useState<Onizleme | null>(null);
  const otomatik = useQuery({ queryKey: ["bakim", "otomatik-uretim"], queryFn: bakimApi.otomatikUretim });
  const kayitlar = useQuery({ queryKey: ["bakim", "uretim-kayitlari"], queryFn: () => bakimApi.uretimKayitlari() });
  const onizle = useMutation({
    mutationFn: bakimApi.onizle,
    onSuccess: setOnizleme,
    onError: (e) => message.error(hataMetni(e)),
  });
  const uret = useMutation({
    mutationFn: bakimApi.uret,
    onSuccess: (v) => {
      message.success(`${v.generated} PB üretildi`);
      setOnizleme(null);
      qc.invalidateQueries({ queryKey: ["bakim"] });
    },
    onError: (e) => message.error(hataMetni(e)),
  });
  const ayarla = useMutation({
    mutationFn: bakimApi.otomatikUretimAyarla,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bakim", "otomatik-uretim"] }),
    onError: (e) => message.error(hataMetni(e)),
  });
  const o = otomatik.data;
  return (
    <Space orientation="vertical" style={{ width: "100%" }} size={16}>
      <Card size="small" title="Otomatik PB üretimi (gece)">
        {o && (
          <Space wrap>
            <Switch
              checked={o.acik}
              disabled={!o.degistirebilir}
              loading={ayarla.isPending}
              onChange={(v) => ayarla.mutate(v)}
            />
            <Typography.Text>
              Eşleştirme %{o.oran.yuzde} ({o.oran.eslesen}/{o.oran.toplam})
            </Typography.Text>
            {o.oran.yuzde < 100 && (
              <Typography.Text type="warning">%100 olmadan otomatik üretim açılamaz.</Typography.Text>
            )}
          </Space>
        )}
      </Card>
      {yetkili("bakim.yaz") && (
        <Space wrap>
          <Button onClick={() => onizle.mutate()} loading={onizle.isPending}>
            Vadesi Gelenleri Önizle
          </Button>
          <Popconfirm title="Vadesi gelen PB işleri üretilsin mi?" onConfirm={() => uret.mutate()} okText="Üret" cancelText="Vazgeç">
            <Button type="primary" loading={uret.isPending}>
              Üret
            </Button>
          </Popconfirm>
        </Space>
      )}
      {onizleme && (
        <>
          <Table
            size="small"
            rowKey={(r) => `${r.contract_id}-${r.donem_id}`}
            pagination={false}
            dataSource={onizleme.uretilecek}
            scroll={{ x: 560 }}
            title={() => "Üretilecek"}
            columns={[
              { title: "Sözleşme", dataIndex: "contract_no", className: "mono" },
              { title: "Müşteri", dataIndex: "musteri" },
              { title: "Hedef", dataIndex: "hedef", render: (v) => tarih(v) },
              { title: "PB", dataIndex: "pb_sayisi" },
            ]}
          />
          {onizleme.atlanacak.length > 0 && (
            <Alert
              type="error"
              title={`${onizleme.atlanacak.length} sözleşme atlanacak`}
              description={
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {onizleme.atlanacak.map((a, i) => (
                    <li key={i}>
                      <span className="mono">{a.contract_no}</span> {a.musteri ? `· ${a.musteri}` : ""} — {a.neden}
                      {a.source_ref ? ` (${a.source_ref})` : ""}
                    </li>
                  ))}
                </ul>
              }
            />
          )}
        </>
      )}
      <Table<UretimKaydi>
        rowKey="id"
        size="small"
        title={() => "Üretim kayıtları"}
        loading={kayitlar.isLoading}
        dataSource={kayitlar.data?.kayitlar}
        pagination={false}
        scroll={{ x: 560 }}
        columns={[
          { title: "Tarih", dataIndex: "created_at", render: (v) => dayjs(v).format("DD.MM.YYYY HH:mm") },
          { title: "Tetik", dataIndex: "tetik" },
          { title: "Üretilen", dataIndex: "generated_count", render: (v) => v ?? "—" },
          {
            title: "Atlanan",
            render: (_, r) =>
              r.skipped.length ? (
                <Typography.Text type="danger">
                  {r.skipped.map((a) => `${a.contract_no}: ${a.neden_kodu}`).join(", ")}
                </Typography.Text>
              ) : (
                "—"
              ),
          },
        ]}
      />
    </Space>
  );
}
