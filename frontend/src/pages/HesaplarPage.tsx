import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Segmented,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ADRES_TURU_ETIKET, anaVeriApi, AnaVeriHatasi, type Lokasyon } from "../api/anaVeri";
import { api, type ApiError } from "../api/client";
import EkYukleyici from "../components/EkYukleyici";
import LokasyonPenceresi from "../components/LokasyonPenceresi";
import MontajTarifeleri from "../components/MontajTarifeleri";
import { useAuth } from "../auth/AuthContext";
import KayitGorevleri from "../components/KayitGorevleri";

interface Hesap {
  id: number;
  title: string;
  roller: string[];
  is_musteri: boolean;
  is_bayi: boolean;
  is_montaj_noktasi: boolean;
  is_tedarikci: boolean;
  parent_dealer_id: number | null;
  parent_dealer_title: string | null;
  tax_no: string | null;
  tax_office: string | null;
  iban: string | null;
  email: string | null;
  phone: string | null;
  region: string | null;
  segment: string | null;
  notes: string | null;
  is_active: boolean;
  version: number;
  eksik_alanlar: string[];
  /** Servis ekranından hızlı açılan müşteri doğrulanana kadar false. */
  is_verified: boolean;
  dis_referans: string | null;
}

/** VKN başka aktif hesapta varsa sunucunun 409 gövdesi. */
interface VknCakismasi {
  degerler: Record<string, unknown>;
  mevcut: { id: number; title: string }[];
  kapsam_disi: number;
}

interface Kisi {
  id: number;
  ad: string;
  gorev: string | null;
  telefon: string | null;
  eposta: string | null;
  birincil: boolean;
}

interface Kart {
  account_id: number;
  kisiler: Kisi[];
  siparisler: {
    id: number;
    order_no: string;
    order_date: string;
    status: string;
    currency: string;
    grand_total: string;
  }[];
  cihazlar: {
    device_id: number;
    kimlik: string | null;
    urun: string;
    status: string;
    plaka: string | null;
  }[];
  araclar: {
    id: number;
    plaka: string;
    sase: string | null;
    marka: string | null;
    model: string | null;
  }[];
  cihaz_sayisi: number;
  arac_sayisi: number;
  abonelikler: {
    id: number;
    subscription_no: string;
    status: string;
    start_date: string;
    end_date: string | null;
  }[];
}

const ROL_RENGI: Record<string, string> = {
  MUSTERI: "blue",
  BAYI: "purple",
  MONTAJ_NOKTASI: "geekblue",
  TEDARIKCI: "default",
};
const ROL_ADI: Record<string, string> = {
  MUSTERI: "Müşteri",
  BAYI: "Bayi",
  MONTAJ_NOKTASI: "Montaj noktası",
  TEDARIKCI: "Tedarikçi",
};

const tl = (v: string | number | null | undefined, birim = "₺") =>
  v == null ? "—" : `${Number(v).toLocaleString("tr-TR", { minimumFractionDigits: 2 })} ${birim}`;

