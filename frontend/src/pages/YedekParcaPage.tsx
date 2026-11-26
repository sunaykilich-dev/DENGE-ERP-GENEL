/**
 * Yedek Parça — servis stoğu, hareket geçmişi, parça talepleri, sayım ve
 * servis depoları (TS-130…138).
 *
 * - Üstte tıklanabilir Fiori KPI kutucukları (`KpiKutucugu`): sayı sunucudan
 *   (`/stok/ozet`), tıklama aynı süzgeçle sekmeyi açar ("sayı = liste").
 * - Stok: parça başına toplam (yalnız erişilebilir servis depoları) + depo
 *   kırılımı; durum (Stok yok / Az stok / Yeterli) sunucunun TEK kuralından.
 * - Hareketler: tür, depo, parça, iş no, belge no (ILIKE), tarih süzgeci;
 *   sunucu sayfalaması; Excel `parca.gor + servis_rapor.disaaktar`.
 *   Maliyet sütunu yalnız sunucu `unit_cost` anahtarını gönderdiyse.
 * - Giriş (belge no), zayi, transfer `parca.yonet`; işe çıkış/iade/talep
 *   `parca.kullan` — servis işi, planlı bakım formu ve atölye kaydındaki
 *   `ServisParcalari` bölümünde. Eski "İş Emri Parçaları" sekmesi (iş arama +
 *   aynı bölüm) kaldırıldı (UI/UX denetimi T10); eski `?sekme=isler&so=<id>`
 *   bağlantısı işin kartına, `so`suz olanı varsayılan sekmeye yönlenir.
 * - Sayım: açılış anı görüntüsü, sayılan adet girişi, gerekçeli onay; sayım
 *   açıkken stok değiştiyse sunucu sapmaları döndürür, kullanıcı değişimi
 *   kabul ederek yeniden onaylar. Onaysız sayım hiçbir bakiyeyi değiştirmez.
 * - Depolar: servis deposu ve teknisyen araç deposu tanımı `sistem.ayar`.
 * - 375 px'te tablolar yatay kaydırılır, sayfa kaymaz.
 */
import {
  DownloadOutlined,
  EditOutlined,
  FilePdfOutlined,
  InboxOutlined,
  PlusOutlined,
  RollbackOutlined,
  StopOutlined,
  SwapOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnsType } from "antd/es/table";
import {
  Alert,
  App,
  Button,
  Checkbox,
  Col,
  DatePicker,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";

import { BIRIM_ETIKETLERI, BIRIM_KODLARI, personelApi } from "../api/personel";
import {
  type Depo,
  HAREKET_TURU_ADLARI,
  type Hareket,
  type HareketSuzgeci,
  KULLANIM_DURUM_ADLARI,
  type Kullanim,
  OLCU_BIRIMLERI,
  olcuBirimiAdi,
  parcaApi,
  parcaHatasi,
  SAYIM_DURUM_ADLARI,
  type Sayim,
  type SayimSatiri,
  STOK_DURUM_ADLARI,
  type StokSatiri,
  type StokSuzgeci,
  TALEP_DURUM_ADLARI,
  type Talep,
} from "../api/yedekParca";
import { useAuth } from "../auth/AuthContext";
import { useSirket } from "../auth/SirketContext";
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
  saati,
  tekliGruplar,
} from "../fiori/ListeOgeleri";
import ListeRaporu from "../fiori/ListeRaporu";
import ParcaHareketPenceresi, { type ParcaHareketTuru } from "../components/ParcaHareketPenceresi";
import ParcaTuketimRaporu from "../components/ParcaTuketimRaporu";

const SAYFA = 25;
const zaman = (v: string | null | undefined) => (v ? dayjs(v).format("DD.MM.YYYY HH:mm") : "—");
const para = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 4 });
const indir = (yol: string) => window.open(yol, "_blank");

export default function YedekParcaPage() {
  const { yetkili } = useAuth();
  const [params, setParams] = useSearchParams();
  const sekme = params.get("sekme") ?? "stok";
  const [pencere, setPencere] = useState<ParcaHareketTuru | null>(null);
  const [kartAcik, setKartAcik] = useState(false);

  const sekmeDegistir = (k: string) => setParams(new URLSearchParams({ sekme: k }));

  // Kaldırılan "İş Emri Parçaları" sekmesinin eski bağlantıları.
  if (sekme === "isler") {
    const so = Number(params.get("so"));
    return (
      <Navigate replace to={Number.isInteger(so) && so > 0 ? `/servis-isleri/${so}` : "/yedek-parca"} />
    );
  }

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      {yetkili("parca.yonet") && (
        <div className="fm-arac-cubugu">
          <span className="fm-arac-baslik">Stok İşlemleri</span>
          <Button type="primary" onClick={() => setPencere("GIRIS")}>
            Giriş
          </Button>
          <Button onClick={() => setPencere("TRANSFER")}>Transfer</Button>
          <Button onClick={() => setPencere("ZAYI")}>Zayi</Button>
          <span className="fm-bosluk" />
          <Button icon={<PlusOutlined />} onClick={() => setKartAcik(true)}>
            Yeni parça kartı
          </Button>
        </div>
      )}
      <div>
        <Tabs
          activeKey={sekme}
          onChange={sekmeDegistir}
          items={[
            { key: "stok", label: "Stok", children: <StokSekmesi /> },
            { key: "hareketler", label: "Hareketler", children: <HareketSekmesi /> },
            { key: "talepler", label: "Parça Talepleri", children: <TalepSekmesi /> },
            { key: "kullanim", label: "Sahada Kullanım", children: <KullanimSekmesi /> },
            { key: "sayimlar", label: "Sayım", children: <SayimSekmesi /> },
            { key: "depolar", label: "Depolar", children: <DepoSekmesi /> },
            ...(yetkili("servis_rapor.gor")
              ? [{ key: "tuketim", label: "Tüketim raporu", children: <ParcaTuketimRaporu /> }]
              : []),
          ]}
        />
      </div>
      <ParcaHareketPenceresi tur={pencere} onKapat={() => setPencere(null)} />
      <KartPenceresi acik={kartAcik} onKapat={() => setKartAcik(false)} />
    </Space>
  );
}

// --- Stok ---------------------------------------------------------------------

function useDepolar(pasifler = false) {
  return useQuery({ queryKey: ["parca", "depolar", pasifler], queryFn: () => parcaApi.depolar(pasifler) });
}

