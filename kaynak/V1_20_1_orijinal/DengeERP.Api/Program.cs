using Microsoft.Data.SqlClient;
using System.Collections.Concurrent;
using System.Globalization;
using System.IO.Compression;
using System.Net;
using System.Net.Mail;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls(builder.Configuration["Urls"] ?? "http://0.0.0.0:5050");
var app = builder.Build();

app.UseDefaultFiles();
app.UseStaticFiles();

var connectionString = builder.Configuration.GetConnectionString("DengeERP")
    ?? throw new InvalidOperationException("ConnectionStrings:DengeERP ayarlanmamis. /etc/dengeerp/dengeerp.env dosyasini kontrol edin.");

var sessions = new ConcurrentDictionary<string, SessionUser>();
var databasePath = Path.Combine(app.Environment.ContentRootPath, "Database");

// Linux kurulumu: varsayilan olarak veri tabaninda HICBIR sema/seed degisikligi yapma.
// Yalnizca IT onayi ve test DB yedegi sonrasinda DengeERP__RunDatabaseSetupOnStartup=true.
if (builder.Configuration.GetValue<bool>("DengeERP:RunDatabaseSetupOnStartup"))
{
    try
    {
        foreach (var sqlFile in Directory.GetFiles(databasePath, "*.sql").OrderBy(Path.GetFileName))
            await ApplySchemaAsync(connectionString, sqlFile);

        await SeedUsersAsync(connectionString, builder.Configuration["DengeERP:InitialAdminPassword"]);
        await EnsureMaintenancePlansAndWorkOrdersAsync(connectionString);
    }
    catch (Exception ex)
    {
        app.Logger.LogError(ex, "DengeERP veritabani ilklendirme basarisiz; hizmet baslatilmadi.");
        throw;
    }
}
else
{
    app.Logger.LogInformation("Veritabani sema guncellemesi KAPALI. Var olan test veritabani kullanilacak.");
}

app.MapGet("/api/health", async () =>
{
    try
    {
        await using var connection = new SqlConnection(connectionString);
        await connection.OpenAsync();
        return Results.Ok(new
        {
            application = "Denge ERP API",
            status = "Çalışıyor",
            database = "Bağlı",
            time = DateTime.Now
        });
    }
    catch (Exception ex)
    {
        return Results.Problem(title: "SQL bağlantısı başarısız", detail: ex.Message, statusCode: 503);
    }
});

app.MapPost("/api/auth/login", async (LoginRequest request) =>
{
    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();

    var command = new SqlCommand(@"
SELECT UserId,Username,PasswordHash,PasswordSalt,FullName,RoleName,AllowedUnits,Permissions,IsActive,MustChangePassword
FROM dbo.ErpUsers
WHERE Username=@Username", connection);
    command.Parameters.AddWithValue("@Username", request.Username.Trim());

    await using var reader = await command.ExecuteReaderAsync();
    if (!await reader.ReadAsync()) return Results.Unauthorized();

    var userId = reader.GetInt32(0);
    var username = reader.GetString(1);
    var hash = reader.GetString(2);
    var salt = reader.GetString(3);
    var fullName = reader.GetString(4);
    var roleName = reader.GetString(5);
    var units = SplitPipe(reader.GetString(6));
    var permissions = SplitPipe(reader.GetString(7));
    var isActive = reader.GetBoolean(8);
    var mustChange = reader.GetBoolean(9);

    if (!isActive || !VerifyPassword(request.Password, salt, hash)) return Results.Unauthorized();

    var token = Convert.ToHexString(RandomNumberGenerator.GetBytes(32));
    var session = new SessionUser(userId, username, fullName, roleName, units, permissions, mustChange);
    sessions[token] = session;

    return Results.Ok(new { token, user = session });
});

app.MapGet("/api/auth/me", (HttpContext ctx) =>
{
    var user = GetCurrentUser(ctx, sessions);
    return user is null ? Results.Unauthorized() : Results.Ok(user);
});

app.MapPost("/api/auth/logout", (HttpContext ctx) =>
{
    var token = ReadToken(ctx);
    if (!string.IsNullOrWhiteSpace(token)) sessions.TryRemove(token, out _);
    return Results.Ok(new { message = "Oturum kapatıldı." });
});

app.MapPost("/api/auth/change-password", async (HttpContext ctx, ChangePasswordRequest request) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (string.IsNullOrWhiteSpace(request.NewPassword) || request.NewPassword.Length < 8)
        return Results.BadRequest(new { message = "Yeni şifre en az 8 karakter olmalı." });

    var (salt, hash) = HashPassword(request.NewPassword);
    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    var command = new SqlCommand(@"
UPDATE dbo.ErpUsers
SET PasswordHash=@Hash,PasswordSalt=@Salt,MustChangePassword=0,UpdatedAt=SYSDATETIME()
WHERE UserId=@Id", connection);
    command.Parameters.AddWithValue("@Hash", hash);
    command.Parameters.AddWithValue("@Salt", salt);
    command.Parameters.AddWithValue("@Id", user.UserId);
    await command.ExecuteNonQueryAsync();

    var refreshed = user with { MustChangePassword = false };
    var token = ReadToken(ctx);
    if (!string.IsNullOrWhiteSpace(token)) sessions[token] = refreshed;
    return Results.Ok(new { message = "Şifre güncellendi.", user = refreshed });
});

app.MapGet("/api/meta/permissions", (HttpContext ctx) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    return Results.Ok(new
    {
        permissions = Catalog.PermissionCatalog,
        roleDefaults = Catalog.RoleDefaults,
        units = Catalog.AllUnits,
        roles = Catalog.RoleDefaults.Keys,
        departments = Catalog.Departments
    });
});

app.MapGet("/api/rules/worktypes", async (HttpContext ctx) =>
{
    if (GetCurrentUser(ctx, sessions) is null) return Results.Unauthorized();
    var rows = new List<object>();
    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    var command = new SqlCommand(@"
SELECT UnitCode,WorkType,SerialRequiredOnCreate,SerialRequiredOnClose
FROM dbo.WorkTypeRules WHERE IsActive=1 ORDER BY UnitCode,WorkType", connection);
    await using var reader = await command.ExecuteReaderAsync();
    while (await reader.ReadAsync())
        rows.Add(new
        {
            unitCode = reader.GetString(0),
            workType = reader.GetString(1),
            serialRequiredOnCreate = reader.GetBoolean(2),
            serialRequiredOnClose = reader.GetBoolean(3)
        });
    return Results.Ok(rows);
});

app.MapGet("/api/users", async (HttpContext ctx) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "users.manage")) return Results.Forbid();

    var rows = new List<object>();
    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    var command = new SqlCommand(@"
SELECT UserId,Username,FullName,RoleName,AllowedUnits,Permissions,IsActive,MustChangePassword,CreatedAt
FROM dbo.ErpUsers ORDER BY FullName", connection);
    await using var reader = await command.ExecuteReaderAsync();
    while (await reader.ReadAsync())
        rows.Add(new
        {
            userId = reader.GetInt32(0),
            username = reader.GetString(1),
            fullName = reader.GetString(2),
            roleName = reader.GetString(3),
            allowedUnits = SplitPipe(reader.GetString(4)),
            permissions = SplitPipe(reader.GetString(5)),
            isActive = reader.GetBoolean(6),
            mustChangePassword = reader.GetBoolean(7),
            createdAt = reader.GetDateTime(8)
        });
    return Results.Ok(rows);
});

app.MapPost("/api/users", async (HttpContext ctx, CreateUserRequest request) =>
{
    var current = GetCurrentUser(ctx, sessions);
    if (current is null) return Results.Unauthorized();
    if (!Can(current, "users.manage")) return Results.Forbid();
    if (string.IsNullOrWhiteSpace(request.Username) || string.IsNullOrWhiteSpace(request.FullName))
        return Results.BadRequest(new { message = "Ad soyad ve kullanıcı adı zorunlu." });
    if (string.IsNullOrWhiteSpace(request.Password) || request.Password.Length < 8)
        return Results.BadRequest(new { message = "Geçici şifre en az 8 karakter olmalı." });

    var permissions = request.Permissions is { Count: > 0 }
        ? request.Permissions
        : GetRoleDefaults(request.RoleName).ToList();
    var units = request.AllowedUnits is { Count: > 0 } ? request.AllowedUnits : Catalog.AllUnits.ToList();
    var (salt, hash) = HashPassword(request.Password);

    try
    {
        await using var connection = new SqlConnection(connectionString);
        await connection.OpenAsync();
        var command = new SqlCommand(@"
INSERT INTO dbo.ErpUsers
(Username,PasswordHash,PasswordSalt,FullName,RoleName,AllowedUnits,Permissions,IsActive,MustChangePassword)
OUTPUT INSERTED.UserId
VALUES(@Username,@Hash,@Salt,@FullName,@Role,@Units,@Permissions,1,@MustChange)", connection);
        command.Parameters.AddWithValue("@Username", request.Username.Trim());
        command.Parameters.AddWithValue("@Hash", hash);
        command.Parameters.AddWithValue("@Salt", salt);
        command.Parameters.AddWithValue("@FullName", request.FullName.Trim());
        command.Parameters.AddWithValue("@Role", request.RoleName);
        command.Parameters.AddWithValue("@Units", JoinPipe(units));
        command.Parameters.AddWithValue("@Permissions", JoinPipe(permissions));
        command.Parameters.AddWithValue("@MustChange", request.MustChangePassword);
        var id = Convert.ToInt32(await command.ExecuteScalarAsync());
        return Results.Ok(new { userId = id, message = "Kullanıcı oluşturuldu." });
    }
    catch (SqlException ex) when (ex.Number is 2601 or 2627)
    {
        return Results.Conflict(new { message = "Bu kullanıcı adı zaten kullanılıyor." });
    }
});

app.MapPut("/api/users/{id:int}", async (HttpContext ctx, int id, UpdateUserRequest request) =>
{
    var current = GetCurrentUser(ctx, sessions);
    if (current is null) return Results.Unauthorized();
    if (!Can(current, "users.manage")) return Results.Forbid();
    if (string.IsNullOrWhiteSpace(request.Username) || string.IsNullOrWhiteSpace(request.FullName))
        return Results.BadRequest(new { message = "Ad soyad ve kullanıcı adı zorunlu." });

    var permissions = request.Permissions is { Count: > 0 }
        ? request.Permissions
        : GetRoleDefaults(request.RoleName).ToList();
    var units = request.AllowedUnits is { Count: > 0 }
        ? request.AllowedUnits
        : Catalog.AllUnits.ToList();

    try
    {
        await using var connection = new SqlConnection(connectionString);
        await connection.OpenAsync();

        var command = new SqlCommand(@"
UPDATE dbo.ErpUsers
SET Username=@Username,
    FullName=@FullName,
    RoleName=@Role,
    AllowedUnits=@Units,
    Permissions=@Permissions,
    MustChangePassword=@MustChange,
    UpdatedAt=SYSDATETIME()
WHERE UserId=@Id;
SELECT @@ROWCOUNT;", connection);
        command.Parameters.AddWithValue("@Username", request.Username.Trim());
        command.Parameters.AddWithValue("@FullName", request.FullName.Trim());
        command.Parameters.AddWithValue("@Role", request.RoleName);
        command.Parameters.AddWithValue("@Units", JoinPipe(units));
        command.Parameters.AddWithValue("@Permissions", JoinPipe(permissions));
        command.Parameters.AddWithValue("@MustChange", request.MustChangePassword);
        command.Parameters.AddWithValue("@Id", id);

        var affected = Convert.ToInt32(await command.ExecuteScalarAsync());
        if (affected == 0) return Results.NotFound(new { message = "Kullanıcı bulunamadı." });

        var updated = new SessionUser(
            id,
            request.Username.Trim(),
            request.FullName.Trim(),
            request.RoleName,
            units,
            permissions,
            request.MustChangePassword
        );

        foreach (var kv in sessions.Where(x => x.Value.UserId == id).ToList())
            sessions[kv.Key] = updated;

        return Results.Ok(new
        {
            message = "Kullanıcı yetkileri güncellendi.",
            user = new
            {
                userId = updated.UserId,
                username = updated.Username,
                fullName = updated.FullName,
                roleName = updated.RoleName,
                allowedUnits = updated.AllowedUnits,
                permissions = updated.Permissions,
                mustChangePassword = updated.MustChangePassword
            }
        });
    }
    catch (SqlException ex) when (ex.Number is 2601 or 2627)
    {
        return Results.Conflict(new { message = "Bu kullanıcı adı zaten kullanılıyor." });
    }
});

app.MapPatch("/api/users/{id:int}/status", async (HttpContext ctx, int id, UserStatusRequest request) =>
{
    var current = GetCurrentUser(ctx, sessions);
    if (current is null) return Results.Unauthorized();
    if (!Can(current, "users.manage")) return Results.Forbid();
    if (current.UserId == id && !request.IsActive)
        return Results.BadRequest(new { message = "Kendi hesabınızı pasif yapamazsınız." });

    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    var command = new SqlCommand("UPDATE dbo.ErpUsers SET IsActive=@Active,UpdatedAt=SYSDATETIME() WHERE UserId=@Id", connection);
    command.Parameters.AddWithValue("@Active", request.IsActive);
    command.Parameters.AddWithValue("@Id", id);
    var affected = await command.ExecuteNonQueryAsync();
    return affected == 0 ? Results.NotFound() : Results.Ok(new { message = "Kullanıcı durumu güncellendi." });
});

app.MapPost("/api/users/{id:int}/reset-password", async (HttpContext ctx, int id, ResetPasswordRequest request) =>
{
    var current = GetCurrentUser(ctx, sessions);
    if (current is null) return Results.Unauthorized();
    if (!Can(current, "users.manage")) return Results.Forbid();
    if (string.IsNullOrWhiteSpace(request.TempPassword) || request.TempPassword.Length < 8)
        return Results.BadRequest(new { message = "Geçici şifre en az 8 karakter olmalı." });

    var (salt, hash) = HashPassword(request.TempPassword);
    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    var command = new SqlCommand(@"
UPDATE dbo.ErpUsers SET PasswordHash=@Hash,PasswordSalt=@Salt,MustChangePassword=1,UpdatedAt=SYSDATETIME()
WHERE UserId=@Id", connection);
    command.Parameters.AddWithValue("@Hash", hash);
    command.Parameters.AddWithValue("@Salt", salt);
    command.Parameters.AddWithValue("@Id", id);
    var affected = await command.ExecuteNonQueryAsync();
    return affected == 0 ? Results.NotFound() : Results.Ok(new { message = "Geçici şifre oluşturuldu." });
});

app.MapGet("/api/workorders", async (HttpContext ctx) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "workorders.view")) return Results.Forbid();

    var records = await LoadWorkOrdersAsync(connectionString);
    records = FilterWorkOrdersForUser(records, user);
    return Results.Ok(records);
});

app.MapPost("/api/workorders", async (HttpContext ctx, CreateWorkOrderRequest request) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "workorders.create")) return Results.Forbid();
    if (!UnitAllowed(user, request.UnitCode)) return Results.Forbid();

    var serials = CleanSerials(request.SerialNumbers);
    var rule = await GetWorkTypeRuleAsync(connectionString, request.UnitCode, request.WorkType);
    if (rule.SerialRequiredOnCreate && serials.Count == 0)
        return Results.BadRequest(new { message = "Bu iş türünde seri numarası kayıt açılışında zorunludur." });

    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    await using var transaction = (SqlTransaction)await connection.BeginTransactionAsync();

    var prefix = $"SRV-{DateTime.Now:yyyyMM}-";
    var numberCommand = new SqlCommand(@"
SELECT ISNULL(MAX(TRY_CONVERT(INT, RIGHT(WorkOrderNo, 4))),0) + 1
FROM dbo.WorkOrders WITH (UPDLOCK, HOLDLOCK)
WHERE WorkOrderNo LIKE @Prefix + '%'", connection, transaction);
    numberCommand.Parameters.AddWithValue("@Prefix", prefix);
    var nextNumber = Convert.ToInt32(await numberCommand.ExecuteScalarAsync());
    var workOrderNo = $"{prefix}{nextNumber:0000}";

    var insertCommand = new SqlCommand(@"
INSERT INTO dbo.WorkOrders
(WorkOrderNo,UnitCode,WorkType,CustomerName,ProjectName,Location,Subject,Description,Priority,Status,CreatedByUserId,CreatedByErpUserId,SystemName,SerialNo,CustomerEmail,UpdatedAt)
OUTPUT INSERTED.WorkOrderId
VALUES
(@WorkOrderNo,@UnitCode,@WorkType,@CustomerName,@ProjectName,@Location,@Subject,@Description,@Priority,N'Müşteri Talebi',NULL,@CreatedByErp,@SystemName,@SerialNo,@CustomerEmail,SYSDATETIME())", connection, transaction);
    insertCommand.Parameters.AddWithValue("@WorkOrderNo", workOrderNo);
    insertCommand.Parameters.AddWithValue("@UnitCode", request.UnitCode);
    insertCommand.Parameters.AddWithValue("@WorkType", request.WorkType);
    insertCommand.Parameters.AddWithValue("@CustomerName", request.CustomerName);
    insertCommand.Parameters.AddWithValue("@ProjectName", Db(request.ProjectName));
    insertCommand.Parameters.AddWithValue("@Location", Db(request.Location));
    insertCommand.Parameters.AddWithValue("@Subject", request.Subject);
    insertCommand.Parameters.AddWithValue("@Description", Db(request.Description));
    insertCommand.Parameters.AddWithValue("@Priority", request.Priority);
    insertCommand.Parameters.AddWithValue("@CreatedByErp", user.UserId);
    insertCommand.Parameters.AddWithValue("@SystemName", Db(request.SystemName));
    insertCommand.Parameters.AddWithValue("@SerialNo", Db(serials.FirstOrDefault()));
    insertCommand.Parameters.AddWithValue("@CustomerEmail", Db(request.CustomerEmail));
    var workOrderId = Convert.ToInt64(await insertCommand.ExecuteScalarAsync());

    foreach (var serial in serials)
    {
        var deviceCommand = new SqlCommand(@"
INSERT INTO dbo.WorkOrderDevices(WorkOrderId,SerialNo,ProductName,IsActive)
VALUES(@WorkOrderId,@SerialNo,@ProductName,1)", connection, transaction);
        deviceCommand.Parameters.AddWithValue("@WorkOrderId", workOrderId);
        deviceCommand.Parameters.AddWithValue("@SerialNo", serial);
        deviceCommand.Parameters.AddWithValue("@ProductName", Db(request.SystemName));
        await deviceCommand.ExecuteNonQueryAsync();
    }

    await InsertStatusLogAsync(connection, transaction, workOrderId, null, "Müşteri Talebi", "Kayıt oluşturuldu.", user);
    await transaction.CommitAsync();
    return Results.Created($"/api/workorders/{workOrderId}", new { workOrderId, workOrderNo, status = "Müşteri Talebi" });
});

app.MapPut("/api/workorders/{id:long}/serials", async (HttpContext ctx, long id, UpdateSerialsRequest request) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "workorders.create") && !Can(user, "workorders.edit") && !Can(user, "workorders.close")) return Results.Forbid();
    if (!await CanAccessWorkOrderAsync(connectionString, id, user)) return Results.Forbid();
    var serials = CleanSerials(request.SerialNumbers);
    await using (var checkDb=new SqlConnection(connectionString))
    {
        await checkDb.OpenAsync();
        var isDevice=new SqlCommand("SELECT COUNT(*) FROM dbo.MaintenanceDeviceItems WHERE WorkOrderId=@Id",checkDb);
        isDevice.Parameters.AddWithValue("@Id",id);
        if(Convert.ToInt32(await isDevice.ExecuteScalarAsync())>0)
            return Results.BadRequest(new {message="Bakım cihazının seri numarasını bakım formundan güncelleyin."});
    }

    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    await using var transaction = (SqlTransaction)await connection.BeginTransactionAsync();

    var deactivate = new SqlCommand("UPDATE dbo.WorkOrderDevices SET IsActive=0 WHERE WorkOrderId=@Id AND IsActive=1", connection, transaction);
    deactivate.Parameters.AddWithValue("@Id", id);
    await deactivate.ExecuteNonQueryAsync();

    foreach (var serial in serials)
    {
        var insert = new SqlCommand("INSERT INTO dbo.WorkOrderDevices(WorkOrderId,SerialNo,IsActive) VALUES(@Id,@Serial,1)", connection, transaction);
        insert.Parameters.AddWithValue("@Id", id);
        insert.Parameters.AddWithValue("@Serial", serial);
        await insert.ExecuteNonQueryAsync();
    }

    var update = new SqlCommand("UPDATE dbo.WorkOrders SET SerialNo=@Serial,UpdatedAt=SYSDATETIME() WHERE WorkOrderId=@Id", connection, transaction);
    update.Parameters.AddWithValue("@Serial", Db(serials.FirstOrDefault()));
    update.Parameters.AddWithValue("@Id", id);
    await update.ExecuteNonQueryAsync();

    await transaction.CommitAsync();
    return Results.Ok(new { message = "Seri numarası güncellendi.", serialNumbers = serials });
});

app.MapPatch("/api/workorders/{id:long}/status", async (HttpContext ctx, long id, UpdateStatusRequest request) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "workorders.edit") && !Can(user, "workorders.close")) return Results.Forbid();
    if (!await CanAccessWorkOrderAsync(connectionString, id, user)) return Results.Forbid();

    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    await using var transaction = (SqlTransaction)await connection.BeginTransactionAsync();

    var currentCommand = new SqlCommand(@"
SELECT UnitCode,WorkType,Status,
COALESCE((SELECT STRING_AGG(d.SerialNo,', ') FROM dbo.WorkOrderDevices d WHERE d.WorkOrderId=w.WorkOrderId AND d.IsActive=1),w.SerialNo,N'')
FROM dbo.WorkOrders w WHERE WorkOrderId=@Id", connection, transaction);
    currentCommand.Parameters.AddWithValue("@Id", id);
    string unit, workType, oldStatus, serials;
    await using (var reader = await currentCommand.ExecuteReaderAsync())
    {
        if (!await reader.ReadAsync()) return Results.NotFound(new { message = "İş emri bulunamadı." });
        unit = reader.GetString(0);
        workType = reader.GetString(1);
        oldStatus = reader.GetString(2);
        serials = reader.IsDBNull(3) ? "" : reader.GetString(3);
    }

    if (!UnitAllowed(user, unit)) return Results.Forbid();
    var deviceWo=new SqlCommand("SELECT COUNT(*) FROM dbo.MaintenanceDeviceItems WHERE WorkOrderId=@Id",connection,transaction);
    deviceWo.Parameters.AddWithValue("@Id",id);
    if(Convert.ToInt32(await deviceWo.ExecuteScalarAsync())>0 && oldStatus=="Kapatıldı" && request.Status!="Kapatıldı")
        return Results.BadRequest(new{message="Kapatılmış cihaz bakım emri bu ekrandan tekrar açılamaz."});
    if (IsClosingStatus(request.Status))
    {
        var liveCheck = new SqlCommand("SELECT COUNT(1) FROM dbo.WorkOrderLiveSessions WHERE WorkOrderId=@Id AND EndedAt IS NULL", connection, transaction);
        liveCheck.Parameters.AddWithValue("@Id", id);
        if (Convert.ToInt32(await liveCheck.ExecuteScalarAsync()) > 0)
            return Results.Conflict(new { message = "Bu işte aktif personel zaman sayacı var. Önce sayacı bitirin." });
        var individual = new SqlCommand("SELECT COUNT(*) FROM dbo.MaintenanceDeviceItems WHERE WorkOrderId=@Id", connection, transaction);
        individual.Parameters.AddWithValue("@Id", id);
        if (Convert.ToInt32(await individual.ExecuteScalarAsync()) > 0)
            return Results.BadRequest(new { message = "Cihaz bakım iş emrini kapatmak için 'Bakım Formu' ekranındaki kontrol listesini tamamlayın." });
        var missing=new SqlCommand(@"SELECT COUNT(*) FROM dbo.MaintenancePlans p WHERE p.GeneratedWorkOrderId=@Id AND p.IsCompleted=0 AND NOT EXISTS(SELECT 1 FROM dbo.MaintenanceDeviceItems i WHERE i.MaintenancePlanId=p.MaintenancePlanId)",connection,transaction);
        missing.Parameters.AddWithValue("@Id",id);
        if((int)(await missing.ExecuteScalarAsync()??0)>0) return Results.BadRequest(new {message="Ana bakım iş emrini kapatmadan önce cihaz bakım kayıtlarını oluşturun."});
        var pending=new SqlCommand(@"SELECT COUNT(*) FROM dbo.MaintenanceDeviceItems i JOIN dbo.MaintenancePlans p ON p.MaintenancePlanId=i.MaintenancePlanId WHERE p.GeneratedWorkOrderId=@Id AND i.Status<>N'Tamamlandı'",connection,transaction);
        pending.Parameters.AddWithValue("@Id",id);
        if((int)(await pending.ExecuteScalarAsync()??0)>0) return Results.BadRequest(new {message="Ana bakım iş emri kapatılamaz: tamamlanmamış cihaz bakımları var."});
        var rule = await GetWorkTypeRuleWithConnectionAsync(connection, transaction, unit, workType);
        if (rule.SerialRequiredOnClose && string.IsNullOrWhiteSpace(serials))
            return Results.BadRequest(new { message = "Bu iş türü seri numarası girilmeden tamamlanamaz/kapatılamaz." });
    }

    var command = new SqlCommand(@"
UPDATE dbo.WorkOrders
SET Status=@Status,UpdatedAt=SYSDATETIME(),ClosedAt=CASE WHEN @Status=N'Kapatıldı' THEN SYSDATETIME() ELSE ClosedAt END
WHERE WorkOrderId=@Id", connection, transaction);
    command.Parameters.AddWithValue("@Id", id);
    command.Parameters.AddWithValue("@Status", request.Status);
    await command.ExecuteNonQueryAsync();

    await InsertStatusLogAsync(connection, transaction, id, oldStatus, request.Status, request.Note, user);
    await transaction.CommitAsync();

    if (IsClosingStatus(request.Status))
    {
        await CompleteMaintenanceFromWorkOrderAsync(connectionString, id);
        await EnsureMaintenancePlansAndWorkOrdersAsync(connectionString);
    }

    return Results.Ok(new { workOrderId = id, status = request.Status, note = request.Note });
});

app.MapPut("/api/workorders/{id:long}/assignments", async (HttpContext ctx, long id, AssignmentRequest request) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "workorders.assign")) return Results.Forbid();
    if (!await CanAccessWorkOrderAsync(connectionString, id, user)) return Results.Forbid();

    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    await using var transaction = (SqlTransaction)await connection.BeginTransactionAsync();

    var deactivateCommand = new SqlCommand(@"
UPDATE dbo.WorkOrderAssignments SET IsActive=0
WHERE WorkOrderId=@WorkOrderId AND IsActive=1", connection, transaction);
    deactivateCommand.Parameters.AddWithValue("@WorkOrderId", id);
    await deactivateCommand.ExecuteNonQueryAsync();

    if (!string.IsNullOrWhiteSpace(request.Chief))
        await InsertAssignmentAsync(connection, transaction, id, request.Chief.Trim(), "Şef");

    foreach (var technician in (request.Technicians ?? []).Where(x => !string.IsNullOrWhiteSpace(x)).Distinct())
        await InsertAssignmentAsync(connection, transaction, id, technician.Trim(), "Teknisyen");

    await transaction.CommitAsync();
    return Results.Ok(new { workOrderId = id, chief = request.Chief, technicians = request.Technicians });
});

// V1.9: Çoklu iş emrine tek transaction içinde şef ve teknisyen atama.
app.MapPut("/api/workorders/bulk-assign", async (HttpContext ctx, BulkAssignmentRequest request) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "workorders.assign")) return Results.Forbid();
    var ids = (request.WorkOrderIds ?? []).Distinct().ToArray();
    if (ids.Length == 0 || ids.Length > 150 || ids.Any(x => x <= 0))
        return Results.BadRequest(new { message = "1 ile 150 arasında geçerli iş emri seçilmelidir." });
    var technicians = (request.Technicians ?? []).Where(x => !string.IsNullOrWhiteSpace(x))
        .Select(x => x.Trim()).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
    var chief = request.Chief?.Trim();
    if (technicians.Length == 0 && string.IsNullOrWhiteSpace(chief))
        return Results.BadRequest(new { message = "En az bir şef veya teknisyen seçilmelidir." });
    if (technicians.Length > 30 || technicians.Any(x => x.Length > 150) || (chief?.Length ?? 0) > 150)
        return Results.BadRequest(new { message = "Personel sayısı veya isim uzunluğu sınırı aşıldı." });

    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    await using var transaction = (SqlTransaction)await connection.BeginTransactionAsync();
    var info = await ReadBulkTargetsAsync(connection, transaction, ids);
    if (info.Count != ids.Length) return Results.BadRequest(new { message = "Seçilen iş emirlerinden biri artık bulunamıyor." });
    if (info.Any(x => !UnitAllowed(user, x.Unit))) return Results.Forbid();
    if (info.Select(x => x.Unit).Distinct(StringComparer.OrdinalIgnoreCase).Count() != 1)
        return Results.BadRequest(new { message = "Toplu atama için aynı birimdeki iş emirlerini seçin." });
    if (info.Any(x => IsBulkClosedStatus(x.Status)))
        return Results.BadRequest(new { message = "Tamamlanmış, kapatılmış veya iptal edilmiş iş emirlerine toplu atama yapılamaz." });

    foreach (var item in info)
    {
        var deactivate = new SqlCommand("UPDATE dbo.WorkOrderAssignments SET IsActive=0 WHERE WorkOrderId=@Id AND IsActive=1", connection, transaction);
        deactivate.Parameters.AddWithValue("@Id", item.Id);
        await deactivate.ExecuteNonQueryAsync();
        if (!string.IsNullOrWhiteSpace(chief))
            await InsertAssignmentAsync(connection, transaction, item.Id, chief, "Şef");
        foreach (var tech in technicians)
            await InsertAssignmentAsync(connection, transaction, item.Id, tech, "Teknisyen");
        await InsertStatusLogAsync(connection, transaction, item.Id, item.Status, item.Status,
            $"Toplu personel ataması: Şef {chief ?? "-"}; Ekip {string.Join(", ", technicians)}", user);
    }
    await transaction.CommitAsync();
    return Results.Ok(new { assignedCount = info.Count, chief, technicians });
});

// V1.9: Aynı müşteri/lokasyondaki cihazların iş emirlerini toplu planla + ata.
// İş emirleri birleştirilmez; her biri ayrı kayıt, ayrı bakım formu olarak kalır.
// V1.11 - Cihaz kütüğünden sahaya ait kayıtlı bilgiler. Şehir açıkça bulunmadığı için tahmin edilmez.
app.MapGet("/api/workorders/{id:long}/site-suggestion", async (HttpContext ctx,long id) =>
{
    var user=GetCurrentUser(ctx,sessions);
    if(user is null) return Results.Unauthorized();
    if(!Can(user,"workorders.plan")) return Results.Forbid();
    if(!await CanAccessWorkOrderAsync(connectionString,id,user)) return Results.Forbid();
    await using var db=new SqlConnection(connectionString);await db.OpenAsync();
    var cmd=new SqlCommand(@"
SELECT w.Location,mdi.Zone,COALESCE(sd.Location,sdSerial.Location),COALESCE(sd.ContactName,sdSerial.ContactName),mc.CurrentAddress
FROM dbo.WorkOrders w
OUTER APPLY (SELECT TOP 1 MaintenancePlanId,SecurityDeviceId,Zone FROM dbo.MaintenanceDeviceItems
             WHERE WorkOrderId=w.WorkOrderId ORDER BY MaintenanceDeviceItemId DESC) mdi
LEFT JOIN dbo.SecurityDevices sd ON sd.SecurityDeviceId=mdi.SecurityDeviceId AND sd.IsActive=1
OUTER APPLY (SELECT TOP 1 sd2.Location,sd2.ContactName FROM dbo.SecurityDevices sd2
 WHERE sd2.IsActive=1 AND sd2.CustomerName=w.CustomerName AND w.SerialNo IS NOT NULL
 AND sd2.SerialNo=w.SerialNo ORDER BY sd2.SecurityDeviceId) sdSerial
LEFT JOIN dbo.MaintenancePlans mp ON mp.MaintenancePlanId=mdi.MaintenancePlanId
LEFT JOIN dbo.MaintenanceContracts mc ON mc.MaintenanceContractId=mp.MaintenanceContractId
WHERE w.WorkOrderId=@Id",db);
    cmd.Parameters.AddWithValue("@Id",id);
    await using var reader=await cmd.ExecuteReaderAsync();
    if(!await reader.ReadAsync())return Results.NotFound();
    string? Read(int col)=>reader.IsDBNull(col)?null:reader.GetString(col);
    var name=Read(0);var zone=Read(1);var deviceLoc=Read(2);
    return Results.Ok(new{siteName=name,siteCity=(string?)null,siteDistrict=(string?)null,
        siteAddress=Read(4),siteArea=zone??(deviceLoc==name?null:deviceLoc),
        siteContact=Read(3),sitePhone=(string?)null,siteDirections=(string?)null,
        source="Cihaz kütüğü / bakım sözleşmesi"});
});

app.MapPut("/api/workorders/bulk-plan", async (HttpContext ctx, BulkPlanRequest request) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "workorders.plan") || !Can(user, "workorders.assign")) return Results.Forbid();
    var ids = (request.WorkOrderIds ?? []).Distinct().ToArray();
    if (ids.Length == 0 || ids.Length > 150 || ids.Any(x => x <= 0))
        return Results.BadRequest(new { message = "1 ile 150 arasında iş emri seçilebilir." });
    if (request.PlanDate == default || (request.EstimatedMinutes is null || request.EstimatedMinutes < 15 || request.EstimatedMinutes > 1440) || request.StartTime is null)
        return Results.BadRequest(new { message = "Plan tarihi, başlangıç saati ve 15-1440 dakika süre zorunludur." });
    if ((request.VehiclePlate?.Length ?? 0) > 30 || (request.PlanNote?.Length ?? 0) > 1000)
        return Results.BadRequest(new { message = "Araç plakası veya plan notu çok uzun." });
    if (!ValidPlanSite(request)) return Results.BadRequest(new {message="Saha adresi veya lokasyon alanı uzunluk sınırını aşıyor."});
    var technicians = (request.Technicians ?? []).Where(x => !string.IsNullOrWhiteSpace(x))
        .Select(x => x.Trim()).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
    var chief = request.Chief?.Trim();
    if (technicians.Length == 0 && string.IsNullOrWhiteSpace(chief))
        return Results.BadRequest(new { message = "Planlama için en az bir şef veya teknisyen seçin." });
    if (technicians.Length > 30 || technicians.Any(x => x.Length > 150) || (chief?.Length ?? 0) > 150)
        return Results.BadRequest(new { message = "Personel sayısı veya isim uzunluğu sınırı aşıldı." });

    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    await using var transaction = (SqlTransaction)await connection.BeginTransactionAsync();
    var info = await ReadBulkTargetsAsync(connection, transaction, ids);
    if (info.Count != ids.Length) return Results.BadRequest(new { message = "Seçilen iş emirlerinden biri artık bulunamıyor." });
    if (info.Any(x => !UnitAllowed(user, x.Unit))) return Results.Forbid();
    var first = info[0];
    if (string.IsNullOrWhiteSpace(first.Location) || string.IsNullOrWhiteSpace(first.Customer) ||
        info.Any(x => !string.Equals(x.Unit.Trim(), first.Unit.Trim(), StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(x.Customer.Trim(), first.Customer.Trim(), StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(x.Location.Trim(), first.Location.Trim(), StringComparison.OrdinalIgnoreCase)))
        return Results.BadRequest(new { message = "Toplu planlama yalnızca aynı müşteri, aynı lokasyon ve aynı birimde yapılabilir." });
    if (info.Any(x => IsBulkClosedStatus(x.Status) || x.IsPlanned))
        return Results.BadRequest(new { message = "Seçilen iş emirlerinden bazıları tamamlanmış veya zaten planlanmış. Listeyi yenileyin." });

    var groupNo = "TPL-" + Guid.NewGuid().ToString("N")[..16].ToUpperInvariant();
    foreach (var item in info)
    {
        var deactivate = new SqlCommand("UPDATE dbo.WorkOrderAssignments SET IsActive=0 WHERE WorkOrderId=@Id AND IsActive=1", connection, transaction);
        deactivate.Parameters.AddWithValue("@Id", item.Id);
        await deactivate.ExecuteNonQueryAsync();
        if (!string.IsNullOrWhiteSpace(chief))
            await InsertAssignmentAsync(connection, transaction, item.Id, chief, "Şef");
        foreach (var tech in technicians)
            await InsertAssignmentAsync(connection, transaction, item.Id, tech, "Teknisyen");

        var plan = new SqlCommand(@"
INSERT INTO dbo.WorkOrderPlans
 (WorkOrderId,PlanDate,StartTime,EstimatedMinutes,VehiclePlate,RouteGroupNo,PlanNote,
 SiteName,SiteCity,SiteDistrict,SiteAddress,SiteArea,SiteContact,SitePhone,SiteDirections,IsActive)
VALUES (@Id,@PlanDate,@StartTime,@Minutes,@Vehicle,@RouteGroup,@Note,
 @SiteName,@SiteCity,@SiteDistrict,@SiteAddress,@SiteArea,@SiteContact,@SitePhone,@SiteDirections,1)", connection, transaction);
        plan.Parameters.AddWithValue("@Id", item.Id);
        plan.Parameters.AddWithValue("@PlanDate", request.PlanDate.ToDateTime(TimeOnly.MinValue));
        plan.Parameters.AddWithValue("@StartTime", request.StartTime.Value.ToTimeSpan());
        plan.Parameters.AddWithValue("@Minutes", request.EstimatedMinutes.Value);
        plan.Parameters.AddWithValue("@Vehicle", Db(request.VehiclePlate?.Trim()));
        plan.Parameters.AddWithValue("@RouteGroup", groupNo);
        plan.Parameters.AddWithValue("@Note", Db(request.PlanNote?.Trim()));
        AddSiteParameters(plan,request);
        await plan.ExecuteNonQueryAsync();

        var update = new SqlCommand("UPDATE dbo.WorkOrders SET Status=N'Planlandı',UpdatedAt=SYSDATETIME() WHERE WorkOrderId=@Id", connection, transaction);
        update.Parameters.AddWithValue("@Id", item.Id);
        await update.ExecuteNonQueryAsync();
        await InsertStatusLogAsync(connection, transaction, item.Id, item.Status, "Planlandı",
            $"Toplu plan: {request.PlanDate:yyyy-MM-dd} {request.StartTime}; Ziyaret {groupNo}; Ekip {string.Join(", ", technicians)}", user);
    }
    await transaction.CommitAsync();
    return Results.Ok(new { plannedCount = info.Count, routeGroupNo = groupNo, workOrderIds = ids });
});

app.MapPut("/api/workorders/{id:long}/plan", async (HttpContext ctx, long id, PlanRequest request) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "workorders.plan")) return Results.Forbid();
    if (!await CanAccessWorkOrderAsync(connectionString, id, user)) return Results.Forbid();
    if (!ValidPlanSite(request)) return Results.BadRequest(new {message="Saha adresi veya lokasyon alanı uzunluk sınırını aşıyor."});

    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    await using var transaction = (SqlTransaction)await connection.BeginTransactionAsync();

    var deactivateCommand = new SqlCommand("UPDATE dbo.WorkOrderPlans SET IsActive=0 WHERE WorkOrderId=@WorkOrderId AND IsActive=1", connection, transaction);
    deactivateCommand.Parameters.AddWithValue("@WorkOrderId", id);
    await deactivateCommand.ExecuteNonQueryAsync();

    var insertCommand = new SqlCommand(@"
INSERT INTO dbo.WorkOrderPlans
(WorkOrderId,PlanDate,StartTime,EstimatedMinutes,VehiclePlate,RouteGroupNo,PlanNote,
 SiteName,SiteCity,SiteDistrict,SiteAddress,SiteArea,SiteContact,SitePhone,SiteDirections,IsActive)
VALUES(@WorkOrderId,@PlanDate,@StartTime,@EstimatedMinutes,@VehiclePlate,@RouteGroupNo,@PlanNote,
 @SiteName,@SiteCity,@SiteDistrict,@SiteAddress,@SiteArea,@SiteContact,@SitePhone,@SiteDirections,1)", connection, transaction);
    insertCommand.Parameters.AddWithValue("@WorkOrderId", id);
    insertCommand.Parameters.AddWithValue("@PlanDate", request.PlanDate.ToDateTime(TimeOnly.MinValue));
    insertCommand.Parameters.AddWithValue("@StartTime", request.StartTime.HasValue ? request.StartTime.Value.ToTimeSpan() : DBNull.Value);
    insertCommand.Parameters.AddWithValue("@EstimatedMinutes", (object?)request.EstimatedMinutes ?? DBNull.Value);
    insertCommand.Parameters.AddWithValue("@VehiclePlate", Db(request.VehiclePlate));
    insertCommand.Parameters.AddWithValue("@RouteGroupNo", Db(request.RouteGroupNo));
    insertCommand.Parameters.AddWithValue("@PlanNote", Db(request.PlanNote));
    AddSiteParameters(insertCommand,request);
    await insertCommand.ExecuteNonQueryAsync();

    var update = new SqlCommand("UPDATE dbo.WorkOrders SET Status=N'Planlandı',UpdatedAt=SYSDATETIME() WHERE WorkOrderId=@Id", connection, transaction);
    update.Parameters.AddWithValue("@Id", id);
    await update.ExecuteNonQueryAsync();
    await InsertStatusLogAsync(connection, transaction, id, null, "Planlandı", $"Plan: {request.PlanDate:yyyy-MM-dd} {request.StartTime}", user);

    await transaction.CommitAsync();
    return Results.Ok(new { workOrderId = id, message = "Plan kaydedildi." });
});

