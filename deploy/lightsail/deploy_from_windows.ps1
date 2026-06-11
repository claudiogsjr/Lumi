param(
    [string]$HostName = "SEU_IP_LIGHTSAIL",
    [string]$UserName = "ubuntu",
    [string]$KeyPath = "$PSScriptRoot\keys\guardian-lightsail-key.pem",
    [string]$RemoteDir = "/opt/guardian-weather-watch",
    [int]$StepRetries = 3,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Comando obrigatorio nao encontrado: $Name"
    }
}

function Run-Step([string]$Message, [scriptblock]$Action) {
    for ($Attempt = 1; $Attempt -le $StepRetries; $Attempt++) {
        Write-Host "==> $Message"
        if ($StepRetries -gt 1) {
            Write-Host "    tentativa $Attempt/$StepRetries"
        }
        $global:LASTEXITCODE = 0
        try {
            & $Action
            if ($global:LASTEXITCODE -eq 0) {
                return
            }
            $FailureMessage = "exit code $global:LASTEXITCODE"
        }
        catch {
            $FailureMessage = $_.Exception.Message
        }
        if ($Attempt -lt $StepRetries) {
            Write-Warning "Falha na etapa '$Message' ($FailureMessage). Tentando novamente em 10s."
            Start-Sleep -Seconds 10
            continue
        }
        throw "Falha na etapa '$Message' apos $StepRetries tentativa(s): $FailureMessage."
    }
}

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$FrontendDir = Join-Path $ProjectRoot "frontend"
$DistDir = Join-Path $FrontendDir "dist"
$AppPath = Join-Path $ProjectRoot "App.py"
$Remote = "$UserName@$HostName"

Require-Command "ssh"
Require-Command "scp"

if (-not (Test-Path $KeyPath)) {
    throw "Chave SSH nao encontrada em '$KeyPath'."
}

if (-not (Test-Path $AppPath)) {
    throw "Arquivo App.py nao encontrado em '$AppPath'."
}

Run-Step "Validando acesso SSH em $Remote" {
    ssh -i $KeyPath -o StrictHostKeyChecking=accept-new $Remote "echo ok"
}

Run-Step "Preparando diretorios remotos" {
    ssh -i $KeyPath -o StrictHostKeyChecking=accept-new $Remote "mkdir -p ${RemoteDir}/frontend ${RemoteDir}/deploy/lightsail ${RemoteDir}/docs ${RemoteDir}/scripts"
}

