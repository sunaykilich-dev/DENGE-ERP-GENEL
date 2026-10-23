/**
 * Operasyon Merkezi (TS-082, TS-083; E10-05/08/09).
 *
 * - Sayaçlar `GET /operasyon/ozet`'ten gelir; her sayaç tıklanınca liste
 *   `GET /operasyon/isler?kpi=` ile aynı süzgeçle açılır (sayı = liste toplamı).
 * - Liste SLA kalan süresine göre sunucuda sıralıdır. SLA durumu, kalan süre ve
 *   hedef YALNIZ sunucudan gelir; bu ekran öncelikten süre türetmez
 *   (`backend/tests/unit/test_on_yuz_sla_hesabi_yok.py`).
 * - Toplu işlemler için yeni uç YOK: toplu tayin `PUT /isler/toplu-atama`,
 *   toplu plan `POST /planlama/toplu-plan` (PlanPenceresi) çağrılır.
 * - "Bugün çalışılan dk" sütunu yalnız `servis_rapor.personel` ile görünür.
 * - Bildirimler kalıcıdır; "görüldü" kişiye özeldir, rozet sayısı anlık hesaptır.
 * - "E-posta kutusu" sekmesi (TS-200) yalnız `operasyon.yonet` ile görünür:
 *   servis e-postasını aç/kapat, özet saati, deneme sınırı ve giden kutusu.
 *   SMTP sırları bu ekrana gelmez (yalnız "tanımlı mı").
 */
