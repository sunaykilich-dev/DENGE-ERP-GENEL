/**
 * Arıza işinin kütükten gelen cihaz bilgisi (KARARLAR 2026-10-28 §12).
 *
 * - Haberleşme arızası: kayıtlı frekans kütükten (ya da o serinin son röle
 *   montaj kaydından) otomatik gelir; yoksa teknisyen girer.
 * - Güvenlik arızası: X-ray / kapı dedektörü seri numarası kütükten gelir;
 *   yoksa teknisyen girer.
 * Eksikken iş KAPATILAMAZ (sunucu 409). Kısmi kayıt serbesttir.
 * Servis işi detayından ve teknisyenin mobil iş kartından açılır.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Col,
  Descriptions,
  Drawer,
  Form,
  Grid,
  Input,
  Row,
  Select,
  Space,
  Spin,
  Tag,
} from "antd";
import { useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { teknikServisApi, type RoleMontajAlani } from "../api/teknikServis";
import { useAuth } from "../auth/AuthContext";

const KAYNAK_ETIKETI: Record<string, { renk: string; ad: string }> = {
  KUTUK: { renk: "green", ad: "Kütükten otomatik geldi" },
  ROLE_MONTAJ: { renk: "green", ad: "Son röle montaj kaydından geldi" },
  TEKNISYEN: { renk: "blue", ad: "Sahada girildi" },
};

function gorunur(a: RoleMontajAlani, v: Record<string, unknown>): boolean {
  if (!a.kosul) return true;
  if (!a.kosul.degerler.includes(String(v[a.kosul.alan] ?? ""))) return false;
  return !a.kosul.mod || a.kosul.mod.includes(String(v.calisma_modu ?? ""));
}

export default function CihazBilgisiFormu({
  soId,
  kapali,
  onKapat,
}: {
  soId: number | null;
  kapali?: boolean;
  onKapat: () => void;
}) {
  const { message } = App.useApp();
  const { yetkili } = useAuth();
  const qc = useQueryClient();
  const ekran = Grid.useBreakpoint();
  const [form] = Form.useForm();
  const [kaydediliyor, setKaydediliyor] = useState(false);
  const sorgu = useQuery({
    queryKey: ["cihaz-bilgisi", soId],
    queryFn: () => teknikServisApi.cihazBilgisi(soId!),
    enabled: soId != null,
  });
  const veri = sorgu.data;
  const yazabilir = yetkili("servis.yaz") && !kapali;
  const degerler = (Form.useWatch([], form) as Record<string, unknown> | undefined) ?? {};

  useEffect(() => {
    if (!veri) return;
    form.resetFields();
    form.setFieldsValue({ seri_no: veri.seri_no ?? undefined, ...veri.frekans });
  }, [veri, form]);

  async function kaydet() {
    if (!veri || soId == null) return;
    const v = form.getFieldsValue(true) as Record<string, unknown>;
    const frekans: Record<string, unknown> = {};
    for (const a of veri.alanlar) {
      if (!gorunur(a, v)) continue;
      const d = v[a.kod];
      if (d != null && String(d).trim() !== "") frekans[a.kod] = d;
    }
    setKaydediliyor(true);
    try {
      const yeni = await teknikServisApi.cihazBilgisiKaydet(soId, {
        seri_no: (v.seri_no as string | undefined)?.trim() || null,
        frekans: veri.kural === "FREKANS" ? frekans : null,
        version: veri.version,
      });
      qc.setQueryData(["cihaz-bilgisi", soId], yeni);
      void qc.invalidateQueries({ queryKey: ["servis-is", soId] });
      void qc.invalidateQueries({ queryKey: ["mobil-kart", soId] });
      if (yeni.eksikler.length) message.warning(`Kaydedildi; eksik: ${yeni.eksikler.join(", ")}`);
      else message.success("Kaydedildi; cihaz bilgisi tamam");
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) void sorgu.refetch();
      message.error((e as Error).message);
    } finally {
      setKaydediliyor(false);
    }
  }

  const frekansli = veri?.kural === "FREKANS";
  const seriVar = !!veri?.seri_no;
  return (
    <Drawer
      open={soId != null}
      onClose={onKapat}
      width={ekran.md ? 640 : "100%"}
      title={frekansli ? "Cihaz ve kayıtlı frekans" : "Cihaz seri numarası"}
      extra={
        yazabilir &&
        veri?.kural && (
          <Button type="primary" loading={kaydediliyor} onClick={() => void kaydet()}>
            Kaydet
          </Button>
        )
      }
    >
      {sorgu.isLoading || !veri ? (
        <Spin />
      ) : !veri.kural ? (
        <Alert type="info" showIcon title="Bu işte kütük cihaz bilgisi istenmez." />
      ) : (
        <Space orientation="vertical" style={{ width: "100%" }}>
          {veri.eksikler.length ? (
            <Alert
              type="warning"
              showIcon
              title="Kütükte bulunamadı — iş kapatılmadan teknisyen girmeli"
              description={`Eksik: ${veri.eksikler.join(", ")}`}
            />
          ) : (
            <Alert type="success" showIcon title="Cihaz bilgisi tamam" />
          )}
          {veri.kaynak && KAYNAK_ETIKETI[veri.kaynak] && (
            <Tag color={KAYNAK_ETIKETI[veri.kaynak].renk}>{KAYNAK_ETIKETI[veri.kaynak].ad}</Tag>
          )}
          {veri.ekipman && (
            <Descriptions size="small" column={1} bordered title="Kütükteki cihaz">
              <Descriptions.Item label="Cihaz">
                {[veri.ekipman.brand, veri.ekipman.model].filter(Boolean).join(" ") || veri.ekipman.equipment_type}
              </Descriptions.Item>
              <Descriptions.Item label="Seri no">{veri.ekipman.serial_no ?? "—"}</Descriptions.Item>
            </Descriptions>
          )}
          <Form form={form} layout="vertical" requiredMark>
            {(!frekansli || !seriVar) && (
              <Form.Item
                name="seri_no"
                label="Cihaz seri numarası"
                required={!frekansli}
                extra={frekansli ? "İşte seri yoksa girin; kütükte varsa frekans oradan gelir." : undefined}
              >
                <Input maxLength={200} disabled={!yazabilir} />
              </Form.Item>
            )}
            {frekansli && (
              <Row gutter={12}>
                {veri.alanlar
                  .filter((a) => gorunur(a, degerler))
                  .map((a) => (
                    <Col xs={24} sm={12} key={a.kod}>
                      <Form.Item
                        name={a.kod}
                        label={a.ad}
                        required={["role_tx", "role_rx"].includes(a.kod)}
                      >
                        {a.tip === "secim" ? (
                          <Select
                            allowClear
                            disabled={!yazabilir}
                            options={(a.secenekler ?? []).map((s) => ({ value: s, label: s }))}
                          />
                        ) : (
                          <Input
                            maxLength={a.tip === "frekans" ? 12 : 100}
                            placeholder={a.tip === "frekans" ? "örn. 427.1125" : undefined}
                            disabled={!yazabilir}
                          />
                        )}
                      </Form.Item>
                    </Col>
                  ))}
              </Row>
            )}
          </Form>
        </Space>
      )}
    </Drawer>
  );
}
