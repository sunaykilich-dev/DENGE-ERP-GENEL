import { BellOutlined, InboxOutlined, SendOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  DatePicker,
  Drawer,
  Form,
  Input,
  Modal,
  Progress,
  Radio,
  Segmented,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import type { UploadFile } from "antd/es/upload/interface";
import dayjs, { type Dayjs } from "dayjs";
import { useMemo, useState } from "react";

import type { ApiError } from "../api/client";
import {
  type Alici,
  type BelgeSatiri,
  type BelgeTuru,
  DURUM_ETIKETLERI,
  type Eslesme,
  type GonderimOzet,
  type Kanit,
  SABLON_TURLERI,
  type Sablon,
  TUR_ETIKETLERI,
  ikBelgeApi,
} from "../api/ikBelgeler";
import { useAuth } from "../auth/AuthContext";

/**
 * Bordro ve Belgeler (İK, KARARLAR 2026-10-28 §11) — Kolaysoft PEYK benzeri.
 *
 * Sekmeler: Takip (kim gördü/onayladı/itiraz etti/bekliyor, hatırlatma),
 * Bordro gönder (toplu PDF, dosya adından kişi eşleştirme), Belge gönder
 * (form/talimat/taahhütname: şablondan ya da PDF'ten, çok kişiye), Şablonlar.
 * Bordro sekmeleri `bordro.yonet`, diğerleri `ik_belge.yonet` ister; sunucu
 * aynı kuralı ayrıca uygular.
 */
export default function IkBelgelerPage() {
  const { yetkili } = useAuth();
  const bordro = yetkili("bordro.yonet");
  const belge = yetkili("ik_belge.yonet");
  const [sekme, setSekme] = useState("takip");
  const items = [
    { key: "takip", label: "Takip", children: <TakipSekmesi /> },
    ...(bordro
      ? [{ key: "bordro", label: "Bordro gönder", children: <BordroSekmesi bitti={() => setSekme("takip")} /> }]
      : []),
    ...(belge
      ? [
          { key: "belge", label: "Belge gönder", children: <BelgeSekmesi bitti={() => setSekme("takip")} /> },
          { key: "sablon", label: "Şablonlar", children: <SablonSekmesi /> },
        ]
      : []),
  ];
  return (
    <Card title="Bordro ve Belgeler">
      <Tabs activeKey={sekme} onChange={setSekme} items={items} destroyOnHidden />
    </Card>
  );
}

const tarih = (s: string | null) => (s ? dayjs(s).format("DD.MM.YYYY HH:mm") : "—");

// --- Takip --------------------------------------------------------------------------------

function TakipSekmesi() {
  const [tur, setTur] = useState<BelgeTuru | "TUMU">("TUMU");
  const [secili, setSecili] = useState<number | null>(null);
  const liste = useQuery({
    queryKey: ["ik-gonderimler", tur],
    queryFn: () => ikBelgeApi.gonderimler(tur === "TUMU" ? undefined : tur),
  });
  const kolonlar: ColumnsType<GonderimOzet> = [
    { title: "Tür", dataIndex: "tur", width: 110, render: (t: BelgeTuru) => <Tag>{TUR_ETIKETLERI[t]}</Tag> },
    { title: "Başlık", dataIndex: "baslik" },
    { title: "Dönem", dataIndex: "donem", width: 90, render: (d) => d ?? "—" },
    { title: "Gönderim", dataIndex: "created_at", width: 140, render: tarih },
    {
      title: "Onaylayan",
      width: 180,
      render: (_, g) => (
        <Progress
          size="small"
          percent={g.toplam ? Math.round(((g.sayilar.ONAYLANDI ?? 0) * 100) / g.toplam) : 0}
          format={() => `${g.sayilar.ONAYLANDI ?? 0}/${g.toplam - (g.sayilar.GERI_ALINDI ?? 0)}`}
        />
      ),
    },
    {
      title: "Durum",
      width: 240,
      render: (_, g) => (
        <Space size={4} wrap>
          {(g.sayilar.GONDERILDI ?? 0) + (g.sayilar.GORULDU ?? 0) > 0 && (
            <Tag color="gold">Bekleyen {(g.sayilar.GONDERILDI ?? 0) + (g.sayilar.GORULDU ?? 0)}</Tag>
          )}
          {(g.sayilar.GONDERILDI ?? 0) > 0 && <Tag>Açmayan {g.sayilar.GONDERILDI}</Tag>}
          {(g.sayilar.ITIRAZ ?? 0) > 0 && <Tag color="red">İtiraz {g.sayilar.ITIRAZ}</Tag>}
        </Space>
      ),
    },
  ];
  return (
    <>
      <Segmented
        style={{ marginBottom: 12 }}
        value={tur}
        onChange={(v) => setTur(v as BelgeTuru | "TUMU")}
        options={[
          { value: "TUMU", label: "Tümü" },
          ...(Object.keys(TUR_ETIKETLERI) as BelgeTuru[]).map((t) => ({ value: t, label: TUR_ETIKETLERI[t] })),
        ]}
      />
      {liste.error && <Alert type="error" title={(liste.error as Error).message} />}
      <Table
        rowKey="id"
        size="small"
        loading={liste.isLoading}
        dataSource={liste.data ?? []}
        columns={kolonlar}
        scroll={{ x: 900 }}
        onRow={(g) => ({ onClick: () => setSecili(g.id), style: { cursor: "pointer" } })}
      />
      {secili !== null && <GonderimCekmecesi id={secili} kapat={() => setSecili(null)} />}
    </>
  );
}

function GonderimCekmecesi({ id, kapat }: { id: number; kapat: () => void }) {
  const { message, modal } = App.useApp();
  const qc = useQueryClient();
  const d = useQuery({ queryKey: ["ik-gonderim", id], queryFn: () => ikBelgeApi.gonderim(id) });
  const [kanit, setKanit] = useState<number | null>(null);
  const tazele = () => {
    void qc.invalidateQueries({ queryKey: ["ik-gonderim", id] });
    void qc.invalidateQueries({ queryKey: ["ik-gonderimler"] });
  };
  const hatirlat = useMutation({
    mutationFn: (idler?: number[]) => ikBelgeApi.hatirlat(id, idler),
    onSuccess: (r) => {
      void message.success(
        `${r.hatirlatilan} kişiye hatırlatma kaydedildi` + (r.bildirilen ? `, ${r.bildirilen} e-posta gitti` : ""),
      );
      tazele();
    },
    onError: (e: ApiError) => void message.error(e.message),
  });
  const geriAl = (b: BelgeSatiri) => {
    let gerekce = "";
    modal.confirm({
      title: `${b.ad} belgesini geri al`,
      content: (
        <Input.TextArea rows={3} placeholder="Gerekçe (en az 5 karakter)" onChange={(e) => (gerekce = e.target.value)} />
      ),
      okText: "Geri al",
      okButtonProps: { danger: true },
      cancelText: "Vazgeç",
      onOk: async () => {
        try {
          await ikBelgeApi.geriAl(b.id, gerekce);
          void message.success("Belge geri alındı");
          tazele();
        } catch (e) {
          void message.error((e as ApiError).message);
          throw e;
        }
      },
    });
  };
  const bekleyen = (d.data?.belgeler ?? []).filter((b) => b.durum === "GONDERILDI" || b.durum === "GORULDU");
  const kolonlar: ColumnsType<BelgeSatiri> = [
    { title: "Personel", dataIndex: "ad", render: (a, b) => (b.sicil_no ? `${a} (${b.sicil_no})` : a) },
    {
      title: "Durum",
      dataIndex: "durum",
      width: 150,
      render: (s: BelgeSatiri["durum"], b) => (
        <Space size={4}>
          <Tag color={DURUM_ETIKETLERI[s].renk}>{DURUM_ETIKETLERI[s].ad}</Tag>
          {b.gecikti && <Tag color="red">Gecikti</Tag>}
        </Space>
      ),
    },
    { title: "Görüldü", dataIndex: "goruldu_at", width: 135, render: tarih },
    { title: "Yanıt", dataIndex: "yanit_at", width: 135, render: tarih },
    {
      title: "İtiraz gerekçesi",
      dataIndex: "itiraz_gerekcesi",
      render: (g) => (g ? <Typography.Text type="danger">{g}</Typography.Text> : null),
    },
    {
      title: "Hatırlatma",
      dataIndex: "hatirlatma_sayisi",
      width: 90,
      render: (n: number, b) => (n ? <Tooltip title={tarih(b.son_hatirlatma_at)}>{n}</Tooltip> : "—"),
    },
    {
      title: "",
      width: 230,
      render: (_, b) => (
        <Space size={4}>
          <Button size="small" href={ikBelgeApi.belgeDosyaUrl(b.id)} target="_blank">
            Aç
          </Button>
          <Button size="small" onClick={() => setKanit(b.id)}>
            Kanıt
          </Button>
          {(b.durum === "GONDERILDI" || b.durum === "GORULDU") && (
            <>
              <Button size="small" icon={<BellOutlined />} onClick={() => hatirlat.mutate([b.id])} />
              <Button size="small" danger onClick={() => geriAl(b)}>
                Geri al
              </Button>
            </>
          )}
        </Space>
      ),
    },
  ];
  return (
    <Drawer open onClose={kapat} width={Math.min(1100, window.innerWidth)} title={d.data?.baslik ?? "Gönderim"}>
      {d.error && <Alert type="error" title={(d.error as Error).message} />}
      {d.data && (
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Space wrap>
            <Tag>{TUR_ETIKETLERI[d.data.tur]}</Tag>
            {d.data.donem && <span>Dönem: {d.data.donem}</span>}
            {d.data.son_tarih && <span>Son tarih: {dayjs(d.data.son_tarih).format("DD.MM.YYYY")}</span>}
            <span>Gönderen: {d.data.gonderen ?? "—"}</span>
            <Button
              icon={<BellOutlined />}
              disabled={bekleyen.length === 0}
              loading={hatirlat.isPending}
              onClick={() => hatirlat.mutate(undefined)}
            >
              Bekleyenlere hatırlat ({bekleyen.length})
            </Button>
          </Space>
          {d.data.aciklama && <Typography.Paragraph>{d.data.aciklama}</Typography.Paragraph>}
          <Table rowKey="id" size="small" pagination={false} dataSource={d.data.belgeler} columns={kolonlar} scroll={{ x: 1000 }} />
        </Space>
      )}
      {kanit !== null && <KanitPenceresi belgeId={kanit} kapat={() => setKanit(null)} />}
    </Drawer>
  );
}

const OLAY_ADLARI: Record<string, string> = {
  GONDERILDI: "Gönderildi",
  GORULDU: "Görüldü",
  ONAYLANDI: "Onaylandı",
  ITIRAZ: "İtiraz",
  HATIRLATMA: "Hatırlatma",
  GERI_ALINDI: "Geri alındı",
};

function KanitPenceresi({ belgeId, kapat }: { belgeId: number; kapat: () => void }) {
  const k = useQuery<Kanit>({ queryKey: ["ik-kanit", belgeId], queryFn: () => ikBelgeApi.kanit(belgeId) });
  return (
    <Modal open onCancel={kapat} footer={null} width={900} title="İmza ve işlem kanıtı">
      {k.data && (
        <>
          <Alert
            style={{ marginBottom: 12 }}
            type={k.data.zincir_gecerli ? "success" : "error"}
            title={k.data.zincir_gecerli ? "Kayıt zinciri doğrulandı (değiştirilmemiş)" : "Kayıt zinciri BOZUK"}
            description={<Typography.Text copyable code>{`Belge özeti (SHA-256): ${k.data.belge_ozeti}`}</Typography.Text>}
          />
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={k.data.olaylar}
            scroll={{ x: 800 }}
            columns={[
              { title: "Olay", dataIndex: "olay", render: (o: string) => OLAY_ADLARI[o] ?? o },
              { title: "Kişi", dataIndex: "kisi" },
              { title: "Zaman", dataIndex: "at", render: tarih },
              { title: "IP", dataIndex: "ip" },
              { title: "Doğrulama", dataIndex: "dogrulama", render: (d) => (d === "TOTP" ? "Kod" : d === "PAROLA" ? "Parola" : "—") },
              { title: "Açıklama", dataIndex: "aciklama" },
              {
                title: "Kayıt özeti",
                dataIndex: "kayit_ozeti",
                render: (o: string) => <Typography.Text code copyable={{ text: o }}>{o.slice(0, 12)}…</Typography.Text>,
              },
            ]}
          />
        </>
      )}
    </Modal>
  );
}

// --- Bordro gönder -----------------------------------------------------------------------

interface BordroSatiri {
  uid: string;
  dosya: File;
  user_id: number | null;
  yontem: Eslesme["yontem"] | "ELLE";
}

function useAlicilar() {
  return useQuery({ queryKey: ["ik-alicilar"], queryFn: ikBelgeApi.alicilar, staleTime: 60_000 });
}

function aliciSecenekleri(alicilar: Alici[] | undefined) {
  return (alicilar ?? []).map((a) => ({
    value: a.id,
    label: `${a.ad}${a.sicil_no ? ` (${a.sicil_no})` : ""}`,
  }));
}

function BordroSekmesi({ bitti }: { bitti: () => void }) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const alicilar = useAlicilar();
  const [donem, setDonem] = useState<Dayjs>(dayjs().subtract(1, "month"));
  const [baslik, setBaslik] = useState("");
  const [satirlar, setSatirlar] = useState<BordroSatiri[]>([]);
  const [bildir, setBildir] = useState(true);

  const ekle = async (dosyalar: File[]) => {
    const yeni = dosyalar.filter((f) => !satirlar.some((s) => s.dosya.name === f.name));
    if (!yeni.length) return;
    try {
      const es = await ikBelgeApi.eslestir(yeni.map((f) => f.name));
      setSatirlar((eski) => [
        ...eski,
        ...yeni.map((f, i) => ({
          uid: `${f.name}-${f.size}-${Date.now()}-${i}`,
          dosya: f,
          user_id: es[i]?.user_id ?? null,
          yontem: es[i]?.yontem ?? "YOK",
        })),
      ]);
    } catch (e) {
      void message.error((e as ApiError).message);
    }
  };

  const tekrar = useMemo(() => {
    const say = new Map<number, number>();
    for (const s of satirlar) if (s.user_id) say.set(s.user_id, (say.get(s.user_id) ?? 0) + 1);
    return new Set([...say].filter(([, n]) => n > 1).map(([k]) => k));
  }, [satirlar]);
  const eksik = satirlar.filter((s) => !s.user_id).length;

  const gonder = useMutation({
    mutationFn: () =>
      ikBelgeApi.gonder(
        {
          tur: "BORDRO",
          donem: donem.format("YYYY-MM"),
          baslik: baslik.trim() || `${donem.format("YYYY-MM")} bordrosu`,
          alicilar: satirlar.map((s) => s.user_id as number),
          bildir,
        },
        satirlar.map((s) => s.dosya),
      ),
    onSuccess: (r) => {
      void message.success(
        `${r.gonderim.toplam} kişiye bordro gönderildi` + (r.bildirilen ? `, ${r.bildirilen} e-posta gitti` : ""),
      );
      setSatirlar([]);
      void qc.invalidateQueries({ queryKey: ["ik-gonderimler"] });
      bitti();
    },
    onError: (e: ApiError) => void message.error(e.message),
  });

  const YONTEM: Record<BordroSatiri["yontem"], { ad: string; renk: string }> = {
    SICIL: { ad: "Sicil no", renk: "green" },
    AD: { ad: "Ad soyad", renk: "blue" },
    BELIRSIZ: { ad: "Birden çok kişi", renk: "orange" },
    YOK: { ad: "Eşleşmedi", renk: "red" },
    ELLE: { ad: "Elle seçildi", renk: "default" },
  };

  return (
    <Space orientation="vertical" style={{ width: "100%" }}>
      <Space wrap>
        <span>Dönem</span>
        <DatePicker picker="month" value={donem} onChange={(v) => v && setDonem(v)} allowClear={false} format="YYYY-MM" />
        <Input
          style={{ width: 280 }}
          placeholder={`${donem.format("YYYY-MM")} bordrosu`}
          value={baslik}
          onChange={(e) => setBaslik(e.target.value)}
        />
        <Space>
          <Switch checked={bildir} onChange={setBildir} /> E-posta ile haber ver
        </Space>
      </Space>
      <Upload.Dragger
        multiple
        accept="application/pdf,.pdf"
        showUploadList={false}
        beforeUpload={(_f: UploadFile, liste) => {
          // Toplu seçimde liste bir kez işlensin.
          if (_f === liste[0]) void ekle(liste as unknown as File[]);
          return false;
        }}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p>Personel bordrolarını (PDF, kişi başına bir dosya) buraya sürükleyin</p>
        <p style={{ color: "#888" }}>Dosya adında sicil no ya da ad soyad varsa kişi kendiliğinden eşleşir.</p>
      </Upload.Dragger>
      {satirlar.length > 0 && (
        <>
          <Table
            rowKey="uid"
            size="small"
            pagination={false}
            dataSource={satirlar}
            columns={[
              { title: "Dosya", render: (_, s) => s.dosya.name },
              {
                title: "Personel",
                width: 340,
                render: (_, s) => (
                  <Select
                    showSearch
                    optionFilterProp="label"
                    style={{ width: "100%" }}
                    status={!s.user_id || tekrar.has(s.user_id) ? "error" : undefined}
                    placeholder="Kişi seçin"
                    value={s.user_id ?? undefined}
                    options={aliciSecenekleri(alicilar.data)}
                    onChange={(v: number) =>
                      setSatirlar((eski) => eski.map((x) => (x.uid === s.uid ? { ...x, user_id: v, yontem: "ELLE" } : x)))
                    }
                  />
                ),
              },
              {
                title: "Eşleşme",
                width: 140,
                render: (_, s) => <Tag color={YONTEM[s.yontem].renk}>{YONTEM[s.yontem].ad}</Tag>,
              },
              {
                title: "",
                width: 70,
                render: (_, s) => (
                  <Button size="small" onClick={() => setSatirlar((eski) => eski.filter((x) => x.uid !== s.uid))}>
                    Çıkar
                  </Button>
                ),
              },
            ]}
          />
          {(eksik > 0 || tekrar.size > 0) && (
            <Alert
              type="warning"
              title={eksik > 0 ? `${eksik} dosyanın kişisi seçilmedi` : "Aynı kişi birden çok dosyaya seçildi"}
            />
          )}
          <Button
            type="primary"
            icon={<SendOutlined />}
            disabled={eksik > 0 || tekrar.size > 0}
            loading={gonder.isPending}
            onClick={() => gonder.mutate()}
          >
            {satirlar.length} kişiye bordroyu gönder
          </Button>
        </>
      )}
    </Space>
  );
}

