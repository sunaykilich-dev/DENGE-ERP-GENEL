/**
 * Ekipman kütüğü toplu işlemleri (E03-11 / TS-053 T2): "Servis işi aç" ve
 * "Sözleşmeye bağla".
 *
 * - Servis işi aç (`servis.yaz` | `servis.kurulum_ac`, + `ekipman.gor`; yalnız
 *   `servis.kurulum_ac` olan satış destek yalnız KURULUM seçer — KARARLAR
 *   2026-11-04 §6.5): seçili her ekipman için bir
 *   iş; birim, müşteri, lokasyon, seri ve kayıtlı irtibat ekipmandan gelir.
 *   Sunucu tek transaction'da açar; açık işte aynı seri varsa 409 `MUKERRER`
 *   döner ve kullanıcı listeyi görüp "yine de aç" der.
 * - Sözleşmeye bağla (`bakim.yaz`): seçilenler TEK müşteriye ait olmalı;
 *   o müşterinin aktif sözleşmesi seçilir, her ekipman aynı türdeki boş
 *   kaleme bağlanır (sözleşmenin eşleştirme ucu — şef onayı kuralı aynen).
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, App, Button, Form, Input, Modal, Select, Space, Typography } from "antd";
import { useState } from "react";

import { bakimApi } from "../api/bakim";
import { ApiError } from "../api/client";
import type { EkipmanSatiri } from "../api/servisEkipman";
import { teknikServisApi } from "../api/teknikServis";
import { useAuth } from "../auth/AuthContext";

interface IsFormu {
  tur: string;
  konu: string;
  talep_kanali: string;
  oncelik: string;
  iletisim_ad?: string;
  iletisim_telefon?: string;
  aciklama?: string;
}

export default function EkipmanTopluIslemleri({
  secili,
  onBitti,
}: {
  secili: EkipmanSatiri[];
  onBitti: () => void;
}) {
  const { yetkili } = useAuth();
  const { message, modal } = App.useApp();
  const [isAcik, setIsAcik] = useState(false);
  const [bagAcik, setBagAcik] = useState(false);
  const [sozlesmeId, setSozlesmeId] = useState<number | null>(null);
  const [form] = Form.useForm<IsFormu>();

  const yalnizKurulum = !yetkili("servis.yaz") && yetkili("servis.kurulum_ac");
  const isAcabilir = yetkili("ekipman.gor") && (yetkili("servis.yaz") || yalnizKurulum);
  const baglayabilir = yetkili("bakim.yaz");
  const musteriler = [...new Set(secili.map((e) => e.account_id))];
  const tekMusteri = musteriler.length === 1 && musteriler[0] != null ? musteriler[0] : null;

  const formVerileri = useQuery({
    queryKey: ["servis-form-verileri"],
    queryFn: teknikServisApi.formVerileri,
    enabled: isAcik,
  });
  const sozlesmeler = useQuery({
    queryKey: ["bakim", "sozlesmeler", "ekipman-bagla", tekMusteri],
    queryFn: () => bakimApi.sozlesmeler({ musteri_id: tekMusteri, durum: "AKTIF", limit: 100 }),
    enabled: bagAcik && tekMusteri != null,
  });

  const isAc = useMutation({
    mutationFn: (g: { v: IsFormu; gec: boolean }) =>
      teknikServisApi.ekipmandanAc({
        ekipman_idler: secili.map((e) => e.id),
        ...g.v,
        mukerrer_gec: g.gec,
      }),
    onSuccess: (r) => {
      message.success(`${r.acilan} servis işi açıldı: ${r.isler.map((x) => x.so_no).join(", ")}`);
      setIsAcik(false);
      form.resetFields();
      onBitti();
    },
    onError: (e, g) => {
      const detay = (e instanceof ApiError ? (e.govde as { detail?: unknown })?.detail : null) as
        | { kod?: string; mesaj?: string }
        | null;
      if (e instanceof ApiError && e.status === 409 && detay?.kod === "MUKERRER" && !g.gec) {
        modal.confirm({
          title: "Mükerrer kayıt olabilir",
          content: detay.mesaj,
          okText: "Yine de aç",
          cancelText: "Vazgeç",
          onOk: () => isAc.mutate({ v: g.v, gec: true }),
        });
        return;
      }
      message.error((e as Error).message);
    },
  });

  const bagla = useMutation({
    mutationFn: async (id: number) => {
      const mevcut = await bakimApi.eslestirme(id);
      const kullanilan = new Set<number>();
      const eslesmeler: { kalem_id: number; equipment_id: number }[] = [];
      const eslesmeyen: string[] = [];
      const zatenBagli = new Set(mevcut.kalemler.map((k) => k.equipment_id).filter(Boolean));
      for (const e of secili) {
        if (zatenBagli.has(e.id)) continue;
        const kalem = mevcut.kalemler.find(
          (k) =>
            k.equipment_type === e.equipment_type &&
            k.equipment_id == null &&
            !kullanilan.has(k.kalem_id),
        );
        if (!kalem) {
          eslesmeyen.push(e.serial_no ?? `#${e.id}`);
          continue;
        }
        kullanilan.add(kalem.kalem_id);
        eslesmeler.push({ kalem_id: kalem.kalem_id, equipment_id: e.id });
      }
      if (eslesmeler.length) await bakimApi.eslestir(id, eslesmeler);
      return { bagli: eslesmeler.length, eslesmeyen };
    },
    onSuccess: (r) => {
      if (r.bagli) message.success(`${r.bagli} ekipman sözleşmeye bağlandı`);
      if (r.eslesmeyen.length)
        message.warning(`Uygun boş kalem yok: ${r.eslesmeyen.join(", ")} (sözleşme kapsamını artırın)`);
      setBagAcik(false);
      setSozlesmeId(null);
      onBitti();
    },
    onError: (e: Error) => message.error(e.message),
  });

  if (!secili.length || (!isAcabilir && !baglayabilir)) return null;

  return (
    <>
      {isAcabilir && (
        <Button size="small" onClick={() => setIsAcik(true)}>
          Servis işi aç
        </Button>
      )}
      {baglayabilir && (
        <Button size="small" onClick={() => setBagAcik(true)}>
          Sözleşmeye bağla
        </Button>
      )}

      <Modal
        title={`Servis işi aç (${secili.length} ekipman)`}
        open={isAcik}
        onCancel={() => setIsAcik(false)}
        onOk={() => form.submit()}
        confirmLoading={isAc.isPending}
        okText="Aç"
        cancelText="Vazgeç"
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary">
          Her ekipman için ayrı iş açılır; birim, müşteri, lokasyon, seri ve kayıtlı irtibat
          ekipmandan alınır.
        </Typography.Paragraph>
        <Form
          form={form}
          layout="vertical"
          initialValues={{ tur: yalnizKurulum ? "KURULUM" : "ARIZA", talep_kanali: "TELEFON", oncelik: "NORMAL" }}
          onFinish={(v) => isAc.mutate({ v, gec: false })}
        >
          <Form.Item name="tur" label="İş türü" rules={[{ required: true }]}>
            <Select
              disabled={yalnizKurulum}
              options={(formVerileri.data?.turler ?? [])
                .filter((t) => t.ekrandan && (!yalnizKurulum || t.kod === "KURULUM"))
                .map((t) => ({ value: t.kod, label: t.ad }))}
            />
          </Form.Item>
          <Form.Item name="konu" label="Konu" rules={[{ required: true, whitespace: true, max: 200 }]}>
            <Input />
          </Form.Item>
          <Space wrap>
            <Form.Item name="talep_kanali" label="Talep kanalı" rules={[{ required: true }]}>
              <Select
                style={{ minWidth: 160 }}
                options={(formVerileri.data?.talep_kanallari ?? [])
                  .filter((k) => k.kod !== "BAKIM_OTOMATIK")
                  .map((k) => ({ value: k.kod, label: k.ad }))}
              />
            </Form.Item>
            <Form.Item name="oncelik" label="Öncelik">
              <Select
                style={{ minWidth: 120 }}
                options={(formVerileri.data?.oncelikler ?? ["KRITIK", "YUKSEK", "NORMAL"]).map((o) => ({
                  value: o,
                  label: o,
                }))}
              />
            </Form.Item>
          </Space>
          <Form.Item
            name="iletisim_ad"
            label="Talep eden (irtibatı kayıtlı olmayan ekipmanlar için)"
          >
            <Input maxLength={120} />
          </Form.Item>
          <Form.Item name="iletisim_telefon" label="Telefon">
            <Input maxLength={20} inputMode="tel" />
          </Form.Item>
          <Form.Item name="aciklama" label="Açıklama">
            <Input.TextArea rows={2} maxLength={4000} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`Sözleşmeye bağla (${secili.length} ekipman)`}
        open={bagAcik}
        onCancel={() => setBagAcik(false)}
        onOk={() => sozlesmeId != null && bagla.mutate(sozlesmeId)}
        okButtonProps={{ disabled: sozlesmeId == null || tekMusteri == null }}
        confirmLoading={bagla.isPending}
        okText="Bağla"
        cancelText="Vazgeç"
        destroyOnHidden
      >
        {tekMusteri == null ? (
          <Alert
            type="warning"
            showIcon
            title="Seçilen ekipmanlar tek bir müşteriye ait olmalı (müşterisiz ekipman bağlanamaz)."
          />
        ) : (
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Typography.Text type="secondary">
              Her ekipman, seçilen aktif sözleşmede aynı türdeki boş kaleme bağlanır.
            </Typography.Text>
            <Select
              style={{ width: "100%" }}
              placeholder="Aktif sözleşme seçin"
              loading={sozlesmeler.isLoading}
              value={sozlesmeId ?? undefined}
              onChange={setSozlesmeId}
              options={(sozlesmeler.data?.kayitlar ?? []).map((s) => ({
                value: s.id,
                label: `${s.contract_no} · ${s.tesis ?? s.musteri ?? ""} (${s.eslesen_kalem}/${s.toplam_kalem} eşleşmiş)`,
              }))}
              notFoundContent="Bu müşterinin aktif sözleşmesi yok"
            />
          </Space>
        )}
      </Modal>
    </>
  );
}
