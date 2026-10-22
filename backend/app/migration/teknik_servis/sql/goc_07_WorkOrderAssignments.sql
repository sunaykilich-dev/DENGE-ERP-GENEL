/*
  Göç-1 dışa aktarım — DengeERP V1.20.1 (SQL Server) — YALNIZ SELECT (TS-170…177, plan §5.3)
  Canlı SQL Server'a BAĞLANILMAZ: .bak yedeği ayrı bir test örneğine geri yüklenir,
  bu dosya orada disa_aktar.ps1 ile koşulur. Çıktı: <Tablo>.csv (UTF-8).
  Tarih/saat ISO 8601 (CONVERT 126, yerel saat — hazırlama UTC'ye çevirir),
  seri no METİN (CAST NVARCHAR). Kaynağa yazma komutu YOKTUR (test denetler).
*/
SET NOCOUNT ON;
SELECT AssignmentId, WorkOrderId, AssignedName, AssignmentRole, CAST(IsActive AS INT) AS IsActive,
       CONVERT(NVARCHAR(19), AssignedAt, 126) AS AssignedAt
FROM dbo.WorkOrderAssignments
ORDER BY AssignmentId;