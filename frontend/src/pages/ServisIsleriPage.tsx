/**
 * Servis İşleri — liste, Drawer, durum/bekleme/sonuç/atama/onay pencereleri (TS-033, TS-036).
 *
 * - Liste SUNUCUDA süzülür ve sayfalanır (`X-Toplam-Kayit`); süzgeç URL'de
 *   durur ki panel kutusu (`?kpi=<kod>&donem=`) ve geri tuşu aynı listeyi açsın.
 * - Durum düğmeleri sunucunun `gecisler` listesinden (makine + uç + izin)
 *   çizilir; ekran kendi geçiş kuralı yazmaz. Yetkisiz düğme görünmez.
 * - Her yazma isteği ekranda görülen durumu (`beklenen_durum`) ya da sürümü
 *   taşır; başkası değiştirdiyse sunucu 409 döner, kayıt yeniden yüklenir ve
 *   kullanıcıya "yenilendi" denir (sessiz üzerine yazma yok).
 * - 375 px: tablo yatay kayar, ikincil sütunlar gizlenir, Drawer tam ekran.
 */
import {
  ClearOutlined,
  FilePdfOutlined,
  FileExcelOutlined,
  PlusOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Col,
  DatePicker,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Grid,
  Input,
  List,
  Modal,
  Radio,
  Row,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Timeline,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { BIRIM_ETIKETLERI, personelApi } from "../api/personel";
import { operasyonApi } from "../api/servisOperasyon";
import {
  DONEMLER,
  DURUM_RENKLERI,
  donemAraligiMetni,
  imzaYukle,
  KPI_ADLARI,
  ONAY_TURLERI,
  ONCELIK_ADLARI,
  ONCELIK_RENKLERI,
  teknikServisApi,
  type AtamaSatiri,
  type FormVerileri,
  type IsSatiri,
  type IsSuzgeci,
  type OnayGirdisi,
} from "../api/teknikServis";
import { useAuth } from "../auth/AuthContext";
import EkYukleyici from "../components/EkYukleyici";
import { ServisGozlemleri } from "../components/GozlemFormu";
import KayitGorevleri from "../components/KayitGorevleri";
import { PlanGecmisiSekmesi, ZamanSekmesi } from "../components/ServisIsSekmeleri";
import ServisParcalari from "../components/ServisParcalari";
import SlaEtiketi, { SlaKartiPenceresi } from "../components/SlaEtiketi";
import BakimFormu from "./BakimFormu";
import ServisIsFormu from "./ServisIsFormu";

const SAYFA_BOYU = 50;
const zaman = (d?: string | null) => (d ? dayjs(d).format("DD.MM.YYYY HH:mm") : "—");

function suzgecOku(p: URLSearchParams): IsSuzgeci {
  return {
    q: p.get("q") ?? undefined,
    birim: p.get("birim") ?? undefined,
    tur: p.get("tur") ?? undefined,
    oncelik: p.get("oncelik") ?? undefined,
    durum_grubu: p.get("durum_grubu") ?? undefined,
    durum: p.getAll("durum").length ? p.getAll("durum") : undefined,
    atanmamis: p.get("atanmamis") === "true" || undefined,
    kapali_dahil: p.get("kapali_dahil") === "true" || undefined,
    kpi: p.get("kpi") ?? undefined,
    donem: p.get("donem") ?? undefined,
    teknisyen_id: p.get("teknisyen_id") ? Number(p.get("teknisyen_id")) : undefined,
    musteri_id: p.get("musteri_id") ? Number(p.get("musteri_id")) : undefined,
    // Müşteri servis kartından tesis bazlı açık iş (TS-192) bağlantısı.
    adres_id: p.get("adres_id") ? Number(p.get("adres_id")) : undefined,
    siralama: p.get("siralama") ?? undefined,
  };
}

function suzgecYaz(s: IsSuzgeci): URLSearchParams {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(s)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    if (Array.isArray(v)) v.forEach((x) => p.append(k, String(x)));
    else p.set(k, String(v));
  }
  return p;
}

/** 409 = ekrandaki hâl eskidi: kullanıcıya söylenir, kayıt yenilenir. */
function useHata(yenile: () => void) {
  const { message } = App.useApp();
  return (e: unknown) => {
    if (e instanceof ApiError && e.status === 409) {
      message.warning(`${e.message}. Kayıt yeniden yüklendi.`, 5);
      yenile();
      return;
    }
    message.error((e as Error).message);
  };
}

function DurumEtiketi({ kod, sozluk }: { kod: string; sozluk?: FormVerileri }) {
  const ad = sozluk?.durumlar.find((d) => d.kod === kod)?.ad ?? kod;
  return <Tag color={DURUM_RENKLERI[kod]}>{ad}</Tag>;
}

// --- İmza (canvas → PNG) -----------------------------------------------------------

function ImzaAlani({ onDegisti }: { onDegisti: (bos: boolean) => void }) {
  const tuval = useRef<HTMLCanvasElement | null>(null);
  const ciziyor = useRef(false);

  const nokta = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return {
      x: ((e.clientX - r.left) * e.currentTarget.width) / r.width,
      y: ((e.clientY - r.top) * e.currentTarget.height) / r.height,
    };
  };

  return (
    <Space orientation="vertical" style={{ width: "100%" }} size={4}>
      <canvas
        ref={tuval}
        width={600}
        height={200}
        style={{
          width: "100%",
          height: 160,
          border: "1px solid #d9d9d9",
          borderRadius: 4,
          touchAction: "none",
          background: "#fff",
        }}
        onPointerDown={(e) => {
          const c = e.currentTarget.getContext("2d");
          if (!c) return;
          ciziyor.current = true;
          e.currentTarget.setPointerCapture(e.pointerId);
          const p = nokta(e);
          c.lineWidth = 2.5;
          c.lineCap = "round";
          c.strokeStyle = "#000";
          c.beginPath();
          c.moveTo(p.x, p.y);
        }}
        onPointerMove={(e) => {
          if (!ciziyor.current) return;
          const c = e.currentTarget.getContext("2d");
          if (!c) return;
          const p = nokta(e);
          c.lineTo(p.x, p.y);
          c.stroke();
        }}
        onPointerUp={() => {
          if (ciziyor.current) onDegisti(false);
          ciziyor.current = false;
        }}
      />
      <Button
        size="small"
        icon={<ClearOutlined />}
        onClick={() => {
          const c = tuval.current?.getContext("2d");
          if (c && tuval.current) c.clearRect(0, 0, tuval.current.width, tuval.current.height);
          onDegisti(true);
        }}
      >
        Temizle
      </Button>
    </Space>
  );
}

function tuvalPng(kapsayici: HTMLElement | null): Promise<Blob | null> {
  const c = kapsayici?.querySelector("canvas");
  return new Promise((coz) => (c ? c.toBlob((b) => coz(b), "image/png") : coz(null)));
}

