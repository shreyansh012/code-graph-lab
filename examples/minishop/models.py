"""Things you can put in a basket."""


class Item:
    def __init__(self, name, price, qty=1):
        self.name = name
        self.price = price
        self.qty = qty

    def cost(self):
        return self.price * self.qty


class Digital(Item):
    def cost(self):
        # The call below is matched by method name only, so it stays "inferred".
        return round(super().cost() * 0.9, 2)


class Bundle:
    def __init__(self, items):
        self.items = items

    def cost(self):
        return sum(item.cost() for item in self.items)
