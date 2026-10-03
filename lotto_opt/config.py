import copy
import yaml


def load(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def set_path(cfg, dotted, value):
    """'rules.overlap.max_common' 같은 점 경로에 값을 넣은 복사본을 반환."""
    out = copy.deepcopy(cfg)
    node = out
    *parents, last = dotted.split(".")
    for key in parents:
        node = node.setdefault(key, {})
    node[last] = value
    return out
