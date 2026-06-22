"""
MT5 Bridge Server — รันบน Windows ที่เปิด MT5 อยู่
ทำให้ Linux server เชื่อมเข้า MT5 ได้ผ่าน network

ติดตั้ง: pip install mt5linux rpyc
รัน: python mt5_bridge_server.py
"""
from mt5linux import MetaTrader5
MetaTrader5(host='0.0.0.0', port=18812).serve()
