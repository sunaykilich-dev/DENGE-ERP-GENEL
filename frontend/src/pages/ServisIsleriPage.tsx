/**
 * Servis İşleri — liste, Drawer, durum/bekleme/sonuç/atama pencereleri (TS-033).
 *
 * İSKELET (D0-S): dosya ve dışa aktarım adı sabittir ki rota/menü (D0-B) ve
 * diğer bileşenler şimdiden bağlanabilsin. İçeriği D1-C paketi yazar.
 */
import { Card, Empty } from "antd";

export default function ServisIsleriPage() {
  return (
    <Card title="Servis İşleri">
      <Empty description="Bu ekran hazırlanıyor." />
    </Card>
  );
}