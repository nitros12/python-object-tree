#!/bin/env python
import argparse
import os
import sys

from graphviz import Digraph

from pyumlgen import analysis


def generate(name: str) -> Digraph:
    """Generate uml graph for a module."""
    result = analysis.build_for_module(name)
    graph = Digraph(name)

    graph.attr('edge', arrowhead="empty")

    for i in result:
        graph.node(i.name, i.info, shape="record")
        if isinstance(i, analysis.PythonClass):
            graph.edges((i.name, n) for n in i.parents)
    return graph


def main():
    parser = argparse.ArgumentParser(description="Generate uml for python module.")
    parser.add_argument("module", help="module path to use.")
    parser.add_argument("-o", "--out", nargs="?", type=argparse.FileType("w"), default=sys.stdout,
                        help="output to dump uml to.")
    parser.add_argument("-r", "--render", help="location to render to if provided.")

    args = parser.parse_args()

    graph = generate(args.module)

    args.out.write(graph.source)

    if args.render:
        fname, fmt = os.path.splitext(args.render)
        graph.format = fmt[1:]
        graph.render(fname, cleanup=True)

if __name__ == "__main__":
    main()
