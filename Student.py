class Student:
    def __init__(self, id, yog, requestedCourses=None, assignedCourses=None, alternateCourses=None, assignedSections=None):
        self.id = int(id)
        self.yog = int(yog)
        self.requestedCourses = requestedCourses if requestedCourses is not None else []
        self.alternateCourses = alternateCourses if alternateCourses is not None else []
        self.assignedCourses = assignedCourses if assignedCourses is not None else [None] * 8
        self.assignedSections = assignedSections if assignedSections is not None else [None] * 8

    def print(self):
        print(self.id)
        print(self.yog)
        print(self.requestedCourses)
        print(self.alternateCourses)
        print(self.assignedCourses)
        print(self.assignedSections)

    def __repr__(self):
        return (
            f"Student(id={self.id}, yog={self.yog}, requested={len(self.requestedCourses)}, "
            f"alternates={len(self.alternateCourses)})"
        )