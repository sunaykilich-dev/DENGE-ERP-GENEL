-- V1.14 - Canli saha zaman oturumlari. Tekrar calistirilabilir, onceki sure kayıtlarini etkilemez.
IF OBJECT_ID(N'dbo.WorkOrderLiveSessions',N'U') IS NULL
BEGIN
    CREATE TABLE dbo.WorkOrderLiveSessions
    (
        SessionId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_WorkOrderLiveSessions PRIMARY KEY,
        WorkOrderId BIGINT NOT NULL CONSTRAINT FK_LiveSessions_WorkOrders REFERENCES dbo.WorkOrders(WorkOrderId),
        TechnicianUserId INT NOT NULL CONSTRAINT FK_LiveSessions_Users REFERENCES dbo.ErpUsers(UserId),
        TechnicianName NVARCHAR(200) NOT NULL,
        ActivityType NVARCHAR(40) NOT NULL,
        StartedAt DATETIME2(0) NOT NULL CONSTRAINT DF_LiveSessions_StartedAt DEFAULT SYSDATETIME(),
        EndedAt DATETIME2(0) NULL,
        StopReason NVARCHAR(30) NULL,
        LocationNote NVARCHAR(250) NULL,
        WorkNote NVARCHAR(1000) NULL,
        ResultTimeLogId BIGINT NULL,
        CancelledByUserId INT NULL,
        CancelReason NVARCHAR(500) NULL,
        CONSTRAINT CK_LiveSessions_Activity CHECK (ActivityType IN (
            N'Saha Çalışması', N'Yol / Ulaşım', N'Bekleme',
            N'Uzaktan Destek', N'Atölye', N'Test / Kontrol', N'Mola / Ara')),
        CONSTRAINT CK_LiveSessions_ValidEnd CHECK (EndedAt IS NULL OR EndedAt>=StartedAt)
    );
END;
GO
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'dbo.WorkOrderLiveSessions') AND name=N'UX_LiveSessions_OneActivePerUser')
    CREATE UNIQUE INDEX UX_LiveSessions_OneActivePerUser
        ON dbo.WorkOrderLiveSessions(TechnicianUserId)
        WHERE EndedAt IS NULL;
GO
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'dbo.WorkOrderLiveSessions') AND name=N'IX_LiveSessions_WorkOrder')
    CREATE INDEX IX_LiveSessions_WorkOrder
        ON dbo.WorkOrderLiveSessions(WorkOrderId,StartedAt DESC)
        INCLUDE (EndedAt,TechnicianUserId,ActivityType);
GO
