/**
 * Plan Penceresi — tekli/toplu/yeniden plan penceresi (TS-041/043/046).
 *
 * İSKELET (D0-S): dosya ve dışa aktarım adı sabittir ki rota/menü (D0-B) ve
 * diğer bileşenler şimdiden bağlanabilsin. İçeriği D1-D paketi yazar.
 */
import { Card, Empty } from "antd";

export default function PlanPenceresi() {
  return (
    <Card title="Plan Penceresi">
      <Empty description="Bu ekran hazırlanıyor." />
    </Card>
  );
}