/*
  Göç-2 dışa aktarım (D3-G, TS-205…208) — DengeERP V1.20.1 (SQL Server) — YALNIZ SELECT.
  Canlı SQL Server'a BAĞLANILMAZ: .bak yedeği ayrı bir test örneğine geri yüklenir,
  bu dosya orada disa_aktar.ps1 ile koşulur. Çıktı: <Tablo>.csv (UTF-8).
  Tarih/saat ISO 8601 (CONVERT 126, yerel saat), seri no METİN. Kişisel iletişim
  verisi (telefon, e-posta, adres) ve parola özeti ALINMAZ.
*/
SET NOCOUNT ON;SELECT RentalOrderId, RentalNo, UnitCode, Status, SerialNumbers,
       CONVERT(NVARCHAR(10), StartDate, 126) AS StartDate,
       CONVERT(NVARCHAR(10), EndDate, 126) AS EndDate,
       CONVERT(NVARCHAR(19), ClosedAt, 126) AS ClosedAt
FROM dbo.RentalOrders
ORDER BY RentalOrderId;
