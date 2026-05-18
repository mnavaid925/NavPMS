## dump_module.ps1
##
## Generates a consolidated <NN>_<slug>.txt file in temp/ containing all backend
## (apps/<name>/) and frontend (templates/<name>/) code for one module.
##
## Usage:
##   pwsh .claude\skills\dump-module\dump_module.ps1 -Module pps
##   pwsh .claude\skills\dump-module\dump_module.ps1 -Module 4
##   pwsh .claude\skills\dump-module\dump_module.ps1 -Module "cost"
##   pwsh .claude\skills\dump-module\dump_module.ps1 -Module all      # regenerates every module

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Module,

    [string]$RepoRoot = 'c:\xampp\htdocs\NavMSM'
)

$ErrorActionPreference = 'Stop'

# -------- Module registry --------
# key = output file slug; value = @(<apps_folder>, <templates_folder>, <human title>)
$registry = [ordered]@{
    '01_tenant_subscription_management' = @('tenants',     'tenants',     '1. Tenant & Subscription Management')
    '02_product_lifecycle_management'   = @('plm',         'plm',         '2. Product Lifecycle Management (PLM)')
    '03_bill_of_materials'              = @('bom',         'bom',         '3. Bill of Materials (BOM) Management')
    '04_production_planning_scheduling' = @('pps',         'pps',         '4. Production Planning & Scheduling')
    '05_material_requirements_planning' = @('mrp',         'mrp',         '5. Material Requirements Planning (MRP)')
    '06_shop_floor_control_mes'         = @('mes',         'mes',         '6. Shop Floor Control (MES)')
    '07_quality_management'             = @('qms',         'qms',         '7. Quality Management (QMS)')
    '08_inventory_warehouse_management' = @('inventory',   'inventory',   '8. Inventory & Warehouse Management')
    '09_procurement_supplier_portal'    = @('procurement', 'procurement', '9. Procurement & Supplier Portal')
    '10_equipment_asset_management'     = @('eam',         'eam',         '10. Equipment & Asset Management (EAM)')
    '11_labor_workforce_management'     = @('labor',       'labor',       '11. Labor & Workforce Management')
    '12_cost_management_accounting'     = @('cost',        'cost',        '12. Cost Management & Accounting')
    '13_compliance_regulatory'          = @('compliance',  'compliance',  '13. Compliance & Regulatory Management')
    '14_energy_utility_management'      = @('utility',     'utility',     '14. Energy & Utility Management')
    '15_iot_scada_integration'          = @('iot',         'iot',         '15. IoT & SCADA Integration')
    '16_business_intelligence_analytics' = @('bi',         'bi',          '16. Business Intelligence & Analytics')
    '17_sales_customer_order'           = @('sales',       'sales',       '17. Sales & Customer Order Management')
    '18_returns_rma_management'         = @('rma',         'rma',         '18. Returns & RMA Management')
    '19_document_knowledge_management'  = @('dms',         'dms',         '19. Document & Knowledge Management')
    '20_workflow_automation'            = @('wfa',         'wfa',         '20. Workflow & Business Process Automation')
}

# Friendly aliases -> registry key
$aliases = @{
    # numeric
    '1'  = '01_tenant_subscription_management'
    '01' = '01_tenant_subscription_management'
    '2'  = '02_product_lifecycle_management'
    '02' = '02_product_lifecycle_management'
    '3'  = '03_bill_of_materials'
    '03' = '03_bill_of_materials'
    '4'  = '04_production_planning_scheduling'
    '04' = '04_production_planning_scheduling'
    '5'  = '05_material_requirements_planning'
    '05' = '05_material_requirements_planning'
    '6'  = '06_shop_floor_control_mes'
    '06' = '06_shop_floor_control_mes'
    '7'  = '07_quality_management'
    '07' = '07_quality_management'
    '8'  = '08_inventory_warehouse_management'
    '08' = '08_inventory_warehouse_management'
    '9'  = '09_procurement_supplier_portal'
    '09' = '09_procurement_supplier_portal'
    '10' = '10_equipment_asset_management'
    '11' = '11_labor_workforce_management'
    '12' = '12_cost_management_accounting'
    '13' = '13_compliance_regulatory'
    '14' = '14_energy_utility_management'
    '15' = '15_iot_scada_integration'
    '16' = '16_business_intelligence_analytics'
    '17' = '17_sales_customer_order'
    '18' = '18_returns_rma_management'
    '19' = '19_document_knowledge_management'
    '20' = '20_workflow_automation'
    # app folder names
    'tenants'     = '01_tenant_subscription_management'
    'tenant'      = '01_tenant_subscription_management'
    'plm'         = '02_product_lifecycle_management'
    'bom'         = '03_bill_of_materials'
    'pps'         = '04_production_planning_scheduling'
    'mrp'         = '05_material_requirements_planning'
    'mes'         = '06_shop_floor_control_mes'
    'qms'         = '07_quality_management'
    'quality'     = '07_quality_management'
    'inventory'   = '08_inventory_warehouse_management'
    'procurement' = '09_procurement_supplier_portal'
    'supplier'    = '09_procurement_supplier_portal'
    'eam'         = '10_equipment_asset_management'
    'asset'       = '10_equipment_asset_management'
    'labor'       = '11_labor_workforce_management'
    'workforce'   = '11_labor_workforce_management'
    'cost'        = '12_cost_management_accounting'
    'accounting'  = '12_cost_management_accounting'
    'compliance'  = '13_compliance_regulatory'
    'regulatory'  = '13_compliance_regulatory'
    'utility'     = '14_energy_utility_management'
    'energy'      = '14_energy_utility_management'
    'iot'         = '15_iot_scada_integration'
    'scada'       = '15_iot_scada_integration'
    'bi'          = '16_business_intelligence_analytics'
    'analytics'   = '16_business_intelligence_analytics'
    'sales'       = '17_sales_customer_order'
    'customer'    = '17_sales_customer_order'
    'rma'         = '18_returns_rma_management'
    'returns'     = '18_returns_rma_management'
    'dms'         = '19_document_knowledge_management'
    'document'    = '19_document_knowledge_management'
    'knowledge'   = '19_document_knowledge_management'
    'wfa'         = '20_workflow_automation'
    'workflow'    = '20_workflow_automation'
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
  Number:       1..12  (or 01..12)
  App folder:   tenants, plm, bom, pps, mrp, mes, qms, inventory, procurement, eam, labor, cost
  Special:      all   (regenerate every module)

Examples:
  pwsh .claude\skills\dump-module\dump_module.ps1 -Module pps
  pwsh .claude\skills\dump-module\dump_module.ps1 -Module 4
  pwsh .claude\skills\dump-module\dump_module.ps1 -Module cost
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
