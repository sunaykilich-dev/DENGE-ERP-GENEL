# Tüm modeller buradan import edilir ki Alembic autogenerate ve Base.metadata
# her tabloyu görsün. Yeni model dosyası ekleyince buraya da ekleyin.
from app.models.account import (
    Account,
    AccountAlias,
    AccountMerge,
    Address,
    Contact,
    InstallationPartner,
)
from app.models.attachment import Attachment
from app.models.audit import AuditLog
from app.models.catalog import Product, ProductBundleItem
from app.models.device import Device, DeviceStatusHistory
from app.models.gorev import (
    Board,
    BoardColumn,
    BoardLabel,
    Card,
    CardComment,
    CardLabel,
    CardMember,
)
from app.models.import_batch import ImportBatch
from app.models.login_attempt import LoginAttempt
from app.models.order import Order, OrderLine, OrderReservation
from app.models.personel import PersonnelNameMap
from app.models.pricing import PriceBatch
from app.models.purchase import (
    GoodsReceipt,
    ImportFile,
    PurchaseOrder,
    PurchaseOrderLine,
)
from app.models.quote import Quote, QuoteLine, QuoteVersion
from app.models.rbac import Permission, Role, RolePermission, UserPermission, UserUnit
from app.models.service import RmaCase
from app.models.servis_bakim import (
    MaintenanceContract,
    MaintenanceContractItem,
    MaintenanceExclusionRequest,
    MaintenanceForm,
    MaintenanceFormCheck,
    MaintenanceGenerationRun,
    MaintenanceNonconformity,
    MaintenancePeriod,
    MaintenanceVisit,
)
from app.models.servis_ekipman import ServiceEquipment
from app.models.servis_planlama import (
    ServicePlan,
    ServicePlanMember,
    ServiceUnavailability,
    ServiceVehicle,
    ServiceVisit,
)
from app.models.setting import Setting
from app.models.settlement import (
    PartnerSettlement,
    PartnerTariff,
    Payment,
    SettlementDispute,
    SettlementLine,
)
from app.models.sim import SimCard, SimDeviceHistory, SimPlanHistory
from app.models.stock import (
    DeviceCustodyHistory,
    StockMovement,
    Transfer,
    TransferItem,
    Warehouse,
)
from app.models.subscription import (
    Subscription,
    SubscriptionEvent,
    SubscriptionPrice,
)
from app.models.teknik_servis import (
    ServiceApproval,
    ServiceFaultReason,
    ServiceHold,
    ServiceHoldReason,
    ServiceOrder,
    ServiceOrderAssignment,
    ServiceOrderEvent,
    ServiceOrderSerial,
    ServiceResult,
    ServiceTimeEntry,
)
from app.models.user import Session, User
from app.models.vehicle import Vehicle
from app.models.workorder import (
    DeviceVehicleAssignment,
    WorkOrder,
    WorkOrderItem,
)

__all__ = [
    "RmaCase",
    "PurchaseOrder",
    "PurchaseOrderLine",
    "ImportFile",
    "GoodsReceipt",
    "ImportBatch",
    "PriceBatch",
    "Subscription",
    "SubscriptionEvent",
    "SubscriptionPrice",
    "Order",
    "OrderLine",
    "OrderReservation",
    "QuoteVersion",
    "QuoteLine",
    "Quote",
    "Warehouse",
    "TransferItem",
    "Transfer",
    "DeviceCustodyHistory",
    "StockMovement",
    "WorkOrderItem",
    "WorkOrder",
    "SettlementLine",
    "SettlementDispute",
    "Payment",
    "PartnerTariff",
    "PartnerSettlement",
    "DeviceVehicleAssignment",
    "Account",
    "Address",
    "Attachment",
    "AuditLog",
    "Contact",
    "Device",
    "DeviceStatusHistory",
    "InstallationPartner",
    "LoginAttempt",
    "Permission",
    "Product",
    "ProductBundleItem",
    "Board",
    "BoardColumn",
    "BoardLabel",
    "Card",
    "CardComment",
    "CardLabel",
    "CardMember",
    "Role",
    "RolePermission",
    "UserPermission",
    "Session",
    "Setting",
    "SimCard",
    "SimDeviceHistory",
    "SimPlanHistory",
    "User",
    "Vehicle",
    # --- Teknik servis (Dalga 0 + 1) ---
    "AccountAlias",
    "AccountMerge",
    "MaintenanceContract",
    "MaintenanceContractItem",
    "MaintenanceExclusionRequest",
    "MaintenanceForm",
    "MaintenanceFormCheck",
    "MaintenanceGenerationRun",
    "MaintenanceNonconformity",
    "MaintenancePeriod",
    "MaintenanceVisit",
    "PersonnelNameMap",
    "ServiceApproval",
    "ServiceEquipment",
    "ServiceFaultReason",
    "ServiceHold",
    "ServiceHoldReason",
    "ServiceOrder",
    "ServiceOrderAssignment",
    "ServiceOrderEvent",
    "ServiceOrderSerial",
    "ServicePlan",
    "ServicePlanMember",
    "ServiceResult",
    "ServiceTimeEntry",
    "ServiceUnavailability",
    "ServiceVehicle",
    "ServiceVisit",
    "UserUnit",
]
