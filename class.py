class Class:
    def __init__(self, name, roomNumber, numOfStudents, block, semester):
        self.name = name
        self.roomNumber = roomNumber
        self.numOfStudents = numOfStudents
        self.block = block
        self.semester = semester

    def print(self):
        print(self.name, self.roomNumber, self.numOfStudents)
