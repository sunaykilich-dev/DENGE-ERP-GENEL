import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App, Button, Input, Modal, Popconfirm, Select, Space, Tag, Typography } from "antd";
import { useState } from "react";

import { gorevApi, type Etiket, type Pano } from "../api/gorevler";

/** AntD etiket paleti — yeni panoya konan altı renk de buradan. */
const RENKLER = [
  { value: "green", label: "Yeşil" },
  { value: "gold", label: "Sarı" },
  { value: "orange", label: "Turuncu" },
  { value: "red", label: "Kırmızı" },
  { value: "purple", label: "Mor" },
  { value: "blue", label: "Mavi" },
  { value: "cyan", label: "Turkuaz" },
  { value: "magenta", label: "Pembe" },
];

/**
 * Pano etiketleri. Ad ZORUNLU DEĞİL — adsız etiket yalnız renk olarak durur.
 *
 * Etiket silinince kartlardan da düşer ama kart silinmez; bu yüzden onay
 * metni ne olacağını açıkça söyler.
 */
export default function EtiketYonetimi({
  acik,
  pano,
  onKapat,
}: {
  acik: boolean;
  pano: Pano | undefined;
  onKapat: () => void;
}) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [yeniAd, setYeniAd] = useState("");
  const [yeniRenk, setYeniRenk] = useState("blue");

  const tazele = () => {
    void qc.invalidateQueries({ queryKey: ["panolar"] });
    void qc.invalidateQueries({ queryKey: ["pano-kartlar"] });
  };

  const ekle = useMutation({
    mutationFn: () => gorevApi.etiketEkle(pano!.id, { ad: yeniAd.trim() || null, renk: yeniRenk }),
    onSuccess: () => {
      setYeniAd("");
      tazele();
    },
    onError: (e: Error) => void message.error(e.message),
  });

  const guncelle = useMutation({
    mutationFn: (v: Etiket) => gorevApi.etiketGuncelle(v.id, { ad: v.ad, renk: v.renk }),
    onSuccess: () => tazele(),
    onError: (e: Error) => void message.error(e.message),
  });

  const sil = useMutation({
    mutationFn: (id: number) => gorevApi.etiketSil(id),
    onSuccess: () => {
      message.success("Etiket silindi");
      tazele();
    },
    onError: (e: Error) => void message.error(e.message),
  });

  return (
    <Modal
      title={`${pano?.title ?? ""} — etiketler`}
      open={acik}
      onCancel={onKapat}
      footer={<Button onClick={onKapat}>Kapat</Button>}
    >
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        Ad zorunlu değil; adsız etiket yalnız renk olarak görünür. Etiketi silmek onu
        kartlardan da düşürür, kartları silmez.
      </Typography.Paragraph>

      <Space orientation="vertical" size={8} style={{ width: "100%" }}>
        {(pano?.etiketler ?? []).map((e) => (
          <Space.Compact key={e.id} style={{ width: "100%" }}>
            <Select
              value={e.renk}
              style={{ width: 130 }}
              onChange={(renk) => guncelle.mutate({ ...e, renk })}
              options={RENKLER}
              optionRender={(o) => <Tag color={String(o.value)}>{o.label}</Tag>}
            />
            <Input
              defaultValue={e.ad ?? ""}
              placeholder="(adsız)"
              onBlur={(ev) => {
                const ad = ev.target.value.trim() || null;
                if (ad !== e.ad) guncelle.mutate({ ...e, ad });
              }}
            />
            <Popconfirm
              title="Etiket silinsin mi?"
              description="Yapıştırıldığı kartlardan düşer; kartlar silinmez."
              okText="Sil"
              cancelText="Vazgeç"
              onConfirm={() => sil.mutate(e.id)}
            >
              <Button danger>×</Button>
            </Popconfirm>
          </Space.Compact>
        ))}

        <Space.Compact style={{ width: "100%", marginTop: 6 }}>
          <Select
            value={yeniRenk}
            style={{ width: 130 }}
            onChange={setYeniRenk}
            options={RENKLER}
            optionRender={(o) => <Tag color={String(o.value)}>{o.label}</Tag>}
          />
          <Input
            value={yeniAd}
            placeholder="Yeni etiket adı (isteğe bağlı)"
            onChange={(ev) => setYeniAd(ev.target.value)}
            onPressEnter={() => ekle.mutate()}
          />
          <Button type="primary" loading={ekle.isPending} onClick={() => ekle.mutate()}>
            Ekle
          </Button>
        </Space.Compact>
      </Space>
    </Modal>
  );
}