app.MapGet("/api/workorders/{id:long}/history", async (HttpContext ctx, long id) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "workorders.view")) return Results.Forbid();
    if (!await CanAccessWorkOrderAsync(connectionString, id, user)) return Results.Forbid();

    var rows = new List<object>();
    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    var command = new SqlCommand(@"
SELECT OldStatus,NewStatus,Note,ChangedByName,ChangedAt
FROM dbo.WorkOrderStatusLogs WHERE WorkOrderId=@Id ORDER BY StatusLogId DESC", connection);
    command.Parameters.AddWithValue("@Id", id);
    await using var reader = await command.ExecuteReaderAsync();
    while (await reader.ReadAsync())
        rows.Add(new
        {
            oldStatus = reader.IsDBNull(0) ? null : reader.GetString(0),
            newStatus = reader.GetString(1),
            note = reader.IsDBNull(2) ? null : reader.GetString(2),
            changedByName = reader.IsDBNull(3) ? null : reader.GetString(3),
            changedAt = reader.GetDateTime(4)
        });
    return Results.Ok(rows);
});

app.MapGet("/api/offers", async (HttpContext ctx) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "offers.view")) return Results.Forbid();
    var offers = await LoadOffersAsync(connectionString);
    if (!IsAdmin(user)) offers = offers.Where(x => UnitAllowed(user, x.UnitCode)).ToList();
    return Results.Ok(offers);
});

app.MapPost("/api/offers", async (HttpContext ctx, CreateOfferRequest request) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "offers.create")) return Results.Forbid();
    if (!UnitAllowed(user, request.UnitCode)) return Results.Forbid();
    if (request.Items is null || request.Items.Count == 0)
        return Results.BadRequest(new { message = "Teklifte en az bir ürün/hizmet kalemi olmalı." });

    var calc = CalculateOffer(request.Items);
    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    await using var transaction = (SqlTransaction)await connection.BeginTransactionAsync();

    var prefix = $"TKL-{DateTime.Now:yyyyMM}-";
    var numberCommand = new SqlCommand(@"
SELECT ISNULL(MAX(TRY_CONVERT(INT, RIGHT(OfferNo, 4))),0)+1
FROM dbo.Offers WITH(UPDLOCK,HOLDLOCK)
WHERE OfferNo LIKE @Prefix+'%'", connection, transaction);
    numberCommand.Parameters.AddWithValue("@Prefix", prefix);
    var next = Convert.ToInt32(await numberCommand.ExecuteScalarAsync());
    var offerNo = $"{prefix}{next:0000}";

    var command = new SqlCommand(@"
INSERT INTO dbo.Offers
(OfferNo,WorkOrderId,UnitCode,CustomerName,CustomerEmail,Status,ValidUntil,Notes,SubTotal,DiscountTotal,VatTotal,GrandTotal,CreatedByUserId)
OUTPUT INSERTED.OfferId
VALUES(@OfferNo,@WorkOrderId,@UnitCode,@CustomerName,@CustomerEmail,N'Taslak',@ValidUntil,@Notes,@SubTotal,@DiscountTotal,@VatTotal,@GrandTotal,@CreatedBy)", connection, transaction);
    command.Parameters.AddWithValue("@OfferNo", offerNo);
    command.Parameters.AddWithValue("@WorkOrderId", (object?)request.WorkOrderId ?? DBNull.Value);
    command.Parameters.AddWithValue("@UnitCode", request.UnitCode);
    command.Parameters.AddWithValue("@CustomerName", request.CustomerName);
    command.Parameters.AddWithValue("@CustomerEmail", Db(request.CustomerEmail));
    command.Parameters.AddWithValue("@ValidUntil", request.ValidUntil.HasValue ? request.ValidUntil.Value.ToDateTime(TimeOnly.MinValue) : DBNull.Value);
    command.Parameters.AddWithValue("@Notes", Db(request.Notes));
    command.Parameters.AddWithValue("@SubTotal", calc.SubTotal);
    command.Parameters.AddWithValue("@DiscountTotal", calc.DiscountTotal);
    command.Parameters.AddWithValue("@VatTotal", calc.VatTotal);
    command.Parameters.AddWithValue("@GrandTotal", calc.GrandTotal);
    command.Parameters.AddWithValue("@CreatedBy", user.UserId);
    var offerId = Convert.ToInt64(await command.ExecuteScalarAsync());

    foreach (var item in request.Items)
    {
        var itemCommand = new SqlCommand(@"
INSERT INTO dbo.OfferItems(OfferId,ItemCode,Description,Quantity,UnitPrice,DiscountPercent,VatPercent)
VALUES(@OfferId,@ItemCode,@Description,@Quantity,@UnitPrice,@DiscountPercent,@VatPercent)", connection, transaction);
        itemCommand.Parameters.AddWithValue("@OfferId", offerId);
        itemCommand.Parameters.AddWithValue("@ItemCode", Db(item.ItemCode));
        itemCommand.Parameters.AddWithValue("@Description", item.Description);
        itemCommand.Parameters.AddWithValue("@Quantity", item.Quantity);
        itemCommand.Parameters.AddWithValue("@UnitPrice", item.UnitPrice);
        itemCommand.Parameters.AddWithValue("@DiscountPercent", item.DiscountPercent);
        itemCommand.Parameters.AddWithValue("@VatPercent", item.VatPercent);
        await itemCommand.ExecuteNonQueryAsync();
    }

    await transaction.CommitAsync();
    return Results.Ok(new { offerId, offerNo, totals = calc });
});

app.MapPatch("/api/offers/{id:long}/status", async (HttpContext ctx, long id, OfferStatusRequest request) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "offers.approve")) return Results.Forbid();
    var allowed = new[] { "Taslak", "Onay Bekliyor", "Onaylandı", "Kabul Edildi", "Reddedildi" };
    if (!allowed.Contains(request.Status)) return Results.BadRequest(new { message = "Geçersiz teklif durumu." });

    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    var command = new SqlCommand(@"
UPDATE dbo.Offers SET Status=@Status,
ApprovedByUserId=CASE WHEN @Status=N'Onaylandı' THEN @UserId ELSE ApprovedByUserId END,
ApprovedAt=CASE WHEN @Status=N'Onaylandı' THEN SYSDATETIME() ELSE ApprovedAt END
WHERE OfferId=@Id", connection);
    command.Parameters.AddWithValue("@Status", request.Status);
    command.Parameters.AddWithValue("@UserId", user.UserId);
    command.Parameters.AddWithValue("@Id", id);
    var affected = await command.ExecuteNonQueryAsync();
    return affected == 0 ? Results.NotFound() : Results.Ok(new { message = "Teklif durumu güncellendi." });
});

app.MapGet("/api/offers/{id:long}/pdf", async (HttpContext ctx, long id) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "offers.view")) return Results.Forbid();
    var offer = await LoadOfferAsync(connectionString, id);
    if (offer is null) return Results.NotFound();
    if (!UnitAllowed(user, offer.UnitCode)) return Results.Forbid();
    var bytes = BuildSimpleOfferPdf(offer);
    return Results.File(bytes, "application/pdf", $"{offer.OfferNo}.pdf");
});

app.MapPost("/api/offers/{id:long}/send", async (HttpContext ctx, long id, SendOfferRequest request) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "offers.send")) return Results.Forbid();

    var offer = await LoadOfferAsync(connectionString, id);
    if (offer is null) return Results.NotFound();
    if (!UnitAllowed(user, offer.UnitCode)) return Results.Forbid();
    if (offer.Status != "Onaylandı") return Results.BadRequest(new { message = "Teklif müşteriye gönderilmeden önce Onaylandı durumunda olmalı." });

    var recipient = string.IsNullOrWhiteSpace(request.Recipient) ? offer.CustomerEmail : request.Recipient;
    if (string.IsNullOrWhiteSpace(recipient)) return Results.BadRequest(new { message = "Müşteri e-posta adresi bulunamadı." });

    var smtpHost = builder.Configuration["Email:SmtpHost"];
    var from = builder.Configuration["Email:From"];
    if (string.IsNullOrWhiteSpace(smtpHost) || string.IsNullOrWhiteSpace(from))
        return Results.BadRequest(new { message = "Kurumsal e-posta ayarları henüz yapılandırılmamış. appsettings.json içindeki Email bölümünü IT ile doldurun." });

    string status = "Gönderildi";
    string? error = null;
    try
    {
        var pdf = BuildSimpleOfferPdf(offer);
        using var message = new MailMessage();
        message.From = new MailAddress(from);
        message.To.Add(recipient);
        message.Subject = $"Denge Elektronik Teknik Servis Teklifi - {offer.OfferNo}";
        message.Body = $"Sayın Yetkili,\r\n\r\nTarafımıza iletilen teknik servis talebine ilişkin {offer.OfferNo} numaralı teklifimiz ekte bilgilerinize sunulmuştur.\r\n\r\nTeklifimizin değerlendirilmesini rica ederiz.\r\n\r\nSaygılarımızla,\r\nDenge Elektronik";
        message.Attachments.Add(new Attachment(new MemoryStream(pdf), $"{offer.OfferNo}.pdf", "application/pdf"));

        using var client = new SmtpClient(smtpHost, builder.Configuration.GetValue<int?>("Email:SmtpPort") ?? 587);
        client.EnableSsl = builder.Configuration.GetValue<bool?>("Email:EnableSsl") ?? true;
        var smtpUser = builder.Configuration["Email:Username"];
        var smtpPassword = builder.Configuration["Email:Password"];
        if (!string.IsNullOrWhiteSpace(smtpUser)) client.Credentials = new NetworkCredential(smtpUser, smtpPassword);
        await client.SendMailAsync(message);
    }
    catch (Exception ex)
    {
        status = "Hata";
        error = ex.Message;
    }

    await using (var connection = new SqlConnection(connectionString))
    {
        await connection.OpenAsync();
        var log = new SqlCommand(@"
INSERT INTO dbo.EmailLogs(OfferId,Recipient,Subject,Status,ErrorMessage,SentByUserId)
VALUES(@OfferId,@Recipient,@Subject,@Status,@Error,@UserId);
IF @Status=N'Gönderildi' UPDATE dbo.Offers SET Status=N'Müşteriye Gönderildi',SentAt=SYSDATETIME() WHERE OfferId=@OfferId;", connection);
        log.Parameters.AddWithValue("@OfferId", id);
        log.Parameters.AddWithValue("@Recipient", recipient);
        log.Parameters.AddWithValue("@Subject", $"Denge Elektronik Teknik Servis Teklifi - {offer.OfferNo}");
        log.Parameters.AddWithValue("@Status", status);
        log.Parameters.AddWithValue("@Error", Db(error));
        log.Parameters.AddWithValue("@UserId", user.UserId);
        await log.ExecuteNonQueryAsync();
    }

    return status == "Gönderildi"
        ? Results.Ok(new { message = "Teklif müşteriye gönderildi." })
        : Results.Problem(title: "E-posta gönderilemedi", detail: error, statusCode: 502);
});


app.MapGet("/api/rentals/catalog", async (HttpContext ctx) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "rentals.view") && !Can(user, "rentals.create")) return Results.Forbid();

    var rows = new List<object>();
    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    var command = new SqlCommand(@"
SELECT RentalProductId,UnitCode,Category,ProductCode,ProductName,RequiresSerial
FROM dbo.RentalProducts
WHERE IsActive=1
ORDER BY UnitCode,DisplayOrder,ProductName", connection);
    await using var reader = await command.ExecuteReaderAsync();
    while (await reader.ReadAsync())
    {
        var unit = reader.GetString(1);
        if (!UnitAllowed(user, unit)) continue;
        rows.Add(new
        {
            rentalProductId = reader.GetInt32(0),
            unitCode = unit,
            category = reader.GetString(2),
            productCode = reader.GetString(3),
            productName = reader.GetString(4),
            requiresSerial = reader.GetBoolean(5)
        });
    }
    return Results.Ok(rows);
});

app.MapGet("/api/rentals", async (HttpContext ctx) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "rentals.view")) return Results.Forbid();

    var rows = new List<object>();
    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    var command = new SqlCommand(@"
SELECT r.RentalOrderId,r.RentalNo,r.UnitCode,r.Category,r.RentalProductId,r.ProductCode,r.ProductName,
       r.CustomerName,r.CustomerEmail,r.ProjectName,r.Location,r.ContactName,r.ContactPhone,
       r.Quantity,r.SerialNumbers,r.StartDate,r.EndDate,r.Status,r.ResponsibleName,r.Notes,
       r.CreatedAt,r.UpdatedAt,r.ClosedAt,
       ISNULL(p.RequiresSerial,0),
       (SELECT COUNT(1) FROM dbo.RentalOrderItems ri WHERE ri.RentalOrderId=r.RentalOrderId),
       (SELECT ISNULL(SUM(ri.Quantity),0) FROM dbo.RentalOrderItems ri WHERE ri.RentalOrderId=r.RentalOrderId)
FROM dbo.RentalOrders r
LEFT JOIN dbo.RentalProducts p ON p.RentalProductId=r.RentalProductId
ORDER BY r.RentalOrderId DESC", connection);
    await using var reader = await command.ExecuteReaderAsync();
    while (await reader.ReadAsync())
    {
        var unit = reader.GetString(2);
        if (!UnitAllowed(user, unit)) continue;
        rows.Add(new
        {
            rentalOrderId = reader.GetInt64(0),
            rentalNo = reader.GetString(1),
            unitCode = unit,
            category = reader.GetString(3),
            rentalProductId = reader.IsDBNull(4) ? (int?)null : reader.GetInt32(4),
            productCode = reader.IsDBNull(5) ? null : reader.GetString(5),
            productName = reader.GetString(6),
            customerName = reader.GetString(7),
            customerEmail = reader.IsDBNull(8) ? null : reader.GetString(8),
            projectName = reader.IsDBNull(9) ? null : reader.GetString(9),
            location = reader.IsDBNull(10) ? null : reader.GetString(10),
            contactName = reader.IsDBNull(11) ? null : reader.GetString(11),
            contactPhone = reader.IsDBNull(12) ? null : reader.GetString(12),
            quantity = reader.GetInt32(13),
            serialNumbers = reader.IsDBNull(14) ? null : reader.GetString(14),
            startDate = DateOnly.FromDateTime(reader.GetDateTime(15)),
            endDate = DateOnly.FromDateTime(reader.GetDateTime(16)),
            status = reader.GetString(17),
            responsibleName = reader.IsDBNull(18) ? null : reader.GetString(18),
            notes = reader.IsDBNull(19) ? null : reader.GetString(19),
            createdAt = reader.GetDateTime(20),
            updatedAt = reader.IsDBNull(21) ? (DateTime?)null : reader.GetDateTime(21),
            closedAt = reader.IsDBNull(22) ? (DateTime?)null : reader.GetDateTime(22),
            requiresSerial = reader.GetBoolean(23),
            itemCount = reader.GetInt32(24),
            totalQuantity = reader.GetInt32(25)
        });
    }
    return Results.Ok(rows);
});

app.MapPost("/api/rentals", async (HttpContext ctx, CreateRentalRequest request) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "rentals.create")) return Results.Forbid();
    if (!UnitAllowed(user, request.UnitCode)) return Results.Forbid();
    if (request.Quantity <= 0) return Results.BadRequest(new { message = "Adet 1 veya daha büyük olmalı." });
    if (request.EndDate < request.StartDate) return Results.BadRequest(new { message = "Bitiş tarihi başlangıç tarihinden önce olamaz." });
    if (string.IsNullOrWhiteSpace(request.CustomerName)) return Results.BadRequest(new { message = "Müşteri zorunludur." });
    var rentalItems = request.Items is { Count: > 0 } ? request.Items :
        new List<RentalLineRequest> { new(null, request.RentalProductId, request.Quantity, request.SerialNumbers, null) };
    var rentalContacts = request.Contacts ?? new List<RentalContactRequest>();
    var validation = ValidateRentalComposition(rentalItems, rentalContacts);
    if (validation is not null) return Results.BadRequest(new { message = validation });

    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    await using var transaction = (SqlTransaction)await connection.BeginTransactionAsync();

    var productCommand = new SqlCommand(@"
SELECT TOP 1 UnitCode,Category,ProductCode,ProductName,RequiresSerial
FROM dbo.RentalProducts
WHERE RentalProductId=@Id AND IsActive=1", connection, transaction);
    productCommand.Parameters.AddWithValue("@Id", rentalItems[0].RentalProductId);
    string productUnit, category, productCode, productName;
    bool requiresSerial;
    await using (var reader = await productCommand.ExecuteReaderAsync())
    {
        if (!await reader.ReadAsync()) return Results.BadRequest(new { message = "Kiralama ürünü bulunamadı." });
        productUnit = reader.GetString(0);
        category = reader.GetString(1);
        productCode = reader.GetString(2);
        productName = reader.GetString(3);
        requiresSerial = reader.GetBoolean(4);
    }
    if (!string.Equals(productUnit, request.UnitCode, StringComparison.OrdinalIgnoreCase))
        return Results.BadRequest(new { message = "Seçilen ürün bu birime ait değil." });

    foreach (var line in rentalItems)
    {
        var chk = new SqlCommand("SELECT UnitCode FROM dbo.RentalProducts WHERE RentalProductId=@Id AND IsActive=1", connection, transaction);
        chk.Parameters.AddWithValue("@Id",line.RentalProductId);
        var productLineUnit = await chk.ExecuteScalarAsync() as string;
        if (productLineUnit is null || !string.Equals(productLineUnit,request.UnitCode,StringComparison.OrdinalIgnoreCase))
            return Results.BadRequest(new { message = "Ürün kalemlerinden biri geçersiz veya farklı birime ait." });
    }

    var prefix = $"KIR-{DateTime.Now:yyyyMM}-";
    var numberCommand = new SqlCommand(@"
SELECT ISNULL(MAX(TRY_CONVERT(INT,RIGHT(RentalNo,4))),0)+1
FROM dbo.RentalOrders WITH(UPDLOCK,HOLDLOCK)
WHERE RentalNo LIKE @Prefix+'%'", connection, transaction);
    numberCommand.Parameters.AddWithValue("@Prefix", prefix);
    var next = Convert.ToInt32(await numberCommand.ExecuteScalarAsync());
    var rentalNo = $"{prefix}{next:0000}";

    var serialText = JoinRentalSerials(rentalItems[0].SerialNumbers);

    var command = new SqlCommand(@"
INSERT INTO dbo.RentalOrders
(RentalNo,UnitCode,Category,RentalProductId,ProductCode,ProductName,CustomerName,CustomerEmail,ProjectName,Location,ContactName,ContactPhone,Quantity,SerialNumbers,StartDate,EndDate,Status,ResponsibleName,Notes,CreatedByUserId)
OUTPUT INSERTED.RentalOrderId
VALUES(@RentalNo,@Unit,@Category,@ProductId,@ProductCode,@ProductName,@Customer,@Email,@Project,@Location,@ContactName,@ContactPhone,@Quantity,@Serials,@StartDate,@EndDate,N'Talep',@Responsible,@Notes,@UserId)", connection, transaction);
    command.Parameters.AddWithValue("@RentalNo", rentalNo);
    command.Parameters.AddWithValue("@Unit", request.UnitCode);
    command.Parameters.AddWithValue("@Category", category);
    command.Parameters.AddWithValue("@ProductId", rentalItems[0].RentalProductId);
    command.Parameters.AddWithValue("@ProductCode", productCode);
    command.Parameters.AddWithValue("@ProductName", productName);
    command.Parameters.AddWithValue("@Customer", request.CustomerName.Trim());
    command.Parameters.AddWithValue("@Email", Db(request.CustomerEmail));
    command.Parameters.AddWithValue("@Project", Db(request.ProjectName));
    command.Parameters.AddWithValue("@Location", Db(request.Location));
    command.Parameters.AddWithValue("@ContactName", Db(request.ContactName));
    command.Parameters.AddWithValue("@ContactPhone", Db(request.ContactPhone));
    command.Parameters.AddWithValue("@Quantity", rentalItems.Sum(x => x.Quantity));
    command.Parameters.AddWithValue("@Serials", Db(serialText));
    command.Parameters.AddWithValue("@StartDate", request.StartDate.ToDateTime(TimeOnly.MinValue));
    command.Parameters.AddWithValue("@EndDate", request.EndDate.ToDateTime(TimeOnly.MinValue));
    command.Parameters.AddWithValue("@Responsible", Db(request.ResponsibleName));
    command.Parameters.AddWithValue("@Notes", Db(request.Notes));
    command.Parameters.AddWithValue("@UserId", user.UserId);
    var rentalOrderId = Convert.ToInt64(await command.ExecuteScalarAsync());
    await SaveRentalCompositionAsync(connection, transaction, rentalOrderId, rentalItems, rentalContacts);
    await transaction.CommitAsync();

    return Results.Ok(new { rentalOrderId, rentalNo, requiresSerial });
});

app.MapPut("/api/rentals/{id:long}", async (HttpContext ctx, long id, UpdateRentalRequest request) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "rentals.edit")) return Results.Forbid();

    var allowedStatuses = new[] { "Talep","Teklif","Planlama","Hazırlanıyor","Teslimata Hazır","Teslim Edildi","Kirada","İade Bekliyor","İade Alındı","Test / Kontrol","Kapandı","İptal" };
    if (!allowedStatuses.Contains(request.Status)) return Results.BadRequest(new { message = "Geçersiz kiralama durumu." });
    if (request.EndDate < request.StartDate) return Results.BadRequest(new { message = "Bitiş tarihi başlangıç tarihinden önce olamaz." });
    if (request.Quantity <= 0) return Results.BadRequest(new { message = "Adet 1 veya daha büyük olmalı." });

    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();

    var load = new SqlCommand(@"
SELECT r.UnitCode,ISNULL(p.RequiresSerial,0)
FROM dbo.RentalOrders r
LEFT JOIN dbo.RentalProducts p ON p.RentalProductId=r.RentalProductId
WHERE r.RentalOrderId=@Id", connection);
    load.Parameters.AddWithValue("@Id", id);
    string unit;
    bool requiresSerial;
    await using (var reader = await load.ExecuteReaderAsync())
    {
        if (!await reader.ReadAsync()) return Results.NotFound();
        unit = reader.GetString(0);
        requiresSerial = reader.GetBoolean(1);
    }
    if (!UnitAllowed(user, unit)) return Results.Forbid();

    var serialText = request.SerialNumbers is { Count: > 0 } ? string.Join(", ", request.SerialNumbers.Where(x => !string.IsNullOrWhiteSpace(x)).Select(x => x.Trim()).Distinct()) : null;
    if (requiresSerial && (request.Status is "Teslim Edildi" or "Kirada" or "İade Bekliyor" or "İade Alındı" or "Test / Kontrol" or "Kapandı") && string.IsNullOrWhiteSpace(serialText))
        return Results.BadRequest(new { message = "Bu ürün seri numarası ile takip ediliyor. Teslim / kirada / iade / kapanış aşamalarında seri numarası zorunludur." });

    var command = new SqlCommand(@"
UPDATE dbo.RentalOrders
SET CustomerName=@Customer,CustomerEmail=@Email,ProjectName=@Project,Location=@Location,
    ContactName=@ContactName,ContactPhone=@ContactPhone,Quantity=@Quantity,SerialNumbers=@Serials,
    StartDate=@StartDate,EndDate=@EndDate,Status=@Status,ResponsibleName=@Responsible,Notes=@Notes,
    UpdatedAt=SYSDATETIME(),
    ClosedAt=CASE WHEN @Status IN (N'Kapandı',N'İptal') THEN COALESCE(ClosedAt,SYSDATETIME()) ELSE NULL END
WHERE RentalOrderId=@Id", connection);
    command.Parameters.AddWithValue("@Customer", request.CustomerName.Trim());
    command.Parameters.AddWithValue("@Email", Db(request.CustomerEmail));
    command.Parameters.AddWithValue("@Project", Db(request.ProjectName));
    command.Parameters.AddWithValue("@Location", Db(request.Location));
    command.Parameters.AddWithValue("@ContactName", Db(request.ContactName));
    command.Parameters.AddWithValue("@ContactPhone", Db(request.ContactPhone));
    command.Parameters.AddWithValue("@Quantity", request.Quantity);
    command.Parameters.AddWithValue("@Serials", Db(serialText));
    command.Parameters.AddWithValue("@StartDate", request.StartDate.ToDateTime(TimeOnly.MinValue));
    command.Parameters.AddWithValue("@EndDate", request.EndDate.ToDateTime(TimeOnly.MinValue));
    command.Parameters.AddWithValue("@Status", request.Status);
    command.Parameters.AddWithValue("@Responsible", Db(request.ResponsibleName));
    command.Parameters.AddWithValue("@Notes", Db(request.Notes));
    command.Parameters.AddWithValue("@Id", id);
    await command.ExecuteNonQueryAsync();
    return Results.Ok(new { message = "Kiralama kaydı güncellendi." });
});

