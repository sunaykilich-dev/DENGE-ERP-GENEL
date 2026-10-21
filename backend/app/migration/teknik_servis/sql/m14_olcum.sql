/*
  M14 kaynak veri ölçümü — DengeERP V1.20.1 (SQL Server) — YALNIZ SELECT
  TS-017 / E14-08 (kaynak tarafı). Canlı SQL Server'a BAĞLANILMAZ: V1.20.1
  .bak yedeği ayrı bir test örneğine geri yüklenir ve bu dosya SSMS'te orada
  koşulur. Her bölüm ayrı sonuç kümesidir; çıktı Excel'e sayfa sayfa
  kopyalanır ve E14-09 faz kapsamı ile E14-01 yayın notuna yazılır.

  Neden yalnız SELECT: ölçüm karar girdisidir, kaynağı değiştirmemeli.
  `tests/integration/test_ana_veri_olcum.py` bu dosyada yazma komutu
  (INSERT/UPDATE/DELETE/MERGE/DDL/EXEC) olmadığını denetler.

  Müşteri adı karşılaştırmaları iki biçimde verilir:
    - BİREBİR: V1'in kullandığı `=` eşitliği (P.cs:3011),
    - KATLANMIŞ: kırpılmış + Turkish_CI_AS (büyük/küçük harf duyarsız).
  Kişi adı ve telefon sonuç kümelerine alınmaz. STRING_AGG için SQL Server 2017+.
*/

SET NOCOUNT ON;

/* 1) Tablo bazında farklı müşteri metni sayısı ------------------------------ */
SELECT N'WorkOrders.CustomerName' AS Kaynak,
       COUNT(*) AS Satir,
       COUNT(DISTINCT CustomerName) AS FarkliBirebir,
       COUNT(DISTINCT UPPER(LTRIM(RTRIM(CustomerName))) COLLATE Turkish_CI_AS) AS FarkliKatlanmis
FROM dbo.WorkOrders
UNION ALL
SELECT N'MaintenanceContracts.CustomerName', COUNT(*), COUNT(DISTINCT CustomerName),
       COUNT(DISTINCT UPPER(LTRIM(RTRIM(CustomerName))) COLLATE Turkish_CI_AS)
FROM dbo.MaintenanceContracts
UNION ALL
SELECT N'SecurityDevices.CustomerName', COUNT(*), COUNT(DISTINCT CustomerName),
       COUNT(DISTINCT UPPER(LTRIM(RTRIM(CustomerName))) COLLATE Turkish_CI_AS)
FROM dbo.SecurityDevices
UNION ALL
SELECT N'SecurityDevices.Location', COUNT(*), COUNT(DISTINCT Location),
       COUNT(DISTINCT UPPER(LTRIM(RTRIM(Location))) COLLATE Turkish_CI_AS)
FROM dbo.SecurityDevices
UNION ALL
SELECT N'Offers.CustomerName', COUNT(*), COUNT(DISTINCT CustomerName),
       COUNT(DISTINCT UPPER(LTRIM(RTRIM(CustomerName))) COLLATE Turkish_CI_AS)
FROM dbo.Offers
UNION ALL
SELECT N'RentalOrders.CustomerName', COUNT(*), COUNT(DISTINCT CustomerName),
       COUNT(DISTINCT UPPER(LTRIM(RTRIM(CustomerName))) COLLATE Turkish_CI_AS)
FROM dbo.RentalOrders
UNION ALL
SELECT N'WorkshopTickets.CompanyName', COUNT(*), COUNT(DISTINCT CompanyName),
       COUNT(DISTINCT UPPER(LTRIM(RTRIM(CompanyName))) COLLATE Turkish_CI_AS)
FROM dbo.WorkshopTickets
UNION ALL
SELECT N'WorkOrderPlans.SiteName', COUNT(*), COUNT(DISTINCT SiteName),
       COUNT(DISTINCT UPPER(LTRIM(RTRIM(SiteName))) COLLATE Turkish_CI_AS)
FROM dbo.WorkOrderPlans;

/* 2) Boş müşteri ------------------------------------------------------------- */
SELECT N'WorkOrders' AS Tablo,
       SUM(CASE WHEN CustomerName IS NULL OR LTRIM(RTRIM(CustomerName)) = N'' THEN 1 ELSE 0 END) AS BosMusteri,
       COUNT(*) AS Satir
