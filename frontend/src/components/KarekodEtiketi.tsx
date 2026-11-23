/**
 * Kiralık cihaz karekod etiketi (KARARLAR 2026-11-20 §3).
 *
 * Her cihazın değişmez etiket kodu vardır; karekod ERP'deki `/etiket/<kod>`
 * sayfasını açar. Etiket yazdırılıp cihaza yapıştırılır (Xray kapı, bariyer…).
 * Telefonun kamerasıyla okutulunca teslim sayfası açılır.
 */
import { PrinterOutlined, QrcodeOutlined } from "@ant-design/icons";
import { useMutation } from "@tanstack/react-query";
import { App, Button, Modal, QRCode, Space, Typography } from "antd";
import { useRef, useState } from "react";

import { kiralamaApi, type EtiketOzeti } from "../api/kiralama";

export function etiketAdresi(kod: string): string {
  return `${window.location.origin}/etiket/${encodeURIComponent(kod)}`;
}

export default function KarekodEtiketiDugmesi({ kiralikId }: { kiralikId: number }) {
  const { message } = App.useApp();
  const [etiket, setEtiket] = useState<EtiketOzeti | null>(null);
  const alan = useRef<HTMLDivElement>(null);
  const uret = useMutation({
    mutationFn: () => kiralamaApi.etiketUret(kiralikId),
    onSuccess: setEtiket,
    onError: (e: Error) => void message.error(e.message),
  });

  const yazdir = () => {
    const icerik = alan.current?.innerHTML;
    if (!icerik) return;
    const pencere = window.open("", "_blank", "width=420,height=520");
    if (!pencere) return;
    pencere.document.write(
      `<!doctype html><html><head><meta charset="utf-8"><title>Etiket</title>` +
        `<style>body{font-family:sans-serif;margin:8mm;text-align:center}` +
        `.ad{font-size:12pt;font-weight:600}.seri{font-family:monospace;font-size:14pt}</style>` +
        `</head><body>${icerik}</body></html>`,
    );
    pencere.document.close();
    pencere.focus();
    pencere.print();
  };

  return (
    <>
      <Button icon={<QrcodeOutlined />} loading={uret.isPending} onClick={() => uret.mutate()}>
        Karekod etiketi
      </Button>
      <Modal
        open={etiket != null}
        title="Karekod etiketi"
        onCancel={() => setEtiket(null)}
        footer={
          <Button type="primary" icon={<PrinterOutlined />} onClick={yazdir}>
            Yazdır
          </Button>
        }
        destroyOnHidden
      >
        {etiket?.etiket_kodu && (
          <Space orientation="vertical" align="center" style={{ width: "100%" }}>
            <div ref={alan} style={{ textAlign: "center" }}>
              <QRCode value={etiketAdresi(etiket.etiket_kodu)} size={200} type="svg" bordered={false} />
              <div className="ad">{etiket.urun}</div>
              <div className="seri">{etiket.seri}</div>
              <div style={{ fontSize: 10 }}>Denge · {etiket.etiket_kodu}</div>
            </div>
            <Typography.Text type="secondary" style={{ fontSize: 12, textAlign: "center" }}>
              Telefonun kamerasıyla okutulunca cihazın teslim sayfası açılır. Kod değişmez; etiket
              yeniden basılabilir.
            </Typography.Text>
          </Space>
        )}
      </Modal>
    </>
  );
}
