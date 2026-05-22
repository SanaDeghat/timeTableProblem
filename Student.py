class Student:
    def __init__(self, id, yog, requestedCourses, assignedCourses):
        self.id = id
        self.yog = yog
        self.requestedCourses = requestedCourses
        self.assignedCourses = assignedCourses

    def print(self):
        print(self.id)
        print(self.yog)
        print(self.requestedCourses)
        print(self.assignedCourses)

    def createTimetable():
        print("")
