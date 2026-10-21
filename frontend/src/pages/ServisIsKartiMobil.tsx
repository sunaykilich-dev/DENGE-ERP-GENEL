/**
 * Servis İşi Kartı — mobil iş kartı (TS-077).
 *
 * İSKELET (D0-S): dosya ve dışa aktarım adı sabittir ki rota/menü (D0-B) ve
 * diğer bileşenler şimdiden bağlanabilsin. İçeriği D1-G paketi yazar.
 */
import { Card, Empty } from "antd";

export default function ServisIsKartiMobil() {
  return (
    <Card title="Servis İşi Kartı">
      <Empty description="Bu ekran hazırlanıyor." />
    </Card>
  );
}