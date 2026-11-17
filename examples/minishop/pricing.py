"""Price rules."""
import math

from .models import Bundle, Item


def with_tax(amount, rate):
    return round(amount * (1 + rate), 2)


def total_price(things, tax=0.2):
    subtotal = sum(thing.cost() for thing in things)
    return with_tax(math.floor(subtotal), tax)


def bundle_of(*items):
    return Bundle([Item(*parts) for parts in items])
