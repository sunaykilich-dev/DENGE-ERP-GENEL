/**
 * Servis İşleri — liste, Drawer, durum/bekleme/sonuç/tayin/onay pencereleri (TS-033, TS-036).
 *
 * - Görünüm SAP Fiori liste raporu (`fiori/ListeRaporu`, rehber §3): tür
 *   kategori şeridi, "Kayıt Sayısı", durum çubuğu (YENİ · TAYİN · İŞLEM …),
 *   radyo seçimli tablo ve alt eylem çubuğu (Liste, Saat Aç/Kapa, Tayin Et,
 *   İptal, Düzenle, PDF). Görünen dil "tayin"dir; API alanları (`atama`,
 *   `atanmamis`) aynı kalır. `ServisIsListesi` Planlı Bakım ekranında da
 *   kullanılır (PLANSIZ/PLANLI kategorileriyle).
 * - Liste SUNUCUDA süzülür ve sayfalanır (`X-Toplam-Kayit`); süzgeç URL'de
 *   durur ki panel kutusu (`?kpi=<kod>&donem=`) ve geri tuşu aynı listeyi açsın.
 * - Durum düğmeleri sunucunun `gecisler` listesinden (makine + uç + izin)
 *   çizilir; ekran kendi geçiş kuralı yazmaz. Yetkisiz düğme görünmez.
 * - Faz A: kapanmış iş YENİDEN AÇILMAZ (M1.7); "Bağlı yeni iş" bu işe bağlı
 *   yeni iş açar ve iki yönlü bağ ayrıntıda görünür. Tamamlanan işe "Kalite
 *   onayı" verilir (D3.4/G4.6); işte çalışmış kişiye düğme kapalıdır (sunucu
 *   da 403 döner). Süzgeçte "Kalite onayı bekleyenler" vardır.
 * - Her yazma isteği ekranda görülen durumu (`beklenen_durum`) ya da sürümü
 *   taşır; başkası değiştirdiyse sunucu 409 döner, kayıt yeniden yüklenir ve
 *   kullanıcıya "yenilendi" denir (sessiz üzerine yazma yok).
 * - 375 px: tablo yatay kayar, ikincil sütunlar gizlenir, Drawer tam ekran.
 */
import {
  ClockCircleOutlined,
  EditOutlined,
  FilePdfOutlined,
  PlusOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  StopOutlined,
  UnorderedListOutlined,
  UserAddOutlined,
  UserOutlined,
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
  Popover,
  Radio,
  Row,
  Select,
  Space,
  Tabs,
  Tag,
  Timeline,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { BIRIM_ETIKETLERI, personelApi } from "../api/personel";
import { operasyonApi } from "../api/servisOperasyon";
import { gecenSure, servisZaman, ZAMAN_SORGULARI } from "../api/servisZaman";
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
  type BagliIsSatiri,
  type FormVerileri,
  type IsSatiri,
  type IsSuzgeci,
  type OnayGirdisi,
} from "../api/teknikServis";
import { useAuth } from "../auth/AuthContext";
import {
  beklemeNedeniAdi,
  durumGrubuBul,
  ONCELIK_ETIKETLERI,
  SERVIS_DURUM_GRUPLARI,
  SERVIS_KATEGORI_SIRASI,
  SERVIS_TUR_ETIKETLERI,
  servisDurumEtiketi,
  TAYIN,
  type FioriDurumGrubu,
} from "../fiori/etiketler";
import ListeRaporu, { type FioriEylem, type FioriKategori } from "../fiori/ListeRaporu";
import { useYeniParametresi } from "../fiori/useYeniParametresi";
import { yerelOku, yerelYaz } from "../fiori/yerelDepo";
import EkYukleyici from "../components/EkYukleyici";
import { ServisGozlemleri } from "../components/GozlemFormu";
import KayitGorevleri from "../components/KayitGorevleri";
import { PlanGecmisiSekmesi, ZamanSekmesi } from "../components/ServisIsSekmeleri";
import ImzaAlani, { tuvalPng } from "../components/ImzaAlani";
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
    // Ana Panel bağlantıları (2026-11-04 §4): şef süzgeci ve açılış tarih aralığı.
    sef_id: p.get("sef_id") ? Number(p.get("sef_id")) : undefined,
    bas: p.get("bas") ?? undefined,
    bit: p.get("bit") ?? undefined,
    musteri_id: p.get("musteri_id") ? Number(p.get("musteri_id")) : undefined,
    // Müşteri servis kartından tesis bazlı açık iş (TS-192) bağlantısı.
    adres_id: p.get("adres_id") ? Number(p.get("adres_id")) : undefined,
    siralama: p.get("siralama") ?? undefined,
    kalite: p.get("kalite") ?? undefined,
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

