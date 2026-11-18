/**
 * Ekipman Kütüğü — liste, filtre, Excel, KPI, toplu işlem (TS-053/055/056).
 *
 * Veri yalnız sayfa açılınca gelir (giriş/panelde kütük çağrılmaz). Liste
 * sunucuda süzülür ve sayfalanır; toplam `X-Toplam-Kayit`. KPI kutularının
 * sayısı, tıklanınca açılan `?kpi=<kod>` listesinin toplamıyla aynı sorgudan
 * gelir (sayı = liste). Excel ekrandaki süzgeci (seçim varsa seçili satırları)
 * aynen alır. `/servis-ekipman/:id` kartı doğrudan açar (görev ve arama
 * bağlantıları buraya gelir).
 */
import {
  DatabaseOutlined,
  EditOutlined,
  PlusOutlined,
  SafetyOutlined,
  WifiOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnsType } from "antd/es/table";
import {
  App,
  Button,
  Checkbox,
  Col,
  Form,
  Grid,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { BIRIM_ETIKETLERI, BIRIM_KODLARI } from "../api/personel";
import {
  DURUM_ETIKETLERI,
  EKIPMAN_TIPLERI,
  ekipmanApi,
  GARANTI_ETIKETLERI,
  TIP_ETIKETLERI,
  type EkipmanKarti as Kart,
  type EkipmanSatiri,
  type EkipmanSuzgeci,
  type GarantiSonucu,
} from "../api/servisEkipman";
import { useAuth } from "../auth/AuthContext";
import EkipmanFormu from "../components/EkipmanFormu";
import EkipmanKarti, { GarantiEtiketi } from "../components/EkipmanKarti";
import EkipmanTopluIslemleri from "../components/EkipmanTopluIslemleri";
import EkipmanVeriKalitesi from "../components/EkipmanVeriKalitesi";
import {
  Aciklama,
  AltNot,
  DurumBaglantisi,
  Kucuk,
  KucukGri,
  NoRozeti,
  TUMU_KATEGORISI,
  gunu,
  kategorilerOlustur,
  tekliGruplar,
} from "../fiori/ListeOgeleri";
import ListeRaporu, { KpiKutucugu, type FioriEylem } from "../fiori/ListeRaporu";
import KutucukPano from "../fiori/KutucukPano";

const SAYFA_BOYU = 50;
const TOPLU_UST_SINIR = 200;

const tarih = (d?: string | null) => (d ? dayjs(d).format("DD.MM.YYYY") : "—");

/** URL arama parametreleri ↔ süzgeç (KPI kutusu ve geri tuşu aynı listeyi açsın). */
function suzgecOku(p: URLSearchParams): EkipmanSuzgeci {
  const bool = (k: string) => (p.get(k) === "true" ? true : p.get(k) === "false" ? false : undefined);
  return {
    q: p.get("q") ?? undefined,
    birim: p.get("birim") ?? undefined,
    tip: p.get("tip") ?? undefined,
    durum: p.get("durum") ?? undefined,
    garanti: p.get("garanti") ?? undefined,
    seri_eksik: bool("seri_eksik"),
    lokasyonsuz: bool("lokasyonsuz"),
    sozlesmesiz: bool("sozlesmesiz"),
    serviste: bool("serviste"),
    pasifler_dahil: bool("pasifler_dahil"),
    kpi: p.get("kpi") ?? undefined,
    kalite: p.get("kalite") ?? undefined,
    hesap_id: p.get("hesap_id") ? Number(p.get("hesap_id")) : undefined,
    sozlesme_id: p.get("sozlesme_id") ? Number(p.get("sozlesme_id")) : undefined,
  };
}

function suzgecYaz(s: EkipmanSuzgeci): URLSearchParams {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(s)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    p.set(k, String(v));
  }
  return p;
}

