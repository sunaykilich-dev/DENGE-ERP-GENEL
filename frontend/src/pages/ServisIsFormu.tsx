/**
 * Servis İşi Formu — açılış/düzenleme formu (TS-033/034).
 *
 * İSKELET (D0-S): dosya ve dışa aktarım adı sabittir ki rota/menü (D0-B) ve
 * diğer bileşenler şimdiden bağlanabilsin. İçeriği D1-C paketi yazar.
 */
import { Card, Empty } from "antd";

export default function ServisIsFormu() {
  return (
    <Card title="Servis İşi Formu">
      <Empty description="Bu ekran hazırlanıyor." />
    </Card>
  );
}