function StokSekmesi() {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [sayfa, setSayfa] = useState(1);
  const [duzenle, setDuzenle] = useState<StokSatiri | null>(null);
  const [secili, setSecili] = useState<number[]>([]);
  const [suzgecAcik, setSuzgecAcik] = useState(false);
  const depolar = useDepolar();
  const s: StokSuzgeci = {
    q: params.get("q") ?? undefined,
    depo_id: params.get("depo_id") ? Number(params.get("depo_id")) : undefined,
    durum: params.get("durum") ?? undefined,
    esikli: params.get("esikli") === "1",
    pasifler: params.get("pasifler") === "1",
  };
  const guncelle = (k: string, v: string | undefined) => {
    const yeni = new URLSearchParams(params);
    yeni.set("sekme", "stok");
    if (v) yeni.set(k, v);
    else yeni.delete(k);
    setParams(yeni);
    setSayfa(1);
  };
  const liste = useQuery({
    queryKey: ["parca", "stok", s, sayfa],
    queryFn: () => parcaApi.stok(s, SAYFA, (sayfa - 1) * SAYFA),
  });
  const [form] = Form.useForm<{ min_stok: number | null; birim: string | null }>();
  const kaydet = useMutation({
    mutationFn: (d: { min_stok: number | null; birim: string | null }) =>
      parcaApi.kartGuncelle({ product_id: duzenle!.product_id, version: duzenle!.version, ...d }),
    onSuccess: async () => {
      message.success("Parça kartı güncellendi");
      setDuzenle(null);
      await qc.invalidateQueries({ queryKey: ["parca"] });
    },
    onError: (e) => void message.error(parcaHatasi(e).mesaj),
  });

  const kayitlar = liste.data?.kayitlar ?? [];
  const tek = kayitlar.find((r) => r.product_id === secili[0]) ?? null;
  const yonetir = yetkili("parca.yonet");
  const kategoriler = kategorilerOlustur(
    (depolar.data ?? []).map((d) => ({ kod: String(d.id), ad: d.name })),
    () => "yesil",
    () => <InboxOutlined />,
  );
  const stokAlanlari = (r: StokSatiri) => {
    setDuzenle(r);
    form.setFieldsValue({ min_stok: r.min_stok, birim: r.birim });
  };
  const sutunlar: ColumnsType<StokSatiri> = [
    {
      title: "Durum",
      key: "d",
      width: 120,
      align: "center",
      render: (_, r) => (
        <DurumBaglantisi
          metin={STOK_DURUM_ADLARI[r.durum] ?? r.durum}
          ton={r.durum === "YOK" ? "olumsuz" : undefined}
          alt={!r.is_active ? <AltNot>PASİF</AltNot> : undefined}
          onClick={yonetir ? () => stokAlanlari(r) : undefined}
        />
      ),
    },
    { title: "Kod", dataIndex: "kod", key: "kod", width: 140, align: "center", render: (v: string) => <NoRozeti no={v} /> },
    { title: "Açıklama", key: "ad", width: 260, render: (_, r) => <Aciklama metin={r.ad} /> },
    {
      title: "Marka /\nModel",
      key: "mm",
      width: 160,
      align: "center",
      responsive: ["md"],
      render: (_, r) => <Kucuk>{[r.marka, r.model].filter(Boolean).join(" ") || null}</Kucuk>,
    },
    { title: "Toplam", key: "t", width: 90, align: "right", render: (_, r) => <b>{`${r.toplam} ${olcuBirimiAdi(r.birim)}`}</b> },
    { title: "Asgari", key: "a", width: 70, align: "right", responsive: ["sm"], render: (_, r) => r.min_stok ?? "—" },
    {
      title: "Depolar",
      key: "dp",
      width: 240,
      align: "center",
      responsive: ["lg"],
      render: (_, r) =>
        r.depolar.length ? (
          <KucukGri>{r.depolar.map((d) => `${d.depo_adi}: ${d.adet}`).join(" · ")}</KucukGri>
        ) : (
          <KucukGri />
        ),
    },
  ];
  const durumGruplari = tekliGruplar(STOK_DURUM_ADLARI);

  return (
    <>
      {liste.isError && <Alert type="error" showIcon message={parcaHatasi(liste.error).mesaj} />}
      <ListeRaporu<StokSatiri>
        kategoriBasligi="Depo"
        kategoriler={kategoriler}
        seciliKategori={s.depo_id ? String(s.depo_id) : TUMU_KATEGORISI.kod}
        onKategori={(k) => guncelle("depo_id", k === TUMU_KATEGORISI.kod ? undefined : k)}
        kayitSayisi={liste.data?.toplam}
        ustSag={
          <Input.Search
            allowClear
            size="small"
            placeholder="Kod, ad, marka, model"
            defaultValue={s.q}
            onSearch={(v) => guncelle("q", v.trim() || undefined)}
            style={{ width: 220 }}
          />
        }
        durumCubugu={{
          gruplar: durumGruplari,
          secili: s.durum,
          onSec: (k) => guncelle("durum", k),
          onYenile: () => void liste.refetch(),
          yenileniyor: liste.isFetching,
          onSuzgec: () => setSuzgecAcik(!suzgecAcik),
          suzgecAcik,
          suzgecSayisi: [s.esikli, s.pasifler].filter(Boolean).length,
        }}
        suzgecPaneli={
          <Space wrap>
            <Checkbox checked={s.esikli} onChange={(e) => guncelle("esikli", e.target.checked ? "1" : undefined)}>
              Yalnız asgari stoku tanımlı
            </Checkbox>
            <Checkbox checked={s.pasifler} onChange={(e) => guncelle("pasifler", e.target.checked ? "1" : undefined)}>
              Pasifler dahil
            </Checkbox>
          </Space>
        }
        sutunlar={sutunlar}
        veri={kayitlar}
        satirAnahtari="product_id"
        yukleniyor={liste.isFetching}
        scrollX={1000}
        secili={secili}
        onSecim={(k) => setSecili(k as number[])}
        onSatirAc={yonetir ? stokAlanlari : undefined}
        sayfalama={{ sayfa, boyut: SAYFA, toplam: liste.data?.toplam ?? 0, onChange: setSayfa }}
        eylemler={[
          {
            anahtar: "liste",
            ad: "Liste",
            menu: [
              ...(yetkili("parca.gor", "servis_rapor.disaaktar") ? [{ key: "excel", label: "Excel'e aktar" }] : []),
              { key: "yenile", label: "Listeyi yenile" },
            ],
            onMenu: (k) => (k === "excel" ? indir(parcaApi.stokExcelYolu(s)) : void liste.refetch()),
          },
          {
            anahtar: "alanlar",
            ad: "Stok Alanları",
            ikon: <EditOutlined />,
            kisalt: true,
            gizli: !yonetir,
            devreDisi: !tek,
            onClick: () => tek && stokAlanlari(tek),
          },
          {
            anahtar: "excel",
            ad: "Excel",
            ikon: <DownloadOutlined />,
            yalnizIkon: true,
            gizli: !yetkili("parca.gor", "servis_rapor.disaaktar"),
            onClick: () => indir(parcaApi.stokExcelYolu(s)),
          },
        ]}
      />
      <Modal
        open={duzenle !== null}
        title={duzenle ? `${duzenle.kod} — stok alanları` : ""}
        onCancel={() => setDuzenle(null)}
        onOk={() => form.submit()}
        okText="Kaydet"
        cancelText="Vazgeç"
        confirmLoading={kaydet.isPending}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={(d) => kaydet.mutate(d)}>
          <Form.Item name="min_stok" label="Asgari stok (az stok uyarısı eşiği)">
            <InputNumber min={0} max={1_000_000} precision={0} />
          </Form.Item>
          <Form.Item name="birim" label="Ölçü birimi">
            <Select allowClear options={OLCU_BIRIMLERI.map((b) => ({ value: b, label: olcuBirimiAdi(b) }))} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

// --- Hareketler ---------------------------------------------------------------

function HareketSekmesi() {
  const { yetkili } = useAuth();
  const { message, modal } = App.useApp();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [sayfa, setSayfa] = useState(1);
  const depolar = useDepolar(true);
  const [secili, setSecili] = useState<number[]>([]);
  const [suzgecAcik, setSuzgecAcik] = useState(false);
  const s: HareketSuzgeci = {
    tur: params.get("tur") ?? undefined,
    depo_id: params.get("depo_id") ? Number(params.get("depo_id")) : undefined,
    so_no: params.get("so_no") ?? undefined,
    belge: params.get("belge") ?? undefined,
    bas: params.get("bas") ?? undefined,
    bit: params.get("bit") ?? undefined,
  };
  const guncelle = (degisen: Record<string, string | undefined>) => {
    const yeni = new URLSearchParams(params);
    yeni.set("sekme", "hareketler");
    for (const [k, v] of Object.entries(degisen)) {
      if (v) yeni.set(k, v);
      else yeni.delete(k);
    }
    setParams(yeni);
    setSayfa(1);
  };
  const liste = useQuery({
    queryKey: ["parca", "hareketler", s, sayfa],
    queryFn: () => parcaApi.hareketler(s, SAYFA, (sayfa - 1) * SAYFA),
  });
  const tersKayit = useMutation({
    mutationFn: ({ id, gerekce }: { id: number; gerekce: string }) => parcaApi.tersKayit(id, gerekce),
    onSuccess: async () => {
      message.success("Ters kayıt yazıldı");
      await qc.invalidateQueries({ queryKey: ["parca"] });
    },
    onError: (e) => void message.error(parcaHatasi(e).mesaj),
  });
  const tersSor = (h: Hareket) => {
    let metin = "";
    modal.confirm({
      title: `Ters kayıt: ${h.tur_adi} — ${h.kod} (${h.adet})`,
      content: (
        <Input.TextArea
          rows={2}
          maxLength={300}
          placeholder="Gerekçe (en az 3 karakter)"
          onChange={(e) => {
            metin = e.target.value;
          }}
        />
      ),
      okText: "Ters kaydı yaz",
      cancelText: "Vazgeç",
      onOk: () => {
        if (metin.trim().length < 3) {
          message.error("Gerekçe en az 3 karakter olmalı");
          return Promise.reject(new Error("gerekçe"));
        }
        tersKayit.mutate({ id: h.id, gerekce: metin.trim() });
        return Promise.resolve();
      },
    });
  };
  const maliyetli = (liste.data?.kayitlar ?? []).some((h) => "unit_cost" in h);
  const aralik: [Dayjs | null, Dayjs | null] | null =
    s.bas || s.bit ? [s.bas ? dayjs(s.bas) : null, s.bit ? dayjs(s.bit) : null] : null;

  const kayitlar = liste.data?.kayitlar ?? [];
  const tek = kayitlar.find((h) => h.id === secili[0]) ?? null;
  const tersYapilabilir = (h: Hareket) =>
    h.tur !== "TERS_KAYIT" && h.tur !== "SAYIM_FAZLASI" && h.tur !== "SAYIM_EKSIGI" && !h.ters_kaydi_var;
  const aktarir = yetkili("parca.gor", "servis_rapor.disaaktar");
  const kategoriler = kategorilerOlustur(
    Object.entries(HAREKET_TURU_ADLARI).map(([kod, ad]) => ({ kod, ad })),
    (k) => (k === "ZAYI" || k === "CIKIS_SERVIS" || k === "TRANSFER_CIKIS" || k === "SAYIM_EKSIGI" || k === "TERS_KAYIT" ? "kirmizi" : "yesil"),
    () => <SwapOutlined />,
  );
  const sutunlar: ColumnsType<Hareket> = [
    {
      title: "Hareket",
      key: "tur",
      width: 150,
      align: "center",
      render: (_, h) => (
        <DurumBaglantisi
          metin={h.tur_adi}
          ton={h.adet < 0 ? "olumsuz" : undefined}
          alt={h.ters_kaydi_var ? <AltNot>TERS KAYDI VAR</AltNot> : undefined}
        />
      ),
    },
    {
      title: "Belge No",
      key: "b",
      width: 140,
      align: "center",
      render: (_, h) => (h.document_no ? <NoRozeti no={h.document_no} /> : <KucukGri />),
    },
    { title: "Tarih", key: "t", width: 100, align: "center", render: (_, h) => gunu(h.created_at) },
    { title: "Saat", key: "s", width: 90, align: "center", responsive: ["md"], render: (_, h) => saati(h.created_at) },
    { title: "Açıklama", key: "p", width: 240, render: (_, h) => <Aciklama metin={`${h.kod} — ${h.ad}`} /> },
    {
      title: "Adet",
      key: "a",
      width: 90,
      align: "right",
      render: (_, h) => <b>{`${h.adet > 0 ? "+" : ""}${h.adet} ${olcuBirimiAdi(h.birim)}`}</b>,
    },
    { title: "Depo", dataIndex: "depo_adi", key: "d", width: 150, align: "center", responsive: ["sm"], render: (v: string) => <Kucuk>{v}</Kucuk> },
    { title: "İş No", key: "so", width: 150, align: "center", responsive: ["lg"], render: (_, h) => <Kucuk>{h.so_no}</Kucuk> },
    { title: "Not", key: "n", width: 180, align: "center", responsive: ["xl"], render: (_, h) => <KucukGri>{h.notes}</KucukGri> },
    { title: "Kullanıcı", key: "k", width: 140, align: "center", responsive: ["lg"], render: (_, h) => <KucukGri>{h.kullanici}</KucukGri> },
    ...(maliyetli
      ? [
          { title: "Birim\nMaliyet", key: "m", width: 100, align: "right" as const, render: (_: unknown, h: Hareket) => para(h.unit_cost) },
          { title: "Tutar", key: "tt", width: 100, align: "right" as const, render: (_: unknown, h: Hareket) => para(h.tutar) },
        ]
      : []),
  ];

  return (
    <ListeRaporu<Hareket>
      kategoriBasligi="Tür"
      kategoriler={kategoriler}
      seciliKategori={s.tur ?? TUMU_KATEGORISI.kod}
      onKategori={(k) => guncelle({ tur: k === TUMU_KATEGORISI.kod ? undefined : k })}
      kayitSayisi={liste.data?.toplam}
      ustSag={
        <Input.Search
          allowClear
          size="small"
          placeholder="İş no"
          defaultValue={s.so_no}
          onSearch={(v) => guncelle({ so_no: v.trim() || undefined })}
          style={{ width: 160 }}
        />
      }
      durumCubugu={{
        gruplar: [],
        onSec: () => undefined,
        onYenile: () => void liste.refetch(),
        yenileniyor: liste.isFetching,
        onSuzgec: () => setSuzgecAcik(!suzgecAcik),
        suzgecAcik,
        suzgecSayisi: [s.depo_id, s.belge, s.bas, s.bit].filter(Boolean).length,
      }}
      suzgecPaneli={
        <Space wrap>
          <Select
            allowClear
            placeholder="Depo"
            value={s.depo_id}
            onChange={(v) => guncelle({ depo_id: v ? String(v) : undefined })}
            options={(depolar.data ?? []).map((d) => ({ value: d.id, label: d.name }))}
            style={{ width: 180 }}
          />
          <Input.Search
            allowClear
            placeholder="Belge no"
            defaultValue={s.belge}
            onSearch={(v) => guncelle({ belge: v.trim() || undefined })}
            style={{ width: 160 }}
          />
          <DatePicker.RangePicker
            value={aralik}
            format="DD.MM.YYYY"
            allowEmpty={[true, true]}
            onChange={(v) => guncelle({ bas: v?.[0]?.format("YYYY-MM-DD"), bit: v?.[1]?.format("YYYY-MM-DD") })}
          />
        </Space>
      }
      sutunlar={sutunlar}
      veri={kayitlar}
      satirAnahtari="id"
      yukleniyor={liste.isFetching}
      bosMetin={liste.isError ? parcaHatasi(liste.error).mesaj : "Veri yok"}
      scrollX={maliyetli ? 1500 : 1300}
      secili={secili}
      onSecim={(k) => setSecili(k as number[])}
      sayfalama={{ sayfa, boyut: SAYFA, toplam: liste.data?.toplam ?? 0, onChange: setSayfa }}
      eylemler={[
        {
          anahtar: "liste",
          ad: "Liste",
          menu: [
            ...(aktarir ? [{ key: "excel", label: "Excel'e aktar" }] : []),
            { key: "yenile", label: "Listeyi yenile" },
          ],
          onMenu: (k) => (k === "excel" ? indir(parcaApi.hareketExcelYolu(s)) : void liste.refetch()),
        },
        {
          anahtar: "ters",
          ad: "Ters Kayıt",
          ikon: <RollbackOutlined />,
          kisalt: true,
          tehlikeli: true,
          gizli: !yetkili("parca.yonet"),
          devreDisi: !tek || !tersYapilabilir(tek),
          onClick: () => tek && tersSor(tek),
        },
        {
          anahtar: "fis",
          ad: "Parça Fişi (PDF)",
          ikon: <FilePdfOutlined />,
          kisalt: true,
          devreDisi: !tek || tek.tur === "TERS_KAYIT",
          onClick: () => tek && window.open(parcaApi.fisYolu(tek.id), "_blank"),
        },
        {
          anahtar: "excel",
          ad: "Excel",
          ikon: <DownloadOutlined />,
          yalnizIkon: true,
          gizli: !aktarir,
          onClick: () => indir(parcaApi.hareketExcelYolu(s)),
        },
      ]}
    />
  );
}

// --- Talepler -----------------------------------------------------------------

function TalepSekmesi() {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [sayfa, setSayfa] = useState(1);
  const durum = params.get("durum") ?? undefined;
  const benim = params.get("benim") === "1";
  const [secili, setSecili] = useState<number[]>([]);
  const guncelle = (k: string, v: string | undefined) => {
    const yeni = new URLSearchParams(params);
    yeni.set("sekme", "talepler");
    if (v) yeni.set(k, v);
    else yeni.delete(k);
    setParams(yeni);
    setSayfa(1);
  };
  const liste = useQuery({
    queryKey: ["parca", "talepler", durum, benim, sayfa],
    queryFn: () => parcaApi.talepler({ durum, benim }, SAYFA, (sayfa - 1) * SAYFA),
  });
  const tazele = async (mesaj: string) => {
    message.success(mesaj);
    await qc.invalidateQueries({ queryKey: ["parca"] });
  };
  const iptal = useMutation({
    mutationFn: (id: number) => parcaApi.talepIptal(id, "Kullanıcı iptal etti"),
    onSuccess: () => tazele("Talep iptal edildi"),
    onError: (e) => void message.error(parcaHatasi(e).mesaj),
  });
  const onayla = useMutation({
    mutationFn: (id: number) => parcaApi.talepOnayla(id),
    onSuccess: () => tazele("Talep onaylandı; depoya iletildi"),
    onError: (e) => void message.error(parcaHatasi(e).mesaj),
  });
  const [redAcik, setRedAcik] = useState(false);
  const [redNedeni, setRedNedeni] = useState("");
  const reddet = useMutation({
    mutationFn: ({ id, neden }: { id: number; neden: string }) => parcaApi.talepReddet(id, neden),
    onSuccess: async () => {
      setRedAcik(false);
      setRedNedeni("");
      await tazele("Talep reddedildi");
    },
    onError: (e) => void message.error(parcaHatasi(e).mesaj),
  });
  const teslim = useMutation({
    mutationFn: (id: number) => parcaApi.talepTeslim(id),
    onSuccess: () => tazele("Parça teslim edildi; stoktan çıkış yapıldı"),
    onError: (e) => void message.error(parcaHatasi(e).mesaj),
  });
  const kayitlar = liste.data?.kayitlar ?? [];
  const tek = kayitlar.find((t) => t.id === secili[0]) ?? null;
  const kullanir = yetkili("parca.kullan");
  const onaylayici = yetkili("parca.talep_onay");
  const depocu = yetkili("parca.yonet");
  const sutunlar: ColumnsType<Talep> = [
    {
      title: "Durum",
      key: "d",
      width: 140,
      align: "center",
      render: (_, t) => (
        <DurumBaglantisi
          metin={TALEP_DURUM_ADLARI[t.durum] ?? t.durum}
          ton={
            t.durum === "IPTAL" || t.durum === "REDDEDILDI"
              ? "olumsuz"
              : t.durum === "ACIK" || t.durum === "ONAY_BEKLIYOR"
                ? undefined
                : "kapali"
          }
          alt={
            t.beklemeye_bagli && (t.durum === "ACIK" || t.durum === "ONAY_BEKLIYOR") ? (
              <AltNot tur="uyari">İŞ BEKLİYOR</AltNot>
            ) : undefined
          }
        />
      ),
    },
    {
      title: "İş No",
      key: "so",
      width: 170,
      align: "center",
      render: (_, t) =>
        t.ikmal ? (
          <Tag color="purple">İkmal → {t.hedef_depo_adi}</Tag>
        ) : (
          <IsNoBaglantisi soId={t.service_order_id} soNo={t.so_no} />
        ),
    },
    { title: "Talep\nTarihi", key: "t", width: 100, align: "center", render: (_, t) => gunu(t.created_at) },
    {
      title: "Talep\nSaati",
      key: "ts",
      width: 90,
      align: "center",
      responsive: ["md"],
      render: (_, t) => saati(t.created_at),
    },
    { title: "Açıklama", key: "p", width: 260, render: (_, t) => <Aciklama metin={`${t.kod} — ${t.ad}`} /> },
    { title: "Adet", dataIndex: "adet", key: "a", width: 70, align: "right" },
    {
      title: "Depo",
      key: "dp",
      width: 150,
      align: "center",
      responsive: ["sm"],
      render: (_, t) => <Kucuk>{t.depo_adi ?? "—"}</Kucuk>,
    },
    {
      title: "Talep Eden /\nOnaylayan",
      key: "kim",
      width: 160,
      align: "center",
      responsive: ["md"],
      render: (_, t) => (
        <KucukGri>
          {t.talep_eden ?? "—"}
          {t.onaylayan ? ` / ${t.onaylayan}` : ""}
        </KucukGri>
      ),
    },
    {
      title: "Teslim",
      key: "k",
      width: 140,
      align: "center",
      responsive: ["sm"],
      render: (_, t) => <KucukGri>{t.karsilanma_at ? zaman(t.karsilanma_at) : null}</KucukGri>,
    },
    {
      title: "Not / Red-İptal Nedeni",
      key: "n",
      width: 200,
      align: "center",
      responsive: ["sm"],
      render: (_, t) => <KucukGri>{t.red_nedeni ?? t.iptal_nedeni ?? t.notes}</KucukGri>,
    },
  ];
  return (
    <>
      {kullanir && <IkmalOnerisiKutusu />}
      <Typography.Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
        Teknisyen parçayı işin biriminin deposundan talep eder; talep şefin onayına düşer (tek adım).
        Onaylanan talebi depo teslim eder ve stoktan işe çıkış yapılır. Reddedilen talep gerekçesiyle
        teknisyene görünür; iş kapanınca açık talepler iptal olur.
      </Typography.Text>
      <ListeRaporu<Talep>
        kayitSayisi={liste.data?.toplam}
        durumCubugu={{
          gruplar: tekliGruplar(TALEP_DURUM_ADLARI),
          secili: durum,
          onSec: (k) => guncelle("durum", k),
          banaAit: benim,
          onBanaAit: (v) => guncelle("benim", v ? "1" : undefined),
          banaAitIpucu: "Yalnız benim taleplerim",
          onYenile: () => void liste.refetch(),
          yenileniyor: liste.isFetching,
        }}
        sutunlar={sutunlar}
        veri={kayitlar}
        satirAnahtari="id"
        yukleniyor={liste.isFetching}
        bosMetin={liste.isError ? parcaHatasi(liste.error).mesaj : "Veri yok"}
        scrollX={1000}
        secili={secili}
        onSecim={(k) => setSecili(k as number[])}
        sayfalama={{ sayfa, boyut: SAYFA, toplam: liste.data?.toplam ?? 0, onChange: setSayfa }}
        eylemler={[
          {
            anahtar: "liste",
            ad: "Liste",
            menu: [{ key: "yenile", label: "Listeyi yenile" }],
            onMenu: () => void liste.refetch(),
          },
          {
            anahtar: "onayla",
            ad: "Onayla",
            gizli: !onaylayici,
            devreDisi: !tek || tek.durum !== "ONAY_BEKLIYOR",
            yukleniyor: onayla.isPending,
            onClick: () => tek && onayla.mutate(tek.id),
          },
          {
            anahtar: "reddet",
            ad: "Reddet",
            tehlikeli: true,
            gizli: !onaylayici,
            devreDisi: !tek || tek.durum !== "ONAY_BEKLIYOR",
            onClick: () => setRedAcik(true),
          },
          {
            anahtar: "teslim",
            ad: "Teslim Et",
            gizli: !depocu,
            devreDisi: !tek || tek.durum !== "ACIK" || tek.depo_id == null,
            yukleniyor: teslim.isPending,
            onClick: () => tek && teslim.mutate(tek.id),
          },
          {
            anahtar: "iptal",
            ad: "Talebi İptal Et",
            ikon: <StopOutlined />,
            yalnizIkon: true,
            tehlikeli: true,
            gizli: !kullanir,
            devreDisi: !tek || (tek.durum !== "ACIK" && tek.durum !== "ONAY_BEKLIYOR"),
            yukleniyor: iptal.isPending,
            onClick: () => tek && iptal.mutate(tek.id),
          },
        ]}
      />
      <Modal
        open={redAcik}
        title="Talebi reddet"
        okText="Reddet"
        okButtonProps={{ danger: true, disabled: redNedeni.trim().length < 3 }}
        cancelText="Vazgeç"
        confirmLoading={reddet.isPending}
        onCancel={() => setRedAcik(false)}
        onOk={() => tek && reddet.mutate({ id: tek.id, neden: redNedeni.trim() })}
        destroyOnHidden
      >
        <Input.TextArea
          rows={3}
          maxLength={200}
          placeholder="Red gerekçesi (teknisyen görür)"
          value={redNedeni}
          onChange={(e) => setRedNedeni(e.target.value)}
        />
      </Modal>
    </>
  );
}

// --- S5.3 Araç ikmal önerisi -----------------------------------------------------

/**
 * Araç deposunda son 30 günde işe çıkılan ve bakiyesi bu tüketimin altına
 * düşen parçalar. Tek tıkla ikmal talebi: amir onaylı talep akışından geçer,
 * depo teslimi birim deposundan araca transferdir.
 */
function IkmalOnerisiKutusu() {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const oneriler = useQuery({ queryKey: ["parca", "ikmal-onerisi"], queryFn: parcaApi.ikmalOnerisi });
  const talep = useMutation({
    mutationFn: (g: { hedef_depo_id: number; product_id: number; adet: number }) => parcaApi.ikmalTalebi(g),
    onSuccess: async (t) => {
      message.success(t.durum === "ONAY_BEKLIYOR" ? "İkmal talebi amir onayına gönderildi" : "İkmal talebi depoya iletildi");
      await qc.invalidateQueries({ queryKey: ["parca"] });
    },
    onError: (e) => void message.error(parcaHatasi(e).mesaj),
  });
  const veri = oneriler.data ?? [];
  if (!veri.length) return null;
  return (
    <Alert
      type="info"
      showIcon
      style={{ marginBottom: 12 }}
      message={`Araç deposu ikmal önerisi (${veri.length})`}
      description={
        <Table
          size="small"
          rowKey={(r) => `${r.hedef_depo_id}-${r.product_id}`}
          pagination={false}
          dataSource={veri}
          scroll={{ x: true }}
          columns={[
            { title: "Araç", dataIndex: "hedef_depo_adi", key: "d" },
            { title: "Parça", key: "p", render: (_, r) => `${r.kod} — ${r.ad}` },
            { title: "Araçta", dataIndex: "bakiye", key: "b", align: "right" },
            { title: "30 gün tüketim", dataIndex: "tuketim", key: "t", align: "right" },
            {
              title: "",
              key: "i",
              render: (_, r) => (
                <Button
                  size="small"
                  type="primary"
                  loading={talep.isPending}
                  onClick={() =>
                    talep.mutate({ hedef_depo_id: r.hedef_depo_id, product_id: r.product_id, adet: r.onerilen_adet })
                  }
                >
                  {r.onerilen_adet} {olcuBirimiAdi(r.birim)} talep et
                </Button>
              ),
            },
          ]}
        />
      }
    />
  );
}

// --- S5.1 Sahada kullanım (araç deposundan işe çıkış) -----------------------------------

function KullanimSekmesi() {
  const { yetkili, kullanici } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [sayfa, setSayfa] = useState(1);
  const [secili, setSecili] = useState<number[]>([]);
  const durum = params.get("durum") ?? undefined;
  const [redAcik, setRedAcik] = useState(false);
  const [zimmetAcik, setZimmetAcik] = useState(false);
  const [metin, setMetin] = useState("");
  const guncelle = (v: string | undefined) => {
    const yeni = new URLSearchParams(params);
    yeni.set("sekme", "kullanim");
    if (v) yeni.set("durum", v);
    else yeni.delete("durum");
    setParams(yeni);
    setSayfa(1);
  };
  const liste = useQuery({
    queryKey: ["parca", "kullanimlar", durum, sayfa],
    queryFn: () => parcaApi.kullanimlar(durum, SAYFA, (sayfa - 1) * SAYFA),
  });
  const bitti = async (m: string) => {
    message.success(m);
    setRedAcik(false);
    setZimmetAcik(false);
    setMetin("");
    await qc.invalidateQueries({ queryKey: ["parca"] });
  };
  const onayla = useMutation({
    mutationFn: (id: number) => parcaApi.kullanimOnayla(id),
    onSuccess: () => bitti("Kullanım onaylandı"),
    onError: (e) => void message.error(parcaHatasi(e).mesaj),
  });
  const reddet = useMutation({
    mutationFn: ({ id, n }: { id: number; n: string }) => parcaApi.kullanimReddet(id, n),
    onSuccess: () => bitti("Kullanım reddedildi; teknisyene zimmet sorusu açıldı"),
    onError: (e) => void message.error(parcaHatasi(e).mesaj),
  });
  const zimmet = useMutation({
    mutationFn: ({ id, n }: { id: number; n: string }) => parcaApi.zimmetCevapla(id, n),
    onSuccess: () => bitti("Açıklama gönderildi"),
    onError: (e) => void message.error(parcaHatasi(e).mesaj),
  });
  const kayitlar = liste.data?.kayitlar ?? [];
  const tek = kayitlar.find((k) => k.id === secili[0]) ?? null;
  const onaylayici = yetkili("parca.talep_onay");
  const sutunlar: ColumnsType<Kullanim> = [
    {
      title: "Durum",
      key: "d",
      width: 150,
      align: "center",
      render: (_, k) => (
        <DurumBaglantisi
          metin={KULLANIM_DURUM_ADLARI[k.durum] ?? k.durum}
          ton={k.durum === "REDDEDILDI" ? "olumsuz" : k.durum === "BEKLIYOR" ? undefined : "kapali"}
          alt={k.zimmet_durumu === "ACIK" ? <AltNot tur="uyari">ZİMMET SORUSU</AltNot> : undefined}
        />
      ),
    },
    {
      title: "İş No",
      key: "so",
      width: 160,
      align: "center",
      render: (_, k) => (
        <IsNoBaglantisi soId={k.service_order_id} soNo={k.so_no} />
      ),
    },
    { title: "Tarih", key: "t", width: 140, align: "center", render: (_, k) => zaman(k.created_at) },
    { title: "Parça", key: "p", width: 240, render: (_, k) => <Aciklama metin={`${k.kod} — ${k.ad}`} /> },
    { title: "Adet", dataIndex: "adet", key: "a", width: 70, align: "right" },
    { title: "Araç", dataIndex: "depo_adi", key: "dp", width: 150, align: "center", responsive: ["sm"] },
    {
      title: "Kullanan /\nOnaylayan",
      key: "kim",
      width: 160,
      align: "center",
      responsive: ["md"],
      render: (_, k) => (
        <KucukGri>
          {k.kullanan ?? "—"}
          {k.onaylayan ? ` / ${k.onaylayan}` : ""}
        </KucukGri>
      ),
    },
    {
      title: "Red Gerekçesi / Açıklama",
      key: "n",
      width: 240,
      align: "center",
      responsive: ["sm"],
      render: (_, k) => (
        <KucukGri>
          {k.red_nedeni}
          {k.zimmet_aciklama ? ` — ${k.zimmet_aciklama}` : ""}
        </KucukGri>
      ),
    },
  ];
  return (
    <>
      <Typography.Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
        Teknisyen sahada parçayı kendi araç deposundan anında işe çıkar; iş beklemez. Şef bu kullanımı sonradan
        onaylar. Reddedilen kullanım fark kaydıdır: teknisyene zimmet sorusu açılır ve açıklama ister.
      </Typography.Text>
      <ListeRaporu<Kullanim>
        kayitSayisi={liste.data?.toplam}
        durumCubugu={{
          gruplar: tekliGruplar(KULLANIM_DURUM_ADLARI),
          secili: durum,
          onSec: (k) => guncelle(k),
          onYenile: () => void liste.refetch(),
          yenileniyor: liste.isFetching,
        }}
        sutunlar={sutunlar}
        veri={kayitlar}
        satirAnahtari="id"
        yukleniyor={liste.isFetching}
        bosMetin={liste.isError ? parcaHatasi(liste.error).mesaj : "Veri yok"}
        scrollX={1100}
        secili={secili}
        onSecim={(k) => setSecili(k as number[])}
        sayfalama={{ sayfa, boyut: SAYFA, toplam: liste.data?.toplam ?? 0, onChange: setSayfa }}
        eylemler={[
          {
            anahtar: "onayla",
            ad: "Onayla",
            gizli: !onaylayici,
            devreDisi: !tek || tek.durum !== "BEKLIYOR",
            yukleniyor: onayla.isPending,
            onClick: () => tek && onayla.mutate(tek.id),
          },
          {
            anahtar: "reddet",
            ad: "Reddet",
            tehlikeli: true,
            gizli: !onaylayici,
            devreDisi: !tek || tek.durum !== "BEKLIYOR",
            onClick: () => setRedAcik(true),
          },
          {
            anahtar: "zimmet",
            ad: "Açıklama Yaz",
            devreDisi: !tek || tek.zimmet_durumu !== "ACIK" || tek.kullanan_id !== kullanici?.id,
            onClick: () => setZimmetAcik(true),
          },
          {
            anahtar: "fis",
            ad: "Parça Fişi (PDF)",
            ikon: <FilePdfOutlined />,
            kisalt: true,
            devreDisi: !tek,
            onClick: () => tek && window.open(parcaApi.fisYolu(tek.hareket_id), "_blank"),
          },
        ]}
      />
      <Modal
        open={redAcik || zimmetAcik}
        title={redAcik ? "Kullanımı reddet (fark kaydı)" : "Zimmet sorusuna açıklama"}
        okText={redAcik ? "Reddet" : "Gönder"}
        okButtonProps={{ danger: redAcik, disabled: metin.trim().length < 3 }}
        cancelText="Vazgeç"
        confirmLoading={reddet.isPending || zimmet.isPending}
        onCancel={() => {
          setRedAcik(false);
          setZimmetAcik(false);
        }}
        onOk={() => {
          if (!tek) return;
          if (redAcik) reddet.mutate({ id: tek.id, n: metin.trim() });
          else zimmet.mutate({ id: tek.id, n: metin.trim() });
        }}
        destroyOnHidden
      >
        <Input.TextArea
          rows={3}
          maxLength={redAcik ? 200 : 500}
          placeholder={redAcik ? "Red gerekçesi (teknisyen görür)" : "Parça nerede / neden kullanıldı?"}
          value={metin}
          onChange={(e) => setMetin(e.target.value)}
        />
      </Modal>
    </>
  );
}

// --- Sayım --------------------------------------------------------------------

function SayimSekmesi() {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [sayfa, setSayfa] = useState(1);
  const [secili, setSecili] = useState<number | null>(null);
  const [isaretli, setIsaretli] = useState<number[]>([]);
  const [yeniAcik, setYeniAcik] = useState(false);
  const durum = params.get("durum") ?? undefined;
  const depolar = useDepolar();
  const liste = useQuery({
    queryKey: ["parca", "sayimlar", durum, sayfa],
    queryFn: () => parcaApi.sayimlar(durum, SAYFA, (sayfa - 1) * SAYFA),
  });
  const [form] = Form.useForm<{ depo_id: number; notes?: string }>();
  const ac = useMutation({
    mutationFn: (d: { depo_id: number; notes?: string }) => parcaApi.sayimAc(d.depo_id, d.notes?.trim() || null),
    onSuccess: async (s) => {
      message.success(`${s.count_no} açıldı`);
      setYeniAcik(false);
      form.resetFields();
      await qc.invalidateQueries({ queryKey: ["parca"] });
      setSecili(s.id);
    },
    onError: (e) => void message.error(parcaHatasi(e).mesaj),
  });
  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <ListeRaporu<Sayim>
        kayitSayisi={liste.data?.toplam}
        durumCubugu={{
          gruplar: tekliGruplar(SAYIM_DURUM_ADLARI),
          secili: durum,
          onSec: (v) => {
            const yeni = new URLSearchParams({ sekme: "sayimlar" });
            if (v) yeni.set("durum", v);
            setParams(yeni);
            setSayfa(1);
          },
          onYenile: () => void liste.refetch(),
          yenileniyor: liste.isFetching,
        }}
        sutunlar={[
          {
            title: "Durum",
            key: "s",
            width: 140,
            align: "center",
            render: (_, r) => (
              <DurumBaglantisi
                metin={SAYIM_DURUM_ADLARI[r.durum] ?? r.durum}
                ton={r.durum === "IPTAL" ? "olumsuz" : r.durum === "ONAYLANDI" ? "kapali" : undefined}
                onClick={() => setSecili(r.id)}
              />
            ),
          },
          {
            title: "Sayım No",
            dataIndex: "count_no",
            key: "no",
            width: 160,
            align: "center",
            render: (v: string, r) => <NoRozeti no={v} onClick={() => setSecili(r.id)} />,
          },
          { title: "Açıklama", dataIndex: "depo_adi", key: "d", width: 240, render: (v: string, r) => <Aciklama metin={v} onClick={() => setSecili(r.id)} /> },
          { title: "Başlangıç", key: "b", width: 140, align: "center", render: (_, r) => zaman(r.baslangic_at) },
          { title: "Onay", key: "o", width: 140, align: "center", responsive: ["sm"], render: (_, r) => zaman(r.onay_at) },
        ]}
        veri={liste.data?.kayitlar ?? []}
        satirAnahtari="id"
        yukleniyor={liste.isFetching}
        scrollX={760}
        secili={isaretli}
        onSecim={(k) => setIsaretli(k as number[])}
        onSatirAc={(r) => setSecili(r.id)}
        sayfalama={{ sayfa, boyut: SAYFA, toplam: liste.data?.toplam ?? 0, onChange: setSayfa }}
        eylemler={[
          {
            anahtar: "liste",
            ad: "Liste",
            menu: [{ key: "yenile", label: "Listeyi yenile" }],
            onMenu: () => void liste.refetch(),
          },
          {
            anahtar: "ac",
            ad: "Sayımı Aç",
            ikon: <EditOutlined />,
            kisalt: true,
            devreDisi: !isaretli.length,
            onClick: () => isaretli.length && setSecili(isaretli[0]),
          },
        ]}
        sagEylemler={[
          {
            anahtar: "yeni",
            ad: "Yeni Sayım",
            ikon: <PlusOutlined />,
            vurgulu: true,
            kisalt: true,
            gizli: !yetkili("parca.yonet"),
            onClick: () => setYeniAcik(true),
          },
        ]}
      />
      <Modal
        open={yeniAcik}
        title="Yeni stok sayımı"
        onCancel={() => setYeniAcik(false)}
        onOk={() => form.submit()}
        okText="Sayımı aç"
        cancelText="Vazgeç"
        confirmLoading={ac.isPending}
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary">
          Sayım açıldığı andaki sistem adetleri görüntü olarak saklanır. Onaya kadar hiçbir bakiye
          değişmez; onayda fark güncel bakiyeye göre yazılır.
        </Typography.Paragraph>
        <Form form={form} layout="vertical" onFinish={(d) => ac.mutate(d)}>
          <Form.Item name="depo_id" label="Depo" rules={[{ required: true, message: "Depo seçin" }]}>
            <Select options={(depolar.data ?? []).map((d) => ({ value: d.id, label: d.name }))} />
          </Form.Item>
          <Form.Item name="notes" label="Not">
            <Input.TextArea rows={2} maxLength={2000} />
          </Form.Item>
        </Form>
      </Modal>
      <SayimCekmecesi sayimId={secili} onKapat={() => setSecili(null)} />
    </Space>
  );
}

function SayimCekmecesi({ sayimId, onKapat }: { sayimId: number | null; onKapat: () => void }) {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [sayilan, setSayilan] = useState<Record<number, number | null>>({});
  const [gerekce, setGerekce] = useState("");
  const [sapma, setSapma] = useState<string | null>(null);
  const sorgu = useQuery({
    queryKey: ["parca", "sayim", sayimId],
    queryFn: () => parcaApi.sayim(sayimId!),
    enabled: sayimId !== null,
  });
  const sayim = sorgu.data;
  const acik = sayim?.durum === "ACIK" && yetkili("parca.yonet");
  const tazele = () => qc.invalidateQueries({ queryKey: ["parca"] });
  const kaydet = useMutation({
    mutationFn: () =>
      parcaApi.sayimSatirlari(
        sayimId!,
        Object.entries(sayilan).map(([pid, adet]) => ({ product_id: Number(pid), sayilan_adet: adet })),
      ),
    onSuccess: async () => {
      message.success("Sayılan adetler kaydedildi");
      setSayilan({});
      await tazele();
    },
    onError: (e) => void message.error(parcaHatasi(e).mesaj),
  });
  const onayla = useMutation({
    mutationFn: (kabul: boolean) => parcaApi.sayimOnayla(sayimId!, gerekce.trim(), kabul),
    onSuccess: async () => {
      message.success("Sayım onaylandı; farklar stoğa yazıldı");
      setSapma(null);
      await tazele();
    },
    onError: (e) => {
      const h = parcaHatasi(e);
      if (h.sapmalar) setSapma(h.mesaj);
      else message.error(h.mesaj);
    },
  });
  const iptal = useMutation({
    mutationFn: () => parcaApi.sayimIptal(sayimId!, gerekce.trim()),
    onSuccess: async () => {
      message.success("Sayım iptal edildi");
      await tazele();
    },
    onError: (e) => void message.error(parcaHatasi(e).mesaj),
  });
  return (
    <Drawer
      open={sayimId !== null}
      onClose={() => {
        setSayilan({});
        setSapma(null);
        setGerekce("");
        onKapat();
      }}
      title={sayim ? `${sayim.count_no} — ${sayim.depo_adi ?? ""}` : "Sayım"}
      size="large"
    >
      {sayim && (
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          <Space wrap>
            <Tag>{SAYIM_DURUM_ADLARI[sayim.durum] ?? sayim.durum}</Tag>
            <Typography.Text type="secondary">Başlangıç: {zaman(sayim.baslangic_at)}</Typography.Text>
            {sayim.gerekce && <Typography.Text type="secondary">Gerekçe: {sayim.gerekce}</Typography.Text>}
          </Space>
          <Table<SayimSatiri>
            size="small"
            rowKey="product_id"
            pagination={false}
            dataSource={sayim.satirlar}
            scroll={{ x: true }}
            columns={[
              { title: "Parça", key: "p", render: (_, r) => `${r.kod} — ${r.ad}` },
              { title: "Sistem (açılış)", dataIndex: "sistem_adet", key: "s", align: "right" },
              {
                title: "Sayılan",
                key: "c",
                render: (_, r) =>
                  acik ? (
                    <InputNumber
                      min={0}
                      max={1_000_000}
                      precision={0}
                      value={r.product_id in sayilan ? sayilan[r.product_id] : r.sayilan_adet}
                      onChange={(v) => setSayilan((o) => ({ ...o, [r.product_id]: v ?? null }))}
                    />
                  ) : (
                    (r.sayilan_adet ?? "—")
                  ),
              },
              { title: "Fark", key: "f", align: "right", render: (_, r) => (r.fark == null ? "—" : r.fark) },
              {
                title: "Onay anında",
                key: "o",
                align: "right",
                render: (_, r) => r.onay_anindaki_adet ?? "—",
              },
            ]}
          />
          {acik && (
            <>
              <Button disabled={Object.keys(sayilan).length === 0} loading={kaydet.isPending} onClick={() => kaydet.mutate()}>
                Sayılan adetleri kaydet
              </Button>
              {sapma && (
                <Alert
                  type="warning"
                  showIcon
                  message={sapma}
                  action={
                    <Button size="small" onClick={() => onayla.mutate(true)} loading={onayla.isPending}>
                      Değişimi kabul et ve onayla
                    </Button>
                  }
                />
              )}
              <Input.TextArea
                rows={2}
                maxLength={500}
                placeholder="Onay / iptal gerekçesi (zorunlu)"
                value={gerekce}
                onChange={(e) => setGerekce(e.target.value)}
              />
              <Space wrap>
                <Button
                  type="primary"
                  disabled={gerekce.trim().length < 3 || Object.keys(sayilan).length > 0}
                  loading={onayla.isPending}
                  onClick={() => onayla.mutate(false)}
                >
                  Sayımı onayla
                </Button>
                <Button danger disabled={gerekce.trim().length < 3} loading={iptal.isPending} onClick={() => iptal.mutate()}>
                  Sayımı iptal et
                </Button>
              </Space>
              {Object.keys(sayilan).length > 0 && (
                <Typography.Text type="secondary">Onaydan önce sayılan adetleri kaydedin.</Typography.Text>
              )}
            </>
          )}
        </Space>
      )}
    </Drawer>
  );
}

// --- İş no bağlantısı ------------------------------------------------------------

/** İş no → servis işinin kartı (parça çıkışı/iade/talep orada); `servis.gor`
 *  yoksa düz metin (kart açılamaz). */
function IsNoBaglantisi({ soId, soNo }: { soId: number | null | undefined; soNo: string | null | undefined }) {
  const { yetkili } = useAuth();
  if (soId == null || !yetkili("servis.gor")) return <span className="fl-no-rozet">{soNo ?? "—"}</span>;
  return (
    <Link to={`/servis-isleri/${soId}`} className="fl-no-rozet">
      {soNo}
    </Link>
  );
}

// --- Depolar ------------------------------------------------------------------

function DepoSekmesi() {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const depolar = useDepolar(true);
  const [duzenle, setDuzenle] = useState<Depo | "yeni" | null>(null);
  const [form] = Form.useForm<{
    code?: string;
    name: string;
    birim?: string | null;
    arac: boolean;
    user_id?: number | null;
    is_active?: boolean;
  }>();
  const tanimci = yetkili("sistem.ayar");
  // Depo tek birime bağlıdır (2026-11-09: birimler tamamen ayrı). Seçenekler
  // kullanıcının görebildiği birimler; tek birim varsa kendiliğinden seçilir.
  const { menuBirimleri } = useSirket();
  const birimSecenekleri = BIRIM_KODLARI.filter((b) => !menuBirimleri || menuBirimleri.has(b));
  const tekBirim = birimSecenekleri.length === 1 ? birimSecenekleri[0] : null;
  const personel = useQuery({
    queryKey: ["parca", "personel"],
    queryFn: () => personelApi.liste({ durum: "CALISIYOR" }, 200, 0),
    enabled: tanimci && yetkili("personel.gor") && duzenle !== null,
  });
  const kaydet = useMutation({
    mutationFn: async (d: {
      code?: string;
      name: string;
      birim?: string | null;
      arac: boolean;
      user_id?: number | null;
      is_active?: boolean;
    }) => {
      if (duzenle === "yeni") {
        return parcaApi.depoOlustur({
          code: d.code!.trim(),
          name: d.name.trim(),
          // Boş: tek birimde o birim, araç deposunda teknisyenin birimi (sunucu).
          birim: d.birim ?? tekBirim ?? null,
          location_type: d.arac ? "TEKNISYEN" : "BOLGE_DEPO",
          user_id: d.arac ? (d.user_id ?? null) : null,
        });
      }
      const depo = duzenle as Depo;
      return parcaApi.depoGuncelle(depo.id, {
        name: d.name.trim(),
        // Birim boşaltılamaz; yalnız seçildiyse/değiştiyse gönderilir.
        ...(d.birim && d.birim !== depo.birim ? { birim: d.birim } : {}),
        is_active: d.is_active,
        ...(depo.location_type === "TEKNISYEN" ? { user_id: d.user_id ?? null } : {}),
      });
    },
    onSuccess: async () => {
      message.success("Depo kaydedildi");
      setDuzenle(null);
      await qc.invalidateQueries({ queryKey: ["parca"] });
    },
    onError: (e) => void message.error(parcaHatasi(e).mesaj),
  });
  const arac = Form.useWatch("arac", form);
  const aracDeposu = duzenle === "yeni" ? arac : duzenle?.location_type === "TEKNISYEN";

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Typography.Text type="secondary">
        Servis depoları birimlere ayrıdır: her depo tek birime (Haberleşme, Güvenlik …) bağlıdır. Teknisyen ve
        şef yalnız kendi biriminin depolarını ve kendi araç deposunu görür; bir birimin deposundan başka
        birimin işine parça çıkılamaz. Mobilite stok ekranları bu depoları göstermez.
      </Typography.Text>
      {tanimci && (
        <Button
          onClick={() => {
            setDuzenle("yeni");
            form.resetFields();
            form.setFieldsValue({ arac: false, birim: tekBirim });
          }}
        >
          Yeni servis deposu
        </Button>
      )}
      <Table<Depo>
        size="small"
        rowKey="id"
        loading={depolar.isLoading}
        dataSource={depolar.data}
        pagination={false}
        scroll={{ x: true }}
        columns={[
          { title: "Kod", dataIndex: "code", key: "c" },
          { title: "Ad", dataIndex: "name", key: "n" },
          {
            title: "Birim",
            key: "b",
            render: (_, d) =>
              d.birim ? (BIRIM_ETIKETLERI[d.birim] ?? d.birim) : <Tag color="orange">Birim seçilmeli</Tag>,
          },
          {
            title: "Tür",
            key: "t",
            render: (_, d) =>
              d.location_type === "TEKNISYEN" ? <Tag color="blue">{d.kendi_araci ? "Araç deposu (benim)" : "Araç deposu"}</Tag> : "Depo",
          },
          { title: "Durum", key: "a", render: (_, d) => (d.is_active ? <Tag color="green">Aktif</Tag> : <Tag>Pasif</Tag>) },
          ...(tanimci
            ? [
                {
                  title: "",
                  key: "i",
                  render: (_: unknown, d: Depo) => (
                    <Button
                      size="small"
                      type="link"
                      onClick={() => {
                        setDuzenle(d);
                        form.setFieldsValue({
                          name: d.name,
                          birim: d.birim,
                          user_id: d.user_id,
                          is_active: d.is_active,
                          arac: d.location_type === "TEKNISYEN",
                        });
                      }}
                    >
                      Düzenle
                    </Button>
                  ),
                },
              ]
            : []),
        ]}
      />
      <Modal
        open={duzenle !== null}
        title={duzenle === "yeni" ? "Yeni servis deposu" : "Depoyu düzenle"}
        onCancel={() => setDuzenle(null)}
        onOk={() => form.submit()}
        okText="Kaydet"
        cancelText="Vazgeç"
        confirmLoading={kaydet.isPending}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={(d) => kaydet.mutate(d)}>
          {duzenle === "yeni" && (
            <Form.Item name="code" label="Kod" rules={[{ required: true }, { max: 20 }]}>
              <Input maxLength={20} />
            </Form.Item>
          )}
          <Form.Item name="name" label="Ad" rules={[{ required: true }, { min: 2 }, { max: 100 }]}>
            <Input maxLength={100} />
          </Form.Item>
          {!(duzenle === "yeni" && tekBirim) && (
            <Form.Item
              name="birim"
              label="Birim"
              extra={duzenle === "yeni" && aracDeposu ? "Boş bırakılırsa teknisyenin birimi" : undefined}
              rules={[{ required: !(duzenle === "yeni" && aracDeposu), message: "Birim seçin" }]}
            >
              <Select options={birimSecenekleri.map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] ?? b }))} />
            </Form.Item>
          )}
          {duzenle === "yeni" && (
            <Form.Item name="arac" label="Teknisyen araç deposu" valuePropName="checked">
              <Switch />
            </Form.Item>
          )}
          {aracDeposu && (
            <Form.Item name="user_id" label="Teknisyen" rules={[{ required: true, message: "Teknisyen seçin" }]}>
              <Select
                showSearch
                optionFilterProp="label"
                loading={personel.isLoading}
                options={(personel.data?.kayitlar ?? []).map((p) => ({ value: p.id, label: p.full_name }))}
                notFoundContent={yetkili("personel.gor") ? "Personel bulunamadı" : "Personel listesi için yetkiniz yok"}
              />
            </Form.Item>
          )}
          {duzenle !== "yeni" && (
            <Form.Item name="is_active" label="Aktif" valuePropName="checked">
              <Switch />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </Space>
  );
}

