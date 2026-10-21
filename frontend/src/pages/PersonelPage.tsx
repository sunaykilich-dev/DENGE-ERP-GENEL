/**
 * Personel — kart = kullanıcı kaydı (TS-002 / TS-008; E13-05/06).
 *
 * Liste sunucuda sayfalanır ve kapsamlıdır (birim şefi yalnız kendi biriminin
 * personelini görür). Üstteki kutular listenin süzgeçleridir: kutudaki sayı,
 * tıklanınca açılan listenin toplamıyla aynıdır (sunucu aynı sorguyu kullanır).
 *
 * Bu ekranda rol, izin, parola ve giriş YOK: girişsiz personel açılır, giriş
 * gerekirse Kullanıcılar ekranından ayrıca ve geçici parolayla açılır.
 * Yeniden aktifleştirme de girişi açmaz (E13-03).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";

import type { ApiError } from "../api/client";
import {
  BIRIM_ETIKETLERI,
  BIRIM_KODLARI,
  personelApi,
  SAHA_ROLU_ETIKETLERI,
  type Personel,
  type PersonelBirimi,
  type PersonelSuzgeci,
} from "../api/personel";
import { useAuth } from "../auth/AuthContext";
import Statistic from "../components/Statistic";

const SAYFA_BOYU = 25;

const birimSecenekleri = BIRIM_KODLARI.map((k) => ({ value: k, label: BIRIM_ETIKETLERI[k] }));
const sahaSecenekleri = [
  { value: "ATANABILIR", label: "Sahaya atanabilir (şef/teknisyen/stajyer)" },
  ...Object.entries(SAHA_ROLU_ETIKETLERI).map(([k, v]) => ({ value: k, label: v })),
  { value: "EKSIK", label: "Saha rolü girilmemiş" },
];

interface KartFormu {
  full_name: string;
  sicil_no?: string;
  unvan?: string;
  saha_rolu?: string;
  ise_giris_tarihi?: Dayjs | null;
  personel_notu?: string;
  birimler?: string[];
  birincil_birim?: string;
}

function birimSatirlari(birimler: string[] | undefined, birincil: string | undefined): PersonelBirimi[] {
  const liste = birimler ?? [];
  const asil = birincil && liste.includes(birincil) ? birincil : liste[0];
  return liste.map((b) => ({ birim: b, birincil: b === asil }));
}

function hataMesaji(e: ApiError): string {
  return e.cakisma ? `${e.message} Gerekirse sayfayı yenileyip tekrar deneyin.` : e.message;
}

export default function PersonelPage() {
  const { yetkili } = useAuth();
  const qc = useQueryClient();
  const { message, modal } = App.useApp();
  const yazabilir = yetkili("personel.yaz");

  const [suzgec, setSuzgec] = useState<PersonelSuzgeci>({ durum: "CALISIYOR" });
  const [sayfa, setSayfa] = useState(1);
  const [seciliId, setSeciliId] = useState<number | null>(null);
  const [yeniAcik, setYeniAcik] = useState(false);
  const [kartForm] = Form.useForm<KartFormu>();
  const [yeniForm] = Form.useForm<KartFormu>();

  const suzgecDegistir = (s: PersonelSuzgeci) => {
    setSuzgec(s);
    setSayfa(1);
  };

  const ozet = useQuery({ queryKey: ["personel-ozet"], queryFn: personelApi.ozet });
  const liste = useQuery({
    queryKey: ["personel", suzgec, sayfa],
    queryFn: () => personelApi.liste(suzgec, SAYFA_BOYU, (sayfa - 1) * SAYFA_BOYU),
  });
  const secili = useQuery({
    queryKey: ["personel-kart", seciliId],
    queryFn: () => personelApi.getir(seciliId!),
    enabled: seciliId != null,
  });

  const tazele = () => {
    void qc.invalidateQueries({ queryKey: ["personel"] });
    void qc.invalidateQueries({ queryKey: ["personel-ozet"] });
    void qc.invalidateQueries({ queryKey: ["personel-kart"] });
  };

  const olustur = useMutation({
    mutationFn: (v: KartFormu) =>
      personelApi.olustur({
        full_name: v.full_name,
        sicil_no: v.sicil_no || null,
        unvan: v.unvan || null,
        saha_rolu: v.saha_rolu || null,
        ise_giris_tarihi: v.ise_giris_tarihi ? v.ise_giris_tarihi.format("YYYY-MM-DD") : null,
        personel_notu: v.personel_notu || null,
        birimler: birimSatirlari(v.birimler, v.birincil_birim),
      }),
    onSuccess: (p) => {
      message.success("Personel açıldı (giriş hesabı kapalı)");
      setYeniAcik(false);
      yeniForm.resetFields();
      tazele();
      setSeciliId(p.id);
    },
    onError: (e: ApiError) => message.error(hataMesaji(e)),
  });

  const kartKaydet = useMutation({
    mutationFn: async (v: KartFormu) => {
      const p = secili.data!;
      await personelApi.guncelle(p.id, {
        full_name: v.full_name,
        sicil_no: v.sicil_no || null,
        unvan: v.unvan || null,
        saha_rolu: v.saha_rolu || null,
        ise_giris_tarihi: v.ise_giris_tarihi ? v.ise_giris_tarihi.format("YYYY-MM-DD") : null,
        personel_notu: v.personel_notu || null,
        version: p.version,
      });
      const yeniBirimler = birimSatirlari(v.birimler, v.birincil_birim);
      const eski = JSON.stringify([...p.birimler].sort((a, b) => a.birim.localeCompare(b.birim)));
      const yeni = JSON.stringify([...yeniBirimler].sort((a, b) => a.birim.localeCompare(b.birim)));
      if (eski !== yeni) await personelApi.birimleriYaz(p.id, yeniBirimler);
    },
    onSuccess: () => {
      message.success("Personel kartı kaydedildi");
      tazele();
    },
    onError: (e: ApiError) => message.error(hataMesaji(e)),
  });

  const aktiflestir = useMutation({
    mutationFn: (id: number) => personelApi.aktiflestir(id),
    onSuccess: (r) => {
      message.success(r.mesaj);
      tazele();
    },
    onError: (e: ApiError) => message.error(hataMesaji(e)),
  });

  const kartiAc = (p: Personel) => {
    setSeciliId(p.id);
    kartForm.resetFields();
  };

  const p = secili.data;
  const formDegerleri: KartFormu | undefined = p && {
    full_name: p.full_name,
    sicil_no: p.sicil_no ?? undefined,
    unvan: p.unvan ?? undefined,
    saha_rolu: p.saha_rolu ?? undefined,
    ise_giris_tarihi: p.ise_giris_tarihi ? dayjs(p.ise_giris_tarihi) : null,
    personel_notu: p.personel_notu ?? undefined,
    birimler: p.birimler.map((b) => b.birim),
    birincil_birim: p.birincil_birim ?? undefined,
  };

  const kartAlanlari = (form: typeof kartForm, yeni: boolean) => (
    <>
      <Form.Item name="full_name" label="Ad soyad" rules={[{ required: true, min: 2, max: 100 }]}>
        <Input />
      </Form.Item>
      <Row gutter={12}>
        <Col xs={24} sm={12}>
          <Form.Item name="sicil_no" label="Sicil no" rules={[{ max: 30 }]}>
            <Input className="mono" />
          </Form.Item>
        </Col>
        <Col xs={24} sm={12}>
          <Form.Item name="ise_giris_tarihi" label="İşe giriş">
            <DatePicker format="DD.MM.YYYY" style={{ width: "100%" }} />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={12}>
        <Col xs={24} sm={12}>
          <Form.Item name="unvan" label="Ünvan" rules={[{ max: 80 }]} extra="Yetkiye etkisi yok.">
            <Input />
          </Form.Item>
        </Col>
        <Col xs={24} sm={12}>
          <Form.Item
            name="saha_rolu"
            label="Saha rolü"
            extra="Atama listeleri buna bakar (şef/teknisyen/stajyer)."
          >
            <Select
              allowClear
              options={Object.entries(SAHA_ROLU_ETIKETLERI).map(([k, v]) => ({ value: k, label: v }))}
            />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={12}>
        <Col xs={24} sm={14}>
          <Form.Item name="birimler" label="Birimler">
            <Select mode="multiple" allowClear options={birimSecenekleri} />
          </Form.Item>
        </Col>
        <Col xs={24} sm={10}>
          <Form.Item noStyle shouldUpdate={(a, b) => a.birimler !== b.birimler}>
            {() => (
              <Form.Item name="birincil_birim" label="Birincil birim">
                <Select
                  allowClear
                  options={(form.getFieldValue("birimler") ?? []).map((b: string) => ({
                    value: b,
                    label: BIRIM_ETIKETLERI[b] ?? b,
                  }))}
                />
              </Form.Item>
            )}
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="personel_notu" label="Personel notu" extra="Kişisel veridir; yalnız İK görür.">
        <Input.TextArea rows={2} maxLength={2000} />
      </Form.Item>
      {yeni && (
        <Typography.Paragraph type="secondary">
          Personel <strong>giriş hesabı kapalı</strong> açılır. Giriş gerekirse Kullanıcılar
          ekranından ayrıca açılır.
        </Typography.Paragraph>
      )}
    </>
  );

  return (
    <Card
      title="Personel"
      extra={
        <Space wrap>
          {yetkili("servis_rapor.disaaktar") && (
            <Button onClick={() => window.open(personelApi.excelYolu(suzgec), "_blank")}>
              Excel
            </Button>
          )}
          {yazabilir && (
            <Button type="primary" onClick={() => setYeniAcik(true)}>
              Yeni personel
            </Button>
          )}
        </Space>
      }
    >
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        {(ozet.data ?? []).map((k) => (
          <Col key={k.kod} xs={12} sm={8} md={6} lg={3}>
            <Card
              size="small"
              hoverable
              onClick={() => suzgecDegistir(k.suzgec)}
              style={{ height: "100%" }}
            >
              <Statistic title={k.baslik} value={k.adet} />
            </Card>
          </Col>
        ))}
      </Row>

      <Space wrap style={{ marginBottom: 12 }}>
        <Input.Search
          placeholder="Ad, sicil, ünvan"
          allowClear
          style={{ width: 200 }}
          onSearch={(q) => suzgecDegistir({ ...suzgec, q: q || undefined })}
        />
        <Select
          placeholder="Birim"
          allowClear
          style={{ width: 170 }}
          value={suzgec.birimsiz ? "__YOK" : suzgec.birim}
          options={[...birimSecenekleri, { value: "__YOK", label: "Birimsiz" }]}
          onChange={(v?: string) =>
            suzgecDegistir({
              ...suzgec,
              birim: v && v !== "__YOK" ? v : undefined,
              birimsiz: v === "__YOK" || undefined,
            })
          }
        />
        <Select
          placeholder="Saha rolü"
          allowClear
          style={{ width: 200 }}
          value={suzgec.saha_rolu}
          options={sahaSecenekleri}
          onChange={(v?: string) => suzgecDegistir({ ...suzgec, saha_rolu: v })}
        />
        <Select
          placeholder="Durum"
          allowClear
          style={{ width: 130 }}
          value={suzgec.durum}
          options={[
            { value: "CALISIYOR", label: "Çalışıyor" },
            { value: "AYRILDI", label: "Ayrıldı" },
          ]}
          onChange={(v?: string) => suzgecDegistir({ ...suzgec, durum: v })}
        />
        <Select
          placeholder="Giriş"
          allowClear
          style={{ width: 130 }}
          value={suzgec.giris}
          options={[
            { value: "ACIK", label: "Giriş açık" },
            { value: "KAPALI", label: "Girişsiz" },
          ]}
          onChange={(v?: string) => suzgecDegistir({ ...suzgec, giris: v })}
        />
      </Space>

      <Table
        rowKey="id"
        size="small"
        scroll={{ x: 760 }}
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar ?? []}
        locale={{ emptyText: <Empty description="Bu süzgeçte personel yok" /> }}
        pagination={{
          current: sayfa,
          pageSize: SAYFA_BOYU,
          total: liste.data?.toplam ?? 0,
          showSizeChanger: false,
          onChange: setSayfa,
          showTotal: (t) => `${t.toLocaleString("tr-TR")} personel`,
        }}
        onRow={(r) => ({ onClick: () => kartiAc(r), style: { cursor: "pointer" } })}
        columns={[
          { title: "Ad soyad", dataIndex: "full_name", ellipsis: true },
          { title: "Sicil", dataIndex: "sicil_no", width: 100, className: "mono" },
          { title: "Ünvan", dataIndex: "unvan", ellipsis: true },
          {
            title: "Saha rolü",
            dataIndex: "saha_rolu",
            width: 110,
            render: (v: string | null) =>
              v ? SAHA_ROLU_ETIKETLERI[v] ?? v : <Tag color="gold">girilmemiş</Tag>,
          },
          {
            title: "Birimler",
            width: 220,
            render: (_, r: Personel) =>
              r.birimler.length ? (
                <Space size={4} wrap>
                  {r.birimler.map((b) => (
                    <Tag key={b.birim} color={b.birincil ? "blue" : undefined}>
                      {BIRIM_ETIKETLERI[b.birim] ?? b.birim}
                    </Tag>
                  ))}
                </Space>
              ) : (
                <Tag color="gold">birimsiz</Tag>
              ),
          },
          {
            title: "Durum",
            width: 150,
            render: (_, r: Personel) => (
              <Space size={4} wrap>
                {r.calisiyor ? <Tag color="green">çalışıyor</Tag> : <Tag>ayrıldı</Tag>}
                {!r.giris_acik && <Tag>giriş yok</Tag>}
              </Space>
            ),
          },
        ]}
      />

      <Drawer
        title={p ? p.full_name : ""}
        open={seciliId != null}
        size={680}
        onClose={() => setSeciliId(null)}
        destroyOnHidden
      >
        {p && (
          <Space orientation="vertical" style={{ width: "100%" }} size="middle">
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="Durum">
                {p.calisiyor ? (
                  <Tag color="green">çalışıyor</Tag>
                ) : (
                  <Tag>ayrıldı {p.ayrilis_tarihi && dayjs(p.ayrilis_tarihi).format("DD.MM.YYYY")}</Tag>
                )}
                {p.giris_acik ? <Tag color="blue">giriş açık</Tag> : <Tag>giriş yok</Tag>}
              </Descriptions.Item>
              <Descriptions.Item label="Rol">{p.rol.name}</Descriptions.Item>
              {p.username !== undefined && (
                <Descriptions.Item label="Kullanıcı adı">
                  <span className="mono">{p.username}</span>
                </Descriptions.Item>
              )}
              {p.email !== undefined && (
                <Descriptions.Item label="E-posta">{p.email ?? "—"}</Descriptions.Item>
              )}
              {p.ayrilis_nedeni !== undefined && p.ayrilis_nedeni && (
                <Descriptions.Item label="Ayrılış nedeni">
                  {p.ayrilis_nedeni.replaceAll("_", " ")}
                </Descriptions.Item>
              )}
            </Descriptions>

            {yazabilir && !p.calisiyor && (
              <Button
                loading={aktiflestir.isPending}
                onClick={() =>
                  modal.confirm({
                    title: "Personel yeniden aktifleştirilsin mi?",
                    content: "Giriş hesabı AÇILMAZ; gerekirse Kullanıcılar ekranından ayrıca açılır.",
                    okText: "Aktifleştir",
                    cancelText: "Vazgeç",
                    onOk: () => aktiflestir.mutateAsync(p.id),
                  })
                }
              >
                Yeniden aktifleştir
              </Button>
            )}

            {yazabilir ? (
              <Form
                form={kartForm}
                layout="vertical"
                initialValues={formDegerleri}
                key={`${p.id}-${p.version}-${p.birimler.map((b) => b.birim).join()}`}
                onFinish={(v) => kartKaydet.mutate(v)}
              >
                {kartAlanlari(kartForm, false)}
                <Button type="primary" htmlType="submit" loading={kartKaydet.isPending}>
                  Kaydet
                </Button>
              </Form>
            ) : (
              <Descriptions size="small" column={1} bordered>
                <Descriptions.Item label="Sicil no">{p.sicil_no ?? "—"}</Descriptions.Item>
                <Descriptions.Item label="Ünvan">{p.unvan ?? "—"}</Descriptions.Item>
                <Descriptions.Item label="Saha rolü">
                  {p.saha_rolu ? SAHA_ROLU_ETIKETLERI[p.saha_rolu] ?? p.saha_rolu : "girilmemiş"}
                </Descriptions.Item>
                <Descriptions.Item label="Birimler">
                  {p.birimler.length
                    ? p.birimler
                        .map((b) => `${BIRIM_ETIKETLERI[b.birim] ?? b.birim}${b.birincil ? " (birincil)" : ""}`)
                        .join(", ")
                    : "birimsiz"}
                </Descriptions.Item>
                <Descriptions.Item label="İşe giriş">
                  {p.ise_giris_tarihi ? dayjs(p.ise_giris_tarihi).format("DD.MM.YYYY") : "—"}
                </Descriptions.Item>
              </Descriptions>
            )}
          </Space>
        )}
      </Drawer>

      <Modal
        title="Yeni personel (girişsiz)"
        open={yeniAcik}
        onCancel={() => setYeniAcik(false)}
        onOk={() => yeniForm.submit()}
        okText="Kaydet"
        cancelText="Vazgeç"
        confirmLoading={olustur.isPending}
        destroyOnHidden
      >
        <Form form={yeniForm} layout="vertical" onFinish={(v) => olustur.mutate(v)}>
          {kartAlanlari(yeniForm, true)}
        </Form>
      </Modal>
    </Card>
  );
}
