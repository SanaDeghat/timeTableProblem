class Class:
    def __init__(self, name, roomNumber, numOfStudents, block, semester):
        self.name = name
        self.roomNumber = roomNumber
        self.numOfStudents = numOfStudents
        self.block = block
        self.semester = semester

    def print(self):
        print(self.id, self.description, self.sections)

    def __repr__(self):
        return f"Class(id={self.id}, sections={self.sections})"