// --- Parça kartı ----------------------------------------------------------------

function KartPenceresi({ acik, onKapat }: { acik: boolean; onKapat: () => void }) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [form] = Form.useForm<{
    code: string;
    name: string;
    brand?: string;
    model?: string;
    supplier_code?: string;
    birim?: string;
    min_stok?: number;
  }>();
  const kaydet = useMutation({
    mutationFn: (d: {
      code: string;
      name: string;
      brand?: string;
      model?: string;
      supplier_code?: string;
      birim?: string;
      min_stok?: number;
    }) =>
      parcaApi.kartOlustur({
        ...d,
        code: d.code.trim(),
        name: d.name.trim(),
        brand: d.brand?.trim() || null,
        model: d.model?.trim() || null,
        supplier_code: d.supplier_code?.trim() || null,
        birim: d.birim ?? null,
        min_stok: d.min_stok ?? null,
      }),
    onSuccess: async (k) => {
      message.success(`${k.code} parça kartı açıldı`);
      form.resetFields();
      onKapat();
      await qc.invalidateQueries({ queryKey: ["parca"] });
    },
    onError: (e) => void message.error(parcaHatasi(e).mesaj),
  });
  return (
    <Modal
      open={acik}
      title="Yeni yedek parça kartı"
      onCancel={onKapat}
      onOk={() => form.submit()}
      okText="Kaydet"
      cancelText="Vazgeç"
      confirmLoading={kaydet.isPending}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary">
        Yedek parça adetle (seri numarasız) izlenir; fiyat bilgisi katalogdan yönetilir.
      </Typography.Paragraph>
      <Form form={form} layout="vertical" initialValues={{ birim: "ADET" }} onFinish={(d) => kaydet.mutate(d)}>
        <Form.Item name="code" label="Kod" rules={[{ required: true }, { max: 40 }]}>
          <Input maxLength={40} />
        </Form.Item>
        <Form.Item name="name" label="Ad" rules={[{ required: true }, { min: 2 }, { max: 160 }]}>
          <Input maxLength={160} />
        </Form.Item>
        <Row gutter={12}>
          <Col xs={24} sm={12}>
            <Form.Item name="brand" label="Marka" rules={[{ max: 60 }]}>
              <Input maxLength={60} />
            </Form.Item>
          </Col>
          <Col xs={24} sm={12}>
            <Form.Item name="model" label="Model" rules={[{ max: 80 }]}>
              <Input maxLength={80} />
            </Form.Item>
          </Col>
          <Col xs={24} sm={12}>
            <Form.Item name="supplier_code" label="Tedarikçi kodu" rules={[{ max: 60 }]}>
              <Input maxLength={60} />
            </Form.Item>
          </Col>
          <Col xs={12} sm={6}>
            <Form.Item name="birim" label="Birim">
              <Select options={OLCU_BIRIMLERI.map((b) => ({ value: b, label: olcuBirimiAdi(b) }))} />
            </Form.Item>
          </Col>
          <Col xs={12} sm={6}>
            <Form.Item name="min_stok" label="Asgari stok">
              <InputNumber min={0} max={1_000_000} precision={0} />
            </Form.Item>
          </Col>
        </Row>
      </Form>
    </Modal>
  );
}
