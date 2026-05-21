class Student:
    def __init__(self, id, yog, courses):
        self.id = id
        self.yog = yog
        self.courses = courses

    def print(self):
        print(self.id)
        print(self.yog)
        print(self.courses)
