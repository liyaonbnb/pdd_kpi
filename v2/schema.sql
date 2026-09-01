-- PostgreSQL 15+ schema for the V2 inventory/cost foundation.
-- All monetary values are numeric(20,6); display rounding belongs to the API.

create extension if not exists pgcrypto;

create table if not exists warehouses (
    id uuid primary key default gen_random_uuid(),
    code varchar(64) not null unique,
    name varchar(128) not null unique,
    is_active boolean not null default true,
    created_at timestamptz not null default now()
);

insert into warehouses (code, name) values
    ('KUNSHAN', '昆山仓'), ('HUIHUANG', '辉煌仓'), ('WAI_GAO_QIAO', '外高桥仓')
on conflict (code) do nothing;

create table if not exists inventory_settings (
    id smallint primary key default 1 check (id = 1),
    inventory_enabled_from date,
    enabled_at timestamptz,
    enabled_by varchar(128),
    is_locked boolean not null default false,
    updated_at timestamptz not null default now()
);
insert into inventory_settings (id) values (1) on conflict (id) do nothing;

-- V2 authentication and legacy permission compatibility.
create table if not exists v2_users (
    id uuid primary key default gen_random_uuid(),
    username varchar(128) not null unique,
    password_hash varchar(255) not null,
    role varchar(16) not null default 'sub' check (role in ('master','sub','admin','operator','viewer')),
    display_name varchar(255),
    allowed_pages jsonb not null default '[]'::jsonb,
    is_active boolean not null default true,
    legacy_username varchar(128),
    password_changed boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create table if not exists v2_user_store_permissions (
    user_id uuid not null references v2_users(id) on delete cascade,
    platform varchar(32) not null,
    store_name varchar(255) not null,
    primary key (user_id, platform, store_name)
);
create index if not exists idx_v2_user_store_permissions_store on v2_user_store_permissions(platform, store_name);

create table if not exists platform_stores (
    id uuid primary key default gen_random_uuid(),
    platform varchar(32) not null,
    store_name varchar(255) not null,
    display_name varchar(255),
    is_active boolean not null default true,
    legacy_key varchar(255),
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (platform, store_name)
);
create index if not exists idx_platform_stores_active on platform_stores (platform, is_active, store_name);
insert into platform_stores(platform, store_name, display_name, legacy_key)
values ('pdd', '测试店', '测试店', '测试店')
on conflict (platform, store_name) do nothing;

create table if not exists inventory_items (
    id uuid primary key default gen_random_uuid(),
    code varchar(128) not null unique,
    name varchar(255) not null,
    base_unit varchar(32) not null,
    category varchar(128),
    tracks_inventory boolean not null default true,
    safety_stock numeric(20,4) not null default 0,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists bundles (
    id uuid primary key default gen_random_uuid(),
    code varchar(128) not null unique,
    name varchar(255) not null,
    estimated_shipping_fee numeric(20,6) not null default 0,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- BOM versions must exist before order lines reference them.
create table if not exists bundle_versions (
    id uuid primary key default gen_random_uuid(),
    bundle_id uuid not null references bundles(id),
    version_no integer not null,
    effective_from date not null,
    effective_to date,
    status varchar(16) not null default 'active' check (status in ('draft','active','retired')),
    created_at timestamptz not null default now(),
    unique (bundle_id, version_no),
    check (effective_to is null or effective_to >= effective_from)
);

create table if not exists bundle_components (
    bundle_version_id uuid not null references bundle_versions(id) on delete cascade,
    item_id uuid not null references inventory_items(id),
    quantity numeric(20,4) not null check (quantity > 0),
    primary key (bundle_version_id, item_id)
);

create table if not exists data_import_batches (
    id uuid primary key default gen_random_uuid(),
    platform varchar(32) not null,
    store_name varchar(255),
    data_type varchar(32) not null check (data_type in ('orders','promotions','inventory','costs')),
    source_filename varchar(512),
    source_sha256 char(64),
    period_from date,
    period_to date,
    status varchar(16) not null default 'processing' check (status in ('processing','succeeded','partial','failed','rolled_back','cancelled')),
    row_count integer not null default 0,
    error_count integer not null default 0,
    error_message text,
    created_by varchar(128),
    created_at timestamptz not null default now(),
    completed_at timestamptz
);

create index if not exists idx_import_batches_lookup on data_import_batches (platform, store_name, data_type, created_at desc);

-- 推广原始明细先独立留存，后续日报/KPI 从该表聚合；不把推广导入混入库存事务。
create table if not exists promotion_metrics_daily (
    id uuid primary key default gen_random_uuid(),
    import_batch_id uuid not null references data_import_batches(id) on delete cascade,
    platform varchar(32) not null,
    store_name varchar(255) not null,
    metric_date date not null,
    product_id varchar(128),
    style_id varchar(128),
    spend numeric(20,6) not null default 0,
    gmv numeric(20,6) not null default 0,
    orders numeric(20,6) not null default 0,
    exposure numeric(20,6) not null default 0,
    clicks numeric(20,6) not null default 0,
    raw_payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (import_batch_id, product_id, style_id)
);
create index if not exists idx_promotion_metrics_lookup on promotion_metrics_daily(platform, store_name, metric_date desc);

create table if not exists platform_orders (
    id uuid primary key default gen_random_uuid(),
    import_batch_id uuid references data_import_batches(id),
    platform varchar(32) not null,
    store_name varchar(255) not null,
    order_id varchar(128) not null,
    payment_time timestamptz,
    order_status varchar(64),
    is_cancelled boolean not null default false,
    warehouse_id uuid references warehouses(id),
    inventory_status varchar(16) not null default 'pending' check (inventory_status in ('legacy','pending','deducted','exception','reversed','not_applicable')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (platform, store_name, order_id)
);

create index if not exists idx_platform_orders_payment on platform_orders (warehouse_id, payment_time, order_id);

create table if not exists platform_order_lines (
    id uuid primary key default gen_random_uuid(),
    order_id uuid not null references platform_orders(id) on delete cascade,
    product_id varchar(128),
    style_id varchar(128),
    bundle_id uuid references bundles(id),
    bom_version_id uuid references bundle_versions(id),
    quantity numeric(20,4) not null default 0,
    expected_shipping_fee numeric(20,6) not null default 0,
    raw_payload jsonb,
    unique (order_id, product_id, style_id)
);

create index if not exists idx_platform_orders_import_batch on platform_orders (import_batch_id);
create index if not exists idx_platform_order_lines_order on platform_order_lines (order_id);
create index if not exists idx_platform_order_lines_bundle on platform_order_lines (bundle_id);
create index if not exists idx_platform_order_lines_bom_version on platform_order_lines (bom_version_id);

create table if not exists platform_listing_mappings (
    id uuid primary key default gen_random_uuid(),
    platform varchar(32) not null,
    store_name varchar(255) not null,
    product_id varchar(128) not null,
    style_id varchar(128),
    bundle_id uuid not null references bundles(id),
    effective_from date,
    effective_to date,
    unique (platform, store_name, product_id, style_id, effective_from)
);

create index if not exists idx_platform_listing_mappings_bundle on platform_listing_mappings (bundle_id);

create table if not exists store_warehouse_assignments (
    id uuid primary key default gen_random_uuid(),
    platform varchar(32) not null,
    store_name varchar(255) not null,
    warehouse_id uuid not null references warehouses(id),
    effective_from date not null,
    effective_to date,
    created_at timestamptz not null default now(),
    check (effective_to is null or effective_to >= effective_from),
    unique (platform, store_name, effective_from)
);

create index if not exists idx_store_warehouse_assignments_warehouse on store_warehouse_assignments (warehouse_id);

create table if not exists item_cost_versions (
    id uuid primary key default gen_random_uuid(),
    item_id uuid not null references inventory_items(id),
    warehouse_id uuid not null references warehouses(id),
    unit_cost numeric(20,6) not null check (unit_cost >= 0),
    effective_from date not null,
    effective_to date,
    source_type varchar(32) not null,
    source_id varchar(128),
    created_at timestamptz not null default now(),
    check (effective_to is null or effective_to >= effective_from)
);

create index if not exists idx_item_cost_versions_item on item_cost_versions (item_id, effective_from desc);
create index if not exists idx_item_cost_versions_warehouse on item_cost_versions (warehouse_id, effective_from desc);

create table if not exists inventory_batches (
    id uuid primary key default gen_random_uuid(),
    warehouse_id uuid not null references warehouses(id),
    item_id uuid not null references inventory_items(id),
    batch_no varchar(128) not null,
    supplier_batch_no varchar(128),
    received_at timestamptz not null,
    received_qty numeric(20,4) not null check (received_qty > 0),
    remaining_qty numeric(20,4) not null check (remaining_qty >= 0),
    unit_cost numeric(20,6) not null check (unit_cost >= 0),
    stock_status varchar(16) not null default 'sellable' check (stock_status in ('sellable','inspection','defective','scrapped')),
    created_at timestamptz not null default now(),
    unique (warehouse_id, item_id, batch_no)
);

create index if not exists idx_batches_fifo on inventory_batches (warehouse_id, item_id, received_at, id) where stock_status = 'sellable' and remaining_qty > 0;

create table if not exists purchase_receipts (
    id uuid primary key default gen_random_uuid(),
    receipt_no varchar(64) not null unique,
    warehouse_id uuid not null references warehouses(id),
    supplier_name varchar(255),
    status varchar(16) not null default 'draft' check (status in ('draft','pending','approved','rejected','void')),
    purchase_amount numeric(20,6) not null default 0 check (purchase_amount >= 0),
    freight_fee numeric(20,6) not null default 0 check (freight_fee >= 0),
    other_fee numeric(20,6) not null default 0 check (other_fee >= 0),
    received_at timestamptz,
    approved_at timestamptz,
    approved_by varchar(128),
    created_by varchar(128),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists purchase_receipt_lines (
    id uuid primary key default gen_random_uuid(),
    receipt_id uuid not null references purchase_receipts(id) on delete cascade,
    item_id uuid not null references inventory_items(id),
    batch_no varchar(128) not null,
    quantity numeric(20,4) not null check (quantity > 0),
    base_unit_cost numeric(20,6) not null check (base_unit_cost >= 0),
    line_amount numeric(20,6) not null check (line_amount >= 0),
    landed_unit_cost numeric(20,6),
    unique (receipt_id, item_id, batch_no)
);

create index if not exists idx_purchase_receipts_warehouse_status on purchase_receipts (warehouse_id, status, created_at desc);
create index if not exists idx_purchase_receipt_lines_receipt on purchase_receipt_lines (receipt_id);
create index if not exists idx_purchase_receipt_lines_item on purchase_receipt_lines (item_id);

create table if not exists inventory_balances (
    warehouse_id uuid not null references warehouses(id),
    item_id uuid not null references inventory_items(id),
    sellable_qty numeric(20,4) not null default 0 check (sellable_qty >= 0),
    total_average_cost numeric(20,6) not null default 0 check (total_average_cost >= 0),
    average_unit_cost numeric(20,6) generated always as (
        case when sellable_qty = 0 then 0 else total_average_cost / sellable_qty end
    ) stored,
    updated_at timestamptz not null default now(),
    primary key (warehouse_id, item_id)
);

create table if not exists inventory_transactions (
    id uuid primary key default gen_random_uuid(),
    warehouse_id uuid not null references warehouses(id),
    item_id uuid not null references inventory_items(id),
    batch_id uuid references inventory_batches(id),
    transaction_type varchar(32) not null check (transaction_type in ('opening','purchase','sale','sale_reversal','customer_return','other_in','other_out','adjustment','supplier_return')),
    quantity numeric(20,4) not null check (quantity <> 0),
    batch_unit_cost numeric(20,6) not null default 0,
    average_unit_cost numeric(20,6) not null default 0,
    reference_type varchar(64) not null,
    reference_id varchar(128) not null,
    idempotency_key varchar(255) not null unique,
    occurred_at timestamptz not null,
    created_by varchar(128),
    created_at timestamptz not null default now()
);

create index if not exists idx_inventory_transactions_item_time on inventory_transactions (warehouse_id, item_id, occurred_at desc);
create index if not exists idx_inventory_transactions_batch on inventory_transactions (batch_id, occurred_at desc);
create index if not exists idx_inventory_transactions_reference on inventory_transactions (reference_type, reference_id);

create table if not exists order_cost_snapshots (
    order_id varchar(128) primary key,
    platform varchar(32) not null,
    store_name varchar(255) not null,
    warehouse_id uuid not null references warehouses(id),
    bundle_id uuid references bundles(id),
    bom_version_id uuid references bundle_versions(id),
    product_cost numeric(20,6) not null default 0,
    shipping_fee numeric(20,6) not null default 0,
    total_cost numeric(20,6) not null default 0,
    average_cost_as_of timestamptz not null,
    created_at timestamptz not null default now()
);

create index if not exists idx_order_cost_snapshots_warehouse on order_cost_snapshots (warehouse_id, average_cost_as_of desc);
create index if not exists idx_order_cost_snapshots_bundle on order_cost_snapshots (bundle_id);
create index if not exists idx_order_cost_snapshots_bom_version on order_cost_snapshots (bom_version_id);

create table if not exists order_batch_allocations (
    order_id varchar(128) not null,
    item_id uuid not null references inventory_items(id),
    batch_id uuid not null references inventory_batches(id),
    quantity numeric(20,4) not null check (quantity > 0),
    batch_unit_cost numeric(20,6) not null,
    created_at timestamptz not null default now(),
    primary key (order_id, item_id, batch_id)
);

create index if not exists idx_order_batch_allocations_batch on order_batch_allocations (batch_id);
create index if not exists idx_order_batch_allocations_item on order_batch_allocations (item_id, created_at desc);

create table if not exists order_cost_snapshot_lines (
    id uuid primary key default gen_random_uuid(),
    order_id varchar(128) not null references order_cost_snapshots(order_id) on delete cascade,
    item_id uuid not null references inventory_items(id),
    bundle_id uuid references bundles(id),
    bom_version_id uuid references bundle_versions(id),
    quantity numeric(20,4) not null check (quantity > 0),
    average_unit_cost numeric(20,6) not null default 0,
    product_cost numeric(20,6) not null default 0,
    shipping_fee numeric(20,6) not null default 0,
    created_at timestamptz not null default now(),
    unique (order_id, item_id, bundle_id)
);

create index if not exists idx_order_cost_snapshot_lines_item on order_cost_snapshot_lines (item_id, created_at desc);
create index if not exists idx_order_cost_snapshot_lines_bom_version on order_cost_snapshot_lines (bom_version_id);

create table if not exists return_receipts (
    id uuid primary key default gen_random_uuid(),
    return_no varchar(64) not null unique,
    order_id varchar(128) not null,
    warehouse_id uuid not null references warehouses(id),
    status varchar(16) not null default 'pending' check (status in ('pending','received','inspected','completed','rejected','void')),
    received_at timestamptz,
    inspected_at timestamptz,
    inspected_by varchar(128),
    created_by varchar(128),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists return_receipt_lines (
    id uuid primary key default gen_random_uuid(),
    return_receipt_id uuid not null references return_receipts(id) on delete cascade,
    item_id uuid not null references inventory_items(id),
    quantity numeric(20,4) not null check (quantity > 0),
    target_status varchar(16) not null default 'inspection' check (target_status in ('inspection','sellable','defective','scrapped')),
    batch_id uuid references inventory_batches(id)
);

create index if not exists idx_return_receipts_warehouse_status on return_receipts (warehouse_id, status, created_at desc);
create index if not exists idx_return_receipt_lines_receipt on return_receipt_lines (return_receipt_id);
create index if not exists idx_return_receipt_lines_item on return_receipt_lines (item_id);
create index if not exists idx_return_receipt_lines_batch on return_receipt_lines (batch_id);

create table if not exists inventory_exceptions (
    id uuid primary key default gen_random_uuid(),
    order_id varchar(128) not null,
    warehouse_id uuid not null references warehouses(id),
    item_id uuid not null references inventory_items(id),
    requested_qty numeric(20,4) not null,
    available_qty numeric(20,4) not null,
    status varchar(16) not null default 'open' check (status in ('open','resolved','cancelled')),
    resolved_at timestamptz,
    resolved_by varchar(128),
    created_at timestamptz not null default now()
);

create index if not exists idx_inventory_exceptions_open on inventory_exceptions (warehouse_id, created_at desc) where status = 'open';
create index if not exists idx_inventory_exceptions_order on inventory_exceptions (order_id);
create index if not exists idx_inventory_exceptions_item_open on inventory_exceptions (item_id, created_at desc) where status = 'open';
