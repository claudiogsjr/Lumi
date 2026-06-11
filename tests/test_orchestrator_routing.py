"""
Testes de regressão do roteamento do orquestrador (modo kw_only / override).

Cobrem:
  - Handlers pré-SLM: _PAT_TEMP_ATUAL, _PAT_UMIDADE_ATUAL,
    _PAT_VENTO_ATUAL, _PAT_PRESSAO_ATUAL
  - PV_REGEX: marcadores temporais futuros (domingo, feriado, logo mais etc.)
  - RT_REGEX / ESTAC_REGEX: sinais de tempo real
  - ORCH_KW_FALLBACK: fallback por keyword quando LLM lança exceção
  - Falsos positivos de chuva atual vs. previsão futura (rodada 1)
"""

import re
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("ORCH_SKIP_WARMUP", "1")
os.environ.setdefault("APP_ENV", "local")

import orchestrator_hf_json_final as orch_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pat_matches(pattern, texts):
    """Asserta que todos os textos casam com o padrão."""
    for t in texts:
        assert pattern.search(t), f"Esperado match para: {repr(t)}"


def _pat_no_match(pattern, texts):
    """Asserta que nenhum texto casa com o padrão."""
    for t in texts:
        assert not pattern.search(t), f"Esperado NO match para: {repr(t)}"


# ---------------------------------------------------------------------------
# 1. Padrões de temperatura genérica
# ---------------------------------------------------------------------------

class TestPatTempAtual(unittest.TestCase):

    def test_matches_expected(self):
        cases = [
            "Qual a temperatura agora?",
            "Como está a temperatura?",
            "Temperatura atual",
            "Qual é a temperatura?",
            "Temp agora",
        ]
        for q in cases:
            with self.subTest(q=q):
                self.assertIsNotNone(
                    orch_mod._PAT_TEMP_ATUAL.search(orch_mod._strip_accents(q)),
                    f"Esperado match: {q!r}",
                )

    def test_no_false_positive_forecast(self):
        """Perguntas de previsão de temperatura NÃO devem casar com _PAT_TEMP_ATUAL."""
        cases = [
            "Qual a temperatura para amanhã?",
            "Qual será a temperatura no domingo?",
            "Temperatura de amanhã",
        ]
        for q in cases:
            with self.subTest(q=q):
                self.assertIsNone(
                    orch_mod._PAT_TEMP_ATUAL.search(orch_mod._strip_accents(q)),
                    f"Falso positivo: {q!r}",
                )


# ---------------------------------------------------------------------------
# 2. Padrões de umidade genérica
# ---------------------------------------------------------------------------

class TestPatUmidadeAtual(unittest.TestCase):

    def test_matches_expected(self):
        cases = [
            "Qual a umidade do ar?",
            "Umidade agora?",
            "Como está a umidade atual?",
            "Qual é a umidade?",
            "Como está a umidade?",
        ]
        for q in cases:
            with self.subTest(q=q):
                self.assertIsNotNone(
                    orch_mod._PAT_UMIDADE_ATUAL.search(orch_mod._strip_accents(q)),
                    f"Esperado match: {q!r}",
                )


# ---------------------------------------------------------------------------
# 3. Padrões de vento genérico
# ---------------------------------------------------------------------------

class TestPatVentoAtual(unittest.TestCase):

    def test_matches_expected(self):
        cases = [
            "Como está o vento?",
            "Qual a velocidade do vento?",
            "Vento agora?",
            "Qual é o vento atual?",
            "Tem rajada agora?",
            "Onde esta ventando?",
            "Onde venta mais?",
            "Qual bairro esta com mais vento?",
        ]
        for q in cases:
            with self.subTest(q=q):
                self.assertIsNotNone(
                    orch_mod._PAT_VENTO_ATUAL.search(orch_mod._strip_accents(q)),
                    f"Esperado match: {q!r}",
                )


# ---------------------------------------------------------------------------
# 4. Padrões de pressão genérica
# ---------------------------------------------------------------------------

