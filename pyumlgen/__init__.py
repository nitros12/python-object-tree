#!/bin/env python
import argparse
import os
import sys
import inspect

from importlib import import_module

from graphviz import Digraph

from pyumlgen import analysis


def generate(*names: str) -> Digraph:
    """Generate uml graph for a module."""
    assert names
    graph = Digraph(names[0])

    modules = [import_module(n) for n in names]

    global_namespace = {}
    global_namespace.update(*map(vars, modules))

    graph.attr('edge', arrowhead="empty")
    for mod in modules:
        global_namespace.update(vars(mod))
        for i in analysis.build_for_module(mod, names=global_namespace):
            graph.node(i.name, i.info, shape="record")
            if isinstance(i, analysis.PythonClass):
                graph.edges((i.name, n) for n in i.parents)
    return graph


def main():
    print(os.getcwd())
    sys.path.append(os.getcwd())

    parser = argparse.ArgumentParser(description="Generate uml for python module.")
    parser.add_argument("modules", nargs="+", help="module path to use.")
    parser.add_argument("-o", "--out", nargs="?", type=argparse.FileType("w"), default=sys.stdout,
                        help="output to dump uml to.")
    parser.add_argument("-r", "--render", help="location to render to if provided.")

    args = parser.parse_args()

    graph = generate(*args.modules)

    args.out.write(graph.source)

    if args.render:
        fname, fmt = os.path.splitext(args.render)
        graph.format = fmt[1:]
        graph.render(fname, cleanup=True)

if __name__ == "__main__":
    main()
