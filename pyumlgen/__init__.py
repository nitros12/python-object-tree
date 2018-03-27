#!/bin/env python
import argparse
import os
import sys
import inspect

from importlib import import_module
from plantuml_dsl import umlclass

from pyumlgen import analysis


def generate(*names: str) -> umlclass.ClassDiagram:
    """Generate uml graph for a module."""
    assert names
    graph = umlclass.ClassDiagram()

    modules = [import_module(n) for n in names]

    global_namespace = {}
    global_namespace.update(*map(vars, modules))

    for mod in modules:
        global_namespace.update(vars(mod))
        for i in analysis.build_for_module(mod, names=global_namespace):
            if isinstance(i, analysis.PythonMethod):
                o = umlclass.Object(str(i))
            elif isinstance(i, analysis.PythonClass):
                o = umlclass.Class(i.name, i.methods, i.attrs)
                graph.add_object(o)
                for n in i.parents:
                    l = umlclass.Link(i.name, n, left_ending=umlclass.ArrowType.extends)
                    graph.add_link(l)
    return graph


def main():
    sys.path.append(os.getcwd())

    parser = argparse.ArgumentParser(description="Generate uml for python module.")
    parser.add_argument("modules", nargs="+", help="module path to use.")
    parser.add_argument("-o", "--out", nargs="?", type=argparse.FileType("w"), default=sys.stdout,
                        help="output to dump uml to.")

    args = parser.parse_args()
    graph = generate(*args.modules)
    args.out.write("@startuml\n")
    args.out.write(graph.render())
    args.out.write("\n@enduml")

if __name__ == "__main__":
    main()