// --- Belge gönder (form/talimat/taahhütname) ------------------------------------------------

interface BelgeFormu {
  tur: BelgeTuru;
  baslik: string;
  aciklama?: string;
  son_tarih?: Dayjs;
  kaynak: "SABLON" | "DOSYA";
  sablon_id?: number;
  alicilar: number[];
  bildir: boolean;
}

function BelgeSekmesi({ bitti }: { bitti: () => void }) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [form] = Form.useForm<BelgeFormu>();
  const alicilar = useAlicilar();
  const sablonlar = useQuery({ queryKey: ["ik-sablonlar", "aktif"], queryFn: () => ikBelgeApi.sablonlar(true) });
  const [dosya, setDosya] = useState<File | null>(null);
  const kaynak = Form.useWatch("kaynak", form);

  const gonder = useMutation({
    mutationFn: (v: BelgeFormu) =>
      ikBelgeApi.gonder(
        {
          tur: v.tur,
          baslik: v.baslik,
          aciklama: v.aciklama ?? null,
          son_tarih: v.son_tarih ? v.son_tarih.format("YYYY-MM-DD") : null,
          sablon_id: v.kaynak === "SABLON" ? (v.sablon_id ?? null) : null,
          alicilar: v.alicilar,
          bildir: v.bildir,
        },
        v.kaynak === "DOSYA" && dosya ? [dosya] : [],
      ),
    onSuccess: (r) => {
      void message.success(`${r.gonderim.toplam} kişiye gönderildi`);
      form.resetFields();
      setDosya(null);
      void qc.invalidateQueries({ queryKey: ["ik-gonderimler"] });
      bitti();
    },
    onError: (e: ApiError) => void message.error(e.message),
  });

  const sablonSec = (id: number) => {
    const s = sablonlar.data?.find((x) => x.id === id);
    if (s) form.setFieldsValue({ tur: s.tur, baslik: form.getFieldValue("baslik") || s.ad });
  };

  return (
    <Form<BelgeFormu>
      form={form}
      layout="vertical"
      style={{ maxWidth: 720 }}
      initialValues={{ tur: "TALIMAT", kaynak: "SABLON", alicilar: [], bildir: true }}
      onFinish={(v) => {
        if (v.kaynak === "DOSYA" && !dosya) {
          void message.error("PDF seçin");
          return;
        }
        gonder.mutate(v);
      }}
    >
      <Form.Item name="kaynak" label="Belge">
        <Radio.Group
          options={[
            { value: "SABLON", label: "Şablondan" },
            { value: "DOSYA", label: "PDF yükle" },
          ]}
        />
      </Form.Item>
      {kaynak === "SABLON" ? (
        <Form.Item name="sablon_id" label="Şablon" rules={[{ required: true, message: "Şablon seçin" }]}>
          <Select
            placeholder="Şablon seçin"
            onChange={sablonSec}
            options={(sablonlar.data ?? []).map((s) => ({ value: s.id, label: `${s.ad} (${TUR_ETIKETLERI[s.tur]})` }))}
          />
        </Form.Item>
      ) : (
        <Form.Item label="PDF" required>
          <Upload
            accept="application/pdf,.pdf"
            maxCount={1}
            beforeUpload={(f) => {
              setDosya(f as unknown as File);
              return false;
            }}
            onRemove={() => setDosya(null)}
          >
            <Button>PDF seç</Button>
          </Upload>
        </Form.Item>
      )}
      <Form.Item name="tur" label="Tür" rules={[{ required: true }]}>
        <Select options={SABLON_TURLERI.map((t) => ({ value: t, label: TUR_ETIKETLERI[t] }))} />
      </Form.Item>
      <Form.Item name="baslik" label="Başlık" rules={[{ required: true, min: 3 }]}>
        <Input maxLength={200} />
      </Form.Item>
      <Form.Item name="aciklama" label="Açıklama (personel görür)">
        <Input.TextArea rows={2} maxLength={2000} />
      </Form.Item>
      <Form.Item name="son_tarih" label="Son tarih (isteğe bağlı)">
        <DatePicker format="DD.MM.YYYY" disabledDate={(d) => d.isBefore(dayjs(), "day")} />
      </Form.Item>
      <Form.Item
        name="alicilar"
        label={
          <Space>
            Alıcılar
            <Button
              size="small"
              type="link"
              onClick={() => form.setFieldValue("alicilar", (alicilar.data ?? []).map((a) => a.id))}
            >
              Tümünü seç ({alicilar.data?.length ?? 0})
            </Button>
          </Space>
        }
        rules={[{ required: true, type: "array", min: 1, message: "En az bir kişi seçin" }]}
      >
        <Select mode="multiple" optionFilterProp="label" placeholder="Personel seçin" options={aliciSecenekleri(alicilar.data)} />
      </Form.Item>
      <Form.Item name="bildir" label="E-posta ile haber ver" valuePropName="checked">
        <Switch />
      </Form.Item>
      <Button type="primary" htmlType="submit" icon={<SendOutlined />} loading={gonder.isPending}>
        Gönder
      </Button>
    </Form>
  );
}

