"""Generates and parses Proxmox-style task IDs (UPIDs).

A real UPID looks like:
    UPID:pve:00001B58:00002A3F:66927E10:qmcreate:100:root@pam:
    UPID:<node>:<pid(hex)>:<pstart(hex)>:<starttime(hex)>:<type>:<id>:<user>:
"""

import random
import time


def generate_upid(node, task_type, task_id="", user="root@pam"):
    pid = random.randint(1, 0xFFFFFF)
    pstart = random.randint(1, 0xFFFFFFFF)
    starttime = int(time.time())
    return "UPID:{node}:{pid:08X}:{pstart:08X}:{starttime:08X}:{task_type}:{task_id}:{user}:".format(
        node=node,
        pid=pid,
        pstart=pstart,
        starttime=starttime,
        task_type=task_type,
        task_id=task_id,
        user=user,
    )


def parse_upid(upid):
    parts = upid.split(":")
    if len(parts) < 9 or parts[0] != "UPID":
        raise ValueError("not a valid UPID: {}".format(upid))
    return {
        "node": parts[1],
        "pid": int(parts[2], 16),
        "pstart": int(parts[3], 16),
        "starttime": int(parts[4], 16),
        "type": parts[5],
        "id": parts[6],
        "user": parts[7],
    }