/** Tekil ya da ziyaret (çoklu iş) müşteri onayı penceresi (TS-036). */
function OnayPenceresi({
  isIdler,
  acik,
  kapat,
  bitti,
}: {
  isIdler: number[];
  acik: boolean;
  kapat: () => void;
  bitti: () => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm<OnayGirdisi & { form_ek_id?: number }>();
  const tur = Form.useWatch("tur", form);
  const [imzaBos, setImzaBos] = useState(true);
  const [gonderiliyor, setGonderiliyor] = useState(false);
  const imzaKutusu = useRef<HTMLDivElement | null>(null);
  const ziyaret = isIdler.length > 1;
  const formEkleri = useQuery({
    queryKey: ["ekler", "service_orders", isIdler[0]],
    queryFn: () =>
      fetch(`/api/ekler/service_orders/${isIdler[0]}`, { credentials: "same-origin" }).then(
        (r) => r.json() as Promise<{ id: number; kind: string; file_name: string }[]>,
      ),
    enabled: acik && tur === "BASILI_FORM",
  });

  useEffect(() => {
    if (acik) {
      form.resetFields();
      setImzaBos(true);
    }
  }, [acik, form]);

  async function gonder(v: OnayGirdisi & { form_ek_id?: number }) {
    setGonderiliyor(true);
    try {
      let ekId: number | null = null;
      if (v.tur === "IMZA") {
        const png = await tuvalPng(imzaKutusu.current);
        if (!png || imzaBos) throw new Error("Müşteri imzası çizilmedi");
        ekId = await imzaYukle(isIdler[0], png);
      } else if (v.tur === "BASILI_FORM") {
        ekId = v.form_ek_id ?? null;
      }
      const govde: OnayGirdisi = {
        tur: v.tur,
        imzalayan_ad: v.imzalayan_ad || null,
        imzalayan_unvan: v.imzalayan_unvan || null,
        eksik_nedeni: v.eksik_nedeni || null,
        ek_id: ekId,
      };
      if (ziyaret) await teknikServisApi.ziyaretOnayi(isIdler, govde);
      else await teknikServisApi.onayAl(isIdler[0], govde);
      message.success(ziyaret ? `${isIdler.length} işe ziyaret onayı yazıldı` : "Onay kaydedildi");
      bitti();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setGonderiliyor(false);
    }
  }

  return (
    <Modal
      title={ziyaret ? `Ziyaret onayı (${isIdler.length} iş)` : "Müşteri onayı"}
      open={acik}
      onCancel={kapat}
      onOk={() => form.submit()}
      okText="Kaydet"
      cancelText="Vazgeç"
      confirmLoading={gonderiliyor}
      destroyOnHidden
    >
      {ziyaret && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="Ziyaret onayı yalnız aynı müşteri, aynı lokasyon ve aynı gündeki işlere verilir."
        />
      )}
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        Onay değiştirilemez; yeni onay öncekini geçersiz kılar ve ikisi de geçmişte kalır.
      </Typography.Paragraph>
      <Form form={form} layout="vertical" onFinish={(v) => void gonder(v)} initialValues={{ tur: "IMZA" }}>
        <Form.Item name="tur" label="Onay biçimi">
          <Radio.Group options={ONAY_TURLERI.map((t) => ({ value: t.kod, label: t.ad }))} />
        </Form.Item>
        {(tur === "IMZA" || tur === "SOZLU" || tur === "BASILI_FORM") && (
          <Row gutter={8}>
            <Col xs={24} sm={14}>
              <Form.Item
                name="imzalayan_ad"
                label="Onaylayan"
                rules={
                  tur === "BASILI_FORM" ? [] : [{ required: true, whitespace: true, message: "Ad zorunlu" }]
                }
              >
                <Input maxLength={120} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={10}>
              <Form.Item name="imzalayan_unvan" label="Unvan">
                <Input maxLength={80} />
              </Form.Item>
            </Col>
          </Row>
        )}
        {tur === "IMZA" && (
          <div ref={imzaKutusu}>
            <Form.Item label="İmza">
              <ImzaAlani onDegisti={setImzaBos} />
            </Form.Item>
          </div>
        )}
        {tur === "BASILI_FORM" && (
          <Form.Item
            name="form_ek_id"
            label="İmzalı formun fotoğrafı"
            extra="Önce 'Ekler' sekmesinden 'Servis formu' olarak yükleyin."
            rules={[{ required: true, message: "Formun ekini seçin" }]}
          >
            <Select
              loading={formEkleri.isFetching}
              options={(formEkleri.data ?? [])
                .filter((e) => e.kind === "SERVIS_FORMU")
                .map((e) => ({ value: e.id, label: e.file_name }))}
            />
          </Form.Item>
        )}
        {tur === "ALINAMADI" && (
          <Form.Item
            name="eksik_nedeni"
            label="Neden alınamadı?"
            rules={[{ required: true, whitespace: true, message: "Neden zorunlu" }]}
          >
            <Input.TextArea rows={2} maxLength={300} />
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
}

// --- Atama -----------------------------------------------------------------------------

function AtamaPenceresi({
  birim,
  isIdler,
  mevcut,
  acik,
  kapat,
  bitti,
}: {
  birim: string;
  isIdler: number[];
  mevcut: AtamaSatiri[];
  acik: boolean;
  kapat: () => void;
  bitti: () => void;
}) {
  const { message } = App.useApp();
  const toplu = isIdler.length > 1;
  const [kisiler, setKisiler] = useState<number[]>([]);
  const [sorumlu, setSorumlu] = useState<number | undefined>();
  const [mod, setMod] = useState<"EKLE" | "DEGISTIR">("DEGISTIR");
  const aday = useQuery({
    queryKey: ["atanabilir", birim],
    queryFn: () => personelApi.atanabilir(birim),
    enabled: acik && !!birim,
  });

  useEffect(() => {
    if (acik) {
      setKisiler(mevcut.map((m) => m.user_id));
      setSorumlu(mevcut.find((m) => m.is_lead)?.user_id);
      setMod("DEGISTIR");
    }
  }, [acik, mevcut]);

  const rolu = (id: number): "SEF" | "TEKNISYEN" =>
    aday.data?.find((k) => k.id === id)?.saha_rolu === "SEF" ? "SEF" : "TEKNISYEN";

  const kaydet = useMutation({
    mutationFn: () => {
      const satirlar: AtamaSatiri[] = kisiler.map((id) => ({
        user_id: id,
        rol: rolu(id),
        is_lead: id === sorumlu,
      }));
      return toplu
        ? teknikServisApi.topluAta(isIdler, satirlar, mod).then((r) => r.uyarilar ?? [])
        : teknikServisApi.ataUyarili(isIdler[0], satirlar).then((r) => r.uyarilar);
    },
    onSuccess: (uyarilar: string[]) => {
      message.success(toplu ? `${isIdler.length} işin ekibi güncellendi` : "Ekip güncellendi");
      if (uyarilar.length) {
        // TS-198 / E08-22: yetkinlik eksikliği atamayı engellemez, yalnız uyarır.
        Modal.warning({
          title: "Yetkinlik uyarısıyla atandı",
          content: (
            <ul style={{ paddingLeft: 18, margin: 0 }}>
              {uyarilar.map((u) => (
                <li key={u}>{u}</li>
              ))}
            </ul>
          ),
        });
      }
      bitti();
    },
    onError: (e: Error) => message.error(e.message),
  });

  const secenekler = (aday.data ?? []).map((k) => ({
    value: k.id,
    label: `${k.ad}${k.giris_acik ? "" : " (girişsiz)"} · ${k.saha_rolu}`,
  }));

  return (
    <Modal
      title={toplu ? `Toplu atama (${isIdler.length} iş)` : "Ekip ataması"}
      open={acik}
      onCancel={kapat}
      onOk={() => kaydet.mutate()}
      okText="Kaydet"
      cancelText="Vazgeç"
      confirmLoading={kaydet.isPending}
      destroyOnHidden
    >
      <Space orientation="vertical" style={{ width: "100%" }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {BIRIM_ETIKETLERI[birim] ?? birim} biriminin atanabilir saha personeli. Sorumlu yalnız
          teknisyen olabilir; açık sayacı olan kişi ekipten çıkarılamaz.
        </Typography.Text>
        {toplu && (
          <Radio.Group
            value={mod}
            onChange={(e) => setMod(e.target.value)}
            options={[
              { value: "DEGISTIR", label: "Ekibi bununla değiştir" },
              { value: "EKLE", label: "Mevcut ekibe ekle" },
            ]}
          />
        )}
        <Select
          mode="multiple"
          style={{ width: "100%" }}
          placeholder="Personel seçin"
          loading={aday.isFetching}
          value={kisiler}
          onChange={(v) => {
            setKisiler(v);
            if (sorumlu && !v.includes(sorumlu)) setSorumlu(undefined);
          }}
          options={secenekler}
          optionFilterProp="label"
        />
        <Select
          allowClear
          style={{ width: "100%" }}
          placeholder="Sorumlu teknisyen"
          value={sorumlu}
          onChange={setSorumlu}
          options={secenekler.filter((s) => kisiler.includes(s.value) && rolu(s.value) === "TEKNISYEN")}
        />
      </Space>
    </Modal>
  );
}

// --- Detay Drawer ----------------------------------------------------------------------

type Pencere =
  | null
  | "duzenle"
  | "genel"
  | "bekleme"
  | "bekleme_bitir"
  | "sonuc"
  | "kapat"
  | "iptal"
  | "yeniden_ac"
  | "atama"
  | "onay";

function IsDetayCekmecesi({
  id,
  sozluk,
  kapat,
}: {
  id: number;
  sozluk?: FormVerileri;
  kapat: () => void;
}) {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const git = useNavigate();
  const ekran = Grid.useBreakpoint();
  const [pencere, setPencere] = useState<Pencere>(null);
  const [hedef, setHedef] = useState<string | null>(null);
  const [sureEksikSoruldu, setSureEksikSoruldu] = useState<string | null>(null);
  const [form] = Form.useForm();
  const [notMetni, setNotMetni] = useState("");
  const [bakimFormuAcik, setBakimFormuAcik] = useState(false);
  const [slaKartiAcik, setSlaKartiAcik] = useState(false);

  const detay = useQuery({ queryKey: ["servis-is", id], queryFn: () => teknikServisApi.getir(id) });
  // SLA kartı (TS-081/084): etiket sunucudan; PB ve atölye işleri SLA dışı.
  const slaTabi = !!detay.data && !["PB", "ATOLYE"].includes(detay.data.tur);
  const slaKarti = useQuery({
    queryKey: ["is-sla", id],
    queryFn: () => operasyonApi.isSla(id),
    enabled: slaTabi,
  });
  const gecmis = useQuery({ queryKey: ["servis-is-gecmis", id], queryFn: () => teknikServisApi.gecmis(id) });
  const onaylar = useQuery({ queryKey: ["servis-is-onay", id], queryFn: () => teknikServisApi.onaylar(id) });
  const beklemeler = useQuery({
    queryKey: ["servis-is-bekleme", id],
    queryFn: () => teknikServisApi.beklemeler(id),
  });

  const yenile = () => {
    void qc.invalidateQueries({ queryKey: ["servis-is", id] });
    void qc.invalidateQueries({ queryKey: ["servis-is-gecmis", id] });
    void qc.invalidateQueries({ queryKey: ["servis-is-onay", id] });
    void qc.invalidateQueries({ queryKey: ["servis-is-bekleme", id] });
    void qc.invalidateQueries({ queryKey: ["servis-isleri"] });
    void qc.invalidateQueries({ queryKey: ["is-sla", id] });
  };
  const hata = useHata(yenile);
  const d = detay.data;
  const birim = d?.birim;

  const arizaNedenleri = useQuery({
    queryKey: ["ariza-nedenleri", birim],
    queryFn: () => teknikServisApi.arizaNedenleri(birim as string),
    enabled: !!birim && pencere === "sonuc",
  });

  const pencereAc = (p: Pencere, h: string | null = null) => {
    form.resetFields();
    setSureEksikSoruldu(null);
    setHedef(h);
    setPencere(p);
  };
  const pencereKapat = () => setPencere(null);

  const islem = useMutation({
    mutationFn: async (v: Record<string, unknown>) => {
      if (!d) throw new Error("Kayıt yok");
      const beklenen = d.status;
      switch (pencere) {
        case "genel":
          return teknikServisApi.durum(d.id, hedef as string, beklenen, (v.gerekce as string) || undefined);
        case "bekleme":
          return teknikServisApi.beklet(d.id, {
            neden: v.neden as string,
            aciklama: (v.aciklama as string) || undefined,
            beklenen_bitis_at: v.beklenen_bitis_at ? dayjs(v.beklenen_bitis_at as string).toISOString() : null,
          });
        case "bekleme_bitir":
          return teknikServisApi.beklemeyiBitir(d.id, (v.not as string) || undefined);
        case "sonuc":
          return teknikServisApi.sonuc(d.id, {
            sonuc: v.sonuc as string,
            cozum_kanali: v.cozum_kanali as string,
            yapilan_islem: (v.yapilan_islem as string).trim(),
            ariza_nedeni_id: (v.ariza_nedeni_id as number) ?? null,
            saha_seri_no: (v.saha_seri_no as string) || null,
            saha_bolge: (v.saha_bolge as string) || null,
            sure_eksik_onay: !!v.sure_eksik_onay,
          });
        case "kapat":
          return teknikServisApi.kapat(d.id, beklenen, (v.gerekce as string) || undefined);
        case "iptal":
          return teknikServisApi.iptal(d.id, v.gerekce as string, beklenen);
        case "yeniden_ac":
          return teknikServisApi.yenidenAc(d.id, v.gerekce as string, beklenen);
        default:
          throw new Error("Bilinmeyen işlem");
      }
    },
    onSuccess: () => {
      message.success("Kaydedildi");
      pencereKapat();
      yenile();
    },
    onError: (e: Error) => {
      // TS-076 (D1-G kancası): süre kaydı eksik/kısmi işte kapanış ayrıca onay ister.
      if (pencere === "sonuc" && e instanceof ApiError && e.status === 409 && /süre kaydı/i.test(e.message)) {
        setSureEksikSoruldu(e.message);
        return;
      }
      hata(e);
    },
  });

  const notEkle = useMutation({
    mutationFn: () => teknikServisApi.notEkle(id, notMetni.trim()),
    onSuccess: () => {
      setNotMetni("");
      void qc.invalidateQueries({ queryKey: ["servis-is-gecmis", id] });
    },
    onError: (e: Error) => message.error(e.message),
  });

  if (detay.isError) {
    return (
      <Drawer open onClose={kapat} title="Servis işi" width={ekran.md ? 760 : "100%"}>
        <Empty description={(detay.error as Error).message} />
      </Drawer>
    );
  }

  const yazabilir = yetkili("servis.yaz");
  const kapali = d ? ["TAMAMLANDI", "KAPATILDI", "IPTAL"].includes(d.status) : false;
  const ekYazabilir = yazabilir && (!kapali || yetkili("servis.kapat"));
  const gecisDugmeleri = (d?.gecisler ?? []).filter((g) => g.yetkili);

  const gecisTiklandi = (uc: string, h: string) => {
    if (uc === "planla") {
      git(`/servis-planlama?is=${id}`);
      return;
    }
    const harita: Record<string, Pencere> = {
      genel: "genel",
      bekleme: "bekleme",
      sonuc: "sonuc",
      kapat: "kapat",
      iptal: "iptal",
      yeniden_ac: "yeniden_ac",
    };
    pencereAc(harita[uc] ?? null, h);
  };

  const pencereBasligi: Record<string, string> = {
    genel: `Durum: ${sozluk?.durumlar.find((x) => x.kod === hedef)?.ad ?? hedef ?? ""}`,
    bekleme: "Beklemeye al",
    bekleme_bitir: "Beklemeyi bitir",
    sonuc: "Sonuç gir ve tamamla",
    kapat: "İşi kapat",
    iptal: "İşi iptal et",
    yeniden_ac: "İşi yeniden aç",
  };

  return (
    <Drawer
      open
      onClose={kapat}
      width={ekran.md ? 760 : "100%"}
      title={
        d ? (
          <Space wrap size={4}>
            <Typography.Text strong copyable>
              {d.so_no}
            </Typography.Text>
            <DurumEtiketi kod={d.status} sozluk={sozluk} />
            {d.oncelik !== "NORMAL" && <Tag color={ONCELIK_RENKLERI[d.oncelik]}>{ONCELIK_ADLARI[d.oncelik]}</Tag>}
            {slaTabi && <SlaEtiketi sla={slaKarti.data?.sla} />}
          </Space>
        ) : (
          "Servis işi"
        )
      }
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={yenile} aria-label="Yenile" />
          {d && (
            <Button icon={<FilePdfOutlined />} href={teknikServisApi.servisFormuYolu(d.id)} target="_blank">
              {ekran.sm ? "Servis formu" : ""}
            </Button>
          )}
        </Space>
      }
      loading={detay.isLoading}
    >
      {d && (
        <Space orientation="vertical" style={{ width: "100%" }} size="middle">
          <Space wrap>
            {gecisDugmeleri.map((g) => (
              <Button
                key={g.hedef}
                type={g.uc === "sonuc" || g.uc === "kapat" ? "primary" : "default"}
                danger={g.uc === "iptal"}
                onClick={() => gecisTiklandi(g.uc, g.hedef)}
              >
                {g.uc === "sonuc" ? "Sonuç gir" : g.uc === "kapat" ? "Kapat" : g.uc === "iptal" ? "İptal et" : g.uc === "yeniden_ac" ? "Yeniden aç" : g.uc === "planla" ? "Planla" : g.ad}
              </Button>
            ))}
            {d.status === "BEKLEMEDE" && yazabilir && (
              <Button onClick={() => pencereAc("bekleme_bitir")}>Beklemeyi bitir</Button>
            )}
            {yazabilir && !["IPTAL"].includes(d.status) && (
              <Button onClick={() => pencereAc("duzenle")}>Düzenle</Button>
            )}
            {yetkili("servis.planla") && !kapali && (
              <Button onClick={() => pencereAc("atama")}>Ekip</Button>
            )}
            {yazabilir && !["IPTAL", "KAPATILDI"].includes(d.status) && (
              <Button onClick={() => pencereAc("onay")}>Müşteri onayı</Button>
            )}
            {d.tur === "PB" && (
              <Button type="dashed" onClick={() => setBakimFormuAcik(true)}>
                Bakım Formu
              </Button>
            )}
            {slaTabi && (
              <Button
                danger={(slaKarti.data?.kapanis_icin_gerekenler.length ?? 0) > 0}
                onClick={() => setSlaKartiAcik(true)}
              >
                SLA kartı
              </Button>
            )}
            {yetkili("teklif.yaz") && !["IPTAL", "KAPATILDI"].includes(d.status) && (
              <Button onClick={() => git(`/teklifler?servis_isi=${d.id}`)}>Teklif hazırla</Button>
            )}
          </Space>
          {slaKarti.data && slaKarti.data.kapanis_icin_gerekenler.length > 0 && (
            <Alert
              type="warning"
              showIcon
              title="Kapatmadan önce SLA kartından kapanış bilgisi girilmeli"
              action={
                <Button size="small" onClick={() => setSlaKartiAcik(true)}>
                  Gir
                </Button>
              }
            />
          )}
          <SlaKartiPenceresi
            soId={slaKartiAcik ? d.id : null}
            onKapat={() => {
              setSlaKartiAcik(false);
              void qc.invalidateQueries({ queryKey: ["is-sla", id] });
            }}
          />
          <BakimFormu
            soId={bakimFormuAcik ? d.id : null}
            onKapat={() => {
              setBakimFormuAcik(false);
              yenile();
            }}
          />

          <Tabs
            items={[
              {
                key: "genel",
                label: "Genel",
                children: (
                  <Space orientation="vertical" style={{ width: "100%" }}>
                    <Descriptions size="small" column={{ xs: 1, sm: 2 }} bordered>
                      <Descriptions.Item label="Birim">{BIRIM_ETIKETLERI[d.birim] ?? d.birim}</Descriptions.Item>
                      <Descriptions.Item label="Tür">
                        {sozluk?.turler.find((t) => t.kod === d.tur)?.ad ?? d.tur}
                      </Descriptions.Item>
                      <Descriptions.Item label="Müşteri" span={2}>
                        {d.musteri?.title ?? d.customer_name_raw ?? "—"}
                      </Descriptions.Item>
                      <Descriptions.Item label="Lokasyon" span={2}>
                        {d.lokasyon ? [d.lokasyon.ad, d.lokasyon.il].filter(Boolean).join(" · ") : "—"}
                      </Descriptions.Item>
                      <Descriptions.Item label="Saha yetkilisi">
                        {d.irtibat?.full_name ?? d.iletisim_ad ?? "—"}
                      </Descriptions.Item>
                      <Descriptions.Item label="Telefon">
                        {d.irtibat?.telefon ?? d.iletisim_telefon ?? "—"}
                      </Descriptions.Item>
                      <Descriptions.Item label="Konu" span={2}>
                        {d.konu}
                      </Descriptions.Item>
                      {d.aciklama && (
                        <Descriptions.Item label="Açıklama" span={2}>
                          <Typography.Paragraph style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                            {d.aciklama}
                          </Typography.Paragraph>
                        </Descriptions.Item>
                      )}
                      <Descriptions.Item label="Seri" span={2}>
                        {d.seriler.length ? d.seriler.map((s) => <Tag key={s.id}>{s.seri_no}</Tag>) : "—"}
                      </Descriptions.Item>
                      <Descriptions.Item label="Bildirim">{zaman(d.reported_at)}</Descriptions.Item>
                      <Descriptions.Item label="Açılış">{zaman(d.created_at)}</Descriptions.Item>
                      {d.completed_at && (
                        <Descriptions.Item label="Tamamlanma">{zaman(d.completed_at)}</Descriptions.Item>
                      )}
                      {d.closed_at && <Descriptions.Item label="Kapanış">{zaman(d.closed_at)}</Descriptions.Item>}
                      {d.cancel_reason && (
                        <Descriptions.Item label="İptal gerekçesi" span={2}>
                          {d.cancel_reason}
                        </Descriptions.Item>
                      )}
                      <Descriptions.Item label="Ekip" span={2}>
                        {d.ekip.length
                          ? d.ekip.map((e) => (
                              <Tag key={e.user_id} color={e.is_lead ? "blue" : undefined}>
                                {e.ad}
                                {e.is_lead ? " (sorumlu)" : ""}
                                {e.giris_acik ? "" : " · girişsiz"}
                              </Tag>
                            ))
                          : <Typography.Text type="warning">Atanmamış</Typography.Text>}
                      </Descriptions.Item>
                    </Descriptions>
                    {d.bekleme && (
                      <Alert
                        type="warning"
                        showIcon
                        message={`Beklemede: ${d.bekleme.neden_adi}`}
                        description={[
                          d.bekleme.aciklama,
                          `Başlangıç ${zaman(d.bekleme.started_at)}`,
                          d.bekleme.beklenen_bitis_at ? `Beklenen bitiş ${zaman(d.bekleme.beklenen_bitis_at)}` : null,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      />
                    )}
                    {d.sonuc && (
                      <Card size="small" title="Sonuç">
                        <Space orientation="vertical" size={2}>
                          <span>
                            {sozluk?.sonuclar.find((s) => s.kod === d.sonuc?.sonuc)?.ad ?? d.sonuc.sonuc} ·{" "}
                            {sozluk?.cozum_kanallari.find((s) => s.kod === d.sonuc?.cozum_kanali)?.ad ??
                              d.sonuc.cozum_kanali}
                            {d.sonuc.ariza_nedeni ? ` · ${d.sonuc.ariza_nedeni}` : ""}
                          </span>
                          <Typography.Text style={{ whiteSpace: "pre-wrap" }}>{d.sonuc.yapilan_islem}</Typography.Text>
                        </Space>
                      </Card>
                    )}
                  </Space>
                ),
              },
              {
                key: "gecmis",
                label: "Geçmiş",
                children: (
                  <Space orientation="vertical" style={{ width: "100%" }}>
                    {yazabilir && (
                      <Space.Compact style={{ width: "100%" }}>
                        <Input
                          placeholder="Not ekle (irtibat adı/telefonu yazmayın)"
                          maxLength={500}
                          value={notMetni}
                          onChange={(e) => setNotMetni(e.target.value)}
                          onPressEnter={() => notMetni.trim() && notEkle.mutate()}
                        />
                        <Button
                          type="primary"
                          loading={notEkle.isPending}
                          disabled={!notMetni.trim()}
                          onClick={() => notEkle.mutate()}
                        >
                          Ekle
                        </Button>
                      </Space.Compact>
                    )}
                    {gecmis.data?.length ? (
                      <Timeline
                        items={gecmis.data
                          .slice()
                          .reverse()
                          .map((o) => ({
                            key: o.id,
                            color: o.olay_turu === "DURUM" ? "blue" : o.olay_turu === "EK_SIL" ? "red" : "gray",
                            children: (
                              <Space orientation="vertical" size={0}>
                                <Typography.Text strong>{o.olay_adi}</Typography.Text>
                                <Typography.Text>{o.ozet}</Typography.Text>
                                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                                  {zaman(o.olusma_zamani)} · {o.kullanici?.ad ?? "Sistem"}
                                </Typography.Text>
                              </Space>
                            ),
                          }))}
                      />
                    ) : (
                      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Olay yok" />
                    )}
                  </Space>
                ),
              },
              {
                key: "ekler",
                label: "Ekler",
                children: (
                  <Space orientation="vertical" style={{ width: "100%" }}>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      Ek yalnız yükleyen kişi tarafından 24 saat içinde silinebilir; kapalı işte ek ekleme ve
                      silme kapatma yetkisi ister. Onaya bağlı ek silinemez.
                    </Typography.Text>
                    <EkYukleyici
                      entity="service_orders"
                      entityId={d.id}
                      kind="SERVIS_ONCESI"
                      baslik="Servis öncesi fotoğraflar"
                      yazabilir={ekYazabilir}
                      accept="image/*"
                      capture="environment"
                    />
                    <EkYukleyici
                      entity="service_orders"
                      entityId={d.id}
                      kind="SERVIS_SONRASI"
                      baslik="Servis sonrası fotoğraflar"
                      yazabilir={ekYazabilir}
                      accept="image/*"
                      capture="environment"
                    />
                    <EkYukleyici
                      entity="service_orders"
                      entityId={d.id}
                      kind="SERVIS_FORMU"
                      baslik="İmzalı servis formu"
                      yazabilir={ekYazabilir}
                      accept="image/*,application/pdf"
                    />
                    <EkYukleyici
                      entity="service_orders"
                      entityId={d.id}
                      kind="IMZA"
                      baslik="Müşteri imzaları"
                      yazabilir={false}
                    />
                  </Space>
                ),
              },
              {
                key: "onay",
                label: `Onay${onaylar.data?.length ? ` (${onaylar.data.length})` : ""}`,
                children: onaylar.data?.length ? (
                  <List
                    size="small"
                    dataSource={onaylar.data.slice().reverse()}
                    renderItem={(o) => {
                      const gecersiz = (onaylar.data ?? []).some((x) => x.gecersiz_kilan_id === o.id);
                      return (
                        <List.Item>
                          <Space orientation="vertical" size={0}>
                            <Space wrap size={4}>
                              <Typography.Text strong delete={gecersiz}>
                                {ONAY_TURLERI.find((t) => t.kod === o.tur)?.ad ?? o.tur}
                              </Typography.Text>
                              {gecersiz ? <Tag>Geçersiz kılındı</Tag> : <Tag color="green">Geçerli</Tag>}
                              {o.onay_grubu && <Tag color="purple">Ziyaret onayı</Tag>}
                            </Space>
                            <Typography.Text>
                              {[o.imzalayan_ad, o.imzalayan_unvan, o.eksik_nedeni].filter(Boolean).join(" · ") || "—"}
                            </Typography.Text>
                            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                              {zaman(o.approved_at)}
                            </Typography.Text>
                          </Space>
                        </List.Item>
                      );
                    }}
                  />
                ) : (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Müşteri onayı yok" />
                ),
              },
              {
                key: "zaman",
                label: "Zaman",
                children: <ZamanSekmesi isId={d.id} soNo={d.so_no} />,
              },
              {
                key: "plan",
                label: "Plan Geçmişi",
                children: <PlanGecmisiSekmesi isId={d.id} />,
              },
              // Kullanılan parçalar (TS-133, D2-D): PB formu ve atölyeyle aynı bileşen.
              {
                key: "parca",
                label: "Parçalar",
                children: <ServisParcalari soId={d.id} />,
              },
              // Saha gözlemi (TS-156, D2-F): iş no ve birim kilitli form.
              ...(yetkili("egitim.gor") || yetkili("egitim.gozlem")
                ? [
                    {
                      key: "gozlem",
                      label: "Saha Gözlemleri",
                      children: <ServisGozlemleri soId={d.id} soNo={d.so_no} birim={d.birim} />,
                    },
                  ]
                : []),
              ...(yetkili("gorev.gor")
                ? [
                    {
                      key: "gorev",
                      label: "Görevler",
                      children: <KayitGorevleri entity="servis_isi" entityId={d.id} />,
                    },
                  ]
                : []),
              {
                key: "bekleme",
                label: "Beklemeler",
                children: (
                  <Space orientation="vertical" style={{ width: "100%" }}>
                    <Typography.Text>
                      Toplam bekleme: {beklemeler.data?.toplam_dk ?? 0} dk
                    </Typography.Text>
                    <List
                      size="small"
                      locale={{ emptyText: "Bekleme yok" }}
                      dataSource={beklemeler.data?.beklemeler ?? []}
                      renderItem={(b) => (
                        <List.Item>
                          <Space orientation="vertical" size={0}>
                            <Typography.Text strong>{b.neden_adi}</Typography.Text>
                            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                              {zaman(b.started_at)} → {b.released_at ? zaman(b.released_at) : "sürüyor"}
                              {b.sure_dk != null ? ` · ${b.sure_dk} dk` : ""}
                            </Typography.Text>
                            {b.aciklama && <Typography.Text>{b.aciklama}</Typography.Text>}
                          </Space>
                        </List.Item>
                      )}
                    />
                  </Space>
                ),
              },
            ]}
          />
        </Space>
      )}

      {d && (
        <Modal
          title="Servis işini düzenle"
          open={pencere === "duzenle"}
          onCancel={pencereKapat}
          footer={null}
          width={ekran.md ? 720 : "100%"}
          destroyOnHidden
        >
          <ServisIsFormu
            is={d}
            formVerileri={sozluk}
            onKaydedildi={() => {
              pencereKapat();
              yenile();
            }}
            onVazgec={pencereKapat}
            onCakisma={() => {
              pencereKapat();
              yenile();
            }}
          />
        </Modal>
      )}

      {d && (
        <Modal
          title={pencereBasligi[pencere ?? ""] ?? ""}
          open={!!pencere && pencere in pencereBasligi}
          onCancel={pencereKapat}
          onOk={() => form.submit()}
          okText="Kaydet"
          cancelText="Vazgeç"
          okButtonProps={{ danger: pencere === "iptal" }}
          confirmLoading={islem.isPending}
          destroyOnHidden
        >
          <Form form={form} layout="vertical" onFinish={(v) => islem.mutate(v)}>
            {pencere === "genel" && (
              <Form.Item name="gerekce" label="Not (isteğe bağlı)">
                <Input maxLength={500} />
              </Form.Item>
            )}
            {pencere === "bekleme" && (
              <>
                <Form.Item name="neden" label="Bekleme nedeni" rules={[{ required: true, message: "Neden seçin" }]}>
                  <Select
                    options={(sozluk?.bekleme_nedenleri ?? []).map((n) => ({ value: n.kod, label: n.ad }))}
                  />
                </Form.Item>
                <Form.Item noStyle shouldUpdate>
                  {() => {
                    const zorunlu = !!sozluk?.bekleme_nedenleri.find(
                      (n) => n.kod === form.getFieldValue("neden"),
                    )?.aciklama_zorunlu;
                    return (
                      <Form.Item
                        name="aciklama"
                        label="Açıklama"
                        rules={zorunlu ? [{ required: true, whitespace: true, message: "Açıklama zorunlu" }] : []}
                      >
                        <Input.TextArea rows={2} maxLength={500} />
                      </Form.Item>
                    );
                  }}
                </Form.Item>
                <Form.Item name="beklenen_bitis_at" label="Beklenen bitiş">
                  <DatePicker
                    showTime={{ format: "HH:mm" }}
                    format="DD.MM.YYYY HH:mm"
                    style={{ width: "100%" }}
                    disabledDate={(x) => x.isBefore(dayjs(), "day")}
                  />
                </Form.Item>
              </>
            )}
            {pencere === "bekleme_bitir" && (
              <Form.Item name="not" label="Not" extra="İş beklemeden önceki durumuna döner.">
                <Input maxLength={200} />
              </Form.Item>
            )}
            {pencere === "sonuc" && (
              <>
                <Row gutter={8}>
                  <Col xs={24} sm={12}>
                    <Form.Item name="sonuc" label="Sonuç" rules={[{ required: true, message: "Sonuç seçin" }]}>
                      <Select options={(sozluk?.sonuclar ?? []).map((s) => ({ value: s.kod, label: s.ad }))} />
                    </Form.Item>
                  </Col>
                  <Col xs={24} sm={12}>
                    <Form.Item
                      name="cozum_kanali"
                      label="Çözüm kanalı"
                      rules={[{ required: true, message: "Kanal seçin" }]}
                    >
                      <Select options={(sozluk?.cozum_kanallari ?? []).map((s) => ({ value: s.kod, label: s.ad }))} />
                    </Form.Item>
                  </Col>
                </Row>
                <Form.Item
                  name="yapilan_islem"
                  label="Yapılan işlem"
                  rules={[{ required: true, whitespace: true, message: "Yapılan işlemi yazın" }]}
                >
                  <Input.TextArea rows={3} maxLength={4000} />
                </Form.Item>
                <Form.Item name="ariza_nedeni_id" label="Arıza nedeni">
                  <Select
                    allowClear
                    loading={arizaNedenleri.isFetching}
                    options={(arizaNedenleri.data ?? [])
                      .filter((n) => n.is_active)
                      .map((n) => ({ value: n.id, label: n.ad }))}
                  />
                </Form.Item>
                <Row gutter={8}>
                  <Col xs={24} sm={12}>
                    <Form.Item name="saha_seri_no" label="Sahada görülen seri (farklıysa)">
                      <Input maxLength={200} />
                    </Form.Item>
                  </Col>
                  <Col xs={24} sm={12}>
                    <Form.Item name="saha_bolge" label="Bölge / konum">
                      <Input maxLength={120} />
                    </Form.Item>
                  </Col>
                </Row>
                {sureEksikSoruldu && (
                  <>
                    <Alert type="warning" showIcon message={sureEksikSoruldu} style={{ marginBottom: 8 }} />
                    <Form.Item
                      name="sure_eksik_onay"
                      valuePropName="checked"
                      rules={[
                        {
                          validator: (_, v) =>
                            v ? Promise.resolve() : Promise.reject(new Error("Kapatmak için onaylayın")),
                        },
                      ]}
                    >
                      <Checkbox>Süre kaydı eksik olduğunu biliyorum, yine de tamamla</Checkbox>
                    </Form.Item>
                  </>
                )}
              </>
            )}
            {pencere === "kapat" && (
              <Form.Item name="gerekce" label="Not (isteğe bağlı)">
                <Input maxLength={500} />
              </Form.Item>
            )}
            {(pencere === "iptal" || pencere === "yeniden_ac") && (
              <Form.Item
                name="gerekce"
                label="Gerekçe"
                rules={[{ required: true, whitespace: true, min: 3, message: "Gerekçe zorunlu (en az 3 karakter)" }]}
              >
                <Input.TextArea rows={2} maxLength={500} />
              </Form.Item>
            )}
          </Form>
        </Modal>
      )}

      {d && (
        <AtamaPenceresi
          birim={d.birim}
          isIdler={[d.id]}
          mevcut={d.ekip.map((e) => ({ user_id: e.user_id, rol: e.rol, is_lead: e.is_lead }))}
          acik={pencere === "atama"}
          kapat={pencereKapat}
          bitti={() => {
            pencereKapat();
            yenile();
          }}
        />
      )}
      {d && (
        <OnayPenceresi
          isIdler={[d.id]}
          acik={pencere === "onay"}
          kapat={pencereKapat}
          bitti={() => {
            pencereKapat();
            yenile();
          }}
        />
      )}
    </Drawer>
  );
}

// --- Sayfa ----------------------------------------------------------------------------------

export default function ServisIsleriPage() {
  const { yetkili } = useAuth();
  const qc = useQueryClient();
  const git = useNavigate();
  const { id } = useParams();
  const [arama, setArama] = useSearchParams();
  const ekran = Grid.useBreakpoint();
  const suzgec = useMemo(() => suzgecOku(arama), [arama]);
  const [sayfa, setSayfa] = useState(1);
  const [secili, setSecili] = useState<number[]>([]);
  const [yeniAcik, setYeniAcik] = useState(false);
  const [topluAtamaAcik, setTopluAtamaAcik] = useState(false);
  const [ziyaretAcik, setZiyaretAcik] = useState(false);
  const [aramaMetni, setAramaMetni] = useState(suzgec.q ?? "");

  const yolEki = arama.toString() ? `?${arama.toString()}` : "";
  const sozluk = useQuery({
    queryKey: ["servis-form-verileri"],
    queryFn: teknikServisApi.formVerileri,
    staleTime: 5 * 60_000,
  });
  const liste = useQuery({
    queryKey: ["servis-isleri", suzgec, sayfa],
    queryFn: () => teknikServisApi.liste(suzgec, SAYFA_BOYU, (sayfa - 1) * SAYFA_BOYU),
  });

  const suzgecDegistir = (yeni: IsSuzgeci) => {
    setArama(suzgecYaz(yeni));
    setSayfa(1);
    setSecili([]);
  };

  const seciliSatirlar = (liste.data?.kayitlar ?? []).filter((r) => secili.includes(r.id));
  const seciliBirimler = new Set(seciliSatirlar.map((r) => r.birim));
  const aktarabilir = yetkili("servis.gor", "servis_rapor.disaaktar");
  const durumAdi = (k: string) => sozluk.data?.durumlar.find((d) => d.kod === k)?.ad ?? k;

  const sutunlar: ColumnsType<IsSatiri> = [
    {
      title: "İş No",
      dataIndex: "so_no",
      width: 150,
      render: (v: string, r) => (
        <Space orientation="vertical" size={0}>
          <Typography.Text strong style={{ fontFamily: "monospace" }}>
            {v}
          </Typography.Text>
          {r.oncelik !== "NORMAL" && (
            <Tag color={ONCELIK_RENKLERI[r.oncelik]} style={{ marginTop: 2 }}>
              {ONCELIK_ADLARI[r.oncelik]}
            </Tag>
          )}
        </Space>
      ),
    },
    {
      title: "Durum",
      dataIndex: "status",
      width: 130,
      render: (v: string, r) => (
        <Space orientation="vertical" size={0}>
          <DurumEtiketi kod={v} sozluk={sozluk.data} />
          {r.aktif_bekleme && (
            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
              {sozluk.data?.bekleme_nedenleri.find((n) => n.kod === r.aktif_bekleme)?.ad ?? r.aktif_bekleme}
            </Typography.Text>
          )}
        </Space>
      ),
    },
    {
      title: "Müşteri / Lokasyon",
      key: "musteri",
      render: (_, r) => (
        <Space orientation="vertical" size={0}>
          <span>{r.musteri?.title ?? r.customer_name_raw ?? "—"}</span>
          {r.lokasyon && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {[r.lokasyon.ad, r.lokasyon.il].filter(Boolean).join(" · ")}
            </Typography.Text>
          )}
        </Space>
      ),
    },
    { title: "Konu", dataIndex: "konu", ellipsis: true, responsive: ["md"] },
    {
      title: "Seri",
      dataIndex: "seriler",
      responsive: ["lg"],
      render: (v: string[]) => v.slice(0, 2).join(", ") + (v.length > 2 ? ` +${v.length - 2}` : ""),
    },
    {
      title: "Birim",
      dataIndex: "birim",
      responsive: ["xl"],
      render: (v: string) => BIRIM_ETIKETLERI[v] ?? v,
    },
    {
      title: "Sorumlu",
      key: "sorumlu",
      responsive: ["md"],
      render: (_, r) =>
        r.sorumlu?.ad ?? (r.ekip_sayisi ? `${r.ekip_sayisi} kişi` : <Typography.Text type="warning">Atanmamış</Typography.Text>),
    },
    {
      title: "Açılış",
      dataIndex: "created_at",
      width: 130,
      responsive: ["sm"],
      render: (v: string) => zaman(v),
    },
  ];

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      <Card
        title="Servis İşleri"
        extra={
          <Space wrap>
            {yetkili("servis.yaz") && (
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setYeniAcik(true)}>
                {ekran.sm ? "Yeni iş" : ""}
              </Button>
            )}
            {aktarabilir && (
              <Button icon={<FileExcelOutlined />} href={teknikServisApi.excelYolu(suzgec)} target="_blank">
                {ekran.sm ? "Excel" : ""}
              </Button>
            )}
          </Space>
        }
      >
        <Space orientation="vertical" size="small" style={{ width: "100%" }}>
          {suzgec.kpi && (
            <Space wrap>
              <Tag
                color="blue"
                closable
                onClose={(e) => {
                  e.preventDefault();
                  suzgecDegistir({ ...suzgec, kpi: undefined, donem: undefined });
                }}
              >
                Panel: {KPI_ADLARI[suzgec.kpi] ?? suzgec.kpi}
                {suzgec.donem
                  ? ` · ${
                      DONEMLER.find((d) => d.kod === suzgec.donem)?.ad ??
                      donemAraligiMetni(suzgec.donem) ??
                      suzgec.donem
                    }`
                  : ""}
              </Tag>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                Liste panel kutusunun süzgeciyle açıldı (sayı = liste).
              </Typography.Text>
            </Space>
          )}
          <Row gutter={[8, 8]}>
            <Col xs={24} md={8}>
              <Input.Search
                allowClear
                placeholder="İş no, seri, konu, müşteri…"
                value={aramaMetni}
                onChange={(e) => setAramaMetni(e.target.value)}
                onSearch={(q) => suzgecDegistir({ ...suzgec, q: q.trim() || undefined })}
              />
            </Col>
            <Col xs={12} md={4}>
              <Select
                allowClear
                style={{ width: "100%" }}
                placeholder="Birim"
                value={suzgec.birim}
                onChange={(v) => suzgecDegistir({ ...suzgec, birim: v })}
                options={(sozluk.data?.birimler ?? []).map((b) => ({ value: b.kod, label: b.ad }))}
              />
            </Col>
            <Col xs={12} md={4}>
              <Select
                allowClear
                mode="multiple"
                maxTagCount={1}
                style={{ width: "100%" }}
                placeholder="Durum"
                value={suzgec.durum}
                onChange={(v) => suzgecDegistir({ ...suzgec, durum: v.length ? v : undefined })}
                options={(sozluk.data?.durumlar ?? []).map((d) => ({ value: d.kod, label: d.ad }))}
              />
            </Col>
            <Col xs={12} md={4}>
              <Select
                allowClear
                style={{ width: "100%" }}
                placeholder="Tür"
                value={suzgec.tur}
                onChange={(v) => suzgecDegistir({ ...suzgec, tur: v })}
                options={(sozluk.data?.turler ?? []).map((t) => ({ value: t.kod, label: t.ad }))}
              />
            </Col>
            <Col xs={12} md={4}>
              <Select
                allowClear
                style={{ width: "100%" }}
                placeholder="Öncelik"
                value={suzgec.oncelik}
                onChange={(v) => suzgecDegistir({ ...suzgec, oncelik: v })}
                options={Object.entries(ONCELIK_ADLARI).map(([k, v]) => ({ value: k, label: v }))}
              />
            </Col>
          </Row>
          <Space wrap>
            <Checkbox
              checked={!!suzgec.atanmamis}
              onChange={(e) => suzgecDegistir({ ...suzgec, atanmamis: e.target.checked || undefined })}
            >
              Atanmamış
            </Checkbox>
            <Checkbox
              checked={!!suzgec.kapali_dahil}
              onChange={(e) => suzgecDegistir({ ...suzgec, kapali_dahil: e.target.checked || undefined })}
            >
              Eski kapalı işler dahil
            </Checkbox>
            <Select
              size="small"
              style={{ width: 150 }}
              value={suzgec.siralama ?? "yeni"}
              onChange={(v) => suzgecDegistir({ ...suzgec, siralama: v === "yeni" ? undefined : v })}
              options={[
                { value: "yeni", label: "En yeni" },
                { value: "eski", label: "En eski" },
                { value: "oncelik", label: "Önceliğe göre" },
                { value: "no", label: "İş numarası" },
              ]}
            />
          </Space>

          {secili.length > 0 && (
            <Alert
              type="info"
              message={
                <Space wrap>
                  <span>{secili.length} iş seçili</span>
                  {yetkili("servis.planla") && (
                    <Button
                      size="small"
                      disabled={seciliBirimler.size !== 1}
                      title={seciliBirimler.size !== 1 ? "Toplu atama tek birimin işleriyle yapılır" : undefined}
                      onClick={() => setTopluAtamaAcik(true)}
                    >
                      Toplu atama
                    </Button>
                  )}
                  {yetkili("servis.yaz") && (
                    <Button size="small" onClick={() => setZiyaretAcik(true)}>
                      Ziyaret onayı
                    </Button>
                  )}
                  <Button
                    size="small"
                    icon={<FilePdfOutlined />}
                    href={teknikServisApi.ziyaretFormuYolu(secili)}
                    target="_blank"
                  >
                    Ziyaret formu
                  </Button>
                  <Button size="small" type="link" onClick={() => setSecili([])}>
                    Seçimi temizle
                  </Button>
                </Space>
              }
            />
          )}

          <Table<IsSatiri>
            rowKey="id"
            size="small"
            columns={sutunlar}
            dataSource={liste.data?.kayitlar ?? []}
            loading={liste.isFetching}
            scroll={{ x: 640 }}
            rowSelection={
              yetkili("servis.yaz") || yetkili("servis.planla")
                ? { selectedRowKeys: secili, onChange: (k) => setSecili(k as number[]) }
                : undefined
            }
            onRow={(r) => ({ onClick: () => git(`/servis-isleri/${r.id}${yolEki}`), style: { cursor: "pointer" } })}
            locale={{
              emptyText: liste.isError ? (liste.error as Error).message : "Bu süzgece uyan servis işi yok",
            }}
            pagination={{
              current: sayfa,
              pageSize: SAYFA_BOYU,
              total: liste.data?.toplam ?? 0,
              showSizeChanger: false,
              showTotal: (t) => `${t.toLocaleString("tr-TR")} iş`,
              onChange: (p) => setSayfa(p),
            }}
          />
          {suzgec.durum?.length === 1 && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Durum: {durumAdi(suzgec.durum[0])}
            </Typography.Text>
          )}
        </Space>
      </Card>

      <Drawer
        open={yeniAcik}
        title="Yeni servis işi"
        width={ekran.md ? 720 : "100%"}
        onClose={() => setYeniAcik(false)}
        destroyOnHidden
      >
        <ServisIsFormu
          formVerileri={sozluk.data}
          onKaydedildi={(d) => {
            setYeniAcik(false);
            void qc.invalidateQueries({ queryKey: ["servis-isleri"] });
            git(`/servis-isleri/${d.id}${yolEki}`);
          }}
          onVazgec={() => setYeniAcik(false)}
        />
      </Drawer>

      {id && (
        <IsDetayCekmecesi
          key={id}
          id={Number(id)}
          sozluk={sozluk.data}
          kapat={() => git(`/servis-isleri${yolEki}`)}
        />
      )}

      {seciliBirimler.size === 1 && (
        <AtamaPenceresi
          birim={[...seciliBirimler][0]}
          isIdler={secili}
          mevcut={[]}
          acik={topluAtamaAcik}
          kapat={() => setTopluAtamaAcik(false)}
          bitti={() => {
            setTopluAtamaAcik(false);
            setSecili([]);
            void qc.invalidateQueries({ queryKey: ["servis-isleri"] });
          }}
        />
      )}
      <OnayPenceresi
        isIdler={secili}
        acik={ziyaretAcik && secili.length > 0}
        kapat={() => setZiyaretAcik(false)}
        bitti={() => {
          setZiyaretAcik(false);
          void qc.invalidateQueries({ queryKey: ["servis-isleri"] });
        }}
      />
    </Space>
  );
}
