import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  DatePicker,
  Divider,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useEffect, useState } from "react";

import { api, type ApiError } from "../api/client";

/**
 * Montaj / söküm girişi.
 *
 * Canlı hak ediş uygulamasının giriş hızı korunuyor: montaj noktası seçilince
 * yetkili ve yol birim fiyatı doluyor, tarife önizleniyor, IMEI çakışması
 * anında uyarıyor, kaydettikten sonra firma/nokta/tarih SABİT kalıp yalnız
 * araca özel alanlar temizleniyor (seri giriş).
 *
 * Farkı: bir iş emri = bir ZİYARET, içine ikinci bir cihaz satırı eklenebilir.
 * Araçların %96,8'inde birden fazla cihaz var ve hak ediş kalem başına
 * ödeniyor — tek kayda indirgemek ya işi ya parayı kaybettirirdi.
 */

interface MontajNoktasi {
  id: number;
  unvan: string;
  yetkili: string | null;
  telefon: string | null;
  yol_birim_fiyat: number | null;
}

interface UrunSecenegi {
  id: number;
  kod: string;
  ad: string;
  marka: string | null;
  aile: string | null;
  identity_kind: string;
  varsayilan_rol: string | null;
}

interface FormVerileri {
  montaj_noktalari: MontajNoktasi[];
  urunler: UrunSecenegi[];
  is_tipleri: string[];
  odenmeme_nedenleri: string[];
}

interface Hesap {
  id: number;
  title: string;
}

interface Cakisma {
  device_id: number;
  status: string;
  plaka: string | null;
  musteri: string | null;
  takildi: string;
}

interface Kalem {
  anahtar: number;
  kimlik: string;
  product_id?: number;
  device_role?: string;
  action?: string;
  payability: string;
  non_payable_reason?: string;
  unit_price?: number;
}

const ROLLER = [
  { value: "BIRINCIL_TAKIP", label: "Birincil takip (ATS)" },
  { value: "OBD_TAKIP", label: "OBD takip (prize takılan ATS)" },
  { value: "KAMERA", label: "Kamera / dashcam" },
  { value: "YARDIMCI_KAMERA", label: "Yardımcı kamera" },
  { value: "AKSESUAR", label: "Aksesuar" },
];

const EYLEMLER = ["TAKILDI", "SOKULDU", "DEGISTIRILDI", "KONTROL"];

const ODEME = [
  { value: "ODENECEK", label: "Ödenecek" },
  { value: "ODENMEYECEK", label: "Ödenmeyecek" },
  { value: "KARAR_BEKLIYOR", label: "Karar bekliyor" },
];

const tl = (v: number | null | undefined) =>
  v == null ? "—" : `${Number(v).toLocaleString("tr-TR", { minimumFractionDigits: 2 })} ₺`;

let sayac = 1;
const bosKalem = (): Kalem => ({ anahtar: sayac++, kimlik: "", payability: "ODENECEK" });

