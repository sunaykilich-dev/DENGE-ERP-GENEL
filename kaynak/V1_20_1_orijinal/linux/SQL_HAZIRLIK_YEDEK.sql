-- IT: Bu sorgu WINDOWS SSMS uzerinde, KAYNAK DengeERP veritabaninda calistirilir.
-- Oncesinde SQL yetkilerini ve backup dizinini kontrol edin.
USE master;
GO
DECLARE @K NVARCHAR(400) = CONVERT(NVARCHAR(400),SERVERPROPERTY('InstanceDefaultBackupPath'));
DECLARE @Y NVARCHAR(500) = @K + CASE WHEN RIGHT(@K,1)='\' THEN '' ELSE '\' END
  + 'DengeERP_V1201_LINUX_GECIS_' + FORMAT(GETDATE(),'yyyyMMdd_HHmmss') + '.bak';
BACKUP DATABASE DengeERP TO DISK=@Y WITH COPY_ONLY, CHECKSUM, INIT, STATS=10;
RESTORE VERIFYONLY FROM DISK=@Y WITH CHECKSUM;
SELECT @Y AS YedekDosyasi;
-- TEST sunucusunda IT tarafindan ayri DengeERP_TEST adi ile geri yuklenmeli.
-- Mevcut uretim veritabanina otomatik migration uygulamayin.