class TestPatPressaoAtual(unittest.TestCase):

    def test_matches_expected(self):
        cases = [
            "Qual a pressão atmosférica?",
            "Pressão agora?",
            "Como está a pressão?",
            "Qual é a pressão atual?",
        ]
        for q in cases:
            with self.subTest(q=q):
                self.assertIsNotNone(
                    orch_mod._PAT_PRESSAO_ATUAL.search(orch_mod._strip_accents(q)),
                    f"Esperado match: {q!r}",
                )


# ---------------------------------------------------------------------------
# 5. Padroes e roteamento de nivel do rio
# ---------------------------------------------------------------------------

class TestNivelRioAtual(unittest.TestCase):

    def test_matches_expected(self):
        cases = [
            "Qual o nivel do rio?",
            "Como esta o nivel de rio no jardim do lago?",
            "Nivel do rio no Jardim do Lago",
            "Piezometro do Jardim do Lago",
        ]
        for q in cases:
            with self.subTest(q=q):
                self.assertIsNotNone(
                    orch_mod._PAT_NIVEL_RIO.search(orch_mod._strip_accents(q)),
                    f"Esperado match: {q!r}",
                )

    def test_routes_to_station_specific_answer(self):
        stations = [
            {"name": "12 - OESTE - JARDIM DAS INDUSTRIAS", "river_level": None},
            {
                "name": "08 - SUDESTE - JARDIM DO LAGO",
                "river_level": 0.31,
                "river_level_unit": "mca",
            },
        ]
        with patch.object(orch_mod, "_fetch_all_stations_safe", return_value=stations):
            result = orch_mod.handle_analytical_query("Como esta o nivel de rio no jardim do lago?")

        self.assertIsNotNone(result)
        answer, handler = result
        self.assertEqual(handler, "nivel_rio")
        self.assertIn("JARDIM DO LAGO", answer)
        self.assertIn("0.31", answer)
        self.assertIn("mca", answer)


# ---------------------------------------------------------------------------
# 5. PV_REGEX — marcadores temporais futuros (rodada 1 + ampliação)
# ---------------------------------------------------------------------------

class TestPvRegex(unittest.TestCase):

    def test_classic_markers(self):
        cases = [
            "Vai chover amanhã?",
            "Qual a previsão para sexta?",
            "Clima para o fim de semana",
            "Vai chover?",
        ]
        for q in cases:
            with self.subTest(q=q):
                self.assertIsNotNone(orch_mod.PV_REGEX.search(q), f"Esperado PV_REGEX match: {q!r}")

    def test_new_day_markers(self):
        """Dias da semana devem casar como marcadores de futuro."""
        cases = [
            "Como vai estar no domingo?",
            "Previsão para segunda-feira?",
            "Vai chover no sábado?",
            "Clima na quinta?",
            "E no feriado, chove?",
        ]
        for q in cases:
            with self.subTest(q=q):
                self.assertIsNotNone(orch_mod.PV_REGEX.search(q), f"Esperado PV_REGEX match: {q!r}")

    def test_colloquial_future(self):
        """Expressões coloquiais de futuro próximo devem casar."""
        cases = [
            "Logo mais vai chover?",
            "Vai chover mais tarde?",
            "Esta noite vai chover?",
            "Amanhã de manhã chove?",
        ]
        for q in cases:
            with self.subTest(q=q):
                self.assertIsNotNone(orch_mod.PV_REGEX.search(q), f"Esperado PV_REGEX match: {q!r}")

    def test_extended_colloquial_future(self):
        """Expressões coloquiais ampliadas devem casar com PV_REGEX."""
        cases = [
            "A noite vai chover?",
            "Vai fazer frio hoje?",
            "Vai fazer calor amanha?",
            "Vai ter chuva essa semana?",
            "Esse fim de semana chove?",
            "No final da semana, como fica?",
            "Vai dar pra sair a tarde?",
            "Daqui a pouco chove?",
        ]
        for q in cases:
            with self.subTest(q=q):
                self.assertIsNotNone(orch_mod.PV_REGEX.search(q), f"Esperado PV_REGEX match: {q!r}")


