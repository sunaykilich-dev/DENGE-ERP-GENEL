/**
 * Servis Tanımları — arıza nedeni ve bekleme nedeni katalogları (TS-024/023).
 *
 * İSKELET (D0-S): dosya ve dışa aktarım adı sabittir ki rota/menü (D0-B) ve
 * diğer bileşenler şimdiden bağlanabilsin. İçeriği D1-B paketi yazar.
 */
import { Card, Empty } from "antd";

export default function ServisTanimlarPage() {
  return (
    <Card title="Servis Tanımları">
      <Empty description="Bu ekran hazırlanıyor." />
    </Card>
  );
}