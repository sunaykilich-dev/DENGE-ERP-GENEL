/**
 * Bakım Formu — dijital bakım formu (TS-064).
 *
 * İSKELET (D0-S): dosya ve dışa aktarım adı sabittir ki rota/menü (D0-B) ve
 * diğer bileşenler şimdiden bağlanabilsin. İçeriği D1-F paketi yazar.
 */
import { Card, Empty } from "antd";

export default function BakimFormu() {
  return (
    <Card title="Bakım Formu">
      <Empty description="Bu ekran hazırlanıyor." />
    </Card>
  );
}