# ---------------------------------------------------------------------------
# 6. Regressão: chuva atual não deve casar com PV_REGEX (falso positivo)
# ---------------------------------------------------------------------------

class TestRainNowVsForecast(unittest.TestCase):
    """
    Regressão da rodada 1: perguntas sobre chuva atual (com "agora", "neste momento")
    devem ser RT, não PREVISAO.
    """

    def test_rain_now_triggers_rt_not_pv(self):
        """Sinal "agora" prevalece sobre "chuva" para classificar como tempo real."""
        texts_rt = [
            "Esta chovendo agora?",
            "Chuva neste momento?",
            "Ta chovendo no centro agora?",
        ]
        for t in texts_rt:
            with self.subTest(t=t):
                self.assertIsNotNone(orch_mod.RT_REGEX.search(t), f"Esperado RT_REGEX match: {t!r}")

    def test_future_rain_triggers_pv(self):
        """Perguntas sobre chuva futura devem casar com PV_REGEX."""
        texts_pv = [
            "Vai chover amanhã?",
            "Vai chover no domingo?",
            "Vai chover esta noite?",
            "Chuva para o feriado?",
        ]
        for t in texts_pv:
            with self.subTest(t=t):
                self.assertIsNotNone(orch_mod.PV_REGEX.search(t), f"Esperado PV_REGEX match: {t!r}")


class TestRegionalSummary(unittest.TestCase):

    def test_region_question_matches_summary(self):
        self.assertIsNotNone(
            orch_mod._PAT_SUMMARY.search("como esta a regiao"),
            "Pergunta geral sobre regiao deveria casar com resumo.",
        )

    def test_region_question_routes_to_summary(self):
        stations = [
            {"name": "A", "temp": 20.0, "humi": 80.0, "rain_day": 0.0},
            {"name": "B", "temp": 22.0, "humi": 70.0, "rain_day": 1.2},
        ]
        o = orch_mod.Orchestrator.__new__(orch_mod.Orchestrator)
        o.log_path = "/dev/null"
        o.stats = {"llm": 0, "fallback": 0}
        o.max_new_tokens = 64
        o.do_sample = False
        o.json_retries = 1

        with patch.object(orch_mod, "_fetch_all_stations_safe", return_value=stations), \
             patch.object(o, "_log"), \
             patch.object(o, "classify_intent", side_effect=AssertionError("LLM nao deveria ser chamado")):
            final, intent, _labels, engine = o.route("Como esta a regiao?", "user-1")

        self.assertEqual(intent, "ESTACOES_RT")
        # handler de resumo regional retorna "deterministic:summary"
        self.assertIn("deterministic:", engine)
        self.assertIn("regiao monitorada", orch_mod._strip_accents(final))
        self.assertNotIn("nao encontrei o bairro", orch_mod._strip_accents(final))


class TestAmbiguousLocationFallback(unittest.TestCase):

    def test_unknown_location_does_not_emit_bairro_error(self):
        stations = [{"name": "08 - SUDESTE - JARDIM DO LAGO"}]
        result = orch_mod._handle_ambiguous_location(
            "qual estacao tem mais chuva acumulada hoje",
            stations,
        )
        self.assertIsNone(result)

    def test_generic_station_signal_can_fall_through_to_slm(self):
        stations = [{"name": "08 - SUDESTE - JARDIM DO LAGO", "rain_day": 0.6}]
        with patch.object(orch_mod, "_fetch_all_stations_safe", return_value=stations):
            result = orch_mod.handle_analytical_query("Como esta a chuva em lugar inventado?")
        self.assertIsNone(result)


