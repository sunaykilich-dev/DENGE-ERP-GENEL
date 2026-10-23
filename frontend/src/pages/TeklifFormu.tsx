import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  DatePicker,
  Input,
  InputNumber,
  Select,
  Space,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useEffect, useMemo, useState } from "react";

import { api, type ApiError } from "../api/client";
import { teknikServisApi } from "../api/teknikServis";
import { useAuth } from "../auth/AuthContext";
import { marka } from "../theme";

/**
 * Teklif hazırlama — solda form, sağda CANLI A4 önizleme.
 *
 * Önizleme, basılacak PDF'in (templates/teklif.html) düzenini birebir
 * izler ve başlık bilgilerini aynı uçtan alır. Ayrı kaynaklardan
 * beslenseydi ekranda görülen teklifle müşteriye giden teklif ayrışırdı —
 * ve bu ancak müşteri şikâyet edince fark edilirdi.
 *
 * Tutarlar burada da hesaplanır ama BAĞLAYICI DEĞİL: kaydedildiğinde
 * sunucu kendi hesabını yapar ve dondurur. Buradaki hesap yalnız
 * yazarken görmek içindir.
 */

interface Urun {
  id: number;
  code: string;
  name: string;
  brand: string | null;
  list_price: number | null;
  currency: string;
  vat_rate: number | null;
}

interface Hesap {
  id: number;
  title: string;
  tax_no: string | null;
  tax_office: string | null;
  // Önizlemede müşteri bloğu bunları gösteriyor; PDF de aynı alanları basıyor.
  phone: string | null;
  email: string | null;
  region: string | null;
}

interface Baslik {
  firma: {
    unvan: string;
    adres: string;
    telefon: string;
    eposta: string;
    vkn: string;
    vergi_dairesi: string;
    mersis: string;
    kep: string;
  };
  sartlar: string;
  kdv_varsayilan: number;
  /** Birimli (servis) teklifte izinli KDV oranları (kesir). */
  birimli_kdv_oranlari?: number[];
}

interface Kalem {
  anahtar: number;
  item_type: string;
  product_id?: number;
  description: string;
  qty: number;
  unit_price?: number;
  discount_pct: number;
  vat_rate?: number;
}

const KALEM_TIPLERI = [
  { value: "URUN", label: "Ürün" },
  { value: "HIZMET", label: "Hizmet" },
  { value: "ABONELIK", label: "Abonelik" },
  { value: "SIM_PAKETI", label: "SIM paketi" },
  { value: "SERBEST", label: "Serbest" },
];

/** Birimli (servis) teklifte kalem tipleri: abonelik/SIM yok, işçilik var. */
const BIRIMLI_KALEM_TIPLERI = [
  { value: "URUN", label: "Ürün / parça" },
  { value: "ISCILIK", label: "İşçilik" },
  { value: "HIZMET", label: "Hizmet" },
  { value: "SERBEST", label: "Serbest" },
];

const PARA_ISARETI: Record<string, string> = { TRY: "₺", USD: "$", EUR: "€" };

/** Sondaki anlamsız sıfırları atar: 20.0000 → 20, 1.00 → 1, 2.50 → 2.5. */
const sade = (v: number | string | undefined) => {
  const s = Number(v ?? 0);
  return Number.isFinite(s) ? String(Number(s.toFixed(4))) : "0";
};

/** Satırın KDV hariç net tutarı — belgede "TUTAR" sütunu. */
const satirTutari = (k: Kalem) => {
  const brut = (k.qty || 0) * (k.unit_price ?? 0);
  return brut - brut * ((k.discount_pct || 0) / 100);
};

const bicim = (v: number, para = "TRY") =>
  `${v.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${
    PARA_ISARETI[para] ?? para
  }`;

let sayac = 1;
const bosKalem = (kdv: number): Kalem => ({
  anahtar: sayac++,
  item_type: "URUN",
  description: "",
  qty: 1,
  discount_pct: 0,
  vat_rate: kdv,
});

