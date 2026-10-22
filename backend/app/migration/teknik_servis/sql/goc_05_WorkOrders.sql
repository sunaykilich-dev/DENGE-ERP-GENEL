/*
  Göç-1 dışa aktarım — DengeERP V1.20.1 (SQL Server) — YALNIZ SELECT (TS-170…177, plan §5.3)
  Canlı SQL Server'a BAĞLANILMAZ: .bak yedeği ayrı bir test örneğine geri yüklenir,
  bu dosya orada disa_aktar.ps1 ile koşulur. Çıktı: <Tablo>.csv (UTF-8).
  Tarih/saat ISO 8601 (CONVERT 126, yerel saat — hazırlama UTC'ye çevirir),
  seri no METİN (CAST NVARCHAR). Kaynağa yazma komutu YOKTUR (test denetler).
*/
SET NOCOUNT ON;
SELECT WorkOrderId, WorkOrderNo, UnitCode, WorkType, CustomerName, ProjectName, Location,
       Subject, Description, Priority, Status, SystemName,
       CAST(SerialNo AS NVARCHAR(200)) AS SerialNo,
       CONVERT(NVARCHAR(19), CreatedAt, 126) AS CreatedAt,
       CONVERT(NVARCHAR(19), UpdatedAt, 126) AS UpdatedAt,
       CONVERT(NVARCHAR(19), ClosedAt, 126) AS ClosedAt
FROM dbo.WorkOrders
ORDER BY WorkOrderId;