class TestRegionalRainQueries(unittest.TestCase):

    def test_zona_sul_rain_now_uses_filtered_stations(self):
        south = [
            {"name": "01 - SUL - RIO COMPRIDO", "rain_day": 0.0},
            {"name": "02 - SUL - CAPUAVA", "rain_day": 1.2},
        ]
        with patch.object(orch_mod, "_fetch_stations_for_query_safe", return_value=south):
            result = orch_mod.handle_analytical_query("Chuva agora na zona sul?")
        self.assertIsNotNone(result)
        answer, handler = result
        self.assertEqual(handler, "rain_bairros")
        self.assertIn("zona sul", orch_mod._strip_accents(answer))
        self.assertIn("CAPUAVA", answer)
        self.assertNotIn("NORTE", answer)

    def test_short_zona_sul_rain_question_is_current_rain(self):
        south = [
            {"name": "01 - SUL - RIO COMPRIDO", "rain_day": 0.0},
            {"name": "02 - SUL - CAPUAVA", "rain_day": 1.2},
        ]
        with patch.object(orch_mod, "_fetch_stations_for_query_safe", return_value=south):
            result = orch_mod.handle_analytical_query("Chuvas na zona sul?")
        self.assertIsNotNone(result)
        answer, handler = result
        self.assertEqual(handler, "rain_bairros")
        self.assertIn("zona sul", orch_mod._strip_accents(answer))


# ---------------------------------------------------------------------------
# 7. Handler _handle_umidade_atual — lógica de saída
# ---------------------------------------------------------------------------

class TestHandleUmidadeAtual(unittest.TestCase):

    def _make_stations(self):
        return [
            {"name": "Bairro A", "humi": 85.0},
            {"name": "Bairro B", "humi": 60.0},
            {"name": "Bairro C", "humi": 72.0},
        ]

    def test_returns_average_and_extremes(self):
        result = orch_mod._handle_umidade_atual(self._make_stations())
        self.assertIn("%", result)
        self.assertIn("Bairro A", result)  # mais úmida
        self.assertIn("Bairro B", result)  # mais seca

    def test_empty_stations(self):
        result = orch_mod._handle_umidade_atual([])
        self.assertIn("dispon", result.lower())

    def test_no_humi_field(self):
        result = orch_mod._handle_umidade_atual([{"name": "X", "temp": 20.0}])
        self.assertIn("dispon", result.lower())


# ---------------------------------------------------------------------------
# 8. Handler _handle_vento_atual — lógica de saída
# ---------------------------------------------------------------------------

class TestHandleVentoAtual(unittest.TestCase):

    def test_returns_wind_data(self):
        stations = [
            {"name": "A", "wind_speed": 15.0, "wind_gust": 25.0},
            {"name": "B", "wind_speed": 8.0,  "wind_gust": 12.0},
        ]
        result = orch_mod._handle_vento_atual(stations)
        self.assertIn("km/h", result)

    def test_empty_stations(self):
        result = orch_mod._handle_vento_atual([])
        self.assertIn("dispon", result.lower())


    def test_uses_real_plugfield_contract(self):
        stations = [
            {"name": "12 - OESTE - JARDIM DAS INDUSTRIAS", "wind": 0.0, "gust": 0.0},
            {"name": "28 - NORTE - BUQUIRINHA 2", "wind": 8.4, "gust": 13.2},
            {"name": "08 - SUDESTE - JARDIM DO LAGO", "wind": 2.0, "gust": 4.0},
        ]
        result = orch_mod._handle_vento_atual(stations)
        self.assertIn("28 - NORTE - BUQUIRINHA 2", result)
        self.assertIn("8.4 km/h", result)
        self.assertIn("13.2 km/h", result)


class TestRouteVentoAtual(unittest.TestCase):

    def test_onde_esta_ventando_uses_deterministic_handler(self):
        stations = [
            {"name": "12 - OESTE - JARDIM DAS INDUSTRIAS", "wind": 0.0, "gust": 0.0},
            {"name": "28 - NORTE - BUQUIRINHA 2", "wind": 8.4, "gust": 13.2},
        ]
        o = orch_mod.Orchestrator.__new__(orch_mod.Orchestrator)
        o.log_path = "/dev/null"
        o.stats = {"llm": 0, "fallback": 0}
        o.max_new_tokens = 64
        o.do_sample = False
        o.json_retries = 1

        with patch.object(orch_mod, "_fetch_all_stations_safe", return_value=stations), \
             patch.object(o, "_log"), \
             patch.object(o, "classify_intent", side_effect=AssertionError("LLM nao deveria ser chamado")):
            final, intent, _labels, engine = o.route("Onde esta ventando?", "user-1")

        self.assertEqual(intent, "ESTACOES_RT")
        self.assertEqual(engine, "deterministic:vento_atual")
        self.assertIn("28 - NORTE - BUQUIRINHA 2", final)