Run-Step "Criando backup seletivo do release atual" {
    ssh -i $KeyPath -o StrictHostKeyChecking=accept-new $Remote "set -e; BACKUP_DIR='${RemoteDir}/.previous_release'; rm -rf `"`$BACKUP_DIR`"; mkdir -p `"`$BACKUP_DIR`"; cd ${RemoteDir}; for item in App.py production_config.py orchestrator_hf_json_final.py openweather_client.py plugfield_client.py requirements.txt frontend/package.json frontend/package-lock.json frontend/index.html frontend/postcss.config.js frontend/tailwind.config.js frontend/vite.config.js frontend/src frontend/dist deploy/lightsail docs scripts; do if [ -e `$item ]; then mkdir -p `"`$BACKUP_DIR/`$(dirname `$item)`"; cp -a `$item `"`$BACKUP_DIR/`$item`"; fi; done"
}

Run-Step "Enviando backend e configuracao" {
    scp -i $KeyPath -o StrictHostKeyChecking=accept-new `
        "$ProjectRoot\App.py" `
        "$ProjectRoot\production_config.py" `
        "$ProjectRoot\db_migrations.py" `
        "$ProjectRoot\orchestrator_hf_json_final.py" `
        "$ProjectRoot\openweather_client.py" `
        "$ProjectRoot\plugfield_client.py" `
        "$ProjectRoot\logging_config.py" `
        "$ProjectRoot\requirements.txt" `
        "${Remote}:${RemoteDir}/"
}

Run-Step "Enviando frontend fonte" {
    scp -r -i $KeyPath -o StrictHostKeyChecking=accept-new `
        "$FrontendDir\package.json" `
        "$FrontendDir\package-lock.json" `
        "$FrontendDir\index.html" `
        "$FrontendDir\postcss.config.js" `
        "$FrontendDir\tailwind.config.js" `
        "$FrontendDir\vite.config.js" `
        "$FrontendDir\src" `
        "${Remote}:${RemoteDir}/frontend/"
}

Run-Step "Enviando scripts e docs de producao" {
    scp -r -i $KeyPath -o StrictHostKeyChecking=accept-new `
        "$ProjectRoot\deploy\lightsail\build_release.sh" `
        "$ProjectRoot\deploy\lightsail\run_migrations.sh" `
        "$ProjectRoot\deploy\lightsail\backup_postgres.sh" `
        "$ProjectRoot\deploy\lightsail\restore_postgres.sh" `
        "$ProjectRoot\deploy\lightsail\prune_jsonl.sh" `
        "$ProjectRoot\deploy\lightsail\rollback_last_release.sh" `
        "$ProjectRoot\deploy\lightsail\start_app.sh" `
        "$ProjectRoot\deploy\lightsail\setup_server.sh" `
        "$ProjectRoot\deploy\lightsail\guardian-weather.service" `
        "$ProjectRoot\deploy\lightsail\nginx-guardian-weather.conf" `
        "$ProjectRoot\deploy\lightsail\logrotate-guardian-weather" `
        "${Remote}:${RemoteDir}/deploy/lightsail/"
    scp -i $KeyPath -o StrictHostKeyChecking=accept-new `
        "$ProjectRoot\deploy\smoke_test_prod.sh" `
        "${Remote}:${RemoteDir}/deploy/"
    scp -r -i $KeyPath -o StrictHostKeyChecking=accept-new "$ProjectRoot\docs" "${Remote}:${RemoteDir}/"
    scp -r -i $KeyPath -o StrictHostKeyChecking=accept-new "$ProjectRoot\scripts" "${Remote}:${RemoteDir}/"
}

if (-not $SkipBuild) {
    Run-Step "Buildando release no servidor" {
        ssh -i $KeyPath -o StrictHostKeyChecking=accept-new $Remote "cd ${RemoteDir} && chmod +x deploy/lightsail/build_release.sh deploy/lightsail/run_migrations.sh deploy/lightsail/backup_postgres.sh deploy/lightsail/restore_postgres.sh deploy/lightsail/prune_jsonl.sh deploy/lightsail/rollback_last_release.sh deploy/lightsail/start_app.sh && APP_DIR=${RemoteDir} deploy/lightsail/build_release.sh"
    }
}

Run-Step "Aplicando migrations do banco" {
    ssh -i $KeyPath -o StrictHostKeyChecking=accept-new $Remote "cd ${RemoteDir} && chmod +x deploy/lightsail/run_migrations.sh && APP_DIR=${RemoteDir} deploy/lightsail/run_migrations.sh"
}

Run-Step "Instalando systemd e Nginx" {
    ssh -i $KeyPath -o StrictHostKeyChecking=accept-new $Remote "sudo cp ${RemoteDir}/deploy/lightsail/guardian-weather.service /etc/systemd/system/guardian-weather.service && sudo systemctl daemon-reload && sudo cp ${RemoteDir}/deploy/lightsail/logrotate-guardian-weather /etc/logrotate.d/guardian-weather && sudo cp ${RemoteDir}/deploy/lightsail/nginx-guardian-weather.conf /etc/nginx/sites-available/guardian-weather && sudo ln -sf /etc/nginx/sites-available/guardian-weather /etc/nginx/sites-enabled/guardian-weather && sudo nginx -t && sudo systemctl reload nginx"
}

Run-Step "Reiniciando servico guardian-weather.service" {
    ssh -i $KeyPath -o StrictHostKeyChecking=accept-new $Remote "sudo systemctl restart guardian-weather.service && sleep 3 && systemctl is-active guardian-weather.service"
}

Run-Step "Validando rotas publicadas" {
    ssh -i $KeyPath -o StrictHostKeyChecking=accept-new $Remote "cd ${RemoteDir} && SMOKE_BASE_URL=http://127.0.0.1:8080 SMOKE_ATTEMPTS=8 SMOKE_SLEEP_SECONDS=8 SMOKE_TIMEOUT_SECONDS=30 python3 scripts/smoke_test.py"
}

Run-Step "Executando smoke test funcional em producao" {
    ssh -i $KeyPath -o StrictHostKeyChecking=accept-new $Remote "cd ${RemoteDir} && chmod +x deploy/smoke_test_prod.sh && SMOKE_BASE_URL=http://127.0.0.1:8080 bash deploy/smoke_test_prod.sh"
}

Write-Host "Deploy concluido."
