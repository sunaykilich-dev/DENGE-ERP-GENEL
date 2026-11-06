-- V1.7: Yalnızca yeni tablo; eski kayıtlar korunur.
IF OBJECT_ID('dbo.MaintenanceDeviceItems','U') IS NULL
BEGIN
 CREATE TABLE dbo.MaintenanceDeviceItems(
  MaintenanceDeviceItemId BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
  MaintenancePlanId BIGINT NOT NULL,
  SecurityDeviceId BIGINT NULL,
  DeviceType NVARCHAR(100) NOT NULL,
  DeviceOrdinal INT NOT NULL,
  SerialNo NVARCHAR(200) NULL,
  Status NVARCHAR(30) NOT NULL CONSTRAINT DF_MDI_Status DEFAULT N'Bekliyor',
  CompletedBy NVARCHAR(180) NULL,
  CompletedAt DATETIME2 NULL,
  Notes NVARCHAR(1000) NULL,
  CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_MDI_Created DEFAULT SYSDATETIME(),
  CONSTRAINT FK_MDI_Plan FOREIGN KEY(MaintenancePlanId) REFERENCES dbo.MaintenancePlans(MaintenancePlanId),
  CONSTRAINT FK_MDI_Device FOREIGN KEY(SecurityDeviceId) REFERENCES dbo.SecurityDevices(SecurityDeviceId),
  CONSTRAINT UQ_MDI_PlanTypeOrdinal UNIQUE(MaintenancePlanId,DeviceType,DeviceOrdinal)
 );
END
GO
