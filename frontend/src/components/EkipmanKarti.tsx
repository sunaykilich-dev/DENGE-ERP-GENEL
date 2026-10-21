/**
 * Ekipman Kartı — kart ve birleşik geçmiş (TS-051/052).
 *
 * İSKELET (D0-S): dosya ve dışa aktarım adı sabittir ki rota/menü (D0-B) ve
 * diğer bileşenler şimdiden bağlanabilsin. İçeriği D1-E paketi yazar.
 */
import { Card, Empty } from "antd";

export default function EkipmanKarti() {
  return (
    <Card title="Ekipman Kartı">
      <Empty description="Bu ekran hazırlanıyor." />
    </Card>
  );
}