/**
 * Saha / Zaman Takibi yönetim ekranı (TS-189, E09-14/15).
 *
 * - Üstte tıklanabilir Fiori KPI kutucukları (`KpiKutucugu`): kutudaki sayı sunucunun
 *   `deger`idir; tıklanınca `?kpi=` ile alttaki ayrıntı tablosu süzülür ve
 *   tablo toplamı (`X-Toplam-Kayit`) kutudaki adetle aynıdır.
 * - "Şu an çalışanlar": açık sayaçlar; uzun sayaç kırmızı; yönetici
 *   (`servis.planla`) gerçek bitişle kapatır ya da iptal eder (E09-06).
 * - Personel dağılımı ve veri disiplini sütunları, kişi süzgeci ve Excel
 *   "Personel" sayfası yalnız `servis_rapor.personel` ile (sunucu anahtarı
 *   hiç göndermez; ekran yalnız yansıtır).
 * - Kayıt yoksa süre "Kayıt eksik" görünür, "0" yazılmaz; tahmini (plan)
 *   süre bu ekranda yoktur.
 * - Menü izni `servis_rapor.gor` (KD-06); izni olmayan Benim İşlerim'e döner.
 */
import { ClockCircleOutlined, DownloadOutlined, FieldTimeOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  DatePicker,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Table,
  Tag,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useMemo, useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";

import type { ApiError } from "../api/client";
import { BIRIM_ETIKETLERI, BIRIM_KODLARI } from "../api/personel";
import {
  type Bolum,
  FAALIYET_ADLARI,
  type Faaliyet,
  type PersonelSatiri,
  KAYNAK_ADLARI,
  SURE_DURUMU_ADLARI,
  type ZamanIsi,
  type ZamanKaydi,
  type ZamanSuzgeci,
  ZAMAN_SORGULARI,
  servisZaman,
  sureMetni,
  zamanTakibi,
} from "../api/servisZaman";
import { useAuth } from "../auth/AuthContext";
import {
  Aciklama,
  AltNot,
  DurumBaglantisi,
  FioriBolum,
  Kucuk,
  KucukGri,
  NoRozeti,
  TUMU_KATEGORISI,
  gunu,
  kategorilerOlustur,
  saati,
} from "../fiori/ListeOgeleri";
import ListeRaporu, { KpiKutucugu } from "../fiori/ListeRaporu";

const ISO = "YYYY-MM-DD";
const SAYFA = 50;
const IS_KPI = new Set(["farkli_is", "sure_eksik"]);

function sure(dk: number | null | undefined) {
  const m = sureMetni(dk);
  return m ?? <Tag color="orange">Kayıt eksik</Tag>;
}

function an(t: string | null) {
  return t ? dayjs(t).format("DD.MM.YYYY HH:mm") : "—";
}

export default function ZamanTakibiPage() {
  const { yetkili, kullanici } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const personelGorur = yetkili("servis_rapor.personel");
  const yonetici = yetkili("servis.planla");

  const [aralik, setAralik] = useState<[Dayjs, Dayjs] | null>(null);
  const [birim, setBirim] = useState<string | undefined>(
    kullanici?.birimler?.length === 1 ? kullanici.birimler[0] : undefined,
  );
  const [kisi, setKisi] = useState<number | undefined>();
  const [faaliyet, setFaaliyet] = useState<string | undefined>();
  const [sayfa, setSayfa] = useState(1);
  const [kapatilan, setKapatilan] = useState<ZamanKaydi | null>(null);
  const [seciliAktif, setSeciliAktif] = useState<number[]>([]);
  const [kapatForm] = Form.useForm<{ gercek_bitis?: Dayjs; gerekce: string }>();

  const kpiKodu = params.get("kpi") ?? undefined;
  const suzgec: ZamanSuzgeci = {
    bas: aralik?.[0].format(ISO),
    bit: aralik?.[1].format(ISO),
    birim,
    kullanici_id: kisi,
    faaliyet,
  };
  const suzgecAnahtari = [suzgec.bas, suzgec.bit, birim, kisi, faaliyet];

  const ozet = useQuery({
    queryKey: ["zaman-ozet", ...suzgecAnahtari],
    queryFn: () => zamanTakibi.ozet(suzgec),
    enabled: yetkili("servis_rapor.gor"),
  });
  const aktif = useQuery({
    queryKey: ["zaman-aktif", birim, kisi],
    queryFn: () => zamanTakibi.aktif({ birim, kullanici_id: kisi }),
    enabled: yetkili("servis_rapor.gor"),
    refetchInterval: 60_000,
  });
  const isListesi = !!kpiKodu && IS_KPI.has(kpiKodu);
  const kayitlar = useQuery({
    queryKey: ["zaman-kayitlar", kpiKodu, sayfa, ...suzgecAnahtari],
    queryFn: () => zamanTakibi.kayitlar({ ...suzgec, kpi: kpiKodu }, SAYFA, (sayfa - 1) * SAYFA),
    enabled: yetkili("servis_rapor.gor") && !isListesi,
  });
  const isler = useQuery({
    queryKey: ["zaman-isler", kpiKodu, sayfa, ...suzgecAnahtari],
    queryFn: () => zamanTakibi.isler({ ...suzgec, kpi: kpiKodu! }, SAYFA, (sayfa - 1) * SAYFA),
    enabled: yetkili("servis_rapor.gor") && isListesi,
  });

  const kapat = useMutation({
    mutationFn: (v: { gercek_bitis?: Dayjs; gerekce: string }) =>
      servisZaman.yoneticiKapat(
        kapatilan as unknown as Bolum,
        v.gerekce,
        v.gercek_bitis ? v.gercek_bitis.toISOString() : undefined,
      ),
    onSuccess: () => {
      message.success("Sayaç kapatıldı");
      setKapatilan(null);
      for (const k of [["zaman-ozet"], ["zaman-aktif"], ["zaman-kayitlar"], ...ZAMAN_SORGULARI]) {
        void qc.invalidateQueries({ queryKey: k });
      }
    },
    onError: (e: ApiError) =>
      message.error(e.cakisma ? `${e.message} Gerekirse sayfayı yenileyin.` : e.message),
  });

  const kisiSecenekleri = useMemo(
    () =>
      (ozet.data?.personel ?? [])
        .filter((p) => p.user_id != null)
        .map((p) => ({ value: p.user_id as number, label: p.ad })),
    [ozet.data],
  );

  if (!yetkili("servis_rapor.gor")) return <Navigate to="/benim-islerim" replace />;

  const filtreDegisti = <T,>(f: (v: T) => void) => (v: T) => {
    f(v);
    setSayfa(1);
  };

  const birimSecenekleri = [
    { value: "", label: "Tüm birimler" },
    ...BIRIM_KODLARI.filter(
      (b) => kullanici?.role.scope === "TUMU" || !kullanici?.birimler?.length || kullanici.birimler.includes(b),
    ).map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] })),
  ];

  const kpiBasligi = ozet.data?.kpi.find((k) => k.kod === kpiKodu)?.baslik;
  const kpiSec = (kod?: string) => {
    if (kod) params.set("kpi", kod);
    else params.delete("kpi");
    setParams(params, { replace: true });
    setSayfa(1);
  };

  const personelSutunlari = [
    { title: "Personel", dataIndex: "ad", fixed: "left" as const },
    { title: "Kişi-saat", dataIndex: "kisi_saat_dk", render: sure },
    { title: "Yol", dataIndex: "yol_dk", render: (d: number | null) => sureMetni(d) ?? "—" },
    { title: "Saha", dataIndex: "saha_dk", render: (d: number | null) => sureMetni(d) ?? "—" },
    { title: "Bekleme", dataIndex: "bekleme_dk", render: (d: number | null) => sureMetni(d) ?? "—" },
    { title: "Mola (hariç)", dataIndex: "mola_dk", render: (d: number | null) => sureMetni(d) ?? "—" },
    { title: "İş", dataIndex: "is_sayisi" },
    {
      title: "Canlı oranı",
      dataIndex: "canli_orani",
      render: (o: number | null) => (o == null ? "—" : `%${o.toLocaleString("tr-TR")}`),
    },
    { title: "Manuel", dataIndex: "manuel_sayisi" },
    { title: "Gecikmeli manuel", dataIndex: "gecikmeli_manuel_sayisi" },
    { title: "Düzeltilen", dataIndex: "duzeltilen_sayisi" },
    { title: "İptal", dataIndex: "iptal_sayisi" },
    { title: "Geri alınan", dataIndex: "geri_alinan_sayisi" },
  ];

  const ayrinti = isListesi ? isler : kayitlar;
  const suzgecMetni = ozet.data
    ? `${dayjs(ozet.data.suzgec.bas).format("DD.MM.YYYY")} – ${dayjs(ozet.data.suzgec.bit).format("DD.MM.YYYY")}`
    : "";

  const sayaclar = aktif.data?.sayaclar ?? [];
  const seciliSayac = sayaclar.find((r) => r.id === seciliAktif[0]) ?? null;
  const aktarir = yetkili("servis_rapor.disaaktar");
  const excelAc = () =>
    window.open(zamanTakibi.excelYolu({ ...suzgec, kpi: isListesi ? undefined : kpiKodu }), "_blank");
  const faaliyetKategorileri = kategorilerOlustur(
    Object.entries(FAALIYET_ADLARI).map(([kod, ad]) => ({ kod, ad })),
    (k) => (k === "MOLA" || k === "BEKLEME" ? "kirmizi" : "yesil"),
    () => <FieldTimeOutlined />,
  );
  const kpiEtiketi = kpiKodu ? (
    <Tag closable onClose={() => kpiSec(undefined)} color="blue">
      {kpiBasligi ?? kpiKodu}
    </Tag>
  ) : undefined;

  return (
    <div className="fm-sayfa">
      <div className="fm-arac-cubugu">
        <span className="fm-arac-baslik">Süzgeç</span>
        <DatePicker.RangePicker
          format="DD.MM.YYYY"
          value={aralik}
          onChange={filtreDegisti((v) => setAralik(v && v[0] && v[1] ? [v[0], v[1]] : null))}
          placeholder={["Son 31 gün", ""]}
          allowClear
        />
        <Select
          style={{ width: 170 }}
          value={birim ?? ""}
          options={birimSecenekleri}
          onChange={filtreDegisti((v: string) => setBirim(v || undefined))}
        />
        {personelGorur && (
          <Select
            style={{ width: 190 }}
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="Personel"
            value={kisi}
            options={kisiSecenekleri}
            onChange={filtreDegisti((v: number | undefined) => setKisi(v))}
          />
        )}
        <Typography.Text type="secondary">{suzgecMetni}</Typography.Text>
        <span className="fm-bosluk" />
        {aktarir && (
          <Button icon={<DownloadOutlined />} onClick={excelAc}>
            Excel
          </Button>
        )}
      </div>

      {ozet.isError && <Alert type="error" showIcon message={(ozet.error as ApiError).message} />}

      <div className="fl-kutucuklar">
        {(ozet.data?.kpi ?? []).map((k) => (
          <KpiKutucugu
            key={k.kod}
            kod={k.kod}
            baslik={k.baslik}
            tanim={k.tanim}
            deger={k.deger}
            ikon={<FieldTimeOutlined />}
            vurgu={(k.kod === "uzun_sayac" || k.kod === "sure_eksik") && (k.deger ?? 0) > 0 ? "uyari" : "normal"}
            yol={k.liste ? `/zaman-takibi?kpi=${k.kod}` : "/zaman-takibi"}
            yukleniyor={ozet.isLoading}
          />
        ))}
      </div>

      <FioriBolum baslik={`Şu an çalışanlar (${sayaclar.length})`} dolgusuz>
        <ListeRaporu<ZamanKaydi>
          kayitSayisi={sayaclar.length}
          durumCubugu={{
            gruplar: [],
            onSec: () => undefined,
            onYenile: () => void aktif.refetch(),
            yenileniyor: aktif.isFetching,
          }}
          sutunlar={[
            {
              title: "Durum",
              key: "d",
              width: 130,
              align: "center",
              render: (_, r) => (
                <DurumBaglantisi
                  metin={r.uzun ? "SAAT AÇIK-UZUN" : "SAAT AÇIK"}
                  ton={r.uzun ? "olumsuz" : undefined}
                />
              ),
            },
            {
              title: "İş No",
              dataIndex: "so_no",
              key: "so",
              width: 170,
              align: "center",
              render: (v: string) => <NoRozeti no={v} />,
            },
            ...(personelGorur
              ? [{ title: "Personel", dataIndex: "kisi_adi", key: "p", width: 170, align: "center" as const, render: (v: string) => <Kucuk kalin>{v}</Kucuk> }]
              : []),
            {
              title: "Faaliyet",
              dataIndex: "faaliyet",
              key: "f",
              width: 120,
              align: "center",
              render: (f: Faaliyet) => <Kucuk>{FAALIYET_ADLARI[f] ?? f}</Kucuk>,
            },
            { title: "Başlangıç\nTarihi", key: "bt", width: 100, align: "center", responsive: ["sm"], render: (_, r) => gunu(r.started_at) },
            { title: "Başlangıç\nSaati", key: "bs", width: 90, align: "center", render: (_, r) => saati(r.started_at) },
            {
              title: "Geçen",
              dataIndex: "gecen_dk",
              key: "g",
              width: 110,
              align: "center",
              render: (d: number | null, r) => (
                <Typography.Text type={r.uzun ? "danger" : undefined} strong>
                  {sureMetni(d) ?? "—"}
                </Typography.Text>
              ),
            },
          ]}
          veri={sayaclar}
          satirAnahtari="id"
          yukleniyor={aktif.isFetching}
          bosMetin="Açık sayaç yok"
          scrollX={760}
          secimModu={yonetici ? "tek" : "yok"}
          secili={seciliAktif}
          onSecim={(k) => setSeciliAktif(k as number[])}
          onSatirAc={
            yonetici
              ? (r) => {
                  kapatForm.resetFields();
                  setKapatilan(r);
                }
              : undefined
          }
          eylemler={
            yonetici
              ? [
                  {
                    anahtar: "saat_kapa",
                    ad: "Saat Kapa / Düzelt",
                    ikon: <ClockCircleOutlined />,
                    tehlikeli: !!seciliSayac?.uzun,
                    devreDisi: !seciliSayac,
                    ipucu: "Gerçek bitişle kapatır ya da iptal eder (yönetici düzeltmesi)",
                    onClick: () => {
                      if (!seciliSayac) return;
                      kapatForm.resetFields();
                      setKapatilan(seciliSayac);
                    },
                  },
                ]
              : undefined
          }
        />
      </FioriBolum>

      {ozet.data?.personel && (
        <FioriBolum baslik="Personel dağılımı ve veri disiplini" dolgusuz>
          <div className="fl-rapor" style={{ border: 0 }}>
            <Table<PersonelSatiri>
              className="fl-tablo"
              size="small"
              rowKey={(r) => String(r.user_id ?? r.ad)}
              dataSource={ozet.data.personel}
              columns={personelSutunlari}
              pagination={false}
              scroll={{ x: 1100 }}
              locale={{ emptyText: "Veri yok" }}
            />
          </div>
        </FioriBolum>
      )}

      {ayrinti.isError ? (
        <FioriBolum baslik="Ayrıntı">
          <Empty description={(ayrinti.error as ApiError).message} />
        </FioriBolum>
      ) : isListesi ? (
        <ListeRaporu<ZamanIsi>
          kayitSayisi={isler.data?.toplam}
          ustBilgi={kpiEtiketi}
          sutunlar={[
            {
              title: "Süre Kaydı",
              dataIndex: "sure_durumu",
              key: "sd",
              width: 140,
              align: "center",
              render: (d: string | null) => (
                <DurumBaglantisi metin={d ? (SURE_DURUMU_ADLARI[d] ?? d) : "—"} ton={d === "EKSIK" ? "olumsuz" : undefined} />
              ),
            },
            { title: "İş No", dataIndex: "so_no", key: "so", width: 170, align: "center", render: (v: string) => <NoRozeti no={v} /> },
            { title: "Açıklama", dataIndex: "konu", key: "k", width: 280, render: (v: string) => <Aciklama metin={v} /> },
            { title: "Sistem", dataIndex: "birim", key: "b", width: 130, align: "center", responsive: ["md"], render: (b: string) => <Kucuk>{BIRIM_ETIKETLERI[b] ?? b}</Kucuk> },
            { title: "Tamamlanma", dataIndex: "completed_at", key: "t", width: 140, align: "center", responsive: ["sm"], render: an },
            { title: "Kişi-saat", dataIndex: "kisi_saat_dk", key: "ks", width: 110, align: "center", render: sure },
          ]}
          veri={isler.data?.kayitlar ?? []}
          satirAnahtari="id"
          yukleniyor={isler.isFetching}
          scrollX={900}
          secimModu="yok"
          sayfalama={{ sayfa, boyut: SAYFA, toplam: isler.data?.toplam ?? 0, onChange: setSayfa }}
          eylemler={aktarir ? [{ anahtar: "excel", ad: "Excel'e aktar", ikon: <DownloadOutlined />, onClick: excelAc }] : undefined}
        />
      ) : (
        <ListeRaporu<ZamanKaydi>
          kategoriBasligi="Faaliyet"
          kategoriler={faaliyetKategorileri}
          seciliKategori={faaliyet ?? TUMU_KATEGORISI.kod}
          onKategori={(k) => {
            setFaaliyet(k === TUMU_KATEGORISI.kod ? undefined : k);
            setSayfa(1);
          }}
          kayitSayisi={kayitlar.data?.toplam}
          ustBilgi={kpiEtiketi}
          sutunlar={[
            {
              title: "Durum",
              key: "d",
              width: 130,
              align: "center",
              render: (_, r) => (
                <DurumBaglantisi
                  metin={r.ended_at ? "SAAT KAPANDI" : "SAAT AÇIK"}
                  ton={r.ended_at ? "kapali" : undefined}
                  alt={r.gecikmeli ? <AltNot tur="uyari">GECİKMELİ</AltNot> : undefined}
                />
              ),
            },
            { title: "İş No", dataIndex: "so_no", key: "so", width: 170, align: "center", render: (v: string) => <NoRozeti no={v} /> },
            { title: "Tarih", key: "t", width: 100, align: "center", render: (_, r) => gunu(r.started_at) },
            { title: "Başlangıç\nSaati", key: "bs", width: 90, align: "center", responsive: ["sm"], render: (_, r) => saati(r.started_at) },
            { title: "Bitiş\nSaati", key: "bb", width: 90, align: "center", responsive: ["sm"], render: (_, r) => (r.ended_at ? saati(r.ended_at) : "—") },
            { title: "Faaliyet", dataIndex: "faaliyet", key: "f", width: 110, align: "center", render: (f: Faaliyet) => <Kucuk>{FAALIYET_ADLARI[f] ?? f}</Kucuk> },
            ...(personelGorur
              ? [{ title: "Personel", dataIndex: "kisi_adi", key: "p", width: 160, align: "center" as const, render: (v: string) => <Kucuk kalin>{v}</Kucuk> }]
              : []),
            {
              title: "Süre",
              dataIndex: "sure_dk",
              key: "s",
              width: 100,
              align: "center",
              render: (d: number | null, r) => (r.ended_at ? sure(d) : "—"),
            },
            { title: "Kaynak", dataIndex: "kaynak", key: "k", width: 130, align: "center", responsive: ["md"], render: (k: string) => <KucukGri>{KAYNAK_ADLARI[k] ?? k}</KucukGri> },
            { title: "Sistem", dataIndex: "birim", key: "b", width: 120, align: "center", responsive: ["lg"], render: (b: string | null) => <Kucuk>{b ? (BIRIM_ETIKETLERI[b] ?? b) : null}</Kucuk> },
          ]}
          veri={kayitlar.data?.kayitlar ?? []}
          satirAnahtari="id"
          yukleniyor={kayitlar.isFetching}
          scrollX={1200}
          secimModu="yok"
          sayfalama={{ sayfa, boyut: SAYFA, toplam: kayitlar.data?.toplam ?? 0, onChange: setSayfa }}
          eylemler={aktarir ? [{ anahtar: "excel", ad: "Excel'e aktar", ikon: <DownloadOutlined />, onClick: excelAc }] : undefined}
        />
      )}

      <Modal
        open={kapatilan !== null}
        title={`Sayacı kapat / düzelt — ${kapatilan?.so_no ?? ""}`}
        okText="Kaydet"
        cancelText="Vazgeç"
        confirmLoading={kapat.isPending}
        onCancel={() => setKapatilan(null)}
        onOk={() => void kapatForm.validateFields().then((v) => kapat.mutate(v))}
      >
        <Typography.Paragraph type="secondary">
          Gerçek bitiş girilirse bölüm o saatte kapanır (yönetici düzeltmesi). Boş bırakılırsa sayaç
          İPTAL edilir ve kişi-saate girmez.
        </Typography.Paragraph>
        <Form form={kapatForm} layout="vertical">
          <Form.Item name="gercek_bitis" label="Gerçek bitiş (isteğe bağlı)">
            <DatePicker
              showTime={{ format: "HH:mm" }}
              format="DD.MM.YYYY HH:mm"
              style={{ width: "100%" }}
              disabledDate={(d) =>
                d.isAfter(dayjs(), "day") || (!!kapatilan && d.isBefore(dayjs(kapatilan.started_at), "day"))
              }
            />
          </Form.Item>
          <Form.Item name="gerekce" label="Gerekçe" rules={[{ required: true, whitespace: true, message: "Gerekçe zorunlu" }]}>
            <Input.TextArea maxLength={300} autoSize={{ minRows: 2, maxRows: 4 }} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
