#!/bin/bash
source ~/.dca_config
cd ~/dca-optimizer
source venv/bin/activate
python3 dca_optimizer.py >> ~/dca-optimizer/dca.log 2>&1
