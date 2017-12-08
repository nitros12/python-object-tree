from types import FunctionType
from typing import Dict, Union

from graphviz import Digraph

import analysis
from analysis import PythonClass, PythonMethod


def generate(name: str):
    result = analysis.build_for_module(name)
    graph = Digraph(name)

    for i in result:
        graph.node(i.name, i.info, shape="record")
        if isinstance(i, PythonClass):
            graph.edges((i.name, n) for n in i.parents)
    return graph
