## dump_module.ps1
##
## Generates a consolidated <NN>_<slug>.txt file in temp/ containing all backend
## (apps/<name>/) and frontend (templates/<name>/) code for one NavPMS module.
##
## Usage:
##   pwsh .claude\skills\dump-module\dump_module.ps1 -Module rfx
##   pwsh .claude\skills\dump-module\dump_module.ps1 -Module 7
##   pwsh .claude\skills\dump-module\dump_module.ps1 -Module "fulfillment"
##   pwsh .claude\skills\dump-module\dump_module.ps1 -Module all      # regenerates every module

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Module,

    [string]$RepoRoot = 'c:\xampp\htdocs\NavPMS'
)

$ErrorActionPreference = 'Stop'

# -------- Module registry --------
# key = output file slug; value = @(<apps_folder>, <templates_folder>, <human title>)
# Real module numbers follow PMS.md (the spec's `### N` headers are offset +1).
$registry = [ordered]@{
    '01_tenant_subscription_management' = @('tenants',         'tenants',         '1. Tenant & Subscription Management')
    '02_user_dashboard_portal'          = @('portal',          'portal',          '2. User Dashboard & Portal')
    '03_requisition_management'         = @('requisitions',    'requisitions',    '3. Requisition Management')
    '04_approval_workflow_engine'       = @('approvals',       'approvals',       '4. Approval Workflow Engine')
    '05_vendor_management'              = @('vendors',         'vendors',         '5. Vendor Management')
    '06_sourcing_tendering'             = @('sourcing',        'sourcing',        '6. Sourcing & Tendering')
    '07_rfx_management'                 = @('rfx',             'rfx',             '7. RFx Management (RFI, RFP, RFQ)')
    '08_eauction_management'            = @('auctions',        'auctions',        '8. E-Auction Management')
    '09_contract_management'            = @('contracts',       'contracts',       '9. Contract Management')
    '10_catalog_management'             = @('catalog',         'catalog',         '10. Catalog Management')
    '11_purchase_order_management'      = @('purchase_orders', 'purchase_orders', '11. Purchase Order (PO) Management')
    '12_order_fulfillment_tracking'     = @('fulfillment',     'fulfillment',     '12. Order Fulfillment & Tracking')
    '13_goods_receipt_inspection'       = @('goods_receipt',   'goods_receipt',   '13. Goods Receipt & Inspection')
}

# Friendly aliases -> registry key
$aliases = @{
    # numeric
    '1'  = '01_tenant_subscription_management'
    '01' = '01_tenant_subscription_management'
    '2'  = '02_user_dashboard_portal'
    '02' = '02_user_dashboard_portal'
    '3'  = '03_requisition_management'
    '03' = '03_requisition_management'
    '4'  = '04_approval_workflow_engine'
    '04' = '04_approval_workflow_engine'
    '5'  = '05_vendor_management'
    '05' = '05_vendor_management'
    '6'  = '06_sourcing_tendering'
    '06' = '06_sourcing_tendering'
    '7'  = '07_rfx_management'
    '07' = '07_rfx_management'
    '8'  = '08_eauction_management'
    '08' = '08_eauction_management'
    '9'  = '09_contract_management'
    '09' = '09_contract_management'
    '10' = '10_catalog_management'
    '11' = '11_purchase_order_management'
    '12' = '12_order_fulfillment_tracking'
    '13' = '13_goods_receipt_inspection'
    # app folder names
    'tenants'         = '01_tenant_subscription_management'
    'tenant'          = '01_tenant_subscription_management'
    'portal'          = '02_user_dashboard_portal'
    'dashboard'       = '02_user_dashboard_portal'
    'requisitions'    = '03_requisition_management'
    'requisition'     = '03_requisition_management'
    'pr'              = '03_requisition_management'
    'approvals'       = '04_approval_workflow_engine'
    'approval'        = '04_approval_workflow_engine'
    'vendors'         = '05_vendor_management'
    'vendor'          = '05_vendor_management'
    'supplier'        = '05_vendor_management'
    'sourcing'        = '06_sourcing_tendering'
    'tendering'       = '06_sourcing_tendering'
    'rfx'             = '07_rfx_management'
    'rfi'             = '07_rfx_management'
    'rfp'             = '07_rfx_management'
    'rfq'             = '07_rfx_management'
    'auctions'        = '08_eauction_management'
    'auction'         = '08_eauction_management'
    'eauction'        = '08_eauction_management'
    'contracts'       = '09_contract_management'
    'contract'        = '09_contract_management'
    'catalog'         = '10_catalog_management'
    'purchase_orders' = '11_purchase_order_management'
    'purchaseorders'  = '11_purchase_order_management'
    'po'              = '11_purchase_order_management'
    'fulfillment'     = '12_order_fulfillment_tracking'
    'fulfilment'      = '12_order_fulfillment_tracking'
    'shipping'        = '12_order_fulfillment_tracking'
    'goods_receipt'   = '13_goods_receipt_inspection'
    'goodsreceipt'    = '13_goods_receipt_inspection'
    'grn'             = '13_goods_receipt_inspection'
    'receipt'         = '13_goods_receipt_inspection'
}