// V1.12 Kiralama: ürün kalemleri, ilgili kişiler, depo stok ve operasyon aşamaları.
app.MapGet("/api/rentals/{id:long}/details", async (HttpContext ctx,long id) =>
{
    var user=GetCurrentUser(ctx,sessions);
    if(user is null) return Results.Unauthorized();
    if(!Can(user,"rentals.view")) return Results.Forbid();
    await using var con=new SqlConnection(connectionString);await con.OpenAsync();
    var unitCmd=new SqlCommand("SELECT UnitCode FROM dbo.RentalOrders WHERE RentalOrderId=@Id",con);
    unitCmd.Parameters.AddWithValue("@Id",id);
    var unit=await unitCmd.ExecuteScalarAsync() as string;
    if(unit is null) return Results.NotFound();
    if(!UnitAllowed(user,unit)) return Results.Forbid();
    var items=new List<object>();
    var ic=new SqlCommand(@"SELECT i.RentalOrderItemId,i.RentalProductId,p.Category,p.ProductName,i.Quantity,i.SerialNumbers,i.Notes,p.RequiresSerial,
 (SELECT COUNT(*) FROM dbo.RentalInventory inv WHERE inv.RentalOrderItemId=i.RentalOrderItemId) AS AssignedCount
 FROM dbo.RentalOrderItems i JOIN dbo.RentalProducts p ON i.RentalProductId=p.RentalProductId
 WHERE i.RentalOrderId=@Id ORDER BY i.RentalOrderItemId",con);
    ic.Parameters.AddWithValue("@Id",id);
    await using(var rd=await ic.ExecuteReaderAsync()) while(await rd.ReadAsync()) items.Add(new {
        rentalOrderItemId=rd.GetInt64(0),rentalProductId=rd.GetInt32(1),category=rd.GetString(2),productName=rd.GetString(3),
        quantity=rd.GetInt32(4),serialNumbers=rd.IsDBNull(5)?"":rd.GetString(5),notes=rd.IsDBNull(6)?"":rd.GetString(6),
        requiresSerial=rd.GetBoolean(7),assignedCount=rd.GetInt32(8)
    });
    var contacts=new List<object>();
    var cc=new SqlCommand("SELECT RentalOrderContactId,ContactType,FullName,JobTitle,Phone,Email,Notes FROM dbo.RentalOrderContacts WHERE RentalOrderId=@Id ORDER BY RentalOrderContactId",con);
    cc.Parameters.AddWithValue("@Id",id);
    await using(var rd=await cc.ExecuteReaderAsync()) while(await rd.ReadAsync()) contacts.Add(new {
        rentalOrderContactId=rd.GetInt64(0),contactType=rd.GetString(1),fullName=rd.GetString(2),jobTitle=rd.IsDBNull(3)?null:rd.GetString(3),
        phone=rd.IsDBNull(4)?null:rd.GetString(4),email=rd.IsDBNull(5)?null:rd.GetString(5),notes=rd.IsDBNull(6)?null:rd.GetString(6)
    });
    var stages=new List<object>();
    var sc=new SqlCommand(@"SELECT h.RentalStageHistoryId,h.StageName,h.EventAt,h.TeamName,h.RentalWarehouseId,w.Name,h.Notes,u.FullName,h.SerialSnapshot
FROM dbo.RentalStageHistory h LEFT JOIN dbo.RentalWarehouses w ON h.RentalWarehouseId=w.RentalWarehouseId
LEFT JOIN dbo.ErpUsers u ON h.CreatedByUserId=u.UserId
WHERE h.RentalOrderId=@Id ORDER BY h.EventAt,h.RentalStageHistoryId",con);
    sc.Parameters.AddWithValue("@Id",id);
    await using(var rd=await sc.ExecuteReaderAsync()) while(await rd.ReadAsync()) stages.Add(new {
        rentalStageHistoryId=rd.GetInt64(0),stageName=rd.GetString(1),eventAt=rd.GetDateTime(2),
        teamName=rd.IsDBNull(3)?null:rd.GetString(3),rentalWarehouseId=rd.IsDBNull(4)?(int?)null:rd.GetInt32(4),
        warehouseName=rd.IsDBNull(5)?null:rd.GetString(5),notes=rd.IsDBNull(6)?null:rd.GetString(6),
        createdBy=rd.IsDBNull(7)?null:rd.GetString(7),serialSnapshot=rd.IsDBNull(8)?null:rd.GetString(8)
    });
    return Results.Ok(new { items,contacts,stages });
});

app.MapPut("/api/rentals/{id:long}/composition",async (HttpContext ctx,long id,RentalCompositionRequest req)=>
{
    var user=GetCurrentUser(ctx,sessions);
    if(user is null)return Results.Unauthorized();
    if(!Can(user,"rentals.edit"))return Results.Forbid();
    var validation=ValidateRentalComposition(req.Items??new(),req.Contacts??new());
    if(validation is not null)return Results.BadRequest(new {message=validation});
    await using var con=new SqlConnection(connectionString);await con.OpenAsync();
    await using var tx=(SqlTransaction)await con.BeginTransactionAsync();
    var unitCmd=new SqlCommand("SELECT UnitCode FROM dbo.RentalOrders WITH(UPDLOCK) WHERE RentalOrderId=@Id",con,tx);
    unitCmd.Parameters.AddWithValue("@Id",id);
    var unit=await unitCmd.ExecuteScalarAsync() as string;
    if(unit is null)return Results.NotFound();
    if(!UnitAllowed(user,unit))return Results.Forbid();
    foreach(var item in req.Items!)
    {
        var cmd=new SqlCommand("SELECT UnitCode FROM dbo.RentalProducts WHERE RentalProductId=@Id AND IsActive=1",con,tx);
        cmd.Parameters.AddWithValue("@Id",item.RentalProductId);
        if(!string.Equals(await cmd.ExecuteScalarAsync() as string,unit,StringComparison.OrdinalIgnoreCase))
            return Results.BadRequest(new {message="Ürün kalemi bu birime ait değil."});
        if(item.RentalOrderItemId.HasValue)
        {
            var allocated=new SqlCommand(@"SELECT COUNT(*) FROM dbo.RentalInventory inv
JOIN dbo.RentalOrderItems i ON inv.RentalOrderItemId=i.RentalOrderItemId
WHERE i.RentalOrderItemId=@Id AND (i.RentalProductId<>@ProductId OR @Qty < inv.Quantity)",con,tx);
            allocated.Parameters.AddWithValue("@Id",item.RentalOrderItemId.Value);
            allocated.Parameters.AddWithValue("@ProductId",item.RentalProductId);
            allocated.Parameters.AddWithValue("@Qty",item.Quantity);
            if(Convert.ToInt32(await allocated.ExecuteScalarAsync())>0)
                return Results.BadRequest(new {message="Envanter atanmış ürünün modeli veya adedi bu şekilde değiştirilemez."});
        }
    }
    try { await SaveRentalCompositionAsync(con,tx,id,req.Items!,req.Contacts??new()); }
    catch(InvalidOperationException ex){return Results.BadRequest(new {message=ex.Message});}
    var first=req.Items![0];
    var update=new SqlCommand(@"UPDATE r SET RentalProductId=@ProductId,Category=p.Category,ProductCode=p.ProductCode,ProductName=p.ProductName,
Quantity=@Quantity,SerialNumbers=@Serials,UpdatedAt=SYSDATETIME()
FROM dbo.RentalOrders r JOIN dbo.RentalProducts p ON p.RentalProductId=@ProductId WHERE r.RentalOrderId=@OrderId",con,tx);
    update.Parameters.AddWithValue("@ProductId",first.RentalProductId);
    update.Parameters.AddWithValue("@Quantity",req.Items.Sum(x=>x.Quantity));
    update.Parameters.AddWithValue("@Serials",Db(JoinRentalSerials(first.SerialNumbers)));
    update.Parameters.AddWithValue("@OrderId",id);
    await update.ExecuteNonQueryAsync();
    await tx.CommitAsync();
    return Results.Ok(new {message="Ürün kalemleri ve irtibatlar kaydedildi."});
});

app.MapGet("/api/rentals/inventory",async (HttpContext ctx)=>
{
    var user=GetCurrentUser(ctx,sessions);
    if(user is null)return Results.Unauthorized();
    if(!Can(user,"rentals.view")&&!Can(user,"warehouse.view"))return Results.Forbid();
    await using var con=new SqlConnection(connectionString);await con.OpenAsync();
    var warehouses=new List<object>();
    var wc=new SqlCommand("SELECT RentalWarehouseId,Code,Name FROM dbo.RentalWarehouses WHERE IsActive=1 ORDER BY Code",con);
    await using(var rd=await wc.ExecuteReaderAsync())while(await rd.ReadAsync())warehouses.Add(new {rentalWarehouseId=rd.GetInt32(0),code=rd.GetString(1),name=rd.GetString(2)});
    var assets=new List<object>();
    var ac=new SqlCommand(@"SELECT inv.RentalInventoryId,inv.RentalProductId,p.UnitCode,p.Category,p.ProductName,inv.RentalWarehouseId,
 w.Name,inv.SerialNo,inv.Quantity,inv.ConditionStatus,inv.MissingNotes,inv.Notes,inv.RentalOrderItemId,
 r.RentalOrderId,r.RentalNo
FROM dbo.RentalInventory inv JOIN dbo.RentalProducts p ON inv.RentalProductId=p.RentalProductId
JOIN dbo.RentalWarehouses w ON w.RentalWarehouseId=inv.RentalWarehouseId
LEFT JOIN dbo.RentalOrderItems ri ON inv.RentalOrderItemId=ri.RentalOrderItemId
LEFT JOIN dbo.RentalOrders r ON ri.RentalOrderId=r.RentalOrderId
ORDER BY p.UnitCode,p.ProductName,inv.SerialNo",con);
    await using(var rd=await ac.ExecuteReaderAsync())while(await rd.ReadAsync())
    {
        if(!UnitAllowed(user,rd.GetString(2)))continue;
        assets.Add(new {rentalInventoryId=rd.GetInt64(0),rentalProductId=rd.GetInt32(1),unitCode=rd.GetString(2),category=rd.GetString(3),productName=rd.GetString(4),
          rentalWarehouseId=rd.GetInt32(5),warehouseName=rd.GetString(6),serialNo=rd.IsDBNull(7)?null:rd.GetString(7),quantity=rd.GetInt32(8),
          conditionStatus=rd.GetString(9),missingNotes=rd.IsDBNull(10)?null:rd.GetString(10),notes=rd.IsDBNull(11)?null:rd.GetString(11),
          rentalOrderItemId=rd.IsDBNull(12)?(long?)null:rd.GetInt64(12),rentalOrderId=rd.IsDBNull(13)?(long?)null:rd.GetInt64(13),
          rentalNo=rd.IsDBNull(14)?null:rd.GetString(14)});
    }
    return Results.Ok(new {warehouses,assets});
});

app.MapPut("/api/rentals/warehouses/{id:int}",async(HttpContext ctx,int id,RentalWarehouseNameRequest req)=>
{
    var user=GetCurrentUser(ctx,sessions);
    if(user is null)return Results.Unauthorized();
    if(!Can(user,"rentals.edit"))return Results.Forbid();
    if(string.IsNullOrWhiteSpace(req.Name)||req.Name.Length>120)return Results.BadRequest(new {message="Depo adı 1–120 karakter olmalı."});
    await using var con=new SqlConnection(connectionString);await con.OpenAsync();
    var cmd=new SqlCommand("UPDATE dbo.RentalWarehouses SET Name=@Name WHERE RentalWarehouseId=@Id",con);
    cmd.Parameters.AddWithValue("@Name",req.Name.Trim());cmd.Parameters.AddWithValue("@Id",id);
    return await cmd.ExecuteNonQueryAsync()==1?Results.Ok(new {message="Depo adı güncellendi."}):Results.NotFound();
});

app.MapPost("/api/rentals/inventory",async(HttpContext ctx,RentalInventoryRequest req)=>
{
    var user=GetCurrentUser(ctx,sessions);
    if(user is null)return Results.Unauthorized();
    if(!Can(user,"rentals.edit"))return Results.Forbid();
    if(req.Quantity<1 || req.Quantity>10000 || (req.SerialNo?.Length??0)>200 || (req.Notes?.Length??0)>1500 || (req.MissingNotes?.Length??0)>1500)
        return Results.BadRequest(new {message="Adet veya metin uzunluğu geçersiz."});
    if(!new[]{"Hazır","Hazır Değil","Kirada","Kontrolde"}.Contains(req.ConditionStatus))return Results.BadRequest(new {message="Geçersiz cihaz durumu."});
    if(req.ConditionStatus=="Hazır Değil"&&string.IsNullOrWhiteSpace(req.MissingNotes))return Results.BadRequest(new {message="Hazır olmayan cihazın eksiğini yazın."});
    await using var con=new SqlConnection(connectionString);await con.OpenAsync();
    var pc=new SqlCommand("SELECT UnitCode,RequiresSerial FROM dbo.RentalProducts WHERE RentalProductId=@Id AND IsActive=1",con);
    pc.Parameters.AddWithValue("@Id",req.RentalProductId);
    string unit;bool serialRequired;
    await using(var rd=await pc.ExecuteReaderAsync())
    {if(!await rd.ReadAsync())return Results.BadRequest(new {message="Ürün bulunamadı."});unit=rd.GetString(0);serialRequired=rd.GetBoolean(1);}
    if(!UnitAllowed(user,unit))return Results.Forbid();
    if(serialRequired&&(string.IsNullOrWhiteSpace(req.SerialNo)||req.Quantity!=1))
        return Results.BadRequest(new {message="Seri takipli ürünler tek tek, seri numarası ile girilmelidir."});
    var wh=new SqlCommand("SELECT COUNT(*) FROM dbo.RentalWarehouses WHERE RentalWarehouseId=@Id AND IsActive=1",con);
    wh.Parameters.AddWithValue("@Id",req.RentalWarehouseId);
    if(Convert.ToInt32(await wh.ExecuteScalarAsync())==0)return Results.BadRequest(new {message="Depo seçimi geçersiz."});
    if(req.RentalInventoryId.HasValue)
    {
        var old=new SqlCommand("SELECT COUNT(*) FROM dbo.RentalInventory WHERE RentalInventoryId=@Id AND RentalOrderItemId IS NOT NULL",con);
        old.Parameters.AddWithValue("@Id",req.RentalInventoryId.Value);
        if(Convert.ToInt32(await old.ExecuteScalarAsync())>0)return Results.BadRequest(new {message="Kiralama işine atanmış cihazı önce işlem üzerinden serbest bırakın."});
    }
    var cmd=new SqlCommand(req.RentalInventoryId.HasValue?@"UPDATE dbo.RentalInventory
SET RentalProductId=@Prod,RentalWarehouseId=@Wh,SerialNo=@Serial,Quantity=@Qty,ConditionStatus=@Status,
MissingNotes=@Missing,Notes=@Notes,UpdatedAt=SYSDATETIME()
WHERE RentalInventoryId=@Id":@"INSERT INTO dbo.RentalInventory
(RentalProductId,RentalWarehouseId,SerialNo,Quantity,ConditionStatus,MissingNotes,Notes)
VALUES(@Prod,@Wh,@Serial,@Qty,@Status,@Missing,@Notes)",con);
    if(req.RentalInventoryId.HasValue)cmd.Parameters.AddWithValue("@Id",req.RentalInventoryId.Value);
    cmd.Parameters.AddWithValue("@Prod",req.RentalProductId);cmd.Parameters.AddWithValue("@Wh",req.RentalWarehouseId);
    cmd.Parameters.AddWithValue("@Serial",Db(req.SerialNo?.Trim()));cmd.Parameters.AddWithValue("@Qty",req.Quantity);
    cmd.Parameters.AddWithValue("@Status",req.ConditionStatus);cmd.Parameters.AddWithValue("@Missing",Db(req.MissingNotes));
    cmd.Parameters.AddWithValue("@Notes",Db(req.Notes));
    try{return await cmd.ExecuteNonQueryAsync()==1?Results.Ok(new {message="Envanter kaydedildi."}):Results.NotFound();}
    catch(SqlException ex) when(ex.Number is 2601 or 2627){return Results.Conflict(new {message="Bu ürünün seri numarası envanterde zaten kayıtlı."});}
});

app.MapPost("/api/rentals/{id:long}/allocate",async(HttpContext ctx,long id,RentalAssetAllocationRequest req)=>
{
    var user=GetCurrentUser(ctx,sessions);
    if(user is null)return Results.Unauthorized();
    if(!Can(user,"rentals.edit"))return Results.Forbid();
    var assetIds=(req.RentalInventoryIds??new()).Distinct().ToList();
    if(assetIds.Count>1000)return Results.BadRequest(new {message="Çok fazla cihaz seçildi."});
    await using var con=new SqlConnection(connectionString);await con.OpenAsync();
    await using var tx=(SqlTransaction)await con.BeginTransactionAsync(System.Data.IsolationLevel.Serializable);
    var itemcmd=new SqlCommand(@"SELECT r.UnitCode,i.RentalProductId,i.Quantity FROM dbo.RentalOrderItems i
JOIN dbo.RentalOrders r ON i.RentalOrderId=r.RentalOrderId
WHERE i.RentalOrderItemId=@ItemId AND i.RentalOrderId=@OrderId",con,tx);
    itemcmd.Parameters.AddWithValue("@ItemId",req.RentalOrderItemId);itemcmd.Parameters.AddWithValue("@OrderId",id);
    string unit;int productId,quantity;
    await using(var rd=await itemcmd.ExecuteReaderAsync())
    {if(!await rd.ReadAsync())return Results.NotFound();unit=rd.GetString(0);productId=rd.GetInt32(1);quantity=rd.GetInt32(2);}
    if(!UnitAllowed(user,unit))return Results.Forbid();
    var oldcmd=new SqlCommand("SELECT RentalInventoryId,ConditionStatus FROM dbo.RentalInventory WITH(UPDLOCK) WHERE RentalOrderItemId=@ItemId",con,tx);
    oldcmd.Parameters.AddWithValue("@ItemId",req.RentalOrderItemId);
    var previous=new List<(long Id,string Status)>();
    await using(var rd=await oldcmd.ExecuteReaderAsync())while(await rd.ReadAsync())previous.Add((rd.GetInt64(0),rd.GetString(1)));
    if(previous.Any(x=>x.Status=="Kirada") && (previous.Count!=assetIds.Count || previous.Any(x=>!assetIds.Contains(x.Id))))
        return Results.BadRequest(new {message="Sevk edilmiş cihazların ataması depo dönüşü tamamlanmadan değiştirilemez."});
    var available=new List<(long Id,int Qty)>();
    foreach(var assetId in assetIds)
    {
        var c=new SqlCommand(@"SELECT RentalProductId,Quantity,ConditionStatus,RentalOrderItemId FROM dbo.RentalInventory WITH(UPDLOCK,HOLDLOCK) WHERE RentalInventoryId=@Id",con,tx);
        c.Parameters.AddWithValue("@Id",assetId);
        await using var rd=await c.ExecuteReaderAsync();
        if(!await rd.ReadAsync())return Results.BadRequest(new {message="Envanter cihazı bulunamadı."});
        var p=rd.GetInt32(0);var q=rd.GetInt32(1);var status=rd.GetString(2);
        var assigned=rd.IsDBNull(3)?(long?)null:rd.GetInt64(3);
        if(p!=productId||status is not ("Hazır" or "Kirada")|| (status=="Kirada"&&assigned!=req.RentalOrderItemId) || (assigned.HasValue&&assigned!=req.RentalOrderItemId))
            return Results.BadRequest(new {message="Seçilen cihaz başka işte, hazır değil veya farklı ürün modelinde."});
        available.Add((assetId,q));
    }
    if(available.Sum(x=>x.Qty)>quantity)return Results.BadRequest(new {message="Atanan stok adedi kiralama kalemi miktarını aşıyor."});
    var clear=new SqlCommand("UPDATE dbo.RentalInventory SET RentalOrderItemId=NULL,UpdatedAt=SYSDATETIME() WHERE RentalOrderItemId=@ItemId AND ConditionStatus=N'Hazır'",con,tx);
    clear.Parameters.AddWithValue("@ItemId",req.RentalOrderItemId);await clear.ExecuteNonQueryAsync();
    foreach(var a in available)
    {
        var c=new SqlCommand("UPDATE dbo.RentalInventory SET RentalOrderItemId=@ItemId,UpdatedAt=SYSDATETIME() WHERE RentalInventoryId=@Id",con,tx);
        c.Parameters.AddWithValue("@ItemId",req.RentalOrderItemId);c.Parameters.AddWithValue("@Id",a.Id);await c.ExecuteNonQueryAsync();
    }
    if(available.Count>0)
    {
        var serialCmd=new SqlCommand("SELECT SerialNo FROM dbo.RentalInventory WHERE RentalOrderItemId=@ItemId AND SerialNo IS NOT NULL ORDER BY RentalInventoryId",con,tx);
        serialCmd.Parameters.AddWithValue("@ItemId",req.RentalOrderItemId);
        var serials=new List<string>();
        await using(var rd=await serialCmd.ExecuteReaderAsync())while(await rd.ReadAsync())serials.Add(rd.GetString(0));
        if(serials.Count>0)
        {
            var set=new SqlCommand("UPDATE dbo.RentalOrderItems SET SerialNumbers=@Serials WHERE RentalOrderItemId=@Id",con,tx);
            set.Parameters.AddWithValue("@Serials",string.Join(", ",serials));set.Parameters.AddWithValue("@Id",req.RentalOrderItemId);
            await set.ExecuteNonQueryAsync();
        }
    }
    await tx.CommitAsync();return Results.Ok(new {message="Envanter cihazları kaleme atandı."});
});

app.MapPost("/api/rentals/{id:long}/stage",async(HttpContext ctx,long id,RentalStageRequest req)=>
{
    var user=GetCurrentUser(ctx,sessions);
    if(user is null)return Results.Unauthorized();
    if(!Can(user,"rentals.edit"))return Results.Forbid();
    var stages=new[]{"Sevk Edildi","Kurulum Yapıldı","Devreye Alındı","Toplandı","Depoya Alındı"};
    if(!stages.Contains(req.StageName))return Results.BadRequest(new {message="Geçersiz operasyon aşaması."});
    if(req.EventAt>DateTime.Now.AddDays(1)||req.EventAt<DateTime.Now.AddYears(-10))return Results.BadRequest(new {message="Aşama tarihi geçersiz."});
    if(req.StageName=="Depoya Alındı"&&!req.RentalWarehouseId.HasValue)return Results.BadRequest(new {message="Depoya alınırken depo seçilmelidir."});
    await using var con=new SqlConnection(connectionString);await con.OpenAsync();
    await using var tx=(SqlTransaction)await con.BeginTransactionAsync();
    var cmdUnit=new SqlCommand("SELECT UnitCode FROM dbo.RentalOrders WHERE RentalOrderId=@Id",con,tx);
    cmdUnit.Parameters.AddWithValue("@Id",id);var unit=await cmdUnit.ExecuteScalarAsync() as string;
    if(unit is null)return Results.NotFound();if(!UnitAllowed(user,unit))return Results.Forbid();
    if(req.RentalWarehouseId.HasValue)
    {
        var wh=new SqlCommand("SELECT COUNT(*) FROM dbo.RentalWarehouses WHERE RentalWarehouseId=@Id",con,tx);
        wh.Parameters.AddWithValue("@Id",req.RentalWarehouseId.Value);
        if(Convert.ToInt32(await wh.ExecuteScalarAsync())==0)return Results.BadRequest(new {message="Depo bulunamadı."});
    }
    var step=new SqlCommand(@"INSERT INTO dbo.RentalStageHistory
(RentalOrderId,StageName,EventAt,TeamName,RentalWarehouseId,Notes,SerialSnapshot,CreatedByUserId)
VALUES(@OrderId,@Stage,@Time,@Team,@Wh,@Notes,
(SELECT STRING_AGG(CONVERT(NVARCHAR(MAX),i.SerialNumbers),N'; ') FROM dbo.RentalOrderItems i WHERE i.RentalOrderId=@OrderId),@UserId)",con,tx);
    step.Parameters.AddWithValue("@OrderId",id);step.Parameters.AddWithValue("@Stage",req.StageName);
    step.Parameters.AddWithValue("@Time",req.EventAt);step.Parameters.AddWithValue("@Team",Db(req.TeamName));
    step.Parameters.AddWithValue("@Wh",req.RentalWarehouseId.HasValue?(object)req.RentalWarehouseId.Value:DBNull.Value);
    step.Parameters.AddWithValue("@Notes",Db(req.Notes));step.Parameters.AddWithValue("@UserId",user.UserId);
    await step.ExecuteNonQueryAsync();
    if(req.StageName=="Sevk Edildi")
    {
        var inv=new SqlCommand(@"UPDATE inv SET ConditionStatus=N'Kirada',UpdatedAt=SYSDATETIME()
FROM dbo.RentalInventory inv JOIN dbo.RentalOrderItems line ON inv.RentalOrderItemId=line.RentalOrderItemId
WHERE line.RentalOrderId=@Id AND inv.ConditionStatus=N'Hazır'",con,tx);
        inv.Parameters.AddWithValue("@Id",id);await inv.ExecuteNonQueryAsync();
    }
    if(req.StageName=="Depoya Alındı")
    {
        var inv=new SqlCommand(@"UPDATE inv SET RentalWarehouseId=@Wh,ConditionStatus=N'Kontrolde',
RentalOrderItemId=NULL,UpdatedAt=SYSDATETIME()
FROM dbo.RentalInventory inv JOIN dbo.RentalOrderItems line ON inv.RentalOrderItemId=line.RentalOrderItemId
WHERE line.RentalOrderId=@Id",con,tx);
        inv.Parameters.AddWithValue("@Id",id);inv.Parameters.AddWithValue("@Wh",req.RentalWarehouseId!.Value);
        await inv.ExecuteNonQueryAsync();
    }
    await tx.CommitAsync();return Results.Ok(new {message="Operasyon aşaması kaydedildi."});
});

// V1.13 | Egitim, yetkinlik, saha gozlem ve gelisim takibi.
app.MapGet("/api/training/overview", async (HttpContext ctx, int? year) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "training.view")) return Results.Forbid();
    var y = year is >= 2020 and <= 2100 ? year.Value : DateTime.Today.Year;
    var all = IsAdmin(user) || user.AllowedUnits.Count == 0;
    var units = "|" + JoinPipe(user.AllowedUnits) + "|";
    await using var db = new SqlConnection(connectionString);
    await db.OpenAsync();
    const string access = "(@All=1 OR (p.UnitCode IS NOT NULL AND CHARINDEX(N'|' + p.UnitCode + N'|', @Units)>0))";
    async Task<List<Dictionary<string,object?>>> Query(string sql, bool needsScope=false, bool needsYear=false)
    {
        await using var cmd = new SqlCommand(sql,db);
        if (needsScope) { cmd.Parameters.AddWithValue("@All",all); cmd.Parameters.AddWithValue("@Units",units); }
        if (needsYear) cmd.Parameters.AddWithValue("@Year",y);
        return await TrainingRowsAsync(cmd);
    }
    var people=await Query($@"SELECT p.PersonnelId AS personnelId,p.FullName AS fullName,p.UnitCode AS unitCode,p.Title AS title,p.DepartmentName AS departmentName,p.ManagerName AS managerName
FROM dbo.Personnel p WHERE p.IsActive=1 AND {access} ORDER BY p.FullName",true);
    var courses=await Query(@"SELECT CourseId AS courseId,CourseCode AS courseCode,Title AS title,Category AS category,UnitCode AS unitCode,
Reason AS reason,TargetBehavior AS targetBehavior,SuccessMetric AS successMetric,DurationHours AS durationHours,Mandatory AS mandatory,IsActive AS isActive
FROM dbo.TrainingCourses WHERE (@All=1 OR UnitCode IS NULL OR CHARINDEX(N'|' + UnitCode + N'|', @Units)>0) ORDER BY Category,Title",true);
    var criteria=await Query(@"SELECT CriterionId AS criterionId,CourseId AS courseId,CriterionText AS criterionText,IsCritical AS isCritical,SortOrder AS sortOrder
FROM dbo.TrainingCriteria WHERE CourseId IN (SELECT CourseId FROM dbo.TrainingCourses WHERE (@All=1 OR UnitCode IS NULL OR CHARINDEX(N'|' + UnitCode + N'|', @Units)>0)) ORDER BY CourseId,SortOrder",true);
    var plans=await Query($@"SELECT pl.TrainingPlanId AS trainingPlanId,pl.PersonnelId AS personnelId,pl.CourseId AS courseId,pl.PlanYear AS planYear,
pl.DueDate AS dueDate,pl.Status AS status,pl.PersonalGoal AS personalGoal,pl.CompletedAt AS completedAt
FROM dbo.TrainingPlans pl JOIN dbo.Personnel p ON p.PersonnelId=pl.PersonnelId
WHERE pl.PlanYear=@Year AND {access} ORDER BY pl.DueDate,p.FullName",true,true);
    var carryoverPlans=await Query($@"SELECT pl.TrainingPlanId AS trainingPlanId,pl.PersonnelId AS personnelId,pl.CourseId AS courseId,pl.PlanYear AS planYear,
pl.DueDate AS dueDate,pl.Status AS status,pl.PersonalGoal AS personalGoal,pl.CompletedAt AS completedAt
FROM dbo.TrainingPlans pl JOIN dbo.Personnel p ON p.PersonnelId=pl.PersonnelId
WHERE pl.PlanYear=@Year-1 AND pl.Status=N'Tamamlandı' AND {access}",true,true);
    var sessionsList=await Query(@"SELECT s.TrainingSessionId AS trainingSessionId,s.CourseId AS courseId,s.SessionDate AS sessionDate,s.TrainerName AS trainerName,
s.DurationHours AS durationHours,s.Location AS location,s.Notes AS notes FROM dbo.TrainingSessions s JOIN dbo.TrainingCourses c ON c.CourseId=s.CourseId WHERE YEAR(s.SessionDate)=@Year AND (@All=1 OR c.UnitCode IS NULL OR CHARINDEX(N'|' + c.UnitCode + N'|', @Units)>0) ORDER BY s.SessionDate DESC",true,true);
    var attendance=await Query($@"SELECT a.TrainingAttendanceId AS trainingAttendanceId,a.TrainingSessionId AS trainingSessionId,a.PersonnelId AS personnelId,
a.Attended AS attended,a.ScoreBefore AS scoreBefore,a.ScoreAfter AS scoreAfter,a.Notes AS notes
FROM dbo.TrainingAttendance a JOIN dbo.TrainingSessions s ON s.TrainingSessionId=a.TrainingSessionId
JOIN dbo.Personnel p ON p.PersonnelId=a.PersonnelId WHERE YEAR(s.SessionDate)=@Year AND {access}",true,true);
    var competencies=await Query(@"SELECT CompetencyId AS competencyId,Code AS code,Name AS name,UnitCode AS unitCode,
SuggestedTargetLevel AS suggestedTargetLevel,IsCritical AS isCritical FROM dbo.CompetencyCatalog WHERE (@All=1 OR UnitCode IS NULL OR CHARINDEX(N'|' + UnitCode + N'|', @Units)>0) ORDER BY UnitCode,Name",true);
    var levels=await Query($@"SELECT c.PersonnelCompetencyId AS personnelCompetencyId,c.PersonnelId AS personnelId,c.CompetencyId AS competencyId,
c.CurrentLevel AS currentLevel,c.TargetLevel AS targetLevel,c.AssessedAt AS assessedAt,c.AssessedBy AS assessedBy,
c.Evidence AS evidence,c.NextReviewDate AS nextReviewDate
FROM dbo.PersonnelCompetencies c JOIN dbo.Personnel p ON p.PersonnelId=c.PersonnelId WHERE {access}",true);
    var observations=await Query($@"SELECT o.ObservationId AS observationId,o.PersonnelId AS personnelId,o.CourseId AS courseId,
o.WorkOrderId AS workOrderId,o.ObservedOn AS observedOn,o.ObserverName AS observerName,o.PhaseDays AS phaseDays,
o.Score AS score,o.CriticalFailure AS criticalFailure,o.Notes AS notes,o.ActionPlan AS actionPlan,o.NextReviewDate AS nextReviewDate
FROM dbo.TrainingObservations o JOIN dbo.Personnel p ON p.PersonnelId=o.PersonnelId WHERE YEAR(o.ObservedOn) BETWEEN @Year-1 AND @Year+1 AND {access}
ORDER BY o.ObservedOn DESC,o.ObservationId DESC",true,true);
    return Results.Ok(new { year=y, people,courses,criteria,plans,carryoverPlans,sessions=sessionsList,attendance,competencies,levels,observations });
});

app.MapPost("/api/training/courses",async(HttpContext ctx,TrainingCourseRequest req)=>
{
    var user=GetCurrentUser(ctx,sessions);if(user is null)return Results.Unauthorized();if(!Can(user,"training.manage"))return Results.Forbid();
    if(string.IsNullOrWhiteSpace(req.Code)||string.IsNullOrWhiteSpace(req.Title)||req.DurationHours<=0||req.DurationHours>24)return Results.BadRequest(new{message="Eğitim kodu, başlığı ve 0–24 saat arası süresi zorunludur."});
    if(!string.IsNullOrWhiteSpace(req.UnitCode)&&!UnitAllowed(user,req.UnitCode))return Results.Forbid();
    await using var db=new SqlConnection(connectionString);await db.OpenAsync();
    var criteria=(req.Checklist??"").Split('\n',StringSplitOptions.RemoveEmptyEntries|StringSplitOptions.TrimEntries)
        .Where(line=>!string.IsNullOrWhiteSpace(line)).Select((line,i)=>new { Text=line.TrimStart('!',' ','*','-').Trim(),Critical=line.StartsWith('!'),Order=i+1 }).ToList();
    if(criteria.Count==0||criteria.Count>30||criteria.Any(c=>c.Text.Length==0||c.Text.Length>450))
        return Results.BadRequest(new{message="Her eğitim için 1–30 saha kontrol maddesi tanımlayın. Kritik maddeleri ! ile başlatın."});
    await using var tx=(SqlTransaction)await db.BeginTransactionAsync();
    await using var cmd=new SqlCommand(@"INSERT dbo.TrainingCourses(CourseCode,Title,Category,UnitCode,Reason,TargetBehavior,SuccessMetric,DurationHours,Mandatory)
OUTPUT INSERTED.CourseId VALUES(@Code,@Title,@Category,@Unit,@Reason,@Behavior,@Metric,@Hours,@Mandatory)",db,tx);
    cmd.Parameters.AddWithValue("@Code",req.Code.Trim());cmd.Parameters.AddWithValue("@Title",req.Title.Trim());
    cmd.Parameters.AddWithValue("@Category",string.IsNullOrWhiteSpace(req.Category)?"Gelişim":req.Category.Trim());
    cmd.Parameters.AddWithValue("@Unit",Db(req.UnitCode));cmd.Parameters.AddWithValue("@Reason",Db(req.Reason));
    cmd.Parameters.AddWithValue("@Behavior",Db(req.TargetBehavior));cmd.Parameters.AddWithValue("@Metric",Db(req.SuccessMetric));
    cmd.Parameters.AddWithValue("@Hours",req.DurationHours);cmd.Parameters.AddWithValue("@Mandatory",req.Mandatory);
    try
    {
       var id=Convert.ToInt32(await cmd.ExecuteScalarAsync());
       foreach(var c in criteria)
       {
          await using var add=new SqlCommand("INSERT dbo.TrainingCriteria(CourseId,CriterionText,IsCritical,SortOrder) VALUES(@Id,@Text,@Critical,@Sort)",db,tx);
          add.Parameters.AddWithValue("@Id",id);add.Parameters.AddWithValue("@Text",c.Text);
          add.Parameters.AddWithValue("@Critical",c.Critical);add.Parameters.AddWithValue("@Sort",c.Order);
          await add.ExecuteNonQueryAsync();
       }
       await tx.CommitAsync();return Results.Ok(new{courseId=id});
    }
    catch(SqlException ex) when(ex.Number is 2601 or 2627){await tx.RollbackAsync();return Results.Conflict(new{message="Eğitim kodu zaten kayıtlı."});}
});

app.MapPost("/api/training/plans/bulk",async(HttpContext ctx,TrainingPlanBulkRequest req)=>
{
    var user=GetCurrentUser(ctx,sessions);if(user is null)return Results.Unauthorized();if(!Can(user,"training.manage"))return Results.Forbid();
    if(req.PersonnelIds is null||req.PersonnelIds.Count==0||req.PersonnelIds.Count>300||req.PlanYear<2020||req.PlanYear>2100||req.DueDate.Year!=req.PlanYear)
        return Results.BadRequest(new{message="Personel, plan yılı ve aynı yıl içinde hedef tarih gerekli."});
    await using var db=new SqlConnection(connectionString);await db.OpenAsync();
    await using var course=new SqlCommand("SELECT UnitCode FROM dbo.TrainingCourses WHERE CourseId=@Id AND IsActive=1",db);
    course.Parameters.AddWithValue("@Id",req.CourseId);var unit=await course.ExecuteScalarAsync();
    if(unit is null)return Results.BadRequest(new{message="Eğitim bulunamadı."});
    if(unit!=DBNull.Value&&!UnitAllowed(user,(string)unit))return Results.Forbid();
    // Tüm seçili personelin rol/birim yetkisi önce kontrol edilir; kısmi kayıt yoktur.
    foreach(var personId in req.PersonnelIds.Distinct())
       if(!await TrainingCanAccessPersonnelAsync(db,user,personId))return Results.Forbid();
    await using var tx=(SqlTransaction)await db.BeginTransactionAsync();
    var created=0;
    foreach(var personId in req.PersonnelIds.Distinct())
    {
       await using var cmd=new SqlCommand(@"INSERT INTO dbo.TrainingPlans(PersonnelId,CourseId,PlanYear,DueDate,PersonalGoal)
SELECT @Person,@Course,@Year,@Due,@Goal WHERE NOT EXISTS
(SELECT 1 FROM dbo.TrainingPlans WITH(UPDLOCK,HOLDLOCK) WHERE PersonnelId=@Person AND CourseId=@Course AND PlanYear=@Year)",db,tx);
       cmd.Parameters.AddWithValue("@Person",personId);cmd.Parameters.AddWithValue("@Course",req.CourseId);
       cmd.Parameters.AddWithValue("@Year",req.PlanYear);cmd.Parameters.AddWithValue("@Due",req.DueDate.ToDateTime(TimeOnly.MinValue));
       cmd.Parameters.AddWithValue("@Goal",Db(req.PersonalGoal));created+=await cmd.ExecuteNonQueryAsync();
    }
    await tx.CommitAsync();return Results.Ok(new{created,message=$"{created} yıllık gelişim hedefi eklendi. Mevcut planlar korunmuştur."});
});

app.MapPost("/api/training/sessions",async(HttpContext ctx,TrainingSessionRequest req)=>
{
    var user=GetCurrentUser(ctx,sessions);if(user is null)return Results.Unauthorized();if(!Can(user,"training.manage"))return Results.Forbid();
    if(req.DurationHours<=0||req.DurationHours>24||string.IsNullOrWhiteSpace(req.TrainerName))return Results.BadRequest(new{message="Eğitmen ve geçerli eğitim süresi zorunludur."});
    await using var db=new SqlConnection(connectionString);await db.OpenAsync();
    await using var cmd=new SqlCommand(@"INSERT dbo.TrainingSessions(CourseId,SessionDate,TrainerName,DurationHours,Location,Notes)
OUTPUT INSERTED.TrainingSessionId VALUES(@Course,@Date,@Trainer,@Hours,@Location,@Notes)",db);
    cmd.Parameters.AddWithValue("@Course",req.CourseId);cmd.Parameters.AddWithValue("@Date",req.SessionDate.ToDateTime(TimeOnly.MinValue));
    cmd.Parameters.AddWithValue("@Trainer",req.TrainerName.Trim());cmd.Parameters.AddWithValue("@Hours",req.DurationHours);
    cmd.Parameters.AddWithValue("@Location",Db(req.Location));cmd.Parameters.AddWithValue("@Notes",Db(req.Notes));
    try {var id=Convert.ToInt64(await cmd.ExecuteScalarAsync());return Results.Ok(new{trainingSessionId=id});}
    catch(SqlException ex) when(ex.Number==547){return Results.BadRequest(new{message="Eğitim bulunamadı."});}
});

app.MapPost("/api/training/attendance",async(HttpContext ctx,TrainingAttendanceRequest req)=>
{
    var user=GetCurrentUser(ctx,sessions);if(user is null)return Results.Unauthorized();if(!Can(user,"training.manage"))return Results.Forbid();
    if(req.ScoreBefore is <0 or >100 || req.ScoreAfter is <0 or >100)return Results.BadRequest(new{message="Puan 0–100 aralığında olmalı."});
    await using var db=new SqlConnection(connectionString);await db.OpenAsync();
    if(!await TrainingCanAccessPersonnelAsync(db,user,req.PersonnelId))return Results.Forbid();
    await using(var sessionCmd=new SqlCommand("SELECT c.UnitCode FROM dbo.TrainingSessions s JOIN dbo.TrainingCourses c ON c.CourseId=s.CourseId WHERE s.TrainingSessionId=@Id",db))
    {
        sessionCmd.Parameters.AddWithValue("@Id",req.TrainingSessionId);
        var courseUnit=await sessionCmd.ExecuteScalarAsync();
        if(courseUnit is null)return Results.BadRequest(new{message="Eğitim oturumu bulunamadı."});
        if(courseUnit!=DBNull.Value&&!UnitAllowed(user,(string)courseUnit))return Results.Forbid();
    }
    await using var tx=(SqlTransaction)await db.BeginTransactionAsync();
    await using var cmd=new SqlCommand(@"MERGE dbo.TrainingAttendance WITH(HOLDLOCK) AS target
USING (SELECT @Session AS TrainingSessionId,@Person AS PersonnelId) s
ON target.TrainingSessionId=s.TrainingSessionId AND target.PersonnelId=s.PersonnelId
WHEN MATCHED THEN UPDATE SET Attended=@Attended,ScoreBefore=@Before,ScoreAfter=@After,Notes=@Notes
WHEN NOT MATCHED THEN INSERT(TrainingSessionId,PersonnelId,Attended,ScoreBefore,ScoreAfter,Notes)
VALUES(@Session,@Person,@Attended,@Before,@After,@Notes);",db,tx);
    cmd.Parameters.AddWithValue("@Session",req.TrainingSessionId);cmd.Parameters.AddWithValue("@Person",req.PersonnelId);
    cmd.Parameters.AddWithValue("@Attended",req.Attended);cmd.Parameters.AddWithValue("@Before",(object?)req.ScoreBefore??DBNull.Value);
    cmd.Parameters.AddWithValue("@After",(object?)req.ScoreAfter??DBNull.Value);cmd.Parameters.AddWithValue("@Notes",Db(req.Notes));
    try{await cmd.ExecuteNonQueryAsync();}
    catch(SqlException ex) when(ex.Number==547){await tx.RollbackAsync();return Results.BadRequest(new{message="Personel veya eğitim oturumu bulunamadı."});}
    // Katılım durumu: katılım yoksa mevcut tamamlanan geçmiş silinmez.
    if(req.Attended)
    {
      await using var upd=new SqlCommand(@"UPDATE pl SET pl.Status=N'Tamamlandı',pl.CompletedAt=CAST(s.SessionDate AS DATETIME2)
FROM dbo.TrainingPlans pl JOIN dbo.TrainingSessions s ON s.CourseId=pl.CourseId
WHERE s.TrainingSessionId=@Session AND pl.PersonnelId=@Person AND pl.PlanYear=YEAR(s.SessionDate) AND pl.Status<>N'Tamamlandı'",db,tx);
      upd.Parameters.AddWithValue("@Session",req.TrainingSessionId);upd.Parameters.AddWithValue("@Person",req.PersonnelId);
      await upd.ExecuteNonQueryAsync();
    }
    await tx.CommitAsync();return Results.Ok(new{message="Eğitim katılımı ve ölçüm kaydedildi."});
});

app.MapPost("/api/training/competencies",async(HttpContext ctx,TrainingCompetencyRequest req)=>
{
    var user=GetCurrentUser(ctx,sessions);if(user is null)return Results.Unauthorized();if(!Can(user,"training.manage")&&!Can(user,"training.observe"))return Results.Forbid();
    if(req.CurrentLevel is <1 or >4 || req.TargetLevel is <1 or >4)return Results.BadRequest(new{message="Yetkinlik 1–4 arasında olmalı."});
    await using var db=new SqlConnection(connectionString);await db.OpenAsync();
    if(!await TrainingCanAccessPersonnelAsync(db,user,req.PersonnelId))return Results.Forbid();
    await using var cmd=new SqlCommand(@"MERGE dbo.PersonnelCompetencies WITH(HOLDLOCK) AS t
USING (SELECT @Person AS PersonnelId,@Competency AS CompetencyId) s ON t.PersonnelId=s.PersonnelId AND t.CompetencyId=s.CompetencyId
WHEN MATCHED THEN UPDATE SET CurrentLevel=@Level,TargetLevel=@Target,AssessedAt=@Date,AssessedBy=@By,Evidence=@Evidence,NextReviewDate=@Next,UpdatedAt=SYSDATETIME()
WHEN NOT MATCHED THEN INSERT(PersonnelId,CompetencyId,CurrentLevel,TargetLevel,AssessedAt,AssessedBy,Evidence,NextReviewDate)
VALUES(@Person,@Competency,@Level,@Target,@Date,@By,@Evidence,@Next);",db);
    cmd.Parameters.AddWithValue("@Person",req.PersonnelId);cmd.Parameters.AddWithValue("@Competency",req.CompetencyId);
    cmd.Parameters.AddWithValue("@Level",req.CurrentLevel);cmd.Parameters.AddWithValue("@Target",req.TargetLevel);
    cmd.Parameters.AddWithValue("@Date",req.AssessedAt.ToDateTime(TimeOnly.MinValue));cmd.Parameters.AddWithValue("@By",user.FullName);
    cmd.Parameters.AddWithValue("@Evidence",Db(req.Evidence));cmd.Parameters.AddWithValue("@Next",(object?)req.NextReviewDate?.ToDateTime(TimeOnly.MinValue)??DBNull.Value);
    try{await cmd.ExecuteNonQueryAsync();return Results.Ok(new{message="Yetkinlik kaydedildi."});}
    catch(SqlException ex) when(ex.Number==547){return Results.BadRequest(new{message="Yetkinlik başlığı bulunamadı."});}
});

app.MapPost("/api/training/observations",async(HttpContext ctx,TrainingObservationRequest req)=>
{
    var user=GetCurrentUser(ctx,sessions);if(user is null)return Results.Unauthorized();if(!Can(user,"training.observe")&&!Can(user,"training.manage"))return Results.Forbid();
    if(req.PhaseDays is not (0 or 30 or 60 or 90)||req.Ratings is null||req.Ratings.Count==0||req.Ratings.Select(x=>x.CriterionId).Distinct().Count()!=req.Ratings.Count)
        return Results.BadRequest(new{message="Geçerli gözlem aşaması ve kontrol maddeleri gerekli."});
    if(req.Ratings.Any(x=>x.Rating is < -1 or > 2)||req.Ratings.All(x=>x.Rating==-1))
        return Results.BadRequest(new{message="En az bir kontrol maddesini değerlendirin."});
    await using var db=new SqlConnection(connectionString);await db.OpenAsync();
    if(!await TrainingCanAccessPersonnelAsync(db,user,req.PersonnelId))return Results.Forbid();
    await using(var ccmd=new SqlCommand("SELECT UnitCode FROM dbo.TrainingCourses WHERE CourseId=@Id",db))
    {
        ccmd.Parameters.AddWithValue("@Id",req.CourseId);
        var courseUnit=await ccmd.ExecuteScalarAsync();
        if(courseUnit is null)return Results.BadRequest(new{message="Eğitim bulunamadı."});
        if(courseUnit!=DBNull.Value&&!UnitAllowed(user,(string)courseUnit))return Results.Forbid();
    }
    await using var check=new SqlCommand("SELECT CriterionId,IsCritical FROM dbo.TrainingCriteria WHERE CourseId=@Course",db);
    check.Parameters.AddWithValue("@Course",req.CourseId);
    var known=new Dictionary<int,bool>();await using(var reader=await check.ExecuteReaderAsync())while(await reader.ReadAsync())known[reader.GetInt32(0)]=reader.GetBoolean(1);
    if(known.Count==0||req.Ratings.Any(x=>!known.ContainsKey(x.CriterionId)))return Results.BadRequest(new{message="Eğitime uygun olmayan kontrol maddeleri seçildi."});
    var answered=req.Ratings.Where(x=>x.Rating>=0).ToList();
    var score=Math.Round(100m*answered.Sum(x=>x.Rating)/(answered.Count*2),2);
    var critical=req.Ratings.Any(x=>known[x.CriterionId]&&x.Rating==0);
    await using var tx=(SqlTransaction)await db.BeginTransactionAsync();
    await using var cmd=new SqlCommand(@"INSERT dbo.TrainingObservations(PersonnelId,CourseId,WorkOrderId,ObservedOn,ObserverName,PhaseDays,Score,CriticalFailure,Notes,ActionPlan,NextReviewDate)
OUTPUT INSERTED.ObservationId VALUES(@Person,@Course,@Work,@On,@Observer,@Phase,@Score,@Critical,@Notes,@Plan,@Next)",db,tx);
    cmd.Parameters.AddWithValue("@Person",req.PersonnelId);cmd.Parameters.AddWithValue("@Course",req.CourseId);
    cmd.Parameters.AddWithValue("@Work",(object?)req.WorkOrderId??DBNull.Value);
    cmd.Parameters.AddWithValue("@On",req.ObservedOn.ToDateTime(TimeOnly.MinValue));cmd.Parameters.AddWithValue("@Observer",user.FullName);
    cmd.Parameters.AddWithValue("@Phase",req.PhaseDays);cmd.Parameters.AddWithValue("@Score",score);cmd.Parameters.AddWithValue("@Critical",critical);
    cmd.Parameters.AddWithValue("@Notes",Db(req.Notes));cmd.Parameters.AddWithValue("@Plan",Db(req.ActionPlan));
    cmd.Parameters.AddWithValue("@Next",(object?)req.NextReviewDate?.ToDateTime(TimeOnly.MinValue)??DBNull.Value);
    long id;
    try{id=Convert.ToInt64(await cmd.ExecuteScalarAsync());}
    catch(SqlException ex) when(ex.Number==547){await tx.RollbackAsync();return Results.BadRequest(new{message="İş emri, personel veya eğitim kaydı bulunamadı."});}
    foreach(var r in req.Ratings)
    {
       await using var ins=new SqlCommand("INSERT dbo.TrainingObservationRatings(ObservationId,CriterionId,Rating) VALUES(@Id,@Criterion,@Rating)",db,tx);
       ins.Parameters.AddWithValue("@Id",id);ins.Parameters.AddWithValue("@Criterion",r.CriterionId);ins.Parameters.AddWithValue("@Rating",r.Rating);
       await ins.ExecuteNonQueryAsync();
    }
    await tx.CommitAsync();return Results.Ok(new{observationId=id,score,criticalFailure=critical,message="Saha gözlemi kaydedildi."});
});

app.MapGet("/api/training/export.csv",async(HttpContext ctx,int? year)=>
{
    var user=GetCurrentUser(ctx,sessions);if(user is null)return Results.Unauthorized();
    if(!Can(user,"training.view")||!Can(user,"training.export"))return Results.Forbid();
    var y=year is >=2020 and <=2100?year.Value:DateTime.Today.Year;
    await using var db=new SqlConnection(connectionString);await db.OpenAsync();
    const string sql=@"SELECT p.FullName,c.Title,pl.PlanYear,pl.DueDate,pl.Status,pl.CompletedAt,
(SELECT TOP 1 CAST(a.ScoreAfter AS NVARCHAR(15)) FROM dbo.TrainingAttendance a JOIN dbo.TrainingSessions s ON s.TrainingSessionId=a.TrainingSessionId
WHERE a.PersonnelId=p.PersonnelId AND s.CourseId=c.CourseId ORDER BY s.SessionDate DESC) AS AfterScore
FROM dbo.TrainingPlans pl JOIN dbo.Personnel p ON p.PersonnelId=pl.PersonnelId JOIN dbo.TrainingCourses c ON c.CourseId=pl.CourseId WHERE pl.PlanYear=@Year
AND (@All=1 OR (p.UnitCode IS NOT NULL AND CHARINDEX(N'|' + p.UnitCode + N'|', @Units)>0)) ORDER BY p.FullName,c.Title";
    await using var cmd=new SqlCommand(sql,db);cmd.Parameters.AddWithValue("@Year",y);cmd.Parameters.AddWithValue("@All",IsAdmin(user)||user.AllowedUnits.Count==0);cmd.Parameters.AddWithValue("@Units","|"+JoinPipe(user.AllowedUnits)+"|");
    var sb=new StringBuilder("\uFEFF\"Personel\";\"Eğitim\";\"Yıl\";\"Hedef Tarih\";\"Durum\";\"Tamamlanma\";\"Son Sınav\"\r\n");
    static string CsvCell(object? value){var text=Convert.ToString(value,CultureInfo.InvariantCulture)??"";if(text.Length>0&&"=+-@".Contains(text[0]))text="'"+text;return "\""+text.Replace("\"","\"\"")+"\"";}
    await using(var r=await cmd.ExecuteReaderAsync())while(await r.ReadAsync())
    {
       sb.AppendLine(string.Join(';',Enumerable.Range(0,7).Select(i=>CsvCell(r.IsDBNull(i)?null:r.GetValue(i)))));
    }
    return Results.File(Encoding.UTF8.GetBytes(sb.ToString()),"text/csv; charset=utf-8",$"DengeERP_Egitim_Plani_{y}.csv");
});

app.MapGet("/api/personnel", async (HttpContext ctx) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "personnel.view")) return Results.Forbid();

    var rows = new List<object>();
    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    var command = new SqlCommand(@"
SELECT p.PersonnelId,p.FullName,p.DepartmentName,p.AdditionalDepartments,p.Title,p.UnitCode,p.ManagerName,
       p.StartDate,p.EndDate,p.IsActive,p.ErpUserId,p.Notes,u.Username,u.RoleName
FROM dbo.Personnel p
LEFT JOIN dbo.ErpUsers u ON u.UserId=p.ErpUserId
ORDER BY p.DepartmentName,p.FullName", connection);
    await using var reader = await command.ExecuteReaderAsync();
    while (await reader.ReadAsync())
        rows.Add(new
        {
            personnelId = reader.GetInt64(0),
            fullName = reader.GetString(1),
            departmentName = reader.GetString(2),
            additionalDepartments = reader.IsDBNull(3) ? new List<string>() : SplitPipe(reader.GetString(3)),
            title = reader.IsDBNull(4) ? null : reader.GetString(4),
            unitCode = reader.IsDBNull(5) ? null : reader.GetString(5),
            managerName = reader.IsDBNull(6) ? null : reader.GetString(6),
            startDate = reader.IsDBNull(7) ? (DateOnly?)null : DateOnly.FromDateTime(reader.GetDateTime(7)),
            endDate = reader.IsDBNull(8) ? (DateOnly?)null : DateOnly.FromDateTime(reader.GetDateTime(8)),
            isActive = reader.GetBoolean(9),
            erpUserId = reader.IsDBNull(10) ? (int?)null : reader.GetInt32(10),
            notes = reader.IsDBNull(11) ? null : reader.GetString(11),
            username = reader.IsDBNull(12) ? null : reader.GetString(12),
            roleName = reader.IsDBNull(13) ? null : reader.GetString(13)
        });
    return Results.Ok(rows);
});

app.MapPost("/api/personnel", async (HttpContext ctx, CreatePersonnelRequest request) =>
{
    var current = GetCurrentUser(ctx, sessions);
    if (current is null) return Results.Unauthorized();
    if (!Can(current, "personnel.manage")) return Results.Forbid();
    if (string.IsNullOrWhiteSpace(request.FullName) || string.IsNullOrWhiteSpace(request.DepartmentName))
        return Results.BadRequest(new { message = "Ad Soyad ve Departman zorunludur." });
    if (request.CreateUser && !Can(current, "users.manage"))
        return Results.Forbid();

    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    await using var transaction = (SqlTransaction)await connection.BeginTransactionAsync();

    int? erpUserId = null;
    if (request.CreateUser)
    {
        if (string.IsNullOrWhiteSpace(request.Username) || string.IsNullOrWhiteSpace(request.Password) || request.Password.Length < 8)
            return Results.BadRequest(new { message = "ERP hesabı için kullanıcı adı ve en az 8 karakter geçici şifre zorunludur." });

        var exists = new SqlCommand("SELECT COUNT(*) FROM dbo.ErpUsers WHERE Username=@Username", connection, transaction);
        exists.Parameters.AddWithValue("@Username", request.Username.Trim());
        if (Convert.ToInt32(await exists.ExecuteScalarAsync()) > 0)
            return Results.BadRequest(new { message = "Bu kullanıcı adı zaten kullanılıyor." });

        var role = string.IsNullOrWhiteSpace(request.RoleName) ? "Operasyon Uzmanı" : request.RoleName;
        var permissions = request.Permissions is { Count: > 0 } ? request.Permissions : GetRoleDefaults(role).ToList();
        var units = request.AllowedUnits ?? [];
        var (salt, hash) = HashPassword(request.Password);
        var userCommand = new SqlCommand(@"
INSERT INTO dbo.ErpUsers(Username,PasswordHash,PasswordSalt,FullName,RoleName,AllowedUnits,Permissions,IsActive,MustChangePassword)
OUTPUT INSERTED.UserId
VALUES(@Username,@Hash,@Salt,@FullName,@Role,@Units,@Permissions,1,@MustChange)", connection, transaction);
        userCommand.Parameters.AddWithValue("@Username", request.Username.Trim());
        userCommand.Parameters.AddWithValue("@Hash", hash);
        userCommand.Parameters.AddWithValue("@Salt", salt);
        userCommand.Parameters.AddWithValue("@FullName", request.FullName.Trim());
        userCommand.Parameters.AddWithValue("@Role", role);
        userCommand.Parameters.AddWithValue("@Units", JoinPipe(units));
        userCommand.Parameters.AddWithValue("@Permissions", JoinPipe(permissions));
        userCommand.Parameters.AddWithValue("@MustChange", request.MustChangePassword);
        erpUserId = Convert.ToInt32(await userCommand.ExecuteScalarAsync());
    }

    var command = new SqlCommand(@"
INSERT INTO dbo.Personnel
(FullName,DepartmentName,AdditionalDepartments,Title,UnitCode,ManagerName,StartDate,IsActive,ErpUserId,Notes)
OUTPUT INSERTED.PersonnelId
VALUES(@FullName,@Department,@Additional,@Title,@Unit,@Manager,@StartDate,1,@ErpUserId,@Notes)", connection, transaction);
    command.Parameters.AddWithValue("@FullName", request.FullName.Trim());
    command.Parameters.AddWithValue("@Department", request.DepartmentName.Trim());
    command.Parameters.AddWithValue("@Additional", Db(request.AdditionalDepartments is { Count: > 0 } ? JoinPipe(request.AdditionalDepartments) : null));
    command.Parameters.AddWithValue("@Title", Db(request.Title));
    command.Parameters.AddWithValue("@Unit", Db(request.UnitCode));
    command.Parameters.AddWithValue("@Manager", Db(request.ManagerName));
    command.Parameters.AddWithValue("@StartDate", request.StartDate.HasValue ? request.StartDate.Value.ToDateTime(TimeOnly.MinValue) : DBNull.Value);
    command.Parameters.AddWithValue("@ErpUserId", (object?)erpUserId ?? DBNull.Value);
    command.Parameters.AddWithValue("@Notes", Db(request.Notes));
    var personnelId = Convert.ToInt64(await command.ExecuteScalarAsync());
    await transaction.CommitAsync();

    return Results.Ok(new { personnelId, erpUserId, message = "Personel kaydı oluşturuldu." });
});

app.MapPut("/api/personnel/{id:long}", async (HttpContext ctx, long id, UpdatePersonnelRequest request) =>
{
    var current = GetCurrentUser(ctx, sessions);
    if (current is null) return Results.Unauthorized();
    if (!Can(current, "personnel.manage")) return Results.Forbid();
    if (string.IsNullOrWhiteSpace(request.FullName) || string.IsNullOrWhiteSpace(request.DepartmentName))
        return Results.BadRequest(new { message = "Ad Soyad ve Departman zorunludur." });

    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    var command = new SqlCommand(@"
UPDATE dbo.Personnel
SET FullName=@FullName,DepartmentName=@Department,AdditionalDepartments=@Additional,Title=@Title,
    UnitCode=@Unit,ManagerName=@Manager,StartDate=@StartDate,Notes=@Notes,UpdatedAt=SYSDATETIME()
WHERE PersonnelId=@Id", connection);
    command.Parameters.AddWithValue("@FullName", request.FullName.Trim());
    command.Parameters.AddWithValue("@Department", request.DepartmentName.Trim());
    command.Parameters.AddWithValue("@Additional", Db(request.AdditionalDepartments is { Count: > 0 } ? JoinPipe(request.AdditionalDepartments) : null));
    command.Parameters.AddWithValue("@Title", Db(request.Title));
    command.Parameters.AddWithValue("@Unit", Db(request.UnitCode));
    command.Parameters.AddWithValue("@Manager", Db(request.ManagerName));
    command.Parameters.AddWithValue("@StartDate", request.StartDate.HasValue ? request.StartDate.Value.ToDateTime(TimeOnly.MinValue) : DBNull.Value);
    command.Parameters.AddWithValue("@Notes", Db(request.Notes));
    command.Parameters.AddWithValue("@Id", id);
    var affected = await command.ExecuteNonQueryAsync();
    return affected == 0 ? Results.NotFound() : Results.Ok(new { message = "Personel bilgileri güncellendi." });
});

app.MapPatch("/api/personnel/{id:long}/status", async (HttpContext ctx, long id, PersonnelStatusRequest request) =>
{
    var current = GetCurrentUser(ctx, sessions);
    if (current is null) return Results.Unauthorized();
    if (!Can(current, "personnel.manage")) return Results.Forbid();

    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    await using var transaction = (SqlTransaction)await connection.BeginTransactionAsync();

    int? userId = null;
    var load = new SqlCommand("SELECT ErpUserId FROM dbo.Personnel WHERE PersonnelId=@Id", connection, transaction);
    load.Parameters.AddWithValue("@Id", id);
    var scalar = await load.ExecuteScalarAsync();
    if (scalar is null) return Results.NotFound();
    if (scalar != DBNull.Value) userId = Convert.ToInt32(scalar);

    var command = new SqlCommand(@"
UPDATE dbo.Personnel
SET IsActive=@Active,
    EndDate=CASE WHEN @Active=0 THEN COALESCE(@EndDate,CONVERT(date,SYSDATETIME())) ELSE NULL END,
    UpdatedAt=SYSDATETIME()
WHERE PersonnelId=@Id", connection, transaction);
    command.Parameters.AddWithValue("@Active", request.IsActive);
    command.Parameters.AddWithValue("@EndDate", request.EndDate.HasValue ? request.EndDate.Value.ToDateTime(TimeOnly.MinValue) : DBNull.Value);
    command.Parameters.AddWithValue("@Id", id);
    await command.ExecuteNonQueryAsync();

    if (userId.HasValue)
    {
        var userCommand = new SqlCommand("UPDATE dbo.ErpUsers SET IsActive=@Active,UpdatedAt=SYSDATETIME() WHERE UserId=@UserId", connection, transaction);
        userCommand.Parameters.AddWithValue("@Active", request.IsActive);
        userCommand.Parameters.AddWithValue("@UserId", userId.Value);
        await userCommand.ExecuteNonQueryAsync();

        foreach (var kv in sessions.Where(x => x.Value.UserId == userId.Value).ToList())
            sessions.TryRemove(kv.Key, out _);
    }

    await transaction.CommitAsync();
    return Results.Ok(new { message = request.IsActive ? "Personel aktif edildi." : "Personel pasif edildi; bağlı ERP hesabı varsa erişimi kapatıldı." });
});


// V1.14 - Canli saha zaman akisi. Sureler yalnizca SQL sunucu zamanindan ve yetkili oturumdan uretilir.
// Onceki manuel sure kayitlari aynen kullanilir, yeni zaman sayaci bitince WorkOrderTimeLogs'a aktarilir.
app.MapGet("/api/timetracking/summary", async (HttpContext ctx) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "workorders.view")) return Results.Forbid();
    var orders = FilterWorkOrdersForUser(await LoadWorkOrdersAsync(connectionString), user);
    var ids = orders.Select(x => x.WorkOrderId).ToHashSet();
    var overview = Can(user, "reports.view");
    var active = (await LoadLiveTimersAsync(connectionString))
        .Where(x => ids.Contains(x.WorkOrderId) && (overview || x.TechnicianUserId == user.UserId))
        .ToList();
    var logs = (await LoadTimeLogsAsync(connectionString))
        .Where(x => ids.Contains(x.WorkOrderId) && (overview ||
            string.Equals(x.TechnicianName, user.FullName, StringComparison.OrdinalIgnoreCase)))
        .ToList();
    var breaks = (await LoadLiveTimersAsync(connectionString, completedBreaks: true))
        .Where(x => ids.Contains(x.WorkOrderId) && (overview || x.TechnicianUserId == user.UserId))
        .ToList();
    return Results.Ok(new { active, logs, breaks, serverTime = DateTime.Now, isManager = overview });
});

app.MapPost("/api/workorders/{id:long}/live-timer/start", async (HttpContext ctx, long id, LiveTimerStartRequest request) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "workorders.view") || (!Can(user, "workorders.close") && !Can(user, "workorders.edit")))
        return Results.Forbid();
    if (!await CanAccessWorkOrderAsync(connectionString, id, user)) return Results.Forbid();
    string[] types = ["Saha Çalışması", "Yol / Ulaşım", "Bekleme", "Uzaktan Destek", "Atölye", "Test / Kontrol", "Mola / Ara"];
    if (!types.Contains(request.ActivityType)) return Results.BadRequest(new { message = "Geçersiz faaliyet türü." });
    if (request.LocationNote?.Length > 250 || request.WorkNote?.Length > 1000)
        return Results.BadRequest(new { message = "Bölge ya da not karakter sınırı aşıldı." });
    await using var conn = new SqlConnection(connectionString);
    await conn.OpenAsync();
    await using var tx = (SqlTransaction)await conn.BeginTransactionAsync(System.Data.IsolationLevel.Serializable);
    var assignment = new SqlCommand(@"
SELECT COUNT(1) FROM dbo.WorkOrderAssignments WITH (UPDLOCK,HOLDLOCK)
WHERE WorkOrderId=@Id AND IsActive=1 AND AssignmentRole=N'Teknisyen' AND AssignedName=@Name", conn, tx);
    assignment.Parameters.AddWithValue("@Id", id); assignment.Parameters.AddWithValue("@Name", user.FullName);
    if (Convert.ToInt32(await assignment.ExecuteScalarAsync()) == 0)
        return Results.BadRequest(new { message = "Canlı sayaç yalnızca iş emrine atanmış kişinin kendi hesabıyla başlatılabilir." });
    var status = new SqlCommand("SELECT Status FROM dbo.WorkOrders WITH (UPDLOCK,HOLDLOCK) WHERE WorkOrderId=@Id", conn, tx);
    status.Parameters.AddWithValue("@Id", id);
    var state = (string?)await status.ExecuteScalarAsync();
    if (state is null) return Results.NotFound();
    if (state is "Tamamlandı" or "Kapatıldı" or "İptal")
        return Results.BadRequest(new { message = "Kapalı veya iptal edilmiş işe canlı süre başlatılamaz." });
    var exists = new SqlCommand("SELECT COUNT(1) FROM dbo.WorkOrderLiveSessions WITH (UPDLOCK,HOLDLOCK) WHERE TechnicianUserId=@Uid AND EndedAt IS NULL", conn, tx);
    exists.Parameters.AddWithValue("@Uid", user.UserId);
    if (Convert.ToInt32(await exists.ExecuteScalarAsync()) > 0)
        return Results.Conflict(new { message = "Başka işte aktif sayacınız var. Önce onu bitirin veya faaliyet değiştirin." });
    var now = (DateTime)(await new SqlCommand("SELECT SYSDATETIME()", conn, tx).ExecuteScalarAsync())!;
    var existing = new SqlCommand(@"
SELECT COUNT(1) FROM dbo.WorkOrderTimeLogs WITH (UPDLOCK,HOLDLOCK)
WHERE TechnicianName=@Name AND IsVoided=0 AND StartedAt<=@Now AND EndedAt>@Now", conn, tx);
    existing.Parameters.AddWithValue("@Name", user.FullName); existing.Parameters.AddWithValue("@Now", now);
    if (Convert.ToInt32(await existing.ExecuteScalarAsync()) > 0)
        return Results.Conflict(new { message = "Bu personelin aynı anda başka süre kaydı mevcut." });
    var insert = new SqlCommand(@"
INSERT dbo.WorkOrderLiveSessions(WorkOrderId,TechnicianUserId,TechnicianName,ActivityType,StartedAt,LocationNote,WorkNote)
OUTPUT INSERTED.SessionId VALUES(@Id,@Uid,@Name,@Activity,@Now,@Location,@Note)", conn, tx);
    insert.Parameters.AddWithValue("@Id", id); insert.Parameters.AddWithValue("@Uid", user.UserId);
    insert.Parameters.AddWithValue("@Name", user.FullName); insert.Parameters.AddWithValue("@Activity", request.ActivityType);
    insert.Parameters.AddWithValue("@Now", now); insert.Parameters.AddWithValue("@Location", Db(request.LocationNote?.Trim()));
    insert.Parameters.AddWithValue("@Note", Db(request.WorkNote?.Trim()));
    try
    {
        var sessionId = Convert.ToInt64(await insert.ExecuteScalarAsync());
        await tx.CommitAsync();
        return Results.Ok(new { sessionId, startedAt = now, message = "Canlı süre başladı." });
    }
    catch (SqlException ex) when (ex.Number is 2601 or 2627)
    {
        return Results.Conflict(new { message = "Birden fazla aktif sayaç açılamaz." });
    }
});

app.MapPost("/api/workorders/{id:long}/live-timer/change", (HttpContext ctx, long id, LiveTimerChangeRequest request) =>
    FinishLiveTimerAsync(ctx, id, request, true));
app.MapPost("/api/workorders/{id:long}/live-timer/finish", (HttpContext ctx, long id, LiveTimerChangeRequest request) =>
    FinishLiveTimerAsync(ctx, id, request, false));

async Task<IResult> FinishLiveTimerAsync(HttpContext ctx, long id, LiveTimerChangeRequest request, bool switchActivity)
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "workorders.view") || (!Can(user, "workorders.close") && !Can(user, "workorders.edit")))
        return Results.Forbid();
    if (!await CanAccessWorkOrderAsync(connectionString, id, user)) return Results.Forbid();
    string[] allowed = ["Saha Çalışması", "Yol / Ulaşım", "Bekleme", "Uzaktan Destek", "Atölye", "Test / Kontrol", "Mola / Ara"];
    if (switchActivity && !allowed.Contains(request.ActivityType))
        return Results.BadRequest(new { message = "Geçersiz yeni faaliyet türü." });
    if (request.LocationNote?.Length > 250 || request.WorkNote?.Length > 1000)
        return Results.BadRequest(new { message = "Bölge veya not karakter sınırı aşıldı." });
    await using var conn = new SqlConnection(connectionString);
    await conn.OpenAsync();
    await using var tx = (SqlTransaction)await conn.BeginTransactionAsync(System.Data.IsolationLevel.Serializable);
    var command = new SqlCommand(@"
SELECT TOP 1 SessionId,ActivityType,StartedAt,LocationNote,WorkNote,TechnicianName
FROM dbo.WorkOrderLiveSessions WITH (UPDLOCK,HOLDLOCK)
WHERE WorkOrderId=@Id AND TechnicianUserId=@Uid AND EndedAt IS NULL", conn, tx);
    command.Parameters.AddWithValue("@Id", id); command.Parameters.AddWithValue("@Uid", user.UserId);
    long liveId; string activity, tech; DateTime start; string? oldLocation, oldNote;
    await using (var reader = await command.ExecuteReaderAsync())
    {
        if (!await reader.ReadAsync()) return Results.Conflict(new { message = "Bu işte aktif zaman sayacınız yok." });
        liveId = reader.GetInt64(0); activity = reader.GetString(1); start = reader.GetDateTime(2);
        oldLocation = reader.IsDBNull(3) ? null : reader.GetString(3);
        oldNote = reader.IsDBNull(4) ? null : reader.GetString(4);
        tech = reader.GetString(5);
    }
    if (switchActivity && request.ActivityType == activity)
        return Results.BadRequest(new { message = "Zaten aynı faaliyet çalışıyor." });
    var end = (DateTime)(await new SqlCommand("SELECT SYSDATETIME()", conn, tx).ExecuteScalarAsync())!;
    if (end < start.AddMinutes(1))
        return Results.BadRequest(new { message = "Doğru süre ölçümü için en az 1 dakika sonra faaliyet değiştirin veya bitirin." });
    if (end > start.AddHours(18))
        return Results.BadRequest(new { message = "Sayaç 18 saati aşmış. Veri güvenliği için yöneticinin bu oturumu iptal edip zamanı manuel girmesi gerekiyor." });
    if (switchActivity)
    {
        var status = new SqlCommand("SELECT Status FROM dbo.WorkOrders WHERE WorkOrderId=@Id", conn, tx);
        status.Parameters.AddWithValue("@Id", id);
        var s = (string?)await status.ExecuteScalarAsync();
        if (s is "Tamamlandı" or "Kapatıldı" or "İptal")
            return Results.BadRequest(new { message = "Kapalı işte yeni faaliyet başlatılamaz." });
    }
    long? timeLogId = null;
    string? savedLocation = request.LocationNote?.Trim() is { Length: > 0 } location ? location : oldLocation;
    string? savedNote = request.WorkNote?.Trim() is { Length: > 0 } note ? note : oldNote;
    if (activity != "Mola / Ara")
    {
        var overlap = new SqlCommand(@"
SELECT COUNT(1) FROM dbo.WorkOrderTimeLogs WITH (UPDLOCK,HOLDLOCK)
WHERE TechnicianName=@Name AND IsVoided=0 AND StartedAt<@End AND EndedAt>@Start", conn, tx);
        overlap.Parameters.AddWithValue("@Name", tech); overlap.Parameters.AddWithValue("@Start", start);
        overlap.Parameters.AddWithValue("@End", end);
        if (Convert.ToInt32(await overlap.ExecuteScalarAsync()) > 0)
            return Results.Conflict(new { message = "Elle girilmiş başka bir faaliyetle saatler çakışıyor. Çift sayımı önlemek için işlem durduruldu." });
        var insertLog = new SqlCommand(@"
INSERT dbo.WorkOrderTimeLogs(WorkOrderId,TechnicianName,ActivityType,StartedAt,EndedAt,LocationNote,WorkNote,CreatedByUserId,CreatedByName)
OUTPUT INSERTED.TimeLogId VALUES(@Id,@Name,@Activity,@Start,@End,@Location,@Note,@Uid,@User)", conn, tx);
        insertLog.Parameters.AddWithValue("@Id", id); insertLog.Parameters.AddWithValue("@Name", tech);
        insertLog.Parameters.AddWithValue("@Activity", activity); insertLog.Parameters.AddWithValue("@Start", start);
        insertLog.Parameters.AddWithValue("@End", end); insertLog.Parameters.AddWithValue("@Location", Db(savedLocation));
        insertLog.Parameters.AddWithValue("@Note", Db(savedNote)); insertLog.Parameters.AddWithValue("@Uid", user.UserId);
        insertLog.Parameters.AddWithValue("@User", user.FullName);
        timeLogId = Convert.ToInt64(await insertLog.ExecuteScalarAsync());
    }
    var finish = new SqlCommand(@"
UPDATE dbo.WorkOrderLiveSessions SET EndedAt=@End,StopReason=@Reason,
ResultTimeLogId=@LogId,LocationNote=@Location,WorkNote=@Note
WHERE SessionId=@Sid AND EndedAt IS NULL", conn, tx);
    finish.Parameters.AddWithValue("@End", end); finish.Parameters.AddWithValue("@Reason", switchActivity ? "Faaliyet Değiştirildi" : "Bitirildi");
    finish.Parameters.AddWithValue("@LogId", timeLogId.HasValue ? (object)timeLogId.Value : DBNull.Value);
    finish.Parameters.AddWithValue("@Location", Db(savedLocation)); finish.Parameters.AddWithValue("@Note", Db(savedNote));
    finish.Parameters.AddWithValue("@Sid", liveId);
    if (await finish.ExecuteNonQueryAsync() != 1) return Results.Conflict(new { message = "Sayaç başka işlem tarafından değiştirilmiş." });
    if (switchActivity)
    {
        var next = new SqlCommand(@"
INSERT dbo.WorkOrderLiveSessions(WorkOrderId,TechnicianUserId,TechnicianName,ActivityType,StartedAt,LocationNote,WorkNote)
VALUES(@Id,@Uid,@Name,@Activity,@Start,@Location,NULL)", conn, tx);
        next.Parameters.AddWithValue("@Id", id); next.Parameters.AddWithValue("@Uid", user.UserId);
        next.Parameters.AddWithValue("@Name", tech); next.Parameters.AddWithValue("@Activity", request.ActivityType!);
        next.Parameters.AddWithValue("@Start", end); next.Parameters.AddWithValue("@Location", Db(savedLocation));
        await next.ExecuteNonQueryAsync();
    }
    await tx.CommitAsync();
    return Results.Ok(new { minutes = (int)(end - start).TotalMinutes, logged = activity != "Mola / Ara",
        message = switchActivity ? "Önceki faaliyet kaydedildi, yenisi başlatıldı." : "Canlı süre tamamlandı. İş emri durumu ayrıca kapatılabilir." });
}

app.MapPost("/api/timetracking/sessions/{sessionId:long}/cancel", async (HttpContext ctx, long sessionId, LiveTimerCancelRequest request) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "workorders.assign") && !Can(user, "users.manage")) return Results.Forbid();
    if (string.IsNullOrWhiteSpace(request.Reason) || request.Reason.Length > 500)
        return Results.BadRequest(new { message = "İptal gerekçesi (en fazla 500 karakter) gereklidir." });
    await using var conn = new SqlConnection(connectionString);
    await conn.OpenAsync();
    var check = new SqlCommand("SELECT WorkOrderId FROM dbo.WorkOrderLiveSessions WHERE SessionId=@Sid AND EndedAt IS NULL", conn);
    check.Parameters.AddWithValue("@Sid", sessionId);
    var id = await check.ExecuteScalarAsync();
    if (id is null) return Results.NotFound();
    if (!await CanAccessWorkOrderAsync(connectionString, Convert.ToInt64(id), user)) return Results.Forbid();
    var cmd = new SqlCommand(@"
UPDATE dbo.WorkOrderLiveSessions SET EndedAt=CASE WHEN SYSDATETIME()<StartedAt THEN StartedAt ELSE SYSDATETIME() END,
StopReason=N'İptal',CancelledByUserId=@Uid,CancelReason=@Reason
WHERE SessionId=@Sid AND EndedAt IS NULL", conn);
    cmd.Parameters.AddWithValue("@Sid", sessionId); cmd.Parameters.AddWithValue("@Uid", user.UserId);
    cmd.Parameters.AddWithValue("@Reason", request.Reason.Trim());
    if (await cmd.ExecuteNonQueryAsync() != 1) return Results.Conflict(new { message = "Oturum zaten tamamlanmış." });
    return Results.Ok(new { message = "Sayaç gerekçeli iptal edildi. Kayıt saklandı, kişi-saat oluşturulmadı." });
});

// V1.10 - Gerçek çalışma süresi, kişi bazlı. Planlanan süre raporda gerçekleşen süre yerine geçmez.
app.MapGet("/api/workorders/{id:long}/time-logs", async (HttpContext ctx, long id) =>
{
    var user=GetCurrentUser(ctx,sessions);
    if(user is null)return Results.Unauthorized();
    if(!Can(user,"workorders.view"))return Results.Forbid();
    if(!await CanAccessWorkOrderAsync(connectionString,id,user))return Results.Forbid();
    var all=await LoadTimeLogsAsync(connectionString);
    return Results.Ok(all.Where(x=>x.WorkOrderId==id));
});
app.MapPost("/api/workorders/{id:long}/time-logs", async (HttpContext ctx, long id, TimeLogCreateRequest request) =>
{
    var user=GetCurrentUser(ctx,sessions);
    if(user is null)return Results.Unauthorized();
    if(!Can(user,"workorders.close")&&!Can(user,"workorders.edit"))return Results.Forbid();
    if(!await CanAccessWorkOrderAsync(connectionString,id,user))return Results.Forbid();
    var name=(user.RoleName=="Teknisyen"?user.FullName:request.TechnicianName??"").Trim();
    if(name.Length==0||name.Length>200)return Results.BadRequest(new{message="Teknisyen seçiniz."});
    string[] activities=["Saha Çalışması","Yol / Ulaşım","Bekleme","Uzaktan Destek","Atölye","Test / Kontrol","Diğer"];
    if(!activities.Contains(request.ActivityType))return Results.BadRequest(new{message="Geçersiz faaliyet türü."});
    if(request.EndedAt<=request.StartedAt || (request.EndedAt-request.StartedAt).TotalMinutes>1080)
        return Results.BadRequest(new{message="Bitiş başlangıçtan sonra olmalı; tek kayıt en fazla 18 saat olabilir."});
    if(request.StartedAt>DateTime.Now.AddMinutes(5)||request.EndedAt>DateTime.Now.AddMinutes(5))
        return Results.BadRequest(new{message="Gelecek tarihli gerçekleşen çalışma kaydı oluşturulamaz."});
    if(request.LocationNote?.Length>250||request.WorkNote?.Length>1000)
        return Results.BadRequest(new{message="Bölge (250) veya not (1000) karakter sınırı aşıldı."});
    await using var connection=new SqlConnection(connectionString);
    await connection.OpenAsync();
    await using var transaction=(SqlTransaction)await connection.BeginTransactionAsync(System.Data.IsolationLevel.Serializable);
    var tech=new SqlCommand(@"
SELECT COUNT(1) FROM dbo.WorkOrderAssignments
WHERE WorkOrderId=@Id AND IsActive=1 AND AssignmentRole=N'Teknisyen' AND AssignedName=@Name",connection,transaction);
    tech.Parameters.AddWithValue("@Id",id); tech.Parameters.AddWithValue("@Name",name);
    if(Convert.ToInt32(await tech.ExecuteScalarAsync())==0)
        return Results.BadRequest(new{message="Süre kaydı için teknisyen önce bu iş emrine atanmalıdır."});
    var running=new SqlCommand(@"SELECT COUNT(1) FROM dbo.WorkOrderLiveSessions WITH (UPDLOCK,HOLDLOCK)
WHERE TechnicianName=@Name AND EndedAt IS NULL AND StartedAt<@End",connection,transaction);
    running.Parameters.AddWithValue("@Name",name);running.Parameters.AddWithValue("@End",request.EndedAt);
    if(Convert.ToInt32(await running.ExecuteScalarAsync())>0)
        return Results.Conflict(new{message="Personelin çalışan zaman sayacıyla manuel kayıt çakışıyor. Önce sayacı bitirin."});
    var overlaps=new SqlCommand(@"
SELECT COUNT(1) FROM dbo.WorkOrderTimeLogs WITH (UPDLOCK, HOLDLOCK)
WHERE TechnicianName=@Name AND IsVoided=0 AND StartedAt<@End AND EndedAt>@Start",connection,transaction);
    overlaps.Parameters.AddWithValue("@Name",name);
    overlaps.Parameters.AddWithValue("@Start",request.StartedAt);
    overlaps.Parameters.AddWithValue("@End",request.EndedAt);
    if(Convert.ToInt32(await overlaps.ExecuteScalarAsync())>0)
        return Results.Conflict(new{message="Bu personel için aynı zaman aralığında başka faaliyet kaydı var. Çift sayımı önlemek için kayıt engellendi."});
    var cmd=new SqlCommand(@"
INSERT INTO dbo.WorkOrderTimeLogs(WorkOrderId,TechnicianName,ActivityType,StartedAt,EndedAt,LocationNote,WorkNote,CreatedByUserId,CreatedByName)
OUTPUT INSERTED.TimeLogId
VALUES(@Id,@Name,@Activity,@Start,@End,@Location,@Note,@UserId,@User)",connection,transaction);
    cmd.Parameters.AddWithValue("@Id",id);cmd.Parameters.AddWithValue("@Name",name);
    cmd.Parameters.AddWithValue("@Activity",request.ActivityType);
    cmd.Parameters.AddWithValue("@Start",request.StartedAt);cmd.Parameters.AddWithValue("@End",request.EndedAt);
    cmd.Parameters.AddWithValue("@Location",Db(request.LocationNote?.Trim()));
    cmd.Parameters.AddWithValue("@Note",Db(request.WorkNote?.Trim()));
    cmd.Parameters.AddWithValue("@UserId",user.UserId);cmd.Parameters.AddWithValue("@User",user.FullName);
    var newId=Convert.ToInt64(await cmd.ExecuteScalarAsync());
    await transaction.CommitAsync();
    return Results.Ok(new{timeLogId=newId,minutes=(int)Math.Round((request.EndedAt-request.StartedAt).TotalMinutes),message="Personel çalışma süresi kaydedildi."});
});
app.MapDelete("/api/workorders/{id:long}/time-logs/{timeLogId:long}", async (HttpContext ctx,long id,long timeLogId)=>
{
    var user=GetCurrentUser(ctx,sessions);
    if(user is null)return Results.Unauthorized();
    if(!Can(user,"workorders.assign")&&!Can(user,"users.manage"))return Results.Forbid();
    if(!await CanAccessWorkOrderAsync(connectionString,id,user))return Results.Forbid();
    await using var connection=new SqlConnection(connectionString);
    await connection.OpenAsync();
    var cmd=new SqlCommand(@"UPDATE dbo.WorkOrderTimeLogs
SET IsVoided=1,VoidedAt=SYSDATETIME(),VoidedByName=@Name
WHERE TimeLogId=@LogId AND WorkOrderId=@Id AND IsVoided=0",connection);
    cmd.Parameters.AddWithValue("@Name",user.FullName);cmd.Parameters.AddWithValue("@Id",id);cmd.Parameters.AddWithValue("@LogId",timeLogId);
    if(await cmd.ExecuteNonQueryAsync()==0)return Results.NotFound();
    return Results.Ok(new{message="Hatalı süre kaydı iptal edildi. Denetim izi saklandı."});
});
app.MapGet("/api/reports/worklogs", async (HttpContext ctx) =>
{
    var user=GetCurrentUser(ctx,sessions);
    if(user is null)return Results.Unauthorized();
    if(!Can(user,"reports.view"))return Results.Forbid();
    var ids=FilterWorkOrdersForUser(await LoadWorkOrdersAsync(connectionString),user)
        .Select(x=>x.WorkOrderId).ToHashSet();
    return Results.Ok((await LoadTimeLogsAsync(connectionString)).Where(x=>ids.Contains(x.WorkOrderId)));
});

app.MapGet("/api/reports/workorders.xlsx", async (HttpContext ctx, DateOnly? start, DateOnly? end, string? dateField, string? kind, string? unit, string? status, string? workType, string? person, string? chief, string? customer) =>
{
    var user=GetCurrentUser(ctx,sessions);
    if(user is null)return Results.Unauthorized();
    if(!Can(user,"reports.export"))return Results.Forbid();
    if(start.HasValue&&end.HasValue&&start>end)return Results.BadRequest(new{message="Başlangıç tarihi bitişten büyük olamaz."});
    var allowed=FilterWorkOrdersForUser(await LoadWorkOrdersAsync(connectionString),user);
    var baseRows=allowed
        .Where(x=>(string.IsNullOrWhiteSpace(kind)||kind=="all"||(kind=="maintenance" ? IsReportMaintenance(x) : !IsReportMaintenance(x))))
        .Where(x=>string.IsNullOrWhiteSpace(unit)||unit=="Tümü"||x.UnitCode==unit)
        .Where(x=>string.IsNullOrWhiteSpace(status)||status=="Tümü"||x.Status==status)
        .Where(x=>string.IsNullOrWhiteSpace(workType)||workType=="Tümü"||x.WorkType==workType)
        .Where(x=>string.IsNullOrWhiteSpace(chief)||(x.ChiefName??"").Contains(chief,StringComparison.OrdinalIgnoreCase)).ToList();
    DateOnly? reportDate(WorkOrderRow x)=>dateField switch
    {
        "plan"=>x.PlanDate,
        "closed"=>x.ClosedAt.HasValue?DateOnly.FromDateTime(x.ClosedAt.Value):null,
        _=>DateOnly.FromDateTime(x.CreatedAt)
    };
    var rows=baseRows
        .Where(x=>string.IsNullOrWhiteSpace(person)||(x.AssignedStaff??"").Contains(person,StringComparison.OrdinalIgnoreCase))
        .Where(x=>string.IsNullOrWhiteSpace(customer)||new[]{x.CustomerName,x.Location,x.WorkOrderNo,x.Subject,x.SerialNumbers}.Any(v=>(v??"").Contains(customer,StringComparison.OrdinalIgnoreCase)))
        .Where(x=>!start.HasValue||(reportDate(x).HasValue&&reportDate(x).GetValueOrDefault()>=start.Value))
        .Where(x=>!end.HasValue||(reportDate(x).HasValue&&reportDate(x).GetValueOrDefault()<=end.Value))
        .ToList();
    // Kişi-saat raporlaması iş emri açılış/plan tarihinden değil, gerçek faaliyet saatinden beslenir.
    var byId=baseRows.ToDictionary(x=>x.WorkOrderId);
    var logs=(await LoadTimeLogsAsync(connectionString))
        .Where(x=>byId.ContainsKey(x.WorkOrderId))
        .Where(x=>!start.HasValue||DateOnly.FromDateTime(x.StartedAt)>=start.Value)
        .Where(x=>!end.HasValue||DateOnly.FromDateTime(x.StartedAt)<=end.Value)
        .Where(x=>string.IsNullOrWhiteSpace(person)||x.TechnicianName.Contains(person,StringComparison.OrdinalIgnoreCase))
        .Where(x=>string.IsNullOrWhiteSpace(customer)||((x.LocationNote??"").Contains(customer,StringComparison.OrdinalIgnoreCase))||
            new[]{byId[x.WorkOrderId].CustomerName,byId[x.WorkOrderId].Location,byId[x.WorkOrderId].WorkOrderNo,byId[x.WorkOrderId].Subject,byId[x.WorkOrderId].SerialNumbers}.Any(v=>(v??"").Contains(customer,StringComparison.OrdinalIgnoreCase)))
        .ToList();
    var bytes=BuildWorkOrderXlsx(rows,logs,byId,start,end,dateField);
    var fileName=$"DengeERP_Yonetim_Raporu_{DateTime.Now:yyyyMMdd_HHmm}.xlsx";
    return Results.File(bytes,"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",fileName);
});

// Pilot V1.5 - Güvenlik cihaz kütüğü
app.MapGet("/api/security/devices", async (HttpContext ctx) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "devices.view") && !Can(user, "workorders.view")) return Results.Forbid();
    if (!UnitAllowed(user, "Güvenlik Sistemleri")) return Results.Forbid();

    var q = (ctx.Request.Query["q"].FirstOrDefault() ?? "").Trim();
    var brand = (ctx.Request.Query["brand"].FirstOrDefault() ?? "").Trim();
    var deviceType = (ctx.Request.Query["type"].FirstOrDefault() ?? "").Trim();
    var model = (ctx.Request.Query["model"].FirstOrDefault() ?? "").Trim();

    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();

    var command = new SqlCommand(@"
SELECT SecurityDeviceId,SourceRowNo,DeviceType,Brand,Model,SerialNo,CustomerName,Location,ContactName,DeliveryDateText,InstallStatus,Notes
FROM dbo.SecurityDevices
WHERE IsActive=1
  AND (@Brand=N'' OR Brand=@Brand)
  AND (@Type=N'' OR DeviceType=@Type)
  AND (@Model=N'' OR Model=@Model)
  AND (@Q=N'' OR
       ISNULL(SerialNo,N'') LIKE N'%'+@Q+N'%' OR
       ISNULL(CustomerName,N'') LIKE N'%'+@Q+N'%' OR
       ISNULL(Location,N'') LIKE N'%'+@Q+N'%' OR
       ISNULL(Model,N'') LIKE N'%'+@Q+N'%')
ORDER BY CustomerName,Location,Model,SecurityDeviceId", connection);
    command.Parameters.AddWithValue("@Q", q);
    command.Parameters.AddWithValue("@Brand", brand);
    command.Parameters.AddWithValue("@Type", deviceType);
    command.Parameters.AddWithValue("@Model", model);

    var rows = new List<object>();
    await using var reader = await command.ExecuteReaderAsync();
    while (await reader.ReadAsync())
        rows.Add(new
        {
            securityDeviceId = reader.GetInt64(0),
            sourceRowNo = reader.IsDBNull(1) ? (int?)null : reader.GetInt32(1),
            deviceType = reader.GetString(2),
            brand = reader.GetString(3),
            model = reader.GetString(4),
            serialNo = reader.IsDBNull(5) ? null : reader.GetString(5),
            customerName = reader.IsDBNull(6) ? null : reader.GetString(6),
            location = reader.IsDBNull(7) ? null : reader.GetString(7),
            contactName = reader.IsDBNull(8) ? null : reader.GetString(8),
            deliveryDateText = reader.IsDBNull(9) ? null : reader.GetString(9),
            installStatus = reader.IsDBNull(10) ? null : reader.GetString(10),
            notes = reader.IsDBNull(11) ? null : reader.GetString(11)
        });

    return Results.Ok(rows);
});

// Pilot V1.5 - Bakım sözleşmeleri / otomatik iş emri üretimi
app.MapGet("/api/maintenance/contracts", async (HttpContext ctx) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "maintenance.view") && !Can(user, "workorders.view")) return Results.Forbid();
    if (!UnitAllowed(user, "Güvenlik Sistemleri")) return Results.Forbid();

    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    var command = new SqlCommand(@"
SELECT c.MaintenanceContractId,c.SourceKey,c.CustomerName,c.CurrentAddress,c.ProductsText,c.FrequencyText,
       c.AnnualFrequency,c.MaintenanceFeeText,c.PeriodText,c.CompletedCount,c.ContractTotal,c.Total2026,
       p.MaintenancePlanId,p.SequenceNo,p.TargetDate,p.IsCompleted,p.GeneratedWorkOrderId,w.WorkOrderNo,w.Status,
(SELECT COUNT(*) FROM dbo.MaintenanceDeviceItems md WHERE md.MaintenancePlanId=p.MaintenancePlanId) AS DeviceCount,
(SELECT COUNT(*) FROM dbo.MaintenanceDeviceItems md WHERE md.MaintenancePlanId=p.MaintenancePlanId AND md.Status=N'Tamamlandı') AS DeviceCompleted
FROM dbo.MaintenanceContracts c
OUTER APPLY
(
    SELECT TOP 1 mp.MaintenancePlanId,mp.SequenceNo,mp.TargetDate,mp.IsCompleted,mp.GeneratedWorkOrderId
    FROM dbo.MaintenancePlans mp
    WHERE mp.MaintenanceContractId=c.MaintenanceContractId
      AND mp.PlanYear=YEAR(GETDATE())
      AND mp.IsCompleted=0
    ORDER BY mp.SequenceNo
) p
LEFT JOIN dbo.WorkOrders w ON w.WorkOrderId=p.GeneratedWorkOrderId
WHERE c.IsActive=1
ORDER BY c.CustomerName", connection);

    var rows = new List<object>();
    await using var reader = await command.ExecuteReaderAsync();
    while (await reader.ReadAsync())
        rows.Add(new
        {
            maintenanceContractId = reader.GetInt64(0),
            sourceKey = reader.GetString(1),
            customerName = reader.GetString(2),
            currentAddress = reader.IsDBNull(3) ? null : reader.GetString(3),
            productsText = reader.IsDBNull(4) ? null : reader.GetString(4),
            frequencyText = reader.IsDBNull(5) ? null : reader.GetString(5),
            annualFrequency = reader.GetInt32(6),
            maintenanceFeeText = !Can(user, "finance.prices.view") || reader.IsDBNull(7) ? null : reader.GetString(7),
            periodText = reader.IsDBNull(8) ? null : reader.GetString(8),
            completedCount = reader.GetInt32(9),
            contractTotal = !Can(user, "finance.prices.view") || reader.IsDBNull(10) ? (decimal?)null : reader.GetDecimal(10),
            total2026 = !Can(user, "finance.prices.view") || reader.IsDBNull(11) ? (decimal?)null : reader.GetDecimal(11),
            nextPlanId = reader.IsDBNull(12) ? (long?)null : reader.GetInt64(12),
            nextSequenceNo = reader.IsDBNull(13) ? (int?)null : reader.GetInt32(13),
            nextTargetDate = reader.IsDBNull(14) ? (DateOnly?)null : DateOnly.FromDateTime(reader.GetDateTime(14)),
            nextCompleted = reader.IsDBNull(15) ? (bool?)null : reader.GetBoolean(15),
            generatedWorkOrderId = reader.IsDBNull(16) ? (long?)null : reader.GetInt64(16),
            workOrderNo = reader.IsDBNull(17) ? null : reader.GetString(17),
            workOrderStatus = reader.IsDBNull(18) ? null : reader.GetString(18),
            deviceCount = reader.GetInt32(19),
            deviceCompleted = reader.GetInt32(20)
        });
    return Results.Ok(rows);
});

app.MapPost("/api/maintenance/generate-due", async (HttpContext ctx) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "maintenance.manage") && !Can(user, "workorders.plan")) return Results.Forbid();
    if (!UnitAllowed(user, "Güvenlik Sistemleri")) return Results.Forbid();

    var count = await EnsureMaintenancePlansAndWorkOrdersAsync(connectionString);
    return Results.Ok(new { generated = count, message = $"{count} adet vadesi gelen bakım iş emri oluşturuldu." });
});


// V1.7 - Ana PB iş emri altında cihaz bazında bakım kayıtları.
app.MapGet("/api/maintenance/plans/{planId:long}/devices", async (HttpContext ctx, long planId) =>
{
    var user=GetCurrentUser(ctx,sessions);
    if(user is null) return Results.Unauthorized();
    if(!Can(user,"maintenance.view") && !Can(user,"workorders.view")) return Results.Forbid();
    if(!UnitAllowed(user,"Güvenlik Sistemleri")) return Results.Forbid();
    await using var db=new SqlConnection(connectionString); await db.OpenAsync();
    var cmd=new SqlCommand(@"SELECT i.MaintenanceDeviceItemId,i.DeviceType,i.DeviceOrdinal,i.SerialNo,i.Status,i.CompletedBy,i.CompletedAt,i.Notes,i.SecurityDeviceId,
       i.WorkOrderId,w.WorkOrderNo,COALESCE(i.Zone,sd.Location)
FROM dbo.MaintenanceDeviceItems i LEFT JOIN dbo.WorkOrders w ON w.WorkOrderId=i.WorkOrderId
LEFT JOIN dbo.SecurityDevices sd ON sd.SecurityDeviceId=i.SecurityDeviceId
WHERE i.MaintenancePlanId=@PlanId ORDER BY i.DeviceType,i.DeviceOrdinal",db);
    cmd.Parameters.AddWithValue("@PlanId",planId);
    var rows=new List<object>(); await using var r=await cmd.ExecuteReaderAsync();
    while(await r.ReadAsync()) rows.Add(new { id=r.GetInt64(0),deviceType=r.GetString(1),ordinal=r.GetInt32(2),serialNo=r.IsDBNull(3)?null:r.GetString(3),status=r.GetString(4),completedBy=r.IsDBNull(5)?null:r.GetString(5),completedAt=r.IsDBNull(6)?(DateTime?)null:r.GetDateTime(6),notes=r.IsDBNull(7)?null:r.GetString(7),securityDeviceId=r.IsDBNull(8)?(long?)null:r.GetInt64(8),workOrderId=r.IsDBNull(9)?(long?)null:r.GetInt64(9),workOrderNo=r.IsDBNull(10)?null:r.GetString(10),zone=r.IsDBNull(11)?null:r.GetString(11)});
    return Results.Ok(rows);
});

// V1.8: Tek plan donemindeki cihazlarin her birinin kendi PB is emri var.
app.MapPost("/api/maintenance/plans/{planId:long}/devices/initialize", async (HttpContext ctx, long planId) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "maintenance.manage")) return Results.Forbid();
    if (!UnitAllowed(user, "Güvenlik Sistemleri")) return Results.Forbid();
    await using var db = new SqlConnection(connectionString); await db.OpenAsync();
    var plan = new SqlCommand(@"SELECT c.CustomerName,c.CurrentAddress,c.ProductsText,p.GeneratedWorkOrderId,p.TargetDate,p.SequenceNo,c.AnnualFrequency
FROM dbo.MaintenancePlans p JOIN dbo.MaintenanceContracts c ON c.MaintenanceContractId=p.MaintenanceContractId
WHERE p.MaintenancePlanId=@Id AND p.IsCompleted=0", db);
    plan.Parameters.AddWithValue("@Id", planId);
    string customer, products; string? address; long? previous; DateOnly target; int seq, freq;
    await using (var r=await plan.ExecuteReaderAsync())
    {
        if (!await r.ReadAsync()) return Results.NotFound(new { message="Açık bakım dönemi bulunamadı." });
        customer=r.GetString(0); address=r.IsDBNull(1)?null:r.GetString(1);
        products=r.IsDBNull(2)?"":r.GetString(2); previous=r.IsDBNull(3)?null:r.GetInt64(3);
        target=DateOnly.FromDateTime(r.GetDateTime(4)); seq=r.GetInt32(5); freq=r.GetInt32(6);
    }
    var count=await EnsureIndividualMaintenanceWorkOrdersAsync(db,planId,previous,customer,address,products,target,seq,freq);
    return Results.Ok(new { created=count, message=$"{count} yeni cihaz iş emri oluşturuldu. Mevcut kayıtlar korunup tekrar oluşturulmadı." });
});

// Bakim cihazlari plan ekrani, bireysel PB numaralari ile listelenir.
app.MapGet("/api/maintenance/workorders/{workOrderId:long}/form", async (HttpContext ctx, long workOrderId) =>
{
    var user=GetCurrentUser(ctx,sessions);
    if(user is null) return Results.Unauthorized();
    if(!Can(user,"workorders.view") && !Can(user,"maintenance.view")) return Results.Forbid();
    if(!await CanAccessWorkOrderAsync(connectionString,workOrderId,user)) return Results.Forbid();
    await using var db=new SqlConnection(connectionString); await db.OpenAsync();
    var cmd=new SqlCommand(@"SELECT i.MaintenanceDeviceItemId,i.MaintenancePlanId,i.DeviceType,i.DeviceOrdinal,i.SerialNo,
COALESCE(i.Zone,sd.Location),i.Notes,i.PerformedWork,i.SpareParts,i.ServiceResult,i.Status,i.CompletedBy,i.CompletedAt,
w.WorkOrderNo,w.CustomerName,w.Status,sd.Brand,sd.Model,c.CurrentAddress
FROM dbo.MaintenanceDeviceItems i
JOIN dbo.WorkOrders w ON w.WorkOrderId=i.WorkOrderId
JOIN dbo.MaintenancePlans p ON p.MaintenancePlanId=i.MaintenancePlanId
JOIN dbo.MaintenanceContracts c ON c.MaintenanceContractId=p.MaintenanceContractId
LEFT JOIN dbo.SecurityDevices sd ON sd.SecurityDeviceId=i.SecurityDeviceId
WHERE i.WorkOrderId=@Id",db);
    cmd.Parameters.AddWithValue("@Id",workOrderId);
    long itemId; object form;
    await using(var r=await cmd.ExecuteReaderAsync())
    {
        if(!await r.ReadAsync()) return Results.NotFound(new {message="Cihaz bakım formu bulunamadı."});
        itemId=r.GetInt64(0);
        form=new {
            workOrderId, itemId, planId=r.GetInt64(1),deviceType=r.GetString(2),deviceOrdinal=r.GetInt32(3),
            serialNo=r.IsDBNull(4)?null:r.GetString(4),zone=r.IsDBNull(5)?null:r.GetString(5),
            notes=r.IsDBNull(6)?null:r.GetString(6),performedWork=r.IsDBNull(7)?null:r.GetString(7),
            spareParts=r.IsDBNull(8)?null:r.GetString(8),serviceResult=r.IsDBNull(9)?null:r.GetString(9),
            itemStatus=r.GetString(10),completedBy=r.IsDBNull(11)?null:r.GetString(11),
            completedAt=r.IsDBNull(12)?(DateTime?)null:r.GetDateTime(12),workOrderNo=r.GetString(13),
            customerName=r.GetString(14),workOrderStatus=r.GetString(15),
            brand=r.IsDBNull(16)?null:r.GetString(16),model=r.IsDBNull(17)?null:r.GetString(17),
            customerAddress=r.IsDBNull(18)?null:r.GetString(18)
        };
    }
    var checks=new List<object>();
    var qc=new SqlCommand("SELECT CheckCode,CheckLabel,CheckResult FROM dbo.MaintenanceDeviceChecks WHERE MaintenanceDeviceItemId=@Id ORDER BY MaintenanceDeviceCheckId",db);
    qc.Parameters.AddWithValue("@Id",itemId);
    await using(var r=await qc.ExecuteReaderAsync()) while(await r.ReadAsync())
        checks.Add(new{ code=r.GetString(0),label=r.GetString(1),result=r.GetString(2) });
    return Results.Ok(new { form, checks });
});

app.MapPost("/api/maintenance/workorders/{workOrderId:long}/form", async (HttpContext ctx,long workOrderId,MaintenanceFormSaveRequest req) =>
{
    var user=GetCurrentUser(ctx,sessions);
    if(user is null) return Results.Unauthorized();
    if(!Can(user,"workorders.close") && !Can(user,"maintenance.manage")) return Results.Forbid();
    if(!await CanAccessWorkOrderAsync(connectionString,workOrderId,user)) return Results.Forbid();
    if(req.Checks is null) return Results.BadRequest(new {message="Kontrol listesi zorunludur."});
    if(req.SerialNo?.Trim().Length>200 || req.Zone?.Trim().Length>250 || req.Notes?.Length>1000 || req.SpareParts?.Length>1000)
        return Results.BadRequest(new{message="Alan uzunluklarını kontrol edin."});
    var allowedChecks=new HashSet<string>(StringComparer.OrdinalIgnoreCase){"Bekliyor","Uygun","Uygunsuz","Kontrol Edilemedi"};
    if(req.Checks.Any(x=>!allowedChecks.Contains(x.Result ?? "")) || req.Checks.GroupBy(x=>x.Code,StringComparer.OrdinalIgnoreCase).Any(g=>g.Count()>1))
        return Results.BadRequest(new{message="Kontrol maddelerinde geçersiz veya tekrar eden kayıt var."});
    var allowedResults=new HashSet<string>{"Tamamlandı","Tekrar Gidilecek","Teklif Sunulacak","Servise Alındı","Servis İptal"};
    if(!string.IsNullOrWhiteSpace(req.ServiceResult) && !allowedResults.Contains(req.ServiceResult))
        return Results.BadRequest(new{message="Geçersiz servis sonucu."});

    await using var db=new SqlConnection(connectionString); await db.OpenAsync();
    await using var tx=(SqlTransaction)await db.BeginTransactionAsync(System.Data.IsolationLevel.Serializable);
    var find=new SqlCommand(@"SELECT i.MaintenanceDeviceItemId,i.MaintenancePlanId,i.Status,w.Status
FROM dbo.MaintenanceDeviceItems i WITH(UPDLOCK,HOLDLOCK)
JOIN dbo.WorkOrders w ON w.WorkOrderId=i.WorkOrderId WHERE i.WorkOrderId=@Id",db,tx);
    find.Parameters.AddWithValue("@Id",workOrderId);
    long itemId,planId;string oldItemStatus,oldWoStatus;
    await using(var r=await find.ExecuteReaderAsync())
    {
        if(!await r.ReadAsync()) return Results.NotFound(new{message="Bakım iş emri bulunamadı."});
        itemId=r.GetInt64(0);planId=r.GetInt64(1);oldItemStatus=r.GetString(2);oldWoStatus=r.GetString(3);
    }
    if(oldWoStatus=="Kapatıldı") return Results.BadRequest(new{message="Kapatılmış bakım formu değiştirilemez."});

    var checkRows=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
    var checkSql=new SqlCommand("SELECT CheckCode,CheckResult FROM dbo.MaintenanceDeviceChecks WITH(UPDLOCK,HOLDLOCK) WHERE MaintenanceDeviceItemId=@Id",db,tx);
    checkSql.Parameters.AddWithValue("@Id",itemId);
    await using(var r=await checkSql.ExecuteReaderAsync()) while(await r.ReadAsync()) checkRows[r.GetString(0)]=r.GetString(1);
    if(checkRows.Count==0) return Results.BadRequest(new{message="Bu cihaz için kontrol listesi oluşturulmamış."});
    if(req.Checks.Any(x=>!checkRows.ContainsKey(x.Code))) return Results.BadRequest(new{message="Tanımsız kontrol maddesi."});
    foreach(var check in req.Checks)
    {
        var updateCheck=new SqlCommand(@"UPDATE dbo.MaintenanceDeviceChecks SET CheckResult=@Result,
CheckedBy=CASE WHEN @Result=N'Bekliyor' THEN NULL ELSE @User END,
CheckedAt=CASE WHEN @Result=N'Bekliyor' THEN NULL ELSE SYSDATETIME() END
WHERE MaintenanceDeviceItemId=@ItemId AND CheckCode=@Code",db,tx);
        updateCheck.Parameters.AddWithValue("@Result",check.Result);
        updateCheck.Parameters.AddWithValue("@User",user.FullName);
        updateCheck.Parameters.AddWithValue("@ItemId",itemId);
        updateCheck.Parameters.AddWithValue("@Code",check.Code);
        await updateCheck.ExecuteNonQueryAsync();
        checkRows[check.Code]=check.Result;
    }
    if(req.Complete)
    {
        var liveMaintenance = new SqlCommand("SELECT COUNT(*) FROM dbo.WorkOrderLiveSessions WHERE WorkOrderId=@Id AND EndedAt IS NULL", db, tx);
        liveMaintenance.Parameters.AddWithValue("@Id", workOrderId);
        if (Convert.ToInt32(await liveMaintenance.ExecuteScalarAsync()) > 0)
            return Results.Conflict(new { message = "Bakımı kapatmadan önce bu işte çalışan personel zaman sayaçlarını bitirin." });
        if(string.IsNullOrWhiteSpace(req.SerialNo) || string.IsNullOrWhiteSpace(req.Zone) || string.IsNullOrWhiteSpace(req.Notes) || string.IsNullOrWhiteSpace(req.ServiceResult))
            return Results.BadRequest(new{message="Kapatmadan önce seri no, cihazın bölgesi, işlem notu ve servis sonucunu girin."});
        if(checkRows.Values.Any(x=>x=="Bekliyor")) return Results.BadRequest(new{message="Kontrol listesindeki tüm maddeleri değerlendirmeniz gerekiyor."});
        if(req.ServiceResult=="Tamamlandı" && checkRows.Values.Any(x=>x!="Uygun"))
            return Results.BadRequest(new{message="Uygunsuz veya kontrol edilemeyen madde var. Sonucu tekrar gidilecek/teklif/servis olarak seçin."});
        var duplicate=new SqlCommand(@"SELECT COUNT(*) FROM dbo.MaintenanceDeviceItems
WHERE MaintenancePlanId=@PlanId AND MaintenanceDeviceItemId<>@ItemId
AND LTRIM(RTRIM(SerialNo))=LTRIM(RTRIM(@Serial))",db,tx);
        duplicate.Parameters.AddWithValue("@PlanId",planId); duplicate.Parameters.AddWithValue("@ItemId",itemId);duplicate.Parameters.AddWithValue("@Serial",req.SerialNo.Trim());
        if(Convert.ToInt32(await duplicate.ExecuteScalarAsync())>0) return Results.BadRequest(new{message="Bu bakım döneminde aynı seri numarası başka cihaz iş emrinde kayıtlı."});
    }
    var completed=req.Complete && req.ServiceResult=="Tamamlandı";
    var newWoStatus=req.Complete?(completed?"Kapatıldı":"Beklemede"):oldWoStatus;
    var noteCmd=new SqlCommand(@"UPDATE dbo.MaintenanceDeviceItems SET
SerialNo=COALESCE(@Serial,SerialNo),Zone=COALESCE(@Zone,Zone),Notes=COALESCE(@Notes,Notes),
PerformedWork=COALESCE(@Work,PerformedWork),SpareParts=COALESCE(@Parts,SpareParts),ServiceResult=COALESCE(@Result,ServiceResult),
Status=@ItemStatus,CompletedBy=CASE WHEN @Done=1 THEN @User ELSE NULL END,
CompletedAt=CASE WHEN @Done=1 THEN SYSDATETIME() ELSE NULL END
WHERE MaintenanceDeviceItemId=@ItemId;
UPDATE dbo.WorkOrders SET SerialNo=COALESCE(@Serial,SerialNo),Location=COALESCE(@Zone,Location),Description=COALESCE(@Work,Description),
Status=@WoStatus,UpdatedAt=SYSDATETIME(),ClosedAt=CASE WHEN @Done=1 THEN SYSDATETIME() ELSE NULL END
WHERE WorkOrderId=@WoId;",db,tx);
    noteCmd.Parameters.AddWithValue("@Serial",Db(req.SerialNo?.Trim()));
    noteCmd.Parameters.AddWithValue("@Zone",Db(req.Zone?.Trim()));
    noteCmd.Parameters.AddWithValue("@Notes",Db(req.Notes?.Trim()));
    noteCmd.Parameters.AddWithValue("@Work",Db(req.PerformedWork?.Trim()));
    noteCmd.Parameters.AddWithValue("@Parts",Db(req.SpareParts?.Trim()));
    noteCmd.Parameters.AddWithValue("@Result",Db(req.ServiceResult));
    noteCmd.Parameters.AddWithValue("@ItemStatus",completed?"Tamamlandı":"Bekliyor");
    noteCmd.Parameters.AddWithValue("@Done",completed);
    noteCmd.Parameters.AddWithValue("@User",user.FullName);
    noteCmd.Parameters.AddWithValue("@WoStatus",newWoStatus);
    noteCmd.Parameters.AddWithValue("@ItemId",itemId);
    noteCmd.Parameters.AddWithValue("@WoId",workOrderId);
    await noteCmd.ExecuteNonQueryAsync();
    if(req.Complete)
    {
        await InsertStatusLogAsync(db,tx,workOrderId,oldWoStatus,newWoStatus,req.Notes,user);
        // Bakim periyodu ancak tum cihazlar "Tamamlandı" oldugunda kapanir.
        var finish=new SqlCommand(@"IF EXISTS(SELECT 1 FROM dbo.MaintenanceDeviceItems WHERE MaintenancePlanId=@PlanId)
AND NOT EXISTS(SELECT 1 FROM dbo.MaintenanceDeviceItems WHERE MaintenancePlanId=@PlanId AND Status<>N'Tamamlandı')
BEGIN
    UPDATE dbo.MaintenancePlans SET IsCompleted=1,CompletedAt=SYSDATETIME()
    WHERE MaintenancePlanId=@PlanId AND IsCompleted=0;
    IF @@ROWCOUNT=1
    BEGIN
        UPDATE c SET CompletedCount=CASE WHEN CompletedCount<AnnualFrequency THEN CompletedCount+1 ELSE CompletedCount END,
           UpdatedAt=SYSDATETIME()
        FROM dbo.MaintenanceContracts c JOIN dbo.MaintenancePlans p ON p.MaintenanceContractId=c.MaintenanceContractId
        WHERE p.MaintenancePlanId=@PlanId;
    END
END",db,tx);
        finish.Parameters.AddWithValue("@PlanId",planId);
        await finish.ExecuteNonQueryAsync();
    }
    await tx.CommitAsync();
    return Results.Ok(new{message=completed?"Cihazın bakım iş emri kapatıldı.":req.Complete?"Servis sonucu kaydedildi; takip gereken iş emri açık kaldı.":"Bakım formu taslak olarak kaydedildi.",status=newWoStatus});
});

// Pilot V1.5 - Haberleşme atölye teknik servis / Logo CRM uyumlu alanlar
app.MapGet("/api/workshop/tickets", async (HttpContext ctx) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "workshop.view") && !Can(user, "workorders.view")) return Results.Forbid();
    if (!UnitAllowed(user, "Haberleşme")) return Results.Forbid();

    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    var command = new SqlCommand(@"
SELECT WorkshopTicketId,WorkshopNo,WorkOrderId,LogoFormNo,LogoMainServiceNo,CompanyName,CompanyAddress,ContactName,
       CustomerEmail,CustomerPhone,EntryDate,EstimatedFinishDate,CompletionDate,IntegrationCompany,ServiceType,Status,
       RepairAmount,ReceiveType,ReceivedBy,DeliveredBy,DeliveryType,CargoTrackingNo,AssignedTo,Brand,Model,SerialNo,
       WarrantyStartDate,WarrantyEndDate,WarrantyStatus,Accessory1,Accessory2,Accessory3,Accessory4,Accessory5,ProjectName,
       Notes,CustomerComplaint,DeviceCondition,RepairInfo,CreatedAt,UpdatedAt
FROM dbo.WorkshopTickets
ORDER BY WorkshopTicketId DESC", connection);

    var rows = new List<object>();
    await using var reader = await command.ExecuteReaderAsync();
    while (await reader.ReadAsync())
        rows.Add(new
        {
            workshopTicketId = reader.GetInt64(0),
            workshopNo = reader.GetString(1),
            workOrderId = reader.IsDBNull(2) ? (long?)null : reader.GetInt64(2),
            logoFormNo = reader.IsDBNull(3) ? null : reader.GetString(3),
            logoMainServiceNo = reader.IsDBNull(4) ? null : reader.GetString(4),
            companyName = reader.GetString(5),
            companyAddress = reader.IsDBNull(6) ? null : reader.GetString(6),
            contactName = reader.IsDBNull(7) ? null : reader.GetString(7),
            customerEmail = reader.IsDBNull(8) ? null : reader.GetString(8),
            customerPhone = reader.IsDBNull(9) ? null : reader.GetString(9),
            entryDate = reader.GetDateTime(10),
            estimatedFinishDate = reader.IsDBNull(11) ? (DateOnly?)null : DateOnly.FromDateTime(reader.GetDateTime(11)),
            completionDate = reader.IsDBNull(12) ? (DateTime?)null : reader.GetDateTime(12),
            integrationCompany = reader.IsDBNull(13) ? null : reader.GetString(13),
            serviceType = reader.GetString(14),
            status = reader.GetString(15),
            repairAmount = reader.IsDBNull(16) ? (decimal?)null : reader.GetDecimal(16),
            receiveType = reader.IsDBNull(17) ? null : reader.GetString(17),
            receivedBy = reader.IsDBNull(18) ? null : reader.GetString(18),
            deliveredBy = reader.IsDBNull(19) ? null : reader.GetString(19),
            deliveryType = reader.IsDBNull(20) ? null : reader.GetString(20),
            cargoTrackingNo = reader.IsDBNull(21) ? null : reader.GetString(21),
            assignedTo = reader.IsDBNull(22) ? null : reader.GetString(22),
            brand = reader.GetString(23),
            model = reader.IsDBNull(24) ? null : reader.GetString(24),
            serialNo = reader.GetString(25),
            warrantyStartDate = reader.IsDBNull(26) ? (DateOnly?)null : DateOnly.FromDateTime(reader.GetDateTime(26)),
            warrantyEndDate = reader.IsDBNull(27) ? (DateOnly?)null : DateOnly.FromDateTime(reader.GetDateTime(27)),
            warrantyStatus = reader.IsDBNull(28) ? null : reader.GetString(28),
            accessory1 = reader.IsDBNull(29) ? null : reader.GetString(29),
            accessory2 = reader.IsDBNull(30) ? null : reader.GetString(30),
            accessory3 = reader.IsDBNull(31) ? null : reader.GetString(31),
            accessory4 = reader.IsDBNull(32) ? null : reader.GetString(32),
            accessory5 = reader.IsDBNull(33) ? null : reader.GetString(33),
            projectName = reader.IsDBNull(34) ? null : reader.GetString(34),
            notes = reader.IsDBNull(35) ? null : reader.GetString(35),
            customerComplaint = reader.IsDBNull(36) ? null : reader.GetString(36),
            deviceCondition = reader.IsDBNull(37) ? null : reader.GetString(37),
            repairInfo = reader.IsDBNull(38) ? null : reader.GetString(38),
            createdAt = reader.GetDateTime(39),
            updatedAt = reader.IsDBNull(40) ? (DateTime?)null : reader.GetDateTime(40)
        });
    return Results.Ok(rows);
});

app.MapPost("/api/workshop/tickets", async (HttpContext ctx, WorkshopTicketRequest request) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "workshop.manage") && !Can(user, "workorders.create")) return Results.Forbid();
    if (!UnitAllowed(user, "Haberleşme")) return Results.Forbid();

    if (string.IsNullOrWhiteSpace(request.CompanyName) || string.IsNullOrWhiteSpace(request.ServiceType) ||
        string.IsNullOrWhiteSpace(request.Brand) || string.IsNullOrWhiteSpace(request.SerialNo))
        return Results.BadRequest(new { message = "Firma, servis türü, marka ve seri no zorunludur." });

    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    await using var transaction = (SqlTransaction)await connection.BeginTransactionAsync();

    var woPrefix = $"SRV-{DateTime.Now:yyyyMM}-";
    var woNumberCommand = new SqlCommand(@"
SELECT ISNULL(MAX(TRY_CONVERT(INT, RIGHT(WorkOrderNo,4))),0)+1
FROM dbo.WorkOrders WITH(UPDLOCK,HOLDLOCK)
WHERE WorkOrderNo LIKE @Prefix+'%'", connection, transaction);
    woNumberCommand.Parameters.AddWithValue("@Prefix", woPrefix);
    var woNext = Convert.ToInt32(await woNumberCommand.ExecuteScalarAsync());
    var workOrderNo = $"{woPrefix}{woNext:0000}";

    var subject = $"{request.Brand} {request.Model ?? ""} Atölye Teknik Servis".Trim();
    var workOrderCommand = new SqlCommand(@"
INSERT INTO dbo.WorkOrders
(WorkOrderNo,UnitCode,WorkType,CustomerName,ProjectName,Location,Subject,Description,Priority,Status,CreatedByUserId,CreatedByErpUserId,SystemName,SerialNo,CustomerEmail,UpdatedAt)
OUTPUT INSERTED.WorkOrderId
VALUES(@No,N'Haberleşme',N'Atölye Teknik Servis',@Customer,@Project,N'Atölye',@Subject,@Description,N'Normal',N'Atölyede',NULL,@UserId,@SystemName,@Serial,@Email,SYSDATETIME())", connection, transaction);
    workOrderCommand.Parameters.AddWithValue("@No", workOrderNo);
    workOrderCommand.Parameters.AddWithValue("@Customer", request.CompanyName.Trim());
    workOrderCommand.Parameters.AddWithValue("@Project", Db(request.ProjectName));
    workOrderCommand.Parameters.AddWithValue("@Subject", subject);
    workOrderCommand.Parameters.AddWithValue("@Description", Db(request.CustomerComplaint));
    workOrderCommand.Parameters.AddWithValue("@UserId", user.UserId);
    workOrderCommand.Parameters.AddWithValue("@SystemName", $"{request.Brand} {request.Model ?? ""}".Trim());
    workOrderCommand.Parameters.AddWithValue("@Serial", request.SerialNo.Trim());
    workOrderCommand.Parameters.AddWithValue("@Email", Db(request.CustomerEmail));
    var workOrderId = Convert.ToInt64(await workOrderCommand.ExecuteScalarAsync());

    var device = new SqlCommand(@"
INSERT INTO dbo.WorkOrderDevices(WorkOrderId,SerialNo,ProductName,IsActive)
VALUES(@WorkOrderId,@Serial,@ProductName,1)", connection, transaction);
    device.Parameters.AddWithValue("@WorkOrderId", workOrderId);
    device.Parameters.AddWithValue("@Serial", request.SerialNo.Trim());
    device.Parameters.AddWithValue("@ProductName", $"{request.Brand} {request.Model ?? ""}".Trim());
    await device.ExecuteNonQueryAsync();

    var prefix = $"AT-{DateTime.Now:yyyyMM}-";
    var numberCommand = new SqlCommand(@"
SELECT ISNULL(MAX(TRY_CONVERT(INT,RIGHT(WorkshopNo,4))),0)+1
FROM dbo.WorkshopTickets WITH(UPDLOCK,HOLDLOCK)
WHERE WorkshopNo LIKE @Prefix+'%'", connection, transaction);
    numberCommand.Parameters.AddWithValue("@Prefix", prefix);
    var next = Convert.ToInt32(await numberCommand.ExecuteScalarAsync());
    var workshopNo = $"{prefix}{next:0000}";

    var command = new SqlCommand(@"
INSERT INTO dbo.WorkshopTickets
(WorkshopNo,WorkOrderId,LogoFormNo,LogoMainServiceNo,CompanyName,CompanyAddress,ContactName,CustomerEmail,CustomerPhone,
 EntryDate,EstimatedFinishDate,IntegrationCompany,ServiceType,Status,RepairAmount,ReceiveType,ReceivedBy,DeliveredBy,
 DeliveryType,CargoTrackingNo,AssignedTo,Brand,Model,SerialNo,WarrantyStartDate,WarrantyEndDate,WarrantyStatus,
 Accessory1,Accessory2,Accessory3,Accessory4,Accessory5,ProjectName,Notes,CustomerComplaint,DeviceCondition,RepairInfo,CreatedByUserId)
OUTPUT INSERTED.WorkshopTicketId
VALUES
(@WorkshopNo,@WorkOrderId,@LogoFormNo,@LogoMainServiceNo,@CompanyName,@CompanyAddress,@ContactName,@CustomerEmail,@CustomerPhone,
 @EntryDate,@EstimatedFinishDate,@IntegrationCompany,@ServiceType,@Status,@RepairAmount,@ReceiveType,@ReceivedBy,@DeliveredBy,
 @DeliveryType,@CargoTrackingNo,@AssignedTo,@Brand,@Model,@SerialNo,@WarrantyStartDate,@WarrantyEndDate,@WarrantyStatus,
 @Accessory1,@Accessory2,@Accessory3,@Accessory4,@Accessory5,@ProjectName,@Notes,@CustomerComplaint,@DeviceCondition,@RepairInfo,@UserId)", connection, transaction);
    AddWorkshopParameters(command, request, workshopNo, workOrderId, user.UserId);
    var ticketId = Convert.ToInt64(await command.ExecuteScalarAsync());

    await InsertStatusLogAsync(connection, transaction, workOrderId, null, "Atölyede", $"Atölye kaydı oluşturuldu: {workshopNo}", user);
    await transaction.CommitAsync();

    return Results.Ok(new { workshopTicketId = ticketId, workshopNo, workOrderId, workOrderNo });
});

app.MapPut("/api/workshop/tickets/{id:long}", async (HttpContext ctx, long id, WorkshopTicketRequest request) =>
{
    var user = GetCurrentUser(ctx, sessions);
    if (user is null) return Results.Unauthorized();
    if (!Can(user, "workshop.manage") && !Can(user, "workorders.edit")) return Results.Forbid();
    if (!UnitAllowed(user, "Haberleşme")) return Results.Forbid();

    if (string.IsNullOrWhiteSpace(request.CompanyName) || string.IsNullOrWhiteSpace(request.ServiceType) ||
        string.IsNullOrWhiteSpace(request.Brand) || string.IsNullOrWhiteSpace(request.SerialNo))
        return Results.BadRequest(new { message = "Firma, servis türü, marka ve seri no zorunludur." });

    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    await using var transaction = (SqlTransaction)await connection.BeginTransactionAsync();

    long? workOrderId = null;
    var current = new SqlCommand("SELECT WorkOrderId FROM dbo.WorkshopTickets WHERE WorkshopTicketId=@Id", connection, transaction);
    current.Parameters.AddWithValue("@Id", id);
    var currentResult = await current.ExecuteScalarAsync();
    if (currentResult is null || currentResult == DBNull.Value)
        return Results.NotFound(new { message = "Atölye kaydı bulunamadı." });
    workOrderId = Convert.ToInt64(currentResult);

    var command = new SqlCommand(@"
UPDATE dbo.WorkshopTickets SET
LogoFormNo=@LogoFormNo,LogoMainServiceNo=@LogoMainServiceNo,CompanyName=@CompanyName,CompanyAddress=@CompanyAddress,
ContactName=@ContactName,CustomerEmail=@CustomerEmail,CustomerPhone=@CustomerPhone,EntryDate=@EntryDate,
EstimatedFinishDate=@EstimatedFinishDate,CompletionDate=@CompletionDate,IntegrationCompany=@IntegrationCompany,
ServiceType=@ServiceType,Status=@Status,RepairAmount=@RepairAmount,ReceiveType=@ReceiveType,ReceivedBy=@ReceivedBy,
DeliveredBy=@DeliveredBy,DeliveryType=@DeliveryType,CargoTrackingNo=@CargoTrackingNo,AssignedTo=@AssignedTo,
Brand=@Brand,Model=@Model,SerialNo=@SerialNo,WarrantyStartDate=@WarrantyStartDate,WarrantyEndDate=@WarrantyEndDate,
WarrantyStatus=@WarrantyStatus,Accessory1=@Accessory1,Accessory2=@Accessory2,Accessory3=@Accessory3,Accessory4=@Accessory4,
Accessory5=@Accessory5,ProjectName=@ProjectName,Notes=@Notes,CustomerComplaint=@CustomerComplaint,DeviceCondition=@DeviceCondition,
RepairInfo=@RepairInfo,UpdatedAt=SYSDATETIME()
WHERE WorkshopTicketId=@Id", connection, transaction);
    AddWorkshopParameters(command, request, "", workOrderId.Value, user.UserId, includeIdentityFields: false);
    command.Parameters.AddWithValue("@Id", id);
    await command.ExecuteNonQueryAsync();

    var woStatus = request.Status switch
    {
        "Yeni Kayıt" => "Atölyede",
        "Onarımda" => "İşlemde",
        "Beklemede" => "Beklemede",
        "Test / Kontrol" => "Test / Kontrol",
        "Tamamlandı" => "Tamamlandı",
        "Teslim Edildi" => "Kapatıldı",
        _ => "Atölyede"
    };

    var updateWo = new SqlCommand(@"
UPDATE dbo.WorkOrders
SET CustomerName=@Customer,ProjectName=@Project,Subject=@Subject,Description=@Description,SystemName=@SystemName,
    SerialNo=@Serial,CustomerEmail=@Email,Status=@Status,UpdatedAt=SYSDATETIME(),
    ClosedAt=CASE WHEN @Status=N'Kapatıldı' THEN SYSDATETIME() ELSE ClosedAt END
WHERE WorkOrderId=@WorkOrderId", connection, transaction);
    updateWo.Parameters.AddWithValue("@Customer", request.CompanyName.Trim());
    updateWo.Parameters.AddWithValue("@Project", Db(request.ProjectName));
    updateWo.Parameters.AddWithValue("@Subject", $"{request.Brand} {request.Model ?? ""} Atölye Teknik Servis".Trim());
    updateWo.Parameters.AddWithValue("@Description", Db(request.CustomerComplaint));
    updateWo.Parameters.AddWithValue("@SystemName", $"{request.Brand} {request.Model ?? ""}".Trim());
    updateWo.Parameters.AddWithValue("@Serial", request.SerialNo.Trim());
    updateWo.Parameters.AddWithValue("@Email", Db(request.CustomerEmail));
    updateWo.Parameters.AddWithValue("@Status", woStatus);
    updateWo.Parameters.AddWithValue("@WorkOrderId", workOrderId.Value);
    await updateWo.ExecuteNonQueryAsync();

    await transaction.CommitAsync();
    return Results.Ok(new { message = "Atölye kaydı güncellendi." });
});

OpsSuite.Map(app, connectionString, ctx => GetCurrentUser(ctx, sessions), Can, UnitAllowed,
    () => LoadWorkOrdersAsync(connectionString), FilterWorkOrdersForUser, () => LoadTimeLogsAsync(connectionString));
app.Run();


// V1.13 - ortak salt-okunur SQL veri dönüşümü.
static async Task<List<Dictionary<string,object?>>> TrainingRowsAsync(SqlCommand cmd)
{
    var rows=new List<Dictionary<string,object?>>();
    await using var reader=await cmd.ExecuteReaderAsync();
    while(await reader.ReadAsync())
    {
        var row=new Dictionary<string,object?>(StringComparer.OrdinalIgnoreCase);
        for(var i=0;i<reader.FieldCount;i++)row[reader.GetName(i)]=reader.IsDBNull(i)?null:reader.GetValue(i);
        rows.Add(row);
    }
    return rows;
}
static async Task<bool> TrainingCanAccessPersonnelAsync(SqlConnection db,SessionUser user,long id)
{
    await using var command=new SqlCommand("SELECT UnitCode FROM dbo.Personnel WHERE PersonnelId=@Id AND IsActive=1",db);
    command.Parameters.AddWithValue("@Id",id);
    var unit=await command.ExecuteScalarAsync();
    return unit is not null && (unit==DBNull.Value ? IsAdmin(user) || user.AllowedUnits.Count==0 : UnitAllowed(user,(string)unit));
}

static string[] GetRoleDefaults(string role) => Catalog.RoleDefaults.TryGetValue(role ?? "", out var p) ? p : ["workorders.view"];
static bool IsAdmin(SessionUser user) => user.Permissions.Contains("*") || user.RoleName == "Admin";
static bool Can(SessionUser user, string permission) => user.Permissions.Contains("*") || user.Permissions.Contains(permission);
static bool UnitAllowed(SessionUser user, string unit) => IsAdmin(user) || user.AllowedUnits.Count == 0 || user.AllowedUnits.Contains(unit, StringComparer.OrdinalIgnoreCase);
static bool IsClosingStatus(string status) => status is "Tamamlandı" or "Kapatıldı" or "Çözüldü";
static object Db(string? value) => string.IsNullOrWhiteSpace(value) ? DBNull.Value : value.Trim();
static List<string> CleanSerials(List<string>? values) => (values ?? []).SelectMany(x => (x ?? "").Split([',',';','\n','\r'], StringSplitOptions.RemoveEmptyEntries)).Select(x => x.Trim()).Where(x => x.Length > 0).Distinct(StringComparer.OrdinalIgnoreCase).ToList();
static string JoinPipe(IEnumerable<string> values) => string.Join('|', values.Where(x => !string.IsNullOrWhiteSpace(x)).Distinct());
static List<string> SplitPipe(string? value) => string.IsNullOrWhiteSpace(value) ? [] : value.Split('|', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToList();

static string? ReadToken(HttpContext ctx)
{
    var h = ctx.Request.Headers.Authorization.ToString();
    if (h.StartsWith("Bearer ", StringComparison.OrdinalIgnoreCase)) return h[7..].Trim();
    return null;
}

static SessionUser? GetCurrentUser(HttpContext ctx, ConcurrentDictionary<string, SessionUser> sessions)
{
    var token = ReadToken(ctx);
    return !string.IsNullOrWhiteSpace(token) && sessions.TryGetValue(token, out var user) ? user : null;
}

static (string Salt, string Hash) HashPassword(string password)
{
    var saltBytes = RandomNumberGenerator.GetBytes(16);
    var hashBytes = Rfc2898DeriveBytes.Pbkdf2(password, saltBytes, 120_000, HashAlgorithmName.SHA256, 32);
    return (Convert.ToBase64String(saltBytes), Convert.ToBase64String(hashBytes));
}

static bool VerifyPassword(string password, string salt, string hash)
{
    try
    {
        var saltBytes = Convert.FromBase64String(salt);
        var expected = Convert.FromBase64String(hash);
        var actual = Rfc2898DeriveBytes.Pbkdf2(password, saltBytes, 120_000, HashAlgorithmName.SHA256, 32);
        return CryptographicOperations.FixedTimeEquals(actual, expected);
    }
    catch { return false; }
}


static void AddWorkshopParameters(SqlCommand command, WorkshopTicketRequest request, string workshopNo, long workOrderId, int userId, bool includeIdentityFields = true)
{
    if (includeIdentityFields)
    {
        command.Parameters.AddWithValue("@WorkshopNo", workshopNo);
        command.Parameters.AddWithValue("@WorkOrderId", workOrderId);
        command.Parameters.AddWithValue("@UserId", userId);
    }

    command.Parameters.AddWithValue("@LogoFormNo", Db(request.LogoFormNo));
    command.Parameters.AddWithValue("@LogoMainServiceNo", Db(request.LogoMainServiceNo));
    command.Parameters.AddWithValue("@CompanyName", request.CompanyName.Trim());
    command.Parameters.AddWithValue("@CompanyAddress", Db(request.CompanyAddress));
    command.Parameters.AddWithValue("@ContactName", Db(request.ContactName));
    command.Parameters.AddWithValue("@CustomerEmail", Db(request.CustomerEmail));
    command.Parameters.AddWithValue("@CustomerPhone", Db(request.CustomerPhone));
    command.Parameters.AddWithValue("@EntryDate", request.EntryDate ?? DateTime.Now);
    command.Parameters.AddWithValue("@EstimatedFinishDate", request.EstimatedFinishDate.HasValue ? (object)request.EstimatedFinishDate.Value.ToDateTime(TimeOnly.MinValue) : DBNull.Value);
    command.Parameters.AddWithValue("@CompletionDate", request.CompletionDate.HasValue ? (object)request.CompletionDate.Value : DBNull.Value);
    command.Parameters.AddWithValue("@IntegrationCompany", Db(request.IntegrationCompany));
    command.Parameters.AddWithValue("@ServiceType", request.ServiceType);
    command.Parameters.AddWithValue("@Status", string.IsNullOrWhiteSpace(request.Status) ? "Yeni Kayıt" : request.Status);
    command.Parameters.AddWithValue("@RepairAmount", request.RepairAmount.HasValue ? (object)request.RepairAmount.Value : DBNull.Value);
    command.Parameters.AddWithValue("@ReceiveType", Db(request.ReceiveType));
    command.Parameters.AddWithValue("@ReceivedBy", Db(request.ReceivedBy));
    command.Parameters.AddWithValue("@DeliveredBy", Db(request.DeliveredBy));
    command.Parameters.AddWithValue("@DeliveryType", Db(request.DeliveryType));
    command.Parameters.AddWithValue("@CargoTrackingNo", Db(request.CargoTrackingNo));
    command.Parameters.AddWithValue("@AssignedTo", Db(request.AssignedTo));
    command.Parameters.AddWithValue("@Brand", request.Brand.Trim());
    command.Parameters.AddWithValue("@Model", Db(request.Model));
    command.Parameters.AddWithValue("@SerialNo", request.SerialNo.Trim());
    command.Parameters.AddWithValue("@WarrantyStartDate", request.WarrantyStartDate.HasValue ? (object)request.WarrantyStartDate.Value.ToDateTime(TimeOnly.MinValue) : DBNull.Value);
    command.Parameters.AddWithValue("@WarrantyEndDate", request.WarrantyEndDate.HasValue ? (object)request.WarrantyEndDate.Value.ToDateTime(TimeOnly.MinValue) : DBNull.Value);
    command.Parameters.AddWithValue("@WarrantyStatus", Db(request.WarrantyStatus));
    command.Parameters.AddWithValue("@Accessory1", Db(request.Accessory1));
    command.Parameters.AddWithValue("@Accessory2", Db(request.Accessory2));
    command.Parameters.AddWithValue("@Accessory3", Db(request.Accessory3));
    command.Parameters.AddWithValue("@Accessory4", Db(request.Accessory4));
    command.Parameters.AddWithValue("@Accessory5", Db(request.Accessory5));
    command.Parameters.AddWithValue("@ProjectName", Db(request.ProjectName));
    command.Parameters.AddWithValue("@Notes", Db(request.Notes));
    command.Parameters.AddWithValue("@CustomerComplaint", Db(request.CustomerComplaint));
    command.Parameters.AddWithValue("@DeviceCondition", Db(request.DeviceCondition));
    command.Parameters.AddWithValue("@RepairInfo", Db(request.RepairInfo));
}

static async Task<int> EnsureMaintenancePlansAndWorkOrdersAsync(string connectionString)
{
    var generated = 0;
    var today = DateOnly.FromDateTime(DateTime.Today);
    var year = today.Year;

    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();

    var contracts = new List<(long Id,string Customer,string? Address,string? Products,int Frequency,int Completed)>();
    var read = new SqlCommand(@"
SELECT MaintenanceContractId,CustomerName,CurrentAddress,ProductsText,AnnualFrequency,CompletedCount
FROM dbo.MaintenanceContracts
WHERE IsActive=1 AND AnnualFrequency>0
ORDER BY MaintenanceContractId", connection);
    await using (var reader = await read.ExecuteReaderAsync())
    {
        while (await reader.ReadAsync())
            contracts.Add((
                reader.GetInt64(0),
                reader.GetString(1),
                reader.IsDBNull(2) ? null : reader.GetString(2),
                reader.IsDBNull(3) ? null : reader.GetString(3),
                reader.GetInt32(4),
                reader.GetInt32(5)
            ));
    }

    foreach (var c in contracts)
    {
        var completed = Math.Min(Math.Max(c.Completed, 0), c.Frequency);

        for (var seq = 1; seq <= c.Frequency; seq++)
        {
            var month = 1 + (int)Math.Floor((seq - 1) * (12.0 / c.Frequency));
            month = Math.Min(Math.Max(month, 1), 12);
            var target = new DateOnly(year, month, 1);

            var planUpsert = new SqlCommand(@"
IF NOT EXISTS(SELECT 1 FROM dbo.MaintenancePlans WHERE MaintenanceContractId=@ContractId AND PlanYear=@Year AND SequenceNo=@Seq)
BEGIN
    INSERT INTO dbo.MaintenancePlans(MaintenanceContractId,PlanYear,SequenceNo,TargetDate,IsCompleted,CompletedAt)
    VALUES(@ContractId,@Year,@Seq,@Target,@Completed,CASE WHEN @Completed=1 THEN SYSDATETIME() ELSE NULL END);
END
ELSE
BEGIN
    UPDATE dbo.MaintenancePlans
    SET TargetDate=@Target,
        IsCompleted=CASE WHEN IsCompleted=1 THEN 1 ELSE @Completed END,
        CompletedAt=CASE WHEN IsCompleted=1 THEN CompletedAt WHEN @Completed=1 THEN COALESCE(CompletedAt,SYSDATETIME()) ELSE CompletedAt END
    WHERE MaintenanceContractId=@ContractId AND PlanYear=@Year AND SequenceNo=@Seq;
END", connection);
            planUpsert.Parameters.AddWithValue("@ContractId", c.Id);
            planUpsert.Parameters.AddWithValue("@Year", year);
            planUpsert.Parameters.AddWithValue("@Seq", seq);
            planUpsert.Parameters.AddWithValue("@Target", target.ToDateTime(TimeOnly.MinValue));
            planUpsert.Parameters.AddWithValue("@Completed", seq <= completed);
            await planUpsert.ExecuteNonQueryAsync();
        }

        var nextSeq = completed + 1;
        if (nextSeq > c.Frequency) continue;

        var nextMonth = 1 + (int)Math.Floor((nextSeq - 1) * (12.0 / c.Frequency));
        nextMonth = Math.Min(Math.Max(nextMonth, 1), 12);
        var nextTarget = new DateOnly(year, nextMonth, 1);
        if (nextTarget > today) continue;

        var planCommand = new SqlCommand(@"
SELECT TOP 1 MaintenancePlanId,GeneratedWorkOrderId
FROM dbo.MaintenancePlans
WHERE MaintenanceContractId=@ContractId AND PlanYear=@Year AND SequenceNo=@Seq AND IsCompleted=0", connection);
        planCommand.Parameters.AddWithValue("@ContractId", c.Id);
        planCommand.Parameters.AddWithValue("@Year", year);
        planCommand.Parameters.AddWithValue("@Seq", nextSeq);

        long planId;
        long? existingWorkOrder;
        await using (var reader = await planCommand.ExecuteReaderAsync())
        {
            if (!await reader.ReadAsync()) continue;
            planId = reader.GetInt64(0);
            existingWorkOrder = reader.IsDBNull(1) ? null : reader.GetInt64(1);
        }
        generated += await EnsureIndividualMaintenanceWorkOrdersAsync(connection,planId,existingWorkOrder,c.Customer,c.Address,c.Products,nextTarget,nextSeq,c.Frequency);
    }

    return generated;
}

// V1.8: Bir firmanin her X-Ray / kapi dedektoru icin farkli PB is emri olustur.
// Onceki V1.7 ana PB kaydi ilk cihaz icin kullanilir; kayit silinmez ve eski ID korunur.
static async Task<int> EnsureIndividualMaintenanceWorkOrdersAsync(
    SqlConnection db,long planId,long? oldWorkOrderId,string customer,string? address,
    string? products,DateOnly target,int sequence,int frequency)
{
    var matches=Regex.Matches(products??"",@"(\d+)\s*(X[\s-]*RAY|KAPI(?:\s+TİPİ)?(?:\s+METAL)?\s+DEDEKTÖR(?:Ü|U)?)", RegexOptions.IgnoreCase|RegexOptions.CultureInvariant);
    var counts=new Dictionary<string,int>();
    foreach(Match m in matches)
    {
        var type=m.Groups[2].Value.StartsWith("X",StringComparison.OrdinalIgnoreCase)?"X-Ray":"Kapı Tipi Metal Dedektörü";
        var n=int.Parse(m.Groups[1].Value);
        if(n<=0 || n>500) throw new InvalidOperationException("Bakım cihaz adedi hatalı: "+customer);
        counts[type]=counts.GetValueOrDefault(type)+n;
    }
    if(counts.Count==0) return 0; // Kaynagi teyit edilmemis cihaz sayisini uydurma.
    await using var tx=(SqlTransaction)await db.BeginTransactionAsync(System.Data.IsolationLevel.Serializable);
    int created=0;
    // Tek plan icin eszamanli istekler lock ile serilestirilir.
    var lockPlan=new SqlCommand("SELECT MaintenancePlanId FROM dbo.MaintenancePlans WITH(UPDLOCK,HOLDLOCK) WHERE MaintenancePlanId=@PlanId",db,tx);
    lockPlan.Parameters.AddWithValue("@PlanId",planId);
    if(await lockPlan.ExecuteScalarAsync() is null){await tx.RollbackAsync();return 0;}
    var usedPrevious=false;
    foreach(var entry in counts)
    {
        var inventory=new List<(long id,string? serial,string? zone)>();
        var inv=new SqlCommand(@"SELECT SecurityDeviceId,SerialNo,Location FROM dbo.SecurityDevices
WHERE IsActive=1 AND CustomerName=@Customer
AND ((@Type=N'X-Ray' AND UPPER(DeviceType) LIKE N'%RAY%')
  OR (@Type<>N'X-Ray' AND (UPPER(DeviceType) LIKE N'%KAPI%' OR UPPER(DeviceType) LIKE N'%DEDEKT%')))
ORDER BY SecurityDeviceId",db,tx);
        inv.Parameters.AddWithValue("@Customer",customer);inv.Parameters.AddWithValue("@Type",entry.Key);
        await using(var r=await inv.ExecuteReaderAsync())while(await r.ReadAsync()) inventory.Add((r.GetInt64(0),r.IsDBNull(1)?null:r.GetString(1),r.IsDBNull(2)?null:r.GetString(2)));
        for(int ordinal=1;ordinal<=entry.Value;ordinal++)
        {
            var itemQuery=new SqlCommand(@"SELECT MaintenanceDeviceItemId,WorkOrderId,SerialNo FROM dbo.MaintenanceDeviceItems WITH(UPDLOCK,HOLDLOCK)
WHERE MaintenancePlanId=@PlanId AND DeviceType=@Type AND DeviceOrdinal=@Ordinal",db,tx);
            itemQuery.Parameters.AddWithValue("@PlanId",planId);itemQuery.Parameters.AddWithValue("@Type",entry.Key);itemQuery.Parameters.AddWithValue("@Ordinal",ordinal);
            long itemId;long? woId=null;string? serial=null;
            await using(var r=await itemQuery.ExecuteReaderAsync())
            {
                if(await r.ReadAsync())
                {
                    itemId=r.GetInt64(0); woId=r.IsDBNull(1)?null:r.GetInt64(1);
                    serial=r.IsDBNull(2)?null:r.GetString(2);
                }
                else itemId=0;
            }
            var invRow=ordinal<=inventory.Count ? inventory[ordinal-1] : (0L,(string?)null,(string?)null);
            if(itemId==0)
            {
                var createItem=new SqlCommand(@"INSERT INTO dbo.MaintenanceDeviceItems
(MaintenancePlanId,SecurityDeviceId,DeviceType,DeviceOrdinal,SerialNo,Zone)
OUTPUT INSERTED.MaintenanceDeviceItemId
VALUES(@PlanId,@DeviceId,@Type,@Ordinal,@Serial,@Zone)",db,tx);
                createItem.Parameters.AddWithValue("@PlanId",planId);
                createItem.Parameters.AddWithValue("@DeviceId",invRow.Item1==0?DBNull.Value:invRow.Item1);
                createItem.Parameters.AddWithValue("@Type",entry.Key); createItem.Parameters.AddWithValue("@Ordinal",ordinal);
                createItem.Parameters.AddWithValue("@Serial",Db(invRow.Item2));createItem.Parameters.AddWithValue("@Zone",Db(invRow.Item3));
                itemId=Convert.ToInt64(await createItem.ExecuteScalarAsync());serial=invRow.Item2;
            }
            foreach(var check in MaintenanceCheckTemplate(entry.Key))
            {
                var insCheck=new SqlCommand(@"IF NOT EXISTS(SELECT 1 FROM dbo.MaintenanceDeviceChecks WHERE MaintenanceDeviceItemId=@Id AND CheckCode=@Code)
INSERT INTO dbo.MaintenanceDeviceChecks(MaintenanceDeviceItemId,CheckCode,CheckLabel) VALUES(@Id,@Code,@Label)",db,tx);
                insCheck.Parameters.AddWithValue("@Id",itemId);insCheck.Parameters.AddWithValue("@Code",check.Code);insCheck.Parameters.AddWithValue("@Label",check.Label);
                await insCheck.ExecuteNonQueryAsync();
            }
            if(woId.HasValue)
            {
                if(oldWorkOrderId==woId) usedPrevious=true;
                continue;
            }
            // V1.7'de tek PB emri zaten olusturulduysa, onu ilk cihaz emrine donustur (silme/numara degistirme yok).
            if(oldWorkOrderId.HasValue && !usedPrevious)
            {
                var usedCheck=new SqlCommand("SELECT COUNT(*) FROM dbo.MaintenanceDeviceItems WHERE WorkOrderId=@Id",db,tx);
                usedCheck.Parameters.AddWithValue("@Id",oldWorkOrderId.Value);
                if(Convert.ToInt32(await usedCheck.ExecuteScalarAsync())==0)
                {
                    woId=oldWorkOrderId;
                    usedPrevious=true;
                    var migrate=new SqlCommand(@"UPDATE dbo.WorkOrders SET SystemName=@Type,Subject=@Subject,
SerialNo=COALESCE(SerialNo,@Serial),UpdatedAt=SYSDATETIME() WHERE WorkOrderId=@Id",db,tx);
                    migrate.Parameters.AddWithValue("@Id",woId.Value);migrate.Parameters.AddWithValue("@Type",entry.Key);
                    migrate.Parameters.AddWithValue("@Subject",$"Planlı bakım • {entry.Key} #{ordinal}");migrate.Parameters.AddWithValue("@Serial",Db(serial));
                    await migrate.ExecuteNonQueryAsync();
                }
                else usedPrevious=true;
            }
            if(!woId.HasValue)
            {
                var prefix=$"PB-{target:yyyyMM}-";
                var numberCmd=new SqlCommand(@"SELECT ISNULL(MAX(TRY_CONVERT(INT,RIGHT(WorkOrderNo,4))),0)+1
FROM dbo.WorkOrders WITH(UPDLOCK,HOLDLOCK) WHERE WorkOrderNo LIKE @Prefix+'%'",db,tx);
                numberCmd.Parameters.AddWithValue("@Prefix",prefix);
                var next=Convert.ToInt32(await numberCmd.ExecuteScalarAsync());
                if(next>9999)throw new InvalidOperationException("Aylık PB numara sınırı aşıldı.");
                var number=$"{prefix}{next:0000}";
                var insWo=new SqlCommand(@"INSERT INTO dbo.WorkOrders
(WorkOrderNo,UnitCode,WorkType,CustomerName,Location,Subject,Description,Priority,Status,CreatedByUserId,CreatedByErpUserId,SystemName,SerialNo,UpdatedAt)
OUTPUT INSERTED.WorkOrderId
VALUES(@No,N'Güvenlik Sistemleri',N'Planlı Bakım',@Customer,@Location,@Subject,@Description,N'Normal',N'Müşteri Talebi',NULL,NULL,@Type,@Serial,SYSDATETIME())",db,tx);
                insWo.Parameters.AddWithValue("@No",number);insWo.Parameters.AddWithValue("@Customer",customer);
                insWo.Parameters.AddWithValue("@Location",Db(invRow.Item3??address));
                insWo.Parameters.AddWithValue("@Subject",$"Planlı bakım • {entry.Key} #{ordinal}");
                insWo.Parameters.AddWithValue("@Description",$"{sequence}/{frequency} bakım dönemi, hedef {target:dd.MM.yyyy}. Cihaz bölgesi, seri numarası ve bakım kontrol listesi teknisyen tarafından doldurulacaktır.");
                insWo.Parameters.AddWithValue("@Type",entry.Key);insWo.Parameters.AddWithValue("@Serial",Db(serial));
                woId=Convert.ToInt64(await insWo.ExecuteScalarAsync());created++;
            }
            var link=new SqlCommand(@"UPDATE dbo.MaintenanceDeviceItems SET WorkOrderId=@WoId WHERE MaintenanceDeviceItemId=@ItemId;
UPDATE dbo.MaintenancePlans SET GeneratedWorkOrderId=COALESCE(GeneratedWorkOrderId,@WoId) WHERE MaintenancePlanId=@PlanId;",db,tx);
            link.Parameters.AddWithValue("@WoId",woId.Value);link.Parameters.AddWithValue("@ItemId",itemId);link.Parameters.AddWithValue("@PlanId",planId);
            await link.ExecuteNonQueryAsync();
        }
    }
    await tx.CommitAsync();
    return created;
}

// Kontrol listesi servis formundaki genel alanlari cihaz turune gore tekniklestirir.
static List<(string Code,string Label)> MaintenanceCheckTemplate(string type)
{
    if(type=="X-Ray") return
    [
        ("XR_EXT","Gövde, kapaklar, koruyucu muhafazalar ve mekanik sabitlemeler kontrol edildi"),
        ("XR_CURTAIN","Giriş/çıkış kurşun perdeleri ve fiziksel bütünlük kontrol edildi"),
        ("XR_ESTOP","Acil durdurma sistemi ve güvenli duruş işlevi kontrol edildi"),
        ("XR_INTERLOCK","Kapak emniyet kilitleri ve interlock uyarıları kontrol edildi"),
        ("XR_BELT","Konveyör bandı, tahrik ve yön kontrolü yapıldı"),
        ("XR_IMG","Ekran görüntüsü, görüntü kalitesi ve operatör fonksiyonları kontrol edildi"),
        ("XR_TEST","Uygun test parçasıyla algılama/performans kontrolü yapıldı"),
        ("XR_LIGHT","İkaz lambaları, sesli uyarılar ve durum göstergeleri kontrol edildi"),
        ("XR_CLEAN","Cihaz dış yüzeyi ve erişilebilir alan temizliği tamamlandı"),
        ("XR_FAULT","Hata kayıtları, kablo/konnektör görünür durumları kontrol edildi"),
        ("XR_SAFETY","Yetkili prosedüre göre radyasyon güvenliği/kaçak kontrol kayıtları değerlendirildi")
    ];
    return
    [
        ("MD_EXT","Panel, gövde, üst bağlantı ve sabitlemeler kontrol edildi"),
        ("MD_POWER","Enerji beslemesi, kablo ve konnektörlerin görünür durumu kontrol edildi"),
        ("MD_BOOT","Cihaz açılışı ve kendi kendini test sonuçları kontrol edildi"),
        ("MD_ALARM","Sesli alarm, ışıklı uyarı ve alarm göstergeleri kontrol edildi"),
        ("MD_ZONES","Algılama bölgeleri ve bölgesel alarm göstergeleri kontrol edildi"),
        ("MD_TEST","Standart test nesnesiyle geçiş ve algılama testi yapıldı"),
        ("MD_SENS","Hassasiyet/ayarların yetkili konfigürasyona uygunluğu kontrol edildi"),
        ("MD_COUNTER","Varsa geçiş/sayaç ve günlük işlevleri kontrol edildi"),
        ("MD_FALSE","Çevresel etkileşim ve yanlış alarm davranışı gözlendi"),
        ("MD_CLEAN","Panel yüzey temizliği ve fiziksel durum kontrolü tamamlandı")
    ];
}

static async Task CompleteMaintenanceFromWorkOrderAsync(string connectionString, long workOrderId)
{
    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    await using var transaction = (SqlTransaction)await connection.BeginTransactionAsync();

    var find = new SqlCommand(@"
SELECT TOP 1 mp.MaintenancePlanId,mp.MaintenanceContractId
FROM dbo.MaintenancePlans mp
WHERE mp.GeneratedWorkOrderId=@WorkOrderId AND mp.IsCompleted=0", connection, transaction);
    find.Parameters.AddWithValue("@WorkOrderId", workOrderId);

    long? planId = null;
    long? contractId = null;
    await using (var reader = await find.ExecuteReaderAsync())
    {
        if (await reader.ReadAsync())
        {
            planId = reader.GetInt64(0);
            contractId = reader.GetInt64(1);
        }
    }

    if (!planId.HasValue || !contractId.HasValue)
    {
        await transaction.RollbackAsync();
        return;
    }

    var complete = new SqlCommand(@"
UPDATE dbo.MaintenancePlans SET IsCompleted=1,CompletedAt=SYSDATETIME() WHERE MaintenancePlanId=@PlanId;
UPDATE dbo.MaintenanceContracts
SET CompletedCount=CASE WHEN CompletedCount<AnnualFrequency THEN CompletedCount+1 ELSE CompletedCount END,
    UpdatedAt=SYSDATETIME()
WHERE MaintenanceContractId=@ContractId;", connection, transaction);
    complete.Parameters.AddWithValue("@PlanId", planId.Value);
    complete.Parameters.AddWithValue("@ContractId", contractId.Value);
    await complete.ExecuteNonQueryAsync();
    await transaction.CommitAsync();
}

static string? JoinRentalSerials(List<string>? serials)
{
    var clean = (serials ?? new()).Select(x=>x?.Trim()??"").Where(x=>x.Length>0).Distinct(StringComparer.OrdinalIgnoreCase).ToList();
    return clean.Count==0 ? null : string.Join(", ",clean);
}

static string? ValidateRentalComposition(List<RentalLineRequest> items,List<RentalContactRequest> contacts)
{
    if (items.Count==0 || items.Count>100) return "En az bir, en fazla 100 ürün kalemi girilebilir.";
    if (contacts.Count>50) return "En fazla 50 irtibat kişisi eklenebilir.";
    foreach(var item in items)
    {
        if (item.RentalProductId<=0 || item.Quantity<=0 || item.Quantity>10000) return "Ürün veya adet geçersiz.";
        if ((item.Notes?.Length??0)>1000) return "Ürün notu en fazla 1000 karakter olabilir.";
        if (item.SerialNumbers is { Count: > 10000 }) return "Seri numarası sayısı geçersiz.";
        if (item.SerialNumbers?.Any(x=>x.Length>200)==true) return "Seri numarası en fazla 200 karakter olabilir.";
    }
    foreach(var c in contacts)
    {
        if (string.IsNullOrWhiteSpace(c.FullName)||c.FullName.Length>180) return "İrtibat kişisinin adı zorunludur (en çok 180 karakter).";
        if ((c.JobTitle?.Length??0)>180 || (c.Phone?.Length??0)>80 || (c.Email?.Length??0)>250 || (c.Notes?.Length??0)>500)
            return "İrtibat bilgileri izin verilen uzunluğu aşıyor.";
    }
    return null;
}

static async Task SaveRentalCompositionAsync(SqlConnection connection,SqlTransaction transaction,long rentalOrderId,List<RentalLineRequest> items,List<RentalContactRequest> contacts)
{
    // Existing item IDs are kept; links to inventory are never silently lost.
    var lookup = new SqlCommand("SELECT RentalOrderItemId FROM dbo.RentalOrderItems WHERE RentalOrderId=@OrderId",connection,transaction);
    lookup.Parameters.AddWithValue("@OrderId",rentalOrderId);
    var existing=new HashSet<long>();
    await using(var rd=await lookup.ExecuteReaderAsync()) while(await rd.ReadAsync()) existing.Add(rd.GetInt64(0));
    var requestedIds=items.Where(x=>x.RentalOrderItemId.HasValue).Select(x=>x.RentalOrderItemId!.Value).ToList();
    if(requestedIds.Distinct().Count()!=requestedIds.Count || requestedIds.Any(x=>!existing.Contains(x)))
        throw new InvalidOperationException("Kiralama ürün kalemi kimliği geçersiz.");
    foreach(var oldId in existing.Where(id=>!requestedIds.Contains(id)))
    {
        var assigned=new SqlCommand("SELECT COUNT(*) FROM dbo.RentalInventory WHERE RentalOrderItemId=@Id",connection,transaction);
        assigned.Parameters.AddWithValue("@Id",oldId);
        if(Convert.ToInt32(await assigned.ExecuteScalarAsync())>0)
            throw new InvalidOperationException("Üzerinde envanter ataması olan ürün kalemi silinemez. Önce cihazları serbest bırakın.");
        var del=new SqlCommand("DELETE FROM dbo.RentalOrderItems WHERE RentalOrderItemId=@Id",connection,transaction);
        del.Parameters.AddWithValue("@Id",oldId);
        await del.ExecuteNonQueryAsync();
    }
    foreach(var item in items)
    {
        var sql=item.RentalOrderItemId.HasValue
            ? "UPDATE dbo.RentalOrderItems SET RentalProductId=@ProductId,Quantity=@Qty,SerialNumbers=@Serial,Notes=@Notes WHERE RentalOrderItemId=@ItemId AND RentalOrderId=@OrderId"
            : "INSERT INTO dbo.RentalOrderItems(RentalOrderId,RentalProductId,Quantity,SerialNumbers,Notes) VALUES(@OrderId,@ProductId,@Qty,@Serial,@Notes)";
        var cmd=new SqlCommand(sql,connection,transaction);
        cmd.Parameters.AddWithValue("@OrderId",rentalOrderId);
        if(item.RentalOrderItemId.HasValue) cmd.Parameters.AddWithValue("@ItemId",item.RentalOrderItemId.Value);
        cmd.Parameters.AddWithValue("@ProductId",item.RentalProductId);
        cmd.Parameters.AddWithValue("@Qty",item.Quantity);
        cmd.Parameters.AddWithValue("@Serial",Db(JoinRentalSerials(item.SerialNumbers)));
        cmd.Parameters.AddWithValue("@Notes",Db(item.Notes));
        await cmd.ExecuteNonQueryAsync();
    }
    // Contact rows are replaced as an atomic set; rental history remains intact.
    var delContacts=new SqlCommand("DELETE FROM dbo.RentalOrderContacts WHERE RentalOrderId=@Id",connection,transaction);
    delContacts.Parameters.AddWithValue("@Id",rentalOrderId);
    await delContacts.ExecuteNonQueryAsync();
    foreach(var c in contacts)
    {
        var cmd=new SqlCommand(@"INSERT INTO dbo.RentalOrderContacts
(RentalOrderId,ContactType,FullName,JobTitle,Phone,Email,Notes)
VALUES(@OrderId,@Type,@Name,@Title,@Phone,@Email,@Notes)",connection,transaction);
        cmd.Parameters.AddWithValue("@OrderId",rentalOrderId);
        cmd.Parameters.AddWithValue("@Type",string.IsNullOrWhiteSpace(c.ContactType)?"Diğer":c.ContactType.Trim());
        cmd.Parameters.AddWithValue("@Name",c.FullName.Trim());
        cmd.Parameters.AddWithValue("@Title",Db(c.JobTitle));
        cmd.Parameters.AddWithValue("@Phone",Db(c.Phone));
        cmd.Parameters.AddWithValue("@Email",Db(c.Email));
        cmd.Parameters.AddWithValue("@Notes",Db(c.Notes));
        await cmd.ExecuteNonQueryAsync();
    }
}

static async Task ApplySchemaAsync(string connectionString, string schemaPath)
{
    if (!File.Exists(schemaPath)) throw new FileNotFoundException("Veritabanı güncelleme dosyası bulunamadı.", schemaPath);
    var sql = await File.ReadAllTextAsync(schemaPath, Encoding.UTF8);
    var batches = Regex.Split(sql, @"^\s*GO\s*;?\s*$", RegexOptions.Multiline | RegexOptions.IgnoreCase);
    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    foreach (var batch in batches.Where(x => !string.IsNullOrWhiteSpace(x)))
    {
        var command = new SqlCommand(batch, connection) { CommandTimeout = 120 };
        await command.ExecuteNonQueryAsync();
    }
}

static async Task SeedUsersAsync(string connectionString, string? initialAdminPassword)
{
    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    var countCommand = new SqlCommand("SELECT COUNT(*) FROM dbo.ErpUsers", connection);
    var count = Convert.ToInt32(await countCommand.ExecuteScalarAsync());
    if (count > 0) return;

    // Yeni ve bos bir test DB'de demo hesaplar olusturulmaz. Admin parolasi IT tarafindan verilir.
    if (string.IsNullOrWhiteSpace(initialAdminPassword) || initialAdminPassword.Length < 14)
        throw new InvalidOperationException("Bos DB icin DengeERP__InitialAdminPassword en az 14 karakter olmalidir.");

    var (salt, hash) = HashPassword(initialAdminPassword);
    var command = new SqlCommand(@"
INSERT INTO dbo.ErpUsers(Username,PasswordHash,PasswordSalt,FullName,RoleName,AllowedUnits,Permissions,IsActive,MustChangePassword)
VALUES(@Username,@Hash,@Salt,@FullName,@Role,@Units,@Permissions,1,1)", connection);
    command.Parameters.AddWithValue("@Username", "admin");
    command.Parameters.AddWithValue("@Hash", hash);
    command.Parameters.AddWithValue("@Salt", salt);
    command.Parameters.AddWithValue("@FullName", "Sistem Yoneticisi");
    command.Parameters.AddWithValue("@Role", "Admin");
    command.Parameters.AddWithValue("@Units", JoinPipe(Catalog.AllUnits));
    command.Parameters.AddWithValue("@Permissions", "*");
    await command.ExecuteNonQueryAsync();
}

// V1.11: Plan sahasi formunda kaydedilen metinler; kütük önerileri kullanıcı tarafından düzenlenebilir.
static bool ValidPlanSite(PlanSiteFields f) =>
    (f.SiteName?.Length ?? 0) <= 250 && (f.SiteCity?.Length ?? 0) <= 100 &&
    (f.SiteDistrict?.Length ?? 0) <= 120 && (f.SiteAddress?.Length ?? 0) <= 600 &&
    (f.SiteArea?.Length ?? 0) <= 250 && (f.SiteContact?.Length ?? 0) <= 180 &&
    (f.SitePhone?.Length ?? 0) <= 80 && (f.SiteDirections?.Length ?? 0) <= 1000;

static void AddSiteParameters(SqlCommand cmd, PlanSiteFields f)
{
    cmd.Parameters.AddWithValue("@SiteName",Db(f.SiteName?.Trim()));
    cmd.Parameters.AddWithValue("@SiteCity",Db(f.SiteCity?.Trim()));
    cmd.Parameters.AddWithValue("@SiteDistrict",Db(f.SiteDistrict?.Trim()));
    cmd.Parameters.AddWithValue("@SiteAddress",Db(f.SiteAddress?.Trim()));
    cmd.Parameters.AddWithValue("@SiteArea",Db(f.SiteArea?.Trim()));
    cmd.Parameters.AddWithValue("@SiteContact",Db(f.SiteContact?.Trim()));
    cmd.Parameters.AddWithValue("@SitePhone",Db(f.SitePhone?.Trim()));
    cmd.Parameters.AddWithValue("@SiteDirections",Db(f.SiteDirections?.Trim()));
}

static bool IsBulkClosedStatus(string status) =>
    status is "Tamamlandı" or "Kapatıldı" or "İptal";

static async Task<List<BulkWorkTarget>> ReadBulkTargetsAsync(SqlConnection connection, SqlTransaction transaction, long[] ids)
{
    var parameters = string.Join(",", ids.Select((_, i) => "@Id" + i));
    var sql = $@"
SELECT w.WorkOrderId,w.UnitCode,w.CustomerName,ISNULL(w.Location,N''),w.Status,
 CASE WHEN EXISTS(SELECT 1 FROM dbo.WorkOrderPlans p WHERE p.WorkOrderId=w.WorkOrderId AND p.IsActive=1)
 THEN CAST(1 AS bit) ELSE CAST(0 AS bit) END
FROM dbo.WorkOrders w WITH (UPDLOCK, HOLDLOCK)
WHERE w.WorkOrderId IN ({parameters}) ORDER BY w.WorkOrderId";
    var command = new SqlCommand(sql, connection, transaction);
    for (var i = 0; i < ids.Length; i++) command.Parameters.AddWithValue("@Id" + i, ids[i]);
    var result = new List<BulkWorkTarget>();
    await using var reader = await command.ExecuteReaderAsync();
    while (await reader.ReadAsync())
        result.Add(new BulkWorkTarget(reader.GetInt64(0), reader.GetString(1), reader.GetString(2),
            reader.GetString(3), reader.GetString(4), reader.GetBoolean(5)));
    return result;
}

static async Task InsertAssignmentAsync(SqlConnection connection, SqlTransaction transaction, long workOrderId, string name, string role)
{
    var command = new SqlCommand(@"
INSERT INTO dbo.WorkOrderAssignments(WorkOrderId,AssignedName,AssignmentRole,IsActive)
VALUES(@WorkOrderId,@AssignedName,@Role,1)", connection, transaction);
    command.Parameters.AddWithValue("@WorkOrderId", workOrderId);
    command.Parameters.AddWithValue("@AssignedName", name);
    command.Parameters.AddWithValue("@Role", role);
    await command.ExecuteNonQueryAsync();
}

static async Task InsertStatusLogAsync(SqlConnection connection, SqlTransaction transaction, long workOrderId, string? oldStatus, string newStatus, string? note, SessionUser user)
{
    var command = new SqlCommand(@"
INSERT INTO dbo.WorkOrderStatusLogs(WorkOrderId,OldStatus,NewStatus,Note,ChangedByUserId,ChangedByName)
VALUES(@WorkOrderId,@OldStatus,@NewStatus,@Note,@UserId,@UserName)", connection, transaction);
    command.Parameters.AddWithValue("@WorkOrderId", workOrderId);
    command.Parameters.AddWithValue("@OldStatus", Db(oldStatus));
    command.Parameters.AddWithValue("@NewStatus", newStatus);
    command.Parameters.AddWithValue("@Note", Db(note));
    command.Parameters.AddWithValue("@UserId", user.UserId);
    command.Parameters.AddWithValue("@UserName", user.FullName);
    await command.ExecuteNonQueryAsync();
}

static async Task<WorkTypeRule> GetWorkTypeRuleAsync(string connectionString, string unit, string workType)
{
    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    return await GetWorkTypeRuleWithConnectionAsync(connection, null, unit, workType);
}

static async Task<WorkTypeRule> GetWorkTypeRuleWithConnectionAsync(SqlConnection connection, SqlTransaction? transaction, string unit, string workType)
{
    var command = new SqlCommand(@"
SELECT TOP 1 SerialRequiredOnCreate,SerialRequiredOnClose
FROM dbo.WorkTypeRules WHERE UnitCode=@Unit AND WorkType=@WorkType AND IsActive=1", connection, transaction);
    command.Parameters.AddWithValue("@Unit", unit);
    command.Parameters.AddWithValue("@WorkType", workType);
    await using var reader = await command.ExecuteReaderAsync();
    if (await reader.ReadAsync()) return new WorkTypeRule(reader.GetBoolean(0), reader.GetBoolean(1));

    var workshop = workType.Contains("Atölye", StringComparison.OrdinalIgnoreCase);
    var field = workType.Contains("Saha", StringComparison.OrdinalIgnoreCase) || workType.Contains("Kurulum", StringComparison.OrdinalIgnoreCase) || workType.Contains("Arıza", StringComparison.OrdinalIgnoreCase);
    return new WorkTypeRule(workshop, workshop || field);
}

static async Task<bool> CanAccessWorkOrderAsync(string connectionString, long id, SessionUser user)
{
    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    var command = new SqlCommand(@"
SELECT w.UnitCode,
       (SELECT STRING_AGG(a.AssignedName,', ') FROM dbo.WorkOrderAssignments a WHERE a.WorkOrderId=w.WorkOrderId AND a.IsActive=1 AND a.AssignmentRole=N'Teknisyen')
FROM dbo.WorkOrders w WHERE w.WorkOrderId=@Id", connection);
    command.Parameters.AddWithValue("@Id", id);
    await using var reader = await command.ExecuteReaderAsync();
    if (!await reader.ReadAsync()) return false;
    var unit = reader.GetString(0);
    if (!UnitAllowed(user, unit)) return false;
    if (user.RoleName != "Teknisyen") return true;
    var staff = reader.IsDBNull(1) ? "" : reader.GetString(1);
    return staff.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).Contains(user.FullName, StringComparer.OrdinalIgnoreCase);
}

static async Task<List<LiveTimerRow>> LoadLiveTimersAsync(string connectionString, bool completedBreaks = false)
{
    var rows = new List<LiveTimerRow>();
    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    var command = new SqlCommand(@"
SELECT SessionId,WorkOrderId,TechnicianUserId,TechnicianName,ActivityType,StartedAt,
       EndedAt,StopReason,LocationNote,WorkNote,ResultTimeLogId
FROM dbo.WorkOrderLiveSessions WHERE " +
        (completedBreaks ? "ActivityType=N'Mola / Ara' AND EndedAt IS NOT NULL AND StopReason<>N'İptal'" : "EndedAt IS NULL") +
        " ORDER BY StartedAt DESC", connection);
    await using var reader = await command.ExecuteReaderAsync();
    while (await reader.ReadAsync())
        rows.Add(new LiveTimerRow(
            reader.GetInt64(0), reader.GetInt64(1), reader.GetInt32(2), reader.GetString(3),
            reader.GetString(4), reader.GetDateTime(5), reader.IsDBNull(6) ? null : reader.GetDateTime(6),
            reader.IsDBNull(7) ? null : reader.GetString(7), reader.IsDBNull(8) ? null : reader.GetString(8),
            reader.IsDBNull(9) ? null : reader.GetString(9), reader.IsDBNull(10) ? null : reader.GetInt64(10)));
    return rows;
}

static async Task<List<TimeLogRow>> LoadTimeLogsAsync(string connectionString)
{
    var rows=new List<TimeLogRow>();
    await using var connection=new SqlConnection(connectionString);
    await connection.OpenAsync();
    var command=new SqlCommand(@"
SELECT TimeLogId,WorkOrderId,TechnicianName,ActivityType,StartedAt,EndedAt,
       DATEDIFF(SECOND,StartedAt,EndedAt)/60 AS Minutes,LocationNote,WorkNote,CreatedByName,CreatedAt
FROM dbo.WorkOrderTimeLogs WHERE IsVoided=0 ORDER BY StartedAt DESC",connection);
    await using var reader=await command.ExecuteReaderAsync();
    while(await reader.ReadAsync()) rows.Add(new TimeLogRow(
        reader.GetInt64(0),reader.GetInt64(1),reader.GetString(2),reader.GetString(3),reader.GetDateTime(4),
        reader.GetDateTime(5),reader.GetInt32(6),reader.IsDBNull(7)?null:reader.GetString(7),
        reader.IsDBNull(8)?null:reader.GetString(8),reader.GetString(9),reader.GetDateTime(10)));
    return rows;
}

static async Task<List<WorkOrderRow>> LoadWorkOrdersAsync(string connectionString)
{
    var records = new List<WorkOrderRow>();
    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    var command = new SqlCommand(@"
SELECT
    w.WorkOrderId,w.WorkOrderNo,w.UnitCode,w.WorkType,w.CustomerName,w.ProjectName,w.Location,w.Subject,w.Description,w.Priority,w.Status,COALESCE(w.CreatedByErpUserId,w.CreatedByUserId) AS CreatedByUserId,w.CreatedAt,
    w.SystemName,w.CustomerEmail,
    (SELECT TOP 1 a.AssignedName FROM dbo.WorkOrderAssignments a WHERE a.WorkOrderId=w.WorkOrderId AND a.IsActive=1 AND a.AssignmentRole=N'Şef' ORDER BY a.AssignmentId DESC) AS ChiefName,
    (SELECT STRING_AGG(a.AssignedName,', ') FROM dbo.WorkOrderAssignments a WHERE a.WorkOrderId=w.WorkOrderId AND a.IsActive=1 AND a.AssignmentRole=N'Teknisyen') AS AssignedStaff,
    COALESCE((SELECT STRING_AGG(d.SerialNo,', ') FROM dbo.WorkOrderDevices d WHERE d.WorkOrderId=w.WorkOrderId AND d.IsActive=1),w.SerialNo) AS SerialNumbers,
    p.PlanDate,p.StartTime,p.EstimatedMinutes,p.VehiclePlate,p.RouteGroupNo,p.PlanNote,w.ClosedAt,
    p.SiteName,p.SiteCity,p.SiteDistrict,p.SiteAddress,p.SiteArea,p.SiteContact,p.SitePhone,p.SiteDirections
FROM dbo.WorkOrders w
OUTER APPLY
(
    SELECT TOP 1 wp.PlanDate,wp.StartTime,wp.EstimatedMinutes,wp.VehiclePlate,wp.RouteGroupNo,wp.PlanNote,
      wp.SiteName,wp.SiteCity,wp.SiteDistrict,wp.SiteAddress,wp.SiteArea,wp.SiteContact,wp.SitePhone,wp.SiteDirections
    FROM dbo.WorkOrderPlans wp WHERE wp.WorkOrderId=w.WorkOrderId AND wp.IsActive=1 ORDER BY wp.WorkOrderPlanId DESC
) p
ORDER BY w.WorkOrderId DESC", connection);

    await using var reader = await command.ExecuteReaderAsync();
    while (await reader.ReadAsync())
    {
        records.Add(new WorkOrderRow(
            reader.GetInt64(0), reader.GetString(1), reader.GetString(2), reader.GetString(3), reader.GetString(4),
            reader.IsDBNull(5) ? null : reader.GetString(5), reader.IsDBNull(6) ? null : reader.GetString(6),
            reader.GetString(7), reader.IsDBNull(8) ? null : reader.GetString(8), reader.GetString(9), reader.GetString(10),
            reader.IsDBNull(11) ? null : reader.GetInt32(11), reader.GetDateTime(12),
            reader.IsDBNull(13) ? null : reader.GetString(13), reader.IsDBNull(14) ? null : reader.GetString(14),
            reader.IsDBNull(15) ? null : reader.GetString(15), reader.IsDBNull(16) ? null : reader.GetString(16),
            reader.IsDBNull(17) ? null : reader.GetString(17),
            reader.IsDBNull(18) ? null : DateOnly.FromDateTime(reader.GetDateTime(18)),
            reader.IsDBNull(19) ? null : reader.GetTimeSpan(19),
            reader.IsDBNull(20) ? null : reader.GetInt32(20),
            reader.IsDBNull(21) ? null : reader.GetString(21),
            reader.IsDBNull(22) ? null : reader.GetString(22),
            reader.IsDBNull(23) ? null : reader.GetString(23),
            reader.IsDBNull(24) ? null : reader.GetDateTime(24),
            reader.IsDBNull(25) ? null : reader.GetString(25),
            reader.IsDBNull(26) ? null : reader.GetString(26),
            reader.IsDBNull(27) ? null : reader.GetString(27),
            reader.IsDBNull(28) ? null : reader.GetString(28),
            reader.IsDBNull(29) ? null : reader.GetString(29),
            reader.IsDBNull(30) ? null : reader.GetString(30),
            reader.IsDBNull(31) ? null : reader.GetString(31),
            reader.IsDBNull(32) ? null : reader.GetString(32)
        ));
    }
    return records;
}

static List<WorkOrderRow> FilterWorkOrdersForUser(List<WorkOrderRow> rows, SessionUser user)
{
    if (!IsAdmin(user) && user.AllowedUnits.Count > 0)
        rows = rows.Where(x => user.AllowedUnits.Contains(x.UnitCode, StringComparer.OrdinalIgnoreCase)).ToList();
    if (user.RoleName == "Teknisyen")
        rows = rows.Where(x => (x.AssignedStaff ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).Contains(user.FullName, StringComparer.OrdinalIgnoreCase)).ToList();
    return rows;
}

static OfferTotals CalculateOffer(List<OfferItemRequest> items)
{
    decimal sub = 0, discount = 0, vat = 0;
    foreach (var i in items)
    {
        var line = i.Quantity * i.UnitPrice;
        var disc = line * i.DiscountPercent / 100m;
        var taxable = line - disc;
        var lineVat = taxable * i.VatPercent / 100m;
        sub += line;
        discount += disc;
        vat += lineVat;
    }
    return new OfferTotals(decimal.Round(sub, 2), decimal.Round(discount, 2), decimal.Round(vat, 2), decimal.Round(sub - discount + vat, 2));
}

static async Task<List<OfferRow>> LoadOffersAsync(string connectionString)
{
    var rows = new List<OfferRow>();
    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    var command = new SqlCommand(@"
SELECT o.OfferId,o.OfferNo,o.WorkOrderId,o.UnitCode,o.CustomerName,o.CustomerEmail,o.Status,o.ValidUntil,o.Notes,o.SubTotal,o.DiscountTotal,o.VatTotal,o.GrandTotal,o.CreatedAt,
       w.WorkOrderNo
FROM dbo.Offers o LEFT JOIN dbo.WorkOrders w ON w.WorkOrderId=o.WorkOrderId
ORDER BY o.OfferId DESC", connection);
    await using var reader = await command.ExecuteReaderAsync();
    while (await reader.ReadAsync())
        rows.Add(new OfferRow(
            reader.GetInt64(0), reader.GetString(1), reader.IsDBNull(2) ? null : reader.GetInt64(2), reader.GetString(3), reader.GetString(4),
            reader.IsDBNull(5) ? null : reader.GetString(5), reader.GetString(6), reader.IsDBNull(7) ? null : DateOnly.FromDateTime(reader.GetDateTime(7)),
            reader.IsDBNull(8) ? null : reader.GetString(8), reader.GetDecimal(9), reader.GetDecimal(10), reader.GetDecimal(11), reader.GetDecimal(12), reader.GetDateTime(13),
            reader.IsDBNull(14) ? null : reader.GetString(14)
        ));
    return rows;
}

static async Task<OfferDetail?> LoadOfferAsync(string connectionString, long id)
{
    await using var connection = new SqlConnection(connectionString);
    await connection.OpenAsync();
    var command = new SqlCommand(@"
SELECT o.OfferId,o.OfferNo,o.WorkOrderId,o.UnitCode,o.CustomerName,o.CustomerEmail,o.Status,o.ValidUntil,o.Notes,o.SubTotal,o.DiscountTotal,o.VatTotal,o.GrandTotal,o.CreatedAt,w.WorkOrderNo
FROM dbo.Offers o LEFT JOIN dbo.WorkOrders w ON w.WorkOrderId=o.WorkOrderId WHERE o.OfferId=@Id", connection);
    command.Parameters.AddWithValue("@Id", id);
    OfferDetail? offer = null;
    await using (var reader = await command.ExecuteReaderAsync())
    {
        if (!await reader.ReadAsync()) return null;
        offer = new OfferDetail(
            reader.GetInt64(0), reader.GetString(1), reader.IsDBNull(2) ? null : reader.GetInt64(2), reader.GetString(3), reader.GetString(4),
            reader.IsDBNull(5) ? null : reader.GetString(5), reader.GetString(6), reader.IsDBNull(7) ? null : DateOnly.FromDateTime(reader.GetDateTime(7)),
            reader.IsDBNull(8) ? null : reader.GetString(8), reader.GetDecimal(9), reader.GetDecimal(10), reader.GetDecimal(11), reader.GetDecimal(12), reader.GetDateTime(13),
            reader.IsDBNull(14) ? null : reader.GetString(14), []
        );
    }

    var itemCommand = new SqlCommand(@"
SELECT ItemCode,Description,Quantity,UnitPrice,DiscountPercent,VatPercent
FROM dbo.OfferItems WHERE OfferId=@Id ORDER BY OfferItemId", connection);
    itemCommand.Parameters.AddWithValue("@Id", id);
    await using var itemReader = await itemCommand.ExecuteReaderAsync();
    while (await itemReader.ReadAsync())
        offer.Items.Add(new OfferItemRow(
            itemReader.IsDBNull(0) ? null : itemReader.GetString(0), itemReader.GetString(1), itemReader.GetDecimal(2), itemReader.GetDecimal(3), itemReader.GetDecimal(4), itemReader.GetDecimal(5)
        ));
    return offer;
}

static byte[] BuildSimpleOfferPdf(OfferDetail offer)
{
    static string PdfText(string s) => ToAscii(s).Replace("\\", "\\\\").Replace("(", "\\(").Replace(")", "\\)");
    var lines = new List<string>
    {
        "DENGE ELEKTRONIK - TEKNIK SERVIS TEKLIFI",
        $"Teklif No: {offer.OfferNo}",
        $"Tarih: {offer.CreatedAt:dd.MM.yyyy}",
        $"Gecerlilik: {(offer.ValidUntil.HasValue ? offer.ValidUntil.Value.ToString("dd.MM.yyyy") : "-")}",
        $"Musteri: {offer.CustomerName}",
        $"Is Emri: {offer.WorkOrderNo ?? "-"}",
        $"Birim: {offer.UnitCode}",
        "",
        "URUN / HIZMET KALEMLERI"
    };
    foreach (var i in offer.Items.Take(15))
        lines.Add($"{i.Description} | {i.Quantity:0.##} x {i.UnitPrice:N2} TL | Isk %{i.DiscountPercent:0.##} | KDV %{i.VatPercent:0.##}");
    lines.Add("");
    lines.Add($"Ara Toplam: {offer.SubTotal:N2} TL");
    lines.Add($"Iskonto: {offer.DiscountTotal:N2} TL");
    lines.Add($"KDV: {offer.VatTotal:N2} TL");
    lines.Add($"GENEL TOPLAM: {offer.GrandTotal:N2} TL");
    if (!string.IsNullOrWhiteSpace(offer.Notes)) lines.Add($"Not: {offer.Notes}");

    var content = new StringBuilder("BT /F1 11 Tf 50 790 Td 14 TL\n");
    foreach (var line in lines)
        content.Append('(').Append(PdfText(line)).Append(") Tj T*\n");
    content.Append("ET");
    var streamBytes = Encoding.ASCII.GetBytes(content.ToString());

    var objects = new List<byte[]>();
    objects.Add(Encoding.ASCII.GetBytes("<< /Type /Catalog /Pages 2 0 R >>"));
    objects.Add(Encoding.ASCII.GetBytes("<< /Type /Pages /Kids [3 0 R] /Count 1 >>"));
    objects.Add(Encoding.ASCII.GetBytes("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"));
    objects.Add(Encoding.ASCII.GetBytes("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"));
    objects.Add(Encoding.ASCII.GetBytes($"<< /Length {streamBytes.Length} >>\nstream\n{content}\nendstream"));

    using var ms = new MemoryStream();
    using var bw = new BinaryWriter(ms, Encoding.ASCII, true);
    bw.Write(Encoding.ASCII.GetBytes("%PDF-1.4\n"));
    var offsets = new List<long> { 0 };
    for (var i = 0; i < objects.Count; i++)
    {
        offsets.Add(ms.Position);
        bw.Write(Encoding.ASCII.GetBytes($"{i + 1} 0 obj\n"));
        bw.Write(objects[i]);
        bw.Write(Encoding.ASCII.GetBytes("\nendobj\n"));
    }
    var xref = ms.Position;
    bw.Write(Encoding.ASCII.GetBytes($"xref\n0 {objects.Count + 1}\n0000000000 65535 f \n"));
    for (var i = 1; i <= objects.Count; i++) bw.Write(Encoding.ASCII.GetBytes($"{offsets[i]:0000000000} 00000 n \n"));
    bw.Write(Encoding.ASCII.GetBytes($"trailer\n<< /Size {objects.Count + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF"));
    bw.Flush();
    return ms.ToArray();
}

static string ToAscii(string? s)
{
    var text = s ?? "";
    var map = new Dictionary<char, char> { ['Ç']='C',['ç']='c',['Ğ']='G',['ğ']='g',['İ']='I',['ı']='i',['Ö']='O',['ö']='o',['Ş']='S',['ş']='s',['Ü']='U',['ü']='u' };
    var sb = new StringBuilder();
    foreach (var ch in text) sb.Append(map.TryGetValue(ch, out var r) ? r : ch <= 127 ? ch : '?');
    return sb.ToString();
}

static bool IsReportMaintenance(WorkOrderRow row) =>
    row.WorkOrderNo.StartsWith("PB-",StringComparison.OrdinalIgnoreCase) || row.WorkType=="Planlı Bakım";

static byte[] BuildWorkOrderXlsx(List<WorkOrderRow> rows,List<TimeLogRow> logs,Dictionary<long,WorkOrderRow> allowed,DateOnly? start,DateOnly? end,string? dateField)
{
    // 8 okunabilir Excel sayfası; çapraz tablolar dışa aktarım anında canlı kayıtlardan üretilir.
    // Bu sürüm statik çapraz özetler üretir, Excel'in yerleşik PivotTable nesneleri değildir.
    var sheets=new List<(string Name,List<List<string>> Rows)>{};
    static string N(double n)=>n.ToString("0.00",CultureInfo.InvariantCulture);
    static string Hours(IEnumerable<TimeLogRow> logs)=>N(logs.Sum(x=>(double)x.Minutes)/60.0);
    var service=rows.Where(x=>!IsReportMaintenance(x)).ToList();
    var upkeep=rows.Where(IsReportMaintenance).ToList();
    var finished=rows.Count(x=>x.Status is "Tamamlandı" or "Kapatıldı");
    var uniqueWorkLogs=logs.Select(x=>x.WorkOrderId).ToHashSet();
    var summary=new List<List<string>> {
        new(){"DENGE ELEKTRONİK • TEKNİK SERVİS YÖNETİM RAPORU",""},
        new(){"Dönem",$"{start?.ToString("dd.MM.yyyy")??"Tümü"} - {end?.ToString("dd.MM.yyyy")??"Tümü"}"},
        new(){"Toplam İş Emri",rows.Count.ToString(CultureInfo.InvariantCulture)},
        new(){"Günlük Servis İş Emri",service.Count.ToString(CultureInfo.InvariantCulture)},
        new(){"Planlı Bakım İş Emri",upkeep.Count.ToString(CultureInfo.InvariantCulture)},
        new(){"Açık Günlük Servis",service.Count(x=>x.Status is not "Tamamlandı" and not "Kapatıldı" and not "İptal").ToString(CultureInfo.InvariantCulture)},
        new(){"Açık Planlı Bakım",upkeep.Count(x=>x.Status is not "Tamamlandı" and not "Kapatıldı" and not "İptal").ToString(CultureInfo.InvariantCulture)},
        new(){"Tamamlanan/Kapatılan İş",finished.ToString(CultureInfo.InvariantCulture)},
        new(){"Gerçek Kişi-Saat",Hours(logs)},
        new(){"Sahada Çalışma Saati",Hours(logs.Where(x=>x.ActivityType=="Saha Çalışması"))},
        new(){"Yol Saati",Hours(logs.Where(x=>x.ActivityType=="Yol / Ulaşım"))},
        new(){"Bekleme Saati",Hours(logs.Where(x=>x.ActivityType=="Bekleme"))},
        new(){"Süre Girilen Farklı İş",uniqueWorkLogs.Count.ToString(CultureInfo.InvariantCulture)},
        new(){"Bu Seçimde Süre Kaydı Eksik İş",rows.Count(x=>!uniqueWorkLogs.Contains(x.WorkOrderId)).ToString(CultureInfo.InvariantCulture)},
        new(){"Önemli", "Kişi-saat gerçekte girilmiş başlangıç-bitiş aralıklarından hesaplanır. Tahmini süre kullanılmaz."},
        new(){"Tarih Esası", "İş emrinde seçilen tarih esası; kişi-saatte faaliyetin başlangıç tarihi geçerlidir."},
        new(){"Kişi-saat açıklaması", "İki teknisyen 2'şer saat çalışırsa 4 kişi-saat sayılır."},
        new(){"Çapraz özet", "Bu sayfalar rapor indirilirken yeniden hesaplanan özet tablolardır; Excel'in yerleşik PivotTable nesnesi değildir."}
    };
    sheets.Add(("Yönetim Özeti",summary));

    List<List<string>> orderDetails(List<WorkOrderRow> records)
    {
        var table=new List<List<string>>{new(){"İş Emri No","Açılış","Birim","İş Türü","Müşteri","Proje","Lokasyon","Şehir","İlçe","Açık Adres","Bina / Bölge","Saha Yetkilisi","Saha Telefonu","Ulaşım Notu","Sistem","Seri No","Konu","Öncelik","Durum","Şef","Teknisyenler","Plan Tarihi","Plan Saati","Tahmini Süre (dk)","Araç","Rota","Plan Notu","Kapanış","Gerçek Kişi-Saat","Süre Kaydı Durumu"}};
        foreach(var r in records){var own=logs.Where(t=>t.WorkOrderId==r.WorkOrderId).ToList();
            table.Add(new(){r.WorkOrderNo,r.CreatedAt.ToString("dd.MM.yyyy HH:mm"),r.UnitCode,r.WorkType,r.CustomerName,r.ProjectName??"",r.SiteName??r.Location??"",r.SiteCity??"",r.SiteDistrict??"",r.SiteAddress??"",r.SiteArea??"",r.SiteContact??"",r.SitePhone??"",r.SiteDirections??"",r.SystemName??"",r.SerialNumbers??"",r.Subject,r.Priority,r.Status,r.ChiefName??"",r.AssignedStaff??"",r.PlanDate?.ToString("dd.MM.yyyy")??"",r.StartTime?.ToString(@"hh\:mm")??"",r.EstimatedMinutes?.ToString()??"",r.VehiclePlate??"",r.RouteGroupNo??"",r.PlanNote??"",r.ClosedAt?.ToString("dd.MM.yyyy HH:mm")??"",Hours(own),own.Count==0?"SÜRE KAYDI YOK":"Kayıtlı"});}
        return table;
    }
    sheets.Add(("Günlük Servis",orderDetails(service)));
    sheets.Add(("Planlı Bakım",orderDetails(upkeep)));
    var categories=new[]{"Günlük Servis","Planlı Bakım"};
    var statuses=new[]{"Müşteri Talebi","Planlamada","Planlandı","Sahada","İşlemde","Atölyede","Beklemede","Tamamlandı","Kapatıldı","İptal"};
    var unitMatrix=new List<List<string>>{new(){"Birim","Kategori","Toplam","Açık","Tamamlanan","Kritik"}};
    foreach(var unit in rows.Select(x=>x.UnitCode).Distinct().OrderBy(x=>x))
      foreach(var category in categories){var a=rows.Where(x=>x.UnitCode==unit&&(IsReportMaintenance(x)?"Planlı Bakım":"Günlük Servis")==category).ToList();
      unitMatrix.Add(new(){unit,category,a.Count.ToString(),a.Count(x=>x.Status is not "Tamamlandı" and not "Kapatıldı" and not "İptal").ToString(),a.Count(x=>x.Status is "Tamamlandı" or "Kapatıldı").ToString(),a.Count(x=>x.Priority=="Kritik").ToString()});}
    sheets.Add(("Birim Durum",unitMatrix));
    var monthly=new List<List<string>>{new(){"Ay","Kategori","Açılan İş","Tamamlanan İş","Kritik İş"}};
    DateOnly? periodDate(WorkOrderRow x)=>dateField switch{"plan"=>x.PlanDate,"closed"=>x.ClosedAt.HasValue?DateOnly.FromDateTime(x.ClosedAt.Value):null,_=>DateOnly.FromDateTime(x.CreatedAt)};
    foreach(var grp in rows.GroupBy(x=>new{Period=periodDate(x)?.ToString("yyyy-MM")??"Tarih yok",Category=IsReportMaintenance(x)?"Planlı Bakım":"Günlük Servis"}).OrderBy(x=>x.Key.Period).ThenBy(x=>x.Key.Category))
       monthly.Add(new(){grp.Key.Period,grp.Key.Category,grp.Count().ToString(),grp.Count(x=>x.Status is "Tamamlandı" or "Kapatıldı").ToString(),grp.Count(x=>x.Priority=="Kritik").ToString()});
    sheets.Add(("Aylık Özet",monthly));
    var activities=new[]{"Saha Çalışması","Yol / Ulaşım","Bekleme","Uzaktan Destek","Atölye","Test / Kontrol","Diğer"};
    var personnel=new List<List<string>>{new(){"Personel","Gerçek Kişi-Saat","Farklı İş","Faaliyet Kaydı","Saha Saati","Yol Saati","Bekleme Saati","Uzaktan Saati","Atölye Saati","Test Saati","Diğer Saat"}};
    foreach(var grp in logs.GroupBy(x=>x.TechnicianName).OrderByDescending(x=>x.Sum(t=>t.Minutes)))
      personnel.Add(new(){grp.Key,Hours(grp),grp.Select(x=>x.WorkOrderId).Distinct().Count().ToString(),grp.Count().ToString(),
          Hours(grp.Where(x=>x.ActivityType==activities[0])),Hours(grp.Where(x=>x.ActivityType==activities[1])),Hours(grp.Where(x=>x.ActivityType==activities[2])),
          Hours(grp.Where(x=>x.ActivityType==activities[3])),Hours(grp.Where(x=>x.ActivityType==activities[4])),Hours(grp.Where(x=>x.ActivityType==activities[5])),Hours(grp.Where(x=>x.ActivityType==activities[6]))});
    sheets.Add(("Personel KPI",personnel));
    var timeDetails=new List<List<string>>{new(){"İş Emri","Kategori","Birim","Teknisyen","Müşteri","Şehir","İlçe","Lokasyon","Açık Adres","Bulunduğu Bölge","Faaliyet","Başlangıç","Bitiş","Süre (dk)","Gerçek Saat","Teknisyen Notu","Kaydeden","Kayıt Tarihi"}};
    foreach(var t in logs.OrderBy(x=>x.StartedAt)){var w=allowed[t.WorkOrderId];timeDetails.Add(new(){w.WorkOrderNo,IsReportMaintenance(w)?"Planlı Bakım":"Günlük Servis",w.UnitCode,t.TechnicianName,w.CustomerName,w.SiteCity??"",w.SiteDistrict??"",w.SiteName??w.Location??"",w.SiteAddress??"",t.LocationNote??"",t.ActivityType,t.StartedAt.ToString("dd.MM.yyyy HH:mm"),t.EndedAt.ToString("dd.MM.yyyy HH:mm"),t.Minutes.ToString(),N((double)t.Minutes/60),t.WorkNote??"",t.CreatedByName,t.CreatedAt.ToString("dd.MM.yyyy HH:mm")});}
    sheets.Add(("Süre Hareketleri",timeDetails));
    var locations=new List<List<string>>{new(){"Müşteri","Şehir","Lokasyon / Bölge","Birim","Farklı İş","Teknisyen","Kayıt Sayısı","Kişi-Saat","Sahada","Yol","Bekleme"}};
    foreach(var grp in logs.GroupBy(t=>new{allowed[t.WorkOrderId].CustomerName,City=allowed[t.WorkOrderId].SiteCity??"-",Location=t.LocationNote??allowed[t.WorkOrderId].SiteName??allowed[t.WorkOrderId].Location??"-",allowed[t.WorkOrderId].UnitCode,t.TechnicianName})
                        .OrderByDescending(g=>g.Sum(t=>t.Minutes)))
      locations.Add(new(){grp.Key.CustomerName,grp.Key.City,grp.Key.Location,grp.Key.UnitCode,grp.Select(t=>t.WorkOrderId).Distinct().Count().ToString(),grp.Key.TechnicianName,grp.Count().ToString(),Hours(grp),Hours(grp.Where(t=>t.ActivityType=="Saha Çalışması")),Hours(grp.Where(t=>t.ActivityType=="Yol / Ulaşım")),Hours(grp.Where(t=>t.ActivityType=="Bekleme"))});
    sheets.Add(("Müşteri Lokasyon",locations));

    using var ms=new MemoryStream();
    using(var zip=new ZipArchive(ms,ZipArchiveMode.Create,true))
    {
        const string mainNs="http://schemas.openxmlformats.org/spreadsheetml/2006/main";
        var types=new StringBuilder("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?><Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"><Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/><Default Extension=\"xml\" ContentType=\"application/xml\"/><Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/><Override PartName=\"/xl/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml\"/>");
        var wb=new StringBuilder($"<?xml version=\"1.0\" encoding=\"UTF-8\"?><workbook xmlns=\"{mainNs}\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\"><sheets>");
        var rels=new StringBuilder("<?xml version=\"1.0\" encoding=\"UTF-8\"?><Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">");
        for(int i=0;i<sheets.Count;i++)
        {
            int n=i+1;
            types.Append($"<Override PartName=\"/xl/worksheets/sheet{n}.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>");
            wb.Append($"<sheet name=\"{Xml(sheets[i].Name)}\" sheetId=\"{n}\" r:id=\"rId{n}\"/>");
            rels.Append($"<Relationship Id=\"rId{n}\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet{n}.xml\"/>");
            // First row heading / normal tables with AutoFilter + frozen headers.
            bool summaryPage=i==0;
            AddZipText(zip,$"xl/worksheets/sheet{n}.xml",MakeSheet(sheets[i].Rows,summaryPage?0:1,!summaryPage));
        }
        types.Append("</Types>");wb.Append("</sheets></workbook>");
        rels.Append($"<Relationship Id=\"rId{(sheets.Count+1)}\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles\" Target=\"styles.xml\"/></Relationships>");
        AddZipText(zip,"[Content_Types].xml",types.ToString());
        AddZipText(zip,"_rels/.rels","<?xml version=\"1.0\" encoding=\"UTF-8\"?><Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"xl/workbook.xml\"/></Relationships>");
        AddZipText(zip,"xl/workbook.xml",wb.ToString());
        AddZipText(zip,"xl/_rels/workbook.xml.rels",rels.ToString());
        AddZipText(zip,"xl/styles.xml","<?xml version=\"1.0\" encoding=\"UTF-8\"?><styleSheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><fonts count=\"2\"><font><sz val=\"11\"/><name val=\"Aptos\"/></font><font><b/><color rgb=\"FFFFFFFF\"/><sz val=\"11\"/><name val=\"Aptos\"/></font></fonts><fills count=\"3\"><fill><patternFill patternType=\"none\"/></fill><fill><patternFill patternType=\"gray125\"/></fill><fill><patternFill patternType=\"solid\"><fgColor rgb=\"FF1E5686\"/><bgColor indexed=\"64\"/></patternFill></fill></fills><borders count=\"1\"><border/></borders><cellStyleXfs count=\"1\"><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\"/></cellStyleXfs><cellXfs count=\"2\"><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\" xfId=\"0\"/><xf numFmtId=\"0\" fontId=\"1\" fillId=\"2\" borderId=\"0\" xfId=\"0\" applyFill=\"1\"/></cellXfs></styleSheet>");
    }
    return ms.ToArray();
}

static string MakeSheet(List<List<string>> rows,int headerRows,bool filter)
{
    var count=Math.Max(1,rows.Count);
    int maxColumns=Math.Max(1,rows.Max(x=>x.Count));
    var sb=new StringBuilder("<?xml version=\"1.0\" encoding=\"UTF-8\"?><worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">");
    if(headerRows>0)sb.Append("<sheetViews><sheetView workbookViewId=\"0\"><pane ySplit=\"1\" topLeftCell=\"A2\" activePane=\"bottomLeft\" state=\"frozen\"/></sheetView></sheetViews>");
    sb.Append("<cols>");
    for(int col=0;col<maxColumns;col++)
    {
        int ideal=rows.Take(Math.Min(rows.Count,60)).Max(row=>col<row.Count?(row[col]?.Length??0):0);
        sb.Append($"<col min=\"{col+1}\" max=\"{col+1}\" width=\"{Math.Clamp(ideal+3,14,48)}\" customWidth=\"1\"/>");
    }
    sb.Append("</cols><sheetData>");
    for(int r=0;r<rows.Count;r++)
    {
        sb.Append($"<row r=\"{r+1}\">");
        for(int c=0;c<rows[r].Count;c++)
        {
            var address=ExcelColumn(c+1)+(r+1);
            var style=r<headerRows?" s=\"1\"":"";
            var value=rows[r][c]??"";
            // All numeric cells are real numeric cells (not text): enables user-side pivot/filters.
            bool numeric=r>=headerRows && (r>0||headerRows>0) && decimal.TryParse(value,NumberStyles.AllowLeadingSign|NumberStyles.AllowDecimalPoint,CultureInfo.InvariantCulture,out _) &&
                (c>0||headerRows>0) && (value=="0" || value.StartsWith("0.",StringComparison.Ordinal) || !value.StartsWith("0",StringComparison.Ordinal)) && value.Length<18;
            if(numeric)
                sb.Append($"<c r=\"{address}\"{style}><v>{Xml(value)}</v></c>");
            else
                sb.Append($"<c r=\"{address}\" t=\"inlineStr\"{style}><is><t>{Xml(value)}</t></is></c>");
        }
        sb.Append("</row>");
    }
    sb.Append("</sheetData>");
    if(filter && rows.Count>1)sb.Append($"<autoFilter ref=\"A1:{ExcelColumn(maxColumns)}{count}\"/>");
    sb.Append("</worksheet>");
    return sb.ToString();
}

static string ExcelColumn(int n)
{
    var s = "";
    while (n > 0) { n--; s = (char)('A' + n % 26) + s; n /= 26; }
    return s;
}

static string Xml(string? s) => System.Security.SecurityElement.Escape(s ?? "") ?? "";
static void AddZipText(ZipArchive zip, string path, string content)
{
    var entry = zip.CreateEntry(path, CompressionLevel.Fastest);
    using var stream = entry.Open();
    using var writer = new StreamWriter(stream, new UTF8Encoding(false));
    writer.Write(content);
}

record LiveTimerStartRequest(string ActivityType, string? LocationNote, string? WorkNote);
record LiveTimerChangeRequest(string? ActivityType, string? LocationNote, string? WorkNote);
record LiveTimerCancelRequest(string Reason);
record LiveTimerRow(long SessionId,long WorkOrderId,int TechnicianUserId,string TechnicianName,string ActivityType,
    DateTime StartedAt,DateTime? EndedAt,string? StopReason,string? LocationNote,string? WorkNote,long? ResultTimeLogId);
record TimeLogCreateRequest(string? TechnicianName,string ActivityType,DateTime StartedAt,DateTime EndedAt,string? LocationNote,string? WorkNote);
record TimeLogRow(long TimeLogId,long WorkOrderId,string TechnicianName,string ActivityType,DateTime StartedAt,DateTime EndedAt,int Minutes,string? LocationNote,string? WorkNote,string CreatedByName,DateTime CreatedAt);
record SessionUser(int UserId, string Username, string FullName, string RoleName, List<string> AllowedUnits, List<string> Permissions, bool MustChangePassword);
record TrainingCourseRequest(string Code,string Title,string? Category,string? UnitCode,string? Reason,string? TargetBehavior,string? SuccessMetric,decimal DurationHours,bool Mandatory,string? Checklist);
record TrainingPlanBulkRequest(List<long> PersonnelIds,int CourseId,int PlanYear,DateOnly DueDate,string? PersonalGoal);
record TrainingSessionRequest(int CourseId,DateOnly SessionDate,string TrainerName,decimal DurationHours,string? Location,string? Notes);
record TrainingAttendanceRequest(long TrainingSessionId,long PersonnelId,bool Attended,int? ScoreBefore,int? ScoreAfter,string? Notes);
record TrainingCompetencyRequest(long PersonnelId,int CompetencyId,int CurrentLevel,int TargetLevel,DateOnly AssessedAt,string? Evidence,DateOnly? NextReviewDate);
record TrainingObservationRatingRequest(int CriterionId,int Rating);
record TrainingObservationRequest(long PersonnelId,int CourseId,long? WorkOrderId,DateOnly ObservedOn,int PhaseDays,List<TrainingObservationRatingRequest> Ratings,string? Notes,string? ActionPlan,DateOnly? NextReviewDate);
record LoginRequest(string Username, string Password);
record ChangePasswordRequest(string NewPassword);
record CreateUserRequest(string Username, string Password, string FullName, string RoleName, List<string>? AllowedUnits, List<string>? Permissions, bool MustChangePassword = true);
record UpdateUserRequest(string Username, string FullName, string RoleName, List<string>? AllowedUnits, List<string>? Permissions, bool MustChangePassword = false);
record UserStatusRequest(bool IsActive);
record ResetPasswordRequest(string TempPassword);
record WorkTypeRule(bool SerialRequiredOnCreate, bool SerialRequiredOnClose);
record CreateWorkOrderRequest(string UnitCode, string WorkType, string CustomerName, string? CustomerEmail, string? ProjectName, string? Location, string? SystemName, List<string>? SerialNumbers, string Subject, string? Description, string Priority);
record UpdateSerialsRequest(List<string>? SerialNumbers);
record UpdateStatusRequest(string Status, string? Note);
record MaintenanceDeviceUpdateRequest(string Status,string? Notes);
record MaintenanceCheckEntry(string Code,string Result);
record MaintenanceFormSaveRequest(string? SerialNo,string? Zone,string? Notes,string? PerformedWork,
    string? SpareParts,string? ServiceResult,bool Complete,List<MaintenanceCheckEntry> Checks);
record AssignmentRequest(string? Chief, List<string>? Technicians);
record BulkAssignmentRequest(List<long>? WorkOrderIds, string? Chief, List<string>? Technicians);
record BulkPlanRequest(List<long>? WorkOrderIds, string? Chief, List<string>? Technicians,
    DateOnly PlanDate, TimeOnly? StartTime, int? EstimatedMinutes, string? VehiclePlate, string? PlanNote,
    string? SiteName, string? SiteCity, string? SiteDistrict, string? SiteAddress,
    string? SiteArea, string? SiteContact, string? SitePhone, string? SiteDirections) :
    PlanSiteFields(SiteName,SiteCity,SiteDistrict,SiteAddress,SiteArea,SiteContact,SitePhone,SiteDirections);
record BulkWorkTarget(long Id, string Unit, string Customer, string Location, string Status, bool IsPlanned);

record PlanSiteFields(string? SiteName,string? SiteCity,string? SiteDistrict,string? SiteAddress,
    string? SiteArea,string? SiteContact,string? SitePhone,string? SiteDirections);
record PlanRequest(DateOnly PlanDate, TimeOnly? StartTime, int? EstimatedMinutes, string? VehiclePlate, string? RouteGroupNo, string? PlanNote,
    string? SiteName,string? SiteCity,string? SiteDistrict,string? SiteAddress,
    string? SiteArea,string? SiteContact,string? SitePhone,string? SiteDirections) :
    PlanSiteFields(SiteName,SiteCity,SiteDistrict,SiteAddress,SiteArea,SiteContact,SitePhone,SiteDirections);
record OfferItemRequest(string? ItemCode, string Description, decimal Quantity, decimal UnitPrice, decimal DiscountPercent, decimal VatPercent);
record CreateOfferRequest(long? WorkOrderId, string UnitCode, string CustomerName, string? CustomerEmail, DateOnly? ValidUntil, string? Notes, List<OfferItemRequest> Items);
record OfferStatusRequest(string Status);
record SendOfferRequest(string? Recipient);
record OfferTotals(decimal SubTotal, decimal DiscountTotal, decimal VatTotal, decimal GrandTotal);

record RentalLineRequest(long? RentalOrderItemId,int RentalProductId,int Quantity,List<string>? SerialNumbers,string? Notes);
record RentalContactRequest(long? RentalOrderContactId,string ContactType,string FullName,string? JobTitle,string? Phone,string? Email,string? Notes);
record RentalCompositionRequest(List<RentalLineRequest> Items,List<RentalContactRequest>? Contacts);
record RentalInventoryRequest(long? RentalInventoryId,int RentalProductId,int RentalWarehouseId,string? SerialNo,int Quantity,string ConditionStatus,string? MissingNotes,string? Notes);
record RentalWarehouseNameRequest(string Name);
record RentalAssetAllocationRequest(long RentalOrderItemId,List<long> RentalInventoryIds);
record RentalStageRequest(string StageName,DateTime EventAt,string? TeamName,int? RentalWarehouseId,string? Notes);
record CreateRentalRequest(int RentalProductId,string UnitCode,string CustomerName,string? CustomerEmail,string? ProjectName,string? Location,string? ContactName,string? ContactPhone,int Quantity,List<string>? SerialNumbers,DateOnly StartDate,DateOnly EndDate,string? ResponsibleName,string? Notes,List<RentalLineRequest>? Items=null,List<RentalContactRequest>? Contacts=null);
record UpdateRentalRequest(string CustomerName,string? CustomerEmail,string? ProjectName,string? Location,string? ContactName,string? ContactPhone,int Quantity,List<string>? SerialNumbers,DateOnly StartDate,DateOnly EndDate,string Status,string? ResponsibleName,string? Notes);
record CreatePersonnelRequest(string FullName,string DepartmentName,List<string>? AdditionalDepartments,string? Title,string? UnitCode,string? ManagerName,DateOnly? StartDate,string? Notes,bool CreateUser=false,string? Username=null,string? Password=null,string? RoleName=null,List<string>? AllowedUnits=null,List<string>? Permissions=null,bool MustChangePassword=true);
record UpdatePersonnelRequest(string FullName,string DepartmentName,List<string>? AdditionalDepartments,string? Title,string? UnitCode,string? ManagerName,DateOnly? StartDate,string? Notes);
record PersonnelStatusRequest(bool IsActive,DateOnly? EndDate);
record WorkshopTicketRequest(
    string CompanyName,string? CompanyAddress,string? ContactName,string? CustomerEmail,string? CustomerPhone,
    DateTime? EntryDate,DateOnly? EstimatedFinishDate,DateTime? CompletionDate,string? LogoFormNo,string? LogoMainServiceNo,
    string? IntegrationCompany,string ServiceType,string? Status,decimal? RepairAmount,string? ReceiveType,string? ReceivedBy,
    string? DeliveredBy,string? DeliveryType,string? CargoTrackingNo,string? AssignedTo,string Brand,string? Model,string SerialNo,
    DateOnly? WarrantyStartDate,DateOnly? WarrantyEndDate,string? WarrantyStatus,string? Accessory1,string? Accessory2,
    string? Accessory3,string? Accessory4,string? Accessory5,string? ProjectName,string? Notes,string? CustomerComplaint,
    string? DeviceCondition,string? RepairInfo
);

record WorkOrderRow(long WorkOrderId,string WorkOrderNo,string UnitCode,string WorkType,string CustomerName,string? ProjectName,string? Location,string Subject,string? Description,string Priority,string Status,int? CreatedByUserId,DateTime CreatedAt,string? SystemName,string? CustomerEmail,string? ChiefName,string? AssignedStaff,string? SerialNumbers,DateOnly? PlanDate,TimeSpan? StartTime,int? EstimatedMinutes,string? VehiclePlate,string? RouteGroupNo,string? PlanNote,DateTime? ClosedAt,
    string? SiteName,string? SiteCity,string? SiteDistrict,string? SiteAddress,
    string? SiteArea,string? SiteContact,string? SitePhone,string? SiteDirections);
record OfferRow(long OfferId,string OfferNo,long? WorkOrderId,string UnitCode,string CustomerName,string? CustomerEmail,string Status,DateOnly? ValidUntil,string? Notes,decimal SubTotal,decimal DiscountTotal,decimal VatTotal,decimal GrandTotal,DateTime CreatedAt,string? WorkOrderNo);
record OfferItemRow(string? ItemCode,string Description,decimal Quantity,decimal UnitPrice,decimal DiscountPercent,decimal VatPercent);
record OfferDetail(long OfferId,string OfferNo,long? WorkOrderId,string UnitCode,string CustomerName,string? CustomerEmail,string Status,DateOnly? ValidUntil,string? Notes,decimal SubTotal,decimal DiscountTotal,decimal VatTotal,decimal GrandTotal,DateTime CreatedAt,string? WorkOrderNo,List<OfferItemRow> Items);

static class Catalog
{
    public static readonly string[] AllUnits = ["Güvenlik Sistemleri", "Haberleşme", "POC", "Mobilite", "Araç Takip"];

    public static readonly Dictionary<string, string> PermissionCatalog = new()
    {
        ["dashboard.view"] = "Ana Paneli Görüntüle",
        ["workorders.view"] = "İş Emirlerini Görüntüle",
        ["workorders.create"] = "İş Kaydı Aç",
        ["workorders.edit"] = "İş Kaydı / Durum Güncelle",
        ["workorders.assign"] = "Şef / Teknisyen Ata",
        ["workorders.plan"] = "Planlama Yap",
        ["workorders.close"] = "İşi Tamamla / Kapat",
        ["offers.view"] = "Teklifleri Görüntüle",
        ["offers.create"] = "Teklif Oluştur",
        ["offers.approve"] = "Teklif Onayla",
        ["offers.send"] = "Teklifi E-posta ile Gönder",
        ["reports.view"] = "Raporları Görüntüle",
        ["reports.export"] = "Excel Dışa Aktar",
        ["training.view"] = "Eğitim / Gelişim Modülünü Gör",
        ["training.manage"] = "Yıllık Eğitim Planı ve Katılım Yönet",
        ["training.observe"] = "Saha Gözlemi / Yetkinlik Değerlendir",
        ["training.export"] = "Eğitim Raporunu Dışa Aktar",
        ["users.manage"] = "Kullanıcı ve Yetki Yönet",
        ["warehouse.view"] = "Depo Modülünü Gör",
        ["warehouse.manage"] = "Yedek Parça Stoklarını Yönet",
        ["operations.manage"] = "SLA / Bekleme Nedenini Yönet",
        ["finance.costs.manage"] = "İş Bazlı Maliyetleri Yönet",
        ["accounting.view"] = "Muhasebe Modülünü Gör",
        ["rentals.view"] = "Kiralama Kayıtlarını Görüntüle",
        ["rentals.create"] = "Kiralama Kaydı Aç",
        ["rentals.edit"] = "Kiralama Kaydı / Durum Güncelle",
        ["personnel.view"] = "Personel / Organizasyonu Görüntüle",
        ["personnel.manage"] = "Personel Ekle / Düzenle / İşten Çıkış",
        ["devices.view"] = "Güvenlik Cihaz Kütüğünü Görüntüle",
        ["finance.prices.view"] = "Ücret / Fiyat Bilgilerini Görüntüle",
        ["maintenance.view"] = "Bakım Planlarını Görüntüle",
        ["maintenance.manage"] = "Bakım Planı / Otomatik İş Emri Yönet",
        ["workshop.view"] = "Haberleşme Atölye Kayıtlarını Görüntüle",
        ["workshop.manage"] = "Haberleşme Atölye Kaydı Aç / Güncelle"
    };

    public static readonly string[] Departments = [
        "Üst Yönetim","Genel Koordinatörlük","Teknik Servis","Güvenlik Sistemleri Teknik Servis",
        "Depo & Lojistik","Müşteri İlişkileri & Kurumsal İletişim","Satış Yönetimi","Güvenlik Satış",
        "Haberleşme Sistemleri Satış","Denge Mobil","Haberleşme Sistemleri Teknik Servis Yönetimi",
        "Haberleşme Sistemleri Teknik Servis","İnsan Kaynakları","Muhasebe & Finans GMY","GMY",
        "İdari İşler","Kiralama & Satış Yönetimi","Kiralama & Operasyon Yönetimi","Muhasebe Yönetimi"
    ];

    public static readonly Dictionary<string, string[]> RoleDefaults = new()
    {
        ["Admin"] = ["*"],
        ["Üst Yönetim"] = ["dashboard.view","workorders.view","workorders.create","workorders.edit","workorders.assign","workorders.plan","workorders.close","offers.view","offers.create","offers.approve","offers.send","reports.view","reports.export","training.view","training.manage","training.observe","training.export","users.manage","warehouse.view","accounting.view","rentals.view","rentals.create","rentals.edit","personnel.view","personnel.manage","devices.view","maintenance.view","maintenance.manage","workshop.view","workshop.manage","finance.prices.view"],
        ["Teknik Servis Müdürü"] = ["dashboard.view","workorders.view","workorders.create","workorders.edit","workorders.assign","workorders.plan","workorders.close","offers.view","offers.create","offers.approve","offers.send","reports.view","reports.export","training.view","training.manage","training.observe","training.export","users.manage","warehouse.view","accounting.view","rentals.view","rentals.create","rentals.edit","personnel.view","personnel.manage","devices.view","maintenance.view","maintenance.manage","workshop.view","workshop.manage","finance.prices.view"],
        ["Teknik Servis Müdür Yardımcısı"] = ["dashboard.view","workorders.view","workorders.create","workorders.edit","workorders.assign","workorders.plan","workorders.close","offers.view","offers.create","offers.approve","offers.send","reports.view","reports.export","training.view","training.manage","training.observe","training.export","users.manage","warehouse.view","accounting.view","rentals.view","rentals.create","rentals.edit","personnel.view","personnel.manage","devices.view","maintenance.view","maintenance.manage","workshop.view","workshop.manage","finance.prices.view"],
        ["Genel Koordinatör"] = ["dashboard.view","workorders.view","offers.view","offers.approve","reports.view","reports.export","training.view","training.export","rentals.view","personnel.view","devices.view","maintenance.view","workshop.view"],
        ["Operasyon Uzmanı"] = ["dashboard.view","workorders.view","workorders.create","offers.view","offers.create","rentals.view","rentals.create","devices.view","maintenance.view","workshop.view"],
        ["Şef"] = ["dashboard.view","workorders.view","workorders.edit","workorders.assign","workorders.plan","workorders.close","offers.view","offers.create","reports.view","training.view","training.observe","rentals.view","rentals.edit","devices.view","maintenance.view","maintenance.manage","workshop.view","workshop.manage"],
        ["Teknisyen"] = ["dashboard.view","workorders.view","workorders.edit","workorders.close","devices.view","workshop.view","workshop.manage"],
        ["Muhasebe"] = ["dashboard.view","workorders.view","offers.view","offers.approve","reports.view","reports.export","accounting.view"],
        ["Depo"] = ["dashboard.view","workorders.view","warehouse.view","rentals.view"],
        ["Kiralama Operasyon"] = ["dashboard.view","workorders.view","rentals.view","rentals.create","rentals.edit","offers.view","offers.create"],
        ["İnsan Kaynakları"] = ["dashboard.view","personnel.view","personnel.manage","training.view","training.manage","training.export","users.manage"]
    };
}
