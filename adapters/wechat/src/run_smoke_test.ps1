# run_smoke_test.ps1 - WeChat 4.1.12.26 自建管道全链路冒烟（H1+H2）
#
# 原则：全程只读，不重启/不退出微信、不影响登录状态。
#   H1: 只读密钥提取（wcdb-key-tool runtime 扫描，仅当密钥文件缺失时）→ sqlcipher3 直读验证
#   H2: collector --once → loader → staging 统计 → 二次 0 增量 → pytest
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File adapters\wechat\src\run_smoke_test.ps1

param(
    [string]$AccountName = "wxid_of4c5546po6t22_606e"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$py = Join-Path $root ".venv-data\Scripts\python.exe"
$src = Join-Path $root "adapters\wechat\src"
$vendor = Join-Path $root "adapters\wechat\src\vendor"
$keysDefault = Join-Path $root "runtime\tmp\wechat\wcd_scan\all_keys.json"
$dbStorage = Join-Path "D:\xwechat_files" ($AccountName + "\db_storage")
$stateOut = Join-Path $root "runtime\state\wechat"

Write-Host "== WeChat self-hosted pipeline smoke (H1+H2, read-only) =="
if (-not (Test-Path $py)) { Write-Host "ERROR: python not found: $py"; exit 1 }
if (-not (Test-Path $dbStorage)) { Write-Host "ERROR: db_storage not found: $dbStorage"; exit 1 }
Write-Host ("account      : " + $AccountName)
Write-Host ("db_storage   : " + $dbStorage)

# 1. dependencies
& $py -c "import sqlcipher3, Crypto" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing sqlcipher3 + pycryptodome ..."
    & $py -m pip install --quiet sqlcipher3 pycryptodome
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: pip install failed"; exit 1 }
}
Write-Host "deps: OK"

# 2. keys: prefer existing; else read-only runtime scan (does NOT touch WeChat)
$keys = $keysDefault
if (-not (Test-Path $keys)) {
    Write-Host "Keys file missing -> running read-only runtime scan (no WeChat restart)..."
    $scanOut = Join-Path $root "runtime\tmp\wechat\wcd_scan"
    New-Item -ItemType Directory -Force -Path $scanOut | Out-Null
    & $py -u (Join-Path $vendor "wcdb-key-tool\wcdb_key_tool_windows.py") extract `
        --db-dir $dbStorage --output (Join-Path $scanOut "all_keys.json")
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: key extraction failed"; exit 1 }
}
Write-Host ("keys         : " + $keys)

# 3. H1 verify: read-only direct query (encrypted DB + WAL auto-replay)
$h1Script = Join-Path $env:TEMP "wechat_h1_verify.py"
@'
# -*- coding: utf-8 -*-
import json, os, sys, sqlcipher3.dbapi2 as sqlite
keys_file, db_dir = sys.argv[1], sys.argv[2]
keys = json.load(open(keys_file, encoding="utf-8"))
def ro(rel):
    con = sqlite.connect("file:" + os.path.join(db_dir, rel).replace("\\", "/") + "?mode=ro", uri=True, isolation_level=None)
    cur = con.cursor()
    cur.execute("PRAGMA key = \"x'%s'\"" % keys[rel]["enc_key"])
    return con, cur
con, cur = ro("message\\message_0.db")
tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
n = sum(cur.execute("SELECT COUNT(*) FROM '%s'" % t).fetchone()[0] for t in tables)
con.close()
con, cur = ro("sns\\sns.db")
m = cur.execute("SELECT COUNT(*) FROM SnsTimeLine").fetchone()[0]
con.close()
print("msg_tables=%d msg_rows=%d sns_rows=%d" % (len(tables), n, m))
'@ | Out-File -FilePath $h1Script -Encoding UTF8
$h1 = & $py $h1Script $keys $dbStorage
Write-Host ("H1 read-only : " + $h1)

# 4. H2 pipeline: collect -> load -> verify（单命令链路）
New-Item -ItemType Directory -Force -Path $stateOut | Out-Null
$r1 = & $py -u (Join-Path $src "collector.py") --once --load --keys $keys --db-dir $dbStorage --out $stateOut `
    --scope (Join-Path $root "adapters\wechat\config\scope.json")
Write-Host ("collect #1   : " + $r1)
$r2 = & $py -u (Join-Path $src "collector.py") --once --load --keys $keys --db-dir $dbStorage --out $stateOut `
    --scope (Join-Path $root "adapters\wechat\config\scope.json")
Write-Host ("collect #2   : " + $r2 + "  (expect events=0)")

# 5. pytest
Push-Location $root
try {
    & $py -m pytest adapters/wechat/tests -q
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: pytest failed"; exit 1 }
} finally { Pop-Location }

Write-Host ""
Write-Host "== DONE =="
Write-Host ("L0 + staging : " + $stateOut)
