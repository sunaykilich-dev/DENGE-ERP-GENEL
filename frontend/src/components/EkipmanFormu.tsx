/**
 * Ekipman Formu — ekipman ekle/düzenle (TS-050).
 *
 * İSKELET (D0-S): dosya ve dışa aktarım adı sabittir ki rota/menü (D0-B) ve
 * diğer bileşenler şimdiden bağlanabilsin. İçeriği D1-E paketi yazar.
 */
import { Card, Empty } from "antd";

export default function EkipmanFormu() {
  return (
    <Card title="Ekipman Formu">
      <Empty description="Bu ekran hazırlanıyor." />
    </Card>
  );
}