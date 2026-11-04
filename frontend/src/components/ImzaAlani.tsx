/**
 * Müşteri imzası tuvali (canvas → PNG) — iş ayrıntısındaki "Müşteri onayı"
 * penceresi ve mobil iş kartındaki sonuç akışı aynı bileşeni kullanır.
 *
 * `touchAction: none` ile parmakla çizim sayfayı kaydırmaz. "Temizle" düğmesi
 * sahada da rahat basılsın diye en az 44 px'tir (rol testi B10).
 */
import { ClearOutlined } from "@ant-design/icons";
import { Button, Space } from "antd";
import { useRef } from "react";

export default function ImzaAlani({ onDegisti }: { onDegisti: (bos: boolean) => void }) {
  const tuval = useRef<HTMLCanvasElement | null>(null);
  const ciziyor = useRef(false);

  const nokta = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return {
      x: ((e.clientX - r.left) * e.currentTarget.width) / r.width,
      y: ((e.clientY - r.top) * e.currentTarget.height) / r.height,
    };
  };

  return (
    <Space orientation="vertical" style={{ width: "100%" }} size={4}>
      <canvas
        ref={tuval}
        width={600}
        height={200}
        aria-label="Müşteri imza alanı"
        style={{
          width: "100%",
          height: 160,
          border: "1px solid #d9d9d9",
          borderRadius: 4,
          touchAction: "none",
          background: "#fff",
        }}
        onPointerDown={(e) => {
          const c = e.currentTarget.getContext("2d");
          if (!c) return;
          ciziyor.current = true;
          e.currentTarget.setPointerCapture(e.pointerId);
          const p = nokta(e);
          c.lineWidth = 2.5;
          c.lineCap = "round";
          c.strokeStyle = "#000";
          c.beginPath();
          c.moveTo(p.x, p.y);
        }}
        onPointerMove={(e) => {
          if (!ciziyor.current) return;
          const c = e.currentTarget.getContext("2d");
          if (!c) return;
          const p = nokta(e);
          c.lineTo(p.x, p.y);
          c.stroke();
        }}
        onPointerUp={() => {
          if (ciziyor.current) onDegisti(false);
          ciziyor.current = false;
        }}
      />
      <Button
        icon={<ClearOutlined />}
        style={{ minHeight: 44 }}
        onClick={() => {
          const c = tuval.current?.getContext("2d");
          if (c && tuval.current) c.clearRect(0, 0, tuval.current.width, tuval.current.height);
          onDegisti(true);
        }}
      >
        Temizle
      </Button>
    </Space>
  );
}

/** Kapsayıcıdaki ilk tuvali PNG'ye çevirir (tuval yoksa null). */
export function tuvalPng(kapsayici: HTMLElement | null): Promise<Blob | null> {
  const c = kapsayici?.querySelector("canvas");
  return new Promise((coz) => (c ? c.toBlob((b) => coz(b), "image/png") : coz(null)));
}
