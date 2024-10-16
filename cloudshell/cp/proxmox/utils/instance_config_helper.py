from cloudshell.cp.proxmox.constants import (
    INSTANCE_CFG_EXC_KEYS,
    INSTANCE_CFG_TAGS,
    MAC_REGEXP,
)


def convert_instance_config(response):
    parsed_response = {}
    for k, v in response.items():
        if "," in str(v) and k not in INSTANCE_CFG_EXC_KEYS:
            str_to_dict = {}
            for i in v.split(","):
                if "=" in i:
                    key, value = i.split("=")
                    if k.startswith("net"):
                        if MAC_REGEXP.search(value):
                            str_to_dict["type"] = key
                            str_to_dict["mac"] = value
                            continue
                        else:
                            str_to_dict[key] = value
                    else:
                        str_to_dict[key] = value
                elif ":" in i:
                    key, value = i.split(":")
                    str_to_dict[key] = value
            parsed_response[k] = str_to_dict
        elif k == INSTANCE_CFG_TAGS:
            parsed_response[k] = v.split(",")
        elif "=" in str(v) and k not in INSTANCE_CFG_EXC_KEYS:
            key, value = v.split("=")
            parsed_response[k] = {key: value}
        else:
            parsed_response[k] = v
    return parsed_response
