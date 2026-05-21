class Student:
    def __init__(self, id, gradDate):
        self.id = id
        self.gradDate = gradDate

    def print(self):
        print(self.id + " " + self.gradDate)
