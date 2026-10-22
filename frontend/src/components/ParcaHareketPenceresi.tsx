/**
 * Yedek parça hareket penceresi — giriş, zayi, transfer, servis işine çıkış ve
 * iade için TEK form (TS-133, TS-136, TS-137).
 *
 * - Satırlar toplu girilir; sunucu tek transaction'da yazar: bir satır
 *   hatalıysa (stok yetersiz, kapalı iş, iade > net çıkış) HİÇBİRİ yazılmaz
 *   ve 409 mesajı aynen gösterilir.
 * - Adet tam sayıdır (birim METRE olsa da; ondalık sunucuda 422).
 * - Not ≤ 300, belge no ≤ 50 karakter (canlı `stock_movements` kolonları).
 * - Teknisyende kendi araç deposu varsayılan seçilir (`kendi_araci`).
 * - Bakiye/stok hesabı yapılmaz; parça seçicide gösterilen toplam sunucudan.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Form, Input, InputNumber, Modal, Select, Space } from "antd";
import { useEffect, useMemo, useState } from "react";

import { type Depo, parcaApi, parcaHatasi, type SatirGirdisi } from "../api/yedekParca";

export type ParcaHareketTuru = "GIRIS" | "ZAYI" | "TRANSFER" | "CIKIS" | "IADE";

const BASLIKLAR: Record<ParcaHareketTuru, string> = {
  GIRIS: "Servis deposuna parça girişi",
  ZAYI: "Zayi (hasarlı / kayıp parça)",
  TRANSFER: "Depolar arası transfer",
  CIKIS: "Servis işine parça çıkışı",
  IADE: "Servis işinden depoya iade",
};

/** Arama yapılabilen yedek parça seçicisi (kod, ad, marka, model). */
export function ParcaSecici({
  value,
  onChange,
  secenekler,
}: {
  value?: number;
  onChange?: (v: number) => void;
  /** Verilirse sunucu araması yerine bu liste kullanılır (ör. iadede yalnız net > 0). */
  secenekler?: { value: number; label: string }[];
}) {
  const [q, setQ] = useState("");
  const sorgu = useQuery({
    queryKey: ["parca", "secici", q],
    queryFn: () => parcaApi.parcalar(q || undefined),
    enabled: !secenekler,
    staleTime: 30_000,
  });
  const opsiyonlar =
    secenekler ??
    (sorgu.data ?? []).map((p) => ({
      value: p.id,
      label: `${p.code} — ${p.name} (stok: ${p.toplam} ${p.birim})`,
    }));
  return (
    <Select
      showSearch
      value={value}
      onChange={onChange}
      placeholder="Kod, ad veya marka ile arayın"
      filterOption={
        secenekler
          ? (girdi, o) =>
              String(o?.label ?? "")
                .toLocaleLowerCase("tr")
                .includes(girdi.toLocaleLowerCase("tr"))
          : false
      }
      onSearch={secenekler ? undefined : (v) => setQ(v.trim())}
      loading={sorgu.isFetching}
      options={opsiyonlar}
      style={{ width: "100%", minWidth: 0 }}
      notFoundContent={sorgu.isFetching ? "Aranıyor…" : "Parça bulunamadı"}
    />
  );
}

export interface ParcaHareketPenceresiProps {
  tur: ParcaHareketTuru | null;
  onKapat: () => void;
  /** Çıkış / iade için servis işi. */
  soId?: number;
  soNo?: string;
  /** İadede seçilebilecek parçalar (net çıkışı olanlar). */
  parcaSecenekleri?: { value: number; label: string }[];
  /** Kaydedildikten sonra (sorgu tazeleme sonrası). */
  onTamam?: () => void;
}

interface FormDegeri {
  depo_id?: number;
  hedef_depo_id?: number;
  document_no?: string;
  notes?: string;
  gerekce?: string;
  satirlar: SatirGirdisi[];
}

