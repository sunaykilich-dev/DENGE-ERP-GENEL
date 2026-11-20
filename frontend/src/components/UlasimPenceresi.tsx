/**
 * Saha ulaşımı ve araç km (KARARLAR 2026-11-20 §1).
 *
 * GÜVENLİK / HABERLEŞME saha işinde:
 * - İşleme alırken ulaşım türü seçilir; şirket aracında plaka listeden seçilir
 *   (elle yazılmaz) ve başlangıç km girilir. Plan aracı ve aracın son km'si önerilir.
 * - Tamamlarken şirket aracında son km girilir.
 * Kural sunucudadır; bu pencere yalnız gereken bilgiyi toplar.
 */
import { useQuery } from "@tanstack/react-query";
import { Alert, Form, InputNumber, Modal, Segmented, Select } from "antd";
import { useEffect, useState } from "react";

import { planlamaApi } from "../api/servisPlanlama";
import { teknikServisApi, ULASIM_TURLERI, type UlasimBilgisi } from "../api/teknikServis";

type Mod = "baslangic" | "bitis";

interface Bicim {
  ulasim_turu: string;
  servis_arac_id?: number | null;
  baslangic_km?: number | null;
  bitis_km?: number | null;
}

/** İşleme al / tamamla öncesi: ulaşım gerekiyor mu? Gerekmiyorsa null. */
export async function ulasimGerekiyor(isId: number, mod: Mod): Promise<UlasimBilgisi | null> {
  const u = await teknikServisApi.ulasim(isId);
  if (!u.zorunlu) return null;
  if (!u.ulasim_turu) return u;
  if (u.ulasim_turu !== "SIRKET_ARACI") return null;
  if (u.servis_arac_id == null || u.baslangic_km == null) return u;
  if (mod === "bitis" && u.bitis_km == null) return u;
  return null;
}

export default function UlasimPenceresi({
  isId,
  birim,
  bilgi,
  mod,
  onKapat,
  onTamam,
}: {
  isId: number;
  birim?: string | null;
  /** `ulasimGerekiyor` sonucu; null iken pencere kapalı. */
  bilgi: UlasimBilgisi | null;
  mod: Mod;
  onKapat: () => void;
  onTamam: () => void;
}) {
  const [form] = Form.useForm<Bicim>();
  const [hata, setHata] = useState<string | null>(null);
  const [kayitta, setKayitta] = useState(false);
  const tur = Form.useWatch("ulasim_turu", form);
  const araclar = useQuery({
    queryKey: ["servis-araclari", birim ?? null],
    queryFn: () => planlamaApi.araclar(undefined, true),
    enabled: bilgi != null,
  });

  useEffect(() => {
    if (!bilgi) return;
    setHata(null);
    form.setFieldsValue({
      ulasim_turu: bilgi.ulasim_turu ?? "SIRKET_ARACI",
      servis_arac_id: bilgi.servis_arac_id ?? bilgi.oneri_arac_id,
      baslangic_km: bilgi.baslangic_km ?? bilgi.oneri_baslangic_km,
      bitis_km: bilgi.bitis_km,
    });
  }, [bilgi, form]);

  const kaydet = async () => {
    const v = await form.validateFields();
    setKayitta(true);
    setHata(null);
    try {
      await teknikServisApi.ulasimYaz(isId, {
        ulasim_turu: v.ulasim_turu,
        servis_arac_id: v.ulasim_turu === "SIRKET_ARACI" ? (v.servis_arac_id ?? null) : null,
        baslangic_km: v.ulasim_turu === "SIRKET_ARACI" ? (v.baslangic_km ?? null) : null,
        bitis_km: v.ulasim_turu === "SIRKET_ARACI" && mod === "bitis" ? (v.bitis_km ?? null) : null,
      });
      onTamam();
    } catch (e) {
      setHata((e as Error).message);
    } finally {
      setKayitta(false);
    }
  };

  const arac = tur === "SIRKET_ARACI";
  // Birimin araçları önce, ortak havuz sonra.
  const secenekler = (araclar.data ?? [])
    .filter((a) => !birim || !a.birim || a.birim === birim)
    .map((a) => ({ value: a.id, label: a.plaka }));

  return (
    <Modal
      open={bilgi != null}
      title={mod === "baslangic" ? "Ulaşım bilgisi" : "Aracın son km'si"}
      okText={mod === "baslangic" ? "Kaydet ve işleme al" : "Kaydet"}
      cancelText="Vazgeç"
      confirmLoading={kayitta}
      onOk={() => void kaydet()}
      onCancel={onKapat}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" requiredMark="optional">
        <Form.Item name="ulasim_turu" label="Nasıl gidildi?" rules={[{ required: true }]}>
          <Segmented block options={ULASIM_TURLERI.map((t) => ({ value: t.value, label: t.label }))} />
        </Form.Item>
        {arac && (
          <>
            <Form.Item
              name="servis_arac_id"
              label="Plaka"
              rules={[{ required: true, message: "Plaka seçin" }]}
            >
              <Select
                showSearch={{ optionFilterProp: "label" }}
                placeholder="Araç seçin"
                loading={araclar.isLoading}
                options={secenekler}
              />
            </Form.Item>
            <Form.Item
              name="baslangic_km"
              label="Başlangıç km"
              rules={[{ required: true, message: "Araç km'sini girin" }]}
            >
              <InputNumber min={0} max={9999999} style={{ width: "100%" }} inputMode="numeric" />
            </Form.Item>
            {mod === "bitis" && (
              <Form.Item
                name="bitis_km"
                label="Son km"
                dependencies={["baslangic_km"]}
                rules={[
                  { required: true, message: "Son km'yi girin" },
                  ({ getFieldValue }) => ({
                    validator: (_, deger?: number | null) =>
                      deger == null || deger >= (getFieldValue("baslangic_km") ?? 0)
                        ? Promise.resolve()
                        : Promise.reject(new Error("Son km başlangıç km'den küçük olamaz")),
                  }),
                ]}
              >
                <InputNumber min={0} max={9999999} style={{ width: "100%" }} inputMode="numeric" />
              </Form.Item>
            )}
          </>
        )}
        {hata && <Alert type="error" showIcon title={hata} />}
      </Form>
    </Modal>
  );
}