export default function IsEmriFormu({ onKaydedildi }: { onKaydedildi?: () => void }) {
  const { message } = App.useApp();
  const qc = useQueryClient();

  const [tarih, setTarih] = useState<Dayjs>(dayjs());
  const [tip, setTip] = useState("MONTAJ");
  const [noktaId, setNoktaId] = useState<number>();
  const [musteriId, setMusteriId] = useState<number>();
  const [musteriArama, setMusteriArama] = useState("");
  const [plaka, setPlaka] = useState("");
  const [sase, setSase] = useState("");
  const [ruhsat, setRuhsat] = useState("");
  const [km, setKm] = useState<number>();
  const [donem, setDonem] = useState("");
  const [yolKm, setYolKm] = useState<number>();
  const [yolBirim, setYolBirim] = useState<number>();
  const [blokajli, setBlokajli] = useState(false);
  const [not, setNot] = useState("");
  const [kalemler, setKalemler] = useState<Kalem[]>([bosKalem()]);
  const [cakismalar, setCakismalar] = useState<Record<number, Cakisma | null>>({});

  const veriler = useQuery({
    queryKey: ["isemri-form"],
    queryFn: () => api.get<FormVerileri>("/api/is-emirleri/form-verileri"),
  });

  const musteriler = useQuery({
    queryKey: ["isemri-musteri", musteriArama],
    queryFn: () =>
      api.get<Hesap[]>(
        `/api/hesaplar?rol=MUSTERI&limit=50${musteriArama ? `&q=${encodeURIComponent(musteriArama)}` : ""}`,
      ),
  });

  const nokta = veriler.data?.montaj_noktalari.find((n) => n.id === noktaId);

  // Montaj noktası seçilince yol birim fiyatı dolar — elle değiştirilebilir.
  useEffect(() => {
    if (nokta?.yol_birim_fiyat != null) setYolBirim(Number(nokta.yol_birim_fiyat));
  }, [nokta]);

  const kaydet = useMutation({
    mutationFn: (govde: Record<string, unknown>) => api.post("/api/is-emirleri", govde),
    onSuccess: () => {
      message.success("İş emri kaydedildi. Araç bilgilerini doldurup yenisini girebilirsiniz.");
      // Seri giriş: firma, nokta, tarih, tip ve ücret korunur; araca özel
      // alanlar temizlenir. Eski uygulamanın en çok kullanılan davranışı.
      setPlaka("");
      setSase("");
      setRuhsat("");
      setKm(undefined);
      setKalemler([bosKalem()]);
      setCakismalar({});
      void qc.invalidateQueries({ queryKey: ["isemirleri"] });
      void qc.invalidateQueries({ queryKey: ["hakedis-panel"] });
      onKaydedildi?.();
    },
    onError: (e: ApiError) => void message.error(e.message),
  });

  async function imeiKontrol(k: Kalem) {
    const kimlik = k.kimlik.trim();
    if (kimlik.length < 6) {
      setCakismalar((o) => ({ ...o, [k.anahtar]: null }));
      return;
    }
    try {
      const r = await api.get<{ cakisma: Cakisma | null }>(
        `/api/is-emirleri/imei-kontrol?kimlik=${encodeURIComponent(kimlik)}`,
      );
      setCakismalar((o) => ({ ...o, [k.anahtar]: r.cakisma }));
    } catch {
      /* kontrol başarısızsa kayıt engellenmez */
    }
  }

  function kalemDegis(anahtar: number, yama: Partial<Kalem>) {
    setKalemler((o) => o.map((k) => (k.anahtar === anahtar ? { ...k, ...yama } : k)));
  }

  function urunSec(anahtar: number, product_id: number) {
    const u = veriler.data?.urunler.find((x) => x.id === product_id);
    kalemDegis(anahtar, {
      product_id,
      // Cihaz modeli rolü belirler; rol de hak ediş iş tipini ve tarifeyi.
      device_role: u?.varsayilan_rol ?? "BIRINCIL_TAKIP",
    });
  }

  const eksikler: string[] = [];
  if (!tarih) eksikler.push("tarih");
  if (!noktaId) eksikler.push("montaj noktası");
  if (!plaka.trim() && !sase.trim()) eksikler.push("plaka ya da şase");
  kalemler.forEach((k, i) => {
    if (!k.kimlik.trim()) eksikler.push(`${i + 1}. kalem kimliği`);
    if (k.payability === "ODENMEYECEK" && !k.non_payable_reason)
      eksikler.push(`${i + 1}. kalem ödenmeme nedeni`);
  });

  const kalemToplam = kalemler
    .filter((k) => k.payability === "ODENECEK")
    .reduce((t, k) => t + (k.unit_price ?? 0), 0);
  const yolToplam = (yolKm ?? 0) * (yolBirim ?? 0);

  function gonder() {
    kaydet.mutate({
      type: tip,
      completed_at: tarih.format("YYYY-MM-DD"),
      assigned_id: noktaId,
      customer_id: musteriId,
      plaka: plaka.trim() || null,
      sase_no: sase.trim() || null,
      ruhsat_no: ruhsat.trim() || null,
      odometer_km: km,
      settlement_period: donem || null,
      travel_km: yolKm ?? null,
      travel_unit_price: yolBirim ?? null,
      blokajli,
      notes: not || null,
      kalemler: kalemler.map((k) => ({
        kimlik: k.kimlik.trim(),
        product_id: k.product_id,
        action: k.action,
        device_role: k.device_role,
        payability: k.payability,
        non_payable_reason: k.non_payable_reason,
        unit_price: k.unit_price,
      })),
    });
  }

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Card size="small" title="İş bilgisi">
        <Space wrap size={16} align="start">
          <Form.Item label="Tarih" required style={{ marginBottom: 0 }}>
            <DatePicker
              value={tarih}
              onChange={(d) => d && setTarih(d)}
              format="DD.MM.YYYY"
              allowClear={false}
              style={{ width: 160 }}
            />
          </Form.Item>
          <Form.Item label="İşlem tipi" required style={{ marginBottom: 0 }}>
            <Select
              value={tip}
              onChange={setTip}
              style={{ width: 170 }}
              options={(veriler.data?.is_tipleri ?? []).map((t) => ({
                value: t,
                label: t.replaceAll("_", " "),
              }))}
            />
          </Form.Item>
          <Form.Item
            label="Hak ediş dönemi"
            style={{ marginBottom: 0 }}
            tooltip="Boş bırakılırsa işin ayı kullanılır. İş bir ay yapılıp sonraki ayın hak edişinde ödenebilir; bu yüzden ayrı alan."
          >
            <Input
              value={donem}
              onChange={(e) => setDonem(e.target.value.trim())}
              placeholder={tarih.format("YYYY-MM")}
              style={{ width: 130 }}
              className="mono"
            />
          </Form.Item>
          <Form.Item label=" " style={{ marginBottom: 0 }}>
            <Checkbox checked={blokajli} onChange={(e) => setBlokajli(e.target.checked)}>
              Blokajlı (röle ile marş kesme)
            </Checkbox>
          </Form.Item>
        </Space>
      </Card>

      <Card size="small" title="Montaj noktası">
        <Space wrap size={16} align="start">
          <Form.Item label="Montaj noktası" required style={{ marginBottom: 0 }}>
            <Select
              showSearch
              optionFilterProp="label"
              value={noktaId}
              onChange={setNoktaId}
              style={{ width: 300 }}
              placeholder="Seçiniz…"
              loading={veriler.isLoading}
              options={(veriler.data?.montaj_noktalari ?? []).map((n) => ({
                value: n.id,
                label: n.unvan,
              }))}
            />
          </Form.Item>
          <Form.Item label="Yetkili" style={{ marginBottom: 0 }}>
            <Input value={nokta?.yetkili ?? ""} disabled style={{ width: 200 }} />
          </Form.Item>
          <Form.Item label="Telefon" style={{ marginBottom: 0 }}>
            <Input value={nokta?.telefon ?? ""} disabled className="mono" style={{ width: 160 }} />
          </Form.Item>
        </Space>
        {noktaId && !nokta?.yetkili && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Bu noktanın yetkili kişisi girilmemiş — Hesaplar ekranından ekleyebilirsiniz.
          </Typography.Text>
        )}
      </Card>

      <Card size="small" title="Firma ve araç">
        <Space wrap size={16} align="start">
          <Form.Item label="Firma" style={{ marginBottom: 0 }}>
            <Select
              showSearch
              allowClear
              value={musteriId}
              onChange={setMusteriId}
              onSearch={setMusteriArama}
              filterOption={false}
              style={{ width: 300 }}
              placeholder="Ara…"
              loading={musteriler.isLoading}
              options={(musteriler.data ?? []).map((m) => ({ value: m.id, label: m.title }))}
            />
          </Form.Item>
          <Form.Item label="Plaka" required style={{ marginBottom: 0 }}>
            <Input
              value={plaka}
              onChange={(e) => setPlaka(e.target.value.toLocaleUpperCase("tr-TR"))}
              placeholder="34ABC123"
              className="mono"
              style={{ width: 150 }}
            />
          </Form.Item>
          <Form.Item label="Şase no" style={{ marginBottom: 0 }}>
            <Input
              value={sase}
              onChange={(e) => setSase(e.target.value.toLocaleUpperCase("tr-TR"))}
              className="mono"
              style={{ width: 200 }}
            />
          </Form.Item>
          <Form.Item label="Ruhsat no" style={{ marginBottom: 0 }}>
            <Input value={ruhsat} onChange={(e) => setRuhsat(e.target.value)} style={{ width: 140 }} />
          </Form.Item>
          <Form.Item
            label="Kilometre"
            style={{ marginBottom: 0 }}
            tooltip="Km araca değil İŞE aittir; aynı araç farklı tarihlerde farklı km'dedir."
          >
            <InputNumber
              value={km}
              onChange={(v) => setKm(v ?? undefined)}
              min={0}
              style={{ width: 130 }}
            />
          </Form.Item>
        </Space>
      </Card>

      <Card
        size="small"
        title={`Cihazlar (${kalemler.length})`}
        extra={
          <Button
            size="small"
            icon={<PlusOutlined />}
            onClick={() => setKalemler((o) => [...o, bosKalem()])}
          >
            Cihaz ekle
          </Button>
        }
      >
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          {kalemler.map((k, i) => {
            const cakisma = cakismalar[k.anahtar];
            return (
              <div
                key={k.anahtar}
                style={{
                  border: "1px solid #e0dace",
                  borderRadius: 6,
                  padding: 12,
                  background: "#fbf9f5",
                }}
              >
                <Space wrap size={12} align="start" style={{ width: "100%" }}>
                  <Form.Item label={`${i + 1}. IMEI / seri no`} required style={{ marginBottom: 0 }}>
                    <Input
                      value={k.kimlik}
                      onChange={(e) => kalemDegis(k.anahtar, { kimlik: e.target.value })}
                      onBlur={() => void imeiKontrol(k)}
                      className="mono"
                      style={{ width: 190 }}
                    />
                  </Form.Item>
                  <Form.Item label="Cihaz modeli" style={{ marginBottom: 0 }}>
                    <Select
                      showSearch
                      optionFilterProp="label"
                      value={k.product_id}
                      onChange={(v) => urunSec(k.anahtar, v)}
                      style={{ width: 230 }}
                      placeholder="Seçiniz…"
                      options={(veriler.data?.urunler ?? []).map((u) => ({
                        value: u.id,
                        label: u.marka ? `${u.marka} ${u.ad}` : u.ad,
                      }))}
                    />
                  </Form.Item>
                  <Form.Item label="Rol" style={{ marginBottom: 0 }}>
                    <Select
                      value={k.device_role}
                      onChange={(v) => kalemDegis(k.anahtar, { device_role: v })}
                      style={{ width: 190 }}
                      options={ROLLER}
                    />
                  </Form.Item>
                  <Form.Item label="Eylem" style={{ marginBottom: 0 }}>
                    <Select
                      value={k.action}
                      onChange={(v) => kalemDegis(k.anahtar, { action: v })}
                      style={{ width: 150 }}
                      placeholder={tip === "SOKUM" ? "SOKULDU" : "TAKILDI"}
                      options={EYLEMLER.map((a) => ({ value: a, label: a }))}
                    />
                  </Form.Item>
                  <Form.Item label="Ödenebilirlik" style={{ marginBottom: 0 }}>
                    <Select
                      value={k.payability}
                      onChange={(v) => kalemDegis(k.anahtar, { payability: v })}
                      style={{ width: 160 }}
                      options={ODEME}
                    />
                  </Form.Item>
                  {k.payability === "ODENMEYECEK" && (
                    <Form.Item label="Neden" required style={{ marginBottom: 0 }}>
                      <Select
                        value={k.non_payable_reason}
                        onChange={(v) => kalemDegis(k.anahtar, { non_payable_reason: v })}
                        style={{ width: 200 }}
                        placeholder="Seçiniz…"
                        options={(veriler.data?.odenmeme_nedenleri ?? []).map((n) => ({
                          value: n,
                          label: n.replaceAll("_", " "),
                        }))}
                      />
                    </Form.Item>
                  )}
                  <Form.Item
                    label="Servis bedeli"
                    style={{ marginBottom: 0 }}
                    tooltip="Boş bırakılırsa tarifeden doldurulur. Tarife bağlayıcı değildir; elle girilen tutar tarifeyi geçersiz kılar."
                  >
                    <InputNumber
                      value={k.unit_price}
                      onChange={(v) => kalemDegis(k.anahtar, { unit_price: v ?? undefined })}
                      min={0}
                      addonAfter="₺"
                      style={{ width: 150 }}
                    />
                  </Form.Item>
                  {kalemler.length > 1 && (
                    <Button
                      danger
                      type="text"
                      icon={<DeleteOutlined />}
                      style={{ marginTop: 30 }}
                      onClick={() =>
                        setKalemler((o) => o.filter((x) => x.anahtar !== k.anahtar))
                      }
                    />
                  )}
                </Space>

                {cakisma && (
                  <Alert
                    style={{ marginTop: 10 }}
                    type="warning"
                    title="Bu cihaz şu an başka bir araçta görünüyor"
                    description={
                      <>
                        <strong>{cakisma.plaka ?? "(plakasız)"}</strong>
                        {cakisma.musteri ? ` · ${cakisma.musteri}` : ""} ·{" "}
                        {dayjs(cakisma.takildi).format("DD.MM.YYYY")} tarihinden beri takılı ·{" "}
                        <Tag>{cakisma.status}</Tag>
                        <br />
                        Cihaz söküldüyse sorun yok — kayıt önceki dönemi kapatır. Sökülmediyse
                        IMEI'yi kontrol edin.
                      </>
                    }
                  />
                )}
              </div>
            );
          })}
        </Space>
      </Card>

      <Card size="small" title="Yol ücreti ve not">
        <Space wrap size={16} align="start">
          <Form.Item label="Yol (km)" style={{ marginBottom: 0 }}>
            <InputNumber
              value={yolKm}
              onChange={(v) => setYolKm(v ?? undefined)}
              min={0}
              style={{ width: 120 }}
            />
          </Form.Item>
          <Form.Item
            label="Km birim"
            style={{ marginBottom: 0 }}
            tooltip="Montaj noktası seçilince tarifeden dolar."
          >
            <InputNumber
              value={yolBirim}
              onChange={(v) => setYolBirim(v ?? undefined)}
              min={0}
              addonAfter="₺"
              style={{ width: 140 }}
            />
          </Form.Item>
          <Form.Item label="Not" style={{ marginBottom: 0 }}>
            <Input
              value={not}
              onChange={(e) => setNot(e.target.value)}
              placeholder="Özel durum, ikinci ziyaret…"
              style={{ width: 380 }}
            />
          </Form.Item>
        </Space>

        <Divider style={{ margin: "14px 0" }} />
        <Space size={32} wrap>
          <Typography.Text type="secondary">
            Yol toplamı: <strong className="mono">{tl(yolToplam)}</strong>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {" "}
              ({yolKm ?? 0} km × {tl(yolBirim)})
            </Typography.Text>
          </Typography.Text>
          <Typography.Text type="secondary">
            Genel toplam:{" "}
            <strong className="mono" style={{ color: "#1f6b4d", fontSize: 16 }}>
              {tl(kalemToplam + yolToplam)}
            </strong>
          </Typography.Text>
        </Space>
      </Card>

      <Space wrap>
        <Button
          type="primary"
          size="large"
          loading={kaydet.isPending}
          disabled={eksikler.length > 0}
          onClick={gonder}
        >
          Kaydet
        </Button>
        {eksikler.length > 0 ? (
          <Typography.Text type="danger">
            {eksikler.length} zorunlu alan eksik: {eksikler.slice(0, 3).join(", ")}
            {eksikler.length > 3 ? "…" : ""}
          </Typography.Text>
        ) : (
          <Typography.Text type="secondary">
            Kayıttan sonra firma, nokta, tarih ve ücret korunur; araç alanları temizlenir.
          </Typography.Text>
        )}
      </Space>
    </Space>
  );
}
