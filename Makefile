# ============================================================================
# DCA OPTIMIZER - Makefile con Ayuda Automática
# ============================================================================

PROJECT_DIR := $(HOME)/dca-optimizer
VENV := $(PROJECT_DIR)/venv/bin/activate
LOG_FILE := $(PROJECT_DIR)/dca.log
DB_FILE := $(PROJECT_DIR)/dca_history.db

# ----------------------------------------------------------------------------
# HELP AUTO-GENERADO
# ----------------------------------------------------------------------------
# Cualquier comando que tenga un comentario con "##" aparecerá en make help

help: ## Muestra todos los comandos disponibles
	@echo ""
	@echo "📘 Comandos disponibles para DCA Optimizer:"
	@echo "-------------------------------------------"
	@grep -E '^[a-zA-Z_-]+:.*?##' Makefile | sed 's/:.*##/: /' | column -t -s ':'
	@echo ""

# ============================================================================
# 1. LOGS
# ============================================================================

logs: ## Ver logs en tiempo real
	tail -f $(LOG_FILE)

# ============================================================================
# 2. EJECUCIÓN MANUAL
# ============================================================================

run: ## Ejecutar el bot manualmente
	$(PROJECT_DIR)/run_dca.sh

# ============================================================================
# 3. SQLITE: HISTORIAL DE SEÑALES
# ============================================================================

history: ## Mostrar últimas señales desde SQLite
	sqlite3 $(DB_FILE) "SELECT * FROM signals ORDER BY timestamp DESC LIMIT 10;"

# ============================================================================
# 4. EXPORT PARA BACKTESTING
# ============================================================================

export: ## Generar dataset para backtesting
	cd $(PROJECT_DIR) && \
		. $(VENV) && \
		python3 dca_backtest.py export

# ============================================================================
# 5. BACKTEST
# ============================================================================

backtest: ## Correr backtest de 365 días
	cd $(PROJECT_DIR) && \
		. $(VENV) && \
		python3 dca_backtest.py backtest 365

backtest-custom: ## Correr backtest con días personalizados (make backtest-custom days=180)
	cd $(PROJECT_DIR) && \
		. $(VENV) && \
		python3 dca_backtest.py backtest $(days)

# ============================================================================
# 6. MONITOREO DEL CRON
# ============================================================================

cron: ## Revisar últimas ejecuciones del CRON
	grep CRON /var/log/syslog | tail -20

last-run: ## Ver última ejecución registrada y últimos logs
	ls -la $(DB_FILE)
	tail -50 $(LOG_FILE)

# ============================================================================
# 7. DCA SELL OPTIMIZER
# ============================================================================

SELL_PROJECT := $(HOME)/dca-optimizer
SELL_LOG := $(SELL_PROJECT)/sell.log
SELL_DB := $(SELL_PROJECT)/dca_sell_history.db
SELL_VENV := $(SELL_PROJECT)/venv/bin/activate

sell-logs: ## Ver logs del DCA Sell en tiempo real
	@tail -f $(SELL_LOG)

sell-position: ## Ver estado actual de la posición
	cd $(SELL_PROJECT) && \
		. $(SELL_VENV) && \
		python3 dca_sell_utils.py position

sell-signals: ## Ver últimas señales de venta (make sell-signals n=20)
	cd $(SELL_PROJECT) && \
		. $(SELL_VENV) && \
		python3 dca_sell_utils.py signals $(n)

sell-register: ## Registrar venta manual (make sell-register amount=0.05 price=95000)
	cd $(SELL_PROJECT) && \
		. $(SELL_VENV) && \
		python3 dca_sell_utils.py sell $(amount) $(price)

sell-performance: ## Ver rendimiento del bot de ventas
	cd $(SELL_PROJECT) && \
		. $(SELL_VENV) && \
		python3 dca_sell_utils.py performance

sell-export: ## Exportar dataset de ventas
	cd $(SELL_PROJECT) && \
		. $(SELL_VENV) && \
		python3 dca_sell_utils.py export

sell-db: ## Ver últimas señales directamente desde SQLite
	sqlite3 $(SELL_DB) "SELECT * FROM sell_signals ORDER BY timestamp DESC LIMIT 5;"

# ============================================================================
# 8. SUMMARY
# ============================================================================

summary: ## Resumen de operaciones realizadas
	cd $(SELL_PROJECT) && \
		. $(SELL_VENV) && \
		python3 dca_dashboard.py