// --- Şablonlar ------------------------------------------------------------------------------

function SablonSekmesi() {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const liste = useQuery({ queryKey: ["ik-sablonlar", "tum"], queryFn: () => ikBelgeApi.sablonlar(false) });
  const [form] = Form.useForm<{ ad: string; tur: BelgeTuru; aciklama?: string }>();
  const [dosya, setDosya] = useState<File | null>(null);
  const tazele = () => void qc.invalidateQueries({ queryKey: ["ik-sablonlar"] });

  const ekle = useMutation({
    mutationFn: (v: { ad: string; tur: BelgeTuru; aciklama?: string }) =>
      ikBelgeApi.sablonEkle(v.ad, v.tur, v.aciklama, dosya as File),
    onSuccess: () => {
      void message.success("Şablon eklendi");
      form.resetFields();
      setDosya(null);
      tazele();
    },
    onError: (e: ApiError) => void message.error(e.message),
  });
  const aktiflik = useMutation({
    mutationFn: (s: Sablon) => ikBelgeApi.sablonDuzelt(s.id, { aktif: !s.aktif, version: s.version }),
    onSuccess: tazele,
    onError: (e: ApiError) => void message.error(e.message),
  });

  return (
    <Space orientation="vertical" style={{ width: "100%" }}>
      <Form
        form={form}
        layout="inline"
        initialValues={{ tur: "TALIMAT" }}
        onFinish={(v) => (dosya ? ekle.mutate(v) : void message.error("PDF seçin"))}
      >
        <Form.Item name="ad" rules={[{ required: true, min: 2 }]}>
          <Input placeholder="Şablon adı" style={{ width: 240 }} />
        </Form.Item>
        <Form.Item name="tur">
          <Select style={{ width: 150 }} options={SABLON_TURLERI.map((t) => ({ value: t, label: TUR_ETIKETLERI[t] }))} />
        </Form.Item>
        <Form.Item name="aciklama">
          <Input placeholder="Açıklama" style={{ width: 220 }} />
        </Form.Item>
        <Form.Item>
          <Upload
            accept="application/pdf,.pdf"
            maxCount={1}
            beforeUpload={(f) => {
              setDosya(f as unknown as File);
              return false;
            }}
            onRemove={() => setDosya(null)}
          >
            <Button>PDF seç</Button>
          </Upload>
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={ekle.isPending}>
          Ekle
        </Button>
      </Form>
      <Table<Sablon>
        rowKey="id"
        size="small"
        loading={liste.isLoading}
        dataSource={liste.data ?? []}
        columns={[
          { title: "Ad", dataIndex: "ad" },
          { title: "Tür", dataIndex: "tur", render: (t: BelgeTuru) => TUR_ETIKETLERI[t] },
          { title: "Açıklama", dataIndex: "aciklama" },
          {
            title: "Dosya",
            dataIndex: "dosya_adi",
            render: (a: string, s) => (
              <a href={ikBelgeApi.sablonDosyaUrl(s.id)} target="_blank" rel="noreferrer">
                {a}
              </a>
            ),
          },
          {
            title: "Aktif",
            dataIndex: "aktif",
            width: 80,
            render: (a: boolean, s) => <Switch size="small" checked={a} onChange={() => aktiflik.mutate(s)} />,
          },
        ]}
      />
    </Space>
  );
}