/** Durum rozeti — SAP dilinde etiket (rehber §5); ipucunda sunucunun adı. */
function DurumEtiketi({ kod, sozluk, bekleme }: { kod: string; sozluk?: FormVerileri; bekleme?: string | null }) {
  const ad = sozluk?.durumlar.find((d) => d.kod === kod)?.ad ?? kod;
  return (
    <Tag color={DURUM_RENKLERI[kod]} title={ad} style={{ fontWeight: 600 }}>
      {servisDurumEtiketi(kod, bekleme)}
    </Tag>
  );
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

// --- Tayin (API: atama) ------------------------------------------------------------------

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
      message.success(toplu ? `${isIdler.length} işe ekip tayin edildi` : "Ekip tayin edildi");
      if (uyarilar.length) {
        // TS-198 / E08-22: yetkinlik eksikliği tayini engellemez, yalnız uyarır.
        Modal.warning({
          title: TAYIN.yetkinlikUyarisiylaTayinEdildi,
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
      title={toplu ? `${TAYIN.topluTayin} (${isIdler.length} iş)` : TAYIN.ekipTayini}
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
          {BIRIM_ETIKETLERI[birim] ?? birim} biriminin tayin edilebilir saha personeli. Sorumlu
          teknisyen ya da şef olabilir; açık sayacı olan kişi ekipten çıkarılamaz.
        </Typography.Text>
        {toplu && (
          <Radio.Group
            value={mod}
            onChange={(e) => setMod(e.target.value)}
            options={[
              { value: "DEGISTIR", label: "Tayini bununla değiştir" },
              { value: "EKLE", label: "Mevcut tayine ekle" },
            ]}
          />
        )}
        <Select
          mode="multiple"
          style={{ width: "100%" }}
          placeholder="Tayin edilecek personeli seçin"
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
          placeholder="Sorumlu (teknisyen ya da şef)"
          value={sorumlu}
          onChange={setSorumlu}
          options={secenekler.filter((s) => kisiler.includes(s.value))}
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
  | "bagli_is"
  | "kalite"
  | "atama"
  | "onay";

/** Alt eylem çubuğundan gelen "detayı aç ve şu pencereyi göster" isteği. */
export interface PencereIstegi {
  pencere: "duzenle" | "iptal" | "kalite";
  /** Aynı pencere ikinci kez istenince de çalışsın diye artan sayaç. */
  n: number;
}

/** Bağlı iş bağlantısı: kapsam dışı iş maskeli (tıklanamaz). */
function BagliIsBaglantisi({ s, ac }: { s: BagliIsSatiri; ac?: (id: number) => void }) {
  if (s.kapsam_disi || s.id == null || !ac) return <Tag>{s.so_no}</Tag>;
  const id = s.id;
  return (
    <Button type="link" size="small" style={{ padding: 0 }} onClick={() => ac(id)}>
      {s.so_no}
    </Button>
  );
}

function IsDetayCekmecesi({
  id,
  sozluk,
  kapat,
  istek,
  isAc,
}: {
  id: number;
  sozluk?: FormVerileri;
  kapat: () => void;
  istek?: PencereIstegi | null;
  /** Başka bir işin ayrıntısını aç (bağlı iş bağlantıları). */
  isAc?: (id: number) => void;
}) {
  const { yetkili, kullanici } = useAuth();
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
        case "kalite":
          return teknikServisApi.kaliteOnayi(d.id, d.version, (v.not as string)?.trim() || undefined);
        case "bagli_is":
          return teknikServisApi.bagliYeniIs(d.id, {
            konu: (v.konu as string).trim(),
            aciklama: (v.aciklama as string)?.trim() || null,
            talep_kanali: v.talep_kanali as string,
            iletisim_ad: (v.iletisim_ad as string)?.trim() || null,
            iletisim_telefon: (v.iletisim_telefon as string)?.trim() || null,
            // Çok cihazlı eski işte yeni işin TEK cihazı seçilir (M1.6).
            ...(d.seriler.length > 1 ? { seriler: v.seri ? [v.seri as string] : [] } : {}),
          });
        default:
          throw new Error("Bilinmeyen işlem");
      }
    },
    onSuccess: (sonuc) => {
      if (pencere === "bagli_is" && sonuc && typeof sonuc === "object" && "so_no" in sonuc) {
        pencereKapat();
        yenile();
        // Rol testi B8: "yalnız kendi işleri" kapsamındaki kişi tayinsiz yeni işi
        // göremez (sunucu 404); ayrıntıyı açıp hata göstermek yerine söylenir.
        if (kullanici?.role.scope === "KENDI_ISLERI") {
          message.info(
            `Bağlı yeni iş açıldı: ${sonuc.so_no}. Tayin için şefe iletildi; size tayin edilince İşlerim'de görünür.`,
            6,
          );
          return;
        }
        message.success(`Bağlı yeni iş açıldı: ${sonuc.so_no}`);
        if (isAc) isAc(sonuc.id);
        return;
      }
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

  // Alt çubuktaki Düzenle / İptal: kayıt yüklenince ilgili pencere açılır;
  // geçiş sunucunun `gecisler` listesinde yoksa (yetki/durum) söylenir.
  const islenenIstek = useRef(0);
  useEffect(() => {
    if (!istek || !d || istek.n === islenenIstek.current) return;
    islenenIstek.current = istek.n;
    if (istek.pencere === "duzenle") {
      if (yetkili("servis.yaz") && d.status !== "IPTAL") pencereAc("duzenle");
      else message.warning("Bu iş düzenlenemez");
      return;
    }
    if (istek.pencere === "kalite") {
      if (d.kalite.verebilir) pencereAc("kalite");
      else message.warning(d.kalite.engel ?? "Bu işe kalite onayı verilemez");
      return;
    }
    const g = (d.gecisler ?? []).find((x) => x.uc === "iptal" && x.yetkili);
    if (g) pencereAc("iptal", g.hedef);
    else message.warning("Bu iş bu durumda iptal edilemez");
    // pencereAc her çizimde yeniden üretilir; istek sayacı tek kez işlenir.
  }, [istek, d]);

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
    bagli_is: "Bu işe bağlı yeni iş aç",
    kalite: "Kalite onayı",
  };
  const iliski = d?.iliskili_isler;
  const sureEksik = !!d && kapali && ["EKSIK", "KISMI"].includes(d.sure_durumu);
  const kanallar = (sozluk?.talep_kanallari ?? []).filter((k) => k.kod !== "BAKIM_OTOMATIK");
  const bagliIsBaslangic =
    d && pencere === "bagli_is"
      ? {
          konu: d.konu,
          talep_kanali: d.talep_kanali && d.talep_kanali !== "BAKIM_OTOMATIK" ? d.talep_kanali : undefined,
          iletisim_ad: d.iletisim_ad ?? undefined,
          iletisim_telefon: d.iletisim_telefon ?? undefined,
          seri: d.seriler.length > 1 ? undefined : d.seriler[0]?.seri_no,
        }
      : undefined;
  // Kayıtlı irtibat kişisinin telefonu varsa ad/telefon boş bırakılabilir.
  const irtibatTam = !!d?.irtibat?.full_name && !!d?.irtibat?.telefon;

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
            <DurumEtiketi kod={d.status} sozluk={sozluk} bekleme={d.bekleme?.neden_adi} />
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
                {g.uc === "sonuc" ? "Sonuç gir" : g.uc === "kapat" ? "Kapat" : g.uc === "iptal" ? "İptal et" : g.uc === "planla" ? "Planla" : g.ad}
              </Button>
            ))}
            {d.kalite.bekliyor && yetkili("servis.kalite_onay") && (
              <Tooltip title={d.kalite.verebilir ? "Tamamlanan işi kalite yönünden onayla" : d.kalite.engel}>
                <Button
                  icon={<SafetyCertificateOutlined />}
                  disabled={!d.kalite.verebilir}
                  onClick={() => pencereAc("kalite")}
                >
                  Kalite onayı
                </Button>
              </Tooltip>
            )}
            {yazabilir && kapali && (
              <Tooltip title="Kapanmış iş yeniden açılmaz; bu işe bağlı yeni iş açılır">
                <Button icon={<PlusOutlined />} onClick={() => pencereAc("bagli_is")}>
                  Bağlı yeni iş
                </Button>
              </Tooltip>
            )}
            {d.status === "BEKLEMEDE" && yazabilir && (
              <Button onClick={() => pencereAc("bekleme_bitir")}>Beklemeyi bitir</Button>
            )}
            {yazabilir && !["IPTAL"].includes(d.status) && (
              <Button onClick={() => pencereAc("duzenle")}>Düzenle</Button>
            )}
            {yetkili("servis.planla") && !kapali && (
              <Button icon={<UserAddOutlined />} onClick={() => pencereAc("atama")}>
                {d.ekip.length ? TAYIN.tayiniDegistir : TAYIN.tayinEt}
              </Button>
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
                      {iliski?.onceki && (
                        <Descriptions.Item label="Önceki iş (devamı olduğu)" span={2}>
                          <BagliIsBaglantisi s={iliski.onceki} ac={isAc} />
                        </Descriptions.Item>
                      )}
                      {!!iliski?.sonrakiler.length && (
                        <Descriptions.Item label="Bağlı yeni işler" span={2}>
                          <Space wrap size={4}>
                            {iliski.sonrakiler.map((s) => (
                              <BagliIsBaglantisi key={s.so_no} s={s} ac={isAc} />
                            ))}
                          </Space>
                        </Descriptions.Item>
                      )}
                      {(iliski?.ust || !!iliski?.alt.length) && (
                        <Descriptions.Item label="İlişkili işler" span={2}>
                          <Space wrap size={4}>
                            {iliski?.ust && <BagliIsBaglantisi s={iliski.ust} ac={isAc} />}
                            {iliski?.alt.map((s) => <BagliIsBaglantisi key={s.so_no} s={s} ac={isAc} />)}
                          </Space>
                        </Descriptions.Item>
                      )}
                      {(d.kalite.onay_at || d.kalite.bekliyor) && (
                        <Descriptions.Item label="Kalite onayı" span={2}>
                          {d.kalite.onay_at ? (
                            <Space orientation="vertical" size={0}>
                              <span>
                                <Tag color="green">Onaylandı</Tag>
                                {zaman(d.kalite.onay_at)} · {d.kalite.onaylayan?.ad ?? "—"}
                              </span>
                              {d.kalite.notu && <Typography.Text type="secondary">{d.kalite.notu}</Typography.Text>}
                            </Space>
                          ) : (
                            <Tag color="orange">Kalite onayı bekliyor</Tag>
                          )}
                        </Descriptions.Item>
                      )}
                      {sureEksik && (
                        <Descriptions.Item label="Süre kaydı" span={2}>
                          <Tag color="warning">Süre kaydı eksik</Tag>
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            Raporlarda "süre eksik" sayılır (0 saat değil).
                          </Typography.Text>
                        </Descriptions.Item>
                      )}
                      <Descriptions.Item label={TAYIN.tayinEdilenEkip} span={2}>
                        {d.ekip.length
                          ? d.ekip.map((e) => (
                              <Tag key={e.user_id} color={e.is_lead ? "blue" : undefined}>
                                {e.ad}
                                {e.is_lead ? " (sorumlu)" : ""}
                                {e.giris_acik ? "" : " · girişsiz"}
                              </Tag>
                            ))
                          : <Typography.Text type="warning">{TAYIN.tayinEdilmemis}</Typography.Text>}
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
                key: "tayin",
                label: `${TAYIN.tayin}${d.ekip.length ? ` (${d.ekip.length})` : ""}`,
                children: (
                  <Space orientation="vertical" style={{ width: "100%" }}>
                    {yetkili("servis.planla") && !kapali && (
                      <Button size="small" icon={<UserAddOutlined />} onClick={() => pencereAc("atama")}>
                        {d.ekip.length ? TAYIN.tayiniDegistir : TAYIN.tayinEt}
                      </Button>
                    )}
                    <List
                      size="small"
                      locale={{ emptyText: TAYIN.tayinEdilmemis }}
                      dataSource={d.ekip}
                      renderItem={(e) => (
                        <List.Item>
                          <Space orientation="vertical" size={0}>
                            <Space wrap size={4}>
                              <Typography.Text strong>{e.ad}</Typography.Text>
                              <Tag>{e.rol === "SEF" ? "Şef" : "Teknisyen"}</Tag>
                              {e.is_lead && <Tag color="blue">Sorumlu</Tag>}
                              {!e.giris_acik && <Tag>girişsiz</Tag>}
                            </Space>
                            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                              {TAYIN.tayinEdildi}: {zaman(e.assigned_at)}
                            </Typography.Text>
                          </Space>
                        </List.Item>
                      )}
                    />
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
          cancelText="Vazgeç"
          okText={pencere === "bagli_is" ? "Yeni işi aç" : pencere === "kalite" ? "Onayla" : "Kaydet"}
          okButtonProps={{ danger: pencere === "iptal" }}
          confirmLoading={islem.isPending}
          destroyOnHidden
        >
          <Form
            form={form}
            layout="vertical"
            initialValues={bagliIsBaslangic}
            onFinish={(v) => islem.mutate(v)}
          >
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
            {pencere === "kalite" && (
              <>
                <Alert
                  type="info"
                  showIcon
                  style={{ marginBottom: 12 }}
                  title="Tamamlanan işin kalite yönünden uygun olduğunu onaylarsınız. İşte tayinli ya da süre kaydı olan kişi onay veremez."
                />
                <Form.Item name="not" label="Kalite notu (isteğe bağlı)">
                  <Input.TextArea rows={2} maxLength={500} />
                </Form.Item>
              </>
            )}
            {pencere === "bagli_is" && (
              <>
                <Alert
                  type="info"
                  showIcon
                  style={{ marginBottom: 12 }}
                  title={`Kapanmış iş yeniden açılmaz. Müşteri, lokasyon ve cihaz ${d.so_no} işinden kopyalanır; yeni iş bu işe bağlanır.`}
                />
                {["PB", "ATOLYE"].includes(d.tur) && (
                  <Typography.Paragraph type="secondary">Yeni iş “Arıza” türünde açılır.</Typography.Paragraph>
                )}
                <Form.Item
                  name="konu"
                  label="Arıza tanımı"
                  rules={[{ required: true, whitespace: true, message: "Arıza tanımı zorunlu" }]}
                >
                  <Input maxLength={200} />
                </Form.Item>
                <Form.Item name="aciklama" label="Açıklama">
                  <Input.TextArea rows={2} maxLength={4000} />
                </Form.Item>
                <Form.Item
                  name="talep_kanali"
                  label="Talep kanalı"
                  rules={[{ required: true, message: "Talep kanalı seçin" }]}
                >
                  <Select options={kanallar.map((k) => ({ value: k.kod, label: k.ad }))} />
                </Form.Item>
                <Row gutter={8}>
                  <Col xs={24} sm={12}>
                    <Form.Item
                      name="iletisim_ad"
                      label="Talep eden kişi"
                      extra={irtibatTam ? `Boşsa kayıtlı irtibat: ${d.irtibat?.full_name}` : undefined}
                      rules={irtibatTam ? [] : [{ required: true, whitespace: true, message: "Ad zorunlu" }]}
                    >
                      <Input maxLength={120} />
                    </Form.Item>
                  </Col>
                  <Col xs={24} sm={12}>
                    <Form.Item
                      name="iletisim_telefon"
                      label="Telefon"
                      rules={irtibatTam ? [] : [{ required: true, whitespace: true, message: "Telefon zorunlu" }]}
                    >
                      <Input maxLength={20} />
                    </Form.Item>
                  </Col>
                </Row>
                {d.seriler.length > 1 ? (
                  <Form.Item
                    name="seri"
                    label="Cihaz (seri no)"
                    extra="Arıza işinde tek cihaz olur; her cihaz için ayrı iş açın."
                  >
                    <Select
                      allowClear
                      options={d.seriler.map((s) => ({ value: s.seri_no, label: s.seri_no }))}
                    />
                  </Form.Item>
                ) : (
                  <Typography.Paragraph type="secondary">
                    Cihaz: {d.seriler[0]?.seri_no ?? "—"}
                  </Typography.Paragraph>
                )}
              </>
            )}
            {pencere === "iptal" && (
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

// --- Fiori liste raporu ------------------------------------------------------------------

/** Kategori şeridi öğesi: hangi süzgeç alanlarını (tur / kpi) koyduğu ile. */
export interface ServisKategorisi extends FioriKategori {
  suzgec: Pick<IsSuzgeci, "tur" | "kpi">;
}

const TUMU_KATEGORISI: ServisKategorisi = {
  kod: "TUMU",
  ad: "TÜMÜ",
  renk: "mavi",
  ikon: <UnorderedListOutlined />,
  suzgec: {},
};

/** Servis İşleri şeridi: TÜMÜ + `SERVIS_TURLERI` (PB hariç, ayrı ekranda). */
export const SERVIS_KATEGORILERI: ServisKategorisi[] = [
  TUMU_KATEGORISI,
  ...SERVIS_KATEGORI_SIRASI.map((t) => ({
    kod: t,
    ad: SERVIS_TUR_ETIKETLERI[t].ad,
    renk: SERVIS_TUR_ETIKETLERI[t].renk,
    suzgec: { tur: t },
  })),
];

const KATEGORI_ALANLARI = ["tur", "kpi"] as const;

const gunu = (d?: string | null) => (d ? dayjs(d).format("DD/MM/YYYY") : "—");
const saati = (d?: string | null) => (d ? dayjs(d).format("HH:mm:ss") : "—");
const KAPALI_DURUMLAR = ["TAMAMLANDI", "KAPATILDI", "IPTAL"];

/** Personel sütunu: tayin edilen ekip özeti + Tayin Et kısayolu. */
function PersonelDugmesi({ satir, onTayin }: { satir: IsSatiri; onTayin?: () => void }) {
  const bos = !satir.sorumlu && !satir.ekip_sayisi;
  return (
    <Popover
      trigger="click"
      title={TAYIN.tayinEdilenEkip}
      content={
        <Space orientation="vertical" size={4} style={{ maxWidth: 240 }}>
          {bos ? (
            <Typography.Text type="warning">{TAYIN.tayinEdilmemis}</Typography.Text>
          ) : (
            <>
              <span>Sorumlu: {satir.sorumlu?.ad ?? "—"}</span>
              <Typography.Text type="secondary">{satir.ekip_sayisi} kişi tayin edildi</Typography.Text>
            </>
          )}
          {onTayin && !KAPALI_DURUMLAR.includes(satir.status) && (
            <Button size="small" type="primary" icon={<UserAddOutlined />} onClick={onTayin}>
              {bos ? TAYIN.tayinEt : TAYIN.tayiniDegistir}
            </Button>
          )}
        </Space>
      }
    >
      <button
        type="button"
        className={`fl-personel${bos ? " bos" : ""}`}
        aria-label={`${satir.so_no} ${TAYIN.tayinEdilenEkip}`}
      >
        <UserOutlined />
      </button>
    </Popover>
  );
}

/** Tek iş için tayin: mevcut ekip sunucudan okunur, pencere onunla açılır. */
function TekliTayin({ satir, kapat }: { satir: IsSatiri; kapat: (yenile: boolean) => void }) {
  const ekip = useQuery({ queryKey: ["servis-is-ekip", satir.id], queryFn: () => teknikServisApi.ekip(satir.id) });
  const mevcut = useMemo(
    () => (ekip.data ?? []).map((e) => ({ user_id: e.user_id, rol: e.rol, is_lead: e.is_lead })),
    [ekip.data],
  );
  if (ekip.isLoading) return null;
  return (
    <AtamaPenceresi
      birim={satir.birim}
      isIdler={[satir.id]}
      mevcut={mevcut}
      acik
      kapat={() => kapat(false)}
      bitti={() => kapat(true)}
    />
  );
}

/** Seçili işte canlı sayaç (sunucu saatine göre, saniyelik). */
function CanliSayac({ soNo, baslangic }: { soNo: string | null; baslangic: string }) {
  const [, setTik] = useState(0);
  useEffect(() => {
    const t = window.setInterval(() => setTik((x) => x + 1), 1000);
    return () => window.clearInterval(t);
  }, []);
  return (
    <span className="fl-sayac" title="Açık sayaç">
      <ClockCircleOutlined />
      {soNo ?? ""} {gecenSure(baslangic)}
    </span>
  );
}

export interface ServisIsListesiProps {
  kategoriler?: ServisKategorisi[];
  /** Hiçbir kategori uymazsa uygulanacak kategori (Planlı Bakım: PLANLI). */
  varsayilanKategori?: string;
  durumGruplari?: FioriDurumGrubu[];
  /** Açık ayrıntı (Drawer) kimliği; null = kapalı. */
  detayId: number | null;
  detayAc: (id: number | null) => void;
  /** Süzgeç URL'ye yazılırken korunacak parametreler (ör. `sekme`). */
  sabitParametreler?: Record<string, string>;
  /** İş no sarı rozetle mi (fotoğraf 0–6) düz mü (fotoğraf 9) gösterilsin. */
  noRozeti?: boolean;
  /** Yeni kayıt düğmesi (Planlı Bakım'da PB elle açılmaz). */
  yeniKayit?: boolean;
  /**
   * Verilirse kişisel süzgeçler (durum, öncelik, sıralama, onay kutuları)
   * kullanıcı başına bu adla hatırlanır (KARARLAR 2026-11-04 §5).
   */
  hatirlaAnahtari?: string;
}

/**
 * Hatırlanan süzgeç alanları. Birim/tür/kpi HATIRLANMAZ: onlar menüden
 * seçilen "nereye baktığım"dır (Güvenlik › Kurulum); hatırlansaydı "Tüm
 * Servis İşleri" tıklaması eski birimi açardı.
 */
const HATIRLANAN_SUZGECLER = [
  "durum",
  "oncelik",
  "siralama",
  "atanmamis",
  "kapali_dahil",
  "kalite",
  "teknisyen_id",
] as const;
const hatirlananAlan = (k: string) => (HATIRLANAN_SUZGECLER as readonly string[]).includes(k);

/**
 * Boş liste: ne yapılacağını söyler (KARARLAR 2026-11-04 §5). Süzgeç varsa
 * temizleme, yoksa ilk kaydı açma yolunu gösterir.
 */
function BosListeMesaji({
  suzgecli,
  yeniAcabilir,
  temizle,
  yeni,
}: {
  suzgecli: boolean;
  yeniAcabilir: boolean;
  temizle: () => void;
  yeni: () => void;
}) {
  return (
    <Empty
      image={Empty.PRESENTED_IMAGE_SIMPLE}
      description={
        suzgecli
          ? "Bu süzgeçle eşleşen servis işi yok. Süzgeci temizleyin ya da durum çubuğundan başka bir durum seçin."
          : "Burada henüz servis işi yok."
      }
    >
      <Space wrap style={{ justifyContent: "center" }}>
        {suzgecli && (
          <Button size="small" onClick={temizle}>
            Süzgeci temizle
          </Button>
        )}
        {yeniAcabilir && (
          <Button size="small" type="primary" icon={<PlusOutlined />} onClick={yeni}>
            Yeni servis işi aç
          </Button>
        )}
      </Space>
    </Empty>
  );
}

export function ServisIsListesi({
  kategoriler = SERVIS_KATEGORILERI,
  varsayilanKategori,
  durumGruplari = SERVIS_DURUM_GRUPLARI,
  detayId,
  detayAc,
  sabitParametreler,
  noRozeti = true,
  yeniKayit = true,
  hatirlaAnahtari,
}: ServisIsListesiProps) {
  const { yetkili, kullanici } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [arama, setArama] = useSearchParams();
  const ekran = Grid.useBreakpoint();
  const urlSuzgeci = useMemo(() => suzgecOku(arama), [arama]);
  const [sayfa, setSayfa] = useState(1);
  const [secili, setSecili] = useState<number[]>([]);
  const [cokluSecim, setCokluSecim] = useState(false);
  const [suzgecAcik, setSuzgecAcik] = useState(false);
  const [yeniAcik, setYeniAcik] = useState(false);
  const [topluAtamaAcik, setTopluAtamaAcik] = useState(false);
  const [tekliTayin, setTekliTayin] = useState<IsSatiri | null>(null);
  const [ziyaretAcik, setZiyaretAcik] = useState(false);
  const [istek, setIstek] = useState<PencereIstegi | null>(null);
  const [aramaMetni, setAramaMetni] = useState(urlSuzgeci.q ?? "");
  const [hatirlandi, setHatirlandi] = useState(false);

  // Kişisel süzgeç hatırlama: ilk açılışta adreste kişisel süzgeç (ve panel
  // kpi'si) yoksa son kullanılan eklenir; sonra her değişiklik kaydedilir.
  const ilkAcilis = useRef(true);
  useEffect(() => {
    if (!hatirlaAnahtari || !kullanici) return;
    const ad = `suzgec.${hatirlaAnahtari}`;
    if (ilkAcilis.current) {
      ilkAcilis.current = false;
      const kisiselVar = HATIRLANAN_SUZGECLER.some((k) => arama.has(k));
      const kayitli = yerelOku<string>(kullanici.id, ad, "");
      if (!kisiselVar && !arama.has("kpi") && kayitli) {
        const p = new URLSearchParams(arama);
        new URLSearchParams(kayitli).forEach((v, k) => {
          if (hatirlananAlan(k)) p.append(k, v);
        });
        if (p.toString() !== arama.toString()) {
          setHatirlandi(true);
          setArama(p, { replace: true });
          return;
        }
      }
    }
    const kayit = new URLSearchParams();
    arama.forEach((v, k) => {
      if (hatirlananAlan(k)) kayit.append(k, v);
    });
    yerelYaz(kullanici.id, ad, kayit.toString());
  }, [arama, hatirlaAnahtari, kullanici, setArama]);

  // Kategori: URL'deki tur/kpi'ye birebir uyan öğe; yoksa varsayılan uygulanır.
  const kategoriUyar = (k: ServisKategorisi, s: IsSuzgeci) =>
    KATEGORI_ALANLARI.every((a) => (k.suzgec[a] ?? undefined) === (s[a] ?? undefined));
  const uyanKategori = kategoriler.find((k) => kategoriUyar(k, urlSuzgeci));
  const varsayilan =
    !uyanKategori && varsayilanKategori && !urlSuzgeci.tur && !urlSuzgeci.kpi
      ? kategoriler.find((k) => k.kod === varsayilanKategori)
      : undefined;
  const suzgec = useMemo<IsSuzgeci>(
    () => (varsayilan ? { ...urlSuzgeci, ...varsayilan.suzgec } : urlSuzgeci),
    [urlSuzgeci, varsayilan],
  );
  const seciliKategori = (uyanKategori ?? varsayilan)?.kod;

  const sozluk = useQuery({
    queryKey: ["servis-form-verileri"],
    queryFn: teknikServisApi.formVerileri,
    staleTime: 5 * 60_000,
  });
  const liste = useQuery({
    queryKey: ["servis-isleri", suzgec, sayfa],
    queryFn: () => teknikServisApi.liste(suzgec, SAYFA_BOYU, (sayfa - 1) * SAYFA_BOYU),
  });

  // Saat Aç / Saat Kapa: mevcut zaman uçları (TS-070…078); sunucu saati tek kaynak.
  const sayacYetkili = yetkili("zaman.yaz");
  const benim = useQuery({
    queryKey: ["zaman-benim"],
    queryFn: servisZaman.benim,
    enabled: sayacYetkili,
    refetchInterval: 60_000,
  });
  const acikBolum = benim.data?.acik_bolum ?? null;
  const zamanTazele = () => {
    for (const k of ZAMAN_SORGULARI) void qc.invalidateQueries({ queryKey: k });
    void qc.invalidateQueries({ queryKey: ["servis-isleri"] });
    void qc.invalidateQueries({ queryKey: ["is-zamani"] });
    void qc.invalidateQueries({ queryKey: ["servis-is"] });
  };
  const saatAc = useMutation({
    mutationFn: (r: IsSatiri) =>
      r.tur === "ATOLYE"
        ? servisZaman.baslat({ is_id: r.id, eylem: "DIGER", faaliyet: "ATOLYE" })
        : servisZaman.baslat({ is_id: r.id, eylem: "SAHAYA_VARDIM" }),
    onSuccess: (_, r) => {
      message.success(`${r.so_no} için saat açıldı`);
      zamanTazele();
    },
    onError: (e: Error) => {
      message.error(e.message);
      zamanTazele();
    },
  });
  const saatKapa = useMutation({
    mutationFn: () => {
      if (!acikBolum) throw new Error("Açık sayaç yok");
      return servisZaman.bitir(acikBolum);
    },
    onSuccess: () => {
      message.success("Saat kapatıldı");
      zamanTazele();
    },
    onError: (e: Error) => {
      message.error(e.message);
      zamanTazele();
    },
  });

  const suzgecDegistir = (yeni: IsSuzgeci) => {
    const p = suzgecYaz(yeni);
    for (const [k, v] of Object.entries(sabitParametreler ?? {})) p.set(k, v);
    setArama(p);
    setSayfa(1);
    setSecili([]);
  };

  const kategoriSec = (kod: string) => {
    const k = kategoriler.find((x) => x.kod === kod);
    if (!k) return;
    const yeni: IsSuzgeci = { ...urlSuzgeci };
    for (const a of KATEGORI_ALANLARI) delete yeni[a];
    if (urlSuzgeci.kpi && !k.suzgec.kpi) delete yeni.donem;
    suzgecDegistir({ ...yeni, ...k.suzgec });
  };

  const kayitlar = liste.data?.kayitlar ?? [];
  const seciliSatirlar = kayitlar.filter((r) => secili.includes(r.id));
  const seciliBirimler = new Set(seciliSatirlar.map((r) => r.birim));
  const tek = seciliSatirlar.length === 1 ? seciliSatirlar[0] : null;
  const tekKapali = tek ? KAPALI_DURUMLAR.includes(tek.status) : false;
  const aktarabilir = yetkili("servis.gor", "servis_rapor.disaaktar");
  const durumAdi = (k: string) => sozluk.data?.durumlar.find((d) => d.kod === k)?.ad ?? k;
  const beklemeAdi = (k: string | null) => beklemeNedeniAdi(k, sozluk.data?.bekleme_nedenleri);
  const banaAit = !!kullanici && suzgec.teknisyen_id === kullanici.id;
  const seciliGrup = durumGrubuBul(durumGruplari, suzgec.durum);
  const planlayabilir = yetkili("servis.planla");
  const yazabilir = yetkili("servis.yaz");
  // Yeni iş: `servis.yaz` ya da yalnız KURULUM açan satış destek
  // (`servis.kurulum_ac`, KARARLAR 2026-11-04 §6.5; tür formda daralır).
  const acabilir = yazabilir || yetkili("servis.kurulum_ac");
  // "+ Hızlı oluştur" → `?yeni=1`: yeni iş penceresi açılır.
  useYeniParametresi(() => setYeniAcik(true), yeniKayit && acabilir);
  const secebilir = yazabilir || planlayabilir;
  const ac = (id: number) => detayAc(id);

  const kaliteYetkili = yetkili("servis.kalite_onay");
  const tekKaliteBekliyor =
    !!tek && ["TAMAMLANDI", "KAPATILDI"].includes(tek.status) && !tek.kalite_onay_at;

  const ekSuzgecSayisi = [
    suzgec.birim,
    suzgec.oncelik,
    suzgec.atanmamis,
    suzgec.kapali_dahil,
    suzgec.kalite,
    suzgec.siralama,
    suzgec.durum?.length && !seciliGrup ? 1 : undefined,
    suzgec.musteri_id,
    suzgec.adres_id,
  ].filter(Boolean).length;

  const sutunlar: ColumnsType<IsSatiri> = [
    {
      title: "Durum",
      dataIndex: "status",
      width: 150,
      align: "center",
      render: (v: string, r) => (
        <button
          type="button"
          className={`fl-durum${v === "IPTAL" ? " olumsuz" : KAPALI_DURUMLAR.includes(v) ? " kapali" : ""}`}
          title={durumAdi(v)}
          onClick={() => ac(r.id)}
        >
          {servisDurumEtiketi(v, beklemeAdi(r.aktif_bekleme))}
        </button>
      ),
    },
    {
      title: "İş No",
      dataIndex: "so_no",
      width: 170,
      align: "center",
      render: (v: string, r) => (
        <>
          <span
            className={noRozeti ? "fl-no-rozet" : "fl-no-duz"}
            role="link"
            tabIndex={0}
            onClick={() => ac(r.id)}
            onKeyDown={(e) => e.key === "Enter" && ac(r.id)}
          >
            {v}
          </span>
          {ONCELIK_ETIKETLERI[r.oncelik] && (
            <span className={`fl-alt-not ${r.oncelik === "KRITIK" ? "kritik" : "uyari"}`}>
              {ONCELIK_ETIKETLERI[r.oncelik]}
            </span>
          )}
        </>
      ),
    },
    {
      title: "Bildirim\nTarihi",
      key: "tarih",
      width: 100,
      align: "center",
      responsive: ["sm"],
      render: (_, r) => gunu(r.reported_at ?? r.created_at),
    },
    {
      title: "Bildirim\nSaati",
      key: "saat",
      width: 90,
      align: "center",
      responsive: ["md"],
      render: (_, r) => saati(r.reported_at ?? r.created_at),
    },
    {
      title: "Açıklama",
      dataIndex: "konu",
      width: 320,
      render: (v: string, r) => (
        <button type="button" className="fl-aciklama" title={v} onClick={() => ac(r.id)}>
          {v}
        </button>
      ),
    },
    {
      // Rol testi 1 B13: müşteri ayrı ve varsayılan görünür sütun (telefon
      // genişliği hariç); müşterisiz açılan iş "girilmedi" diye işaretlenir.
      title: "Müşteri",
      key: "musteri",
      width: 200,
      responsive: ["sm"],
      render: (_, r) =>
        r.musteri?.title || r.customer_name_raw ? (
          <span className="fl-kucuk" style={{ fontWeight: 600 }} title={r.musteri?.title ?? r.customer_name_raw ?? ""}>
            {r.musteri?.title ?? r.customer_name_raw}
          </span>
        ) : (
          <span className="fl-kucuk-gri">Müşteri girilmedi</span>
        ),
    },
    {
      title: "Ekipman",
      dataIndex: "seriler",
      width: 130,
      align: "center",
      responsive: ["lg"],
      render: (v: string[]) => (
        <span className="fl-kucuk">{v.slice(0, 2).join(", ") + (v.length > 2 ? ` +${v.length - 2}` : "")}</span>
      ),
    },
    {
      title: "Mahal",
      key: "mahal",
      width: 200,
      align: "center",
      responsive: ["md"],
      render: (_, r) =>
        r.lokasyon ? (
          <span className="fl-kucuk">{[r.lokasyon.ad, r.lokasyon.il].filter(Boolean).join(" · ") || "—"}</span>
        ) : (
          <span className="fl-kucuk-gri">—</span>
        ),
    },
    {
      title: "Sistem",
      key: "sistem",
      width: 140,
      align: "center",
      responsive: ["lg"],
      render: (_, r) => (
        <>
          <span className="fl-kucuk">{BIRIM_ETIKETLERI[r.birim] ?? r.birim}</span>
          <span className="fl-kucuk-gri">
            {SERVIS_TUR_ETIKETLERI[r.tur]?.ad ?? sozluk.data?.turler.find((t) => t.kod === r.tur)?.ad ?? r.tur}
          </span>
        </>
      ),
    },
    {
      title: "Personel",
      key: "personel",
      width: 80,
      align: "center",
      render: (_, r) => (
        <PersonelDugmesi satir={r} onTayin={planlayabilir ? () => setTekliTayin(r) : undefined} />
      ),
    },
    {
      title: "Bildiren Kişi/Tel",
      key: "bildiren",
      width: 160,
      align: "center",
      responsive: ["xl"],
      render: (_, r) =>
        r.iletisim_ad || r.iletisim_telefon ? (
          <span className="fl-kucuk-gri">{[r.iletisim_ad, r.iletisim_telefon].filter(Boolean).join(" / ")}</span>
        ) : (
          <span className="fl-kucuk-gri">/</span>
        ),
    },
  ];

  const listeMenusu = [
    ...(aktarabilir ? [{ key: "excel", label: "Excel'e aktar" }] : []),
    ...(secebilir
      ? [{ key: "coklu", label: cokluSecim ? "Tekli seçime dön" : "Çoklu seçim (toplu işlem)" }]
      : []),
    ...(yazabilir ? [{ key: "ziyaret", label: "Ziyaret onayı", disabled: !secili.length }] : []),
    { key: "ziyaret_formu", label: "Ziyaret formu (PDF)", disabled: !secili.length },
    { key: "temizle", label: "Seçimi temizle", disabled: !secili.length },
    { type: "divider" as const },
    { key: "yenile", label: "Listeyi yenile" },
  ];
  const listeMenusuTikla = (k: string) => {
    if (k === "excel") window.open(teknikServisApi.excelYolu(suzgec), "_blank");
    else if (k === "coklu") {
      setCokluSecim(!cokluSecim);
      setSecili((s) => (cokluSecim ? s.slice(0, 1) : s));
    } else if (k === "ziyaret") setZiyaretAcik(true);
    else if (k === "ziyaret_formu") window.open(teknikServisApi.ziyaretFormuYolu(secili), "_blank");
    else if (k === "temizle") setSecili([]);
    else if (k === "yenile") void liste.refetch();
  };

  const tayinEt = () => {
    if (secili.length > 1) setTopluAtamaAcik(true);
    else if (tek) setTekliTayin(tek);
  };

  const eylemler: FioriEylem[] = [
    {
      anahtar: "liste",
      ad: "Liste",
      menu: listeMenusu,
      onMenu: listeMenusuTikla,
    },
    {
      anahtar: "saat_ac",
      ad: "Saat Aç",
      gizli: !sayacYetkili,
      ipucu: acikBolum ? `Açık sayaç var (${acikBolum.so_no ?? ""}); önce Saat Kapa` : "Seçili işte sayacı başlat",
      devreDisi: !tek || tekKapali || tek.status === "BEKLEMEDE" || !!acikBolum,
      yukleniyor: saatAc.isPending,
      onClick: () => tek && saatAc.mutate(tek),
    },
    {
      anahtar: "saat_kapa",
      ad: "Saat Kapa",
      gizli: !sayacYetkili,
      ipucu: acikBolum ? `${acikBolum.so_no ?? ""} sayacını bitir` : "Açık sayaç yok",
      devreDisi: !acikBolum,
      yukleniyor: saatKapa.isPending,
      onClick: () => saatKapa.mutate(),
    },
    {
      anahtar: "tayin",
      ad: secili.length > 1 ? TAYIN.topluTayin : TAYIN.tayinEt,
      ikon: <UserAddOutlined />,
      yalnizIkon: true,
      gizli: !planlayabilir,
      ipucu:
        secili.length > 1 && seciliBirimler.size !== 1
          ? "Toplu tayin tek birimin işleriyle yapılır"
          : secili.length > 1
            ? `${TAYIN.topluTayin} (${secili.length} iş)`
            : TAYIN.tayinEt,
      devreDisi: !secili.length || (secili.length > 1 ? seciliBirimler.size !== 1 : tekKapali),
      onClick: tayinEt,
    },
    {
      anahtar: "iptal",
      ad: "İptal Et",
      ikon: <StopOutlined />,
      yalnizIkon: true,
      tehlikeli: true,
      gizli: !yazabilir,
      devreDisi: !tek || tekKapali,
      onClick: () => {
        if (!tek) return;
        setIstek({ pencere: "iptal", n: Date.now() });
        ac(tek.id);
      },
    },
    {
      anahtar: "kalite",
      ad: "Kalite Onayı",
      ikon: <SafetyCertificateOutlined />,
      yalnizIkon: true,
      gizli: !kaliteYetkili,
      ipucu: !tek
        ? "Kalite onayı: bir iş seçin"
        : tek.kalite_onay_at
          ? "Kalite onayı verilmiş"
          : tekKaliteBekliyor
            ? "Kalite onayı ver"
            : "Kalite onayı iş tamamlandıktan sonra verilir",
      devreDisi: !tekKaliteBekliyor,
      onClick: () => {
        if (!tek) return;
        setIstek({ pencere: "kalite", n: Date.now() });
        ac(tek.id);
      },
    },
    {
      anahtar: "duzenle",
      ad: "Düzenle",
      ikon: <EditOutlined />,
      yalnizIkon: true,
      gizli: !yazabilir,
      devreDisi: !tek || tek.status === "IPTAL",
      onClick: () => {
        if (!tek) return;
        setIstek({ pencere: "duzenle", n: Date.now() });
        ac(tek.id);
      },
    },
    {
      anahtar: "pdf",
      ad: secili.length > 1 ? "Ziyaret formu (PDF)" : "Servis formu (PDF)",
      ikon: <FilePdfOutlined />,
      yalnizIkon: true,
      devreDisi: !secili.length,
      href: tek
        ? teknikServisApi.servisFormuYolu(tek.id)
        : secili.length
          ? teknikServisApi.ziyaretFormuYolu(secili)
          : undefined,
    },
  ];

  const sagEylemler: FioriEylem[] = [
    {
      anahtar: "yeni",
      ad: "Yeni Kayıt",
      ikon: <PlusOutlined />,
      vurgulu: true,
      kisalt: true,
      gizli: !yeniKayit || !acabilir,
      onClick: () => setYeniAcik(true),
    },
  ];

  const suzgecPaneli = (
    <Row gutter={[8, 8]}>
      <Col xs={12} md={6}>
        <Select
          allowClear
          style={{ width: "100%" }}
          placeholder="Birim"
          value={suzgec.birim}
          onChange={(v) => suzgecDegistir({ ...urlSuzgeci, birim: v })}
          options={(sozluk.data?.birimler ?? []).map((b) => ({ value: b.kod, label: b.ad }))}
        />
      </Col>
      <Col xs={12} md={6}>
        <Select
          allowClear
          mode="multiple"
          maxTagCount={1}
          style={{ width: "100%" }}
          placeholder="Durum (ayrıntılı)"
          value={suzgec.durum}
          onChange={(v) => suzgecDegistir({ ...urlSuzgeci, durum: v.length ? v : undefined })}
          options={(sozluk.data?.durumlar ?? []).map((d) => ({
            value: d.kod,
            label: servisDurumEtiketi(d.kod),
          }))}
        />
      </Col>
      <Col xs={12} md={6}>
        <Select
          allowClear
          style={{ width: "100%" }}
          placeholder="Öncelik"
          value={suzgec.oncelik}
          onChange={(v) => suzgecDegistir({ ...urlSuzgeci, oncelik: v })}
          options={Object.entries(ONCELIK_ADLARI).map(([k, v]) => ({ value: k, label: v }))}
        />
      </Col>
      <Col xs={12} md={6}>
        <Select
          style={{ width: "100%" }}
          value={suzgec.siralama ?? "yeni"}
          onChange={(v) => suzgecDegistir({ ...urlSuzgeci, siralama: v === "yeni" ? undefined : v })}
          options={[
            { value: "yeni", label: "En yeni" },
            { value: "eski", label: "En eski" },
            { value: "oncelik", label: "Önceliğe göre" },
            { value: "no", label: "İş numarası" },
          ]}
        />
      </Col>
      <Col xs={24}>
        <Space wrap>
          <Checkbox
            checked={!!suzgec.atanmamis}
            onChange={(e) => suzgecDegistir({ ...urlSuzgeci, atanmamis: e.target.checked || undefined })}
          >
            {TAYIN.tayinEdilmemis}
          </Checkbox>
          <Checkbox
            checked={!!suzgec.kapali_dahil}
            onChange={(e) => suzgecDegistir({ ...urlSuzgeci, kapali_dahil: e.target.checked || undefined })}
          >
            Eski kapalı işler dahil
          </Checkbox>
          <Checkbox
            checked={suzgec.kalite === "BEKLEYEN"}
            onChange={(e) => suzgecDegistir({ ...urlSuzgeci, kalite: e.target.checked ? "BEKLEYEN" : undefined })}
          >
            Kalite onayı bekleyenler
          </Checkbox>
          {ekSuzgecSayisi > 0 && (
            <Button
              size="small"
              type="link"
              onClick={() =>
                suzgecDegistir({
                  q: urlSuzgeci.q,
                  tur: urlSuzgeci.tur,
                  kpi: urlSuzgeci.kpi,
                  donem: urlSuzgeci.donem,
                  teknisyen_id: urlSuzgeci.teknisyen_id,
                  durum: seciliGrup ? urlSuzgeci.durum : undefined,
                })
              }
            >
              Süzgeci temizle
            </Button>
          )}
        </Space>
      </Col>
    </Row>
  );

  const ustBilgi =
    suzgec.kpi && !uyanKategori?.suzgec.kpi && !varsayilan?.suzgec.kpi ? (
      <Space wrap>
        <Tag
          color="blue"
          closable
          onClose={(e) => {
            e.preventDefault();
            suzgecDegistir({ ...urlSuzgeci, kpi: undefined, donem: undefined });
          }}
        >
          Panel: {KPI_ADLARI[suzgec.kpi] ?? suzgec.kpi}
          {suzgec.donem
            ? ` · ${
                DONEMLER.find((d) => d.kod === suzgec.donem)?.ad ?? donemAraligiMetni(suzgec.donem) ?? suzgec.donem
              }`
            : ""}
        </Tag>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          Liste panel kutusunun süzgeciyle açıldı (sayı = liste).
        </Typography.Text>
      </Space>
    ) : hatirlandi && HATIRLANAN_SUZGECLER.some((k) => arama.has(k)) ? (
      <Space wrap>
        <Tag
          color="gold"
          closable
          onClose={(e) => {
            e.preventDefault();
            setHatirlandi(false);
            const yeni: IsSuzgeci = { ...urlSuzgeci };
            for (const k of HATIRLANAN_SUZGECLER) delete yeni[k];
            suzgecDegistir(yeni);
          }}
        >
          Son kullandığınız süzgeç uygulandı
        </Tag>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          Kaldırmak için etiketi kapatın.
        </Typography.Text>
      </Space>
    ) : suzgec.musteri_id || suzgec.adres_id ? (
      <Tag
        closable
        onClose={(e) => {
          e.preventDefault();
          suzgecDegistir({ ...urlSuzgeci, musteri_id: undefined, adres_id: undefined });
        }}
      >
        Müşteri/tesis süzgeci
      </Tag>
    ) : null;

  return (
    <>
      <ListeRaporu<IsSatiri>
        kategoriler={kategoriler}
        seciliKategori={seciliKategori}
        onKategori={kategoriSec}
        kayitSayisi={liste.data?.toplam}
        ustSag={
          <Input.Search
            allowClear
            size="small"
            style={{ width: ekran.sm ? 260 : 180 }}
            placeholder="İş no, seri, konu, müşteri…"
            value={aramaMetni}
            onChange={(e) => setAramaMetni(e.target.value)}
            onSearch={(q) => suzgecDegistir({ ...urlSuzgeci, q: q.trim() || undefined })}
          />
        }
        durumCubugu={{
          gruplar: durumGruplari,
          secili: seciliGrup,
          onSec: (kod) =>
            suzgecDegistir({
              ...urlSuzgeci,
              durum: kod ? durumGruplari.find((g) => g.kod === kod)?.durumlar : undefined,
            }),
          banaAit,
          onBanaAit: kullanici
            ? (v) => suzgecDegistir({ ...urlSuzgeci, teknisyen_id: v ? kullanici.id : undefined })
            : undefined,
          onYenile: () => void liste.refetch(),
          yenileniyor: liste.isFetching,
          onSuzgec: () => setSuzgecAcik(!suzgecAcik),
          suzgecAcik,
          suzgecSayisi: ekSuzgecSayisi,
        }}
        suzgecPaneli={suzgecPaneli}
        ustBilgi={ustBilgi}
        sutunlar={sutunlar}
        veri={kayitlar}
        satirAnahtari="id"
        yukleniyor={liste.isFetching}
        bosMetin={
          liste.isError ? (
            (liste.error as Error).message
          ) : (
            <BosListeMesaji
              suzgecli={ekSuzgecSayisi > 0 || !!suzgec.durum?.length || !!suzgec.q || !!suzgec.kpi || !!suzgec.tur}
              yeniAcabilir={yeniKayit && acabilir}
              temizle={() => {
                setAramaMetni("");
                setHatirlandi(false);
                // Menüden gelen birim korunur (Güvenlik › Kurulum → Güvenlik).
                suzgecDegistir({ birim: urlSuzgeci.birim });
              }}
              yeni={() => setYeniAcik(true)}
            />
          )
        }
        // Gizlenen (responsive) sütunlar kadar daralır: 375 px'te yalnız
        // durum, no, açıklama ve personel kalır, tablo kendi içinde kayar.
        scrollX={ekran.xl ? 1540 : ekran.lg ? 1380 : ekran.md ? 1210 : ekran.sm ? 1060 : 720}
        secimModu={cokluSecim ? "coklu" : "tek"}
        secili={secili}
        onSecim={(k) => setSecili(k as number[])}
        onSatirAc={(r) => ac(r.id)}
        sayfalama={{
          sayfa,
          boyut: SAYFA_BOYU,
          toplam: liste.data?.toplam ?? 0,
          onChange: (s) => {
            setSayfa(s);
            setSecili([]);
          },
        }}
        eylemler={eylemler}
        sagEylemler={sagEylemler}
        eylemBilgisi={
          acikBolum ? <CanliSayac soNo={acikBolum.so_no} baslangic={acikBolum.started_at} /> : undefined
        }
      />

      <Drawer
        open={yeniAcik}
        title="Yeni servis işi"
        width={ekran.md ? 720 : "100%"}
        onClose={() => setYeniAcik(false)}
        destroyOnHidden
      >
        <ServisIsFormu
          formVerileri={sozluk.data}
          varsayilan={{ birim: suzgec.birim, tur: suzgec.tur }}
          onKaydedildi={(d) => {
            setYeniAcik(false);
            void qc.invalidateQueries({ queryKey: ["servis-isleri"] });
            detayAc(d.id);
          }}
          onVazgec={() => setYeniAcik(false)}
        />
      </Drawer>

      {detayId != null && (
        <IsDetayCekmecesi
          key={detayId}
          id={detayId}
          sozluk={sozluk.data}
          istek={istek}
          isAc={(x) => {
            setIstek(null);
            detayAc(x);
          }}
          kapat={() => {
            setIstek(null);
            detayAc(null);
          }}
        />
      )}

      {tekliTayin && (
        <TekliTayin
          key={tekliTayin.id}
          satir={tekliTayin}
          kapat={(yenile) => {
            setTekliTayin(null);
            if (yenile) {
              void qc.invalidateQueries({ queryKey: ["servis-isleri"] });
              void qc.invalidateQueries({ queryKey: ["servis-is", tekliTayin.id] });
              void qc.invalidateQueries({ queryKey: ["servis-is-ekip", tekliTayin.id] });
            }
          }}
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
    </>
  );
}

// --- Sayfa ----------------------------------------------------------------------------------

export default function ServisIsleriPage() {
  const git = useNavigate();
  const { id } = useParams();
  const [arama] = useSearchParams();
  const yolEki = arama.toString() ? `?${arama.toString()}` : "";
  return (
    <ServisIsListesi
      hatirlaAnahtari="servis-isleri"
      detayId={id ? Number(id) : null}
      detayAc={(x) => git(x ? `/servis-isleri/${x}${yolEki}` : `/servis-isleri${yolEki}`)}
    />
  );
}
