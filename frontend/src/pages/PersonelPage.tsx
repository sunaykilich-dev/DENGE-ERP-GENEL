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
 *
 * İşten çıkış (TS-165, E13-09): Drawer'daki düğme önce ÖNİZLEME açar (açık
 * işler, açık sayaç, oturumlar, eğitim kayıtları), onayla tek işlemde uygulanır.
 * Açık sayaç kapatılmaz; uyarı ve görev kartıyla yöneticiye düşer. Ayrılmış
 * personelin KVKK anonimleştirmesi yalnız `kvkk.yonet` ile ve elle yapılır.
 *
 * Süreli vekâlet (TS-213): `vekalet.ver` sahibi kart üzerinden kendi kalıcı
 * izinlerinin bir kısmını en fazla 30 günlüğüne devreder; işten çıkışta kişiye
 * verilen ve kişinin verdiği vekâletler sunucuda kendiliğinden biter.
 *
 * "Ekibim" (TS-199, E13-17): doğrudan bağlı çalışan personel; kapsam
 * süzgecinden SONRA uygulanır, yetki genişletmez. Yönetici `personel.yaz` ile
 * kartta seçilir; kapsamınız dışındaki yönetici "Kapsam dışı kişi" görünür.
 */
import { PlusOutlined, ReadOutlined, TeamOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnsType } from "antd/es/table";
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
  Form,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, type ApiError } from "../api/client";
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
import { useSirket } from "../auth/SirketContext";
import OzlukDosyasi, { OzlukBekleyenler } from "../components/OzlukDosyasi";
import {
  Aciklama,
  AltNot,
  DurumBaglantisi,
  Kucuk,
  KucukGri,
  NoRozeti,
  TUMU_KATEGORISI,
  buyuk,
} from "../fiori/ListeOgeleri";
import SicilNumaralaPenceresi from "../components/SicilNumaralaPenceresi";
import ListeRaporu from "../fiori/ListeRaporu";
import KutucukPano from "../fiori/KutucukPano";

const SAYFA_BOYU = 25;

