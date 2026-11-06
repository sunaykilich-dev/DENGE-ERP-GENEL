-- V1.10 - Gerçek kişi bazlı çalışma süresi. Tekrar çalıştırılabilir / mevcut kayıtlara dokunmaz.
IF OBJECT_ID(N'dbo.WorkOrderTimeLogs', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.WorkOrderTimeLogs
    (
        TimeLogId BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        WorkOrderId BIGINT NOT NULL REFERENCES dbo.WorkOrders(WorkOrderId),
        TechnicianName NVARCHAR(200) NOT NULL,
        ActivityType NVARCHAR(40) NOT NULL,
        StartedAt DATETIME2(0) NOT NULL,
        EndedAt DATETIME2(0) NOT NULL,
        LocationNote NVARCHAR(250) NULL,
        WorkNote NVARCHAR(1000) NULL,
        CreatedByUserId INT NULL,
        CreatedByName NVARCHAR(200) NOT NULL,
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_WorkOrderTimeLogs_CreatedAt DEFAULT SYSDATETIME(),
        IsVoided BIT NOT NULL CONSTRAINT DF_WorkOrderTimeLogs_IsVoided DEFAULT (0),
        VoidedAt DATETIME2(0) NULL,
        VoidedByName NVARCHAR(200) NULL,
        CONSTRAINT CK_WorkOrderTimeLogs_ValidTimes CHECK (EndedAt > StartedAt AND DATEDIFF(MINUTE,StartedAt,EndedAt) <= 1080),
        CONSTRAINT CK_WorkOrderTimeLogs_Activity CHECK (ActivityType IN (N'Saha Çalışması',N'Yol / Ulaşım',N'Bekleme',N'Uzaktan Destek',N'Atölye',N'Test / Kontrol',N'Diğer'))
    );
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'dbo.WorkOrderTimeLogs') AND name=N'IX_WorkOrderTimeLogs_TechnicianStart')
    CREATE INDEX IX_WorkOrderTimeLogs_TechnicianStart ON dbo.WorkOrderTimeLogs(TechnicianName,StartedAt) INCLUDE (EndedAt,WorkOrderId,IsVoided);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'dbo.WorkOrderTimeLogs') AND name=N'IX_WorkOrderTimeLogs_WorkOrder')
    CREATE INDEX IX_WorkOrderTimeLogs_WorkOrder ON dbo.WorkOrderTimeLogs(WorkOrderId) INCLUDE (IsVoided,StartedAt,EndedAt);
GO
