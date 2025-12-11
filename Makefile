# ============================================================================
# DCA OPTIMIZER - Makefile Refactorizado
# ============================================================================

PROJECT_DIR := $(HOME)/dca-optimizer
VENV := $(PROJECT_DIR)/venv/bin/activate
PYTHON := cd $(PROJECT_DIR) && . $(VENV) && python3

.PHONY: help buy sell logs dashboard backtest install test

# ----------------------------------------------------------------------------
# HELP
# ----------------------------------------------------------------------------

help: ## Muestra todos los comandos disponibles
	@echo ""
	@echo "📘 DCA Optimizer - Comandos disponibles:"
	@echo "========================================="
	@grep -E '^[a-zA-Z_-]+:.*?##' Makefile | sed 's/:.*##/: /' | column -t -s ':'
	@echo ""

# ============================================================================
# INSTALACIÓN
# ============================================================================

install: ## Instalar dependencias y crear entorno virtual
	cd $(PROJECT_DIR) && python3 -m venv venv
	. $(VENV) && pip install --upgrade pip
	. $(VENV) && pip install pandas requests

# ============================================================================
# COMPRA (BUY)
# ============================================================================

buy: ## Ejecutar bot de compra
	$(PYTHON) dca_buy.py

buy-dry: ## Ejecutar bot de compra (sin notificación)
	$(PYTHON) dca_buy.py --dry-run

buy-history: ## Ver historial de señales de compra
	$(PYTHON) dca_utils.py buy history 20

# ============================================================================
# VENTA (SELL)
# ============================================================================

sell: ## Ejecutar bot de venta
	$(PYTHON) dca_sell.py

sell-dry: ## Ejecutar bot de venta (sin notificación)
	$(PYTHON) dca_sell.py --dry-run

sell-force: ## Ejecutar bot de venta (forzar notificación)
	$(PYTHON) dca_sell.py --force

sell-position: ## Ver estado de la posición
	$(PYTHON) dca_utils.py sell position

sell-signals: ## Ver últimas señales de venta
	$(PYTHON) dca_utils.py sell signals 20

sell-record: ## Registrar venta manual (make sell-record btc=0.05 price=95000)
	$(PYTHON) dca_utils.py sell record $(btc) $(price)

# ============================================================================
# DASHBOARD Y MONITOREO
# ============================================================================

dashboard: ## Ver dashboard combinado
	$(PYTHON) dca_utils.py dashboard

logs: ## Ver logs en tiempo real
	tail -f $(PROJECT_DIR)/dca.log

logs-sell: ## Ver logs de sell en tiempo real
	tail -f $(PROJECT_DIR)/sell.log

# ============================================================================
# CRON Y SISTEMA
# ============================================================================

cron: ## Revisar últimas ejecuciones del CRON
	grep -i "dca\|CRON" /var/log/syslog 2>/dev/null | tail -20 || \
	grep -i "dca\|CRON" /var/log/cron.log 2>/dev/null | tail -20 || \
	echo "No se encontraron logs de cron"

cron-install: ## Instalar crontabs recomendados
	@echo "Agregar estas líneas a tu crontab (crontab -e):"
	@echo ""
	@echo "# DCA Buy - Domingo 03:00 UTC"
	@echo "0 3 * * 0 cd $(PROJECT_DIR) && . venv/bin/activate && python dca_buy.py >> dca.log 2>&1"
	@echo ""
	@echo "# DCA Sell - Cada 4 horas"
	@echo "0 */4 * * * cd $(PROJECT_DIR) && . venv/bin/activate && python dca_sell.py >> sell.log 2>&1"

# ============================================================================
# BACKTEST
# ============================================================================

backtest: ## Correr backtest de 365 días
	$(PYTHON) -c "from dca_backtest import *; \
		df = fetch_historical_data(365); \
		results = backtest_strategy(df); \
		analyze_backtest(results)"

backtest-timing: ## Analizar patrones de timing
	$(PYTHON) -c "from dca_backtest import *; \
		df = fetch_historical_data(180); \
		analyze_day_of_week_patterns(df)"

# ============================================================================
# DATABASE
# ============================================================================

db-buy: ## Ver últimas señales de compra desde SQLite
	sqlite3 $(PROJECT_DIR)/dca.db \
		"SELECT timestamp, signal_type, price, suggested_amount FROM signals ORDER BY timestamp DESC LIMIT 10;"

db-sell: ## Ver últimas señales de venta desde SQLite
	sqlite3 $(PROJECT_DIR)/dca.db \
		"SELECT timestamp, signal_type, risk_score, sell_percentage FROM sell_signals ORDER BY timestamp DESC LIMIT 10;"

db-position: ## Ver posición desde SQLite
	sqlite3 $(PROJECT_DIR)/dca.db \
		"SELECT total_btc, sold_btc, (total_btc - sold_btc) as remaining, cost_basis FROM position;"

# ============================================================================
# TESTING
# ============================================================================

test: ## Ejecutar tests
	$(PYTHON) -m pytest tests/ -v

test-notify: ## Probar notificación de Telegram
	$(PYTHON) -c "from core.notifications import notifier; \
		notifier.notify_custom('🧪 Test de notificación DCA Optimizer')"

# ============================================================================
# LIMPIEZA
# ============================================================================

clean-logs: ## Limpiar logs antiguos (>30 días)
	find $(PROJECT_DIR) -name "*.log" -mtime +30 -delete
	@echo "Logs antiguos eliminados"

clean-cache: ## Limpiar cache de Python
	find $(PROJECT_DIR) -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find $(PROJECT_DIR) -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "Cache limpiado"