import {
  CalendarOutlined,
  CheckOutlined,
  DashboardOutlined,
  FieldTimeOutlined,
  ReloadOutlined,
  UserAddOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Badge,
  Button,
  Card,
  Empty,
  Modal,
  Radio,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { BIRIM_ETIKETLERI, personelApi } from "../api/personel";
import {
  operasyonApi,
  sureMetni,
  type Bildirim,
  type EpostaKutusuSatiri,
  type OperasyonSatiri,
  type OperasyonSuzgeci,
  type PersonelYuku,
} from "../api/servisOperasyon";
import { teknikServisApi, type AtamaSatiri } from "../api/teknikServis";
import { useAuth } from "../auth/AuthContext";
import PlanPenceresi from "../components/PlanPenceresi";
import SlaEtiketi, { SlaKartiPenceresi } from "../components/SlaEtiketi";
import { ONCELIK_ETIKETLERI, TAYIN, servisDurumEtiketi } from "../fiori/etiketler";
import {
  Aciklama,
  AltNot,
  DurumBaglantisi,
  Kucuk,
  NoRozeti,
  PersonelHucresi,
  TUMU_KATEGORISI,
  buyuk,
  gunu,
  kategorilerOlustur,
  saati,
} from "../fiori/ListeOgeleri";
import ListeRaporu from "../fiori/ListeRaporu";

const SAYFA = 50;
const YENILEME_MS = 60_000;
const ONEM_RENGI: Record<string, string> = { KRITIK: "red", UYARI: "gold", BILGI: "blue" };

function TopluAtama({
  birim,
  isIdler,
  acik,
  kapat,
  bitti,
}: {
  birim: string;
  isIdler: number[];
  acik: boolean;
  kapat: () => void;
  bitti: () => void;
}) {
  const { message } = App.useApp();
  const [kisiler, setKisiler] = useState<number[]>([]);
  const [sorumlu, setSorumlu] = useState<number | undefined>();
  const [mod, setMod] = useState<"EKLE" | "DEGISTIR">("EKLE");
  const aday = useQuery({
    queryKey: ["atanabilir", birim],
    queryFn: () => personelApi.atanabilir(birim),
    enabled: acik && !!birim,
  });
  const rolu = (id: number): "SEF" | "TEKNISYEN" =>
    aday.data?.find((k) => k.id === id)?.saha_rolu === "SEF" ? "SEF" : "TEKNISYEN";
  const kaydet = useMutation({
    mutationFn: () => {
      const satirlar: AtamaSatiri[] = kisiler.map((id) => ({ user_id: id, rol: rolu(id), is_lead: id === sorumlu }));
      return teknikServisApi.topluAta(isIdler, satirlar, mod);
    },
    onSuccess: (s) => {
      message.success(`${s.guncellenen} işin ekibi güncellendi`);
      setKisiler([]);
      setSorumlu(undefined);
      bitti();
    },
    onError: (e: Error) => message.error(e.message),
  });
  const secenekler = (aday.data ?? []).map((k) => ({ value: k.id, label: `${k.ad} · ${k.saha_rolu}` }));
  return (
    <Modal
      title={isIdler.length > 1 ? `${TAYIN.topluTayin} (${isIdler.length} iş)` : TAYIN.ekipTayini}
      open={acik}
      onCancel={kapat}
      onOk={() => kaydet.mutate()}
      okText="Kaydet"
      cancelText="Vazgeç"
      okButtonProps={{ disabled: kisiler.length === 0 }}
      confirmLoading={kaydet.isPending}
      destroyOnHidden
    >
      <Space orientation="vertical" style={{ width: "100%" }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {BIRIM_ETIKETLERI[birim] ?? birim} biriminin tayin edilebilir saha personeli.
        </Typography.Text>
        <Radio.Group
          value={mod}
          onChange={(e) => setMod(e.target.value)}
          options={[
            { value: "EKLE", label: "Mevcut ekibe ekle" },
            { value: "DEGISTIR", label: "Ekibi bununla değiştir" },
          ]}
        />
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

function IsListesi({
  suzgec,
  baslik,
  oncelikler,
  degistir,
}: {
  suzgec: OperasyonSuzgeci;
  baslik: string;
  oncelikler: string[];
  degistir: (anahtar: string, deger: string | undefined) => void;
}) {
  const { yetkili } = useAuth();
  const qc = useQueryClient();
  const [sayfa, setSayfa] = useState(1);
  const [secili, setSecili] = useState<OperasyonSatiri[]>([]);
  const [atamaAcik, setAtamaAcik] = useState(false);
  const [planAcik, setPlanAcik] = useState(false);
  const [kartIs, setKartIs] = useState<number | null>(null);
  const anahtar = JSON.stringify(suzgec);
  const [oncekiAnahtar, setOncekiAnahtar] = useState(anahtar);
  if (anahtar !== oncekiAnahtar) {
    setOncekiAnahtar(anahtar);
    setSayfa(1);
    setSecili([]);
  }
  const liste = useQuery({
    queryKey: ["operasyon-isler", suzgec, sayfa],
    queryFn: () => operasyonApi.isler(suzgec, SAYFA, (sayfa - 1) * SAYFA),
    refetchInterval: YENILEME_MS,
  });
  const birimler = new Set(secili.map((s) => s.birim));
  const tekBirim = birimler.size === 1 ? [...birimler][0] : undefined;
  const yenile = () => {
    setSecili([]);
    qc.invalidateQueries({ queryKey: ["operasyon-isler"] });
    qc.invalidateQueries({ queryKey: ["operasyon-ozet"] });
  };
  const git = useNavigate();
  const isAc = (r: OperasyonSatiri) => git(`/servis-isleri/${r.id}`);

  const atayabilir = yetkili("servis.ata");
  const planlayabilir = yetkili("servis.planla");
  const kayitlar = liste.data?.kayitlar ?? [];

  const sutunlar: ColumnsType<OperasyonSatiri> = [
    {
      title: "Durum",
      dataIndex: "status",
      width: 150,
      align: "center",
      render: (s: string, r) => (
        <DurumBaglantisi
          metin={servisDurumEtiketi(s, r.aktif_bekleme)}
          ipucu={s}
          onClick={() => isAc(r)}
        />
      ),
    },
    {
      title: "İş No",
      dataIndex: "so_no",
      width: 170,
      align: "center",
      render: (no: string, r) => (
        <NoRozeti
          no={no}
          onClick={() => isAc(r)}
          alt={
            <>
              {ONCELIK_ETIKETLERI[r.oncelik] && (
                <AltNot tur={r.oncelik === "KRITIK" ? "kritik" : "uyari"}>{ONCELIK_ETIKETLERI[r.oncelik]}</AltNot>
              )}
              {r.tekrar_ariza_aday && (
                <Tooltip title="Son günlerde aynı cihazda kapanmış iş var (tekrar arıza adayı)">
                  <Tag color="magenta" style={{ marginTop: 2 }}>
                    Tekrar?
                  </Tag>
                </Tooltip>
              )}
            </>
          }
        />
      ),
    },
    {
      title: "SLA",
      key: "sla",
      width: 110,
      align: "center",
      render: (_, r) => (
        <Button type="link" size="small" style={{ padding: 0 }} onClick={() => setKartIs(r.id)} aria-label="SLA kartı">
          <SlaEtiketi sla={r.sla} />
        </Button>
      ),
    },
    { title: "Açılış\nTarihi", dataIndex: "created_at", width: 100, align: "center", responsive: ["sm"], render: gunu },
    { title: "Açılış\nSaati", dataIndex: "created_at", key: "saat", width: 90, align: "center", responsive: ["md"], render: saati },
    { title: "Açıklama", dataIndex: "konu", width: 280, render: (v: string, r) => <Aciklama metin={v} onClick={() => isAc(r)} /> },
    {
      title: "Mahal",
      key: "musteri",
      width: 180,
      align: "center",
      responsive: ["md"],
      render: (_, r) => <Kucuk kalin>{r.musteri?.title ?? r.customer_name_raw}</Kucuk>,
    },
    {
      title: "Sistem",
      dataIndex: "birim",
      width: 120,
      align: "center",
      responsive: ["lg"],
      render: (b: string) => <Kucuk>{BIRIM_ETIKETLERI[b] ?? b}</Kucuk>,
    },
    {
      title: "Personel",
      key: "ekip",
      width: 80,
      align: "center",
      render: (_, r) => (
        <PersonelHucresi
          sorumlu={r.sorumlu?.ad}
          kisiSayisi={r.ekip_sayisi}
          etiket={`${r.so_no} ${TAYIN.tayinEdilenEkip}`}
          onTayin={
            atayabilir
              ? () => {
                  setSecili([r]);
                  setAtamaAcik(true);
                }
              : undefined
          }
        />
      ),
    },
  ];

  const birimUyari = secili.length > 1 && !tekBirim ? "Seçili işler aynı birimde olmalı" : undefined;

  return (
    <>
      <ListeRaporu<OperasyonSatiri>
        kategoriler={kategorilerOlustur(
          Object.entries(BIRIM_ETIKETLERI).map(([kod, ad]) => ({ kod, ad })),
          () => "kirmizi",
        )}
        seciliKategori={suzgec.birim ?? TUMU_KATEGORISI.kod}
        onKategori={(k) => degistir("birim", k === TUMU_KATEGORISI.kod ? undefined : k)}
        kayitSayisi={liste.data?.toplam}
        ustSag={<Typography.Text strong>{baslik}</Typography.Text>}
        durumCubugu={{
          gruplar: oncelikler.map((o) => ({ kod: o, ad: ONCELIK_ETIKETLERI[o] ?? buyuk(o), durumlar: [o] })),
          secili: suzgec.oncelik,
          onSec: (o) => degistir("oncelik", o),
          onYenile: () => void liste.refetch(),
          yenileniyor: liste.isFetching,
        }}
        sutunlar={sutunlar}
        veri={kayitlar}
        satirAnahtari="id"
        yukleniyor={liste.isFetching}
        bosMetin={liste.isError ? (liste.error as Error).message : "Veri yok"}
        scrollX={1380}
        secimModu={atayabilir || planlayabilir ? "coklu" : "yok"}
        secili={secili.map((s) => s.id)}
        onSecim={(_, satirlar) => setSecili(satirlar)}
        onSatirAc={isAc}
        sayfalama={{ sayfa, boyut: SAYFA, toplam: liste.data?.toplam ?? 0, onChange: setSayfa }}
        eylemBilgisi={
          atayabilir || planlayabilir ? (
            <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
              {secili.length ? `${secili.length} iş seçili` : "Toplu işlem için iş seçin"}
            </Typography.Text>
          ) : undefined
        }
        eylemler={[
          {
            anahtar: "liste",
            ad: "Liste",
            menu: [
              { key: "temizle", label: "Seçimi temizle", disabled: !secili.length },
              { key: "yenile", label: "Listeyi yenile" },
            ],
            onMenu: (k) => (k === "temizle" ? setSecili([]) : yenile()),
          },
          {
            anahtar: "tayin",
            ad: secili.length > 1 ? TAYIN.topluTayin : TAYIN.tayinEt,
            ikon: <UserAddOutlined />,
            kisalt: true,
            gizli: !atayabilir,
            ipucu: birimUyari,
            devreDisi: !tekBirim,
            onClick: () => setAtamaAcik(true),
          },
          {
            anahtar: "plan",
            ad: "Toplu Plan",
            ikon: <CalendarOutlined />,
            kisalt: true,
            gizli: !planlayabilir,
            ipucu: birimUyari,
            devreDisi: !tekBirim,
            onClick: () => setPlanAcik(true),
          },
          {
            anahtar: "sla",
            ad: "SLA Kartı",
            ikon: <FieldTimeOutlined />,
            yalnizIkon: true,
            devreDisi: secili.length !== 1,
            onClick: () => secili.length === 1 && setKartIs(secili[0].id),
          },
        ]}
      />
      <SlaKartiPenceresi soId={kartIs} onKapat={() => setKartIs(null)} />
      {tekBirim && (
        <>
          <TopluAtama
            birim={tekBirim}
            isIdler={secili.map((s) => s.id)}
            acik={atamaAcik}
            kapat={() => setAtamaAcik(false)}
            bitti={() => {
              setAtamaAcik(false);
              yenile();
            }}
          />
          <PlanPenceresi
            acik={planAcik}
            mod="toplu"
            isIdler={secili.map((s) => s.id)}
            birim={tekBirim}
            baslik={`Toplu plan (${secili.length} iş)`}
            onKapat={() => setPlanAcik(false)}
            onKaydedildi={() => {
              setPlanAcik(false);
              yenile();
            }}
          />
        </>
      )}
    </>
  );
}

function PersonelSekmesi({ birim }: { birim?: string }) {
  const veri = useQuery({
    queryKey: ["operasyon-personel", birim],
    queryFn: () => operasyonApi.personel(birim),
    refetchInterval: YENILEME_MS,
  });
  const sutunlar: ColumnsType<PersonelYuku> = [
    { title: "Personel", dataIndex: "ad" },
    { title: "Saha rolü", dataIndex: "saha_rolu", render: (r: string | null) => r ?? "—" },
    {
      title: "Birimler",
      dataIndex: "birimler",
      render: (b: string[]) => b.map((k) => BIRIM_ETIKETLERI[k] ?? k).join(", "),
    },
    {
      title: "Şu an",
      key: "sayac",
      render: (_, r) =>
        r.acik_sayac ? (
          <Tooltip title={`Başlangıç ${dayjs(r.acik_sayac.started_at).format("DD.MM HH:mm")}`}>
            <Tag color="green">
              {r.acik_sayac.so_no} · {r.acik_sayac.faaliyet}
            </Tag>
          </Tooltip>
        ) : (
          <Typography.Text type="secondary">Açık sayaç yok</Typography.Text>
        ),
    },
    { title: "Açık tayin edilmiş iş", dataIndex: "acik_atanmis", align: "right" },
    { title: "Bugün planlı", dataIndex: "bugun_planli", align: "right" },
    { title: "Yarın planlı", dataIndex: "yarin_planli", align: "right" },
    ...(veri.data?.kisi_saat_gorunur
      ? [
          {
            title: "Bugün çalışılan",
            dataIndex: "bugun_calisilan_dk",
            align: "right" as const,
            render: (d: number | null | undefined) =>
              d == null ? <Typography.Text type="secondary">Kayıt yok</Typography.Text> : sureMetni(d),
          },
        ]
      : []),
  ];
  return (
    <Table<PersonelYuku>
      rowKey="user_id"
      size="small"
      loading={veri.isLoading}
      dataSource={veri.data?.personel ?? []}
      columns={sutunlar}
      scroll={{ x: true }}
      pagination={{ pageSize: 50, hideOnSinglePage: true }}
      locale={{ emptyText: <Empty description="Saha personeli yok" /> }}
    />
  );
}

function BildirimSekmesi() {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [acik, setAcik] = useState(true);
  const [sayfa, setSayfa] = useState(1);
  const veri = useQuery({
    queryKey: ["operasyon-bildirimler", acik, sayfa],
    queryFn: () => operasyonApi.bildirimler(acik, SAYFA, (sayfa - 1) * SAYFA),
    refetchInterval: YENILEME_MS,
  });
  const gor = useMutation({
    mutationFn: (idler: number[]) => operasyonApi.goruldu(idler),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["operasyon-bildirimler"] }),
    onError: (e: Error) => message.error(e.message),
  });
  const gorulmemis = (veri.data?.kayitlar ?? []).filter((b) => !b.goruldu).map((b) => b.id);
  const sutunlar: ColumnsType<Bildirim> = [
    {
      title: "Önem",
      dataIndex: "onem",
      render: (o: string, r) => (
        <Badge dot={!r.goruldu}>
          <Tag color={ONEM_RENGI[o]}>{o}</Tag>
        </Badge>
      ),
    },
    { title: "Tür", dataIndex: "kod_adi" },
    {
      title: "İş",
      dataIndex: "so_no",
      render: (no: string, r) => (
        <Link to={`/servis-isleri/${r.service_order_id}`} className="mono">
          {no}
        </Link>
      ),
    },
    { title: "Başlık", dataIndex: "baslik", ellipsis: true },
    { title: "Açılış", dataIndex: "acilis_at", render: (t: string) => dayjs(t).format("DD.MM.YYYY HH:mm") },
    ...(!acik
      ? [
          {
            title: "Kapanış",
            dataIndex: "kapanis_at",
            render: (t: string | null, r: Bildirim) =>
              t ? `${dayjs(t).format("DD.MM.YYYY HH:mm")}${r.kapanis_nedeni ? ` (${r.kapanis_nedeni})` : ""}` : "—",
          },
        ]
      : []),
    {
      title: "",
      key: "islem",
      width: 60,
      render: (_, r) =>
        r.goruldu ? null : (
          <Button size="small" icon={<CheckOutlined />} aria-label="Görüldü" onClick={() => gor.mutate([r.id])} />
        ),
    },
  ];
  return (
    <>
      <Space wrap style={{ marginBottom: 12 }}>
        <Switch
          checked={acik}
          onChange={(v) => {
            setAcik(v);
            setSayfa(1);
          }}
          checkedChildren="Açık"
          unCheckedChildren="Tümü"
        />
        <Button
          size="small"
          disabled={gorulmemis.length === 0}
          loading={gor.isPending}
          onClick={() => gor.mutate(gorulmemis)}
        >
          Bu sayfadakileri görüldü say ({gorulmemis.length})
        </Button>
      </Space>
      <Table<Bildirim>
        rowKey="id"
        size="small"
        loading={veri.isLoading}
        dataSource={veri.data?.kayitlar ?? []}
        columns={sutunlar}
        scroll={{ x: true }}
        locale={{ emptyText: <Empty description="Bildirim yok" /> }}
        pagination={{
          current: sayfa,
          pageSize: SAYFA,
          total: veri.data?.toplam ?? 0,
          showSizeChanger: false,
          onChange: setSayfa,
        }}
      />
    </>
  );
}

const KUTU_DURUM_RENGI: Record<string, string> = { BEKLIYOR: "blue", GONDERILDI: "green", BASARISIZ: "red" };
const KUTU_DURUM_ADI: Record<string, string> = {
  BEKLIYOR: "Bekliyor",
  GONDERILDI: "Gönderildi",
  BASARISIZ: "Başarısız",
};

/** Servis e-posta kutusu ve ayarları (TS-200; yalnız `operasyon.yonet`). */
function EpostaSekmesi() {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [durum, setDurum] = useState<string | undefined>();
  const [sayfa, setSayfa] = useState(1);
  const ayar = useQuery({ queryKey: ["operasyon-eposta-ayar"], queryFn: operasyonApi.epostaAyarlari });
  const kutu = useQuery({
    queryKey: ["operasyon-eposta-kutusu", durum, sayfa],
    queryFn: () => operasyonApi.epostaKutusu(SAYFA, (sayfa - 1) * SAYFA, durum),
    refetchInterval: YENILEME_MS,
  });
  const yaz = useMutation({
    mutationFn: operasyonApi.epostaAyarlariYaz,
    onSuccess: (r) => {
      qc.setQueryData(["operasyon-eposta-ayar"], r);
      message.success("E-posta ayarı kaydedildi");
    },
    onError: (e: Error) => message.error(e.message),
  });
  const a = ayar.data;
  const sutunlar: ColumnsType<EpostaKutusuSatiri> = [
    {
      title: "Durum",
      dataIndex: "durum",
      render: (d: string) => <Tag color={KUTU_DURUM_RENGI[d]}>{KUTU_DURUM_ADI[d] ?? d}</Tag>,
    },
    { title: "Tür", dataIndex: "tur", render: (t: string) => (t === "ANLIK" ? "Anlık" : "Günlük özet") },
    { title: "Kişi", key: "kisi", render: (_, r) => r.kullanici.ad },
    { title: "Alıcı", dataIndex: "alici", ellipsis: true },
    { title: "Konu", dataIndex: "konu", ellipsis: true },
    { title: "Deneme", dataIndex: "deneme", align: "right" },
    {
      title: "Son hata",
      dataIndex: "son_hata",
      ellipsis: true,
      render: (h: string | null) => h ?? "—",
    },
    { title: "Oluşma", dataIndex: "created_at", render: (t: string) => dayjs(t).format("DD.MM.YYYY HH:mm") },
    {
      title: "Gönderim",
      dataIndex: "gonderildi_at",
      render: (t: string | null) => (t ? dayjs(t).format("DD.MM.YYYY HH:mm") : "—"),
    },
  ];
  return (
    <Space orientation="vertical" style={{ width: "100%" }} size={12}>
      {a && !a.smtp_tanimli && (
        <Alert
          type="warning"
          showIcon
          message="SMTP ayarları tanımlı değil: e-postalar kutuda BEKLİYOR kalır, deneme sayılmaz. SMTP, Parametreler → Bildirim (e-posta) bölümünden tanımlanır."
        />
      )}
      {a && (
        <Card size="small" title="Servis e-postası">
          <Space wrap size={16}>
            <Space>
              <Switch
                checked={a.servis_eposta_acik}
                loading={yaz.isPending}
                onChange={(v) => yaz.mutate({ servis_eposta_acik: v })}
              />
              <Typography.Text>{a.servis_eposta_acik ? "Açık" : "Kapalı"}</Typography.Text>
            </Space>
            <Space>
              <Typography.Text type="secondary">Günlük özet saati</Typography.Text>
              <Select
                style={{ width: 100 }}
                value={a.servis_gunluk_ozet_saati}
                onChange={(v) => yaz.mutate({ servis_gunluk_ozet_saati: v })}
                options={Array.from({ length: 48 }, (_, i) => {
                  const s = `${String(Math.floor(i / 2)).padStart(2, "0")}:${i % 2 ? "30" : "00"}`;
                  return { value: s, label: s };
                })}
              />
            </Space>
            <Space>
              <Typography.Text type="secondary">Deneme sınırı</Typography.Text>
              <Select
                style={{ width: 80 }}
                value={a.servis_eposta_deneme}
                onChange={(v) => yaz.mutate({ servis_eposta_deneme: v })}
                options={Array.from({ length: 10 }, (_, i) => ({ value: i + 1, label: String(i + 1) }))}
              />
            </Space>
          </Space>
        </Card>
      )}
      <Select
        allowClear
        placeholder="Tüm durumlar"
        style={{ width: 180 }}
        value={durum}
        onChange={(v) => {
          setDurum(v);
          setSayfa(1);
        }}
        options={Object.entries(KUTU_DURUM_ADI).map(([value, label]) => ({ value, label }))}
      />
      <Table<EpostaKutusuSatiri>
        rowKey="id"
        size="small"
        loading={kutu.isLoading}
        dataSource={kutu.data?.kayitlar ?? []}
        columns={sutunlar}
        scroll={{ x: true }}
        locale={{ emptyText: <Empty description="E-posta kutusu boş" /> }}
        pagination={{
          current: sayfa,
          pageSize: SAYFA,
          total: kutu.data?.toplam ?? 0,
          showSizeChanger: false,
          onChange: setSayfa,
        }}
      />
    </Space>
  );
}

export default function OperasyonMerkeziPage() {
  const qc = useQueryClient();
  const { yetkili } = useAuth();
  const [arama, setArama] = useSearchParams();
  const suzgec: OperasyonSuzgeci = useMemo(
    () => ({
      kpi: arama.get("kpi") ?? "acik",
      birim: arama.get("birim") ?? undefined,
      oncelik: arama.get("oncelik") ?? undefined,
    }),
    [arama],
  );
  const sekme = arama.get("sekme") ?? "isler";
  const degistir = (anahtar: string, deger: string | undefined) => {
    const p = new URLSearchParams(arama);
    if (deger) p.set(anahtar, deger);
    else p.delete(anahtar);
    setArama(p, { replace: true });
  };

  const sozluk = useQuery({ queryKey: ["sla-sozluk"], queryFn: operasyonApi.sozluk, staleTime: 300_000 });
  const ozet = useQuery({
    queryKey: ["operasyon-ozet", suzgec.birim, suzgec.oncelik],
    queryFn: () => operasyonApi.ozet({ birim: suzgec.birim, oncelik: suzgec.oncelik }),
    refetchInterval: YENILEME_MS,
  });
  const rozet = useQuery({
    queryKey: ["operasyon-bildirimler", "rozet"],
    queryFn: () => operasyonApi.bildirimler(true, 1, 0),
    refetchInterval: YENILEME_MS,
  });

  const gruplar = useMemo(() => {
    const m = new Map<string, NonNullable<typeof ozet.data>["sayaclar"]>();
    for (const s of ozet.data?.sayaclar ?? []) {
      const g = m.get(s.grup) ?? [];
      g.push(s);
      m.set(s.grup, g);
    }
    return [...m.entries()];
  }, [ozet.data]);
  const seciliSayac = ozet.data?.sayaclar.find((s) => s.kod === suzgec.kpi);

  return (
    <div className="fm-sayfa">
      {sozluk.data && !sozluk.data.sla_yururlukte && (
        <Alert
          type="info"
          showIcon
          message="SLA henüz yürürlükte değil: işlere hedef damgalanmıyor, SLA sayaçları boş kalır."
        />
      )}
      {ozet.error && <Alert type="error" showIcon message={(ozet.error as Error).message} />}
      {gruplar.map(([grup, sayaclar]) => (
        <div key={grup}>
          <div className="fl-kutucuk-grubu-baslik">{grup}</div>
          <div className="fl-kutucuklar">
            {sayaclar.map((s) => {
              const sec = () => {
                degistir("kpi", s.kod);
                if (sekme !== "isler") degistir("sekme", undefined);
              };
              return (
                <Tooltip key={s.kod} title={s.tanim}>
                  <div
                    className="fl-kutucuk"
                    role="button"
                    tabIndex={0}
                    aria-pressed={s.kod === suzgec.kpi}
                    onClick={sec}
                    onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && sec()}
                    style={s.kod === suzgec.kpi ? { borderColor: "#0a6ed1", boxShadow: "0 0 0 2px #0a6ed1" } : undefined}
                  >
                    <div className="fl-kutucuk-baslik">{s.baslik}</div>
                    <div className="fl-kutucuk-dip">
                      <span className="fl-kutucuk-ikon">
                        <DashboardOutlined />
                      </span>
                      <span
                        className={`fl-kutucuk-sayi${s.deger > 0 && s.vurgu === "kritik" ? " kritik" : s.deger > 0 && s.vurgu === "uyari" ? " uyari" : ""}`}
                      >
                        {s.deger.toLocaleString("tr-TR")}
                      </span>
                    </div>
                  </div>
                </Tooltip>
              );
            })}
          </div>
        </div>
      ))}
      {ozet.data && (
        <Space wrap>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Güncelleme {dayjs(ozet.data.sunucu_zamani).format("DD.MM.YYYY HH:mm")} · "SLA riskte" eşiği: hedef
            süresinin %{ozet.data.risk_yuzde}'i geçmiş açık işler
          </Typography.Text>
          <Tooltip title="Yenile (ekran dakikada bir kendiliğinden yenilenir)">
            <Button
              size="small"
              icon={<ReloadOutlined />}
              aria-label="Yenile"
              onClick={() => qc.invalidateQueries({ predicate: (q) => String(q.queryKey[0]).startsWith("operasyon") })}
            />
          </Tooltip>
        </Space>
      )}
      <Tabs
        activeKey={sekme}
        onChange={(k) => degistir("sekme", k === "isler" ? undefined : k)}
        items={[
          {
            key: "isler",
            label: "İşler",
            children: (
              <IsListesi
                suzgec={suzgec}
                baslik={seciliSayac?.baslik ?? "Açık işler"}
                oncelikler={sozluk.data?.oncelikler ?? []}
                degistir={degistir}
              />
            ),
          },
          { key: "personel", label: "Personel iş yükü", children: <PersonelSekmesi birim={suzgec.birim} /> },
          {
            key: "bildirimler",
            label: (
              <Badge count={rozet.data?.toplam ?? 0} size="small" offset={[8, -2]}>
                SLA bildirimleri
              </Badge>
            ),
            children: <BildirimSekmesi />,
          },
          ...(yetkili("operasyon.yonet")
            ? [{ key: "eposta", label: "E-posta kutusu", children: <EpostaSekmesi /> }]
            : []),
        ]}
      />
    </div>
  );
}
