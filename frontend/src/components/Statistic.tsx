import { Statistic as AntStatistic } from "antd";
import type { ComponentProps } from "react";

type AntProps = ComponentProps<typeof AntStatistic>;

/**
 * Türkçe sayı biçimiyle gelen `Statistic`.
 *
 * İki şeyi tek yerde çözer:
 *
 * 1. AntD'nin varsayılan binlik ayırıcısı `,` ve ondalığı `.` — `trTR`
 *    yerelleştirmesi bunları DEĞİŞTİRMİYOR. Sahadaki cihaz sayısı ekranda
 *    "1,694" çıkıyordu; bir ERP'de bu "bin altı yüz doksan dört" değil
 *    "bir tam altı yüz doksan dört" diye okunur.
 * 2. AntD 6'da `valueStyle` yerini `styles.content`'e bıraktı. Çağıran
 *    taraflar `valueStyle` yazmaya devam ediyor; çeviri burada yapılır ki
 *    her sayfayı tek tek değiştirmek gerekmesin.
 */
export default function Statistic({ valueStyle, styles, ...props }: AntProps) {
  return (
    <AntStatistic
      groupSeparator="."
      decimalSeparator=","
      styles={styles ?? (valueStyle ? { content: valueStyle } : undefined)}
      {...props}
    />
  );
}
