import os
from . import util
from .util import helper as h


class Base:
    def run(self):
        return self.step()

    def step(self):
        return 1


class Child(Base):
    def step(self):
        return h(2)


class Other:
    def step(self):
        return util.helper(3)


def drive(obj, items):
    obj.step()
    items.append(1)
    len(items)
    os.getcwd()
    items.mystery()
    return Child().run()


def outer():
    def inner():
        return util.helper(4)

    return inner()