export default function TeklifFormu({
  onKaydedildi,
  servisIsiId,
}: {
  onKaydedildi?: (id?: number) => void;
  /** Servis işinden teklif (TS-147): müşteri, birim ve adres işten gelir. */
  servisIsiId?: number;
}) {
  const { message } = App.useApp();
  const { kullanici } = useAuth();
  const qc = useQueryClient();
  const birimlerim = kullanici?.birimler ?? [];

  const [musteriId, setMusteriId] = useState<number>();
  const [birim, setBirim] = useState<string | undefined>(
    servisIsiId ? undefined : birimlerim.length === 1 ? birimlerim[0] : undefined,
  );
  const [musteriArama, setMusteriArama] = useState("");
  const [baslikMetni, setBaslikMetni] = useState("");
  const [paraBirimi, setParaBirimi] = useState("TRY");
  const [gecerlilik, setGecerlilik] = useState<Dayjs | null>(dayjs().add(15, "day"));
  const [kalemler, setKalemler] = useState<Kalem[]>([]);
  const [not, setNot] = useState("");

  const baslik = useQuery({
    queryKey: ["teklif-baslik"],
    queryFn: () => api.get<Baslik>("/api/teklifler/belge-basligi"),
  });
  const kdvVarsayilan = baslik.data?.kdv_varsayilan ?? 0.2;

  const urunler = useQuery({
    queryKey: ["teklif-urunler"],
    queryFn: () => api.get<Urun[]>("/api/urunler?limit=500"),
  });
  const musteriler = useQuery({
    queryKey: ["teklif-musteri", musteriArama],
    queryFn: () =>
      api.get<Hesap[]>(
        `/api/hesaplar?rol=MUSTERI&limit=50${
          musteriArama ? `&q=${encodeURIComponent(musteriArama)}` : ""
        }`,
      ),
  });

  const servisIsi = useQuery({
    queryKey: ["teklif-servis-isi", servisIsiId],
    queryFn: () => teknikServisApi.getir(servisIsiId as number),
    enabled: servisIsiId != null,
  });
  useEffect(() => {
    const so = servisIsi.data;
    if (!so) return;
    setBirim(so.birim);
    if (so.customer_id) setMusteriId(so.customer_id);
    setBaslikMetni((o) => o || `${so.so_no} · ${so.konu}`);
  }, [servisIsi.data]);

  const birimli = !!birim;
  const kdvOranlari = baslik.data?.birimli_kdv_oranlari ?? [0, 0.01, 0.1, 0.2];

  const musteri = (musteriler.data ?? []).find((m) => m.id === musteriId);
  const musteriSecenekleri = (musteriler.data ?? []).map((m) => ({ value: m.id, label: m.title }));
  if (servisIsi.data?.musteri && !musteriSecenekleri.some((o) => o.value === musteriId)) {
    musteriSecenekleri.unshift({
      value: servisIsi.data.musteri.id,
      label: servisIsi.data.musteri.title,
    });
  }

  const kaydet = useMutation({
    mutationFn: (govde: Record<string, unknown>) =>
      api.post<{ id: number; quote_no: string; uyarilar?: string[] }>("/api/teklifler", govde),
    onSuccess: (t) => {
      message.success(`${t.quote_no} oluşturuldu`);
      for (const u of t.uyarilar ?? []) message.warning(u);
      setKalemler([]);
      setBaslikMetni("");
      void qc.invalidateQueries({ queryKey: ["teklifler"] });
      onKaydedildi?.(t.id);
    },
    onError: (e: ApiError) => message.error(e.message),
  });

  function degis(anahtar: number, yama: Partial<Kalem>) {
    setKalemler((o) => o.map((k) => (k.anahtar === anahtar ? { ...k, ...yama } : k)));
  }

  function urunSec(anahtar: number, product_id: number) {
    const u = urunler.data?.find((x) => x.id === product_id);
    degis(anahtar, {
      product_id,
      // Liste fiyatı ve KDV ürün kartından doluyor; ikisi de elle
      // değiştirilebilir ve kaydedilince belgeye DONDURULUR.
      description: u ? (u.brand ? `${u.brand} ${u.name}` : u.name) : "",
      unit_price: u?.list_price ?? undefined,
      vat_rate: u?.vat_rate ?? kdvVarsayilan,
    });
  }

  const toplam = useMemo(() => {
    let ara = 0;
    let iskonto = 0;
    let kdv = 0;
    for (const k of kalemler) {
      const brut = (k.qty || 0) * (k.unit_price ?? 0);
      const isk = brut * ((k.discount_pct || 0) / 100);
      const net = brut - isk;
      ara += brut;
      iskonto += isk;
      kdv += net * (k.vat_rate ?? kdvVarsayilan);
    }
    return { ara, iskonto, kdv, genel: ara - iskonto + kdv };
  }, [kalemler, kdvVarsayilan]);

  const eksikler: string[] = [];
  if (!musteriId) eksikler.push("müşteri");
  if (kalemler.length === 0) eksikler.push("en az bir kalem");
  kalemler.forEach((k, i) => {
    if (k.item_type === "URUN" && !k.product_id) eksikler.push(`${i + 1}. kalemde ürün`);
    if (k.item_type !== "URUN" && (!k.description.trim() || k.unit_price == null))
      eksikler.push(`${i + 1}. kalemde açıklama ve fiyat`);
  });

  function gonder() {
    kaydet.mutate({
      customer_id: musteriId,
      ...(birim ? { birim } : {}),
      ...(servisIsiId ? { service_order_id: servisIsiId } : {}),
      title: baslikMetni || null,
      currency: paraBirimi,
      valid_until: gecerlilik ? gecerlilik.format("YYYY-MM-DD") : null,
      kalemler: kalemler.map((k) => ({
        item_type: k.item_type,
        product_id: k.item_type === "URUN" ? k.product_id : null,
        description: k.description || null,
        qty: k.qty,
        unit_price: k.unit_price ?? null,
        discount_pct: k.discount_pct,
        vat_rate: k.vat_rate ?? kdvVarsayilan,
      })),
      notes: not || null,
    });
  }

  const f = baslik.data?.firma;
  const kullaniciAdi = kullanici?.full_name ?? "—";

  return (
    <div style={{ display: "flex", gap: 20, alignItems: "flex-start", flexWrap: "wrap" }}>
      {/* ---------- SOL: form ---------- */}
      <div style={{ flex: "1 1 430px", minWidth: 380, maxWidth: 560 }}>
        <Space orientation="vertical" size={14} style={{ width: "100%" }}>
          <Bolum baslik="Teklif bilgileri">
            {servisIsiId != null && (
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 10 }}
                title={
                  servisIsi.data
                    ? `${servisIsi.data.so_no} servis işinden teklif`
                    : "Servis işi yükleniyor…"
                }
                description="Müşteri, birim, adres ve irtibat işten alınır; kabul edilince KDV hariç net tutar işin gelirine aktarılır."
              />
            )}
            {servisIsi.isError && (
              <Alert
                type="error"
                showIcon
                style={{ marginBottom: 10 }}
                title={(servisIsi.error as ApiError).message}
              />
            )}
            {birimlerim.length > 0 && (
              <Alan etiket="Birim (servis teklifi)">
                <Select
                  allowClear={birimlerim.length > 1 || !servisIsiId}
                  disabled={servisIsiId != null}
                  value={birim}
                  onChange={(b) => {
                    setBirim(b);
                    // Birimli teklifte abonelik/SIM kalemi yok; tipi sıfırla.
                    setKalemler((o) =>
                      o.map((k) =>
                        b && ["ABONELIK", "SIM_PAKETI"].includes(k.item_type)
                          ? { ...k, item_type: "HIZMET" }
                          : !b && k.item_type === "ISCILIK"
                            ? { ...k, item_type: "HIZMET" }
                            : k,
                      ),
                    );
                  }}
                  placeholder="Boş = satış teklifi"
                  style={{ width: "100%" }}
                  options={birimlerim.map((b) => ({ value: b, label: b }))}
                />
              </Alan>
            )}
            <Alan etiket="Müşteri" zorunlu>
              <Select
                showSearch
                disabled={servisIsiId != null}
                value={musteriId}
                onChange={setMusteriId}
                onSearch={setMusteriArama}
                filterOption={false}
                placeholder="Ara…"
                style={{ width: "100%" }}
                loading={musteriler.isLoading}
                options={musteriSecenekleri}
              />
            </Alan>
            <Alan etiket="Teklif başlığı">
              <Input
                value={baslikMetni}
                onChange={(e) => setBaslikMetni(e.target.value)}
                placeholder="Araç takip sistemi kurulumu"
              />
            </Alan>
            <Space style={{ width: "100%" }} size={10}>
              <Alan etiket="Geçerlilik tarihi">
                <DatePicker
                  value={gecerlilik}
                  onChange={setGecerlilik}
                  format="DD.MM.YYYY"
                  style={{ width: 160 }}
                />
              </Alan>
              <Alan etiket="Para birimi">
                <Select
                  value={paraBirimi}
                  onChange={setParaBirimi}
                  style={{ width: 110 }}
                  options={["TRY", "USD", "EUR"].map((p) => ({ value: p, label: p }))}
                />
              </Alan>
            </Space>
          </Bolum>

          <Bolum
            baslik={`Teklif kalemleri (${kalemler.length})`}
            ek={
              <Button
                size="small"
                icon={<PlusOutlined />}
                onClick={() => setKalemler((o) => [...o, bosKalem(kdvVarsayilan)])}
              >
                Kalem ekle
              </Button>
            }
          >
            {kalemler.length === 0 && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                Henüz kalem yok. "Kalem ekle" ile başlayın — sağdaki önizleme anında güncellenir.
              </Typography.Text>
            )}
            <Space orientation="vertical" size={10} style={{ width: "100%" }}>
              {kalemler.map((k, i) => (
                <div
                  key={k.anahtar}
                  style={{
                    border: `1px solid ${marka.ruleSoft}`,
                    borderRadius: 6,
                    padding: 10,
                    background: marka.card2,
                  }}
                >
                  <Space style={{ width: "100%", justifyContent: "space-between" }}>
                    <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                      {i + 1}. kalem
                    </Typography.Text>
                    <Button
                      size="small"
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() =>
                        setKalemler((o) => o.filter((x) => x.anahtar !== k.anahtar))
                      }
                    />
                  </Space>
                  <Space orientation="vertical" size={6} style={{ width: "100%" }}>
                    <Space size={6} style={{ width: "100%" }}>
                      <Select
                        value={k.item_type}
                        onChange={(v) => degis(k.anahtar, { item_type: v })}
                        style={{ width: 120 }}
                        options={birimli ? BIRIMLI_KALEM_TIPLERI : KALEM_TIPLERI}
                      />
                      {k.item_type === "URUN" ? (
                        <Select
                          showSearch
                          optionFilterProp="label"
                          value={k.product_id}
                          onChange={(v) => urunSec(k.anahtar, v)}
                          placeholder="Ürün seçin"
                          style={{ flex: 1, minWidth: 180 }}
                          options={(urunler.data ?? []).map((u) => ({
                            value: u.id,
                            label: `${u.code} · ${u.name}`,
                          }))}
                        />
                      ) : (
                        <Input
                          value={k.description}
                          onChange={(e) => degis(k.anahtar, { description: e.target.value })}
                          placeholder={k.item_type === "ISCILIK" ? "İşçilik açıklaması" : "Açıklama"}
                          maxLength={birimli ? 500 : 300}
                          style={{ flex: 1, minWidth: 180 }}
                        />
                      )}
                    </Space>
                    {k.item_type === "URUN" && (
                      <Input
                        value={k.description}
                        onChange={(e) => degis(k.anahtar, { description: e.target.value })}
                        placeholder="Açıklama (boşsa ürün adı kullanılır)"
                        size="small"
                      />
                    )}
                    <Space size={6} wrap>
                      <InputNumber
                        value={k.qty}
                        onChange={(v) => degis(k.anahtar, { qty: v ?? 1 })}
                        min={0.01}
                        addonBefore="Adet"
                        style={{ width: 130 }}
                      />
                      <InputNumber
                        value={k.unit_price}
                        onChange={(v) => degis(k.anahtar, { unit_price: v ?? undefined })}
                        min={0}
                        addonBefore="Fiyat"
                        style={{ width: 170 }}
                      />
                      <InputNumber
                        value={k.discount_pct}
                        onChange={(v) => degis(k.anahtar, { discount_pct: v ?? 0 })}
                        min={0}
                        max={100}
                        addonBefore="İsk."
                        addonAfter="%"
                        style={{ width: 150 }}
                      />
                      {birimli ? (
                        // Servis teklifinde KDV beyaz listeden seçilir (sunucu da denetler).
                        <Select
                          value={k.vat_rate ?? kdvVarsayilan}
                          onChange={(v) => degis(k.anahtar, { vat_rate: v })}
                          style={{ width: 120 }}
                          options={kdvOranlari.map((o) => ({
                            value: o,
                            label: `KDV %${Math.round(o * 100)}`,
                          }))}
                        />
                      ) : (
                        <InputNumber
                          // KDV oranı KESİR saklanır (0.20 = %20); ekranda yüzde
                          // gösterilir çünkü kullanıcı "20" yazmak ister.
                          value={Math.round((k.vat_rate ?? kdvVarsayilan) * 100)}
                          onChange={(v) => degis(k.anahtar, { vat_rate: (v ?? 20) / 100 })}
                          min={0}
                          max={100}
                          addonBefore="KDV"
                          addonAfter="%"
                          style={{ width: 150 }}
                        />
                      )}
                    </Space>
                  </Space>
                </div>
              ))}
            </Space>
          </Bolum>

          <Bolum baslik="Not">
            <Input.TextArea
              value={not}
              onChange={(e) => setNot(e.target.value)}
              rows={3}
              placeholder="İç not — teklif belgesine basılmaz."
            />
          </Bolum>

          <Space wrap>
            <Button
              type="primary"
              size="large"
              loading={kaydet.isPending}
              disabled={eksikler.length > 0}
              onClick={gonder}
            >
              Teklifi oluştur
            </Button>
            {eksikler.length > 0 && (
              <Typography.Text type="danger" style={{ fontSize: 12 }}>
                Eksik: {eksikler.slice(0, 2).join(", ")}
                {eksikler.length > 2 ? "…" : ""}
              </Typography.Text>
            )}
          </Space>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Kaydedildiğinde fiyat, iskonto ve KDV belgeye <strong>dondurulur</strong>:
            parametreler sonradan değişse de bu teklif değişmez.
          </Typography.Text>
        </Space>
      </div>

      {/* ---------- SAĞ: canlı A4 önizleme ----------
          Tasarım `~/denge-teklif/teklif-formu.html` referansıyla BİREBİR aynı
          ve PDF şablonuyla (backend/app/templates/teklif.html) ölçü ölçü
          eşleşir. Marka RENKLERİ burada kullanılmaz — belge sade, ticari bir
          form; siyah ince çerçeve. Yazı tipi ise ERP'nin geri kalanıyla aynı
          (Archivo): tek belgeyi ayrı bir yazı tipine bırakmak tutarsızdı
          (kullanıcı kararı, 30 Eyl 2026). Ekranda başka, PDF'te başka bir şey
          görmek teklif hazırlayanın işine yaramıyordu. */}
      <div style={{ flex: "1 1 520px", minWidth: 380 }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          Önizleme — basılacak PDF'in birebir düzeni
        </Typography.Text>
        <div className="teklif-kapsayici" style={{ marginTop: 6 }}>
        <div className="teklif-sayfa">
          <div className="s-top">
            <div>
              <img className="s-logo" src="/brand/denge-mobilite.png" alt={f?.unvan ?? ""} />
              <div className="s-addr">
                {f?.adres}
                <br />
                Telefon: {f?.telefon}
                {f?.eposta ? `   ${f.eposta}` : ""}
              </div>
            </div>
            <table className="s-meta">
              <tbody>
                <tr>
                  <td className="lbl">TARİH</td>
                  <td className="val">{dayjs().format("DD.MM.YYYY")}</td>
                </tr>
                <tr>
                  <td className="lbl">Teklif No.</td>
                  <td className="val">{"— (kayıtta verilir)"}</td>
                </tr>
                <tr>
                  <td className="lbl">Müşteri Kimliği</td>
                  <td className="val">{musteri?.tax_no || musteri?.id || "—"}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div className="s-titleline">
            <div className="s-title">Fiyat Teklifi</div>
            <div className="s-validity">
              <span className="vurgu">Teklif geçerlilik tarihi:</span>
              <span>{gecerlilik ? gecerlilik.format("DD.MM.YYYY") : "—"}</span>
            </div>
          </div>

          <div className="s-parties">
            <div className="s-customer">
              Şirket Adı : {musteri?.title ?? "—"}
              <br />
              Açık Adres : {musteri?.region ?? "—"}
              <br />
              Telefon : {musteri?.phone ?? "—"}
            </div>
            <div className="s-preparer">
              <span className="h">Hazırlayan:</span>
              <br />
              {kullaniciAdi}
              <br />
              {f?.telefon}
              <br />
              {f?.eposta}
            </div>
          </div>

          <div className="s-note">
            <b>Açıklamalar veya Özel Yönergeler:</b>
            {baslikMetni || ""}
          </div>

          <table className="grid s-items">
            <thead>
              <tr>
                <th style={{ width: "16%" }}>MİKTAR</th>
                <th style={{ width: "36%" }}>AÇIKLAMA</th>
                <th style={{ width: "16%" }}>BİRİM FİYATI</th>
                <th style={{ width: "16%" }}>Vergi Oranı</th>
                <th style={{ width: "16%" }}>TUTAR</th>
              </tr>
            </thead>
            <tbody>
              {kalemler.map((k, i) => (
                <tr key={i}>
                  <td className="qty">{sade(k.qty)}</td>
                  <td className="desc">
                    {k.description || "—"}
                    {Number(k.discount_pct) > 0 ? ` (%${sade(k.discount_pct)} iskonto)` : ""}
                  </td>
                  <td className="unit">{bicim(Number(k.unit_price) || 0, paraBirimi)}</td>
                  <td className="tax">%{sade(Number(k.vat_rate) * 100)}</td>
                  <td className="amt">{bicim(satirTutari(k), paraBirimi)}</td>
                </tr>
              ))}
              {Array.from({ length: Math.max(0, 8 - kalemler.length) }).map((_, i) => (
                <tr key={`bos-${i}`}>
                  <td className="qty">&nbsp;</td>
                  <td className="desc" />
                  <td className="unit" />
                  <td className="tax" />
                  <td className="amt" />
                </tr>
              ))}
            </tbody>
          </table>

          <div className="s-bottom">
            <div className="s-notes">
              {(baslik.data?.sartlar ?? "")
                .split("\n")
                .filter((x) => x.trim())
                .map((x, i) => (
                  <p key={i}>{x.trim()}</p>
                ))}
            </div>
            <table className="s-totals">
              <tbody>
                <tr>
                  <td className="lbl">ARA TOPLAM</td>
                  <td className="box">{bicim(toplam.ara, paraBirimi)}</td>
                </tr>
                {toplam.iskonto > 0 && (
                  <tr>
                    <td className="lbl">İSKONTO</td>
                    <td className="box">{bicim(toplam.iskonto, paraBirimi)}</td>
                  </tr>
                )}
                <tr>
                  <td className="lbl">SATIŞ VERGİSİ</td>
                  <td className="box">{bicim(toplam.kdv, paraBirimi)}</td>
                </tr>
                <tr className="grand">
                  <td className="lbl">TOPLAM</td>
                  <td className="box">{bicim(toplam.genel, paraBirimi)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        </div>

        {!f?.vkn && (
          <Alert
            style={{ marginTop: 10 }}
            type="info"
            title="Şirket künyesi eksik"
            description="Resmî unvan, VKN, vergi dairesi ve MERSİS Parametreler ekranından girilince hem önizlemede hem PDF'te görünür."
          />
        )}
      </div>
    </div>
  );
}

function Bolum({
  baslik,
  ek,
  children,
}: {
  baslik: string;
  ek?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        border: `1px solid ${marka.rule}`,
        borderRadius: 8,
        padding: "10px 14px 14px",
        background: "#fff",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 10,
        }}
      >
        <span
          style={{
            fontSize: 11,
            fontWeight: 700,
            color: marka.signal,
            textTransform: "uppercase",
            letterSpacing: ".04em",
          }}
        >
          {baslik}
        </span>
        {ek}
      </div>
      {children}
    </div>
  );
}

function Alan({
  etiket,
  zorunlu,
  children,
}: {
  etiket: string;
  zorunlu?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div style={{ marginBottom: 8 }}>
      <label
        style={{
          display: "block",
          fontSize: 11.5,
          fontWeight: 600,
          color: marka.ink2,
          marginBottom: 3,
        }}
      >
        {zorunlu && <span style={{ color: marka.alarm }}>* </span>}
        {etiket}
      </label>
      {children}
    </div>
  );
}
