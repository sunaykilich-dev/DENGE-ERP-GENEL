/**
 * Benim İşlerim — teknisyenin tek mobil ekranı (TS-077/078).
 *
 * İSKELET (D0-S): dosya ve dışa aktarım adı sabittir ki rota/menü (D0-B) ve
 * diğer bileşenler şimdiden bağlanabilsin. İçeriği D1-G paketi yazar.
 */
import { Card, Empty } from "antd";

export default function BenimIslerimPage() {
  return (
    <Card title="Benim İşlerim">
      <Empty description="Bu ekran hazırlanıyor." />
    </Card>
  );
}