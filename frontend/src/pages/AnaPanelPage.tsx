/**
 * Ana Panel — GEÇİCİ yer tutucu.
 *
 * Asıl Ana Panel (KARARLAR 2026-11-04 §4) başka bir pakette yazılıyor ve
 * birleştirmede bu dosyanın yerini alır. Kabuk paketi yalnız rotayı (`/`,
 * `/ana-panel`) bu bileşene bağlar.
 */
import { Empty, Typography } from "antd";

export default function AnaPanelPage() {
  return (
    <div style={{ background: "#fff", border: "1px solid #e5e5e5", borderRadius: 8, padding: 24 }}>
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        Ana Panel
      </Typography.Title>
      <Empty description="Hazırlanıyor" />
    </div>
  );
}
