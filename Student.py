class Student:
    def __init__(self, id, yog, requestedCourses=None, assignedCourses=None):
        self.id = int(id)
        self.yog = int(yog)
        self.requestedCourses = requestedCourses if requestedCourses is not None else []
        # 8 blocks; None means NULL/unassigned
        self.assignedCourses = assignedCourses if assignedCourses is not None else [None] * 8

    def print(self):
        print(self.id)
        print(self.yog)
        print(self.requestedCourses)
        print(self.assignedCourses)

    def __repr__(self):
        return f"Student(id={self.id}, yog={self.yog}, requested={len(self.requestedCourses)})"