"""A text report for a basket."""
from . import pricing
from .models import Item


def format_line(thing):
    return "%s: %s" % (thing.name.upper(), thing.cost())


def render(things):
    lines = [format_line(t) for t in things]
    lines.append("total: %s" % pricing.total_price(things))
    return "\n".join(lines)


def main():
    print(render([Item("pen", 2, 3), Item("book", 10)]))


if __name__ == "__main__":
    main()