# -------- Resolve which keys to process --------
$targetKeys = @()
$lookup = $Module.Trim().ToLower()

if ($lookup -eq 'all' -or $lookup -eq '*') {
    $targetKeys = @($registry.Keys)
}
elseif ($registry.Contains($Module)) {
    $targetKeys = @($Module)
}
elseif ($aliases.ContainsKey($lookup)) {
    $targetKeys = @($aliases[$lookup])
}
else {
    # last-chance fuzzy: contains match against title
    foreach ($k in $registry.Keys) {
        $title = $registry[$k][2].ToLower()
        if ($title -like "*$lookup*") {
            $targetKeys = @($k)
            break
        }
    }
}

if ($targetKeys.Count -eq 0) {
    Write-Error @"
Unknown module: '$Module'.

Valid identifiers:
  Number:       1..13  (or 01..13)
  App folder:   tenants, portal, requisitions, approvals, vendors, sourcing, rfx, auctions, contracts, catalog, purchase_orders, fulfillment, goods_receipt
  Special:      all   (regenerate every module)

Examples:
  pwsh .claude\skills\dump-module\dump_module.ps1 -Module rfx
  pwsh .claude\skills\dump-module\dump_module.ps1 -Module 7
  pwsh .claude\skills\dump-module\dump_module.ps1 -Module fulfillment
  pwsh .claude\skills\dump-module\dump_module.ps1 -Module all
"@
    exit 1
}

# -------- Ensure temp/ exists --------
$outDir = Join-Path $RepoRoot 'temp'
if (-not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

# -------- Helpers --------
function Add-Section {
    param([string]$OutFile, [string]$Header)
    $banner = ('=' * 100)
    Add-Content -Path $OutFile -Value "`r`n$banner`r`n$Header`r`n$banner`r`n" -Encoding UTF8
}

function Add-FileBlock {
    param([string]$OutFile, [System.IO.FileInfo]$File, [string]$RelPath)
    $sub = ('-' * 100)
    Add-Content -Path $OutFile -Value "`r`n$sub`r`nFILE: $RelPath`r`n$sub" -Encoding UTF8
    $content = [System.IO.File]::ReadAllText($File.FullName)
    Add-Content -Path $OutFile -Value $content -Encoding UTF8
}

# -------- Generate --------
foreach ($key in $targetKeys) {
    $appsFolder, $tplFolder, $title = $registry[$key]
    $outFile = Join-Path $outDir "$key.txt"

    Set-Content -Path $outFile -Value "" -Encoding UTF8

    $banner = ('#' * 100)
    Add-Content -Path $outFile -Value "$banner`r`n# MODULE $title`r`n# Backend:  apps\$appsFolder\`r`n# Frontend: templates\$tplFolder\`r`n# Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`r`n$banner" -Encoding UTF8

    # Backend
    $appsPath = Join-Path $RepoRoot "apps\$appsFolder"
    if (Test-Path $appsPath) {
        Add-Section -OutFile $outFile -Header "BACKEND  (apps\$appsFolder\)"
        $files = Get-ChildItem -Path $appsPath -Recurse -File `
            | Where-Object { $_.FullName -notmatch '__pycache__' } `
            | Where-Object { $_.Extension -in '.py', '.txt', '.md', '.json', '.yml', '.yaml', '.cfg', '.ini' } `
            | Sort-Object FullName
        foreach ($f in $files) {
            $rel = $f.FullName.Substring($RepoRoot.Length + 1)
            Add-FileBlock -OutFile $outFile -File $f -RelPath $rel
        }
    } else {
        Add-Content -Path $outFile -Value "`r`n(no backend folder found at apps\$appsFolder\)`r`n" -Encoding UTF8
    }

    # Frontend
    $tplPath = Join-Path $RepoRoot "templates\$tplFolder"
    if (Test-Path $tplPath) {
        Add-Section -OutFile $outFile -Header "FRONTEND  (templates\$tplFolder\)"
        $files = Get-ChildItem -Path $tplPath -Recurse -File `
            | Where-Object { $_.Extension -in '.html', '.htm', '.js', '.css', '.txt' } `
            | Sort-Object FullName
        foreach ($f in $files) {
            $rel = $f.FullName.Substring($RepoRoot.Length + 1)
            Add-FileBlock -OutFile $outFile -File $f -RelPath $rel
        }
    } else {
        Add-Content -Path $outFile -Value "`r`n(no frontend folder found at templates\$tplFolder\)`r`n" -Encoding UTF8
    }

    $size = (Get-Item $outFile).Length
    Write-Output ("OK  {0,-45} {1,12:N0} bytes  ->  temp\{0}.txt" -f $key, $size)
}
