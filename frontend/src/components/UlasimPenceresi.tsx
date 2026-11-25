/**
 * Saha ulaşımı ve araç km (KARARLAR 2026-11-20 §1).
 *
 * GÜVENLİK / HABERLEŞME saha işinde:
 * - İşleme alırken ulaşım türü seçilir; şirket aracında plaka listeden seçilir
 *   ya da elle yazılır (KARARLAR 2026-11-25). Plan aracı ve son km önerilir.
 * - Km alanları yalnız `km_zorunlu` açıkken zorunludur (varsayılan kapalı).
 * Kural sunucudadır; bu pencere yalnız gereken bilgiyi toplar.
 */
import { useQuery } from "@tanstack/react-query";
import { Alert, AutoComplete, Form, InputNumber, Modal, Segmented } from "antd";
import { useEffect, useState } from "react";

import { planlamaApi } from "../api/servisPlanlama";
import { teknikServisApi, ULASIM_TURLERI, type UlasimBilgisi } from "../api/teknikServis";

type Mod = "baslangic" | "bitis";

interface Bicim {
  ulasim_turu: string;
  plaka?: string | null;
  baslangic_km?: number | null;
  bitis_km?: number | null;
}

/** İşleme al / tamamla öncesi: ulaşım gerekiyor mu? Gerekmiyorsa null. */
export async function ulasimGerekiyor(isId: number, mod: Mod): Promise<UlasimBilgisi | null> {
  const u = await teknikServisApi.ulasim(isId);
  if (!u.zorunlu) return null;
  if (!u.ulasim_turu) return u;
  if (u.ulasim_turu !== "SIRKET_ARACI") return null;
  if (u.servis_arac_id == null && !u.plaka) return u;
  if (!u.km_zorunlu) return null;
  if (u.baslangic_km == null) return u;
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
      plaka: bilgi.plaka ?? bilgi.oneri_plaka,
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
        plaka: v.ulasim_turu === "SIRKET_ARACI" ? (v.plaka?.trim() ?? null) : null,
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
  const kmZorunlu = bilgi?.km_zorunlu ?? false;
  // Birimin araçları ve ortak havuz; listede olmayan plaka elle yazılır.
  const secenekler = (araclar.data ?? [])
    .filter((a) => !birim || !a.birim || a.birim === birim)
    .map((a) => ({ value: a.plaka, label: a.plaka }));

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
              name="plaka"
              label="Plaka"
              extra="Listeden seçin ya da plakayı yazın"
              rules={[{ required: true, whitespace: true, message: "Plakayı seçin ya da yazın" }]}
            >
              <AutoComplete
                placeholder="Örn. 34 ABC 123"
                options={secenekler}
                maxLength={20}
                showSearch={{
                  filterOption: (girdi, secenek) =>
                    String(secenek?.value ?? "")
                      .replace(/\s/g, "")
                      .toUpperCase()
                      .includes(girdi.replace(/\s/g, "").toUpperCase()),
                }}
              />
            </Form.Item>
            <Form.Item
              name="baslangic_km"
              label="Başlangıç km"
              rules={[{ required: kmZorunlu, message: "Araç km'sini girin" }]}
            >
              <InputNumber min={0} max={9999999} style={{ width: "100%" }} inputMode="numeric" />
            </Form.Item>
            {mod === "bitis" && (
              <Form.Item
                name="bitis_km"
                label="Son km"
                dependencies={["baslangic_km"]}
                rules={[
                  { required: kmZorunlu, message: "Son km'yi girin" },
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
