/**
 * Ekipman Kütüğü — liste, filtre, Excel, KPI (TS-053/055/056).
 *
 * İSKELET (D0-S): dosya ve dışa aktarım adı sabittir ki rota/menü (D0-B) ve
 * diğer bileşenler şimdiden bağlanabilsin. İçeriği D1-E paketi yazar.
 */
import { Card, Empty } from "antd";

export default function ServisEkipmanPage() {
  return (
    <Card title="Ekipman Kütüğü">
      <Empty description="Bu ekran hazırlanıyor." />
    </Card>
  );
}