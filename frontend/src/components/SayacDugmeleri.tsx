/**
 * Sayaç Düğmeleri — tek dokunuş saha akışı (TS-071).
 *
 * İSKELET (D0-S): dosya ve dışa aktarım adı sabittir ki rota/menü (D0-B) ve
 * diğer bileşenler şimdiden bağlanabilsin. İçeriği D1-G paketi yazar.
 */
import { Card, Empty } from "antd";

export default function SayacDugmeleri() {
  return (
    <Card title="Sayaç Düğmeleri">
      <Empty description="Bu ekran hazırlanıyor." />
    </Card>
  );
}