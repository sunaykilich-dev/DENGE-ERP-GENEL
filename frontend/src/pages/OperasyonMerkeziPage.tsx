/**
 * Operasyon Merkezi (TS-082, TS-083; E10-05/08/09).
 *
 * - Sayaçlar `GET /operasyon/ozet`'ten gelir; her sayaç tıklanınca liste
 *   `GET /operasyon/isler?kpi=` ile aynı süzgeçle açılır (sayı = liste toplamı).
 * - Liste SLA kalan süresine göre sunucuda sıralıdır. SLA durumu, kalan süre ve
 *   hedef YALNIZ sunucudan gelir; bu ekran öncelikten süre türetmez
 *   (`backend/tests/unit/test_on_yuz_sla_hesabi_yok.py`).
 * - Toplu işlemler için yeni uç YOK: toplu atama `PUT /isler/toplu-atama`,
 *   toplu plan `POST /planlama/toplu-plan` (PlanPenceresi) çağrılır.
 * - "Bugün çalışılan dk" sütunu yalnız `servis_rapor.personel` ile görünür.
 * - Bildirimler kalıcıdır; "görüldü" kişiye özeldir, rozet sayısı anlık hesaptır.
 */
import { CheckOutlined, ReloadOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Badge,
  Button,
  Card,
  Col,
  Empty,
  Modal,
  Radio,
  Row,
  Select,
  Space,
  Statistic,
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
import { Link, useSearchParams } from "react-router-dom";

import { BIRIM_ETIKETLERI, personelApi } from "../api/personel";
import {
  operasyonApi,
  sureMetni,
  type Bildirim,
  type OperasyonSatiri,
  type OperasyonSuzgeci,
  type PersonelYuku,
} from "../api/servisOperasyon";
import { teknikServisApi, type AtamaSatiri } from "../api/teknikServis";
import { useAuth } from "../auth/AuthContext";
import PlanPenceresi from "../components/PlanPenceresi";
import SlaEtiketi, { SlaKartiPenceresi } from "../components/SlaEtiketi";

const SAYFA = 50;
const YENILEME_MS = 60_000;
const ONCELIK_RENGI: Record<string, string> = { KRITIK: "red", YUKSEK: "orange", NORMAL: "blue", DUSUK: "default" };
const VURGU_RENGI: Record<string, string | undefined> = { kritik: "#cf1322", uyari: "#d48806", normal: undefined };
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
      title={`Toplu atama (${isIdler.length} iş)`}
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
          {BIRIM_ETIKETLERI[birim] ?? birim} biriminin atanabilir saha personeli.
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

function IsListesi({ suzgec, baslik }: { suzgec: OperasyonSuzgeci; baslik: string }) {
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

  const sutunlar: ColumnsType<OperasyonSatiri> = [
    {
      title: "İş",
      dataIndex: "so_no",
      render: (no: string, r) => (
        <Space size={4}>
          <Link to={`/servis-isleri/${r.id}`} className="mono">
            {no}
          </Link>
          {r.tekrar_ariza_aday && (
            <Tooltip title="Son günlerde aynı cihazda kapanmış iş var (tekrar arıza adayı)">
              <Tag color="magenta">Tekrar?</Tag>
            </Tooltip>
          )}
        </Space>
      ),
    },
    {
      title: "SLA",
      key: "sla",
      render: (_, r) => (
        <Button type="link" size="small" style={{ padding: 0 }} onClick={() => setKartIs(r.id)} aria-label="SLA kartı">
          <SlaEtiketi sla={r.sla} />
        </Button>
      ),
    },
    {
      title: "Öncelik",
      dataIndex: "oncelik",
      render: (o: string) => <Tag color={ONCELIK_RENGI[o]}>{o}</Tag>,
    },
    { title: "Birim", dataIndex: "birim", render: (b: string) => BIRIM_ETIKETLERI[b] ?? b },
    { title: "Konu", dataIndex: "konu", ellipsis: true },
    { title: "Müşteri", key: "musteri", render: (_, r) => r.musteri?.title ?? r.customer_name_raw ?? "—" },
    {
      title: "Ekip",
      key: "ekip",
      render: (_, r) =>
        r.sorumlu ? `${r.sorumlu.ad}${r.ekip_sayisi > 1 ? ` +${r.ekip_sayisi - 1}` : ""}` : <Tag>Atanmamış</Tag>,
    },
    {
      title: "Durum",
      dataIndex: "status",
      render: (s: string, r) => (
        <Space size={4} wrap>
          <Tag>{s}</Tag>
          {r.aktif_bekleme && <Tag color="blue">İş beklemesi: {r.aktif_bekleme}</Tag>}
        </Space>
      ),
    },
    {
      title: "Açılış",
      dataIndex: "created_at",
      render: (t: string) => dayjs(t).format("DD.MM.YYYY HH:mm"),
    },
  ];

  const atayabilir = yetkili("servis.ata");
  const planlayabilir = yetkili("servis.planla");
  return (
    <Card
      size="small"
      title={baslik}
      extra={
        <Space wrap>
          {(atayabilir || planlayabilir) && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {secili.length ? `${secili.length} iş seçili` : "Toplu işlem için iş seçin"}
            </Typography.Text>
          )}
          {atayabilir && (
            <Tooltip title={secili.length && !tekBirim ? "Seçili işler aynı birimde olmalı" : undefined}>
              <Button size="small" disabled={!tekBirim} onClick={() => setAtamaAcik(true)}>
                Toplu atama
              </Button>
            </Tooltip>
          )}
          {planlayabilir && (
            <Tooltip title={secili.length && !tekBirim ? "Seçili işler aynı birimde olmalı" : undefined}>
              <Button size="small" disabled={!tekBirim} onClick={() => setPlanAcik(true)}>
                Toplu plan
              </Button>
            </Tooltip>
          )}
        </Space>
      }
    >
      <Table<OperasyonSatiri>
        rowKey="id"
        size="small"
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar ?? []}
        columns={sutunlar}
        scroll={{ x: true }}
        rowSelection={
          atayabilir || planlayabilir
            ? {
                selectedRowKeys: secili.map((s) => s.id),
                onChange: (_, satirlar) => setSecili(satirlar),
                preserveSelectedRowKeys: true,
              }
            : undefined
        }
        locale={{ emptyText: <Empty description="Bu süzgeçte iş yok" /> }}
        pagination={{
          current: sayfa,
          pageSize: SAYFA,
          total: liste.data?.toplam ?? 0,
          showSizeChanger: false,
          showTotal: (t) => `${t} iş`,
          onChange: setSayfa,
        }}
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
    </Card>
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
    { title: "Açık atanmış iş", dataIndex: "acik_atanmis", align: "right" },
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

export default function OperasyonMerkeziPage() {
  const qc = useQueryClient();
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
    <Card
      title="Operasyon Merkezi"
      extra={
        <Space wrap>
          <Select
            allowClear
            placeholder="Tüm birimler"
            style={{ minWidth: 180 }}
            value={suzgec.birim}
            onChange={(v) => degistir("birim", v)}
            options={Object.entries(BIRIM_ETIKETLERI).map(([value, label]) => ({ value, label }))}
          />
          <Select
            allowClear
            placeholder="Tüm öncelikler"
            style={{ minWidth: 150 }}
            value={suzgec.oncelik}
            onChange={(v) => degistir("oncelik", v)}
            options={(sozluk.data?.oncelikler ?? []).map((o) => ({ value: o, label: o }))}
          />
          <Tooltip title="Yenile (ekran dakikada bir kendiliğinden yenilenir)">
            <Button
              icon={<ReloadOutlined />}
              aria-label="Yenile"
              onClick={() => qc.invalidateQueries({ predicate: (q) => String(q.queryKey[0]).startsWith("operasyon") })}
            />
          </Tooltip>
        </Space>
      }
    >
      {sozluk.data && !sozluk.data.sla_yururlukte && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="SLA henüz yürürlükte değil: işlere hedef damgalanmıyor, SLA sayaçları boş kalır."
        />
      )}
      {ozet.error && (
        <Alert type="error" showIcon style={{ marginBottom: 12 }} message={(ozet.error as Error).message} />
      )}
      <Space orientation="vertical" style={{ width: "100%" }} size={12}>
        {gruplar.map(([grup, sayaclar]) => (
          <Row gutter={[8, 8]} key={grup}>
            {sayaclar.map((s) => (
              <Col key={s.kod} xs={12} sm={8} md={6} lg={4}>
                <Tooltip title={s.tanim}>
                  <Card
                    size="small"
                    hoverable
                    onClick={() => {
                      degistir("kpi", s.kod);
                      if (sekme !== "isler") degistir("sekme", undefined);
                    }}
                    style={s.kod === suzgec.kpi ? { borderColor: "var(--ant-color-primary)" } : undefined}
                  >
                    <Statistic
                      title={s.baslik}
                      value={s.deger}
                      valueStyle={s.deger > 0 ? { color: VURGU_RENGI[s.vurgu] } : undefined}
                    />
                  </Card>
                </Tooltip>
              </Col>
            ))}
          </Row>
        ))}
        {ozet.data && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Güncelleme {dayjs(ozet.data.sunucu_zamani).format("DD.MM.YYYY HH:mm")} · "SLA riskte" eşiği: hedef
            süresinin %{ozet.data.risk_yuzde}'i geçmiş açık işler
          </Typography.Text>
        )}
        <Tabs
          activeKey={sekme}
          onChange={(k) => degistir("sekme", k === "isler" ? undefined : k)}
          items={[
            {
              key: "isler",
              label: "İşler",
              children: <IsListesi suzgec={suzgec} baslik={seciliSayac?.baslik ?? "Açık işler"} />,
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
          ]}
        />
      </Space>
    </Card>
  );
}