const birimSecenekleri = BIRIM_KODLARI.map((k) => ({ value: k, label: BIRIM_ETIKETLERI[k] }));
const sahaSecenekleri = [
  { value: "ATANABILIR", label: "Sahaya tayin edilebilir (şef/teknisyen/stajyer)" },
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

// --- İşten çıkış ve KVKK (TS-165; sunucu: `api/personel.py`) ---------------------

const AYRILIS_NEDENLERI: Record<string, string> = {
  ISTIFA: "İstifa",
  FESIH: "Fesih",
  EMEKLILIK: "Emeklilik",
  SOZLESME_BITIMI: "Sözleşme bitimi",
  DIGER: "Diğer",
};

interface CikisIsi {
  id: number;
  so_no: string;
  durum: string;
  birim: string;
  sorumlu: boolean;
  sayac_acik: boolean;
}

interface CikisOnizleme {
  personel_id: number;
  kendisi: boolean;
  ust_yetkili: boolean;
  son_admin: boolean;
  zaten_ayrildi: boolean;
  aktif_isler: CikisIsi[];
  kapsam_disi_is_sayisi: number;
  acik_sayac: { bolum_id: number; so_no: string | null; baslangic: string; faaliyet: string } | null;
  acik_oturum_sayisi: number;
  mobilite_acik_is_sayisi: number;
  egitim: {
    acik_plan: number;
    acik_duzeltici_faaliyet: number;
    sorumlu_oldugu_acik_faaliyet: number;
  };
  uyarilar: string[];
  gorev_karti_acilacak: boolean;
}

interface CikisSonucu {
  personel_id: number;
  cikarilan_isler: string[];
  ekipte_kalan_isler: string[];
  acik_sayac_bolum_id: number | null;
  gorev_karti_id: number | null;
  kapanan_oturum: number;
}

interface CikisFormu {
  ayrilis_tarihi: Dayjs;
  ayrilis_nedeni: string;
}

const cikisApi = {
  onizleme: (id: number) => api.get<CikisOnizleme>(`/api/personel/${id}/cikis-onizleme`),
  uygula: (id: number, g: { ayrilis_tarihi: string; ayrilis_nedeni: string; version: number }) =>
    api.post<CikisSonucu>(`/api/personel/${id}/cikis`, g),
  anonimlestir: (id: number, gerekce: string) =>
    api.post<{ temizlenen_alanlar: string[]; denetim_satiri: number }>(
      `/api/personel/${id}/anonimlestir`,
      { gerekce, onay: true },
    ),
};

/**
 * Doğrudan yönetici (TS-199). Yazma `personel.yaz`; aday listesi kapsamınızdaki
 * çalışan personeldir. Döngü (kişinin astını yönetici seçmek) sunucuda 400 verir.
 * Yönetici ilişkisi yetki VERMEZ; "Ekibim" yalnız süzgeçtir.
 */
function YoneticiAlani({ p, yazabilir, bitti }: { p: Personel; yazabilir: boolean; bitti: () => void }) {
  const { message } = App.useApp();
  const [arama, setArama] = useState("");
  const adaylar = useQuery({
    queryKey: ["personel-yonetici-aday", arama],
    queryFn: () => personelApi.liste({ q: arama || undefined, durum: "CALISIYOR" }, 20, 0),
    enabled: yazabilir,
  });
  const yaz = useMutation({
    mutationFn: (id: number | null) => personelApi.yoneticiYaz(p.id, id, p.version),
    onSuccess: () => {
      message.success("Yönetici kaydedildi");
      bitti();
    },
    onError: (e: ApiError) => void message.error(hataMesaji(e)),
  });
  if (!yazabilir) return <>{p.yonetici?.ad ?? "—"}</>;
  const secenekler = (adaylar.data?.kayitlar ?? [])
    .filter((k) => k.id !== p.id)
    .map((k) => ({ value: k.id, label: k.full_name }));
  if (p.yonetici?.id != null && !secenekler.some((s) => s.value === p.yonetici!.id)) {
    secenekler.unshift({ value: p.yonetici.id, label: p.yonetici.ad });
  }
  return (
    <Select
      allowClear
      showSearch
      filterOption={false}
      style={{ width: "100%", maxWidth: 320 }}
      placeholder={p.yonetici?.id === null ? p.yonetici.ad : "Yönetici seçin"}
      value={p.yonetici?.id ?? undefined}
      loading={adaylar.isFetching || yaz.isPending}
      disabled={yaz.isPending}
      onSearch={setArama}
      onChange={(v?: number) => yaz.mutate(v ?? null)}
      options={secenekler}
      notFoundContent={adaylar.isFetching ? "Aranıyor…" : "Kişi bulunamadı"}
    />
  );
}

// --- Süreli vekâlet (TS-213; sunucu: `api/vekalet.py`) ----------------------------

interface Vekalet {
  personel_id: number;
  izin: string;
  izin_aciklama: string;
  baslangic_at: string;
  bitis_at: string;
  gerekce: string | null;
  veren_id: number | null;
  veren_adi: string | null;
  durum: "BASLAMADI" | "YURURLUKTE" | "SONA_ERDI";
}

interface VekaletFormu {
  izinler: string[];
  aralik: [Dayjs, Dayjs];
  gerekce: string;
}

const VEKALET_AZAMI_GUN = 30;
const VEKALET_DURUM_RENGI: Record<Vekalet["durum"], string> = {
  YURURLUKTE: "green",
  BASLAMADI: "blue",
  SONA_ERDI: "default",
};
const VEKALET_DURUM_ADI: Record<Vekalet["durum"], string> = {
  YURURLUKTE: "yürürlükte",
  BASLAMADI: "başlamadı",
  SONA_ERDI: "sona erdi",
};

/**
 * Personel kartındaki "Vekâletler" bloğu (`vekalet.ver`). Veren yalnız kendi
 * kalıcı izinlerinden, vekâlete kapalı olmayanları (maliyet, hak ediş, sistem
 * ...) en fazla 30 günlüğüne verebilir; seçenek listesi sunucudan gelir.
 * Verme ve iptalde alıcının açık oturumları düşer. İptal: veren ya da yönetici.
 */
function VekaletAlani({ p, verebilir }: { p: Personel; verebilir: boolean }) {
  const { message } = App.useApp();
  const { kullanici } = useAuth();
  const qc = useQueryClient();
  const [acik, setAcik] = useState(false);
  const [form] = Form.useForm<VekaletFormu>();

  const liste = useQuery({
    queryKey: ["vekalet", p.id],
    queryFn: () => api.get<Vekalet[]>(`/api/vekalet/${p.id}`),
  });
  const secenekler = useQuery({
    queryKey: ["vekalet-verilebilir"],
    queryFn: () => api.get<{ kod: string; aciklama: string }[]>("/api/vekalet/verilebilir"),
    enabled: acik,
    staleTime: 60_000,
  });
  const tazele = () => void qc.invalidateQueries({ queryKey: ["vekalet", p.id] });

  const ver = useMutation({
    mutationFn: (v: VekaletFormu) =>
      api.post<Vekalet[]>(`/api/vekalet/${p.id}`, {
        izinler: v.izinler,
        baslangic_at: v.aralik[0].toISOString(),
        bitis_at: v.aralik[1].toISOString(),
        gerekce: v.gerekce,
      }),
    onSuccess: () => {
      message.success("Vekâlet verildi; kişinin açık oturumları sonlandı.");
      setAcik(false);
      form.resetFields();
      tazele();
    },
    onError: (e: ApiError) => void message.error(hataMesaji(e)),
  });
  const iptal = useMutation({
    mutationFn: (izin: string) => api.post<Vekalet[]>(`/api/vekalet/${p.id}/iptal`, { izin }),
    onSuccess: () => {
      message.success("Vekâlet iptal edildi");
      tazele();
    },
    onError: (e: ApiError) => void message.error(hataMesaji(e)),
  });

  return (
    <Card
      size="small"
      title="Vekâletler"
      extra={
        verebilir && (
          <Button size="small" onClick={() => setAcik(true)}>
            Vekâlet ver
          </Button>
        )
      }
    >
      <Table
        rowKey={(v) => `${v.izin}-${v.bitis_at}`}
        size="small"
        pagination={false}
        loading={liste.isLoading}
        dataSource={liste.data ?? []}
        locale={{ emptyText: "Vekâlet yok" }}
        scroll={{ x: 520 }}
        columns={[
          {
            title: "İzin",
            render: (_, v: Vekalet) => (
              <Tooltip title={v.izin_aciklama}>
                <span className="mono">{v.izin}</span>
              </Tooltip>
            ),
          },
          {
            title: "Süre",
            render: (_, v: Vekalet) =>
              `${dayjs(v.baslangic_at).format("DD.MM.YYYY HH:mm")} – ${dayjs(v.bitis_at).format("DD.MM.YYYY HH:mm")}`,
          },
          {
            title: "Durum",
            width: 110,
            render: (_, v: Vekalet) => (
              <Tag color={VEKALET_DURUM_RENGI[v.durum]}>{VEKALET_DURUM_ADI[v.durum]}</Tag>
            ),
          },
          { title: "Veren", dataIndex: "veren_adi", width: 130, ellipsis: true },
          {
            title: "",
            width: 80,
            render: (_, v: Vekalet) =>
              v.durum !== "SONA_ERDI" &&
              (v.veren_id === kullanici?.id || kullanici?.role.code === "ADMIN") ? (
                <Button
                  size="small"
                  danger
                  loading={iptal.isPending}
                  onClick={() => iptal.mutate(v.izin)}
                >
                  İptal
                </Button>
              ) : null,
          },
        ]}
      />
      <Modal
        title={`Vekâlet ver: ${p.full_name}`}
        open={acik}
        onCancel={() => setAcik(false)}
        onOk={() => form.submit()}
        okText="Vekâlet ver"
        cancelText="Vazgeç"
        confirmLoading={ver.isPending}
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ aralik: [dayjs(), dayjs().add(7, "day").endOf("day")] }}
          onFinish={(v) => ver.mutate(v)}
        >
          <Form.Item
            name="izinler"
            label="Devredilecek izinler"
            rules={[{ required: true, message: "En az bir izin seçin" }]}
            extra="Yalnız sizde kalıcı olarak bulunan ve vekâlete açık izinler listelenir."
          >
            <Select
              mode="multiple"
              loading={secenekler.isLoading}
              optionFilterProp="label"
              options={(secenekler.data ?? []).map((s) => ({
                value: s.kod,
                label: `${s.kod} — ${s.aciklama}`,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="aralik"
            label="Başlangıç – bitiş"
            rules={[
              { required: true, message: "Süre seçin" },
              {
                validator: (_, d?: [Dayjs, Dayjs]) =>
                  !d || d[1].diff(d[0], "day", true) <= VEKALET_AZAMI_GUN
                    ? Promise.resolve()
                    : Promise.reject(new Error(`En fazla ${VEKALET_AZAMI_GUN} gün`)),
              },
            ]}
          >
            <DatePicker.RangePicker
              showTime={{ format: "HH:mm" }}
              format="DD.MM.YYYY HH:mm"
              style={{ width: "100%" }}
            />
          </Form.Item>
          <Form.Item
            name="gerekce"
            label="Gerekçe"
            rules={[{ required: true, min: 5, max: 300, message: "5–300 karakter" }]}
          >
            <Input placeholder="ör. Yıllık izin süresince planlama vekâleti" maxLength={300} />
          </Form.Item>
          <Typography.Text type="secondary">
            Vekâlet verilince kişinin açık oturumları sonlanır; süre dolunca izin kendiliğinden düşer.
          </Typography.Text>
        </Form>
      </Modal>
    </Card>
  );
}

export default function PersonelPage() {
  const { yetkili } = useAuth();
  const qc = useQueryClient();
  const { message, modal } = App.useApp();
  const yazabilir = yetkili("personel.yaz");
  // Uyarı zili "Onay bekleyen özlük belgesi" → `/personel?ozluk=bekleyen`.
  const [arama] = useSearchParams();

  const [suzgec, setSuzgec] = useState<PersonelSuzgeci>({ durum: "CALISIYOR" });
  const [sayfa, setSayfa] = useState(1);
  const [seciliId, setSeciliId] = useState<number | null>(null);
  const [sicilAcik, setSicilAcik] = useState(false);
  const [suzgecAcik, setSuzgecAcik] = useState(false);
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
    onError: (e: ApiError) => void message.error(hataMesaji(e)),
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
    onError: (e: ApiError) => void message.error(hataMesaji(e)),
  });

  const aktiflestir = useMutation({
    mutationFn: (id: number) => personelApi.aktiflestir(id),
    onSuccess: (r) => {
      message.success(r.mesaj);
      tazele();
    },
    onError: (e: ApiError) => void message.error(hataMesaji(e)),
  });

  const cikisYetkisi = yetkili("personel.cikis");
  const kvkkYetkisi = yetkili("kvkk.yonet");
  const [cikisAcik, setCikisAcik] = useState(false);
  const [anonimAcik, setAnonimAcik] = useState(false);
  const [anonimGerekce, setAnonimGerekce] = useState("");
  const [anonimOnay, setAnonimOnay] = useState(false);
  const [cikisForm] = Form.useForm<CikisFormu>();

  const onizleme = useQuery({
    queryKey: ["personel-cikis-onizleme", seciliId],
    queryFn: () => cikisApi.onizleme(seciliId!),
    enabled: cikisAcik && seciliId != null,
  });

  const cikis = useMutation({
    mutationFn: (v: CikisFormu) =>
      cikisApi.uygula(secili.data!.id, {
        ayrilis_tarihi: v.ayrilis_tarihi.format("YYYY-MM-DD"),
        ayrilis_nedeni: v.ayrilis_nedeni,
        version: secili.data!.version,
      }),
    onSuccess: (r) => {
      setCikisAcik(false);
      cikisForm.resetFields();
      tazele();
      modal.info({
        title: "İşten çıkış uygulandı",
        content: (
          <Space orientation="vertical">
            <span>Personel ve giriş hesabı kapatıldı; {r.kapanan_oturum} oturum sonlandı.</span>
            <span>
              Ekipten çıkarılan açık işler:{" "}
              {r.cikarilan_isler.length ? r.cikarilan_isler.join(", ") : "yok"}
            </span>
            {r.ekipte_kalan_isler.length > 0 && (
              <span>
                Açık sayaç nedeniyle ekipte kalan: {r.ekipte_kalan_isler.join(", ")} — sayaç
                kapatılınca ekipten çıkarın.
              </span>
            )}
            {r.gorev_karti_id != null && <span>Görev panosunda inceleme kartı açıldı.</span>}
          </Space>
        ),
      });
    },
    onError: (e: ApiError) => void message.error(hataMesaji(e)),
  });

  const anonimlestir = useMutation({
    mutationFn: () => cikisApi.anonimlestir(secili.data!.id, anonimGerekce.trim()),
    onSuccess: (r) => {
      message.success(
        `Kişisel veriler anonimleştirildi (${r.temizlenen_alanlar.length} alan, ${r.denetim_satiri} denetim satırı).`,
      );
      setAnonimAcik(false);
      setAnonimGerekce("");
      setAnonimOnay(false);
      tazele();
    },
    onError: (e: ApiError) => void message.error(hataMesaji(e)),
  });

  const o = onizleme.data;
  const cikisEngelli = !o || o.kendisi || o.son_admin || o.zaten_ayrildi;

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
          <Form.Item
            name="sicil_no"
            label="Sicil no"
            rules={[{ max: 30 }]}
            extra="Boş bırakılırsa sıradaki numara verilir."
          >
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
            extra="Tayin listeleri buna bakar (şef/teknisyen/stajyer)."
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

  const kayitlar = liste.data?.kayitlar ?? [];
  const { aktifBirimler } = useSirket();
  // Rol testi B-13: şerit yalnız etkin şirketin birimlerini gösterir.
  const kategoriler = [
    TUMU_KATEGORISI,
    ...birimSecenekleri.filter((b) => !aktifBirimler || aktifBirimler.has(b.value)).map((b) => ({ kod: b.value, ad: buyuk(b.label), ipucu: b.label, renk: "yesil" as const, ikon: <TeamOutlined /> })),
    { kod: "__YOK", ad: "BİRİMSİZ", renk: "kirmizi" as const, ikon: <TeamOutlined /> },
  ];
  const sutunlar: ColumnsType<Personel> = [
    {
      title: "Durum",
      key: "durum",
      width: 130,
      align: "center",
      render: (_, r) => (
        <DurumBaglantisi
          metin={r.calisiyor ? "ÇALIŞIYOR" : "AYRILDI"}
          ton={r.calisiyor ? undefined : "kapali"}
          onClick={() => kartiAc(r)}
          alt={
            <>
              {!r.giris_acik && <AltNot>GİRİŞ YOK</AltNot>}
              {r.acik_sayac_var && <AltNot tur="uyari">SAAT AÇIK</AltNot>}
            </>
          }
        />
      ),
    },
    {
      title: "Sicil",
      dataIndex: "sicil_no",
      width: 110,
      align: "center",
      render: (v: string | null, r) => (v ? <NoRozeti no={v} onClick={() => kartiAc(r)} /> : <KucukGri />),
    },
    { title: "Ad Soyad", dataIndex: "full_name", width: 220, render: (v: string, r) => <Aciklama metin={v} onClick={() => kartiAc(r)} /> },
    { title: "Ünvan", dataIndex: "unvan", width: 160, align: "center", responsive: ["md"], render: (v: string | null) => <Kucuk>{v}</Kucuk> },
    {
      title: "Saha Rolü",
      dataIndex: "saha_rolu",
      width: 110,
      align: "center",
      render: (v: string | null, r) =>
        v ? (
          <Kucuk>{SAHA_ROLU_ETIKETLERI[v] ?? v}</Kucuk>
        ) : r.saha_rolu_bekleniyor ? (
          <Tag color="gold">girilmemiş</Tag>
        ) : (
          <KucukGri>—</KucukGri>
        ),
    },
    {
      title: "Sistem",
      key: "birimler",
      width: 200,
      align: "center",
      responsive: ["sm"],
      render: (_, r: Personel) =>
        r.birimler.length ? (
          <Kucuk>
            {r.birimler.map((b) => `${BIRIM_ETIKETLERI[b.birim] ?? b.birim}${b.birincil && r.birimler.length > 1 ? " ★" : ""}`).join(" · ")}
          </Kucuk>
        ) : (
          <Tag color="gold">birimsiz</Tag>
        ),
    },
    {
      title: "Yönetici",
      key: "yonetici",
      width: 160,
      align: "center",
      responsive: ["lg"],
      render: (_, r: Personel) => <KucukGri>{r.yonetici?.ad}</KucukGri>,
    },
  ];
  const ekSuzgecSayisi = [suzgec.saha_rolu, suzgec.giris].filter(Boolean).length;

  return (
    <div className="fm-sayfa">
      {(ozet.data ?? []).length > 0 && (
        <KutucukPano ekran="personel">
          {(ozet.data ?? []).map((k) => (
            <div
              key={k.kod}
              className="fl-kutucuk"
              role="button"
              tabIndex={0}
              onClick={() => suzgecDegistir(k.suzgec)}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && suzgecDegistir(k.suzgec)}
            >
              <div className="fl-kutucuk-baslik">{k.baslik}</div>
              <div className="fl-kutucuk-dip">
                <span className="fl-kutucuk-ikon">
                  <TeamOutlined />
                </span>
                <span className="fl-kutucuk-sayi">{k.adet.toLocaleString("tr-TR")}</span>
              </div>
            </div>
          ))}
        </KutucukPano>
      )}

      {/* 2026-11-23: personelin kendi yüklediği, İK onayı bekleyen özlük belgeleri. */}
      {yetkili("ik_belge.yonet") && <OzlukBekleyenler acik={arama.get("ozluk") === "bekleyen"} />}
      <SicilNumaralaPenceresi acik={sicilAcik} onKapat={() => setSicilAcik(false)} />
      <ListeRaporu<Personel>
        kategoriBasligi="Birim"
        kategoriler={kategoriler}
        seciliKategori={suzgec.birimsiz ? "__YOK" : (suzgec.birim ?? TUMU_KATEGORISI.kod)}
        onKategori={(k) =>
          suzgecDegistir({
            ...suzgec,
            birim: k !== TUMU_KATEGORISI.kod && k !== "__YOK" ? k : undefined,
            birimsiz: k === "__YOK" || undefined,
          })
        }
        kayitSayisi={liste.data?.toplam}
        ustSag={
          <Input.Search
            placeholder="Ad, sicil, ünvan"
            allowClear
            size="small"
            style={{ width: 200 }}
            onSearch={(q) => suzgecDegistir({ ...suzgec, q: q || undefined })}
          />
        }
        durumCubugu={{
          gruplar: [
            { kod: "CALISIYOR", ad: "ÇALIŞIYOR", durumlar: ["CALISIYOR"] },
            { kod: "AYRILDI", ad: "AYRILDI", durumlar: ["AYRILDI"] },
          ],
          secili: suzgec.durum,
          onSec: (v) => suzgecDegistir({ ...suzgec, durum: v }),
          banaAit: !!suzgec.ekibim,
          onBanaAit: (v) => suzgecDegistir({ ...suzgec, ekibim: v || undefined }),
          banaAitIpucu: "Ekibim — yalnız size doğrudan bağlı çalışan personel (süzgeçtir)",
          onYenile: () => void liste.refetch(),
          yenileniyor: liste.isFetching,
          onSuzgec: () => setSuzgecAcik(!suzgecAcik),
          suzgecAcik,
          suzgecSayisi: ekSuzgecSayisi,
        }}
        suzgecPaneli={
          <Space wrap>
            <Select
              placeholder="Saha rolü"
              allowClear
              style={{ width: 240 }}
              value={suzgec.saha_rolu}
              options={sahaSecenekleri}
              onChange={(v?: string) => suzgecDegistir({ ...suzgec, saha_rolu: v })}
            />
            <Select
              placeholder="Giriş"
              allowClear
              style={{ width: 140 }}
              value={suzgec.giris}
              options={[
                { value: "ACIK", label: "Giriş açık" },
                { value: "KAPALI", label: "Girişsiz" },
              ]}
              onChange={(v?: string) => suzgecDegistir({ ...suzgec, giris: v })}
            />
          </Space>
        }
        sutunlar={sutunlar}
        veri={kayitlar}
        satirAnahtari="id"
        yukleniyor={liste.isFetching}
        bosMetin={liste.isError ? (liste.error as ApiError).message : "Veri yok"}
        scrollX={1000}
        onSatirAc={kartiAc}
        sayfalama={{ sayfa, boyut: SAYFA_BOYU, toplam: liste.data?.toplam ?? 0, onChange: setSayfa }}
        eylemler={[
          {
            anahtar: "liste",
            ad: "Liste",
            menu: [
              ...(yetkili("servis_rapor.disaaktar") ? [{ key: "excel", label: "Excel'e aktar" }] : []),
              { key: "yenile", label: "Listeyi yenile" },
              // KARARLAR 2026-11-20 §8: şirket geçmişine göre sicil numarası.
              ...(yetkili("personel.yaz") ? [{ key: "sicil", label: "Sicil numarala" }] : []),
            ],
            onMenu: (k) =>
              k === "excel"
                ? window.open(personelApi.excelYolu(suzgec), "_blank")
                : k === "sicil"
                  ? setSicilAcik(true)
                  : void liste.refetch(),
          },
        ]}
        sagEylemler={[
          {
            anahtar: "yeni",
            ad: "Yeni Personel",
            ikon: <PlusOutlined />,
            vurgulu: true,
            kisalt: true,
            gizli: !yazabilir,
            onClick: () => setYeniAcik(true),
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
              {yetkili("egitim.gor") && (
                <Descriptions.Item label="Eğitim">
                  {/* UI/UX I5: Eğitim'deki "Bireysel Gelişim" sekmesi kaldırıldı; kişi kartı buradan açılır. */}
                  <Link to={`/egitim/${p.id}`}>
                    <ReadOutlined /> Eğitim kartını aç
                  </Link>
                </Descriptions.Item>
              )}
              <Descriptions.Item label="Yönetici">
                <YoneticiAlani p={p} yazabilir={yazabilir} bitti={tazele} />
              </Descriptions.Item>
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

            {(cikisYetkisi && p.calisiyor) || (kvkkYetkisi && !p.calisiyor) ? (
              <Space wrap>
                {cikisYetkisi && p.calisiyor && (
                  <Button danger onClick={() => setCikisAcik(true)}>
                    İşten çıkış
                  </Button>
                )}
                {kvkkYetkisi && !p.calisiyor && (
                  <Button danger onClick={() => setAnonimAcik(true)}>
                    KVKK anonimleştir
                  </Button>
                )}
              </Space>
            ) : null}

            {yetkili("vekalet.ver") && (
              <VekaletAlani p={p} verebilir={p.calisiyor && p.giris_acik} />
            )}

            {/* Özlük dosyası (2026-11-20): İK yükler, türleri yönetir. */}
            {yetkili("ik_belge.yonet") && (
              <div>
                <Typography.Title level={5} style={{ marginBottom: 8 }}>
                  Özlük dosyası
                </Typography.Title>
                <OzlukDosyasi kisiId={p.id} />
              </div>
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
                  {p.saha_rolu
                    ? SAHA_ROLU_ETIKETLERI[p.saha_rolu] ?? p.saha_rolu
                    : p.saha_rolu_bekleniyor
                      ? "girilmemiş"
                      : "—"}
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

      <Modal
        title={p ? `İşten çıkış: ${p.full_name}` : "İşten çıkış"}
        open={cikisAcik}
        width={720}
        onCancel={() => setCikisAcik(false)}
        onOk={() => cikisForm.submit()}
        okText="Çıkışı uygula"
        okButtonProps={{ danger: true, disabled: cikisEngelli }}
        cancelText="Vazgeç"
        confirmLoading={cikis.isPending}
        destroyOnHidden
      >
        {onizleme.isLoading && <Typography.Text type="secondary">Önizleme hazırlanıyor…</Typography.Text>}
        {onizleme.isError && (
          <Alert type="error" showIcon title={(onizleme.error as ApiError).message} />
        )}
        {o && (
          <Space orientation="vertical" style={{ width: "100%" }} size="middle">
            {o.uyarilar.map((u) => (
              <Alert key={u} type="warning" showIcon title={u} />
            ))}
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="Açık oturum">{o.acik_oturum_sayisi} (sonlandırılacak)</Descriptions.Item>
              <Descriptions.Item label="Açık sayaç">
                {o.acik_sayac ? (
                  <span>
                    {o.acik_sayac.so_no ?? "kapsam dışı iş"} · {o.acik_sayac.faaliyet} ·{" "}
                    {dayjs(o.acik_sayac.baslangic).format("DD.MM.YYYY HH:mm")}{" "}
                    <Tag color="orange">kapatılmaz, inceleme bekler</Tag>
                  </span>
                ) : (
                  "yok"
                )}
              </Descriptions.Item>
              <Descriptions.Item label="Eğitim">
                {o.egitim.acik_plan} açık plan · {o.egitim.acik_duzeltici_faaliyet} açık düzeltici
                faaliyet · sorumlu olduğu {o.egitim.sorumlu_oldugu_acik_faaliyet} açık faaliyet
              </Descriptions.Item>
              {o.mobilite_acik_is_sayisi > 0 && (
                <Descriptions.Item label="Mobilite iş emri">
                  {o.mobilite_acik_is_sayisi} açık (bu akış değiştirmez)
                </Descriptions.Item>
              )}
            </Descriptions>
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={o.aktif_isler}
              locale={{ emptyText: "Açık servis işinde tayini yok" }}
              title={() =>
                `Açık servis işleri (${o.aktif_isler.length}${
                  o.kapsam_disi_is_sayisi ? ` + kapsamınız dışında ${o.kapsam_disi_is_sayisi}` : ""
                })`
              }
              columns={[
                { title: "İş", dataIndex: "so_no", className: "mono" },
                { title: "Durum", dataIndex: "durum" },
                { title: "Birim", dataIndex: "birim", render: (b: string) => BIRIM_ETIKETLERI[b] ?? b },
                {
                  title: "Sonuç",
                  render: (_, r: CikisIsi) =>
                    r.sayac_acik ? (
                      <Tag color="orange">sayaç açık: ekipte kalır</Tag>
                    ) : (
                      <Tag color={r.sorumlu ? "red" : undefined}>
                        ekipten çıkar{r.sorumlu ? " (sorumluydu)" : ""}
                      </Tag>
                    ),
                },
              ]}
            />
            {o.gorev_karti_acilacak && (
              <Typography.Text type="secondary">
                Görev panosunda “İşten çıkış incelemesi” kartı açılacak. İş durumları değişmez.
              </Typography.Text>
            )}
            <Form
              form={cikisForm}
              layout="vertical"
              initialValues={{ ayrilis_tarihi: dayjs() }}
              onFinish={(v) => cikis.mutate(v)}
            >
              <Row gutter={12}>
                <Col xs={24} sm={12}>
                  <Form.Item name="ayrilis_tarihi" label="Ayrılış tarihi" rules={[{ required: true }]}>
                    <DatePicker format="DD.MM.YYYY" style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item
                    name="ayrilis_nedeni"
                    label="Ayrılış nedeni"
                    rules={[{ required: true, message: "Neden seçin" }]}
                  >
                    <Select
                      options={Object.entries(AYRILIS_NEDENLERI).map(([k, v]) => ({ value: k, label: v }))}
                    />
                  </Form.Item>
                </Col>
              </Row>
            </Form>
          </Space>
        )}
      </Modal>

      <Modal
        title="KVKK anonimleştirme"
        open={anonimAcik}
        onCancel={() => setAnonimAcik(false)}
        onOk={() => anonimlestir.mutate()}
        okText="Anonimleştir"
        okButtonProps={{ danger: true, disabled: !anonimOnay || anonimGerekce.trim().length < 5 }}
        cancelText="Vazgeç"
        confirmLoading={anonimlestir.isPending}
        destroyOnHidden
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Alert
            type="warning"
            showIcon
            title="Geri alınamaz"
            description="Personel notu, e-posta ve ayrılış nedeni silinir; denetim kayıtlarındaki değerler maskelenir. Kayıt ve ad, iş geçmişi için kalır."
          />
          <Input
            placeholder="Gerekçe (ör. başvuru numarası)"
            maxLength={300}
            value={anonimGerekce}
            onChange={(e) => setAnonimGerekce(e.target.value)}
          />
          <Checkbox checked={anonimOnay} onChange={(e) => setAnonimOnay(e.target.checked)}>
            İşlemin geri alınamayacağını biliyorum
          </Checkbox>
        </Space>
      </Modal>
    </div>
  );
}