export default function HesaplarPage() {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const { yetkili } = useAuth();
  const { id } = useParams();
  const navigate = useNavigate();

  const [arama, setArama] = useState("");
  const [rol, setRol] = useState<string>("HEPSI");
  const [yalnizEksik, setYalnizEksik] = useState(false);
  const [yalnizDogrulanmamis, setYalnizDogrulanmamis] = useState(false);
  const [vknCakismasi, setVknCakismasi] = useState<VknCakismasi | null>(null);
  const [vknGerekce, setVknGerekce] = useState("");
  // Lokasyon penceresi: undefined = kapalı, null = yeni, sayı = düzenlenen.
  const [lokasyonPenceresi, setLokasyonPenceresi] = useState<number | null | undefined>(
    undefined,
  );
  const [duzenlenen, setDuzenlenen] = useState<Hesap | null>(null);
  const [acik, setAcik] = useState(false);
  const [kisiDuzenlenen, setKisiDuzenlenen] = useState<Kisi | null>(null);
  const [kisiAcik, setKisiAcik] = useState(false);
  const [form] = Form.useForm();
  const [kisiForm] = Form.useForm();

  // Sayfalama SUNUCUDA; gelen liste "hepsi" değil, istenen sayfadır.
  const [sayfa, setSayfa] = useState(1);
  const SAYFA_BOYU = 25;

  const hesaplar = useQuery({
    queryKey: ["hesaplar", arama, rol, yalnizEksik, yalnizDogrulanmamis, sayfa],
    queryFn: () => {
      const p = new URLSearchParams();
      if (arama) p.set("q", arama);
      if (rol !== "HEPSI") p.set("rol", rol);
      if (yalnizEksik) p.set("eksigi_olanlar", "true");
      if (yalnizDogrulanmamis) p.set("dogrulanmamis", "true");
      p.set("limit", String(SAYFA_BOYU));
      p.set("offset", String((sayfa - 1) * SAYFA_BOYU));
      return api.getSayfa<Hesap>(`/api/hesaplar?${p}`);
    },
  });

  const secili = useQuery({
    queryKey: ["hesap", id],
    queryFn: () => api.get<Hesap>(`/api/hesaplar/${id}`),
    enabled: !!id,
  });
  const kart = useQuery({
    queryKey: ["hesap-kart", id],
    queryFn: () => api.get<Kart>(`/api/hesaplar/${id}/kart`),
    enabled: !!id,
  });
  const lokasyonlar = useQuery({
    queryKey: ["hesap-lokasyonlari", Number(id)],
    queryFn: () => anaVeriApi.hesapLokasyonlari(Number(id)),
    enabled: !!id,
  });

  const kaydet = useMutation({
    mutationFn: (v: Record<string, unknown>) =>
      anaVeriApi.hesapKaydet(
        duzenlenen ? duzenlenen.id : null,
        duzenlenen ? { ...v, version: duzenlenen.version } : v,
      ),
    onSuccess: () => {
      message.success(duzenlenen ? "Hesap güncellendi" : "Hesap açıldı");
      setAcik(false);
      setDuzenlenen(null);
      setVknCakismasi(null);
      setVknGerekce("");
      form.resetFields();
      void qc.invalidateQueries({ queryKey: ["hesaplar"] });
      void qc.invalidateQueries({ queryKey: ["hesap"] });
    },
    onError: (e: ApiError, degerler) => {
      // VKN başka aktif hesapta: kayıt engellenmez, listeyi gösterip gerekçe ister.
      if (e instanceof AnaVeriHatasi && e.detay?.kod === "VKN_CAKISMASI") {
        setVknCakismasi({
          degerler,
          mevcut: (e.detay.mevcut as VknCakismasi["mevcut"]) ?? [],
          kapsam_disi: Number(e.detay.kapsam_disi ?? 0),
        });
        return;
      }
      message.error(e.cakisma ? `${e.message} Sayfayı yenileyip tekrar deneyin.` : e.message);
      if (e.cakisma) void qc.invalidateQueries({ queryKey: ["hesaplar"] });
    },
  });

  const dogrula = useMutation({
    mutationFn: (hesapId: number) => anaVeriApi.hesapDogrula(hesapId),
    onSuccess: () => {
      message.success("Hesap doğrulandı");
      void qc.invalidateQueries({ queryKey: ["hesaplar"] });
      void qc.invalidateQueries({ queryKey: ["hesap"] });
    },
    onError: (e: ApiError) => message.error(e.message),
  });

  const kisiKaydet = useMutation({
    mutationFn: (v: Record<string, unknown>) =>
      kisiDuzenlenen
        ? api.patch<Kisi>(`/api/hesaplar/kisiler/${kisiDuzenlenen.id}`, v)
        : api.post<Kisi>(`/api/hesaplar/${id}/kisiler`, v),
    onSuccess: () => {
      message.success("Yetkili kişi kaydedildi");
      setKisiAcik(false);
      setKisiDuzenlenen(null);
      kisiForm.resetFields();
      void qc.invalidateQueries({ queryKey: ["hesap-kart", id] });
    },
    onError: (e: ApiError) => message.error(e.message),
  });

  const kisiSil = useMutation({
    mutationFn: (kisiId: number) => api.delete(`/api/hesaplar/kisiler/${kisiId}`),
    onSuccess: () => {
      message.success("Kişi silindi");
      void qc.invalidateQueries({ queryKey: ["hesap-kart", id] });
    },
    onError: (e: ApiError) => message.error(e.message),
  });

  function duzenle(hesap: Hesap | null) {
    setDuzenlenen(hesap);
    form.setFieldsValue(
      hesap ?? {
        is_musteri: true,
        is_bayi: false,
        is_montaj_noktasi: false,
        is_tedarikci: false,
      },
    );
    setAcik(true);
  }

  function kisiAc(kisi: Kisi | null) {
    setKisiDuzenlenen(kisi);
    kisiForm.setFieldsValue(
      kisi
        ? {
            full_name: kisi.ad,
            title: kisi.gorev,
            phone: kisi.telefon,
            email: kisi.eposta,
            is_primary: kisi.birincil,
          }
        : { is_primary: false },
    );
    setKisiAcik(true);
  }

  const h = secili.data;
  const k = kart.data;

  return (
    <Card
      title="Hesaplar"
      extra={
        yetkili("hesap.yaz") && (
          <Button type="primary" onClick={() => duzenle(null)}>
            Yeni hesap
          </Button>
        )
      }
    >
      <Space wrap style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="Unvan, vergi no, telefon…"
          allowClear
          onSearch={(v) => {
              setArama(v);
              setSayfa(1);
            }}
          style={{ width: 280 }}
        />
        <Segmented
          value={rol}
          onChange={(v) => {
            setRol(String(v));
            setSayfa(1);
          }}
          options={[
            { label: "Hepsi", value: "HEPSI" },
            { label: "Müşteri", value: "MUSTERI" },
            { label: "Bayi", value: "BAYI" },
            { label: "Montaj noktası", value: "MONTAJ_NOKTASI" },
            { label: "Tedarikçi", value: "TEDARIKCI" },
          ]}
        />
        <Checkbox checked={yalnizEksik} onChange={(e) => {
            setYalnizEksik(e.target.checked);
            setSayfa(1);
          }}>
          Yalnız eksik bilgisi olanlar
        </Checkbox>
        <Checkbox
          checked={yalnizDogrulanmamis}
          onChange={(e) => {
            setYalnizDogrulanmamis(e.target.checked);
            setSayfa(1);
          }}
        >
          Doğrulanmamışlar
        </Checkbox>
      </Space>

      {/* Listede yalnız kimlik bilgisi var: unvan, rol, bağlı bayi. Vergi no,
          IBAN ve iletişim detayı satıra tıklayınca açılan kartta — liste on
          sütuna çıktığında unvan okunamaz hale geliyordu. */}
      <Table
        rowKey="id"
        size="small"
        loading={hesaplar.isLoading}
        dataSource={hesaplar.data?.kayitlar ?? []}
        pagination={{
          current: sayfa,
          pageSize: SAYFA_BOYU,
          total: hesaplar.data?.toplam ?? 0,
          showSizeChanger: false,
          onChange: setSayfa,
          showTotal: (t) => `${t.toLocaleString("tr-TR")} hesap`,
        }}
        scroll={{ x: 720 }}
        onRow={(hesap) => ({
          onClick: () => navigate(`/hesaplar/${hesap.id}`),
          style: { cursor: "pointer" },
        })}
        columns={[
          {
            title: "Unvan",
            dataIndex: "title",
            ellipsis: true,
            render: (x: string, hesap: Hesap) => (
              <Space size={6}>
                <span>{x}</span>
                {!hesap.is_verified && (
                  <Tooltip title="Servis ekranından hızlı açıldı; mükerrer mi, bilgileri doğru mu kontrol edilip doğrulanmalı.">
                    <Tag color="orange">Doğrulanmamış</Tag>
                  </Tooltip>
                )}
                {hesap.eksik_alanlar.length > 0 && (
                  <Tooltip
                    title={`Eksik: ${hesap.eksik_alanlar.join(", ")} — hak ediş dökümü gönderimi ve ödeme listesi için gerekli`}
                  >
                    <Tag color="orange">eksik bilgi</Tag>
                  </Tooltip>
                )}
              </Space>
            ),
          },
          {
            title: "Rol",
            width: 260,
            render: (_, hesap: Hesap) => (
              <Space size={4} wrap>
                {hesap.roller.map((r) => (
                  <Tag key={r} color={ROL_RENGI[r]}>
                    {ROL_ADI[r]}
                  </Tag>
                ))}
              </Space>
            ),
          },
          {
            title: "Bağlı bayi",
            dataIndex: "parent_dealer_title",
            width: 220,
            ellipsis: true,
            render: (v: string | null) =>
              v ?? <Typography.Text type="secondary">—</Typography.Text>,
          },
        ]}
      />

      {/* --- Hesap kartı --- */}
      <Drawer
        title={h?.title ?? "Hesap"}
        open={!!id}
        size={720}
        onClose={() => navigate("/hesaplar")}
        loading={secili.isLoading}
        extra={
          h && (
            <Space wrap>
              {!h.is_verified && yetkili("hesap.birlestir") && (
                <Button loading={dogrula.isPending} onClick={() => dogrula.mutate(h.id)}>
                  Doğrula
                </Button>
              )}
              {yetkili("hesap.yaz") && <Button onClick={() => duzenle(h)}>Düzenle</Button>}
            </Space>
          )
        }
      >
        {secili.isError && <Empty description="Hesap bulunamadı" />}
        {h && (
          <Space orientation="vertical" size={16} style={{ width: "100%" }}>
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="Roller" span={2}>
                <Space size={4} wrap>
                  {h.roller.map((r) => (
                    <Tag key={r} color={ROL_RENGI[r]}>
                      {ROL_ADI[r]}
                    </Tag>
                  ))}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="VKN / TCKN">
                <span className="mono">{h.tax_no ?? "—"}</span>
              </Descriptions.Item>
              <Descriptions.Item label="Vergi dairesi">{h.tax_office ?? "—"}</Descriptions.Item>
              <Descriptions.Item label="Telefon">
                <span className="mono">{h.phone ?? "—"}</span>
              </Descriptions.Item>
              <Descriptions.Item label="E-posta">{h.email ?? "—"}</Descriptions.Item>
              <Descriptions.Item label="IBAN" span={2}>
                <span className="mono">{h.iban ?? "—"}</span>
              </Descriptions.Item>
              <Descriptions.Item label="Bölge">{h.region ?? "—"}</Descriptions.Item>
              <Descriptions.Item label="Cari kodu">
                <span className="mono">{h.dis_referans ?? "—"}</span>
              </Descriptions.Item>
              <Descriptions.Item label="Doğrulama">
                {h.is_verified ? (
                  <Tag color="green">Doğrulandı</Tag>
                ) : (
                  <Tag color="orange">Doğrulanmamış</Tag>
                )}
              </Descriptions.Item>
              <Descriptions.Item label="Segment">
                {h.segment?.replaceAll("_", " ") ?? "—"}
              </Descriptions.Item>
              {h.parent_dealer_title && (
                <Descriptions.Item label="Bağlı bayi" span={2}>
                  <Link to={`/hesaplar/${h.parent_dealer_id}`}>{h.parent_dealer_title}</Link>
                </Descriptions.Item>
              )}
              {h.notes && (
                <Descriptions.Item label="Not" span={2}>
                  {h.notes}
                </Descriptions.Item>
              )}
            </Descriptions>

            <Tabs
              size="small"
              items={[
                {
                  key: "kisiler",
                  label: `Yetkili kişiler${k?.kisiler.length ? ` (${k.kisiler.length})` : ""}`,
                  children: (
                    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
                      {yetkili("hesap.yaz") && (
                        <Button size="small" type="primary" onClick={() => kisiAc(null)}>
                          Yetkili kişi ekle
                        </Button>
                      )}
                      <Table
                        rowKey="id"
                        size="small"
                        pagination={false}
                        loading={kart.isLoading}
                        dataSource={k?.kisiler ?? []}
                        scroll={{ x: 620 }}
                        locale={{
                          emptyText: (
                            <Empty description="Yetkili kişi girilmemiş — teklif ve hak ediş yazışması bu kişiye gider" />
                          ),
                        }}
                        columns={[
                          {
                            title: "Ad soyad",
                            dataIndex: "ad",
                            ellipsis: true,
                            render: (x: string, kisi: Kisi) => (
                              <Space size={4}>
                                <span>{x}</span>
                                {kisi.birincil && <Tag color="blue">birincil</Tag>}
                              </Space>
                            ),
                          },
                          { title: "Görev", dataIndex: "gorev", width: 150, ellipsis: true },
                          {
                            title: "Telefon",
                            dataIndex: "telefon",
                            width: 150,
                            className: "mono",
                            render: (x: string | null) => x ?? "—",
                          },
                          {
                            title: "E-posta",
                            dataIndex: "eposta",
                            width: 200,
                            ellipsis: true,
                            render: (x: string | null) => x ?? "—",
                          },
                          ...(yetkili("hesap.yaz")
                            ? [
                                {
                                  title: "",
                                  width: 120,
                                  render: (_: unknown, kisi: Kisi) => (
                                    <Space size={4}>
                                      <Button size="small" onClick={() => kisiAc(kisi)}>
                                        Düzenle
                                      </Button>
                                      <Button
                                        size="small"
                                        danger
                                        onClick={() => kisiSil.mutate(kisi.id)}
                                      >
                                        Sil
                                      </Button>
                                    </Space>
                                  ),
                                },
                              ]
                            : []),
                        ]}
                      />
                    </Space>
                  ),
                },
                {
                  key: "lokasyonlar",
                  label: `Lokasyonlar${lokasyonlar.data?.length ? ` (${lokasyonlar.data.length})` : ""}`,
                  children: (
                    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
                      {yetkili("lokasyon.yaz") && (
                        <Button
                          size="small"
                          type="primary"
                          onClick={() => setLokasyonPenceresi(null)}
                        >
                          Lokasyon ekle
                        </Button>
                      )}
                      <Table
                        rowKey="id"
                        size="small"
                        pagination={false}
                        loading={lokasyonlar.isLoading}
                        dataSource={lokasyonlar.data ?? []}
                        scroll={{ x: 560 }}
                        onRow={(l) => ({
                          onClick: () => setLokasyonPenceresi(l.id),
                          style: { cursor: "pointer" },
                        })}
                        locale={{
                          emptyText: (
                            <Empty description="Lokasyon yok — servis işleri tesise bağlanır" />
                          ),
                        }}
                        columns={[
                          {
                            title: "Ad",
                            ellipsis: true,
                            render: (_: unknown, l: Lokasyon) => (
                              <Space size={4} wrap>
                                <span>{l.site_name ?? l.label}</span>
                                {!l.is_active && <Tag>pasif</Tag>}
                                {!l.is_verified && <Tag color="orange">Doğrulanmamış</Tag>}
                              </Space>
                            ),
                          },
                          {
                            title: "Tür",
                            dataIndex: "kind",
                            width: 130,
                            render: (x: Lokasyon["kind"]) => ADRES_TURU_ETIKET[x] ?? x,
                          },
                          {
                            title: "İl / ilçe",
                            width: 170,
                            ellipsis: true,
                            render: (_: unknown, l: Lokasyon) =>
                              [l.city, l.district].filter(Boolean).join(" / ") || "—",
                          },
                        ]}
                      />
                    </Space>
                  ),
                },
                ...(h.is_montaj_noktasi
                  ? [
                      {
                        key: "tarife",
                        label: "Hak ediş tarifesi",
                        children: <MontajTarifeleri hesapId={h.id} />,
                      },
                    ]
                  : []),
                {
                  key: "belgeler",
                  label: "Belgeler",
                  children: (
                    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
                      <EkYukleyici
                        entity="accounts"
                        entityId={h.id}
                        kind="VERGI_LEVHASI"
                        baslik="Vergi levhası"
                        aciklama="VKN ve vergi dairesi bu belgeden gelir; teklif ve fatura künyesinin kaynağıdır."
                        accept=".pdf,image/*"
                        yazabilir={yetkili("hesap.yaz")}
                      />
                      <EkYukleyici
                        entity="accounts"
                        entityId={h.id}
                        kind="SOZLESME"
                        baslik="Sözleşmeler"
                        accept=".pdf,.docx,image/*"
                        yazabilir={yetkili("hesap.yaz")}
                      />
                      <EkYukleyici
                        entity="accounts"
                        entityId={h.id}
                        kind="DIGER"
                        baslik="Diğer belgeler"
                        yazabilir={yetkili("hesap.yaz")}
                      />
                    </Space>
                  ),
                },
                {
                  key: "siparisler",
                  label: `Siparişler${k?.siparisler.length ? ` (${k.siparisler.length})` : ""}`,
                  children: (
                    <Table
                      rowKey="id"
                      size="small"
                      loading={kart.isLoading}
                      dataSource={k?.siparisler ?? []}
                      pagination={{ pageSize: 10, hideOnSinglePage: true }}
                      scroll={{ x: 520 }}
                      locale={{ emptyText: <Empty description="Sipariş yok" /> }}
                      columns={[
                        { title: "No", dataIndex: "order_no", width: 150, className: "mono" },
                        {
                          title: "Tarih",
                          dataIndex: "order_date",
                          width: 120,
                          className: "mono",
                          render: (x: string) => dayjs(x).format("DD.MM.YYYY"),
                        },
                        {
                          title: "Durum",
                          dataIndex: "status",
                          width: 150,
                          render: (x: string) => <Tag>{x.replaceAll("_", " ")}</Tag>,
                        },
                        {
                          title: "Tutar",
                          dataIndex: "grand_total",
                          width: 140,
                          className: "tutar",
                          render: (x: string, o: Kart["siparisler"][number]) => tl(x, o.currency),
                        },
                      ]}
                    />
                  ),
                },
                {
                  key: "cihazlar",
                  label: `Cihazlar${k?.cihaz_sayisi ? ` (${k.cihaz_sayisi.toLocaleString("tr-TR")})` : ""}`,
                  children: (
                    <Table
                      rowKey="device_id"
                      size="small"
                      loading={kart.isLoading}
                      dataSource={k?.cihazlar ?? []}
                      pagination={{ pageSize: 15, hideOnSinglePage: true }}
                      footer={
                        k && k.cihaz_sayisi > k.cihazlar.length
                          ? () => (
                              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                                {k.cihaz_sayisi.toLocaleString("tr-TR")} cihazın ilk{" "}
                                {k.cihazlar.length.toLocaleString("tr-TR")} tanesi listeleniyor.
                              </Typography.Text>
                            )
                          : undefined
                      }
                      scroll={{ x: 560 }}
                      locale={{ emptyText: <Empty description="Bu firmada cihaz yok" /> }}
                      columns={[
                        {
                          title: "Kimlik",
                          dataIndex: "kimlik",
                          width: 170,
                          className: "mono",
                          render: (x: string | null) =>
                            x ? <Link to={`/cihazlar/${x}`}>{x}</Link> : "—",
                        },
                        { title: "Ürün", dataIndex: "urun", ellipsis: true },
                        {
                          title: "Araç",
                          dataIndex: "plaka",
                          width: 120,
                          className: "mono",
                          render: (x: string | null) => x ?? "—",
                        },
                        {
                          title: "Durum",
                          dataIndex: "status",
                          width: 140,
                          render: (x: string) => <Tag>{x.replaceAll("_", " ")}</Tag>,
                        },
                      ]}
                    />
                  ),
                },
                {
                  key: "araclar",
                  label: `Araçlar${k?.arac_sayisi ? ` (${k.arac_sayisi.toLocaleString("tr-TR")})` : ""}`,
                  children: (
                    <Table
                      rowKey="id"
                      size="small"
                      loading={kart.isLoading}
                      dataSource={k?.araclar ?? []}
                      pagination={{ pageSize: 15, hideOnSinglePage: true }}
                      footer={
                        k && k.arac_sayisi > k.araclar.length
                          ? () => (
                              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                                {k.arac_sayisi.toLocaleString("tr-TR")} aracın ilk{" "}
                                {k.araclar.length.toLocaleString("tr-TR")} tanesi listeleniyor.
                              </Typography.Text>
                            )
                          : undefined
                      }
                      scroll={{ x: 520 }}
                      locale={{ emptyText: <Empty description="Araç yok" /> }}
                      columns={[
                        {
                          title: "Plaka",
                          dataIndex: "plaka",
                          width: 140,
                          className: "mono",
                          render: (x: string, a: Kart["araclar"][number]) => (
                            <Link to={`/araclar/${a.id}`}>{x}</Link>
                          ),
                        },
                        { title: "Marka", dataIndex: "marka", width: 160, ellipsis: true },
                        { title: "Model", dataIndex: "model", width: 140, ellipsis: true },
                        {
                          title: "Şase",
                          dataIndex: "sase",
                          className: "mono",
                          ellipsis: true,
                          render: (x: string | null) => x ?? "—",
                        },
                      ]}
                    />
                  ),
                },
                {
                  key: "abonelikler",
                  label: `Abonelikler${k?.abonelikler.length ? ` (${k.abonelikler.length})` : ""}`,
                  children: (
                    <Table
                      rowKey="id"
                      size="small"
                      loading={kart.isLoading}
                      dataSource={k?.abonelikler ?? []}
                      pagination={false}
                      scroll={{ x: 520 }}
                      locale={{ emptyText: <Empty description="Abonelik yok" /> }}
                      columns={[
                        {
                          title: "No",
                          dataIndex: "subscription_no",
                          width: 160,
                          className: "mono",
                        },
                        {
                          title: "Durum",
                          dataIndex: "status",
                          width: 130,
                          render: (x: string) => <Tag>{x}</Tag>,
                        },
                        {
                          title: "Başlangıç",
                          dataIndex: "start_date",
                          width: 120,
                          className: "mono",
                          render: (x: string) => dayjs(x).format("DD.MM.YYYY"),
                        },
                        {
                          title: "Bitiş",
                          dataIndex: "end_date",
                          width: 120,
                          className: "mono",
                          render: (x: string | null) =>
                            x ? dayjs(x).format("DD.MM.YYYY") : "süresiz",
                        },
                      ]}
                    />
                  ),
                },
                {
                  key: "gorevler",
                  label: "Görevler",
                  children: k ? <KayitGorevleri entity="hesap" entityId={k.account_id} /> : null,
                },
              ]}
            />
          </Space>
        )}
      </Drawer>

      {/* --- Hesap düzenleme --- */}
      <Drawer
        title={duzenlenen ? duzenlenen.title : "Yeni hesap"}
        open={acik}
        size={520}
        onClose={() => setAcik(false)}
        extra={
          <Button type="primary" onClick={() => form.submit()} loading={kaydet.isPending}>
            Kaydet
          </Button>
        }
      >
        <Form form={form} layout="vertical" onFinish={(v) => kaydet.mutate(v)}>
          <Form.Item name="title" label="Unvan" rules={[{ required: true, min: 2 }]}>
            <Input />
          </Form.Item>

          <Typography.Text type="secondary">
            Bir hesap aynı anda birden fazla rolü taşıyabilir — örneğin kendi aracına kendi
            montajını yapan bir müşteri hem müşteri hem montaj noktasıdır.
          </Typography.Text>
          <Space style={{ display: "flex", margin: "10px 0 18px" }} wrap>
            <Form.Item name="is_musteri" valuePropName="checked" noStyle>
              <Checkbox>Müşteri</Checkbox>
            </Form.Item>
            <Form.Item name="is_bayi" valuePropName="checked" noStyle>
              <Checkbox>Bayi</Checkbox>
            </Form.Item>
            <Form.Item name="is_montaj_noktasi" valuePropName="checked" noStyle>
              <Checkbox>Montaj noktası</Checkbox>
            </Form.Item>
            <Form.Item name="is_tedarikci" valuePropName="checked" noStyle>
              <Checkbox>Tedarikçi</Checkbox>
            </Form.Item>
          </Space>

          <Form.Item name="tax_no" label="VKN / TCKN" extra="10 hane VKN veya 11 hane TCKN">
            <Input className="mono" />
          </Form.Item>
          <Form.Item name="tax_office" label="Vergi dairesi">
            <Input />
          </Form.Item>
          <Form.Item
            name="iban"
            label="IBAN"
            extra="Hak ediş ödeme listesi bu alandan üretilir; sağlaması doğrulanır."
          >
            <Input className="mono" placeholder="TR.. .... .... .... .... .... .." />
          </Form.Item>
          <Form.Item name="email" label="E-posta" extra="Hak ediş dökümü buraya gönderilir.">
            <Input type="email" />
          </Form.Item>
          <Form.Item name="phone" label="Telefon">
            <Input className="mono" />
          </Form.Item>
          <Form.Item name="region" label="Bölge">
            <Input />
          </Form.Item>
          <Form.Item
            name="dis_referans"
            label="Cari kodu"
            extra="Muhasebedeki cari kodu — yalnız bilgi amaçlı."
            rules={[{ max: 40 }]}
          >
            <Input className="mono" />
          </Form.Item>
          <Form.Item name="segment" label="Segment">
            <Select
              allowClear
              options={[
                "BIREYSEL",
                "KURUMSAL_FILO",
                "OKUL_SERVISI",
                "KIRALAMA",
                "LOJISTIK",
                "KAMU",
                "HYTERA_BAYI",
                "DIGER",
              ].map((s) => ({ value: s, label: s.replaceAll("_", " ") }))}
            />
          </Form.Item>
          <Form.Item name="notes" label="Not">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Drawer>

      {/* --- Yetkili kişi --- */}
      <Modal
        title={kisiDuzenlenen ? "Yetkili kişiyi düzenle" : "Yetkili kişi ekle"}
        open={kisiAcik}
        onCancel={() => setKisiAcik(false)}
        onOk={() => kisiForm.submit()}
        confirmLoading={kisiKaydet.isPending}
        okText="Kaydet"
        cancelText="Vazgeç"
      >
        <Form form={kisiForm} layout="vertical" onFinish={(v) => kisiKaydet.mutate(v)}>
          <Form.Item name="full_name" label="Ad soyad" rules={[{ required: true, min: 2 }]}>
            <Input />
          </Form.Item>
          <Form.Item name="title" label="Görev" extra="Örn. Filo müdürü, Satın alma sorumlusu">
            <Input />
          </Form.Item>
          <Form.Item
            name="phone"
            label="Telefon"
            extra="05xx… ya da +905xx… — kayıtta tek biçime çevrilir."
          >
            <Input className="mono" />
          </Form.Item>
          <Form.Item name="email" label="E-posta">
            <Input type="email" />
          </Form.Item>
          <Form.Item name="is_primary" valuePropName="checked">
            <Checkbox>Birincil yetkili (yazışma bu kişiye gider)</Checkbox>
          </Form.Item>
        </Form>
      </Modal>

      {/* --- Aynı VKN'li kayıt uyarısı --- */}
      <Modal
        title="Bu VKN başka hesapta kayıtlı"
        open={vknCakismasi !== null}
        onCancel={() => {
          setVknCakismasi(null);
          setVknGerekce("");
        }}
        okText="Gerekçeyle kaydet"
        cancelText="Vazgeç"
        okButtonProps={{ disabled: vknGerekce.trim().length < 5 }}
        confirmLoading={kaydet.isPending}
        onOk={() =>
          vknCakismasi &&
          kaydet.mutate({
            ...vknCakismasi.degerler,
            vkn_cakisma_onayi: true,
            vkn_cakisma_gerekce: vknGerekce.trim(),
          })
        }
      >
        <Typography.Paragraph>
          Aynı VKN'li aktif kayıtlar aşağıda. Aynı firmaysa yeni kayıt açmak yerine mevcut olanı
          kullanın; şube/bayi gibi meşru bir durumsa gerekçe yazıp kaydedin (denetime yazılır).
        </Typography.Paragraph>
        <ul>
          {vknCakismasi?.mevcut.map((m) => (
            <li key={m.id}>
              <Link to={`/hesaplar/${m.id}`}>{m.title}</Link>
            </li>
          ))}
          {!!vknCakismasi?.kapsam_disi && (
            <li>
              <Typography.Text type="secondary">
                Görme yetkiniz olmayan {vknCakismasi.kapsam_disi} kayıt
              </Typography.Text>
            </li>
          )}
        </ul>
        <Input.TextArea
          rows={2}
          placeholder="Gerekçe (en az 5 karakter)"
          value={vknGerekce}
          onChange={(e) => setVknGerekce(e.target.value)}
        />
      </Modal>

      {h && lokasyonPenceresi !== undefined && (
        <LokasyonPenceresi
          acik
          hesapId={h.id}
          lokasyonId={lokasyonPenceresi}
          onKapat={() => setLokasyonPenceresi(undefined)}
        />
      )}
    </Card>
  );
}
