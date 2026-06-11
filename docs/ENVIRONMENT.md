# Variaveis de Ambiente

Este documento lista as variaveis necessarias para rodar o projeto em producao. Nao coloque valores reais neste arquivo.

## Aplicacao

- `APP_ENV`: use `production` em producao.
- `PORT`: porta do backend Flask/Gunicorn. Padrao operacional atual: `8080`.
- `FLASK_SECRET_KEY`: segredo forte para cookies de sessao Flask. Obrigatorio em producao.
- `DASHBOARD_ACCESS_TOKEN`: token administrativo do dashboard. Obrigatorio em producao.
- `SESSION_COOKIE_SECURE`: use `1` quando estiver atras de HTTPS.
- `SESSION_COOKIE_SAMESITE`: normalmente `Lax`.
- `MAX_CONTENT_LENGTH_BYTES`: limite maximo do corpo HTTP. Exemplo: `1048576`.
- `CHAT_MAX_CONCURRENCY`: numero maximo de chamadas simultaneas ao `/chat`.
- `CHAT_MAX_MESSAGE_CHARS`: tamanho maximo da mensagem do usuario no `/chat`.

## Banco de Dados

- `POSTGRES_ENABLED`: `1` para usar Postgres.
- `PGHOST`: host do Postgres.
- `PGPORT`: porta do Postgres.
- `PGDATABASE`: nome do banco.
- `PGUSER`: usuario.
- `PGPASSWORD`: senha.
- `PGSSLMODE`: normalmente `require`.

## OpenWeather

- `OPENWEATHER_API_KEY`: chave da API OpenWeather.
- `WEATHER_DEFAULT_CITY`: cidade default para consultas sem cidade explicita.

Observacao: `WEATHER_API_KEY` ainda e aceito como fallback de compatibilidade, mas o nome recomendado e `OPENWEATHER_API_KEY`.

## Plugfield

- `PLUGFIELD_LOGIN_URL`: endpoint de login.
- `PLUGFIELD_DEVICE_URL`: endpoint de dispositivos/estacoes.
- `PLUGFIELD_USERNAME`: usuario.
- `PLUGFIELD_PASSWORD`: senha.
- `PLUGFIELD_API_KEY`: chave da API.
- `PLUGFIELD_CENTER_LAT`: latitude de referencia.
- `PLUGFIELD_CENTER_LON`: longitude de referencia.

## Orquestrador / LLM

- `HF_MODEL_ID`: modelo Hugging Face.
- `HF_NUM_THREADS`: threads de CPU para PyTorch.
- `HF_NUM_INTEROP`: threads interop.
- `OMP_NUM_THREADS`: threads OpenMP.
- `MKL_NUM_THREADS`: threads MKL.
- `ORCH_MAX_NEW_TOKENS`: limite geral de tokens.
- `ORCH_JSON_RETRIES`: tentativas extras para JSON valido.
- `ORCH_LLM_TIMEOUT_S`: timeout conceitual/operacional.
- `ORCH_INCLUDE_LLM_RAW`: padrao recomendado `0` em producao. Use `1` apenas se houver necessidade academica de auditar raw output.
- `ORCH_LLM_RAW_MAXCHARS`: limite de caracteres do raw output.
- `ORCH_SLOW_MODE`: modo robusto/lento.
- `ORCH_CLS_MAX_NEW_TOKENS`: limite de tokens na classificacao.
- `ORCH_ENABLE_RT_OVERRIDE`: habilita override por tempo real.
- `ORCH_ENABLE_PV_OVERRIDE`: habilita override por previsao.
- `ORCH_USE_LLM`: liga/desliga LLM.
- `ORCH_STRICT_LLM`: falha se o LLM falhar.

## Logs Locais

Estas variaveis existem para fallback local. Em producao, prefira Postgres e logs estruturados no stdout.

- `USER_LOG_PATH`
- `USABILITY_SESSIONS_PATH`
- `USABILITY_CHAT_LOGS_PATH`
- `USABILITY_SURVEYS_PATH`
- `ORCH_LOG_PATH`

## Checklist De Producao

- Gerar novos valores para todos os segredos.
- Confirmar que `.env` nao esta versionado.
- Confirmar que chaves `.pem` nao estao versionadas.
- Configurar `SESSION_COOKIE_SECURE=1` depois de habilitar HTTPS.
- Manter `ORCH_INCLUDE_LLM_RAW=0` em producao se os dados puderem conter informacao sensivel.
