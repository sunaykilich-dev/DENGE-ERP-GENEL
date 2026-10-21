/**
 * Planlama — takvim, plansız havuz, araç havuzu (TS-042…048).
 *
 * İSKELET (D0-S): dosya ve dışa aktarım adı sabittir ki rota/menü (D0-B) ve
 * diğer bileşenler şimdiden bağlanabilsin. İçeriği D1-D paketi yazar.
 */
import { Card, Empty } from "antd";

export default function ServisPlanlamaPage() {
  return (
    <Card title="Planlama">
      <Empty description="Bu ekran hazırlanıyor." />
    </Card>
  );
}