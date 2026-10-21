/**
 * Planlı Bakım — sözleşme, dönem, eşleştirme, kapsam dışı (TS-060…069).
 *
 * İSKELET (D0-S): dosya ve dışa aktarım adı sabittir ki rota/menü (D0-B) ve
 * diğer bileşenler şimdiden bağlanabilsin. İçeriği D1-F paketi yazar.
 */
import { Card, Empty } from "antd";

export default function BakimPage() {
  return (
    <Card title="Planlı Bakım">
      <Empty description="Bu ekran hazırlanıyor." />
    </Card>
  );
}