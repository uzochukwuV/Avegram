#!/bin/bash
cd /home/workspace/Avegram
export $(cat /home/workspace/Avegram/.env | xargs)
exec python3 signal_telegram.py