# ---------------------------------------------------------------------------
# 9. Handler _handle_pressao_atual — lógica de saída
# ---------------------------------------------------------------------------

class TestHandlePressaoAtual(unittest.TestCase):

    def test_returns_pressure_data(self):
        stations = [
            {"name": "A", "pres": 1013.0},
            {"name": "B", "pres": 1010.0},
            {"name": "C", "pres": 1015.0},
        ]
        result = orch_mod._handle_pressao_atual(stations)
        self.assertIn("hPa", result)

    def test_empty_stations(self):
        result = orch_mod._handle_pressao_atual([])
        self.assertIn("dispon", result.lower())


# ---------------------------------------------------------------------------
# 10. ORCH_KW_FALLBACK — fallback por keyword quando LLM lança exceção
# ---------------------------------------------------------------------------

class TestOrchKwFallback(unittest.TestCase):

    def setUp(self):
        # Garante que não tenta carregar modelo real
        os.environ["ORCH_SKIP_WARMUP"] = "1"
        os.environ["APP_ENV"] = "local"

    def _make_orch(self, kw_fallback=True):
        """Cria instância de Orchestrator com ORCH_KW_FALLBACK configurado."""
        o = orch_mod.Orchestrator.__new__(orch_mod.Orchestrator)
        o.log_path = "/dev/null"
        o.stats = {"llm": 0, "fallback": 0}
        o.max_new_tokens = 64
        o.do_sample = False
        o.json_retries = 1
        with patch.object(orch_mod, "ORCH_KW_FALLBACK", kw_fallback):
            return o, kw_fallback

    def test_kw_fallback_on_llm_exception_previsao(self):
        """Com ORCH_KW_FALLBACK=True e LLM levantando exceção, deve retornar PREVISAO via keyword."""
        o = orch_mod.Orchestrator.__new__(orch_mod.Orchestrator)
        o.stats = {"llm": 0, "fallback": 0}

        def _raise(*a, **kw):
            raise RuntimeError("modelo nao carregado")

        with patch.object(o, "_call_llm_json", side_effect=_raise), \
             patch.object(orch_mod, "ORCH_KW_FALLBACK", True), \
             patch.object(orch_mod, "ORCH_STRICT_LLM", False):
            intent, reason, source, _, _ = o.classify_intent("Vai chover amanhã?")

        self.assertEqual(intent, "PREVISAO")
        self.assertEqual(source, "llm_json_override")

    def test_kw_fallback_on_llm_exception_estacoes(self):
        """Com ORCH_KW_FALLBACK=True e LLM levantando exceção, deve retornar ESTACOES_RT."""
        o = orch_mod.Orchestrator.__new__(orch_mod.Orchestrator)
        o.stats = {"llm": 0, "fallback": 0}

        def _raise(*a, **kw):
            raise RuntimeError("401 gated model")

        with patch.object(o, "_call_llm_json", side_effect=_raise), \
             patch.object(orch_mod, "ORCH_KW_FALLBACK", True), \
             patch.object(orch_mod, "ORCH_STRICT_LLM", False):
            intent, reason, source, _, _ = o.classify_intent("Qual a umidade agora?")

        self.assertEqual(intent, "ESTACOES_RT")
        self.assertEqual(source, "llm_json_override")

    def test_no_kw_fallback_returns_generico_on_exception(self):
        """Com ORCH_KW_FALLBACK=False e exceção no LLM, retorna GENERICO (comportamento original)."""
        o = orch_mod.Orchestrator.__new__(orch_mod.Orchestrator)
        o.stats = {"llm": 0, "fallback": 0}

        def _raise(*a, **kw):
            raise RuntimeError("timeout")

        with patch.object(o, "_call_llm_json", side_effect=_raise), \
             patch.object(orch_mod, "ORCH_KW_FALLBACK", False), \
             patch.object(orch_mod, "ORCH_STRICT_LLM", False):
            intent, reason, source, _, _ = o.classify_intent("Uma pergunta qualquer")

        self.assertEqual(intent, "GENERICO")
        self.assertIn("llm_fail_generic", source)