FROM dbo.WorkOrders
UNION ALL
SELECT N'MaintenanceContracts',
       SUM(CASE WHEN CustomerName IS NULL OR LTRIM(RTRIM(CustomerName)) = N'' THEN 1 ELSE 0 END),
       COUNT(*)
FROM dbo.MaintenanceContracts
UNION ALL
SELECT N'SecurityDevices',
       SUM(CASE WHEN CustomerName IS NULL OR LTRIM(RTRIM(CustomerName)) = N'' THEN 1 ELSE 0 END),
       COUNT(*)
FROM dbo.SecurityDevices
UNION ALL
SELECT N'Offers',
       SUM(CASE WHEN CustomerName IS NULL OR LTRIM(RTRIM(CustomerName)) = N'' THEN 1 ELSE 0 END),
       COUNT(*)
FROM dbo.Offers
UNION ALL
SELECT N'RentalOrders',
       SUM(CASE WHEN CustomerName IS NULL OR LTRIM(RTRIM(CustomerName)) = N'' THEN 1 ELSE 0 END),
       COUNT(*)
FROM dbo.RentalOrders
UNION ALL
SELECT N'WorkshopTickets',
       SUM(CASE WHEN CompanyName IS NULL OR LTRIM(RTRIM(CompanyName)) = N'' THEN 1 ELSE 0 END),
       COUNT(*)
FROM dbo.WorkshopTickets;

/* 3) Sözleşme – kütük eşleşmesi (CustomerName ve Location AYRI AYRI) -------- */
-- 3a) Özet: aktif sözleşmelerden kaçı kütükte karşılık buluyor.
SELECT COUNT(*) AS AktifSozlesme,
       SUM(CASE WHEN EXISTS (SELECT 1 FROM dbo.SecurityDevices d
                             WHERE d.IsActive = 1 AND d.CustomerName = c.CustomerName)
                THEN 1 ELSE 0 END) AS MusteriBirebir,
       SUM(CASE WHEN EXISTS (SELECT 1 FROM dbo.SecurityDevices d
                             WHERE d.IsActive = 1
                               AND UPPER(LTRIM(RTRIM(d.CustomerName))) COLLATE Turkish_CI_AS
                                 = UPPER(LTRIM(RTRIM(c.CustomerName))) COLLATE Turkish_CI_AS)
                THEN 1 ELSE 0 END) AS MusteriKatlanmis,
       SUM(CASE WHEN EXISTS (SELECT 1 FROM dbo.SecurityDevices d
                             WHERE d.IsActive = 1 AND d.Location = c.CustomerName)
                THEN 1 ELSE 0 END) AS LokasyonBirebir,
       SUM(CASE WHEN EXISTS (SELECT 1 FROM dbo.SecurityDevices d
                             WHERE d.IsActive = 1
                               AND UPPER(LTRIM(RTRIM(d.Location))) COLLATE Turkish_CI_AS
                                 = UPPER(LTRIM(RTRIM(c.CustomerName))) COLLATE Turkish_CI_AS)
                THEN 1 ELSE 0 END) AS LokasyonKatlanmis
FROM dbo.MaintenanceContracts c
WHERE c.IsActive = 1;

-- 3b) Ayrıntı: her aktif sözleşme ve kütükteki karşılık adedi.
SELECT c.SourceKey, c.CustomerName,
       (SELECT COUNT(*) FROM dbo.SecurityDevices d
        WHERE d.IsActive = 1 AND d.CustomerName = c.CustomerName) AS MusteriBirebirCihaz,
       (SELECT COUNT(*) FROM dbo.SecurityDevices d
        WHERE d.IsActive = 1
          AND UPPER(LTRIM(RTRIM(d.CustomerName))) COLLATE Turkish_CI_AS
            = UPPER(LTRIM(RTRIM(c.CustomerName))) COLLATE Turkish_CI_AS) AS MusteriKatlanmisCihaz,
       (SELECT COUNT(*) FROM dbo.SecurityDevices d
        WHERE d.IsActive = 1 AND d.Location = c.CustomerName) AS LokasyonBirebirCihaz,
       (SELECT COUNT(*) FROM dbo.SecurityDevices d
        WHERE d.IsActive = 1
          AND UPPER(LTRIM(RTRIM(d.Location))) COLLATE Turkish_CI_AS
            = UPPER(LTRIM(RTRIM(c.CustomerName))) COLLATE Turkish_CI_AS) AS LokasyonKatlanmisCihaz
