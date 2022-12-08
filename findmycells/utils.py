# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/00_utils.ipynb.

# %% auto 0
__all__ = ['listdir_nohidden']

# %% ../nbs/00_utils.ipynb 2
from typing import List
from pathlib import Path

# %% ../nbs/00_utils.ipynb 4
def listdir_nohidden(path: Path) -> List:
    return [f for f in os.listdir(path) if f.startswith('.') == False]
