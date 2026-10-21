/**
 * Servis Paneli — tıklanabilir KPI kutuları (TS-035).
 *
 * İSKELET (D0-S): dosya ve dışa aktarım adı sabittir ki rota/menü (D0-B) ve
 * diğer bileşenler şimdiden bağlanabilsin. İçeriği D1-C paketi yazar.
 */
import { Card, Empty } from "antd";

export default function ServisPaneli() {
  return (
    <Card title="Servis Paneli">
      <Empty description="Bu ekran hazırlanıyor." />
    </Card>
  );
}