FROM dbo.MaintenanceContracts c
WHERE c.IsActive = 1
ORDER BY c.SourceKey;

/* 4) PB işinde lokasyon = bölge (M14-07 etkisi, A3-08) ----------------------- */
SELECT COUNT(*) AS LokasyonuBolgeIleEzilmisPbIsi
FROM dbo.WorkOrders w
JOIN dbo.MaintenanceDeviceItems i ON i.WorkOrderId = w.WorkOrderId
WHERE w.Location = i.Zone;

SELECT w.WorkOrderNo, w.CustomerName, w.Location, i.Zone
FROM dbo.WorkOrders w
JOIN dbo.MaintenanceDeviceItems i ON i.WorkOrderId = w.WorkOrderId
WHERE w.Location = i.Zone
ORDER BY w.WorkOrderNo;

/* 5) Şüpheli mükerrer sözleşmeler ------------------------------------------- */
-- 5a) Aynı (katlanmış) müşteri adıyla birden çok AKTİF sözleşme.
SELECT UPPER(LTRIM(RTRIM(CustomerName))) COLLATE Turkish_CI_AS AS MusteriAnahtari,
       COUNT(*) AS AktifSozlesme,
       STRING_AGG(CAST(SourceKey AS NVARCHAR(MAX)), N', ') AS SozlesmeAnahtarlari
FROM dbo.MaintenanceContracts
WHERE IsActive = 1
GROUP BY UPPER(LTRIM(RTRIM(CustomerName))) COLLATE Turkish_CI_AS
HAVING COUNT(*) > 1
ORDER BY COUNT(*) DESC;

-- 5b) Aynı adres + aynı ürün metniyle birden çok AKTİF sözleşme.
SELECT CurrentAddress, ProductsText, COUNT(*) AS AktifSozlesme,
       STRING_AGG(CAST(SourceKey AS NVARCHAR(MAX)), N', ') AS SozlesmeAnahtarlari
FROM dbo.MaintenanceContracts
WHERE IsActive = 1 AND CurrentAddress IS NOT NULL
GROUP BY CurrentAddress, ProductsText
HAVING COUNT(*) > 1
ORDER BY COUNT(*) DESC;

/* 6) Kütük: seri no'suz ve mükerrer seri (E03-05) ---------------------------- */
SELECT COUNT(*) AS AktifCihaz,
       SUM(CASE WHEN SerialNo IS NULL OR LTRIM(RTRIM(SerialNo)) = N'' THEN 1 ELSE 0 END) AS SeriNosuz,
       SUM(CASE WHEN Location IS NULL OR LTRIM(RTRIM(Location)) = N'' THEN 1 ELSE 0 END) AS Lokasyonsuz
FROM dbo.SecurityDevices
WHERE IsActive = 1;

-- Kırpılmış + büyük harf seri anahtarıyla mükerrer gruplar (baştaki sıfır korunur).
SELECT UPPER(LTRIM(RTRIM(SerialNo))) COLLATE Turkish_CI_AS AS SeriAnahtari,
       COUNT(*) AS Satir,
       STRING_AGG(CAST(SourceKey AS NVARCHAR(MAX)), N', ') AS KaynakAnahtarlari
FROM dbo.SecurityDevices
WHERE IsActive = 1 AND SerialNo IS NOT NULL AND LTRIM(RTRIM(SerialNo)) <> N''
GROUP BY UPPER(LTRIM(RTRIM(SerialNo))) COLLATE Turkish_CI_AS
HAVING COUNT(*) > 1
ORDER BY COUNT(*) DESC;

/* 7) PB kalemi: cihaz kimliği boş (E03-05 kabul 3) --------------------------- */
SELECT COUNT(*) AS PbKalemi,
       SUM(CASE WHEN SecurityDeviceId IS NULL THEN 1 ELSE 0 END) AS CihazKimligiBos,
       SUM(CASE WHEN SecurityDeviceId IS NULL AND (SerialNo IS NULL OR LTRIM(RTRIM(SerialNo)) = N'')
                THEN 1 ELSE 0 END) AS CihazKimligiVeSeriBos
FROM dbo.MaintenanceDeviceItems;