export default function ParcaHareketPenceresi({
  tur,
  onKapat,
  soId,
  soNo,
  parcaSecenekleri,
  onTamam,
}: ParcaHareketPenceresiProps) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [form] = Form.useForm<FormDegeri>();
  const [hata, setHata] = useState<string | null>(null);

  const depolar = useQuery({
    queryKey: ["parca", "depolar"],
    queryFn: () => parcaApi.depolar(),
    enabled: tur !== null,
  });
  const depoSecenekleri = useMemo(
    () =>
      (depolar.data ?? []).map((d: Depo) => ({
        value: d.id,
        label: `${d.code} — ${d.name}${d.kendi_araci ? " (aracım)" : ""}`,
      })),
    [depolar.data],
  );

  useEffect(() => {
    if (tur === null) return;
    setHata(null);
    form.resetFields();
    const arac = depolar.data?.find((d) => d.kendi_araci);
    const tek = depolar.data?.length === 1 ? depolar.data[0] : undefined;
    const varsayilan = (tur === "CIKIS" || tur === "IADE" ? arac : undefined) ?? tek;
    form.setFieldsValue({ depo_id: varsayilan?.id, satirlar: [{ adet: 1 } as SatirGirdisi] });
  }, [tur, depolar.data, form]);

  const kaydet = useMutation({
    mutationFn: async (d: FormDegeri) => {
      const satirlar = d.satirlar.map((s) => ({
        product_id: s.product_id,
        adet: s.adet,
        ...(tur === "GIRIS" && s.unit_cost != null ? { unit_cost: s.unit_cost } : {}),
      }));
      switch (tur) {
        case "GIRIS":
          return parcaApi.giris({
            depo_id: d.depo_id!,
            document_no: d.document_no?.trim() || null,
            notes: d.notes?.trim() || null,
            satirlar,
          });
        case "ZAYI":
          return parcaApi.zayi({ depo_id: d.depo_id!, gerekce: d.gerekce!.trim(), satirlar });
        case "TRANSFER":
          return parcaApi.transfer({
            kaynak_depo_id: d.depo_id!,
            hedef_depo_id: d.hedef_depo_id!,
            notes: d.notes?.trim() || null,
            satirlar,
          });
        case "CIKIS":
          return parcaApi.cikis({ service_order_id: soId!, depo_id: d.depo_id!, notes: d.notes?.trim() || null, satirlar });
        case "IADE":
          return parcaApi.iade({ service_order_id: soId!, depo_id: d.depo_id!, notes: d.notes?.trim() || null, satirlar });
        default:
          throw new Error("Bilinmeyen hareket türü");
      }
    },
    onSuccess: async () => {
      message.success("Hareket kaydedildi");
      await qc.invalidateQueries({ queryKey: ["parca"] });
      onTamam?.();
      onKapat();
    },
    onError: (e) => setHata(parcaHatasi(e).mesaj),
  });

  if (tur === null) return null;
  const isHareketi = tur === "CIKIS" || tur === "IADE";

  return (
    <Modal
      open
      title={BASLIKLAR[tur] + (isHareketi && soNo ? ` — ${soNo}` : "")}
      onCancel={onKapat}
      onOk={() => form.submit()}
      okText="Kaydet"
      cancelText="Vazgeç"
      confirmLoading={kaydet.isPending}
      destroyOnHidden
      width={720}
    >
      {hata && <Alert type="error" showIcon message={hata} style={{ marginBottom: 12 }} />}
      <Form<FormDegeri> form={form} layout="vertical" onFinish={(d) => kaydet.mutate(d)}>
        <Form.Item
          name="depo_id"
          label={tur === "TRANSFER" ? "Kaynak depo" : "Depo"}
          rules={[{ required: true, message: "Depo seçin" }]}
        >
          <Select options={depoSecenekleri} loading={depolar.isLoading} placeholder="Depo seçin" />
        </Form.Item>
        {tur === "TRANSFER" && (
          <Form.Item
            name="hedef_depo_id"
            label="Hedef depo"
            dependencies={["depo_id"]}
            rules={[
              { required: true, message: "Hedef depo seçin" },
              ({ getFieldValue }) => ({
                validator: (_, v) =>
                  v && v === getFieldValue("depo_id")
                    ? Promise.reject(new Error("Kaynak ve hedef depo aynı olamaz"))
                    : Promise.resolve(),
              }),
            ]}
          >
            <Select options={depoSecenekleri} placeholder="Hedef depo" />
          </Form.Item>
        )}
        {tur === "GIRIS" && (
          <Form.Item name="document_no" label="Belge no (irsaliye / fatura)" rules={[{ max: 50 }]}>
            <Input maxLength={50} />
          </Form.Item>
        )}
        <Form.List name="satirlar">
          {(alanlar, { add, remove }) => (
            <>
              {alanlar.map((alan) => (
                <Space key={alan.key} align="start" wrap style={{ display: "flex", width: "100%" }}>
                  <Form.Item
                    name={[alan.name, "product_id"]}
                    rules={[{ required: true, message: "Parça seçin" }]}
                    style={{ minWidth: 260, flex: 1 }}
                  >
                    <ParcaSecici secenekler={tur === "IADE" ? parcaSecenekleri : undefined} />
                  </Form.Item>
                  <Form.Item name={[alan.name, "adet"]} rules={[{ required: true, message: "Adet" }]}>
                    <InputNumber min={1} max={1_000_000} precision={0} placeholder="Adet" />
                  </Form.Item>
                  {tur === "GIRIS" && (
                    <Form.Item name={[alan.name, "unit_cost"]}>
                      <InputNumber min={0} precision={4} placeholder="Birim maliyet" style={{ width: 140 }} />
                    </Form.Item>
                  )}
                  {alanlar.length > 1 && (
                    <Button type="link" danger onClick={() => remove(alan.name)}>
                      Sil
                    </Button>
                  )}
                </Space>
              ))}
              {alanlar.length < 50 && (
                <Button type="dashed" block onClick={() => add({ adet: 1 })} style={{ marginBottom: 12 }}>
                  Satır ekle
                </Button>
              )}
            </>
          )}
        </Form.List>
        {tur === "ZAYI" ? (
          <Form.Item
            name="gerekce"
            label="Gerekçe"
            rules={[
              { required: true, message: "Gerekçe zorunlu" },
              { min: 3, message: "En az 3 karakter" },
              { max: 300 },
            ]}
          >
            <Input.TextArea rows={2} maxLength={300} showCount />
          </Form.Item>
        ) : (
          <Form.Item name="notes" label="Not" rules={[{ max: 300 }]}>
            <Input.TextArea rows={2} maxLength={300} showCount />
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
}
