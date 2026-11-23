/**
 * Kamerayla barkod/QR okuma penceresi. İlk okunan kod `onOkundu`'ya gider ve
 * pencere kapanır (okunan değer alana el okuyucu yazmış gibi girer).
 */
import { CameraOutlined } from "@ant-design/icons";
import { Alert, Button, Modal, Spin, Typography } from "antd";
import { useEffect, useRef, useState } from "react";

import { taramayiBaslat } from "./kameraTarama";

export function KameraDugmesi({
  onOkundu,
  disabled,
  baslik,
  buyuk,
}: {
  onOkundu: (metin: string) => void;
  disabled?: boolean;
  baslik?: string;
  buyuk?: boolean;
}) {
  const [acik, setAcik] = useState(false);
  return (
    <>
      <Button
        icon={<CameraOutlined />}
        aria-label="Kamerayla okut"
        title="Kamerayla okut"
        disabled={disabled}
        size={buyuk ? "large" : undefined}
        style={buyuk ? { minHeight: 44, minWidth: 44 } : undefined}
        onClick={() => setAcik(true)}
      />
      <KameraOkuyucu
        acik={acik}
        baslik={baslik}
        onKapat={() => setAcik(false)}
        onOkundu={(m) => {
          setAcik(false);
          onOkundu(m);
        }}
      />
    </>
  );
}

export default function KameraOkuyucu({
  acik,
  onKapat,
  onOkundu,
  baslik = "Barkodu kameraya gösterin",
}: {
  acik: boolean;
  onKapat: () => void;
  onOkundu: (metin: string) => void;
  baslik?: string;
}) {
  const video = useRef<HTMLVideoElement | null>(null);
  const [hata, setHata] = useState<string | null>(null);
  const [hazir, setHazir] = useState(false);
  const geriCagri = useRef(onOkundu);
  geriCagri.current = onOkundu;

  useEffect(() => {
    if (!acik) return;
    let durdur: (() => void) | null = null;
    let iptal = false;
    let okundu = false;
    setHata(null);
    setHazir(false);
    // Modal içeriği çizildikten sonra video öğesi hazır olur.
    const t = window.setTimeout(() => {
      if (!video.current) return;
      taramayiBaslat(video.current, (metin) => {
        if (okundu) return;
        okundu = true;
        durdur?.();
        navigator.vibrate?.(80);
        geriCagri.current(metin);
      })
        .then((d) => {
          if (iptal || okundu) d();
          else {
            durdur = d;
            setHazir(true);
          }
        })
        .catch((e: Error) => {
          if (!iptal) setHata(e.message);
        });
    }, 50);
    return () => {
      iptal = true;
      window.clearTimeout(t);
      durdur?.();
    };
  }, [acik]);

  return (
    <Modal open={acik} onCancel={onKapat} title={baslik} footer={null} destroyOnHidden centered width={480}>
      {hata ? (
        <Alert type="warning" showIcon message={hata} />
      ) : (
        <div style={{ position: "relative", background: "#000", borderRadius: 8, overflow: "hidden" }}>
          <video
            ref={video}
            muted
            playsInline
            autoPlay
            style={{ width: "100%", display: "block", minHeight: 240, objectFit: "cover" }}
          />
          {/* Hedef çerçevesi: kodu bu bandın içine getirin. */}
          <div
            style={{
              position: "absolute",
              inset: "30% 8%",
              border: "2px solid rgba(255,255,255,0.85)",
              borderRadius: 8,
              pointerEvents: "none",
            }}
          />
          {!hazir && (
            <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>
              <Spin />
            </div>
          )}
        </div>
      )}
      <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0, fontSize: 12 }}>
        Barkod ya da QR kodu çerçeveye getirin; okununca pencere kendiliğinden kapanır.
      </Typography.Paragraph>
    </Modal>
  );
}
