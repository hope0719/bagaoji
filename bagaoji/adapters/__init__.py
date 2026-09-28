"""适配器注册表。

内置适配器 + 用户私有适配器（`~/.bagaoji/adapters/*.py`）统一注册。

私有适配器模块里可以定义：

    ADAPTER = MyAdapter()            # 单个
    ADAPTERS = [A(), B()]            # 多个

也可以是 `Adapter` 的子类（会自动实例化）。这样就能在不修改本项目代码的前提下
把自己那套来源站实现留在本地。
"""

from __future__ import annotations

import importlib.util
import os
import sys

from .base import Adapter
from .xhs import XhsAdapter

__all__ = ["Adapter", "registry", "all_adapters", "get_adapter",
           "load_user_adapters", "USER_ADAPTER_DIR"]

#: 用户私有适配器目录
USER_ADAPTER_DIR = os.path.expanduser("~/.bagaoji/adapters")

_REGISTRY = {}


def registry():
    return _REGISTRY


def all_adapters():
    """已注册适配器列表（按注册顺序）。"""
    return list(_REGISTRY.values())


def get_adapter(name):
    return _REGISTRY.get((name or "").lower())


def register(adapter):
    """注册一个适配器实例（或类）。"""
    if isinstance(adapter, type) and issubclass(adapter, Adapter):
        adapter = adapter()
    if not isinstance(adapter, Adapter) or not adapter.name:
        return None
    _REGISTRY[adapter.name.lower()] = adapter
    return adapter


def load_user_adapters(directory=None, quiet=True):
    """加载 `~/.bagaoji/adapters/*.py` 里的私有适配器。

    返回 `(loaded_names, errors)`。
    """
    directory = directory or USER_ADAPTER_DIR
    loaded, errors = [], []
    if not os.path.isdir(directory):
        return loaded, errors
    if directory not in sys.path:
        sys.path.insert(0, directory)
    for fn in sorted(os.listdir(directory)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        path = os.path.join(directory, fn)
        modname = "bagaoji_user_" + os.path.splitext(fn)[0]
        try:
            spec = importlib.util.spec_from_file_location(modname, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[modname] = mod
            spec.loader.exec_module(mod)
        except Exception as e:
            errors.append("%s: %s" % (fn, e))
            continue
        found = []
        for attr in ("ADAPTER", "ADAPTERS", "adapter", "adapters"):
            v = getattr(mod, attr, None)
            if v is None:
                continue
            found += list(v) if isinstance(v, (list, tuple)) else [v]
        if not found:
            found = [v for v in vars(mod).values()
                     if isinstance(v, type) and issubclass(v, Adapter) and v is not Adapter]
        for a in found:
            if register(a) is not None:
                loaded.append(getattr(a, "name", "?"))
    if not quiet and errors:
        for e in errors:
            print("[bagaoji] 私有适配器加载失败 %s" % e, file=sys.stderr)
    return loaded, errors


# ---------------------------------------------------------------- 内置

register(XhsAdapter())
load_user_adapters()
