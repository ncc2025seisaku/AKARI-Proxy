import psutil

import requests

import time

def get_net_bytes():

    io = psutil.net_io_counters()

    return io.bytes_sent, io.bytes_recv

# before

sent_before, recv_before = get_net_bytes()

# 測りたいHTTPS通信

r = requests.get("https://www.ncc-net.ac.jp/")

_ = r.content  # ちゃんと読み切ることが重要

# after

sent_after, recv_after = get_net_bytes()

print("送信:", sent_after - sent_before, "bytes")

print("受信:", recv_after - recv_before, "bytes")

 