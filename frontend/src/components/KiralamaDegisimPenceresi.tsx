/**
 * Sahada cihaz değişimi (TS-195, E06-20) — tek pencere, tek işlem.
 *
 * Sunucu tek transaction'da: yeni seri cihaza tahsis + sevk, eski cihazın
 * seçilen depoya KONTROLDE iadesi; iki cihaza da `DEGISIM` hareketi. Kiralama
 * durumu değişmez. Hazır olmayan cihaz 409 döner (mesaj gösterilir); yeni
 * cihaz başka kiralamaya tarih çakışıyorsa (M10.1) uyarı + gerekçe ile
 * devam edilir. Yetki `kiralama.asama`.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, App, Form, Input, Modal, Select } from "antd";
import { useState } from "react";

import { kiralamaApi, type KiralamaKarti } from "../api/kiralama";
import { CakismaVazgecildi, useCakismaOnayi } from "./KiralamaCakismaOnayi";

export default function KiralamaDegisimPenceresi({
  k,
  onKapat,
  onBitti,
}: {
  k: KiralamaKarti;
  onKapat: () => void;
  onBitti: () => void;
}) {
  const { message } = App.useApp();
  const sahada = k.tahsisler.filter((t) => t.durum === "AKTIF" && t.kiralik_id && t.musteride > 0);
  const [eski, setEski] = useState<number | undefined>(sahada.length === 1 ? sahada[0].id : undefined);
  const [yeni, setYeni] = useState<number | undefined>();
  const [depo, setDepo] = useState<number | undefined>();
  const [not, setNot] = useState("");
  const eskiTahsis = sahada.find((t) => t.id === eski);
  const adaylar = useQuery({
    queryKey: ["kiralik-hazir", eskiTahsis?.product_id],
    queryFn: () => kiralamaApi.envanter({ product_id: eskiTahsis!.product_id, durum: "HAZIR" }, 200, 0),
    enabled: !!eskiTahsis,
  });
  const depolar = useQuery({ queryKey: ["kiralama-depolar"], queryFn: kiralamaApi.depolar });

  const cakismaOnayiyla = useCakismaOnayi();

  const gonder = useMutation({
    mutationFn: () =>
      cakismaOnayiyla((onay) =>
        kiralamaApi.degisim(
          k.id,
          {
            eski_tahsis_id: eski!,
            yeni_kiralik_id: yeni!,
            iade_depo_id: depo!,
            not: not.trim() || undefined,
          },
          onay,
        ),
      ),
    onSuccess: () => {
      message.success("Cihaz değiştirildi; eski cihaz kontrole alındı");
      onBitti();
      onKapat();
    },
    onError: (e) =>
      e instanceof CakismaVazgecildi ? message.info(e.message) : message.error((e as Error).message),
  });

  return (
    <Modal
      open
      title="Sahada cihaz değişimi"
      onCancel={onKapat}
      onOk={() => gonder.mutate()}
      okText="Değiştir"
      cancelText="Vazgeç"
      okButtonProps={{ disabled: !eski || !yeni || !depo, loading: gonder.isPending }}
    >
      {sahada.length === 0 ? (
        <Alert type="info" showIcon title="Müşteride seri takipli cihaz yok" />
      ) : (
        <Form layout="vertical">
          <Form.Item label="Sahadaki cihaz" required>
            <Select
              value={eski}
              onChange={(v) => {
                setEski(v);
                setYeni(undefined);
              }}
              options={sahada.map((t) => ({ value: t.id, label: `${t.urun_kodu ?? ""} · ${t.seri ?? ""}` }))}
            />
          </Form.Item>
          <Form.Item label="Yerine gönderilecek hazır cihaz" required>
            <Select
              showSearch
              optionFilterProp="label"
              loading={adaylar.isLoading}
              value={yeni}
              onChange={setYeni}
              disabled={!eskiTahsis}
              options={(adaylar.data?.kayitlar ?? [])
                .filter((c) => c.birim === k.birim && !c.kiralama_id)
                .map((c) => ({ value: c.id, label: `${c.serial_no} · ${c.depo_adi ?? ""}` }))}
            />
          </Form.Item>
          <Form.Item label="Eski cihazın döneceği depo (kontrole girer)" required>
            <Select
              value={depo}
              onChange={setDepo}
              options={(depolar.data ?? [])
                .filter((d) => !d.birim || d.birim === k.birim)
                .map((d) => ({ value: d.id, label: `${d.code} — ${d.name}` }))}
            />
          </Form.Item>
          <Form.Item label="Not">
            <Input.TextArea maxLength={300} value={not} onChange={(e) => setNot(e.target.value)} />
          </Form.Item>
        </Form>
      )}
    </Modal>
  );
}
