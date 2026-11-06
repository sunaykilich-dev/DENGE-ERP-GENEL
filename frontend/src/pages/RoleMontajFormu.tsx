/**
 * Röle montaj bilgileri — Haberleşme kurulum/montaj işi (KARARLAR 2026-10-28 §10).
 *
 * Alanlar "Repeater Montaj Bilgileri" kütüğünün sütunlarıdır; tanımlar
 * sunucudan gelir (`role_montaj.ALANLAR`). Kısmi kayıt serbesttir; zorunlu
 * alan eksikken iş KAPATILAMAZ (sunucu 409). Moda bağlı alanlar yalnız ilgili
 * modda (analog/dijital, simpleks VAR) görünür ve aranır.
 * Servis işi detayından ve teknisyenin mobil iş kartından açılır.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Col,
  DatePicker,
  Divider,
  Drawer,
  Form,
  Grid,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useEffect, useMemo, useState } from "react";

import { ApiError } from "../api/client";
import { teknikServisApi, type RoleMontajAlani, type RoleMontajDurumu } from "../api/teknikServis";
import { useAuth } from "../auth/AuthContext";

function gorunur(a: RoleMontajAlani, v: Record<string, unknown>): boolean {
  if (!a.kosul) return true;
  if (!a.kosul.degerler.includes(String(v[a.kosul.alan] ?? ""))) return false;
  return !a.kosul.mod || a.kosul.mod.includes(String(v.calisma_modu ?? ""));
}

function formaCevir(alanlar: RoleMontajAlani[], degerler: RoleMontajDurumu["degerler"]) {
  const sonuc: Record<string, unknown> = {};
  for (const a of alanlar) {
    const d = degerler[a.kod];
    if (d == null || d === "" || (Array.isArray(d) && !d.length)) continue;
    sonuc[a.kod] = a.tip === "tarih" ? dayjs(String(d)) : d;
  }
  return sonuc;
}

export default function RoleMontajFormu({
  soId,
  kapali,
  onKapat,
}: {
  soId: number | null;
  /** Kapanmış/iptal iş: yalnız görüntülenir. */
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
    queryKey: ["role-montaj", soId],
    queryFn: () => teknikServisApi.roleMontaj(soId!),
    enabled: soId != null,
  });
  const veri = sorgu.data;
  const yazabilir = yetkili("servis.yaz") && !kapali;
  const izlenen = Form.useWatch([], form) as Record<string, unknown> | undefined;
  const degerler = izlenen ?? {};

  useEffect(() => {
    if (!veri) return;
    form.resetFields();
    form.setFieldsValue(formaCevir(veri.alanlar, veri.degerler));
  }, [veri, form]);

  const gruplar = useMemo(() => {
    const g = new Map<string, RoleMontajAlani[]>();
    for (const a of veri?.alanlar ?? []) g.set(a.grup, [...(g.get(a.grup) ?? []), a]);
    return [...g.entries()];
  }, [veri]);

  const toplam = ["el_telsizi", "arac_telsizi", "sabit_telsiz"].every((k) => typeof degerler[k] === "number")
    ? ["el_telsizi", "arac_telsizi", "sabit_telsiz"].reduce((t, k) => t + (degerler[k] as number), 0)
    : null;

  async function kaydet() {
    if (!veri || soId == null) return;
    const v = form.getFieldsValue(true) as Record<string, unknown>;
    const gonder: Record<string, unknown> = {};
    for (const a of veri.alanlar) {
      if (!gorunur(a, v)) continue; // gizli (moda uymayan) alan saklanmaz
      const d = v[a.kod];
      if (d == null || d === "" || (Array.isArray(d) && !d.length)) continue;
      gonder[a.kod] = a.tip === "tarih" && dayjs.isDayjs(d) ? d.format("YYYY-MM-DD") : d;
    }
    setKaydediliyor(true);
    try {
      const yeni = await teknikServisApi.roleMontajKaydet(soId, gonder, veri.version);
      qc.setQueryData(["role-montaj", soId], yeni);
      void qc.invalidateQueries({ queryKey: ["servis-is", soId] });
      void qc.invalidateQueries({ queryKey: ["mobil-kart", soId] });
      if (yeni.eksikler.length) message.warning(`Kaydedildi; ${yeni.eksikler.length} zorunlu alan eksik`);
      else message.success("Kaydedildi; montaj bilgileri tamam");
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) void sorgu.refetch();
      message.error((e as Error).message);
    } finally {
      setKaydediliyor(false);
    }
  }

  function alanGirdisi(a: RoleMontajAlani) {
    const kapali_ = !yazabilir;
    switch (a.tip) {
      case "sayi":
        return <InputNumber min={0} max={100000} precision={0} style={{ width: "100%" }} disabled={kapali_} />;
      case "tarih":
        return <DatePicker format="DD.MM.YYYY" style={{ width: "100%" }} disabled={kapali_} />;
      case "secim":
        return (
          <Select
            allowClear
            disabled={kapali_}
            options={(a.secenekler ?? []).map((s) => ({ value: s, label: s }))}
          />
        );
      case "personel":
        return (
          <Select
            mode="multiple"
            allowClear
            disabled={kapali_}
            placeholder="Teknisyen seçin (birden çok)"
            optionFilterProp="label"
            options={(veri?.personel_secenekleri ?? []).map((s) => ({ value: s, label: s }))}
          />
        );
      case "frekans":
        return <Input placeholder="örn. 427.1125" maxLength={12} disabled={kapali_} />;
      default:
        return <Input maxLength={500} placeholder={a.ipucu ?? undefined} disabled={kapali_} />;
    }
  }

  const eksikler = veri?.eksikler ?? [];
  return (
    <Drawer
      open={soId != null}
      onClose={onKapat}
      width={ekran.md ? 720 : "100%"}
      title="Röle montaj bilgileri"
      extra={
        yazabilir && (
          <Button type="primary" loading={kaydediliyor} onClick={() => void kaydet()}>
            Kaydet
          </Button>
        )
      }
    >
      {sorgu.isLoading || !veri ? (
        <Spin />
      ) : (
        <Space orientation="vertical" style={{ width: "100%" }}>
          {!veri.uygulanir ? (
            <Alert
              type="info"
              showIcon
              title="Bu iş kurulum/montaj işi değil; bilgiler isteğe bağlıdır."
            />
          ) : eksikler.length ? (
            <Alert
              type="warning"
              showIcon
              title={`İş kapatılmadan önce ${eksikler.length} zorunlu alan doldurulmalı`}
              description={veri.kayitli ? eksikler.join(", ") : "Henüz kayıt yok."}
            />
          ) : (
            <Alert type="success" showIcon title="Zorunlu montaj bilgileri tamam" />
          )}
          {!veri.kayitli && (
            <Typography.Text type="secondary">
              Firma, proje, adres ve montajı yapan personel işten önerildi; kontrol edip kaydedin.
            </Typography.Text>
          )}
          <Form form={form} layout="vertical" requiredMark>
            {gruplar.map(([grup, alanlar]) => {
              const gorunenler = alanlar.filter((a) => gorunur(a, degerler));
              if (!gorunenler.length) return null;
              return (
                <div key={grup}>
                  <Divider style={{ margin: "8px 0" }} />
                  <Typography.Title level={5} style={{ marginTop: 0 }}>
                    {grup}
                  </Typography.Title>
                  <Row gutter={12}>
                    {gorunenler.map((a) => (
                      <Col xs={24} sm={12} key={a.kod}>
                        <Form.Item
                          name={a.kod}
                          label={a.ad}
                          required={a.zorunlu && veri.uygulanir}
                          extra={a.tip !== "metin" ? a.ipucu ?? undefined : undefined}
                        >
                          {alanGirdisi(a)}
                        </Form.Item>
                      </Col>
                    ))}
                    {grup === "Telsizler" && (
                      <Col xs={24} sm={12}>
                        <Form.Item label="Kullanılan toplam telsiz sayısı">
                          <Tag>{toplam ?? "—"}</Tag>
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            El + araç + sabit (otomatik)
                          </Typography.Text>
                        </Form.Item>
                      </Col>
                    )}
                  </Row>
                </div>
              );
            })}
          </Form>
        </Space>
      )}
    </Drawer>
  );
}
