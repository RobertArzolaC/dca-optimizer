#!/bin/bash
source ~/.dca_sell_config
cd ~/dca-optimizer
source venv/bin/activate
python3 dca_sell.py >> ~/dca-optimizer/sell.log 2>&1