export default function ServisEkipmanPage() {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const git = useNavigate();
  const { id } = useParams();
  const [arama, setArama] = useSearchParams();
  const yazabilir = yetkili("ekipman.yaz");
  const aktarabilir = yetkili("ekipman.gor", "servis_rapor.disaaktar");

  const suzgec = useMemo(() => suzgecOku(arama), [arama]);
  const [sayfa, setSayfa] = useState(1);
  const [secili, setSecili] = useState<number[]>([]);
  const [seciliSatirlar, setSeciliSatirlar] = useState<Record<number, EkipmanSatiri>>({});
  const [formAcik, setFormAcik] = useState(false);
  const [duzenlenen, setDuzenlenen] = useState<Kart | null>(null);
  const [topluDurumAcik, setTopluDurumAcik] = useState(false);
  const [garantiAcik, setGarantiAcik] = useState(false);
  const [onizleme, setOnizleme] = useState<GarantiSonucu | null>(null);
  const [topluForm] = Form.useForm<{ hedef: string; gerekce: string }>();
  const [aramaMetni, setAramaMetni] = useState(suzgec.q ?? "");
  const [suzgecAcik, setSuzgecAcik] = useState(false);

  const kartId = id ? Number(id) : null;
  const yolEki = arama.toString() ? `?${arama.toString()}` : "";

  // Veri Kalitesi paneli (TS-188): `?sekme=kalite[&liste=mukerrer|saha]`.
  const kalitePaneli = arama.get("sekme") === "kalite";
  const kaliteListesi = arama.get("liste");

  const suzgecDegistir = (yeni: EkipmanSuzgeci, panel?: { sekme?: string; liste?: string | null }) => {
    const p = suzgecYaz(yeni);
    const sekme = panel ? panel.sekme : arama.get("sekme");
    const liste = panel ? panel.liste : arama.get("liste");
    if (sekme) p.set("sekme", sekme);
    if (sekme && liste) p.set("liste", liste);
    setArama(p);
    setSayfa(1);
    setSecili([]);
  };

  const ozet = useQuery({ queryKey: ["servis-ekipman-ozet"], queryFn: ekipmanApi.ozet });
  const liste = useQuery({
    queryKey: ["servis-ekipman", suzgec, sayfa],
    queryFn: () => ekipmanApi.liste(suzgec, SAYFA_BOYU, (sayfa - 1) * SAYFA_BOYU),
  });

  const tazele = () => {
    void qc.invalidateQueries({ queryKey: ["servis-ekipman"] });
    void qc.invalidateQueries({ queryKey: ["servis-ekipman-ozet"] });
  };

  const topluDurum = useMutation({
    mutationFn: (v: { hedef: string; gerekce: string }) =>
      ekipmanApi.topluDurum({ idler: secili, hedef: v.hedef, gerekce: v.gerekce }),
    onSuccess: (r) => {
      message.success(`${r.length} ekipmanın durumu değişti`);
      setTopluDurumAcik(false);
      setSecili([]);
      tazele();
    },
    onError: (e: Error) => message.error(e.message),
  });

  const garanti = useMutation({
    mutationFn: (uygula: boolean) =>
      ekipmanApi.topluGaranti({ idler: secili.length ? secili : null }, uygula),
    onSuccess: (r) => {
      if (r.uygulandi) {
        message.success(`${r.satir_sayisi} kayda garanti yazıldı`);
        setGarantiAcik(false);
        setOnizleme(null);
        tazele();
      } else {
        setOnizleme(r);
      }
    },
    onError: (e: Error) => message.error(e.message),
  });

  const kartAc = (r: EkipmanSatiri) => git(`/servis-ekipman/${r.id}${yolEki}`);
  const kartKapat = () => git(`/servis-ekipman${yolEki}`);

  const ekran = Grid.useBreakpoint();
  const kayitlar = liste.data?.kayitlar ?? [];
  const tek = secili.length === 1 ? (seciliSatirlar[secili[0]] ?? kayitlar.find((r) => r.id === secili[0])) : null;
  const servisAcabilir = yetkili("servis.yaz") || yetkili("servis.kurulum_ac");
  const secimVar = yazabilir || aktarabilir || servisAcabilir || yetkili("bakim.yaz");
  const kategoriler = kategorilerOlustur(
    EKIPMAN_TIPLERI.map((t) => ({ kod: t, ad: TIP_ETIKETLERI[t] ?? t })),
    (t) => (t === "XRAY" || t.includes("DEDEKTOR") || t === "DIGER_GUVENLIK" ? "kirmizi" : "yesil"),
    (t) => (t.startsWith("TELSIZ") || t === "ROLE_TEKRARLAYICI" ? <WifiOutlined /> : <SafetyOutlined />),
  );
  const durumGruplari = tekliGruplar(DURUM_ETIKETLERI);
  const ekSuzgecSayisi = [
    suzgec.birim,
    suzgec.garanti,
    suzgec.lokasyonsuz,
    suzgec.sozlesmesiz,
    suzgec.pasifler_dahil,
  ].filter(Boolean).length;
  const secimDegisti = (k: number[], satirlar: EkipmanSatiri[]) => {
    setSecili(k);
    // Sayfa değişse de seçili satırların verisi (müşteri, tür) elde kalsın.
    setSeciliSatirlar((eski) => {
      const yeni = { ...eski };
      for (const s of satirlar) if (s) yeni[s.id] = s;
      return yeni;
    });
  };

  const sutunlar: ColumnsType<EkipmanSatiri> = [
    {
      title: "Durum",
      key: "durum",
      width: 150,
      align: "center",
      render: (_, r) => (
        <DurumBaglantisi
          metin={DURUM_ETIKETLERI[r.lifecycle_status] ?? r.lifecycle_status}
          ton={r.lifecycle_status === "HURDA" ? "olumsuz" : !r.is_active || r.lifecycle_status === "DEVRE_DISI" ? "kapali" : undefined}
          onClick={() => kartAc(r)}
          alt={
            <>
              {r.serviste && <AltNot tur="uyari">SERVİSTE</AltNot>}
              {!r.is_active && <AltNot>PASİF</AltNot>}
            </>
          }
        />
      ),
    },
    {
      title: "Seri No",
      dataIndex: "serial_no",
      width: 150,
      align: "center",
      render: (s: string | null, r) =>
        s ? <NoRozeti no={s} onClick={() => kartAc(r)} /> : <Tag color="gold">eksik</Tag>,
    },
    {
      title: "Açıklama",
      key: "mm",
      width: 260,
      render: (_, r) => (
        <Aciklama
          metin={[r.brand, r.model].filter(Boolean).join(" ") || TIP_ETIKETLERI[r.equipment_type] || r.equipment_type}
          onClick={() => kartAc(r)}
        />
      ),
    },
    {
      title: "Ekipman",
      dataIndex: "equipment_type",
      width: 130,
      align: "center",
      responsive: ["lg"],
      render: (t: string) => <Kucuk>{TIP_ETIKETLERI[t] ?? t}</Kucuk>,
    },
    {
      title: "Mahal",
      key: "lok",
      width: 200,
      align: "center",
      responsive: ["md"],
      render: (_, r) => (
        <>
          <Kucuk kalin>{r.hesap_unvan}</Kucuk>
          {(r.lokasyon_adi || r.il) && <Kucuk>{[r.lokasyon_adi, r.il].filter(Boolean).join(" · ")}</Kucuk>}
        </>
      ),
    },
    {
      title: "Garanti",
      key: "garanti",
      width: 140,
      align: "center",
      responsive: ["sm"],
      render: (_, r) => (
        <>
          <GarantiEtiketi durum={r.garanti_durumu} />
          {r.warranty_end && <KucukGri>{gunu(r.warranty_end)}</KucukGri>}
        </>
      ),
    },
    {
      title: "Sözleşme",
      dataIndex: "sozlesme_sayisi",
      width: 90,
      align: "center",
      responsive: ["lg"],
      render: (n: number) => (n ? <Tag color="blue">{n}</Tag> : "—"),
    },
  ];

  const eylemler: FioriEylem[] = [
    {
      anahtar: "liste",
      ad: "Liste",
      menu: [
        ...(aktarabilir
          ? [{ key: "excel", label: `Excel'e aktar${secili.length ? ` (${secili.length} seçili)` : ""}` }]
          : []),
        { key: "kalite", label: kalitePaneli ? "Veri Kalitesi panelini kapat" : "Veri Kalitesi" },
        { key: "temizle", label: "Seçimi temizle", disabled: !secili.length },
        { type: "divider" as const },
        { key: "yenile", label: "Listeyi yenile" },
      ],
      onMenu: (k) => {
        if (k === "excel") window.open(ekipmanApi.excelYolu(suzgec, secili), "_blank");
        else if (k === "kalite") suzgecDegistir(suzgec, kalitePaneli ? { sekme: undefined } : { sekme: "kalite" });
        else if (k === "temizle") setSecili([]);
        else if (k === "yenile") void liste.refetch();
      },
    },
    {
      anahtar: "durum",
      ad: secili.length > 1 ? `Durum Değiştir (${secili.length})` : "Durum Değiştir",
      kisalt: true,
      gizli: !yazabilir,
      devreDisi: !secili.length || secili.length > TOPLU_UST_SINIR,
      ipucu: secili.length > TOPLU_UST_SINIR ? `En çok ${TOPLU_UST_SINIR} ekipman` : undefined,
      onClick: () => {
        topluForm.resetFields();
        setTopluDurumAcik(true);
      },
    },
    {
      anahtar: "garanti",
      ad: `Garanti Hesapla${secili.length ? ` (${secili.length})` : ""}`,
      kisalt: true,
      gizli: !yazabilir,
      onClick: () => {
        setOnizleme(null);
        setGarantiAcik(true);
        garanti.mutate(false);
      },
    },
    {
      anahtar: "duzenle",
      ad: "Kartı Aç / Düzenle",
      ikon: <EditOutlined />,
      yalnizIkon: true,
      devreDisi: !tek,
      onClick: () => tek && kartAc(tek),
    },
  ];
  const sagEylemler: FioriEylem[] = [
    {
      anahtar: "yeni",
      ad: "Yeni Ekipman",
      ikon: <PlusOutlined />,
      vurgulu: true,
      kisalt: true,
      gizli: !yazabilir,
      onClick: () => {
        setDuzenlenen(null);
        setFormAcik(true);
      },
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
          onChange={(v) => suzgecDegistir({ ...suzgec, birim: v })}
          options={BIRIM_KODLARI.map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] }))}
        />
      </Col>
      <Col xs={12} md={6}>
        <Select
          allowClear
          style={{ width: "100%" }}
          placeholder="Garanti"
          value={suzgec.garanti}
          onChange={(v) => suzgecDegistir({ ...suzgec, garanti: v })}
          options={Object.entries(GARANTI_ETIKETLERI).map(([k, v]) => ({ value: k, label: v }))}
        />
      </Col>
      <Col xs={24} md={12}>
        <Space wrap>
          <Checkbox
            checked={!!suzgec.lokasyonsuz}
            onChange={(e) => suzgecDegistir({ ...suzgec, lokasyonsuz: e.target.checked || undefined })}
          >
            Lokasyonsuz
          </Checkbox>
          <Checkbox
            checked={!!suzgec.sozlesmesiz}
            onChange={(e) => suzgecDegistir({ ...suzgec, sozlesmesiz: e.target.checked || undefined })}
          >
            Sözleşmesiz
          </Checkbox>
          <Checkbox
            checked={!!suzgec.pasifler_dahil}
            onChange={(e) => suzgecDegistir({ ...suzgec, pasifler_dahil: e.target.checked || undefined })}
          >
            Pasifler dahil
          </Checkbox>
        </Space>
      </Col>
    </Row>
  );

  const ustBilgi =
    suzgec.kalite || suzgec.kpi || Object.values(suzgec).some((v) => v !== undefined) || secili.length > 0 ? (
      <Space wrap>
        {suzgec.kalite && (
          <Tag closable onClose={() => suzgecDegistir({ ...suzgec, kalite: undefined })} color="gold">
            Kalite: {suzgec.kalite}
          </Tag>
        )}
        {suzgec.kpi && (
          <Tag closable onClose={() => suzgecDegistir({ ...suzgec, kpi: undefined })} color="orange">
            KPI: {ozet.data?.find((k) => k.kod === suzgec.kpi)?.baslik ?? suzgec.kpi}
          </Tag>
        )}
        {Object.values(suzgec).some((v) => v !== undefined) && (
          <Button
            size="small"
            type="link"
            onClick={() => {
              setAramaMetni("");
              suzgecDegistir({});
            }}
          >
            Süzgeci temizle
          </Button>
        )}
        {secili.length > 0 && (yazabilir || servisAcabilir || yetkili("bakim.yaz")) && (
          <>
            <Typography.Text>{secili.length} ekipman seçili</Typography.Text>
            <EkipmanTopluIslemleri
              secili={secili.map((i) => seciliSatirlar[i]).filter((s): s is EkipmanSatiri => !!s)}
              onBitti={() => {
                setSecili([]);
                tazele();
              }}
            />
          </>
        )}
      </Space>
    ) : null;

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      {(ozet.data ?? []).length > 0 && (
        <KutucukPano ekran="servis-ekipman">
          {(ozet.data ?? []).map((k) => (
            <KpiKutucugu
              key={k.kod}
              kod={k.kod}
              baslik={k.baslik}
              tanim={k.tanim}
              deger={k.deger}
              ikon={<DatabaseOutlined />}
              yol={`/servis-ekipman?kpi=${k.kod}`}
              vurgu={suzgec.kpi === k.kod ? "uyari" : "normal"}
            />
          ))}
        </KutucukPano>
      )}

      {kalitePaneli && (
        <EkipmanVeriKalitesi
          liste={kaliteListesi}
          onListe={(l) => suzgecDegistir(suzgec, { sekme: "kalite", liste: l })}
          onKalite={(kod) => suzgecDegistir({ kalite: kod }, { sekme: "kalite", liste: null })}
        />
      )}

      <ListeRaporu<EkipmanSatiri>
        kategoriBasligi="Tip"
        kategoriler={kategoriler}
        seciliKategori={suzgec.tip ?? TUMU_KATEGORISI.kod}
        onKategori={(k) => suzgecDegistir({ ...suzgec, tip: k === TUMU_KATEGORISI.kod ? undefined : k })}
        kayitSayisi={liste.data?.toplam}
        ustSag={
          <Input.Search
            allowClear
            size="small"
            style={{ width: ekran.sm ? 280 : 190 }}
            placeholder="Seri, model, müşteri, tesis, bölge…"
            value={aramaMetni}
            onChange={(e) => setAramaMetni(e.target.value)}
            onSearch={(q) => suzgecDegistir({ ...suzgec, q: q.trim() || undefined })}
          />
        }
        durumCubugu={{
          gruplar: durumGruplari,
          secili: suzgec.durum,
          onSec: (kod) => suzgecDegistir({ ...suzgec, durum: kod }),
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
        bosMetin={liste.isError ? (liste.error as Error).message : "Veri yok"}
        scrollX={ekran.lg ? 1200 : ekran.md ? 1000 : ekran.sm ? 820 : 640}
        secimModu={secimVar ? "coklu" : "yok"}
        secili={secili}
        onSecim={(k, satirlar) => secimDegisti(k as number[], satirlar)}
        onSatirAc={kartAc}
        sayfalama={{
          sayfa,
          boyut: SAYFA_BOYU,
          toplam: liste.data?.toplam ?? 0,
          onChange: setSayfa,
        }}
        eylemler={eylemler}
        sagEylemler={sagEylemler}
      />

      <EkipmanKarti
        ekipmanId={kartId}
        onKapat={kartKapat}
        onDuzenle={(k) => {
          setDuzenlenen(k);
          setFormAcik(true);
        }}
        onDegisti={tazele}
      />

      <EkipmanFormu
        acik={formAcik}
        kayit={duzenlenen}
        onKapat={() => setFormAcik(false)}
        onKaydedildi={(k) => {
          setFormAcik(false);
          tazele();
          void qc.invalidateQueries({ queryKey: ["servis-ekipman-kart", k.id] });
          void qc.invalidateQueries({ queryKey: ["servis-ekipman-degisiklik", k.id] });
          if (!duzenlenen) git(`/servis-ekipman/${k.id}${yolEki}`);
        }}
      />

      <Modal
        title={`Toplu durum değişikliği (${secili.length} ekipman)`}
        open={topluDurumAcik}
        onCancel={() => setTopluDurumAcik(false)}
        onOk={() => topluForm.submit()}
        okText="Uygula"
        cancelText="Vazgeç"
        confirmLoading={topluDurum.isPending}
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          Seçilenlerden biri bu duruma geçemiyorsa hiçbiri değişmez ve liste gösterilir.
        </Typography.Paragraph>
        <Form form={topluForm} layout="vertical" onFinish={(v) => topluDurum.mutate(v)}>
          <Form.Item name="hedef" label="Yeni durum" rules={[{ required: true }]}>
            <Select options={Object.entries(DURUM_ETIKETLERI).map(([k, v]) => ({ value: k, label: v }))} />
          </Form.Item>
          <Form.Item name="gerekce" label="Gerekçe" rules={[{ required: true, whitespace: true, min: 5 }]}>
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="Toplu garanti hesaplama"
        open={garantiAcik}
        onCancel={() => setGarantiAcik(false)}
        onOk={() => garanti.mutate(true)}
        okText="Uygula"
        okButtonProps={{ disabled: !onizleme || onizleme.satir_sayisi === 0 }}
        cancelText="Vazgeç"
        confirmLoading={garanti.isPending}
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          Yalnız garanti bitişi boş kayıtlar: başlangıç = kurulum (yoksa teslim) tarihi, süre = ürün
          kartındaki garanti ayı (ürün yoksa varsayılan ayar). Kaynak "Hesaplandı" yazılır; belgeli
          kayıtlara dokunulmaz.
        </Typography.Paragraph>
        {onizleme && (
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Typography.Text>
              <strong>{onizleme.satir_sayisi}</strong> kayda garanti yazılacak;{" "}
              {onizleme.baslangic_tarihsiz} kayıtta kurulum/teslim tarihi olmadığı için hesaplanamaz.
            </Typography.Text>
            <Table
              size="small"
              rowKey="id"
              pagination={false}
              scroll={{ y: 240 }}
              dataSource={onizleme.ornekler}
              columns={[
                { title: "#", dataIndex: "id", width: 70 },
                { title: "Seri", dataIndex: "seri", render: (s) => s ?? "—" },
                { title: "Başlangıç", dataIndex: "baslangic", render: tarih },
                { title: "Bitiş", dataIndex: "bitis", render: tarih },
                { title: "Ay", dataIndex: "ay", width: 50 },
              ]}
            />
          </Space>
        )}
      </Modal>
    </Space>
  );
}
