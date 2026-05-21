class Class:
    def __init__(self, name, roomNumber, numOfStudents, block, sem):
        self.name = name
        self.roomNumber = roomNumber
        self.numOfStudents = numOfStudents
        self.block = block
        self.sem = sem

    def print(self):
        print(self.name, self.roomNumber, self.numOfStudents, self.block, self.sem)
