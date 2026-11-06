-- DengeERP V1.8: Her cihaz icin bagimsiz PB is emri ve dijital servis/bakim formu.
-- Yalnizca eksik kolon ve tablolar eklenir, eski satirlar silinmez.
IF COL_LENGTH('dbo.MaintenanceDeviceItems','WorkOrderId') IS NULL
    ALTER TABLE dbo.MaintenanceDeviceItems ADD WorkOrderId BIGINT NULL;
GO
IF COL_LENGTH('dbo.MaintenanceDeviceItems','Zone') IS NULL
    ALTER TABLE dbo.MaintenanceDeviceItems ADD Zone NVARCHAR(250) NULL;
GO
IF COL_LENGTH('dbo.MaintenanceDeviceItems','PerformedWork') IS NULL
    ALTER TABLE dbo.MaintenanceDeviceItems ADD PerformedWork NVARCHAR(MAX) NULL;
GO
IF COL_LENGTH('dbo.MaintenanceDeviceItems','SpareParts') IS NULL
    ALTER TABLE dbo.MaintenanceDeviceItems ADD SpareParts NVARCHAR(1000) NULL;
GO
IF COL_LENGTH('dbo.MaintenanceDeviceItems','ServiceResult') IS NULL
    ALTER TABLE dbo.MaintenanceDeviceItems ADD ServiceResult NVARCHAR(80) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_MDI_IndividualWorkOrder')
BEGIN
    ALTER TABLE dbo.MaintenanceDeviceItems ADD CONSTRAINT FK_MDI_IndividualWorkOrder
    FOREIGN KEY(WorkOrderId) REFERENCES dbo.WorkOrders(WorkOrderId);
END
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='UX_MDI_WorkOrderId' AND object_id=OBJECT_ID('dbo.MaintenanceDeviceItems'))
BEGIN
    CREATE UNIQUE NONCLUSTERED INDEX UX_MDI_WorkOrderId
    ON dbo.MaintenanceDeviceItems(WorkOrderId) WHERE WorkOrderId IS NOT NULL;
END
GO
IF OBJECT_ID('dbo.MaintenanceDeviceChecks','U') IS NULL
BEGIN
    CREATE TABLE dbo.MaintenanceDeviceChecks
    (
        MaintenanceDeviceCheckId BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        MaintenanceDeviceItemId BIGINT NOT NULL,
        CheckCode NVARCHAR(60) NOT NULL,
        CheckLabel NVARCHAR(350) NOT NULL,
        CheckResult NVARCHAR(40) NOT NULL CONSTRAINT DF_MDChecks_Result DEFAULT N'Bekliyor',
        CheckedBy NVARCHAR(180) NULL,
        CheckedAt DATETIME2 NULL,
        CONSTRAINT FK_MDChecks_DeviceItem FOREIGN KEY(MaintenanceDeviceItemId)
           REFERENCES dbo.MaintenanceDeviceItems(MaintenanceDeviceItemId),
        CONSTRAINT UQ_MDChecks_DeviceItem_Code UNIQUE(MaintenanceDeviceItemId,CheckCode)
    );
END
GO