# ---------------------------------------------------------------------------
# 11. Validação de entrada vazia (regressão Bug 2)
# ---------------------------------------------------------------------------

class TestEmptyInputRegression(unittest.TestCase):
    """
    Confirma que App.py já trata entrada vazia antes de chegar ao orquestrador.
    Regressão para garantir que o fix não seja revertido.
    """

    def setUp(self):
        from App import app
        self.client = app.test_client()

    def test_empty_string_returns_400(self):
        resp = self.client.post("/chat", json={"message": ""})
        self.assertEqual(resp.status_code, 400)
        payload = resp.get_json()
        self.assertIn("error", payload)

    def test_whitespace_only_returns_400(self):
        resp = self.client.post("/chat", json={"message": "   "})
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# 12. _PAT_CHUVA_RANKING e _handle_chuva_ranking (Bug NLU Tarefa 25)
# ---------------------------------------------------------------------------

class TestPatChuvRanking(unittest.TestCase):
    """Confirma que _PAT_CHUVA_RANKING reconhece perguntas de ranking de chuva."""

    def _match(self, q):
        from orchestrator_hf_json_final import _PAT_CHUVA_RANKING, _strip_accents
        return bool(_PAT_CHUVA_RANKING.search(_strip_accents(q)))

    def test_qual_estacao_tem_mais_chuva(self):
        self.assertTrue(self._match("Qual estação tem mais chuva acumulada hoje?"))

    def test_onde_choveu_mais(self):
        self.assertTrue(self._match("Onde choveu mais?"))

    def test_onde_esta_chovendo_mais(self):
        self.assertTrue(self._match("Onde está chovendo mais?"))

    def test_qual_local_mais_chuva(self):
        self.assertTrue(self._match("Qual local tem mais chuva?"))

    def test_maior_acumulado_chuva(self):
        self.assertTrue(self._match("Qual o maior acumulado de chuva hoje?"))

    def test_nao_captura_pergunta_generica(self):
        """Pergunta genérica de previsão não deve casar."""
        self.assertFalse(self._match("Vai chover hoje?"))

    def test_nao_captura_temperatura(self):
        self.assertFalse(self._match("Qual a temperatura agora?"))


class TestHandleChuvRanking(unittest.TestCase):
    """Testa _handle_chuva_ranking com payload do Plugfield."""

    def _stations(self):
        return [
            {"name": "01 - NORTE - TURVO",           "rain_day": 0.0},
            {"name": "08 - SUDESTE - JARDIM DO LAGO", "rain_day": 12.4},
            {"name": "14 - LESTE - NOVA DETROIT",     "rain_day": 5.2},
            {"name": "28 - NORTE - BUQUIRINHA 2",     "rain_day": 18.7},
        ]

    def test_destaca_estacao_com_mais_chuva(self):
        from orchestrator_hf_json_final import _handle_chuva_ranking
        resp = _handle_chuva_ranking(self._stations())
        self.assertIn("BUQUIRINHA 2", resp)
        self.assertIn("18.7", resp)

    def test_sem_chuva_retorna_mensagem_clara(self):
        from orchestrator_hf_json_final import _handle_chuva_ranking
        stations = [{"name": "A", "rain_day": 0.0}, {"name": "B", "rain_day": None}]
        resp = _handle_chuva_ranking(stations)
        self.assertIn("Nenhuma estacao", resp)

    def test_contagem_correta(self):
        from orchestrator_hf_json_final import _handle_chuva_ranking
        resp = _handle_chuva_ranking(self._stations())
        self.assertIn("3/4", resp)
