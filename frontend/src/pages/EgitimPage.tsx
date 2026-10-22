/**
 * Eğitim ve Gelişim (TS-150…160).
 *
 * Sekmeler eski sistemle aynı sırada (E-18): Yönetim Özeti · Yıllık Plan ·
 * Eğitim Kataloğu · Katılım ve Sınav · Saha Gözlemi · 30/60/90 Takip ·
 * Düzeltici Faaliyetler · Yetkinlik Matrisi · Belgeler · Bireysel Gelişim.
 * Sekme ve KPI süzgeci URL'dedir (`?sekme=plan&kpi=plan_geciken`): KPI kutusu
 * tıklanınca liste AYNI süzgeçle açılır, kutudaki sayı listenin toplamıdır.
 * `/egitim/:id` kişi kartını açar. Butonlar `yetkili()` ile gizlenir; sunucu
 * her uçta ayrıca kontrol eder.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Card,
  Checkbox,
  Col,
  DatePicker,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
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
import type { ColumnsType } from "antd/es/table";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import type { ApiError } from "../api/client";
import {
  asamaEtiketi,
  egitimApi,
  KATEGORI_ETIKETLERI,
  PLAN_DURUM_ETIKETLERI,
  PLAN_DURUM_RENKLERI,
  SONUC_ETIKETLERI,
  type Faaliyet,
  type Gozlem,
  type Kurs,
  type Oturum,
  type Plan,
  type Yetkinlik,
} from "../api/egitim";
import { BIRIM_ETIKETLERI, BIRIM_KODLARI } from "../api/personel";
import { useAuth } from "../auth/AuthContext";
import GozlemFormu, { SonucRozeti } from "../components/GozlemFormu";
import KatilimTablosu from "../components/KatilimTablosu";
import KpiKutusu from "../components/KpiKutusu";
import { KisiKartiGorunumu } from "./EgitimKisiKarti";
import { EslemeSekmesi, EtkinlikSekmesi, YenidenDegerlendirSekmesi } from "./EgitimRaporlari";

const SAYFA = 25;
const tarih = (t: string | null | undefined) => (t ? dayjs(t).format("DD.MM.YYYY") : "—");
const birimSecenekleri = BIRIM_KODLARI.map((k) => ({ value: k, label: BIRIM_ETIKETLERI[k] }));
const yilSecenekleri = Array.from({ length: 6 }, (_, i) => dayjs().year() + 1 - i).map((y) => ({
  value: y,
  label: String(y),
}));
const hata = (e: ApiError) => (e.cakisma ? `${e.message} Sayfayı yenileyip tekrar deneyin.` : e.message);

function useSorguParam() {
  const [params, setParams] = useSearchParams();
  const al = (k: string) => params.get(k) ?? undefined;
  const sayi = (k: string) => (params.get(k) ? Number(params.get(k)) : undefined);
  return { params, setParams, al, sayi };
}

function gerekceSor(
  modal: ReturnType<typeof App.useApp>["modal"],
  baslik: string,
  islem: (gerekce: string) => Promise<unknown>,
) {
  let deger = "";
  modal.confirm({
    title: baslik,
    content: <Input.TextArea rows={3} maxLength={500} onChange={(e) => (deger = e.target.value)} placeholder="Gerekçe (zorunlu)" />,
    okText: "Kaydet",
    onOk: () => islem(deger),
  });
}

// --- Yönetim özeti (TS-153) -----------------------------------------------------------------

function OzetSekmesi() {
  const { sayi, al, params, setParams } = useSorguParam();
  const yil = sayi("yil") ?? dayjs().year();
  const birim = al("birim");
  const ozet = useQuery({ queryKey: ["egitim-ozet", yil, birim], queryFn: () => egitimApi.ozet(yil, birim) });
  const ayarla = (k: string, v?: string | number) => {
    const p = new URLSearchParams(params);
    if (v === undefined || v === "") p.delete(k);
    else p.set(k, String(v));
    setParams(p);
  };
  const g = ozet.data?.gerceklesme;
  const gz = ozet.data?.gozlem;
  return (
    <Space orientation="vertical" style={{ width: "100%" }} size="middle">
      <Space wrap>
        <Select style={{ width: 110 }} value={yil} options={yilSecenekleri} onChange={(v) => ayarla("yil", v)} />
        <Select
          allowClear
          placeholder="Tüm birimler"
          style={{ width: 200 }}
          value={birim}
          options={birimSecenekleri}
          onChange={(v) => ayarla("birim", v)}
        />
      </Space>
      <Row gutter={[12, 12]}>
        {(ozet.data?.kutular ?? []).map((k) => (
          <Col key={k.kod} xs={12} sm={8} lg={6} xl={4}>
            <KpiKutusu kod={k.kod} baslik={k.baslik} tanim={k.tanim} deger={k.deger} yol={k.yol} vurgu={k.vurgu} />
          </Col>
        ))}
      </Row>
      <Row gutter={[12, 12]}>
        <Col xs={24} md={12}>
          <Card size="small" title={`${yil} yıllık gerçekleşme`} loading={ozet.isLoading}>
            {g && g.toplam ? (
              <Space orientation="vertical" style={{ width: "100%" }}>
                <Progress percent={g.yuzde ?? 0} />
                <Typography.Text>
                  Toplam {g.toplam} · Zamanında {g.zamaninda} · Geç {g.gec} · Açık {g.acik}
                </Typography.Text>
              </Space>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Bu yıl plan yok" />
            )}
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card size="small" title="Saha gözlemi başarı oranı" loading={ozet.isLoading}>
            {gz && gz.toplam ? (
              <Space orientation="vertical" style={{ width: "100%" }}>
                <Progress percent={gz.basari_orani ?? 0} status="normal" />
                <Typography.Text>
                  {gz.basarili} / {gz.toplam} gözlem başarılı · Ortalama puan %{gz.ortalama_puan ?? "—"}
                </Typography.Text>
              </Space>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Gözlem yok" />
            )}
          </Card>
        </Col>
      </Row>
      {(ozet.data?.birim_ilerleme.length ?? 0) > 0 && (
        <Card size="small" title="Birim bazlı ilerleme">
          {ozet.data!.birim_ilerleme.map((b) => (
            <div key={b.birim}>
              <Typography.Text>{BIRIM_ETIKETLERI[b.birim] ?? b.birim}</Typography.Text>
              <Progress percent={Math.round((100 * b.tamamlanan) / b.toplam)} format={() => `${b.tamamlanan}/${b.toplam}`} />
            </div>
          ))}
        </Card>
      )}
    </Space>
  );
}

// --- Yıllık plan (TS-150/152) ---------------------------------------------------------------

function TopluPlanPenceresi({ acik, kapat }: { acik: boolean; kapat: () => void }) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [form] = Form.useForm();
  const [secili, setSecili] = useState<number[]>([]);
  const [birim, setBirim] = useState<string | undefined>();
  const kurslar = useQuery({ queryKey: ["egitim-kurslar", "aktif"], queryFn: () => egitimApi.kurslar({ aktif: true }), enabled: acik });
  const kisiler = useQuery({
    queryKey: ["egitim-kisiler", "toplu", birim],
    queryFn: () => egitimApi.kisiler({ birim }, 200, 0),
    enabled: acik,
  });
  const kaydet = useMutation({
    mutationFn: (v: { course_id: number; plan_yili: number; hedef_tarih?: Dayjs; gelisim_hedefi?: string }) =>
      egitimApi.topluPlan({
        course_id: v.course_id,
        plan_yili: v.plan_yili,
        hedef_tarih: v.hedef_tarih ? v.hedef_tarih.format("YYYY-MM-DD") : null,
        gelisim_hedefi: v.gelisim_hedefi || null,
        user_ids: secili,
      }),
    onSuccess: (r) => {
      message.success(`${r.olusan} plan açıldı${r.atlanan ? `, ${r.atlanan} kişi zaten planlıydı` : ""}`);
      void qc.invalidateQueries({ queryKey: ["egitim-planlar"] });
      void qc.invalidateQueries({ queryKey: ["egitim-ozet"] });
      setSecili([]);
      kapat();
    },
    onError: (e: ApiError) => message.error(hata(e)),
  });
  const tumu = (kisiler.data?.kayitlar ?? []).map((k) => k.id);
  return (
    <Modal
      open={acik}
      title="Toplu yıllık plan"
      onCancel={kapat}
      onOk={() => form.submit()}
      okButtonProps={{ disabled: !secili.length, loading: kaydet.isPending }}
      width={640}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{ plan_yili: dayjs().year(), hedef_tarih: dayjs(`${dayjs().year()}-12-15`) }}
        onFinish={(v) => kaydet.mutate(v)}
        onValuesChange={(c) => {
          if (c.plan_yili) form.setFieldValue("hedef_tarih", dayjs(`${c.plan_yili}-12-15`));
        }}
      >
        <Form.Item name="course_id" label="Eğitim" rules={[{ required: true, message: "Eğitim seçin" }]}>
          <Select options={(kurslar.data ?? []).map((k) => ({ value: k.id, label: `${k.kod} — ${k.baslik}` }))} />
        </Form.Item>
        <Space wrap>
          <Form.Item name="plan_yili" label="Yıl" rules={[{ required: true }]}>
            <Select style={{ width: 110 }} options={yilSecenekleri} />
          </Form.Item>
          <Form.Item name="hedef_tarih" label="Hedef tarih">
            <DatePicker format="DD.MM.YYYY" />
          </Form.Item>
        </Space>
        <Form.Item name="gelisim_hedefi" label="Gelişim hedefi">
          <Input.TextArea rows={2} maxLength={2000} />
        </Form.Item>
        <Space wrap style={{ marginBottom: 8 }}>
          <Select allowClear placeholder="Birim" style={{ width: 180 }} options={birimSecenekleri} onChange={setBirim} />
          <Button size="small" onClick={() => setSecili(tumu)}>
            Tümünü seç
          </Button>
          <Button size="small" onClick={() => setSecili([])}>
            Temizle
          </Button>
          <Typography.Text type="secondary">{secili.length} kişi seçili</Typography.Text>
        </Space>
        <Checkbox.Group
          value={secili}
          onChange={(v) => setSecili(v as number[])}
          style={{ maxHeight: 260, overflow: "auto", display: "flex", flexDirection: "column" }}
          options={(kisiler.data?.kayitlar ?? []).map((k) => ({ value: k.id, label: k.ad }))}
        />
      </Form>
    </Modal>
  );
}

function PlanSekmesi() {
  const { yetkili } = useAuth();
  const { message, modal } = App.useApp();
  const qc = useQueryClient();
  const git = useNavigate();
  const { al, sayi } = useSorguParam();
  const [suzgec, setSuzgec] = useState({
    yil: sayi("yil") ?? dayjs().year(),
    durum: undefined as string | undefined,
    q: "",
    kpi: al("kpi"),
    vade: al("vade") === "1",
  });
  const [sayfa, setSayfa] = useState(1);
  const [topluAcik, setTopluAcik] = useState(false);
  const [ertelenen, setErtelenen] = useState<Plan | null>(null);
  const [ertelemeForm] = Form.useForm();
  const yazabilir = yetkili("egitim.yaz");
  const p = { yil: suzgec.yil, durum: suzgec.durum, q: suzgec.q, kpi: suzgec.kpi, vade: suzgec.vade };
  const liste = useQuery({
    queryKey: ["egitim-planlar", p, sayfa],
    queryFn: () => egitimApi.planlar(p, SAYFA, (sayfa - 1) * SAYFA),
  });
  const tazele = () => {
    void qc.invalidateQueries({ queryKey: ["egitim-planlar"] });
    void qc.invalidateQueries({ queryKey: ["egitim-ozet"] });
  };
  const ertele = useMutation({
    mutationFn: (v: { yeni_tarih: Dayjs; gerekce: string }) =>
      egitimApi.planErtele(ertelenen!, v.yeni_tarih.format("YYYY-MM-DD"), v.gerekce),
    onSuccess: () => {
      message.success("Plan ertelendi");
      setErtelenen(null);
      tazele();
    },
    onError: (e: ApiError) => message.error(hata(e)),
  });
  const kolonlar: ColumnsType<Plan> = [
    { title: "Personel", dataIndex: "ad", render: (ad: string, r) => <a onClick={() => git(`/egitim/${r.user_id}`)}>{ad}</a> },
    { title: "Eğitim", dataIndex: "kurs" },
    { title: "Yıl", dataIndex: "plan_yili", width: 70, responsive: ["sm"] },
    {
      title: "Hedef",
      dataIndex: "hedef_tarih",
      render: (t: string, r) => <Typography.Text type={r.geciken ? "danger" : undefined}>{tarih(t)}</Typography.Text>,
    },
    {
      title: "Durum",
      dataIndex: "status",
      render: (s: string, r) => (
        <Space size={4}>
          <Tag color={PLAN_DURUM_RENKLERI[s]}>{PLAN_DURUM_ETIKETLERI[s] ?? s}</Tag>
          {r.gec && <Tag color="orange">Geç</Tag>}
        </Space>
      ),
    },
    { title: "Tamamlanma", dataIndex: "completed_on", render: tarih, responsive: ["md"] },
    ...(yazabilir
      ? [
          {
            title: "",
            key: "islem",
            render: (_: unknown, r: Plan) =>
              ["PLANLANDI", "ERTELENDI", "BASARISIZ_TEKRAR"].includes(r.status) && (
                <Space size={4}>
                  <Button size="small" onClick={() => setErtelenen(r)}>
                    Ertele
                  </Button>
                  <Button
                    size="small"
                    danger
                    onClick={() =>
                      gerekceSor(modal, "Planı iptal et", (g) =>
                        egitimApi.planIptal(r, g).then(tazele, (e: ApiError) => {
                          message.error(hata(e));
                          throw e;
                        }),
                      )
                    }
                  >
                    İptal
                  </Button>
                </Space>
              ),
          },
        ]
      : []),
  ];
  const excel = yetkili("egitim.gor", "servis_rapor.disaaktar");
  return (
    <Card
      size="small"
      title={suzgec.kpi ? `Yıllık plan — KPI: ${suzgec.kpi}` : suzgec.vade ? "Hedefi yaklaşan/geçen planlar" : "Yıllık plan"}
      extra={
        <Space wrap>
          {(suzgec.kpi || suzgec.vade) && (
            <Button size="small" onClick={() => setSuzgec((s) => ({ ...s, kpi: undefined, vade: false }))}>
              Süzgeci kaldır
            </Button>
          )}
          {excel && (
            <Button size="small" href={egitimApi.planExcelYolu({ yil: suzgec.yil, durum: suzgec.durum, q: suzgec.q, kpi: suzgec.kpi })}>
              Excel
            </Button>
          )}
          {yazabilir && (
            <Button size="small" type="primary" onClick={() => setTopluAcik(true)}>
              Toplu plan
            </Button>
          )}
        </Space>
      }
    >
      <Space wrap style={{ marginBottom: 12 }}>
        <Select style={{ width: 100 }} value={suzgec.yil} options={yilSecenekleri} onChange={(v) => { setSuzgec((s) => ({ ...s, yil: v })); setSayfa(1); }} />
        <Select
          allowClear
          placeholder="Durum"
          style={{ width: 160 }}
          value={suzgec.durum}
          options={Object.entries(PLAN_DURUM_ETIKETLERI).map(([k, v]) => ({ value: k, label: v }))}
          onChange={(v) => { setSuzgec((s) => ({ ...s, durum: v })); setSayfa(1); }}
        />
        <Input.Search allowClear placeholder="Personel / eğitim" onSearch={(q) => { setSuzgec((s) => ({ ...s, q })); setSayfa(1); }} style={{ width: 220 }} />
      </Space>
      <Table<Plan>
        size="small"
        rowKey="id"
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar}
        columns={kolonlar}
        scroll={{ x: 640 }}
        pagination={{
          current: sayfa,
          pageSize: SAYFA,
          total: liste.data?.toplam,
          onChange: setSayfa,
          showTotal: (t) => `${t} plan`,
        }}
      />
      <TopluPlanPenceresi acik={topluAcik} kapat={() => setTopluAcik(false)} />
      <Modal
        open={!!ertelenen}
        title={`Ertele — ${ertelenen?.ad ?? ""}`}
        onCancel={() => setErtelenen(null)}
        onOk={() => ertelemeForm.submit()}
        confirmLoading={ertele.isPending}
        destroyOnHidden
      >
        <Form form={ertelemeForm} layout="vertical" onFinish={(v) => ertele.mutate(v)}>
          <Form.Item name="yeni_tarih" label="Yeni hedef tarih" rules={[{ required: true }]}>
            <DatePicker format="DD.MM.YYYY" />
          </Form.Item>
          <Form.Item name="gerekce" label="Gerekçe" rules={[{ required: true, whitespace: true, message: "Gerekçe zorunlu" }]}>
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}

// --- Katalog (TS-150/152) ---------------------------------------------------------------------

function Kriterler({ kurs, yazabilir }: { kurs: Kurs; yazabilir: boolean }) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [metin, setMetin] = useState("");
  const [kritik, setKritik] = useState(false);
  const liste = useQuery({ queryKey: ["egitim-kriterler", kurs.id], queryFn: () => egitimApi.kriterler(kurs.id) });
  const tazele = () => void qc.invalidateQueries({ queryKey: ["egitim-kriterler", kurs.id] });
  const ekle = useMutation({
    mutationFn: () => egitimApi.kriterEkle({ kurs_id: kurs.id, metin, is_critical: kritik }),
    onSuccess: () => {
      setMetin("");
      setKritik(false);
      tazele();
    },
    onError: (e: ApiError) => message.error(hata(e)),
  });
  const guncelle = useMutation({
    mutationFn: (g: { id: number; version: number; is_active: boolean }) => egitimApi.kriterGuncelle(g),
    onSuccess: tazele,
    onError: (e: ApiError) => message.error(hata(e)),
  });
  return (
    <Space orientation="vertical" style={{ width: "100%" }}>
      <List
        size="small"
        dataSource={liste.data ?? []}
        locale={{ emptyText: "Gözlem maddesi yok" }}
        renderItem={(m) => (
          <List.Item
            actions={
              yazabilir
                ? [
                    <Switch
                      key="aktif"
                      size="small"
                      checked={m.is_active}
                      checkedChildren="Aktif"
                      unCheckedChildren="Pasif"
                      onChange={(v) => guncelle.mutate({ id: m.id, version: m.version, is_active: v })}
                    />,
                  ]
                : []
            }
          >
            <Space wrap size={4}>
              <Typography.Text type={m.is_active ? undefined : "secondary"}>
                {m.sira}. {m.metin}
              </Typography.Text>
              {m.is_critical && <Tag color="red">Kritik</Tag>}
            </Space>
          </List.Item>
        )}
      />
      {yazabilir && (
        <Space.Compact style={{ width: "100%" }}>
          <Input placeholder="Yeni gözlem maddesi" maxLength={300} value={metin} onChange={(e) => setMetin(e.target.value)} />
          <Checkbox checked={kritik} onChange={(e) => setKritik(e.target.checked)} style={{ padding: "4px 8px" }}>
            Kritik
          </Checkbox>
          <Button disabled={!metin.trim()} onClick={() => ekle.mutate()} loading={ekle.isPending}>
            Ekle
          </Button>
        </Space.Compact>
      )}
    </Space>
  );
}

function KatalogSekmesi() {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const yazabilir = yetkili("egitim.yaz");
  const [duzenlenen, setDuzenlenen] = useState<Kurs | "yeni" | null>(null);
  const [form] = Form.useForm();
  const liste = useQuery({ queryKey: ["egitim-kurslar", "tum"], queryFn: () => egitimApi.kurslar() });
  const kaydet = useMutation({
    mutationFn: (v: Partial<Kurs>) =>
      duzenlenen === "yeni"
        ? egitimApi.kursOlustur(v)
        : egitimApi.kursGuncelle({ ...v, id: (duzenlenen as Kurs).id, version: (duzenlenen as Kurs).version }),
    onSuccess: () => {
      message.success("Eğitim kaydedildi");
      setDuzenlenen(null);
      void qc.invalidateQueries({ queryKey: ["egitim-kurslar"] });
    },
    onError: (e: ApiError) => message.error(hata(e)),
  });
  return (
    <Card
      size="small"
      title="Eğitim kataloğu"
      extra={
        yazabilir && (
          <Button size="small" type="primary" onClick={() => { form.resetFields(); setDuzenlenen("yeni"); }}>
            Yeni eğitim
          </Button>
        )
      }
    >
      <Table<Kurs>
        size="small"
        rowKey="id"
        loading={liste.isLoading}
        dataSource={liste.data}
        pagination={false}
        scroll={{ x: 600 }}
        expandable={{ expandedRowRender: (k) => <Kriterler kurs={k} yazabilir={yazabilir} /> }}
        columns={[
          { title: "Kod", dataIndex: "kod", width: 110 },
          { title: "Eğitim", dataIndex: "baslik" },
          { title: "Kategori", dataIndex: "kategori", render: (k: string) => KATEGORI_ETIKETLERI[k] ?? k, responsive: ["sm"] },
          { title: "Birim", dataIndex: "birim", render: (b: string | null) => (b ? BIRIM_ETIKETLERI[b] : "Tümü"), responsive: ["md"] },
          { title: "Yenileme", dataIndex: "yenileme_ay", render: (a: number | null) => (a ? `${a} ay` : "—"), responsive: ["md"] },
          { title: "Durum", dataIndex: "is_active", render: (a: boolean) => (a ? <Tag color="green">Aktif</Tag> : <Tag>Pasif</Tag>) },
          ...(yazabilir
            ? [
                {
                  title: "",
                  key: "d",
                  render: (_: unknown, k: Kurs) => (
                    <Button size="small" onClick={() => { form.setFieldsValue({ ...k, sure_saat: Number(k.sure_saat), gozlem_esik_yuzde: k.gozlem_esik_yuzde ? Number(k.gozlem_esik_yuzde) : null }); setDuzenlenen(k); }}>
                      Düzenle
                    </Button>
                  ),
                },
              ]
            : []),
        ]}
      />
      <Modal
        open={duzenlenen !== null}
        title={duzenlenen === "yeni" ? "Yeni eğitim" : "Eğitimi düzenle"}
        onCancel={() => setDuzenlenen(null)}
        onOk={() => form.submit()}
        confirmLoading={kaydet.isPending}
        width={640}
      >
        <Form form={form} layout="vertical" initialValues={{ kategori: "TEKNIK", sure_saat: 2 }} onFinish={(v) => kaydet.mutate({ ...v, birim: v.birim ?? null })}>
          <Space wrap>
            <Form.Item name="kod" label="Kod" rules={[{ required: true }]}>
              <Input maxLength={30} style={{ width: 140 }} />
            </Form.Item>
            <Form.Item name="kategori" label="Kategori" rules={[{ required: true }]}>
              <Select style={{ width: 160 }} options={Object.entries(KATEGORI_ETIKETLERI).map(([k, v]) => ({ value: k, label: v }))} />
            </Form.Item>
            <Form.Item name="birim" label="Birim">
              <Select allowClear placeholder="Tüm birimler" style={{ width: 180 }} options={birimSecenekleri} />
            </Form.Item>
          </Space>
          <Form.Item name="baslik" label="Eğitim adı" rules={[{ required: true }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Space wrap>
            <Form.Item name="sure_saat" label="Süre (saat)" rules={[{ required: true }]}>
              <InputNumber min={0.5} max={24} step={0.5} />
            </Form.Item>
            <Form.Item name="gozlem_esik_yuzde" label="Gözlem başarı eşiği %">
              <InputNumber min={0} max={100} placeholder="85" />
            </Form.Item>
            <Form.Item name="yenileme_ay" label="Yenileme (ay)">
              <InputNumber min={1} max={120} />
            </Form.Item>
            <Form.Item name="sinav_gecme_puani" label="Sınav geçme puanı">
              <InputNumber min={0} max={100} />
            </Form.Item>
          </Space>
          <Space wrap>
            <Form.Item name="zorunlu" label="Zorunlu" valuePropName="checked">
              <Switch />
            </Form.Item>
            {duzenlenen !== "yeni" && (
              <Form.Item name="is_active" label="Aktif" valuePropName="checked">
                <Switch />
              </Form.Item>
            )}
          </Space>
          <Form.Item name="hedef_davranis" label="Hedef davranış">
            <Input.TextArea rows={2} maxLength={4000} />
          </Form.Item>
          <Form.Item name="basari_olcutu" label="Başarı ölçütü">
            <Input.TextArea rows={2} maxLength={4000} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}

// --- Katılım ve sınav (TS-150/158) ---------------------------------------------------------------

function KatilimSekmesi() {
  const { yetkili } = useAuth();
  const { message, modal } = App.useApp();
  const qc = useQueryClient();
  const yazabilir = yetkili("egitim.yaz");
  const [yil, setYil] = useState(dayjs().year());
  const [sayfa, setSayfa] = useState(1);
  const [secili, setSecili] = useState<Oturum | null>(null);
  const [yeniAcik, setYeniAcik] = useState(false);
  const [form] = Form.useForm();
  const liste = useQuery({
    queryKey: ["egitim-oturumlar", yil, sayfa],
    queryFn: () => egitimApi.oturumlar({ yil }, SAYFA, (sayfa - 1) * SAYFA),
  });
  const kurslar = useQuery({ queryKey: ["egitim-kurslar", "aktif"], queryFn: () => egitimApi.kurslar({ aktif: true }), enabled: yeniAcik });
  const olustur = useMutation({
    mutationFn: (v: { course_id: number; oturum_tarihi: Dayjs; egitmen_ad?: string; yer?: string }) =>
      egitimApi.oturumOlustur({ ...v, oturum_tarihi: v.oturum_tarihi.format("YYYY-MM-DD") }),
    onSuccess: (o) => {
      message.success("Oturum açıldı");
      setYeniAcik(false);
      setSecili(o);
      void qc.invalidateQueries({ queryKey: ["egitim-oturumlar"] });
    },
    onError: (e: ApiError) => message.error(hata(e)),
  });
  return (
    <Space orientation="vertical" style={{ width: "100%" }}>
      <Card
        size="small"
        title="Oturumlar"
        extra={
          <Space>
            <Select style={{ width: 100 }} value={yil} options={yilSecenekleri} onChange={(v) => { setYil(v); setSayfa(1); }} />
            {yazabilir && (
              <Button size="small" type="primary" onClick={() => { form.resetFields(); setYeniAcik(true); }}>
                Yeni oturum
              </Button>
            )}
          </Space>
        }
      >
        <Table<Oturum>
          size="small"
          rowKey="id"
          loading={liste.isLoading}
          dataSource={liste.data?.kayitlar}
          onRow={(o) => ({ onClick: () => setSecili(o), style: { cursor: "pointer" } })}
          rowClassName={(o) => (o.id === secili?.id ? "ant-table-row-selected" : "")}
          pagination={{ current: sayfa, pageSize: SAYFA, total: liste.data?.toplam, onChange: setSayfa }}
          columns={[
            { title: "Tarih", dataIndex: "oturum_tarihi", render: tarih },
            { title: "Eğitim", dataIndex: "kurs" },
            { title: "Eğitmen", dataIndex: "egitmen_ad", responsive: ["sm"] },
            { title: "Katılımcı", dataIndex: "katilimci", width: 90 },
            ...(yazabilir
              ? [
                  {
                    title: "",
                    key: "sil",
                    render: (_: unknown, o: Oturum) =>
                      o.katilimci === 0 && (
                        <Button
                          size="small"
                          danger
                          onClick={(e) => {
                            e.stopPropagation();
                            modal.confirm({
                              title: "Oturum silinsin mi?",
                              onOk: () =>
                                egitimApi.oturumSil(o).then(
                                  () => void qc.invalidateQueries({ queryKey: ["egitim-oturumlar"] }),
                                  (er: ApiError) => message.error(hata(er)),
                                ),
                            });
                          }}
                        >
                          Sil
                        </Button>
                      ),
                  },
                ]
              : []),
          ]}
        />
      </Card>
      {secili && (
        <Card size="small" title={`Katılım — ${secili.kurs ?? ""} ${tarih(secili.oturum_tarihi)}`}>
          <KatilimTablosu key={secili.id} oturum={secili} yazabilir={yazabilir} />
        </Card>
      )}
      <Modal open={yeniAcik} title="Yeni oturum" onCancel={() => setYeniAcik(false)} onOk={() => form.submit()} confirmLoading={olustur.isPending}>
        <Form form={form} layout="vertical" initialValues={{ oturum_tarihi: dayjs() }} onFinish={(v) => olustur.mutate(v)}>
          <Form.Item name="course_id" label="Eğitim" rules={[{ required: true }]}>
            <Select options={(kurslar.data ?? []).map((k) => ({ value: k.id, label: `${k.kod} — ${k.baslik}` }))} />
          </Form.Item>
          <Form.Item name="oturum_tarihi" label="Tarih" rules={[{ required: true }]}>
            <DatePicker format="DD.MM.YYYY" disabledDate={(d) => d.isAfter(dayjs(), "day")} />
          </Form.Item>
          <Form.Item name="egitmen_ad" label="Eğitmen">
            <Input maxLength={120} />
          </Form.Item>
          <Form.Item name="yer" label="Yer">
            <Input maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  );
}

// --- Saha gözlemi (TS-151/152/156) -----------------------------------------------------------------

function GozlemSekmesi() {
  const { yetkili, kullanici } = useAuth();
  const { message, modal } = App.useApp();
  const qc = useQueryClient();
  const git = useNavigate();
  const { al, sayi } = useSorguParam();
  const [suzgec, setSuzgec] = useState({
    yil: sayi("yil") ?? dayjs().year(),
    sonuc: undefined as string | undefined,
    asama: undefined as number | undefined,
    kpi: al("kpi"),
  });
  const [sayfa, setSayfa] = useState(1);
  const [formAcik, setFormAcik] = useState(false);
  const liste = useQuery({
    queryKey: ["egitim-gozlemler", suzgec, sayfa],
    queryFn: () => egitimApi.gozlemler(suzgec, SAYFA, (sayfa - 1) * SAYFA),
  });
  const iptalEdebilir = (g: Gozlem) =>
    !g.cancelled_at && (yetkili("egitim.yaz") || (yetkili("egitim.gozlem") && g.observer_user_id === kullanici?.id));
  return (
    <Card
      size="small"
      title={suzgec.kpi ? `Saha gözlemleri — KPI: ${suzgec.kpi}` : "Saha gözlemleri"}
      extra={
        <Space wrap>
          {suzgec.kpi && (
            <Button size="small" onClick={() => setSuzgec((s) => ({ ...s, kpi: undefined }))}>
              Süzgeci kaldır
            </Button>
          )}
          {yetkili("egitim.gozlem") && (
            <Button size="small" type="primary" onClick={() => setFormAcik(true)}>
              Yeni gözlem
            </Button>
          )}
        </Space>
      }
    >
      <Space wrap style={{ marginBottom: 12 }}>
        <Select style={{ width: 100 }} value={suzgec.yil} options={yilSecenekleri} onChange={(v) => { setSuzgec((s) => ({ ...s, yil: v })); setSayfa(1); }} />
        <Select allowClear placeholder="Sonuç" style={{ width: 160 }} value={suzgec.sonuc}
          options={Object.entries(SONUC_ETIKETLERI).map(([k, v]) => ({ value: k, label: v }))}
          onChange={(v) => { setSuzgec((s) => ({ ...s, sonuc: v })); setSayfa(1); }} />
        <Select allowClear placeholder="Aşama" style={{ width: 130 }} value={suzgec.asama}
          options={[0, 30, 60, 90].map((a) => ({ value: a, label: asamaEtiketi(a) }))}
          onChange={(v) => { setSuzgec((s) => ({ ...s, asama: v })); setSayfa(1); }} />
      </Space>
      <Table<Gozlem>
        size="small"
        rowKey="id"
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar}
        scroll={{ x: 640 }}
        pagination={{ current: sayfa, pageSize: SAYFA, total: liste.data?.toplam, onChange: setSayfa, showTotal: (t) => `${t} gözlem` }}
        columns={[
          { title: "Tarih", dataIndex: "gozlem_tarihi", render: tarih },
          { title: "Personel", dataIndex: "ad", render: (ad: string, g) => <a onClick={() => git(`/egitim/${g.user_id}`)}>{ad}</a> },
          { title: "Eğitim", dataIndex: "kurs", responsive: ["sm"] },
          { title: "Aşama", dataIndex: "asama", render: asamaEtiketi, responsive: ["md"] },
          { title: "Sonuç", key: "sonuc", render: (_, g) => <SonucRozeti g={g} /> },
          { title: "Gözlemci", dataIndex: "gozlemci_ad", responsive: ["md"] },
          { title: "Gördü", dataIndex: "gordu_at", render: (t: string | null) => (t ? tarih(t) : "—"), responsive: ["lg"] },
          {
            title: "",
            key: "iptal",
            render: (_, g) =>
              iptalEdebilir(g) && (
                <Button size="small" danger onClick={() =>
                  gerekceSor(modal, "Gözlemi iptal et", (r) =>
                    egitimApi.gozlemIptal(g, r).then(
                      () => { void qc.invalidateQueries({ queryKey: ["egitim-gozlemler"] }); void qc.invalidateQueries({ queryKey: ["egitim-ozet"] }); },
                      (e: ApiError) => { message.error(hata(e)); throw e; },
                    ),
                  )}>
                  İptal
                </Button>
              ),
          },
        ]}
      />
      <GozlemFormu open={formAcik} onClose={() => setFormAcik(false)} />
    </Card>
  );
}

function TakipSekmesi() {
  const git = useNavigate();
  const { al } = useSorguParam();
  const [durum, setDurum] = useState<string | undefined>(al("vadesi_gelen") ? "VADESI_GELEN" : undefined);
  const kpi = al("kpi");
  const [sayfa, setSayfa] = useState(1);
  const p = kpi ? { kpi } : durum === "VADESI_GELEN" ? { vadesi_gelen: true } : { durum };
  const liste = useQuery({ queryKey: ["egitim-takipler", p, sayfa], queryFn: () => egitimApi.takipler(p, SAYFA, (sayfa - 1) * SAYFA) });
  const renk: Record<string, string> = { GECIKTI: "red", ZAMANI_GELDI: "orange", YAKLASAN: "blue" };
  const ad: Record<string, string> = { GECIKTI: "Gecikti", ZAMANI_GELDI: "Bugün", YAKLASAN: "Yaklaşıyor" };
  return (
    <Card
      size="small"
      title="30/60/90 gün takibi"
      extra={
        <Select allowClear placeholder="Tümü" style={{ width: 180 }} value={durum} onChange={(v) => { setDurum(v); setSayfa(1); }}
          options={[{ value: "VADESI_GELEN", label: "Vadesi gelenler" }, ...Object.entries(ad).map(([k, v]) => ({ value: k, label: v }))]} />
      }
    >
      <Table
        size="small"
        rowKey={(t) => `${t.plan_id}-${t.asama}`}
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar}
        pagination={{ current: sayfa, pageSize: SAYFA, total: liste.data?.toplam, onChange: setSayfa }}
        columns={[
          { title: "Personel", dataIndex: "ad", render: (a: string, t) => <a onClick={() => git(`/egitim/${t.user_id}`)}>{a}</a> },
          { title: "Eğitim", dataIndex: "kurs" },
          { title: "Aşama", dataIndex: "asama", render: asamaEtiketi },
          { title: "Tamamlandı", dataIndex: "completed_on", render: tarih, responsive: ["md"] },
          { title: "Vade", dataIndex: "vade", render: tarih },
          { title: "Durum", dataIndex: "durum", render: (d: string) => <Tag color={renk[d]}>{ad[d] ?? d}</Tag> },
        ]}
      />
    </Card>
  );
}

function FaaliyetSekmesi() {
  const { yetkili } = useAuth();
  const { message, modal } = App.useApp();
  const qc = useQueryClient();
  const { al } = useSorguParam();
  const [durum, setDurum] = useState<string | undefined>("ACIK");
  const [kpi, setKpi] = useState(al("kpi"));
  const [sayfa, setSayfa] = useState(1);
  const p = kpi ? { kpi } : { durum };
  const liste = useQuery({ queryKey: ["egitim-faaliyetler", p, sayfa], queryFn: () => egitimApi.faaliyetler(p, SAYFA, (sayfa - 1) * SAYFA) });
  const kapat = (f: Faaliyet) => {
    let kanit = "";
    modal.confirm({
      title: "Düzeltici faaliyeti kapat",
      content: <Input.TextArea rows={3} placeholder="Kanıt / açıklama (zorunlu)" onChange={(e) => (kanit = e.target.value)} />,
      onOk: () =>
        egitimApi.faaliyetKapat(f, kanit).then(
          () => { message.success("Kapatıldı"); void qc.invalidateQueries({ queryKey: ["egitim-faaliyetler"] }); },
          (e: ApiError) => { message.error(hata(e)); throw e; },
        ),
    });
  };
  return (
    <Card
      size="small"
      title="Düzeltici faaliyetler (kritik İSG)"
      extra={
        <Space>
          {kpi && <Button size="small" onClick={() => setKpi(undefined)}>Süzgeci kaldır</Button>}
          <Select allowClear placeholder="Tümü" style={{ width: 140 }} value={durum} onChange={(v) => { setDurum(v); setSayfa(1); }}
            options={[{ value: "ACIK", label: "Açık" }, { value: "KAPATILDI", label: "Kapatıldı" }]} />
        </Space>
      }
    >
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        Faaliyet, kritik maddeleri "Uygun" alan sonraki gözlemle kendiliğinden kapanır; elle kapanış eğitim yöneticisinin
        (egitim.yaz) kanıtıyla yapılır. Gözlemi iptal edilen faaliyet açık kalır.
      </Typography.Paragraph>
      <Table<Faaliyet>
        size="small"
        rowKey="id"
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar}
        pagination={{ current: sayfa, pageSize: SAYFA, total: liste.data?.toplam, onChange: setSayfa }}
        columns={[
          { title: "Personel", dataIndex: "ad" },
          { title: "Eğitim", dataIndex: "kurs", responsive: ["sm"] },
          { title: "Gözlem", dataIndex: "gozlem_tarihi", render: (t: string, f) => <Space size={4}>{tarih(t)}{f.gozlem_iptal && <Tag>İptal edildi</Tag>}</Space> },
          { title: "Termin", dataIndex: "termin", render: (t: string, f) => <Typography.Text type={f.gecikmis ? "danger" : undefined}>{tarih(t)}</Typography.Text> },
          { title: "Durum", dataIndex: "status", render: (s: string, f) => (s === "ACIK" ? <Tag color={f.gecikmis ? "red" : "orange"}>Açık</Tag> : <Tag color="green">{f.kapanis_turu === "OTOMATIK_GOZLEM" ? "Gözlemle kapandı" : "Kapatıldı"}</Tag>) },
          ...(yetkili("egitim.yaz")
            ? [{ title: "", key: "k", render: (_: unknown, f: Faaliyet) => f.status === "ACIK" && <Button size="small" onClick={() => kapat(f)}>Kapat</Button> }]
            : []),
        ]}
      />
    </Card>
  );
}

// --- Yetkinlik (TS-150/160) ----------------------------------------------------------------------

function YetkinlikSekmesi() {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const { al } = useSorguParam();
  const [kpi, setKpi] = useState(al("kpi"));
  const [hedefAlti, setHedefAlti] = useState(false);
  const [sayfa, setSayfa] = useState(1);
  const [duzenlenen, setDuzenlenen] = useState<Yetkinlik | "yeni" | null>(null);
  const [degAcik, setDegAcik] = useState(false);
  const [arama, setArama] = useState("");
  const [form] = Form.useForm();
  const [degForm] = Form.useForm();
  const katalog = useQuery({ queryKey: ["egitim-yetkinlikler"], queryFn: () => egitimApi.yetkinlikler() });
  const p = kpi ? { kpi } : { hedef_alti: hedefAlti };
  const matris = useQuery({ queryKey: ["egitim-matris", p, sayfa], queryFn: () => egitimApi.matris(p, 50, (sayfa - 1) * 50) });
  const kisiler = useQuery({ queryKey: ["egitim-kisiler", "deg", arama], queryFn: () => egitimApi.kisiler({ q: arama }, 30, 0), enabled: degAcik });
  const kaydet = useMutation({
    mutationFn: (v: Partial<Yetkinlik>) =>
      duzenlenen === "yeni"
        ? egitimApi.yetkinlikOlustur(v)
        : egitimApi.yetkinlikGuncelle({ ...v, id: (duzenlenen as Yetkinlik).id, version: (duzenlenen as Yetkinlik).version }),
    onSuccess: () => { setDuzenlenen(null); void qc.invalidateQueries({ queryKey: ["egitim-yetkinlikler"] }); },
    onError: (e: ApiError) => message.error(hata(e)),
  });
  const degerlendir = useMutation({
    mutationFn: (v: { user_id: number; competency_id: number; mevcut_seviye: number; hedef_seviye?: number; kanit?: string }) =>
      egitimApi.degerlendir(v),
    onSuccess: (r) => {
      message.success("Değerlendirme kaydedildi");
      r.uyarilar.forEach((u) => message.warning(u));
      setDegAcik(false);
      void qc.invalidateQueries({ queryKey: ["egitim-matris"] });
    },
    onError: (e: ApiError) => message.error(hata(e)),
  });
  return (
    <Space orientation="vertical" style={{ width: "100%" }}>
      <Card
        size="small"
        title="Yetkinlik matrisi (güncel seviye)"
        extra={
          <Space wrap>
            {kpi ? <Button size="small" onClick={() => setKpi(undefined)}>Süzgeci kaldır</Button> : (
              <Checkbox checked={hedefAlti} onChange={(e) => { setHedefAlti(e.target.checked); setSayfa(1); }}>Hedefin altındakiler</Checkbox>
            )}
            {yetkili("egitim.gozlem") && <Button size="small" type="primary" onClick={() => { degForm.resetFields(); setDegAcik(true); }}>Değerlendir</Button>}
          </Space>
        }
      >
        <Table
          size="small"
          rowKey="id"
          loading={matris.isLoading}
          dataSource={matris.data?.kayitlar}
          pagination={{ current: sayfa, pageSize: 50, total: matris.data?.toplam, onChange: setSayfa }}
          columns={[
            { title: "Personel", dataIndex: "ad" },
            { title: "Yetkinlik", dataIndex: "yetkinlik", render: (y: string, r) => <Space size={4}>{y}{r.kritik && <Tag color="red">Kritik</Tag>}</Space> },
            { title: "Seviye", key: "s", render: (_, r) => <Typography.Text type={r.hedef_alti ? "danger" : undefined}>{r.mevcut_seviye} / hedef {r.hedef_seviye}</Typography.Text> },
            { title: "Tarih", dataIndex: "degerlendirme_tarihi", render: tarih, responsive: ["sm"] },
          ]}
        />
      </Card>
      <Card
        size="small"
        title="Yetkinlik kataloğu"
        extra={yetkili("egitim.yaz") && <Button size="small" onClick={() => { form.resetFields(); setDuzenlenen("yeni"); }}>Yeni yetkinlik</Button>}
      >
        <Table<Yetkinlik>
          size="small"
          rowKey="id"
          dataSource={katalog.data}
          pagination={false}
          columns={[
            { title: "Kod", dataIndex: "kod", width: 100 },
            { title: "Ad", dataIndex: "ad" },
            { title: "Birim", dataIndex: "birim", render: (b: string | null) => (b ? BIRIM_ETIKETLERI[b] : "Tümü"), responsive: ["sm"] },
            { title: "Önerilen hedef", dataIndex: "onerilen_hedef", responsive: ["md"] },
            { title: "Durum", key: "d", render: (_, y) => <Space size={4}>{y.is_critical && <Tag color="red">Kritik</Tag>}{y.is_active ? <Tag color="green">Aktif</Tag> : <Tag>Pasif</Tag>}</Space> },
            ...(yetkili("egitim.yaz") ? [{ title: "", key: "e", render: (_: unknown, y: Yetkinlik) => <Button size="small" onClick={() => { form.setFieldsValue(y); setDuzenlenen(y); }}>Düzenle</Button> }] : []),
          ]}
        />
      </Card>
      <Modal open={duzenlenen !== null} title="Yetkinlik" onCancel={() => setDuzenlenen(null)} onOk={() => form.submit()} confirmLoading={kaydet.isPending}>
        <Form form={form} layout="vertical" initialValues={{ onerilen_hedef: 3 }} onFinish={(v) => kaydet.mutate({ ...v, birim: v.birim ?? null })}>
          <Form.Item name="kod" label="Kod" rules={[{ required: true }]}><Input maxLength={20} /></Form.Item>
          <Form.Item name="ad" label="Ad" rules={[{ required: true }]}><Input maxLength={150} /></Form.Item>
          <Form.Item name="birim" label="Birim"><Select allowClear placeholder="Tüm birimler" options={birimSecenekleri} /></Form.Item>
          <Space wrap>
            <Form.Item name="onerilen_hedef" label="Önerilen hedef"><InputNumber min={1} max={4} /></Form.Item>
            <Form.Item name="is_critical" label="Kritik" valuePropName="checked"><Switch /></Form.Item>
            {duzenlenen !== "yeni" && <Form.Item name="is_active" label="Aktif" valuePropName="checked"><Switch /></Form.Item>}
          </Space>
        </Form>
      </Modal>
      <Modal open={degAcik} title="Yetkinlik değerlendirmesi" onCancel={() => setDegAcik(false)} onOk={() => degForm.submit()} confirmLoading={degerlendir.isPending}>
        <Form form={degForm} layout="vertical" onFinish={(v) => degerlendir.mutate(v)}>
          <Form.Item name="user_id" label="Personel" rules={[{ required: true }]}>
            <Select showSearch filterOption={false} onSearch={setArama} options={(kisiler.data?.kayitlar ?? []).map((k) => ({ value: k.id, label: k.ad }))} />
          </Form.Item>
          <Form.Item name="competency_id" label="Yetkinlik" rules={[{ required: true }]}>
            <Select options={(katalog.data ?? []).filter((y) => y.is_active).map((y) => ({ value: y.id, label: `${y.kod} — ${y.ad}${y.is_critical ? " (kritik)" : ""}` }))} />
          </Form.Item>
          <Space wrap>
            <Form.Item name="mevcut_seviye" label="Mevcut seviye (1–4)" rules={[{ required: true }]}><InputNumber min={1} max={4} /></Form.Item>
            <Form.Item name="hedef_seviye" label="Hedef seviye"><InputNumber min={1} max={4} /></Form.Item>
          </Space>
          <Form.Item name="kanit" label="Kanıt / açıklama (kritik yetkinlikte zorunlu)"><Input.TextArea rows={2} maxLength={4000} /></Form.Item>
        </Form>
      </Modal>
    </Space>
  );
}

// --- Belgeler / geçerlilik (TS-159) -----------------------------------------------------------------

function BelgeSekmesi() {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const { al } = useSorguParam();
  const [durum, setDurum] = useState<string | undefined>();
  const [kpi, setKpi] = useState(al("kpi"));
  const [sayfa, setSayfa] = useState(1);
  const [acik, setAcik] = useState(false);
  const [arama, setArama] = useState("");
  const [form] = Form.useForm();
  const p = kpi ? { kpi } : { durum };
  const liste = useQuery({ queryKey: ["egitim-belgeler", p, sayfa], queryFn: () => egitimApi.belgeler(p, SAYFA, (sayfa - 1) * SAYFA) });
  const kisiler = useQuery({ queryKey: ["egitim-kisiler", "belge", arama], queryFn: () => egitimApi.kisiler({ q: arama }, 30, 0), enabled: acik });
  const ekle = useMutation({
    mutationFn: (v: { user_id: number; belge_adi: string; verilis_tarihi: Dayjs; gecerlilik_bitis?: Dayjs; belge_no?: string }) =>
      egitimApi.belgeOlustur({
        ...v,
        verilis_tarihi: v.verilis_tarihi.format("YYYY-MM-DD"),
        gecerlilik_bitis: v.gecerlilik_bitis ? v.gecerlilik_bitis.format("YYYY-MM-DD") : null,
      }),
    onSuccess: () => { message.success("Belge kaydedildi"); setAcik(false); void qc.invalidateQueries({ queryKey: ["egitim-belgeler"] }); },
    onError: (e: ApiError) => message.error(hata(e)),
  });
  return (
    <Card
      size="small"
      title="Eğitim ve belge geçerliliği"
      extra={
        <Space wrap>
          {kpi && <Button size="small" onClick={() => setKpi(undefined)}>Süzgeci kaldır</Button>}
          <Select allowClear placeholder="Tümü" style={{ width: 150 }} value={durum} onChange={(v) => { setDurum(v); setSayfa(1); }}
            options={[{ value: "DOLDU", label: "Süresi dolan" }, { value: "DOLACAK", label: "Süresi dolacak" }, { value: "GECERLI", label: "Geçerli" }]} />
          {yetkili("egitim.yaz") && <Button size="small" type="primary" onClick={() => { form.resetFields(); setAcik(true); }}>Belge ekle</Button>}
        </Space>
      }
    >
      <Table
        size="small"
        rowKey={(r) => `${r.kaynak}-${r.kayit_id}`}
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar}
        pagination={{ current: sayfa, pageSize: SAYFA, total: liste.data?.toplam, onChange: setSayfa }}
        columns={[
          { title: "Personel", dataIndex: "kisi" },
          { title: "Eğitim / belge", dataIndex: "ad", render: (a: string, r) => <Space size={4}>{a}<Tag>{r.kaynak === "PLAN" ? "Eğitim" : "Belge"}</Tag></Space> },
          { title: "Başlangıç", dataIndex: "baslangic", render: tarih, responsive: ["md"] },
          { title: "Bitiş", dataIndex: "bitis", render: tarih },
          { title: "Durum", dataIndex: "durum", render: (d: string) => <Tag color={d === "DOLDU" ? "red" : d === "DOLACAK" ? "orange" : "green"}>{d === "DOLDU" ? "Doldu" : d === "DOLACAK" ? "Doluyor" : "Geçerli"}</Tag> },
        ]}
      />
      <Modal open={acik} title="Belge / sertifika ekle" onCancel={() => setAcik(false)} onOk={() => form.submit()} confirmLoading={ekle.isPending}>
        <Form form={form} layout="vertical" onFinish={(v) => ekle.mutate(v)}>
          <Form.Item name="user_id" label="Personel" rules={[{ required: true }]}>
            <Select showSearch filterOption={false} onSearch={setArama} options={(kisiler.data?.kayitlar ?? []).map((k) => ({ value: k.id, label: k.ad }))} />
          </Form.Item>
          <Form.Item name="belge_adi" label="Belge adı" rules={[{ required: true }]}><Input maxLength={200} /></Form.Item>
          <Space wrap>
            <Form.Item name="verilis_tarihi" label="Veriliş" rules={[{ required: true }]}><DatePicker format="DD.MM.YYYY" /></Form.Item>
            <Form.Item name="gecerlilik_bitis" label="Geçerlilik bitişi"><DatePicker format="DD.MM.YYYY" /></Form.Item>
          </Space>
          <Form.Item name="belge_no" label="Belge no"><Input maxLength={60} /></Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}

// --- Bireysel gelişim (kişi listesi) ------------------------------------------------------------------

function KisilerSekmesi() {
  const git = useNavigate();
  const [q, setQ] = useState("");
  const [birim, setBirim] = useState<string | undefined>();
  const [sayfa, setSayfa] = useState(1);
  const liste = useQuery({
    queryKey: ["egitim-kisiler", "liste", q, birim, sayfa],
    queryFn: () => egitimApi.kisiler({ q, birim }, SAYFA, (sayfa - 1) * SAYFA),
  });
  return (
    <Card
      size="small"
      title="Bireysel gelişim"
      extra={
        <Space wrap>
          <Select allowClear placeholder="Birim" style={{ width: 170 }} options={birimSecenekleri} onChange={(v) => { setBirim(v); setSayfa(1); }} />
          <Input.Search allowClear placeholder="Ad / sicil" onSearch={(v) => { setQ(v); setSayfa(1); }} style={{ width: 200 }} />
        </Space>
      }
    >
      <Table
        size="small"
        rowKey="id"
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar}
        onRow={(k) => ({ onClick: () => git(`/egitim/${k.id}`), style: { cursor: "pointer" } })}
        pagination={{ current: sayfa, pageSize: SAYFA, total: liste.data?.toplam, onChange: setSayfa }}
        columns={[
          { title: "Personel", dataIndex: "ad" },
          { title: "Ünvan", dataIndex: "unvan", responsive: ["sm"] },
          { title: "Birim", dataIndex: "birimler", render: (b: string[]) => b.map((x) => BIRIM_ETIKETLERI[x] ?? x).join(", ") || "Birimsiz" },
        ]}
      />
    </Card>
  );
}

function KisiKartiSayfasi({ kisiId }: { kisiId: number }) {
  const git = useNavigate();
  const kart = useQuery({ queryKey: ["egitim-kart", kisiId], queryFn: () => egitimApi.kart(kisiId) });
  return (
    <Card
      title={kart.data ? `Eğitim kartı — ${kart.data.kisi.ad}` : "Eğitim kartı"}
      extra={<Button onClick={() => git("/egitim?sekme=kisiler")}>Listeye dön</Button>}
      loading={kart.isLoading}
    >
      {kart.error && <Empty description={(kart.error as Error).message} />}
      {kart.data && <KisiKartiGorunumu kart={kart.data} />}
    </Card>
  );
}

const SEKMELER = [
  { key: "ozet", label: "Yönetim Özeti", el: <OzetSekmesi /> },
  { key: "plan", label: "Yıllık Plan", el: <PlanSekmesi /> },
  { key: "katalog", label: "Eğitim Kataloğu", el: <KatalogSekmesi /> },
  { key: "katilim", label: "Katılım ve Sınav", el: <KatilimSekmesi /> },
  { key: "gozlem", label: "Saha Gözlemi", el: <GozlemSekmesi /> },
  { key: "takip", label: "30/60/90 Takip", el: <TakipSekmesi /> },
  { key: "faaliyet", label: "Düzeltici Faaliyetler", el: <FaaliyetSekmesi /> },
  { key: "yetkinlik", label: "Yetkinlik Matrisi", el: <YetkinlikSekmesi /> },
  { key: "belge", label: "Belgeler", el: <BelgeSekmesi /> },
  { key: "kisiler", label: "Bireysel Gelişim", el: <KisilerSekmesi /> },
  // TS-198: etkinlik raporu, yeniden değerlendir listesi, yetkinlik eşlemeleri.
  { key: "etkinlik", label: "Etkinlik Raporu", el: <EtkinlikSekmesi /> },
  { key: "yeniden", label: "Yeniden Değerlendir", el: <YenidenDegerlendirSekmesi /> },
  { key: "esleme", label: "Yetkinlik Eşlemeleri", el: <EslemeSekmesi /> },
];

export default function EgitimPage() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  if (id && /^\d+$/.test(id)) return <KisiKartiSayfasi kisiId={Number(id)} />;
  const sekme = params.get("sekme") ?? "ozet";
  return (
    <Card title="Eğitim ve Gelişim" styles={{ body: { paddingTop: 0 } }}>
      <Tabs
        activeKey={sekme}
        destroyOnHidden
        onChange={(k) => setParams({ sekme: k })}
        items={SEKMELER.map((s) => ({ key: s.key, label: s.label, children: <div key={params.toString()}>{s.el}</div> }))}
      />
    </Card>
  );
}
