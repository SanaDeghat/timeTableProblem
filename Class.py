class Class:
    def __init__(self, code, name, department, requestedPrimary, requestedAlt, capacity, section):
        self.code = code
        self.name = name
        self.department = department
        self.requestedPrimary = requestedPrimary
        self.requestedAlt = requestedAlt
        self.capacity = capacity
        self.section = section

    def print(self):
        print(self.code, self.name, self.department, self.requestedPrimary, self.requestedAlt, self.capacity, self.section)

    def getName(self):
        return self.name