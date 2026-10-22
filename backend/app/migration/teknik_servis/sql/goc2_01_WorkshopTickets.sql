/*
  Göç-2 dışa aktarım (D3-G, TS-205…208) — DengeERP V1.20.1 (SQL Server) — YALNIZ SELECT.
  Canlı SQL Server'a BAĞLANILMAZ: .bak yedeği ayrı bir test örneğine geri yüklenir,
  bu dosya orada disa_aktar.ps1 ile koşulur. Çıktı: <Tablo>.csv (UTF-8).
  Tarih/saat ISO 8601 (CONVERT 126, yerel saat), seri no METİN. Kişisel iletişim
  verisi (telefon, e-posta, adres) ve parola özeti ALINMAZ.
*/
SET NOCOUNT ON;SELECT WorkshopTicketId, WorkshopNo, WorkOrderId, Status, AssignedTo,
       CAST(SerialNo AS NVARCHAR(180)) AS SerialNo, Brand, Model, ServiceType, WarrantyStatus,
       CONVERT(NVARCHAR(19), EntryDate, 126) AS EntryDate,
       CONVERT(NVARCHAR(19), CompletionDate, 126) AS CompletionDate,
       CONVERT(NVARCHAR(19), UpdatedAt, 126) AS UpdatedAt, RepairInfo
FROM dbo.WorkshopTickets
ORDER BY WorkshopTicketId;
