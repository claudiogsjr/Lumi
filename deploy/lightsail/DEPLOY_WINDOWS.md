Deploy via Windows

Script
- `deploy/lightsail/deploy_from_windows.ps1`

O script usa por padrao:
- host: `SEU_IP_LIGHTSAIL`
- usuario: `ubuntu`
- chave: `deploy\\lightsail\\keys\\guardian-lightsail-key.pem`
- diretorio remoto: `/opt/guardian-weather-watch`

Uso
```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\lightsail\deploy_from_windows.ps1
```

Opcoes uteis
```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\lightsail\deploy_from_windows.ps1 `
  -KeyPath "C:\caminho\para\guardian-lightsail-key.pem" `
  -HostName "SEU_IP_LIGHTSAIL" `
  -StepRetries 3
```

Sem rebuild remoto
```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\lightsail\deploy_from_windows.ps1 -SkipBuild
```

Observacao importante
- A instancia atual precisa aceitar a chave passada em `-KeyPath`.
- Se o SSH retornar `Permission denied (publickey)`, use a chave real associada a instancia.
- O build de producao agora roda no servidor via `deploy/lightsail/build_release.sh`.
- As migrations do Postgres rodam no servidor via `deploy/lightsail/run_migrations.sh`.
- Backup manual do Postgres:
```powershell
ssh -i .\deploy\lightsail\keys\guardian-lightsail-key.pem ubuntu@SEU_IP_LIGHTSAIL "APP_DIR=/opt/guardian-weather-watch /opt/guardian-weather-watch/deploy/lightsail/backup_postgres.sh"
```
- Restore manual do Postgres exige confirmacao explicita:
```powershell
ssh -i .\deploy\lightsail\keys\guardian-lightsail-key.pem ubuntu@SEU_IP_LIGHTSAIL "APP_DIR=/opt/guardian-weather-watch RESTORE_CONFIRM=1 /opt/guardian-weather-watch/deploy/lightsail/restore_postgres.sh /opt/guardian-weather-watch/backups/postgres/arquivo.dump"
```
- O servico `guardian-weather.service` apenas inicia a aplicacao. Ele nao instala dependencias nem executa build no boot.
- Antes de publicar, o script cria um backup seletivo em `/opt/guardian-weather-watch/.previous_release`.
- Rollback manual:
```powershell
ssh -i .\deploy\lightsail\keys\guardian-lightsail-key.pem ubuntu@SEU_IP_LIGHTSAIL "APP_DIR=/opt/guardian-weather-watch /opt/guardian-weather-watch/deploy/lightsail/rollback_last_release.sh"
```
