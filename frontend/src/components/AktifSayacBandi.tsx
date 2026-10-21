/**
 * Aktif Sayaç Bandı — açık sayaç bandı, unuttum/geri al (TS-072).
 *
 * İSKELET (D0-S): dosya ve dışa aktarım adı sabittir ki rota/menü (D0-B) ve
 * diğer bileşenler şimdiden bağlanabilsin. İçeriği D1-G paketi yazar.
 */
import { Card, Empty } from "antd";

export default function AktifSayacBandi() {
  return (
    <Card title="Aktif Sayaç Bandı">
      <Empty description="Bu ekran hazırlanıyor." />
    </Card>
  );
}